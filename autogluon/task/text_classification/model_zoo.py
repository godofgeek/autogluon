from typing import AnyStr

import gluonnlp as nlp
import mxnet as mx
from mxnet import gluon
from mxnet.gluon import Block, HybridBlock, nn
import gluonnlp as nlp

from .dataset import *


__all__ = ['get_network', 'get_model_instances', 'models', 'LMClassifier', 'BERTClassifier', 'RoBERTaClassifier']

models = ['standard_lstm_lm_200',
          'standard_lstm_lm_650',
          'standard_lstm_lm_1500',
          'awd_lstm_lm_1150',
          'awd_lstm_lm_600',
          'bert_12_768_12',
          'bert_24_1024_16',
          'roberta_12_768_12']

def get_model_instances(name,
                        dataset_name='wikitext-2', **kwargs):
    """
    Parameters
    ----------
    name : str
        Name of the model.
    dataset_name : str or None, default 'wikitext-2'.
        The dataset name on which the pre-trained model is trained.
        For language model, options are 'wikitext-2'.
        For ELMo, Options are 'gbw' and '5bw'.
        'gbw' represents 1 Billion Word Language Model Benchmark
        http://www.statmt.org/lm-benchmark/;
        '5bw' represents a dataset of 5.5B tokens consisting of
        Wikipedia (1.9B) and all of the monolingual news crawl data from WMT 2008-2012 (3.6B).
        If specified, then the returned vocabulary is extracted from
        the training set of the dataset.
        If None, then vocab is required, for specifying embedding weight size, and is directly
        returned.
    vocab : gluonnlp.Vocab or None, default None
        Vocabulary object to be used with the language model.
        Required when dataset_name is not specified.
        None Vocabulary object is required with the ELMo model.
    pretrained : bool, default False
        Whether to load the pre-trained weights for model.
    ctx : Context, default CPU
        The context in which to load the pre-trained weights.
    root : str, default '~/.mxnet/models'
        Location for keeping the model parameters.

    Returns
    -------
    gluon.Block, gluonnlp.Vocab, (optional) gluonnlp.Vocab
    """
    if name is None:
        raise ValueError("model name cannot be passed as none for the model")
    name = name.lower()

    if 'bert' in name:
        # Currently the dataset for BERT is book corpus wiki only on gluon model zoo
        dataset_name = 'book_corpus_wiki_en_uncased'

    if name not in models:
        err_str = '{} is not among the following model list: \n\t'.format(name)
        raise ValueError(err_str)
    return nlp.model.get_model(name=name, dataset_name=dataset_name, **kwargs)

def get_network(net, ctx, *args):
    if type(net) == str:
        task_name = args.task_name
        task = tasks[task_name]
        model_name = args.bert_model
        dataset = args.bert_dataset
        pretrained_bert_parameters = args.pretrained_bert_parameters
        model_parameters = args.model_parameters
        get_pretrained = not (pretrained_bert_parameters is not None
                              or model_parameters is not None)

        use_roberta = 'roberta' in model_name
        get_model_params = {
            'name': model_name,
            'dataset_name': dataset,
            'pretrained': get_pretrained,
            'ctx': ctx,
            'use_decoder': False,
            'use_classifier': False,
        }
        # RoBERTa does not contain parameters for sentence pair classification
        if not use_roberta:
            get_model_params['use_pooler'] = True

        bert, vocabulary = nlp.model.get_model(**get_model_params)

        # initialize the rest of the parameters
        initializer = mx.init.Normal(0.02)
        # STS-B is a regression task.
        # STSBTask().class_labels returns None
        do_regression = not task.class_labels
        if do_regression:
            num_classes = 1
        else:
            num_classes = len(task.class_labels)
        # reuse the BERTClassifier class with num_classes=1 for regression
        if use_roberta:
            model = RoBERTaClassifier(bert, dropout=0.0, num_classes=num_classes)
        else:
            model = BERTClassifier(bert, dropout=0.1, num_classes=num_classes)
        # initialize classifier
        if not model_parameters:
            model.classifier.initialize(init=initializer, ctx=ctx)
    else:
        net.initialize(ctx=ctx)
    return net


class LMClassifier(gluon.Block):
    """
    Network for Text Classification which uses a pre-trained language model.
    This works with  standard_lstm_lm_200, standard_lstm_lm_650, standard_lstm_lm_1500, awd_lstm_lm_1150, awd_lstm_lm_600
    """

    def __init__(self, prefix=None, params=None, embedding=None):
        super(LMClassifier, self).__init__(prefix=prefix, params=params)
        with self.name_scope():
            self.embedding = embedding
            self.encoder = None
            self.classifier = None
            self.pool_out = None

    def forward(self, data, valid_length):  # pylint: disable=arguments-differ
        encoded = self.encoder(self.embedding(data))
        # Add mean pooling to the output of the LSTM Layers
        masked_encoded = mx.ndarray.SequenceMask(encoded, sequence_length=valid_length, use_sequence_length=True)
        self.pool_out = mx.ndarray.broadcast_div(mx.ndarray.sum(masked_encoded, axis=0),
                                             mx.ndarray.expand_dims(valid_length, axis=1))
        out = self.classifier(self.pool_out)
        return out


class BERTClassifier(gluon.Block):
    """
    Network for Text Classification which uses a BERT pre-trained model.
    This works with  bert_12_768_12, bert_24_1024_16.
    Adapted from https://github.com/dmlc/gluon-nlp/blob/master/scripts/bert/model/classification.py#L76
    """

    def __init__(self, bert, num_classes=2, dropout=0.0, prefix=None, params=None):
        super(BERTClassifier, self).__init__(prefix=prefix, params=params)
        self.bert = bert
        self.pool_out = None
        with self.name_scope():
            self.classifier = gluon.nn.HybridSequential(prefix=prefix)
            if dropout:
                self.classifier.add(gluon.nn.Dropout(rate=dropout))
            self.classifier.add(gluon.nn.Dense(units=num_classes))

    def forward(self, inputs, token_types, valid_length=None):  # pylint: disable=arguments-differ
        _, self.pooler_out = self.bert(inputs, token_types, valid_length)
        return self.classifier(self.pooler_out)

class RoBERTaClassifier(HybridBlock):
    """Model for sentence (pair) classification task with BERT.
    The model feeds token ids and token type ids into BERT to get the
    pooled BERT sequence representation, then apply a Dense layer for
    classification.
    Parameters
    ----------
    bert: RoBERTaModel
        The RoBERTa model.
    num_classes : int, default is 2
        The number of target classes.
    dropout : float or None, default 0.0.
        Dropout probability for the bert output.
    prefix : str or None
        See document of `mx.gluon.Block`.
    params : ParameterDict or None
        See document of `mx.gluon.Block`.
    Inputs:
        - **inputs**: input sequence tensor, shape (batch_size, seq_length)
        - **valid_length**: optional tensor of input sequence valid lengths.
            Shape (batch_size, num_classes).
    Outputs:
        - **output**: Regression output, shape (batch_size, num_classes)
    """

    def __init__(self, roberta, num_classes=2, dropout=0.0,
                 prefix=None, params=None):
        super(RoBERTaClassifier, self).__init__(prefix=prefix, params=params)
        self.roberta = roberta
        self._units = roberta._units
        with self.name_scope():
            self.classifier = nn.HybridSequential(prefix=prefix)
            if dropout:
                self.classifier.add(nn.Dropout(rate=dropout))
            self.classifier.add(nn.Dense(units=self._units, activation='tanh'))
            if dropout:
                self.classifier.add(nn.Dropout(rate=dropout))
            self.classifier.add(nn.Dense(units=num_classes))

    def __call__(self, inputs, valid_length=None):
        # pylint: disable=dangerous-default-value, arguments-differ
        """Generate the unnormalized score for the given the input sequences.
        Parameters
        ----------
        inputs : NDArray or Symbol, shape (batch_size, seq_length)
            Input words for the sequences.
        valid_length : NDArray or Symbol, or None, shape (batch_size)
            Valid length of the sequence. This is used to mask the padded tokens.
        Returns
        -------
        outputs : NDArray or Symbol
            Shape (batch_size, num_classes)
        """
        return super(RoBERTaClassifier, self).__call__(inputs, valid_length)

    def hybrid_forward(self, F, inputs, valid_length=None):
        # pylint: disable=arguments-differ
        """Generate the unnormalized score for the given the input sequences.
        Parameters
        ----------
        inputs : NDArray or Symbol, shape (batch_size, seq_length)
            Input words for the sequences.
        valid_length : NDArray or Symbol, or None, shape (batch_size)
            Valid length of the sequence. This is used to mask the padded tokens.
        Returns
        -------
        outputs : NDArray or Symbol
            Shape (batch_size, num_classes)
        """
        seq_out = self.roberta(inputs, valid_length)
        assert not isinstance(seq_out, (tuple, list)), 'Expected one output from RoBERTaModel'
        outputs = seq_out.slice(begin=(0, 0, 0), end=(None, 1, None))
        outputs = outputs.reshape(shape=(-1, self._units))
        return self.classifier(outputs)


class Nets(HybridBlock):
    """Model for classification task with pretrained and head models.
    """

    def __init__(self, pretrained_net, head_net, num_classes=2, dropout=0.0,
                 prefix=None, params=None):
        super(Nets, self).__init__(prefix=prefix, params=params)
        self.pretrained_net = pretrained_net
        self.head_net = head_net

    def __call__(self, inputs, token_types, valid_length=None):
        # pylint: disable=dangerous-default-value, arguments-differ
        """
        """
        # XXX Temporary hack for hybridization as hybridblock does not support None inputs
        valid_length = [] if valid_length is None else valid_length
        return super(Nets, self).__call__(inputs, token_types, valid_length)

    def hybrid_forward(self, F, inputs, token_types, valid_length=None):
        # pylint: disable=arguments-differ
        """
        """
        # XXX Temporary hack for hybridization as hybridblock does not support None
        if isinstance(valid_length, list) and len(valid_length) == 0:
            valid_length = None
        _, pooler_out = self.pretrained_net(inputs, token_types, valid_length)
        try:
            return self.head_net(pooler_out)
        except ValueError:
            raise ValueError