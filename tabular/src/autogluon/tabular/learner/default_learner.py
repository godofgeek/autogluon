import copy
import logging
import math
import time

import pandas as pd
from pandas import DataFrame

from .abstract_learner import AbstractLearner
from ..constants import BINARY, MULTICLASS, REGRESSION
from ..trainer.auto_trainer import AutoTrainer
from autogluon.core.utils.utils import augment_rare_classes
from ..data.cleaner import Cleaner
from ..data.label_cleaner import LabelCleaner

logger = logging.getLogger(__name__)


# TODO: Add functionality for advanced feature generators such as gl_code_matrix_generator (inter-row dependencies, apply to train differently than test, etc., can only run after train/test split, rerun for each cv fold)
# TODO: - Differentiate between advanced generators that require fit (stateful, gl_code_matrix) and those that do not (bucket label averaging in SCOT GC 2019)
# TODO: - Those that do not could be added to preprocessing function of model, but would then have to be recomputed on each model.
# TODO: Add cv / OOF generator option, so that AutoGluon can be used as a base model in an ensemble stacker
# Learner encompasses full problem, loading initial data, feature generation, model training, model prediction
class DefaultLearner(AbstractLearner):
    def __init__(self, trainer_type=AutoTrainer, **kwargs):
        super().__init__(**kwargs)
        self.trainer_type = trainer_type

        self._time_fit_total = None
        self._time_fit_preprocessing = None
        self._time_fit_training = None
        self._time_limit = None

    # TODO: Add trainer_kwargs to simplify parameter count and extensibility

    def _fit(self, X: DataFrame, X_val: DataFrame = None, X_unlabeled: DataFrame = None, scheduler_options=None, hyperparameter_tune=False,
            feature_prune=False, holdout_frac=0.1, num_bagging_folds=0, num_bagging_sets=1, stack_ensemble_levels=0,
            hyperparameters=None, ag_args_fit=None, excluded_model_types=None, time_limit=None, save_data=False, save_bagged_folds=True, verbosity=2):
        """ Arguments:
                X (DataFrame): training data
                X_val (DataFrame): data used for hyperparameter tuning. Note: final model may be trained using this data as well as training data
                X_unlabeled (DataFrame): data used for pretraining a model. This is same data format as X, without label-column. This data is used for semi-supervised learning.
                hyperparameter_tune (bool): whether to tune hyperparameters or simply use default values
                feature_prune (bool): whether to perform feature selection
                scheduler_options (tuple: (search_strategy, dict): Options for scheduler
                holdout_frac (float): Fraction of data to hold out for evaluating validation performance (ignored if X_val != None, ignored if kfolds != 0)
                num_bagging_folds (int): kfolds used for bagging of models, roughly increases model training time by a factor of k (0: disabled)
                num_bagging_sets (int): number of repeats of kfold bagging to perform (values must be >= 1),
                    total number of models trained during bagging = num_bagging_folds * num_bagging_sets
                stack_ensemble_levels : (int) Number of stacking levels to use in ensemble stacking. Roughly increases model training time by factor of stack_levels+1 (0: disabled)
                    Default is 0 (disabled). Use values between 1-3 to improve model quality.
                    Ignored unless kfolds is also set >= 2
                hyperparameters (dict): keys = hyperparameters + search-spaces for each type of model we should train.
        """
        if hyperparameters is None:
            hyperparameters = {'NN': {}, 'GBM': {}}
        # TODO: if provided, feature_types in X, X_val are ignored right now, need to pass to Learner/trainer and update this documentation.
        self._time_limit = time_limit
        if time_limit:
            logger.log(20, f'Beginning AutoGluon training ... Time limit = {time_limit}s')
        else:
            logger.log(20, 'Beginning AutoGluon training ...')
        logger.log(20, f'AutoGluon will save models to {self.path}')
        logger.log(20, f'AutoGluon Version:  {self.version}')
        logger.log(20, f'Train Data Rows:    {len(X)}')
        logger.log(20, f'Train Data Columns: {len([column for column in X.columns if column != self.label])}')
        if X_val is not None:
            logger.log(20, f'Tuning Data Rows:    {len(X_val)}')
            logger.log(20, f'Tuning Data Columns: {len([column for column in X_val.columns if column != self.label])}')
        time_preprocessing_start = time.time()
        logger.log(20, 'Preprocessing data ...')
        X, y, X_val, y_val, X_unlabeled, holdout_frac, num_bagging_folds = self.general_data_processing(X, X_val, X_unlabeled, holdout_frac, num_bagging_folds)
        time_preprocessing_end = time.time()
        self._time_fit_preprocessing = time_preprocessing_end - time_preprocessing_start
        logger.log(20, f'Data preprocessing and feature engineering runtime = {round(self._time_fit_preprocessing, 2)}s ...')
        if time_limit:
            time_limit_trainer = time_limit - self._time_fit_preprocessing
        else:
            time_limit_trainer = None

        trainer = self.trainer_type(
            path=self.model_context,
            problem_type=self.label_cleaner.problem_type_transform,
            eval_metric=self.eval_metric,
            stopping_metric=self.stopping_metric,
            num_classes=self.label_cleaner.num_classes,
            feature_metadata=self.feature_generator.feature_metadata,
            low_memory=True,
            k_fold=num_bagging_folds,  # TODO: Consider moving to fit call
            n_repeats=num_bagging_sets,  # TODO: Consider moving to fit call
            stack_ensemble_levels=stack_ensemble_levels,  # TODO: Consider moving to fit call
            scheduler_options=scheduler_options,
            save_data=save_data,
            save_bagged_folds=save_bagged_folds,
            random_seed=self.random_seed,
            verbosity=verbosity
        )

        self.trainer_path = trainer.path
        if self.eval_metric is None:
            self.eval_metric = trainer.eval_metric
        if self.stopping_metric is None:
            self.stopping_metric = trainer.stopping_metric

        self.save()
        trainer.train(X, y, X_val, y_val, X_unlabeled=X_unlabeled, hyperparameter_tune=hyperparameter_tune, feature_prune=feature_prune, holdout_frac=holdout_frac,
                      hyperparameters=hyperparameters, ag_args_fit=ag_args_fit, excluded_model_types=excluded_model_types, time_limit=time_limit_trainer)
        self.save_trainer(trainer=trainer)
        time_end = time.time()
        self._time_fit_training = time_end - time_preprocessing_end
        self._time_fit_total = time_end - time_preprocessing_start
        logger.log(20, f'AutoGluon training complete, total runtime = {round(self._time_fit_total, 2)}s ...')

    def general_data_processing(self, X: DataFrame, X_val: DataFrame, X_unlabeled: DataFrame, holdout_frac: float, num_bagging_folds: int):
        """ General data processing steps used for all models. """
        X = copy.deepcopy(X)

        # TODO: We should probably uncomment the below lines, NaN label should be treated as just another value in multiclass classification -> We will have to remove missing, compute problem type, and add back missing if multiclass
        # if self.problem_type == MULTICLASS:
        #     X[self.label] = X[self.label].fillna('')

        # Remove all examples with missing labels from this dataset:
        missinglabel_inds = [index for index, x in X[self.label].isna().iteritems() if x]
        if len(missinglabel_inds) > 0:
            logger.warning(f"Warning: Ignoring {len(missinglabel_inds)} (out of {len(X)}) training examples for which the label value in column '{self.label}' is missing")
            X = X.drop(missinglabel_inds, axis=0)

        if self.problem_type is None:
            self.problem_type = self.infer_problem_type(X[self.label])

        if X_val is not None and self.label in X_val.columns:
            # TODO: This is not an ideal solution, instead check if bagging and X_val exists with label, then merge them prior to entering general data processing.
            #  This solution should handle virtually all cases correctly, only downside is it might cut more classes than it needs to.
            self.threshold, holdout_frac, num_bagging_folds = self.adjust_threshold_if_necessary(X[self.label], threshold=self.threshold, holdout_frac=1, num_bagging_folds=num_bagging_folds)
        else:
            self.threshold, holdout_frac, num_bagging_folds = self.adjust_threshold_if_necessary(X[self.label], threshold=self.threshold, holdout_frac=holdout_frac, num_bagging_folds=num_bagging_folds)

        if (self.eval_metric is not None) and (self.eval_metric.name in ['log_loss', 'pac_score']) and (self.problem_type == MULTICLASS):
            X = augment_rare_classes(X, self.label, self.threshold)

        # Gets labels prior to removal of infrequent classes
        y_uncleaned = X[self.label].copy()

        self.cleaner = Cleaner.construct(problem_type=self.problem_type, label=self.label, threshold=self.threshold)
        # TODO: What if all classes in X are low frequency in multiclass? Currently we would crash. Not certain how many problems actually have this property
        X = self.cleaner.fit_transform(X)  # TODO: Consider merging cleaner into label_cleaner
        X, y = self.extract_label(X)
        self.label_cleaner = LabelCleaner.construct(problem_type=self.problem_type, y=y, y_uncleaned=y_uncleaned)
        y = self.label_cleaner.transform(y)

        if self.label_cleaner.num_classes is not None and self.problem_type != BINARY:
            logger.log(20, f'Train Data Class Count: {self.label_cleaner.num_classes}')

        if X_val is not None and self.label in X_val.columns:
            X_val = self.cleaner.transform(X_val)
            if len(X_val) == 0:
                logger.warning('All X_val data contained low frequency classes, ignoring X_val and generating from subset of X')
                X_val = None
                y_val = None
            else:
                X_val, y_val = self.extract_label(X_val)
                y_val = self.label_cleaner.transform(y_val)
        else:
            y_val = None

        if self.id_columns:
            logger.log(20, f'Dropping ID columns: {self.id_columns}')
            X = X.drop(self.id_columns, axis=1, errors='ignore')
            if X_val is not None:
                X_val = X_val.drop(self.id_columns, axis=1, errors='ignore')

        # TODO: Move this up to top of data before removing data, this way our feature generator is better
        logger.log(20, f'Using Feature Generators to preprocess the data ...')
        if X_val is not None:
            # Do this if working with SKLearn models, otherwise categorical features may perform very badly on the test set
            logger.log(15, 'Performing general data preprocessing with merged train & validation data, so validation performance may not accurately reflect performance on new test data')
            X_super = pd.concat([X, X_val, X_unlabeled], ignore_index=True)
            if self.feature_generator.is_fit():
                logger.log(20, f'{self.feature_generator.__class__.__name__} is already fit, so the training data will be processed via .transform() instead of .fit_transform().')
                X_super = self.feature_generator.transform(X_super)
                self.feature_generator.print_feature_metadata_info()
            else:
                X_super = self.feature_generator.fit_transform(X_super)
            X = X_super.head(len(X)).set_index(X.index)

            X_val = X_super.head(len(X)+len(X_val)).tail(len(X_val)).set_index(X_val.index)

            if X_unlabeled is not None:
                X_unlabeled = X_super.tail(len(X_unlabeled)).set_index(X_unlabeled.index)
            del X_super
        else:
            X_super = pd.concat([X, X_unlabeled], ignore_index=True)
            if self.feature_generator.is_fit():
                logger.log(20, f'{self.feature_generator.__class__.__name__} is already fit, so the training data will be processed via .transform() instead of .fit_transform().')
                X_super = self.feature_generator.transform(X_super)
                self.feature_generator.print_feature_metadata_info()
            else:
                X_super = self.feature_generator.fit_transform(X_super)

            X = X_super.head(len(X)).set_index(X.index)
            if X_unlabeled is not None:
                X_unlabeled = X_super.tail(len(X_unlabeled)).set_index(X_unlabeled.index)
            del X_super


        return X, y, X_val, y_val, X_unlabeled, holdout_frac, num_bagging_folds

    def adjust_threshold_if_necessary(self, y, threshold, holdout_frac, num_bagging_folds):
        new_threshold, new_holdout_frac, new_num_bagging_folds = self._adjust_threshold_if_necessary(y, threshold, holdout_frac, num_bagging_folds)
        if new_threshold != threshold:
            if new_threshold < threshold:
                logger.warning(f'Warning: Updated label_count_threshold from {threshold} to {new_threshold} to avoid cutting too many classes.')
        if new_holdout_frac != holdout_frac:
            if new_holdout_frac > holdout_frac:
                logger.warning(f'Warning: Updated holdout_frac from {holdout_frac} to {new_holdout_frac} to avoid cutting too many classes.')
        if new_num_bagging_folds != num_bagging_folds:
            logger.warning(f'Warning: Updated num_bagging_folds from {num_bagging_folds} to {new_num_bagging_folds} to avoid cutting too many classes.')
        return new_threshold, new_holdout_frac, new_num_bagging_folds

    def _adjust_threshold_if_necessary(self, y, threshold, holdout_frac, num_bagging_folds):
        new_threshold = threshold
        if self.problem_type == REGRESSION:
            num_rows = len(y)
            holdout_frac = max(holdout_frac, 1 / num_rows + 0.001)
            num_bagging_folds = min(num_bagging_folds, num_rows)
            return new_threshold, holdout_frac, num_bagging_folds

        if num_bagging_folds < 2:
            minimum_safe_threshold = math.ceil(1 / holdout_frac)
        else:
            minimum_safe_threshold = num_bagging_folds

        if minimum_safe_threshold > new_threshold:
            new_threshold = minimum_safe_threshold

        class_counts = y.value_counts()
        total_rows = class_counts.sum()
        minimum_percent_to_keep = 0.975
        minimum_rows_to_keep = math.ceil(total_rows * minimum_percent_to_keep)
        minimum_class_to_keep = 2

        num_classes = len(class_counts)
        class_counts_valid = class_counts[class_counts >= new_threshold]
        num_rows_valid = class_counts_valid.sum()
        num_classes_valid = len(class_counts_valid)

        if (num_rows_valid >= minimum_rows_to_keep) and (num_classes_valid >= minimum_class_to_keep):
            return new_threshold, holdout_frac, num_bagging_folds

        num_classes_valid = 0
        num_rows_valid = 0
        new_threshold = None
        for i in range(num_classes):
            num_classes_valid += 1
            num_rows_valid += class_counts.iloc[i]
            new_threshold = class_counts.iloc[i]
            if (num_rows_valid >= minimum_rows_to_keep) and (num_classes_valid >= minimum_class_to_keep):
                break

        if new_threshold == 1:
            new_threshold = 2  # threshold=1 is invalid, can't perform any train/val split in this case.
        self.threshold = new_threshold

        if new_threshold < minimum_safe_threshold:
            if num_bagging_folds >= 2:
                if num_bagging_folds > new_threshold:
                    num_bagging_folds = new_threshold
            elif math.ceil(1 / holdout_frac) > new_threshold:
                holdout_frac = 1 / new_threshold + 0.001

        return new_threshold, holdout_frac, num_bagging_folds

    def get_info(self, include_model_info=False, **kwargs):
        learner_info = super().get_info(**kwargs)
        trainer = self.load_trainer()
        trainer_info = trainer.get_info(include_model_info=include_model_info)
        learner_info.update({
            'time_fit_preprocessing': self._time_fit_preprocessing,
            'time_fit_training': self._time_fit_training,
            'time_fit_total': self._time_fit_total,
            'time_limit': self._time_limit,
        })

        learner_info.update(trainer_info)
        return learner_info
