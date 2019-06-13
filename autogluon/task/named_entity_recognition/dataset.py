import os
from multiprocessing import cpu_count
from typing import AnyStr
import numpy as np
import gluonnlp as nlp
from autogluon.dataset import TextDataTransform, utils
from mxnet import gluon

from ... import dataset
from .utils import *
import logging

logger = logging.getLogger(__name__)

__all__ = ['Dataset']
NULL_TAG = "X"


class Dataset(dataset.Dataset):
    def __init__(self, name: AnyStr = None, train_path: AnyStr = None, val_path: AnyStr = None,
                 lazy: bool = True, vocab: nlp.Vocab = None, max_sequence_length: int = 300,
                 tokenizer: nlp.data.transforms = None, indexes_format: dict = None,
                 batch_size: int = 8):
        super(Dataset, self).__init__(name, train_path, val_path)
        # TODO : add search space, handle batch_size, num_workers
        self._num_classes: int = 0
        self._vocab: nlp.Vocab = vocab
        self._train_ds_transformed = None
        self._val_ds_transformed = None
        self.batch_size = batch_size
        self.max_sequence_length = max_sequence_length  # TODO This should come from config
        self.tokenizer = tokenizer
        self.indexes_format = indexes_format
        self._download_dataset()
        self.add_search_space()

        if self._vocab is None:
            _, self._vocab = nlp.model.get_model(name='bert_12_768_12',
                                                 dataset_name='book_corpus_wiki_en_cased')
            logger.info("Taking default vocabulary of pre-trained model `bert_12_768_12` "
                        "on `book_corpus_wiki_en_cased`. If you would like to use different"
                        "vocabulary then please pass parameter `vocab` as an instance of"
                        "`nlp.Vocab`.")

        # if not lazy:
        if not lazy:
            self._init_()

    def _init_(self):
        self._read_dataset()
        self.add_search_space()

    @property
    def num_classes(self) -> int:
        return self._num_classes

    @property
    def vocab(self) -> nlp.vocab:
        return self._vocab

    @vocab.setter
    def vocab(self, value: nlp.vocab) -> None:
        self.vocab = value
        self._init_()

    def _download_dataset(self) -> None:
        if self.name.lower() in {'conll2003', 'wnut2017'}:
            if self.train_path is None or self.val_path is None:
                raise ValueError("{} can't be downloaded directly from Gluon due to"
                                 "license Issue. Please provide the downloaded filepath"
                                 "as `train_path` and `val_path`".format(self.name.lower()))
        else:
            raise NotImplementedError  # TODO: Add support for more dataset

    def _read_dataset(self) -> None:
        """
        This method reads the datasets. Preprocesses the data.
        Prepares data loader from it.
        """
        self._load_dataset()
        self._preprocess()
        self._prepare_data_loader()

    def _load_dataset(self):
        """Load the dataset from file, convert into BIOES scheme and build tag
        vocabulary"""
        print("Loading the dataset...")
        if self.tokenizer is None:
            self.tokenizer = getattr(nlp.data.transforms, 'BERTTokenizer')
        self.tokenizer = self.tokenizer(vocab=self.vocab, lower=False)
        self.train_dataset = load_segment(file_path=self.train_path, tokenizer=self.tokenizer,
                                          indexes_format=self.indexes_format)
        self.val_dataset = load_segment(file_path=self.val_path, tokenizer=self.tokenizer,
                                        indexes_format=self.indexes_format)

        print("Train data length: {}".format(len(self.train_dataset)))
        print("Validation data length: {}".format(len(self.val_dataset)))

        # Build tag vocab
        print("\nBuilding tag vocabulary...")
        all_sentences = self.train_dataset + self.val_dataset
        tag_counter = nlp.data.count_tokens(token.tag for sentence in all_sentences for token in sentence)
        self.tag_vocab = nlp.Vocab(tag_counter, padding_token=NULL_TAG,
                                   bos_token=None, eos_token=None, unknown_token=None)
        self.null_tag_index = self.tag_vocab[NULL_TAG]
        self._num_classes = len(self.tag_vocab)
        print("Number of tag types: {}".format(self._num_classes))

    def encode_as_input(self, sentence):
        # check whether the given sequence can be fit into `seq_len`.
        assert len(sentence) <= self.max_sequence_length - 2, \
            'the number of tokens {} should not be larger than {} - 2. offending sentence: {}'.format(
                len(sentence), self.max_sequence_length, sentence)

        text_tokens = ([self.vocab.cls_token] + [token.text for token in sentence] +
                       [self.vocab.sep_token])
        padded_text_ids = (self.vocab.to_indices(text_tokens)
                           + [self.vocab[self.vocab.padding_token]] * (self.max_sequence_length - len(text_tokens)))

        tags = [NULL_TAG] + [token.tag for token in sentence] + [NULL_TAG]
        padded_tag_ids = (self.tag_vocab.to_indices(tags)
                          + [self.tag_vocab[NULL_TAG]] * (self.max_sequence_length - len(tags)))

        assert len(text_tokens) == len(tags)
        assert len(padded_text_ids) == len(padded_tag_ids)
        assert len(padded_text_ids) == self.max_sequence_length

        valid_length = len(text_tokens)

        # in sequence tagging problems, only one sentence is given
        token_types = [0] * self.max_sequence_length

        np_tag_ids = np.array(padded_tag_ids, dtype='int32')
        # gluon batchify cannot batchify numpy.bool? :(
        flag_nonnull_tag = (np_tag_ids != self.null_tag_index).astype('int32')

        return (np.array(padded_text_ids, dtype='int32'),
                np.array(token_types, dtype='int32'),
                np.array(valid_length, dtype='int32'),
                np_tag_ids,
                flag_nonnull_tag)

    def _preprocess(self):
        self.train_dataset = [self.encode_as_input(sentence) for sentence in self.train_dataset]
        self.val_dataset = [self.encode_as_input(sentence) for sentence in self.val_dataset]

    def _prepare_data_loader(self):
        print("Preparing dataloaders...")
        self.train_dataloader = gluon.data.DataLoader(self.train_dataset, batch_size=self.batch_size, shuffle=True,
                                                      last_batch='keep', num_workers=cpu_count())
        self.valid_dataloader = gluon.data.DataLoader(self.val_dataset, batch_size=self.batch_size, shuffle=False,
                                                      last_batch='keep', num_workers=cpu_count())
