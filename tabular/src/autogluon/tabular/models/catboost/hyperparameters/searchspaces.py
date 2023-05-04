""" Default hyperparameter search spaces used in CatBoost Boosting model """
from autogluon.common.space import Space, Categorical, Real, Int, Bool

from autogluon.core.constants import BINARY, MULTICLASS, REGRESSION


def get_default_searchspace(problem_type, num_classes=None):
    if problem_type == BINARY:
        return get_searchspace_binary_baseline()
    elif problem_type == MULTICLASS:
        return get_searchspace_multiclass_baseline(num_classes=num_classes)
    elif problem_type == REGRESSION:
        return get_searchspace_regression_baseline()
    else:
        return get_searchspace_binary_baseline()


def get_searchspace_multiclass_baseline(num_classes):
    params = {
        'learning_rate': Real(lower=5e-3, upper=0.2, default=0.05, log=True),
        'depth': Int(lower=5, upper=8, default=6),
        'l2_leaf_reg': Real(lower=1, upper=5, default=3),
    }
    return params


def get_searchspace_binary_baseline():
    params = {
        'learning_rate': Real(lower=5e-3, upper=0.2, default=0.05, log=True),
        'depth': Int(lower=5, upper=8, default=6),
        'l2_leaf_reg': Real(lower=1, upper=5, default=3),
    }
    return params


def get_searchspace_regression_baseline():
    params = {
        'learning_rate': Real(lower=5e-3, upper=0.2, default=0.05, log=True),
        'depth': Int(lower=5, upper=8, default=6),
        'l2_leaf_reg': Real(lower=1, upper=5, default=3),
    }
    return params
