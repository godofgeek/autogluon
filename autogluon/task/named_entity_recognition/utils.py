import re
import sys
from collections import namedtuple

import logging

log = logging.getLogger(__name__)

TaggedToken = namedtuple('TaggedToken', ['text', 'tag'])

NULL_TAG = "X"


def read_data(name, file_path, column_format):
    """Calls specific read method based on dataset.
    
    Parameters
    ----------
    name : str
        Name of the dataset
    file_path : str
        A file path
    column_format : dict
        A dictionary contains key as an index and value as text/tag to find
        location in a file

    Returns
    -------
    List[List[TaggedToken]]:
        A list of sentences with each sentence breaks down into TaggedToken
    """
    if name.lower() == 'conll2003':
        return read_conll2003(file_path, column_format)
    elif name.lower() == 'wnut2017':
        return read_wnut2017(file_path, column_format)
    else:
        print(name.lower())
        raise NotImplementedError  # TODO: More dataset support


def read_wnut2017(file_path, column_format):
    """Reads the data from the file and convert into list of sentences.

    Parameters
    ----------
    file_path : str
        A file path
    column_format : dict
        A dictionary contains key as an index and value as text/tag to find
        location in a file

    Returns
    -------
    List[List[TaggedToken]]:
        A list of sentences with each sentence breaks down into TaggedToken
    """
    sentence_list = []
    current_sentence = []

    try:
        lines = open(
            str(file_path), encoding="utf-8"
        ).read().strip().split("\n")
    except:
        log.info(
            'UTF-8 can\'t read: {} ... using "latin-1" instead.'.format(
                file_path
            )
        )
        lines = open(
            str(file_path), encoding="latin1"
        ).read().strip().split("\n")

    # get the text and ner column
    text_column: int = sys.maxsize
    ner_column: int = sys.maxsize
    for column in column_format:
        if column_format[column].lower() == "text":
            text_column = column
        elif column_format[column].lower() == 'ner':
            ner_column = column
        else:
            raise ValueError("Invalid column type")

    for line in lines:
        if line.startswith("#"):
            continue

        if line.strip().replace("﻿", "") == "":
            if len(current_sentence) > 0:
                sentence_list.append(current_sentence)
            current_sentence = []

        else:
            fields = re.split("\s+", line)
            # token = TaggedToken(text=fields[text_column], tag=None)
            for column in column_format:
                if len(fields) > column:
                    if column != text_column:
                        token = TaggedToken(text=fields[text_column], tag=fields[column])

            current_sentence.append(token)

    if len(current_sentence) > 0:
        sentence_list.append(current_sentence)

    return sentence_list


def read_conll2003(file_path, column_format):
    """Reads the data from the file and convert into list of sentences.

    Parameters
    ----------
    file_path : str
        A file path
    column_format : dict
        A dictionary contains key as an index and value as text/tag to find
        location in a file

    Returns
    -------
    List[List[TaggedToken]]:
        A list of sentences with each sentence breaks down into TaggedToken
    """
    with open(file_path, 'r') as ifp:
        sentence_list = []
        current_sentence = []

        for line in ifp:
            if len(line.strip()) > 0:
                word, _, _, tag = line.rstrip().split(" ")
                current_sentence.append(TaggedToken(text=word, tag=tag))
            else:
                # the sentence was completed if an empty line occurred; flush the current sentence.
                sentence_list.append(current_sentence)
                current_sentence = []

        # check if there is a remaining token. in most CoNLL data files, this does not happen.
        if len(current_sentence) > 0:
            sentence_list.append(current_sentence)
        return sentence_list


def bio_to_bio2(sentences):
    """Check that tags have a valid IOB format.
    Tags in IOB1 format are converted to IOB2.

    Parameters
    ----------
    sentences : List[List[TaggedToken]]
        A list of sentences in BIO format with each sentence breaks down into TaggedToken

    Returns
    -------
    List[List[TaggedToken]]:
        A list of sentences in BIO-2 format with each sentence breaks down into TaggedToken
    """
    sentence_list = []
    current_sentence = []
    prev_tag = 'O'

    for sentence in sentences:
        for i, token in enumerate(sentence):
            tag = token.tag
            if tag == 'O':
                bio2_tag = 'O'
            else:
                if prev_tag == 'O' or tag[2:] != prev_tag[2:]:
                    bio2_tag = 'B' + tag[1:]
                else:
                    bio2_tag = tag
            current_sentence.append(TaggedToken(text=token.text, tag=bio2_tag))
            prev_tag = tag
        sentence_list.append(current_sentence)
        current_sentence = []
        prev_tag = 'O'

    # check if there is a remaining token. in most CoNLL data files, this does not happen.
    if len(current_sentence) > 0:
        sentence_list.append(current_sentence)
    return sentence_list


def bio2_to_bioes(tokens):
    """Convert a list of TaggedTokens from BIO-2 scheme to BIOES scheme.

    Parameters
    ----------
    tokens: List[TaggedToken]
        A list of tokens in BIO-2 scheme

    Returns
    -------
    List[TaggedToken]:
        A list of tokens in BIOES scheme
    """
    ret = []
    for index, token in enumerate(tokens):
        if token.tag == 'O':
            ret.append(token)
        elif token.tag.startswith('B'):
            # if a B-tag is continued by other tokens with the same entity,
            # then it is still a B-tag
            if index + 1 < len(tokens) and tokens[index + 1].tag.startswith("I"):
                ret.append(token)
            else:
                ret.append(TaggedToken(text=token.text, tag="S" + token.tag[1:]))
        elif token.tag.startswith('I'):
            # if an I-tag is continued by other tokens with the same entity,
            # then it is still an I-tag
            if index + 1 < len(tokens) and tokens[index + 1].tag.startswith("I"):
                ret.append(token)
            else:
                ret.append(TaggedToken(text=token.text, tag="E" + token.tag[1:]))
    return ret


def remove_docstart_sentence(sentences):
    """Remove -DOCSTART- sentences in the list of sentences.

    Parameters
    ----------
    sentences: List[List[TaggedToken]]
        List of sentences, each of which is a List of TaggedTokens;
        this list may contain DOCSTART sentences.

    Returns
    -------
        List of sentences, each of which is a List of TaggedTokens;
        this list does not contain DOCSTART sentences.
    """
    ret = []
    for sentence in sentences:
        current_sentence = []
        for token in sentence:
            if token.text != '-DOCSTART-':
                current_sentence.append(token)
        if len(current_sentence) > 0:
            ret.append(current_sentence)
    return ret


def bert_tokenize_sentence(sentence, bert_tokenizer):
    """Convert the text word into BERTTokenize format.

    Parameters
    ----------
    sentence : List[List[TaggedToken]]
        A list of sentences with each sentence breaks down into TaggedToken
    bert_tokenizer : gluonnlp.data.transforms
        A Bert Tokenize instance

    Returns
    -------
    List[List[TaggedToken]]:
        A list of sentences in BERT scheme
    """
    ret = []
    for token in sentence:
        # break a word into sub-word tokens
        sub_token_texts = bert_tokenizer(token.text)
        # only the first token of a word is going to be tagged
        ret.append(TaggedToken(text=sub_token_texts[0], tag=token.tag))
        ret += [TaggedToken(text=sub_token_text, tag=NULL_TAG)
                for sub_token_text in sub_token_texts[1:]]
    return ret


def load_segment(dataset_name, file_path, tokenizer, indexes_format):
    sentences = read_data(dataset_name, file_path, indexes_format)
    bio2_sentences = remove_docstart_sentence(bio_to_bio2(sentences))
    bioes_sentences = [bio2_to_bioes(sentence) for sentence in bio2_sentences]
    subword_sentences = [bert_tokenize_sentence(sentence, tokenizer) for sentence in bioes_sentences]
    return subword_sentences
