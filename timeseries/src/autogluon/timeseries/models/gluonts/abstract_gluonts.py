import logging
import os
import shutil
import time
from datetime import timedelta
from itertools import zip_longest
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Type

import gluonts
import gluonts.core.settings
import numpy as np
import pandas as pd
from gluonts.core.component import from_hyperparameters
from gluonts.dataset.common import Dataset as GluonTSDataset
from gluonts.dataset.field_names import FieldName
from gluonts.model.estimator import Estimator as GluonTSEstimator
from gluonts.model.forecast import Forecast, QuantileForecast, SampleForecast
from gluonts.model.predictor import Predictor as GluonTSPredictor
from pandas.tseries.frequencies import to_offset

from autogluon.common.loaders import load_pkl
from autogluon.common.utils.log_utils import set_logger_verbosity
from autogluon.timeseries.dataset.ts_dataframe import ITEMID, TIMESTAMP, TimeSeriesDataFrame
from autogluon.timeseries.models.abstract import AbstractTimeSeriesModel
from autogluon.timeseries.utils.datetime import norm_freq_str
from autogluon.timeseries.utils.forecast import get_forecast_horizon_index_ts_dataframe
from autogluon.timeseries.utils.warning_filters import disable_root_logger, warning_filter

# NOTE: We avoid imports for torch and pytorch_lightning at the top level and hide them inside class methods.
# This is done to skip these imports during multiprocessing (which may cause bugs)

logger = logging.getLogger(__name__)
gts_logger = logging.getLogger(gluonts.__name__)


GLUONTS_SUPPORTED_OFFSETS = ["Y", "Q", "M", "W", "D", "B", "H", "T", "min", "S"]


class SimpleGluonTSDataset(GluonTSDataset):
    def __init__(
        self,
        target_df: TimeSeriesDataFrame,
        target_column: str = "target",
        feat_static_cat: Optional[pd.DataFrame] = None,
        feat_static_real: Optional[pd.DataFrame] = None,
        feat_dynamic_real: Optional[pd.DataFrame] = None,
        past_feat_dynamic_real: Optional[pd.DataFrame] = None,
        includes_future: bool = False,
        prediction_length: int = None,
    ):
        assert target_df is not None
        assert target_df.freq, "Initializing GluonTS data sets without freq is not allowed"
        # Convert TimeSeriesDataFrame to pd.Series for faster processing
        self.target_array = self._to_array(target_df[target_column], dtype=np.float32)
        self.feat_static_cat = self._to_array(feat_static_cat, dtype=np.int64)
        self.feat_static_real = self._to_array(feat_static_real, dtype=np.float32)
        self.feat_dynamic_real = self._to_array(feat_dynamic_real, dtype=np.float32)
        self.past_feat_dynamic_real = self._to_array(past_feat_dynamic_real, dtype=np.float32)
        self.freq = self._to_gluonts_freq(target_df.freq)

        # Necessary to compute indptr for known_covariates at prediction time
        self.includes_future = includes_future
        self.prediction_length = prediction_length

        self.item_ids = target_df.index.get_level_values(ITEMID)
        self.timestamps = target_df.index.get_level_values(TIMESTAMP)
        indices_sizes = self.item_ids.value_counts(sort=False)
        cum_sizes = indices_sizes.values.cumsum()
        self.indptr = np.append(0, cum_sizes).astype(np.int32)

    @staticmethod
    def _to_array(df: Optional[pd.DataFrame], dtype: np.dtype) -> Optional[np.ndarray]:
        if df is None:
            return None
        else:
            return df.to_numpy(dtype=dtype)

    @staticmethod
    def _to_gluonts_freq(freq: str) -> str:
        # FIXME: GluonTS expects a frequency string, but only supports a limited number of such strings
        # for feature generation. If the frequency string doesn't match or is not provided, it raises an exception.
        # Here we bypass this by issuing a default "yearly" frequency, tricking it into not producing
        # any lags or features.
        pd_offset = to_offset(freq)

        # normalize freq str to handle peculiarities such as W-SUN
        offset_base_alias = norm_freq_str(pd_offset)
        if freq not in GLUONTS_SUPPORTED_OFFSETS or offset_base_alias is None:
            return "A"
        else:
            return freq

    def __len__(self):
        return len(self.indptr) - 1  # noqa

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        for j in range(len(self.indptr) - 1):
            start_idx = self.indptr[j]
            end_idx = self.indptr[j + 1]
            ts = {
                FieldName.ITEM_ID: self.item_ids[j],
                FieldName.START: pd.Period(self.timestamps[j], freq=self.freq),
                FieldName.TARGET: self.target_array[start_idx:end_idx],
            }
            if self.feat_static_cat is not None:
                ts[FieldName.FEAT_STATIC_CAT] = self.feat_static_cat[j]
            if self.feat_static_real is not None:
                ts[FieldName.FEAT_STATIC_REAL] = self.feat_static_real[j]
            if self.past_feat_dynamic_real is not None:
                ts[FieldName.PAST_FEAT_DYNAMIC_REAL] = self.past_feat_dynamic_real[start_idx:end_idx].T
            if self.feat_dynamic_real is not None:
                if self.includes_future:
                    start = start + j * self.prediction_length
                    end = end + (j + 1) * self.prediction_length
                ts[FieldName.FEAT_DYNAMIC_REAL] = self.feat_dynamic_real[start_idx:end_idx].T
            yield ts


class AbstractGluonTSModel(AbstractTimeSeriesModel):
    """Abstract class wrapping GluonTS estimators for use in autogluon.timeseries.

    Parameters
    ----------
    path: str
        directory to store model artifacts.
    freq: str
        string representation (compatible with GluonTS frequency strings) for the data provided.
        For example, "1D" for daily data, "1H" for hourly data, etc.
    prediction_length: int
        Number of time steps ahead (length of the forecast horizon) the model will be optimized
        to predict. At inference time, this will be the number of time steps the model will
        predict.
    name: str
        Name of the model. Also, name of subdirectory inside path where model will be saved.
    eval_metric: str
        objective function the model intends to optimize, will use WQL by default.
    hyperparameters:
        various hyperparameters that will be used by model (can be search spaces instead of
        fixed values). See *Other Parameters* in each inheriting model's documentation for
        possible values.
    """

    gluonts_model_path = "gluon_ts"
    # datatype of floating point and integers passed internally to GluonTS
    float_dtype: Type = np.float32
    int_dtype: Type = np.int64
    # default number of samples for prediction
    default_num_samples: int = 1000
    supports_known_covariates: bool = False
    supports_past_covariates: bool = False

    def __init__(
        self,
        freq: Optional[str] = None,
        prediction_length: int = 1,
        path: Optional[str] = None,
        name: Optional[str] = None,
        eval_metric: str = None,
        hyperparameters: Dict[str, Any] = None,
        **kwargs,  # noqa
    ):
        super().__init__(
            path=path,
            freq=freq,
            prediction_length=prediction_length,
            name=name,
            eval_metric=eval_metric,
            hyperparameters=hyperparameters,
            **kwargs,
        )
        self.gts_predictor: Optional[GluonTSPredictor] = None
        self.callbacks = []
        self.num_feat_static_cat = 0
        self.num_feat_static_real = 0
        self.num_feat_dynamic_real = 0
        self.num_past_feat_dynamic_real = 0
        self.feat_static_cat_cardinality: List[int] = []

    def save(self, path: str = None, verbose: bool = True) -> str:
        # we flush callbacks instance variable if it has been set. it can keep weak references which breaks training
        self.callbacks = []
        # The GluonTS predictor is serialized using custom logic
        predictor = self.gts_predictor
        self.gts_predictor = None
        path = Path(super().save(path=path, verbose=verbose))

        with disable_root_logger():
            if predictor:
                Path.mkdir(path / self.gluonts_model_path, exist_ok=True)
                predictor.serialize(path / self.gluonts_model_path)

        self.gts_predictor = predictor

        return str(path)

    @classmethod
    def load(cls, path: str, reset_paths: bool = True, verbose: bool = True) -> "AbstractGluonTSModel":
        from gluonts.torch.model.predictor import PyTorchPredictor

        with warning_filter():
            model = load_pkl.load(path=os.path.join(path, cls.model_file_name), verbose=verbose)
            if reset_paths:
                model.set_contexts(path)
            model.gts_predictor = PyTorchPredictor.deserialize(Path(path) / cls.gluonts_model_path)
        return model

    def _deferred_init_params_aux(self, **kwargs) -> None:
        """Update GluonTS specific parameters with information available
        only at training time.
        """
        if "dataset" in kwargs:
            ds = kwargs.get("dataset")
            self.freq = ds.freq or self.freq
            if not self.freq:
                raise ValueError(
                    "Dataset frequency not provided in the dataset, fit arguments or "
                    "during initialization. Please provide a `freq` string to `fit`."
                )

            model_params = self._get_model_params()
            disable_static_features = model_params.get("disable_static_features", False)
            if not disable_static_features:
                self.num_feat_static_cat = len(self.metadata.static_features_cat)
                self.num_feat_static_real = len(self.metadata.static_features_real)
                if self.num_feat_static_cat > 0:
                    feat_static_cat = ds.static_features[self.metadata.static_features_cat]
                    self.feat_static_cat_cardinality = feat_static_cat.nunique().tolist()
            disable_known_covariates = model_params.get("disable_known_covariates", False)
            if not disable_known_covariates and self.supports_known_covariates:
                self.num_feat_dynamic_real = len(self.metadata.known_covariates_real)
            disable_past_covariates = model_params.get("disable_past_covariates", False)
            if not disable_past_covariates and self.supports_past_covariates:
                self.num_past_feat_dynamic_real = len(self.metadata.past_covariates_real)

        if "callbacks" in kwargs:
            self.callbacks += kwargs["callbacks"]

    @property
    def default_context_length(self) -> int:
        return max(10, 2 * self.prediction_length)

    def _get_model_params(self) -> dict:
        """Gets params that are passed to the inner model."""
        args = super()._get_model_params().copy()
        args.setdefault("batch_size", 64)
        args.setdefault("context_length", self.default_context_length)
        args.update(
            dict(
                freq=self.freq,
                prediction_length=self.prediction_length,
                quantiles=self.quantile_levels,
                callbacks=self.callbacks,
            )
        )
        return args

    def _get_estimator_init_args(self) -> Dict[str, Any]:
        """Get GluonTS specific constructor arguments for estimator objects, an alias to `self._get_model_params`
        for better readability."""
        init_kwargs = self._get_model_params()
        # Map MXNet kwarg names to PyTorch Lightning kwarg names
        init_kwargs.setdefault("lr", init_kwargs.get("learning_rate", 1e-3))
        init_kwargs.setdefault("max_epochs", init_kwargs.get("epochs"))
        return init_kwargs

    def _get_estimator_class(self) -> Type[GluonTSEstimator]:
        raise NotImplementedError

    def _get_estimator(self) -> GluonTSEstimator:
        """Return the GluonTS Estimator object for the model"""
        # As GluonTSPyTorchLightningEstimator objects do not implement `from_hyperparameters` convenience
        # constructors, we re-implement the logic here.
        # we translate the "epochs" parameter to "max_epochs" for consistency in the AbstractGluonTSModel interface
        import torch

        init_args = self._get_estimator_init_args()

        trainer_kwargs = {}
        epochs = init_args.get("max_epochs")
        callbacks = init_args.get("callbacks", [])

        # TODO: Provide trainer_kwargs outside the function (e.g., to specify # of GPUs)?
        if epochs is not None:
            trainer_kwargs.update({"max_epochs": epochs})
        trainer_kwargs.update({"callbacks": callbacks, "enable_progress_bar": False})
        trainer_kwargs["default_root_dir"] = self.path

        if torch.cuda.is_available():
            trainer_kwargs["accelerator"] = "gpu"
            trainer_kwargs["devices"] = 1
        else:
            trainer_kwargs["accelerator"] = "cpu"

        return from_hyperparameters(
            self._get_estimator_class(),
            trainer_kwargs=trainer_kwargs,
            **init_args,
        )

    def _to_gluonts_dataset(
        self, time_series_df: Optional[TimeSeriesDataFrame], known_covariates: Optional[TimeSeriesDataFrame] = None
    ) -> Optional[GluonTSDataset]:
        if time_series_df is not None:
            start = time.time()
            if self.num_feat_static_cat > 0:
                feat_static_cat = time_series_df.static_features[self.metadata.static_features_cat]
            else:
                feat_static_cat = None

            if self.num_feat_static_real > 0:
                feat_static_real = time_series_df.static_features[self.metadata.static_features_real]
            else:
                feat_static_real = None

            if self.num_feat_dynamic_real > 0:
                # Convert TSDF -> DF to avoid overhead / input validation
                feat_dynamic_real = pd.DataFrame(time_series_df[self.metadata.known_covariates_real])
                # Append future values of known covariates
                if known_covariates is not None:
                    feat_dynamic_real = pd.concat([feat_dynamic_real, known_covariates], axis=0)
                    expected_length = len(time_series_df) + self.prediction_length * time_series_df.num_items
                    if len(feat_dynamic_real) != expected_length:
                        raise ValueError(
                            f"known_covariates must contain values for the next prediction_length = "
                            f"{self.prediction_length} time steps in each time series."
                        )
            else:
                feat_dynamic_real = None

            if self.num_past_feat_dynamic_real > 0:
                # Convert TSDF -> DF to avoid overhead / input validation
                past_feat_dynamic_real = pd.DataFrame(time_series_df[self.metadata.past_covariates_real])
            else:
                past_feat_dynamic_real = None

            # result = list(GTSDataset(time_series_df[self.target], self.freq))
            # from statsforecast.core import GroupedArray, _grouped_array_from_df

            return SimpleGluonTSDataset(
                target_df=time_series_df,
                target_column=self.target,
                feat_static_cat=feat_static_cat,
                feat_static_real=feat_static_real,
                feat_dynamic_real=feat_dynamic_real,
                past_feat_dynamic_real=past_feat_dynamic_real,
                includes_future=known_covariates is not None,
                prediction_length=self.prediction_length,
            )
        else:
            return None

    def _fit(
        self,
        train_data: TimeSeriesDataFrame,
        val_data: Optional[TimeSeriesDataFrame] = None,
        time_limit: int = None,
        **kwargs,
    ) -> None:
        # necessary to initialize the loggers
        import pytorch_lightning  # noqa

        verbosity = kwargs.get("verbosity", 2)
        for logger_name in logging.root.manager.loggerDict:
            if "pytorch_lightning" in logger_name:
                pl_logger = logging.getLogger(logger_name)
                pl_logger.setLevel(logging.ERROR if verbosity <= 3 else logging.INFO)
        set_logger_verbosity(verbosity, logger=logger)
        gts_logger.setLevel(logging.ERROR if verbosity <= 3 else logging.INFO)

        if verbosity > 3:
            logger.warning(
                "GluonTS logging is turned on during training. Note that losses reported by GluonTS "
                "may not correspond to those specified via `eval_metric`."
            )

        self._check_fit_params()
        # update auxiliary parameters
        self._deferred_init_params_aux(
            dataset=train_data, callbacks=self._get_callbacks(time_limit=time_limit), **kwargs
        )

        estimator = self._get_estimator()
        with warning_filter(), disable_root_logger(), gluonts.core.settings.let(gluonts.env.env, use_tqdm=False):
            self.gts_predictor = estimator.train(
                self._to_gluonts_dataset(train_data),
                validation_data=self._to_gluonts_dataset(val_data),
                cache_data=True,
            )
            self.gts_predictor.batch_size = 500

        lightning_logs_dir = Path(self.path) / "lightning_logs"
        if lightning_logs_dir.exists() and lightning_logs_dir.is_dir():
            logger.debug(f"Removing lightning_logs directory {lightning_logs_dir}")
            shutil.rmtree(lightning_logs_dir)

    def _get_callbacks(self, time_limit: int, *args, **kwargs) -> List[Callable]:
        """Retrieve a list of callback objects for the GluonTS trainer"""
        from pytorch_lightning.callbacks import Timer

        return [Timer(timedelta(seconds=time_limit))] if time_limit is not None else []

    def predict(
        self,
        data: TimeSeriesDataFrame,
        known_covariates: Optional[TimeSeriesDataFrame] = None,
        quantile_levels: List[float] = None,
        **kwargs,
    ) -> TimeSeriesDataFrame:
        if self.gts_predictor is None:
            raise ValueError("Please fit the model before predicting.")

        logger.debug(f"Predicting with time series model {self.name}")
        logger.debug(
            f"\tProvided data for prediction with {len(data)} rows, {data.num_items} items. "
            f"Average time series length is {len(data) / data.num_items}."
        )
        with warning_filter(), gluonts.core.settings.let(gluonts.env.env, use_tqdm=False):
            quantiles = quantile_levels or self.quantile_levels
            if not all(0 < q < 1 for q in quantiles):
                raise ValueError("Invalid quantile value specified. Quantiles must be between 0 and 1 (exclusive).")

            print("Starting GluonTS forecast")
            start = time.time()
            predicted_targets = self._predict_gluonts_forecasts(data, known_covariates=known_covariates, **kwargs)
            print(f"Finished GluonTS forecast, time = {time.time() - start:.1f}s")

            start = time.time()
            df = self._gluonts_forecasts_to_data_frame(
                predicted_targets,
                quantile_levels=quantile_levels or self.quantile_levels,
                forecast_index=get_forecast_horizon_index_ts_dataframe(data, self.prediction_length),
            )
            print(f"Finished Df conversion, time = {time.time() - start:.1f}s")

        return df

    def _predict_gluonts_forecasts(
        self, data: TimeSeriesDataFrame, known_covariates: Optional[TimeSeriesDataFrame] = None, **kwargs
    ) -> List[Forecast]:
        gts_data = self._to_gluonts_dataset(data, known_covariates=known_covariates)

        predictor_kwargs = dict(dataset=gts_data)
        predictor_kwargs["num_samples"] = kwargs.get("num_samples", self.default_num_samples)

        return list(self.gts_predictor.predict(**predictor_kwargs))

    @staticmethod
    def _sample_to_quantile_forecast(forecast: SampleForecast, quantile_levels: List[float]) -> QuantileForecast:
        forecast_arrays = [forecast.mean]

        quantile_keys = [str(q) for q in quantile_levels]
        for q in quantile_keys:
            forecast_arrays.append(forecast.quantile(q))

        forecast_init_args = dict(
            forecast_arrays=np.array(forecast_arrays),
            start_date=forecast.start_date,
            forecast_keys=["mean"] + quantile_keys,
            item_id=str(forecast.item_id),
        )
        return QuantileForecast(**forecast_init_args)

    @staticmethod
    def _distribution_to_quantile_forecast(forecast: Forecast, quantile_levels: List[float]) -> QuantileForecast:
        import torch

        # Compute all quantiles in parallel instead of a for-loop
        quantiles = torch.tensor(quantile_levels, device=forecast.distribution.mean.device).reshape(-1, 1)
        quantile_predictions = forecast.distribution.icdf(quantiles).cpu().detach().numpy()
        forecast_arrays = np.vstack([forecast.mean, quantile_predictions])
        forecast_keys = ["mean"] + [str(q) for q in quantile_levels]

        forecast_init_args = dict(
            forecast_arrays=forecast_arrays,
            start_date=forecast.start_date,
            forecast_keys=forecast_keys,
            item_id=str(forecast.item_id),
        )
        return QuantileForecast(**forecast_init_args)

    def _gluonts_forecasts_to_data_frame(
        self,
        forecasts: List[Forecast],
        quantile_levels: List[float],
        forecast_index: pd.MultiIndex,
    ) -> TimeSeriesDataFrame:
        from gluonts.torch.model.forecast import DistributionForecast

        # TODO: Concatenate all forecasts into a single tensor/object before converting?
        # Especially for DistributionForecast this could result in massive speedups
        if isinstance(forecasts[0], SampleForecast):
            forecasts = [self._sample_to_quantile_forecast(f, quantile_levels) for f in forecasts]
        elif isinstance(forecasts[0], DistributionForecast):
            forecasts = [self._distribution_to_quantile_forecast(f, quantile_levels) for f in forecasts]
        else:
            assert isinstance(forecasts[0], QuantileForecast), f"Unrecognized forecast type {type(forecasts[0])}"

        # sanity check to ensure all quantiles are accounted for
        assert all(str(q) in forecasts[0].forecast_keys for q in quantile_levels), (
            "Some forecast quantiles are missing from GluonTS forecast outputs. Was"
            " the model trained to forecast all quantiles?"
        )
        item_id_to_forecast = {str(f.item_id): f for f in forecasts}
        result_dfs = []
        for item_id in forecast_index.unique(level=ITEMID):
            # GluonTS always saves item_id as a string
            forecast = item_id_to_forecast[str(item_id)]
            item_forecast_dict = {"mean": forecast.mean}
            for quantile in quantile_levels:
                item_forecast_dict[str(quantile)] = forecast.quantile(str(quantile))
            result_dfs.append(pd.DataFrame(item_forecast_dict))

        result = pd.concat(result_dfs)
        result.index = forecast_index
        return TimeSeriesDataFrame(result)
