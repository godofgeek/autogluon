import warnings
import logging

import random
import mxnet as mx
import numpy as np

from mxnet import gluon, init, autograd
from mxnet.gluon import nn
from gluoncv.model_zoo import get_model

from ...basic import autogluon_method
from .dataset import Dataset

__all__ = ['train_image_classification', 'train_ray_image_classification']

logger = logging.getLogger(__name__)


@autogluon_method
def train_image_classification(args, reporter):
    # Set Hyper-params
    def _init_hparams():
        if hasattr(args, 'batch_size') and hasattr(args, 'num_gpus'):
            batch_size = args.batch_size * max(args.num_gpus, 1)
            ctx = [mx.gpu(i)
                   for i in range(args.num_gpus)] if args.num_gpus > 0 else [mx.cpu()]
        else:
            if hasattr(args, 'num_gpus'):
                num_gpus = args.num_gpus
            else:
                num_gpus = 0
            if hasattr(args, 'batch_size'):
                batch_size = args.batch_size * max(num_gpus, 1)
            else:
                batch_size = 64 * max(num_gpus, 1)
            ctx = [mx.gpu(i)
                   for i in range(num_gpus)] if num_gpus > 0 else [mx.cpu()]
        return batch_size, ctx

    batch_size, ctx = _init_hparams()

    # Define DataLoader
    dataset = Dataset(args.data)
    train_data = dataset.train_data
    val_data = dataset.val_data

    # Define Network
    net = get_model(args.model, pretrained=args.pretrained)
    with net.name_scope():
        num_classes = dataset.num_classes
        if hasattr(args, 'classes'):
            warnings.warn('Warning: '
                          'number of class of labels can be inferred.')
            num_classes = args.classes
        net.output = nn.Dense(num_classes)
    if not args.pretrained:
        net.collect_params().initialize(mx.init.Xavier(magnitude=2.24), ctx=ctx)
    else:
        net.output.initialize(init.Xavier(), ctx=ctx)
        net.collect_params().reset_ctx(ctx)

    # Define trainer
    def _set_optimizer_params(args):
        # TODO (cgraywang): a better way?
        if args.optimizer == 'sgd' or args.optimizer == 'nag':
            optimizer_params = {
                'learning_rate': args.lr,
                'momentum': args.momentum,
                'wd': args.wd
            }
        elif args.optimizer == 'adam':
            optimizer_params = {
                'learning_rate': args.lr,
                'wd': args.wd
            }
        else:
            raise NotImplementedError
        return optimizer_params

    optimizer_params = _set_optimizer_params(args)
    trainer = gluon.Trainer(net.collect_params(),
                            args.optimizer,
                            optimizer_params)

    def _print_debug_info(args):
        for k, v in vars(args).items():
            logger.debug('%s:%s' % (k, v))

    _print_debug_info(args)

    # TODO (cgraywang): update with search space
    L = gluon.loss.SoftmaxCrossEntropyLoss()
    metric = mx.metric.Accuracy()

    def train(epoch):
        for i, batch in enumerate(train_data):
            data = gluon.utils.split_and_load(batch[0],
                                              ctx_list=ctx,
                                              )
            label = gluon.utils.split_and_load(batch[1],
                                               ctx_list=ctx,
                                               )
            with autograd.record():
                outputs = [net(X) for X in data]
                loss = [L(yhat, y) for yhat, y in zip(outputs, label)]
            for l in loss:
                l.backward()

            trainer.step(batch_size)
        if epoch == 0 and hasattr(args, 'viz'):
            args.viz.add_graph(net)
        mx.nd.waitall()

    def test(epoch):
        test_loss = 0
        for i, batch in enumerate(val_data):
            data = gluon.utils.split_and_load(batch[0],
                                              ctx_list=ctx,
                                              batch_axis=0,
                                              even_split=False)
            label = gluon.utils.split_and_load(batch[1],
                                               ctx_list=ctx,
                                               batch_axis=0,
                                               even_split=False)
            outputs = [net(X) for X in data]
            loss = [L(yhat, y) for yhat, y in zip(outputs, label)]

            test_loss += sum([l.mean().asscalar() for l in loss]) / len(loss)
            metric.update(label, outputs)
        _, test_acc = metric.get()
        test_loss /= len(val_data)
        reporter(epoch=epoch, accuracy=test_acc)
        if hasattr(args, 'viz'):
            args.viz.add_scalar(tag='loss',
                                value=('task %d valid_loss' % args.task_id, test_loss),
                                global_step=epoch)
            args.viz.add_scalar(tag='accuracy_curves',
                                value=('task %d valid_acc' % args.task_id, test_acc),
                                global_step=epoch)

    for epoch in range(1, args.epochs + 1):
        train(epoch)
        test(epoch)


def train_ray_image_classification(args, config, reporter):
    vars(args).update(config)
    np.random.seed(args.seed)
    random.seed(args.seed)
    mx.random.seed(args.seed)

    # Set Hyper-params
    batch_size = args.batch_size * max(args.num_gpus, 1)
    ctx = [mx.gpu(i)
           for i in range(args.num_gpus)] if args.num_gpus > 0 else [mx.cpu()]

    # Define DataLoader
    train_data = args.train_data
    test_data = args.test_data

    # Load model architecture and Initialize the net with pretrained model
    finetune_net = get_model(args.model, pretrained=args.pretrained)
    with finetune_net.name_scope():
        finetune_net.fc = nn.Dense(args.classes)
    finetune_net.fc.initialize(init.Xavier(), ctx=ctx)
    finetune_net.collect_params().reset_ctx(ctx)
    finetune_net.hybridize()

    # Define trainer
    trainer = gluon.Trainer(finetune_net.collect_params(), args.optimizer, {
        "learning_rate": args.lr,
        "momentum": args.momentum,
        "wd": args.wd
    })
    L = args.loss
    metric = args.metric

    def train(epoch):
        for i, batch in enumerate(train_data):
            data = gluon.utils.split_and_load(batch[0],
                                              ctx_list=ctx,
                                              batch_axis=0,
                                              even_split=False)
            label = gluon.utils.split_and_load(batch[1],
                                               ctx_list=ctx,
                                               batch_axis=0,
                                               even_split=False)
            with autograd.record():
                outputs = [finetune_net(X) for X in data]
                loss = [L(yhat, y) for yhat, y in zip(outputs, label)]
            for l in loss:
                l.backward()

            trainer.step(batch_size)
        mx.nd.waitall()

    def test():
        test_loss = 0
        for i, batch in enumerate(test_data):
            data = gluon.utils.split_and_load(batch[0],
                                              ctx_list=ctx,
                                              batch_axis=0,
                                              even_split=False)
            label = gluon.utils.split_and_load(batch[1],
                                               ctx_list=ctx,
                                               batch_axis=0,
                                               even_split=False)
            outputs = [finetune_net(X) for X in data]
            loss = [L(yhat, y) for yhat, y in zip(outputs, label)]

            test_loss += sum([l.mean().asscalar() for l in loss]) / len(loss)
            metric.update(label, outputs)

        _, test_acc = metric.get()
        test_loss /= len(test_data)
        reporter(mean_loss=test_loss, mean_accuracy=test_acc)

    for epoch in range(1, args.epochs + 1):
        train(epoch)
        test()
