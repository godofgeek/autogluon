from abc import abstractmethod

from ..core import *

__all__ = ['Dataset']


class Dataset(BaseAutoObject):
    def __init__(self, name, train_path=None, val_path=None, batch_size=None, num_workers=None,
                 transform_train_fn=None, transform_val_fn=None,
                 transform_train_list=None, transform_val_list=None,
                 batchify_train_fn=None, batchify_val_fn=None, **kwargs):
        # TODO (cgraywang): add search space, handle batch_size, num_workers
        super(Dataset, self).__init__()
        self.name = name
        self.train_path = train_path
        self.val_path = val_path
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.transform_train_fn = transform_train_fn
        self.transform_val_fn = transform_val_fn
        self.transform_train_list = transform_train_list
        self.transform_val_list = transform_val_list
        self.batchify_train_fn = batchify_train_fn
        self.batchify_val_fn = batchify_val_fn
        self._train = None
        self._val = None
        self._num_classes = None

    @property
    def train(self):
        return self._train

    @train.setter
    def train(self, value):
        self._train = value

    @property
    def val(self):
        return self._val

    @val.setter
    def val(self, value):
        self._val = value

    @property
    def num_classes(self):
        return self._num_classes

    @num_classes.setter
    def num_classes(self, value):
        self._num_classes = value

    @abstractmethod
    def _read_dataset(self):
        pass
