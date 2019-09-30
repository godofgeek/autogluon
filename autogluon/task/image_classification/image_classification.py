import logging

from mxnet import gluon, nd
from mxnet.gluon.data.vision import transforms
from gluoncv.data import transforms as gcv_transforms

from ...core.optimizer import *
from ...core import *
from ...searcher import *
from ...scheduler import *

from .nets import get_built_in_network
from .dataset import get_built_in_dataset
from .pipeline import train_image_classification

from ...utils import EasyDict as ezdict
from ..base import BaseTask

__all__ = ['ImageClassification']

logger = logging.getLogger(__name__)

class ImageClassification(BaseTask):
    @staticmethod
    def fit(train_dataset='cifar10',
            val_dataset='cifar10',
            net=List('CIFAR_ResNet20_v1', 'CIFAR_ResNet20_v2'),
            optimizer=SGD(learning_rate=LogLinear(1e-4, 1e-2),
                          momentum=LogLinear(0.85, 0.95),
                          wd=LogLinear(1e-5, 1e-3)),
            loss=gluon.loss.SoftmaxCrossEntropyLoss(),
            batch_size=64,
            epochs=20,
            metric='accuracy',
            num_cpus=4,
            num_gpus=0,
            algorithm='random',
            resume=False,
            checkpoint='checkpoint/exp1.ag',
            visualizer='none',
            num_trials=2,
            dist_ip_addrs=[],
            grace_period=None,
            auto_search=True):

        if auto_search:
            # The strategies can be injected here, for example: automatic suggest some hps
            # based on the dataset statistics
            pass

        train_image_classification.update(
            train_dataset=train_dataset,
            val_dataset=val_dataset,
            net=net,
            optimizer=optimizer,
            loss=loss,
            metric=metric,
            num_gpus=num_gpus,
            batch_size=batch_size,
            epochs=epochs,
            num_workers=num_cpus)

        scheduler_options = {
            'resource': {'num_cpus': num_cpus, 'num_gpus': num_gpus},
            'checkpoint': checkpoint,
            'num_trials': num_trials,
            'resume': resume,
            'visualizer': visualizer,
            'time_attr': 'epoch',
            'reward_attr': metric,
            'dist_ip_addrs': dist_ip_addrs,
        }
        if algorithm == 'hyperband':
            scheduler_options.update({
                'max_t': args.epochs,
                'grace_period': grace_period if grace_period else args.epochs//4})

        return BaseTask.run_fit(train_image_classification, algorithm, scheduler_options)
