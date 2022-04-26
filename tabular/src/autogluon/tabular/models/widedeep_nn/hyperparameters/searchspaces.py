from autogluon.core import Categorical, Real, Int
from autogluon.core.constants import BINARY, MULTICLASS, REGRESSION


def get_default_searchspace(problem_type, num_classes=None):
    if problem_type == BINARY:
        return get_searchspace_binary()
    elif problem_type == MULTICLASS:
        return get_searchspace_multiclass(num_classes=num_classes)
    elif problem_type == REGRESSION:
        return get_searchspace_regression()
    else:
        return get_searchspace_binary()


def get_searchspace_binary():
    spaces = {
        # See docs: https://docs.fast.ai/tabular.models.html
        'bs': Categorical(256, 64, 128, 512, 1024, 2048, 4096),
        'lr': Real(5e-5, 1e-1, default=1e-2, log=True),
        'epochs': Int(lower=5, upper=30, default=10),
    }
    return spaces


def get_searchspace_multiclass(num_classes):
    return get_searchspace_binary()


def get_searchspace_regression():
    return get_searchspace_binary()
