import os
import mxnet as mx
from tqdm.auto import tqdm
from collections import OrderedDict

from ...utils import collect_params
from ..enas import ENAS_Scheduler
from .enas_utils import *
from .torch_utils import AverageMeter
from .dataset import get_dataset, get_transform

class Torch_ENAS_Scheduler(ENAS_Scheduler):
    """ENAS Scheduler, which automatically creates LSTM controller based on the search spaces.
    """
    def __init__(self, supernet, train_fn=default_train_fn, eval_fn=default_val_fn,
                 *args, **kwargs):
        super(Torch_ENAS_Scheduler, self).__init__(supernet, train_fn=train_fn, eval_fn=eval_fn,
                                                   *args, **kwargs)

    def initialize_miscs(self, train_set, val_set, batch_size, num_cpus, num_gpus,
                         train_args, val_args):
        """Initialize framework related miscs, such as train/val data and train/val
        function arguments.
        """
        criterion = torch.nn.CrossEntropyLoss()
        if num_gpus > 0:
            self.supernet.cuda()
            self.supernet = torch.nn.DataParallel(self.supernet, device_ids=list(range(num_gpus)))
        # init datasets
        if isinstance(train_set, str):
            dataset_name = train_set
            transform_train, transform_val = get_transform(dataset_name)
            train_set = get_dataset(dataset_name, root=os.path.dirname(self.checkname),
                                    transform=transform_train, train=True, download=True)
            val_set = get_dataset(dataset_name, root=os.path.dirname(self.checkname),
                                 transform=transform_val, train=False, download=True)
        self.train_data = torch.utils.data.DataLoader(
                train_set, batch_size=batch_size, shuffle=True,
                num_workers=num_cpus, pin_memory=True, drop_last=True)
        # very important, make shuffle for training contoller
        self.val_data = torch.utils.data.DataLoader(
                val_set, batch_size=batch_size, shuffle=True,
                num_workers=num_cpus, pin_memory=True)
        self.train_args = init_default_train_args(
                self.supernet, base_lr=0.1, epochs=self.epochs, iters_per_epoch=len(train_set),
                criterion=criterion) if len(train_args) == 0 else train_args
        self.val_args = val_args
        self.train_args['use_cuda'] = True if num_gpus > 0 else False
        self.val_args['use_cuda'] = True if num_gpus > 0 else False

    def run(self):
        tq = tqdm(range(self.epochs))
        for epoch in tq:
            # for recordio data
            tbar = tqdm(enumerate(self.train_data))
            for i, (data, label) in tbar:
                # sample network configuration
                self.supernet.train()
                config = self.controller.pre_sample()[0]
                self.supernet.sample(**config)
                self.train_fn(self.supernet, data, label, i, epoch, **self.train_args)
                if epoch >= self.warmup_epochs and (i % self.update_arch_frequency) == 0:
                    self.train_controller()
                if self.plot_frequency > 0 and i % self.plot_frequency == 0:
                    from IPython.display import SVG, display, clear_output
                    clear_output(wait=True)
                    graph = self.supernet.graph
                    graph.attr(rankdir='LR', size='8,3')
                    display(SVG(graph._repr_svg_()))
                tbar.set_description('epoch {}, iter {}, val_acc: {}, avg reward: {}' \
                        .format(epoch, i, self.val_acc, self.baseline))
            self.validation()
            self.save()
            tq.set_description('epoch {}, val_acc: {}, avg reward: {}' \
                        .format(epoch, self.val_acc, self.baseline))

    def validation(self):
        self.supernet.eval()
        # data iter
        tbar = tqdm(enumerate(self.val_data))
        # update network arc
        config = self.controller.inference()
        self.supernet.sample(**config)
        metric = AverageMeter()
        for i, (data, label) in tbar:
            acc = self.eval_fn(self.supernet, data, label, metric=metric, **self.val_args)
            reward = metric.avg
            tbar.set_description('Acc: {}'.format(reward))

        self.val_acc = reward
        self.training_history.append(reward)

    def train_controller(self):
        """Run multiple number of trials
        """
        self.supernet.eval()
        decay = self.ema_decay
        if hasattr(self.val_data, 'reset'): self.val_data.reset()
        # update 
        metric = AverageMeter()
        with mx.autograd.record():
            # sample controller_batch_size number of configurations
            configs, log_probs, entropies = self._sample_controller()
            for i, (data, label) in enumerate(self.val_data):
                if i >= self.controller_batch_size: break
                self.supernet.sample(**configs[i])
                # schedule the training tasks and gather the reward
                acc = self.eval_fn(self.supernet, data, label, metric=metric, **self.val_args)
                reward = self.reward_fn(acc.item(), self.supernet)
                self.baseline = reward if not self.baseline else self.baseline
                # substract baseline
                avg_rewards = mx.nd.array([reward - self.baseline],
                                          ctx=self.controller.context)
                # EMA baseline
                self.baseline = decay * self.baseline + (1 - decay) * reward
                # negative policy gradient
                log_prob = log_probs[i]
                log_prob = log_prob.sum()
                loss = - log_prob * avg_rewards
                loss = loss.sum()
        # update
        loss.backward()
        self.controller_optimizer.step(self.controller_batch_size)
        self._prefetch_controller()

    def state_dict(self, destination=None):
        if destination is None:
            destination = OrderedDict()
            destination._metadata = OrderedDict()
        destination['supernet_params'] = self.supernet.state_dict()
        destination['controller_params'] = collect_params(self.controller)
        destination['training_history'] = self.training_history
        return destination

    def load_state_dict(self, state_dict):
        self.supernet.load_state_dict(state_dict['supernet_params'])
        update_params(self.controller, state_dict['controller_params'], ctx=self.controller.context)
        self.training_history = state_dict['training_history']
