"""Image Prediction task"""
import copy
import pickle
import logging

import pandas as pd
from autogluon.core.utils import verbosity2loglevel
from gluoncv.auto.tasks import ImageClassification as _ImageClassification
from gluoncv.model_zoo import get_model_list

__all__ = ['ImagePredictor']

class ImagePredictor(object):
    """AutoGluon Predictor for predicting image category based on their whole contents

    Parameters
    ----------
    problem_type : str, default = None
        Type of prediction problem. Options: ('multiclass'). If problem_type = None, the prediction problem type is inferred
         based on the provided dataset. Currently only multiclass(or single class vs. background) classification is supported.
    eval_metric : str, default = None
        Metric by which to evaluate the data with. Options: ('accuracy').
        Currently only supports accuracy for multiclass classification.
    path : str, default = None
        The directory for saving logs or intermediate data. If unspecified, will create a sub-directory under
        current working directory.
    verbosity : int, default = 2
        Verbosity levels range from 0 to 4 and control how much information is printed. 
        Higher levels correspond to more detailed print statements (you can set verbosity = 0 to suppress warnings). 
        If using logging, you can alternatively control amount of information printed via logger.setLevel(L), 
        where L ranges from 0 to 50 (Note: higher values of L correspond to fewer print statements, opposite of verbosity levels)
    """
    # Dataset is a subclass of `pd.DataFrame`, with `image` and `label` columns.
    Dataset = _ImageClassification.Dataset

    def __init__(self, problem_type=None, eval_metric=None, path=None, verbosity=2):
        self._problem_type = problem_type
        self._eval_metric = eval_metric
        self._log_dir = path
        self._verbosity = verbosity
        self._classifier = None
        self._fit_summary = {}

    def fit(self,
            train_data,
            tuning_data=None,
            holdout_frac=0.1,
            random_state=None,
            time_limit=None,
            num_trials=1,
            hyperparameters=None,
            search_strategy='random',
            scheduler_options=None,
            num_cpus=None,
            num_gpus=None):
        """Automatic fit process for image prediction.

        Parameters
        ----------
        train_data : pd.DataFrame or str
            Training data, can be a dataframe like image dataset.
            For dataframe like datasets, `image` and `label` columns are required.
            `image`: raw image paths. `label`: categorical integer id, starting from 0.
            For more details of how to construct a dataset for image predictor, check out:
            `http://preview.d2l.ai/d8/main/image_classification/getting_started.html`.
            If a string is provided, will search for k8 built-in datasets.
        tuning_data : pd.DataFrame or str, default = None
            Another dataset containing validation data reserved for tuning processes,
            can be a dataframe like image dataset.
            If a string is provided, will search for k8 datasets.
            If `None`, the validation dataset will be randomly split from `train_data` according to `holdout_frac`.
        holdout_frac : float, default = 0.1
            The random split ratio for `tuning_data` if `tuning_data==None`.
        random_state : numpy.random.state, default = None
            The random_state for shuffling, only used if `tuning_data==None`.
            Note that the `random_state` only affect the splitting process, not model training.
        time_limit : int, default = None
            Time limit in seconds, if not specified, will run until all tuning and training finished.
            If `time_limit` is hit during `fit`, the
            HPO process will interrupt and return the current best configuration.
        num_trials : int, default = 1
            The number of HPO trials. If `None`, will run infinite trials until `time_limit` is met.
        hyperparameters : dict, default = None
            Extra hyperparameters for specific models.
            Accepted args includes(not limited to):
            epochs : int, default value based on network
                The `epochs` for model training.
            net : mx.gluon.Block
                The custom network. If defined, the model name in config will be ignored so your
                custom network will be used for training rather than pulling it from model zoo.
            optimizer : mx.Optimizer
                The custom optimizer object. If defined, the optimizer will be ignored in config but this
                object will be used in training instead.
            batch_size : int
                Mini batch size
            lr : float
                Trainer learning rate for optimization process.
            You can get the list of accepted hyperparameters in `config.yaml` saved by this predictor.
        search_strategy : str, default = 'random'
            Searcher strategy for HPO, 'random' by default.
            Options include: ‘random’ (random search), ‘bayesopt’ (Gaussian process Bayesian optimization),
            ‘skopt’ (SKopt Bayesian optimization), ‘grid’ (grid search).
        scheduler_options : dict, default = None
            Extra options for HPO scheduler, please refer to `autogluon.core.Searcher` for details.
        num_cpus : int, default = (# cpu cores)
            Number of CPU threads for each trial, if `None`, will detect the # cores on current instance.
        num_gpus : int, default = (# gpus)
            Number of GPUs to use for each trial, if `None`, will detect the # gpus on current instance.
        """
        if self._problem_type is None:
            # options: multiclass
            self._problem_type = 'multiclass'
        if self._eval_metric is None:
            # options: accuracy, 
            self._eval_metric = 'accuracy'
        log_level = verbosity2loglevel(self._verbosity)
        use_rec = False
        if isinstance(train_data, str) and train_data == 'imagenet':
            logging.warn('ImageNet is a huge dataset which cannot be downloaded directly, ' +
                         'please follow the data preparation tutorial in GluonCV.' +
                         'The following record files(symlinks) will be used: \n' +
                         'rec_train : ~/.mxnet/datasets/imagenet/rec/train.rec\n' +
                         'rec_train_idx : ~/.mxnet/datasets/imagenet/rec/train.idx\n' +
                         'rec_val : ~/.mxnet/datasets/imagenet/rec/val.rec\n' +
                         'rec_val_idx : ~/.mxnet/datasets/imagenet/rec/val.idx\n')
            train_data = pd.DataFrame({'image': [], 'label': []})
            tuning_data = pd.DataFrame({'image': [], 'label': []})
            use_rec = True
        if isinstance(train_data, str):
            from d8.image_classification import Dataset as D8D
            names = D8D.list()
            if train_data.lower() in names:
                train_data = D8D.get(train_data)
            else:
                valid_names = '\n'.join(names)
                raise ValueError(f'`train_data` {train_data} is not among valid list {valid_names}')
            if tuning_data is None:
                train_data, tuning_data = train_data.split(1 - holdout_frac)
        if isinstance(tuning_data, str):
            from d8.image_classification import Dataset as D8D
            names = D8D.list()
            if tuning_data.lower() in names:
                tuning_data = D8D.get(tuning_data)
            else:
                valid_names = '\n'.join(names)
                raise ValueError(f'`tuning_data` {tuning_data} is not among valid list {valid_names}')
        if self._classifier is not None:
            logging.getLogger("ImageClassificationEstimator").propagate = True
            self._classifier._logger.setLevel(log_level)
            self._fit_summary = self._classifier.fit(train_data, tuning_data, 1 - holdout_frac, random_state, resume=False)
            return

        # new HPO task
        if time_limit is None and num_trials is None:
            raise ValueError('`time_limit` and `num_trials` can not be `None` at the same time, '
                             'otherwise the training will not be terminated gracefully.')
        config={'log_dir': self._log_dir,
                'num_trials': 99999 if num_trials is None else max(1, num_trials),
                'time_limits': 2147483647 if time_limit is None else max(1, time_limit),
                'search_strategy': search_strategy,
                }
        if num_cpus is not None:
            config['nthreads_per_trial'] = num_cpus
        if num_gpus is not None:
            config['ngpus_per_trial'] = num_gpus
        if isinstance(hyperparameters, dict):
            net = hyperparameters.pop('net', None)
            if net is not None:
                config['custom_net'] = net
            optimizer = hyperparameters.pop('optimizer', None)
            if optimizer is not None:
                config['custom_optimizer'] = optimizer
            # check if hyperparameters overwriting existing config
            for k, v in hyperparameters.items():
                if k in config:
                    raise ValueError(f'Overwriting {k} = {config[k]} to {v} by hyperparameters is ambiguous.')
            config.update(hyperparameters)
        if scheduler_options is not None:
            config.update(scheduler_options)
        if use_rec == True:
            config['use_rec'] = True
        # verbosity
        if log_level > logging.INFO:
            logging.getLogger('gluoncv.auto.tasks.image_classification').propagate = False
            logging.getLogger("ImageClassificationEstimator").propagate = False
            logging.getLogger("ImageClassificationEstimator").setLevel(log_level)
        task = _ImageClassification(config=config)
        task._logger.setLevel(log_level)
        task._logger.propagate = True
        self._classifier = task.fit(train_data, tuning_data, 1 - holdout_frac, random_state)
        self._classifier._logger.setLevel(log_level)
        self._classifier._logger.propagate = True
        self._fit_summary = task.fit_summary()

    def predict_proba(self, x):
        """Predict images as a whole, return the probabilities of each category rather
        than class-labels.

        Parameters
        ----------
        x : str, pd.DataFrame or ndarray
            The input, can be str(filepath), pd.DataFrame with 'image' column, or raw ndarray input.

        Returns
        -------

        pd.DataFrame
            The returned dataframe will contain probs of each category. If more than one image in input,
            the returned dataframe will contain `images` column, and all results are concatenated.
        """
        if self._classifier is None:
            raise RuntimeError('Classifier is not initialized, try `fit` first.')
        proba = self._classifier.predict(x)
        if 'image' in proba.columns:
            return proba.groupby(["image"]).agg(list)
        return proba

    def predict(self, x):
        """Predict images as a whole, return labels(class category).

        Parameters
        ----------
        x : str, pd.DataFrame or ndarray
            The input, can be str(filepath), pd.DataFrame with 'image' column, or raw ndarray input.

        Returns
        -------

        pd.DataFrame
            The returned dataframe will contain labels. If more than one image in input,
            the returned dataframe will contain `images` column, and all results are concatenated.
        """
        if self._classifier is None:
            raise RuntimeError('Classifier is not initialized, try `fit` first.')
        proba = self._classifier.predict(x)
        if 'image' in proba.columns:
            # multiple images
            return proba.loc[proba.groupby(["image"])["score"].idxmax()].reset_index(drop=True)
        else:
            # single image
            return proba.loc[[proba["score"].idxmax()]]

    def predict_feature(self, x):
        """Predict images visual feature representations, return the features as numpy (1xD) vector.

        Parameters
        ----------
        x : str, pd.DataFrame or ndarray
            The input, can be str(filepath), pd.DataFrame with 'image' column, or raw ndarray input.

        Returns
        -------

        pd.DataFrame
            The returned dataframe will contain image features. If more than one image in input,
            the returned dataframe will contain `images` column, and all results are concatenated.
        """
        if self._classifier is None:
            raise RuntimeError('Classifier is not initialized, try `fit` first.')
        return self._classifier.predict_feature(x)

    def evaluate(self, tuning_data):
        """Evaluate model performance on validation data.

        Parameters
        ----------
        tuning_data : pd.DataFrame or iterator
            The validation data.
        """
        if self._classifier is None:
            raise RuntimeError('Classifier not initialized, try `fit` first.')
        return self._classifier.evaluate(tuning_data)

    def fit_summary(self):
        """Return summary of last `fit` process.

        Returns
        -------
        dict
            The summary of last `fit` process. Major keys are ('train_acc', 'val_acc', 'total_time',...)

        """
        return copy.copy(self._fit_summary)

    def save(self, file_name):
        """Dump predictor to disk.

        Parameters
        ----------
        file_name : str
            The file name of saved copy.

        """
        with open(file_name, 'wb') as fid:
            pickle.dump(self, fid)

    @classmethod
    def load(cls, file_name):
        """Load previously saved predictor.

        Parameters
        ----------
        file_name : str
            The file name for saved pickle file.

        """
        with open(file_name, 'rb') as fid:
            obj = pickle.load(fid)
        return obj

    @classmethod
    def list_models(cls):
        """Get the list of supported model names in model zoo that
        can be used for image classification.

        Returns
        -------
        tuple of str
            A tuple of supported model names in str.

        """
        return tuple(_SUPPORTED_MODELS)


def _get_supported_models():
    all_models = get_model_list()
    blacklist = ['ssd', 'faster_rcnn', 'mask_rcnn', 'fcn', 'deeplab',
                 'psp', 'icnet', 'fastscnn', 'danet', 'yolo', 'pose',
                 'center_net', 'siamrpn', 'monodepth',
                 'ucf101', 'kinetics', 'voc', 'coco', 'citys', 'mhpv1',
                 'ade', 'hmdb51', 'sthsth', 'otb']
    cls_models = [m for m in all_models if not any(x in m for x in blacklist)]
    return cls_models

_SUPPORTED_MODELS = _get_supported_models()
