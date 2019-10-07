from collections import OrderedDict 
import datetime, json
import pandas as pd
from pandas import DataFrame, Series
from sklearn.metrics import accuracy_score, balanced_accuracy_score, matthews_corrcoef, f1_score, classification_report # , roc_curve, auc
from sklearn.metrics import mean_absolute_error, explained_variance_score, r2_score, mean_squared_error, median_absolute_error, max_error
from numpy import corrcoef

from tabular.ml.constants import BINARY, MULTICLASS, REGRESSION
from tabular.ml.label_cleaner import LabelCleaner
from tabular.ml.utils import get_pred_from_proba
from tabular.utils.loaders import load_pkl
from tabular.utils.savers import save_pkl, save_pd
from tabular.ml.trainer.abstract_trainer import AbstractTrainer


# TODO: Take as input objective function, function takes y_test, y_pred_proba as inputs and outputs score
# TODO: Add functionality for advanced feature generators such as gl_code_matrix_generator (inter-row dependencies, apply to train differently than test, etc., can only run after train/test split, rerun for each cv fold)
# TODO: - Differentiate between advanced generators that require fit (stateful, gl_code_matrix) and those that do not (bucket label averaging in SCOT GC 2019)
# TODO: - Those that do not could be added to preprocessing function of model, but would then have to be recomputed on each model.
# Learner encompasses full problem, loading initial data, feature generation, model training, model prediction
class AbstractLearner:
    save_file_name = 'learner.pkl'

    def __init__(self, path_context: str, label: str, submission_columns: list, feature_generator, threshold=100, problem_type=None, objective_func=None, is_trainer_present=False):
        self.path_context, self.model_context, self.latest_model_checkpoint, self.eval_result_path, self.save_path = self.create_contexts(path_context)

        self.label = label
        self.submission_columns = submission_columns

        self.threshold = threshold
        self.problem_type = problem_type
        self.objective_func = objective_func
        self.is_trainer_present = is_trainer_present
        self.cleaner = None
        self.label_cleaner: LabelCleaner = None
        self.feature_generator = feature_generator

        self.trainer: AbstractTrainer = None
        self.trainer_type = None
        self.trainer_path = None
        self.reset_paths = False

    def set_contexts(self, path_context):
        self.path_context, self.model_context, self.latest_model_checkpoint, self.eval_result_path, self.save_path = self.create_contexts(path_context)

    def create_contexts(self, path_context):
        model_context = path_context + 'models/'
        latest_model_checkpoint = model_context + 'model_checkpoint_latest.pointer'
        eval_result_path = model_context + 'eval_result.pkl'
        save_path = path_context + self.save_file_name
        return path_context, model_context, latest_model_checkpoint, eval_result_path, save_path

    def fit(self, X: DataFrame, X_test: DataFrame=None, sample=None):
        raise NotImplementedError

    def predict_proba(self, X_test: DataFrame, sample=None):
        ##########
        # Enable below for local testing
        if sample is not None:
            X_test = X_test.head(sample)
        ##########
        trainer = self.load_trainer()

        X_test = self.feature_generator.transform(X_test)
        y_pred_proba = trainer.predict_proba(X_test)

        return y_pred_proba

    def predict(self, X_test: DataFrame, sample=None):
        y_pred_proba = self.predict_proba(X_test=X_test, sample=sample)
        y_pred = get_pred_from_proba(y_pred_proba=y_pred_proba, problem_type=self.problem_type)
        y_pred = self.label_cleaner.inverse_transform(pd.Series(y_pred))
        return y_pred.values

    def score(self, X: DataFrame, y=None):
        if y is None:
            X, y = self.extract_label(X)
        trainer = self.load_trainer()
        X = self.feature_generator.transform(X)
        score = trainer.score(X=X, y=y)
        return score
    
    def evaluate(self, y_true, y_pred, silent=False, auxiliary_metrics=False):
        """ Evaluate predictions. 
            Args:
                silent (bool): Should we print which metric is being used as well as performance.
                auxiliary_metrics (bool): Should we compute other (problem_type specific) metrics in addition to the default metric?
            
            Returns single performance-value if auxiliary_metrics=False.
            Otherwise returns dict where keys = metrics, values = performance along each metric.
        """
        perf = self.objective_func(y_true, y_pred)
        metric = self.objective_func.__name__
        if not silent:
            print("Evaluation: %s on test data: %f" % (metric, perf))
        if not auxiliary_metrics:
            return perf
        # Otherwise compute auxiliary metrics:
        perf_dict = OrderedDict({metric: perf})
        if self.problem_type == REGRESSION: # Additional metrics: R^2, Mean-Absolute-Error, Pearson correlation (TODO)
            pearson_corr = lambda x,y: corrcoef(x,y)[0][1]
            pearson_corr.__name__ = 'pearson_correlation'
            regression_metrics = [mean_absolute_error, explained_variance_score, r2_score, pearson_corr, mean_squared_error, median_absolute_error, max_error]
            for reg_metric in regression_metrics:
                metric_name = reg_metric.__name__
                if metric_name not in perf_dict:
                    perf_dict[metric_name] = reg_metric(y_true, y_pred)
        else: # Compute classification metrics
            classif_metrics = [accuracy_score, balanced_accuracy_score, matthews_corrcoef]
            if self.problem_type == BINARY: # binary-specific metrics
                # def auc_score(y_true, y_pred): # TODO: this requires y_pred to be probability-scores
                #     fpr, tpr, _ = roc_curve(y_true, y_pred, pos_label)
                #   return auc(fpr, tpr)
                f1micro_score = lambda y_true, y_pred: f1_score(y_true, y_pred, average='micro')
                f1micro_score.__name__ = f1_score.__name__
                classif_metrics += [f1micro_score] # TODO: add auc?
            elif self.problem_type == MULTICLASS: # multiclass metrics
                classif_metrics += [] # TODO: No multi-class specific metrics for now. Include, top-1, top-5, top-10 accuracy here.
            classif_metrics += [classification_report] # Final metric to report
            for cl_metric in classif_metrics:
                metric_name = cl_metric.__name__
                if metric_name not in perf_dict:
                    perf_dict[metric_name] = cl_metric(y_true, y_pred)
        if not silent:
            print("Evaluations on test data:")
            print(json.dumps(perf_dict, indent=4))
        return perf_dict
    
    def extract_label(self, X):
        y = self.label_cleaner.transform(X[self.label])
        X = X.drop(self.label, axis=1)
        return X, y

    def submit_from_preds(self, X_test: DataFrame, y_pred_proba, save=True, save_proba=False):
        submission = X_test[self.submission_columns].copy()
        y_pred = get_pred_from_proba(y_pred_proba=y_pred_proba, problem_type=self.problem_type)

        submission[self.label] = y_pred
        submission[self.label] = self.label_cleaner.inverse_transform(submission[self.label])

        submission_proba = pd.DataFrame(y_pred_proba)

        if save:
            utcnow = datetime.datetime.utcnow()
            timestamp_str_now = utcnow.strftime("%Y%m%d_%H%M%S")
            path_submission = self.model_context + 'submissions/submission_' + timestamp_str_now + '.csv'
            path_submission_proba = self.model_context + 'submissions/submission_proba_' + timestamp_str_now + '.csv'
            save_pd.save(path=path_submission, df=submission)
            if save_proba:
                save_pd.save(path=path_submission_proba, df=submission_proba)

        return submission

    def predict_and_submit(self, X_test: DataFrame, save=True, save_proba=False):
        y_pred_proba = self.predict_proba(X_test=X_test)
        return self.submit_from_preds(X_test=X_test, y_pred_proba=y_pred_proba, save=save, save_proba=save_proba)

    @staticmethod
    def get_problem_type(y: Series):
        """ Identifies which type of prediction problem we are interested in (if user has not specified).
            Ie. binary classification, multi-class classification, or regression. 
        """
        if len(y) == 0:
            raise ValueError("provided labels cannot have length = 0")
        unique_vals = y.unique()
        REGRESS_THRESHOLD = 0.1 # if the unique-ratio is less than this, we assume multiclass classification, even when labels are integers 
        if len(unique_vals) == 2:
            problem_type =  BINARY
            reason = "only two unique label-values observed"
        elif unique_vals.dtype == 'float':
            problem_type = REGRESSION
            reason = "dtype of label-column == float"
        elif unique_vals.dtype == 'object':
            problem_type = MULTICLASS
            reason = "dtype of label-column == object"
        elif unique_vals.dtype == 'int':
            unique_ratio = len(unique_vals)/float(len(y))
            if unique_ratio > REGRESS_THRESHOLD:
                problem_type = REGRESSION
                reason = "dtype of label-column == int and many unique label-values observed"
            else:
                problem_type = MULTICLASS
                reason = "dtype of label-column == int, but few unique label-values observed"
        else:
            raise NotImplementedError('label dtype', unique_vals.dtype, 'not supported!')
        print("\n AutoGluon infers your prediction problem is: %s  (because %s)" % (problem_type, reason))
        print("If this is wrong, please specify `problem_type` argument in fit() instead (You may specify problem_type as one of: ['%s', '%s', '%s']) \n\n" % (BINARY, MULTICLASS, REGRESSION))
        return problem_type


    def save(self):
        save_pkl.save(path=self.save_path, object=self)

    # reset_paths=True if the learner files have changed location since fitting.
    @classmethod
    def load(cls, path_context, reset_paths=False):
        load_path = path_context + cls.save_file_name
        obj = load_pkl.load(path=load_path)
        if reset_paths:
            obj.set_contexts(path_context)
            obj.trainer_save_path = obj.model_context + cls.save_file_name
            obj.reset_paths = reset_paths
            # TODO: Still have to change paths of models in trainer + trainer object path variables
            return obj
        else:
            return obj

    def save_trainer(self, trainer):
        if self.is_trainer_present:
            self.trainer = trainer
            self.save()
        else:
            self.trainer_path = trainer.path
            trainer.save()

    def load_trainer(self) -> AbstractTrainer:
        if self.is_trainer_present:
            return self.trainer
        else:
            return self.trainer_type.load(path=self.trainer_path, reset_paths=self.reset_paths)
