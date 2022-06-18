"""Functions and objects for evaluating forecasts. Adapted from gluonts.evaluation.
See also, https://ts.gluon.ai/api/gluonts/gluonts.evaluation.html
"""
import logging
from typing import Callable, List, Optional

import numpy as np
import pandas as pd

from autogluon.timeseries import TimeSeriesDataFrame

logger = logging.getLogger(__name__)


# unit metric callables -- compute an error or summary statistic of a single
# time series against a forecast


def mean_square_error(
    *, target: np.ndarray, forecast: np.ndarray, **kwargs  # noqa: F841
) -> float:
    return np.mean(np.square(target - forecast))  # noqa


def abs_error(
    *, target: np.ndarray, forecast: np.ndarray, **kwargs  # noqa: F841
) -> float:
    return np.sum(np.abs(target - forecast))  # noqa


def mean_abs_error(
    *, target: np.ndarray, forecast: np.ndarray, **kwargs  # noqa: F841
) -> float:
    return np.mean(np.abs(target - forecast))  # noqa


def quantile_loss(
    *, target: np.ndarray, forecast: np.ndarray, q: float, **kwargs  # noqa: F841
) -> float:
    return 2 * np.sum(np.abs((forecast - target) * ((target <= forecast) - q)))


def coverage(
    *, target: np.ndarray, forecast: np.ndarray, **kwargs  # noqa: F841
) -> float:
    return np.mean(target < forecast)  # noqa


def mape(*, target: np.ndarray, forecast: np.ndarray, **kwargs) -> float:  # noqa: F841
    return np.mean(np.abs(target - forecast) / np.abs(target))  # noqa


def symmetric_mape(
    *, target: np.ndarray, forecast: np.ndarray, **kwargs  # noqa: F841
) -> float:
    return 2 * np.mean(np.abs(target - forecast) / (np.abs(target) + np.abs(forecast)))


def abs_target_sum(*, target: np.ndarray, **kwargs):  # noqa: F841
    return np.sum(np.abs(target))


def abs_target_mean(*, target: np.ndarray, **kwargs):  # noqa: F841
    return np.mean(np.abs(target))


def in_sample_naive_1_error(*, target_history: np.ndarray, **kwargs):  # noqa: F841
    return np.mean(np.abs(np.diff(target_history)))


class TimeSeriesEvaluator:
    """Does not ensure consistency with GluonTS, for example in definition of MASE."""

    AVAILABLE_METRICS = ["MASE", "MAPE", "sMAPE", "mean_wQuantileLoss"]

    def __init__(
        self, eval_metric: str, prediction_length: int, target_column: str = "target"
    ):
        assert (
            eval_metric in self.AVAILABLE_METRICS
        ), f"Metric {eval_metric} not available"

        self.prediction_length = prediction_length
        self.eval_metric = eval_metric
        self.target_column = target_column

        self.metric_method = self.__getattribute__("_" + self.eval_metric.lower())

    def _mase(
        self, data: TimeSeriesDataFrame, predictions: TimeSeriesDataFrame
    ) -> float:
        metric_callables = [mean_abs_error, in_sample_naive_1_error]
        df = self.get_metrics_per_ts(
            data, predictions, metric_callables=metric_callables
        )
        return float(np.mean(df["mean_abs_error"] / df["in_sample_naive_1_error"]))

    def _mape(
        self, data: TimeSeriesDataFrame, predictions: TimeSeriesDataFrame
    ) -> float:
        df = self.get_metrics_per_ts(data, predictions, metric_callables=[mape])
        return float(np.mean(df["mape"]))

    def _smape(
        self, data: TimeSeriesDataFrame, predictions: TimeSeriesDataFrame
    ) -> float:
        df = self.get_metrics_per_ts(
            data, predictions, metric_callables=[symmetric_mape]
        )
        return float(np.mean(df["symmetric_mape"]))

    def _mean_wquantileloss(
        self,
        data: TimeSeriesDataFrame,
        predictions: TimeSeriesDataFrame,
        quantiles: List[float] = None,
    ):
        if not quantiles:
            quantiles = [float(col) for col in predictions.columns if col != "mean"]
            assert all(0 <= q <= 1 for q in quantiles)

        df = self.get_metrics_per_ts(
            data=data,
            predictions=predictions,
            metric_callables=[quantile_loss, abs_target_sum],
            quantiles=quantiles,
        )

        w_quantile_losses = []
        total_abs_target = df["abs_target_sum"].sum()
        for q in quantiles:
            w_quantile_losses.append(
                df[f"quantile_loss[{str(q)}]"].sum() / total_abs_target
            )

        return float(np.mean(w_quantile_losses))

    def _get_minimizing_forecast(
        self, predictions: TimeSeriesDataFrame, metric: str
    ) -> np.ndarray:
        """get field from among predictions that minimizes the given metric"""
        if "0.5" in predictions.columns and metric != "MSE":
            return np.array(predictions["0.5"])
        elif metric != "MSE":
            logger.warning("Median forecast not found. Defaulting to mean forecasts.")

        if "mean" not in predictions.columns:
            ValueError(f"Mean forecast not found. Cannot evaluate metric {metric}")
        return np.array(predictions["mean"])

    def get_metrics_per_ts(
        self,
        data: TimeSeriesDataFrame,
        predictions: TimeSeriesDataFrame,
        metric_callables: List[Callable],
        quantiles: Optional[List[float]] = None,
    ) -> pd.DataFrame:
        metrics = []
        for item_id in data.iter_items():
            y_true_w_hist = data.loc[item_id][self.target_column]

            target = np.array(y_true_w_hist[-self.prediction_length :])
            target_history = np.array(y_true_w_hist[: -self.prediction_length])

            item_metrics = {}
            for metric_callable in metric_callables:
                if metric_callable is quantile_loss:
                    assert all(0 <= q <= 1 for q in quantiles)
                    for q in quantiles:
                        assert (
                            str(q) in predictions.columns
                        ), f"Quantile {q} not found in predictions"
                        item_metrics[f"quantile_loss[{str(q)}]"] = quantile_loss(
                            target=target,
                            forecast=np.array(predictions.loc[item_id][str(q)]),
                            q=q,
                        )
                else:
                    forecast = self._get_minimizing_forecast(
                        predictions.loc[item_id], metric=self.eval_metric
                    )
                    item_metrics[metric_callable.__name__] = metric_callable(
                        target=target,
                        forecast=forecast,
                        target_history=target_history,
                    )

            metrics.append(item_metrics)

        return pd.DataFrame(metrics)

    def __call__(
        self, data: TimeSeriesDataFrame, predictions: TimeSeriesDataFrame
    ) -> float:
        assert all(
            len(predictions.loc[i]) == self.prediction_length
            for i in predictions.iter_items()
        )
        assert set(predictions.iter_items()) == set(
            data.iter_items()
        ), "Prediction and data indices do not match."

        return self.metric_method(data, predictions)
