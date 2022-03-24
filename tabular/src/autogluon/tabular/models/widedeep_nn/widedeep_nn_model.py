import logging

import numpy as np
import pytorch_widedeep.training.trainer
import torch
from autogluon.common.features.types import R_OBJECT, S_TEXT_NGRAM, S_TEXT_AS_CATEGORY
from pytorch_widedeep.callbacks import ModelCheckpoint
from pytorch_widedeep.models import FTTransformer, TabPerceiver

from autogluon.core.constants import BINARY, MULTICLASS, REGRESSION
from autogluon.core.models import AbstractModel
from autogluon.core.utils.files import make_temp_directory
from common.src.autogluon.common.features.types import R_INT, R_FLOAT, R_DATETIME, R_BOOL, R_CATEGORY
from .utils import set_seed
from .hyperparameters.parameters import get_param_baseline
from .hyperparameters.searchspaces import get_default_searchspace

logger = logging.getLogger(__name__)


class WideDeepNNModel(AbstractModel):
    # TODO: Leverage time_limit
    # TODO: Leverage sample_weight
    # TODO: Experiment with text and image data
    # TODO: How to leverage GPU?
    # TODO: Missing value handling?
    def _fit(self,
             X,
             y,
             X_val=None,
             y_val=None,
             sample_weight=None,
             time_limit=None,
             **kwargs):
        # TODO: Add try_import_pytorch_widedeep() to enable a more helpful error message if pytorch_widedeep is not installed
        #  Refer to other model implementations for examples
        from pytorch_widedeep import Trainer
        from pytorch_widedeep.preprocessing import TabPreprocessor
        from pytorch_widedeep.metrics import Accuracy, R2Score
        # TODO: Use this to get user-specified params instead of hard-coding
        # params = self._get_model_params()

        set_seed(0, True)

        params = self._get_model_params()

        X = self.preprocess(X)

        # prepare wide, crossed, embedding and continuous columns
        # TODO: Either don't use cross_cols or find a way to automatically determine them in a fully automated fashion
        # TODO: Find a way to automatically determine embed dimensions

        cont_cols = self._feature_metadata.get_features(valid_raw_types=[R_INT, R_FLOAT, R_DATETIME])
        cat_cols = self._feature_metadata.get_features(valid_raw_types=[R_OBJECT, R_CATEGORY, R_BOOL])

        # train the model
        # TODO: Add custom metric support (Convert arbitrary AG metric)
        if self.problem_type == BINARY:
            objective = 'binary'
            metrics = [Accuracy]
            pred_dim = 1
        elif self.problem_type == MULTICLASS:
            objective = 'multiclass'
            metrics = [Accuracy]
            pred_dim = self.num_classes
        elif self.problem_type == REGRESSION:
            objective = 'regression'
            metrics = [R2Score]
            pred_dim = 1
        else:
            raise ValueError(f'{self.name} does not support the problem_type {self.problem_type}.')

        # deeptabular
        for_transformer = self.params['type'] in ['tab_transformer', 'ft_transformer', 'tab_perciever']
        if for_transformer:
            embed_cols = cat_cols
        else:
            embed_cols = []
            for cat_feat in cat_cols:
                num_categories = len(X[cat_feat].cat.categories)
                embed_cols.append((cat_feat, min(600, round(1.6 * num_categories ** 0.56))))
        if len(embed_cols) == 0:
            embed_cols = None
            for_transformer = False

        self._tab_preprocessor = TabPreprocessor(embed_cols=embed_cols, continuous_cols=cont_cols, for_transformer=for_transformer)
        X_tab = self._tab_preprocessor.fit_transform(X)

        embed_input = None if embed_cols is None else self._tab_preprocessor.embeddings_input
        model = self._construct_wide_deep_model(
            self.params['type'],
            self._tab_preprocessor.column_idx,
            embed_input,
            cont_cols,
            pred_dim,
            **self.params.get('model_args', {})
        )

        X_train = {'X_tab': X_tab, 'target': y.values}

        if X_val is not None and y_val is not None:
            X_val_in = {'X_tab': self._tab_preprocessor.transform(X_val), 'target': y_val.values}
            val_split = None
        else:
            X_val_in = None
            val_split = 0.1

        logger.log(15, model)

        # DataLoaders are very slow if defaults are used
        # TODO: confirm if this is reproducible on linux
        pytorch_widedeep.training.trainer.n_cpus = 0

        # TODO: move to parameters
        logger.log(15, f'Fitting with parameters {params}...')
        n_epochs = params['epochs']
        lr = params['lr']
        bs = params['bs']

        tab_opt = torch.optim.Adam(model.deeptabular.parameters(), lr=lr)
        steps_per_epoch = int(np.ceil(len(X_tab) / bs))
        tab_sch = torch.optim.lr_scheduler.OneCycleLR(tab_opt, max_lr=lr, epochs=n_epochs, steps_per_epoch=steps_per_epoch, pct_start=0.25, final_div_factor=1e5)

        monitor_metric = f'val_{metrics[0]()._name}'
        with make_temp_directory() as temp_dir:
            checkpoint_path_prefix = f'{temp_dir}/model'

            model_checkpoint = ModelCheckpoint(filepath=checkpoint_path_prefix, verbose=kwargs.get('verbosity', 2), save_best_only=True, max_save=1, monitor=monitor_metric)

            trainer = Trainer(
                model,
                objective=objective,
                metrics=metrics,
                optimizers=tab_opt,
                lr_schedulers=tab_sch,
                callbacks=[model_checkpoint],
                verbose=kwargs.get('verbosity', 2),
            )
            # FIXME: Does not return best epoch, instead returns final epoch
            #  Very important to return best epoch, otherwise model can be far worse than ideal
            # FIXME: Add early stopping
            trainer.fit(
                X_train=X_train,
                X_val=X_val_in,
                n_epochs=n_epochs,
                batch_size=bs,
                val_split=val_split,
            )

            best_checkpoint = f'{checkpoint_path_prefix}_{model_checkpoint.best_epoch + 1}.p'
            trainer.model.load_state_dict(torch.load(best_checkpoint))

        self.model = trainer

    def _predict_proba(self, X, **kwargs):
        X = self.preprocess(X, **kwargs)
        X_tab = self._tab_preprocessor.transform(X)
        if self.problem_type != REGRESSION:
            preds = self.model.predict_proba(X_tab=X_tab)
        else:
            preds = self.model.predict(X_tab=X_tab)

        if self.problem_type == BINARY:
            return preds[:, 1]
        else:
            return preds

    def _get_default_auxiliary_params(self) -> dict:
        default_auxiliary_params = super()._get_default_auxiliary_params()
        extra_auxiliary_params = dict(
            ignored_type_group_raw=[R_OBJECT],
        )
        default_auxiliary_params.update(extra_auxiliary_params)
        return default_auxiliary_params

    @staticmethod
    def _construct_wide_deep_model(model_type, column_idx, embed_input, continuous_cols, pred_dim, **model_args):
        from pytorch_widedeep.models import TabMlp, WideDeep, TabResnet, SAINT, TabTransformer

        __MODEL_TYPES = dict(
            tabmlp=TabMlp,
            tabresnet=TabResnet,
            SAINT=SAINT,
            tab_transformer=TabTransformer,
            ft_transformer=FTTransformer,
            tab_perciever=TabPerceiver,
        )

        model_cls = __MODEL_TYPES.get(model_type, None)
        if model_cls is None:
            raise ValueError(f'Unknown model type {model_type}')

        model = model_cls(
            column_idx=column_idx,
            embed_input=embed_input,
            continuous_cols=continuous_cols,
            **model_args
        )
        model = WideDeep(deeptabular=model, pred_dim=pred_dim)
        return model

    def _set_default_params(self):
        """ Specifies hyperparameter values to use by default """
        default_params = get_param_baseline(self.problem_type)
        for param, val in default_params.items():
            self._set_default_param_value(param, val)

    def _get_default_searchspace(self):
        return get_default_searchspace(self.problem_type, num_classes=None)

    def _get_default_auxiliary_params(self) -> dict:
        default_auxiliary_params = super()._get_default_auxiliary_params()
        extra_auxiliary_params = dict(
            valid_raw_types=[R_BOOL, R_INT, R_FLOAT, R_CATEGORY],
            ignored_type_group_special=[S_TEXT_NGRAM, S_TEXT_AS_CATEGORY],
        )
        default_auxiliary_params.update(extra_auxiliary_params)
        return default_auxiliary_params
