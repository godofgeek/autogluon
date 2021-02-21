import os
import json
import argparse
import pandas as pd
import numpy as np
import random
from autogluon.tabular import TabularPredictor
from autogluon.text import TextPredictor


def get_parser():
    parser = argparse.ArgumentParser(description='The Basic Example of AutoML '
                                                 'for Text Prediction.')
    parser.add_argument('--train_file', type=str,
                        help='The training CSV file.',
                        default=None)
    parser.add_argument('--test_file', type=str,
                        help='The testing CSV file.',
                        default=None)
    parser.add_argument('--sample_submission', type=str,
                        help='The sample submission CSV file.',
                        default=None)
    parser.add_argument('--seed', type=int,
                        help='The seed',
                        default=123)
    parser.add_argument('--eval_metric', type=str,
                        help='The metric used to evaluate the model.',
                        default=None)
    parser.add_argument('--task', type=str,
                        choices=['product_sentiment', 'mercari_price'],
                        required=True)
    parser.add_argument('--exp_dir', type=str, default=None,
                        help='The experiment directory where the model params will be written.')
    parser.add_argument('--mode',
                        choices=['stacking', 'weighted', 'single'],
                        default='single',
                        help='Whether to use a single model or a stack ensemble. '
                             'If it is "single", If it is turned on, we will use 5-fold, 1-layer for stacking.')
    return parser


def load_machine_hack_product_sentiment(train_path, test_path):
    train_df = pd.read_csv(train_path)
    test_df = pd.read_csv(test_path)
    feature_columns = ['Product_Description', 'Product_Type']
    label_column = 'Sentiment'
    train_df = train_df[feature_columns + [label_column]]
    test_df = test_df[feature_columns]
    return train_df, test_df, label_column


def load_mercari_price_prediction(train_path, test_path):
    train_df = pd.read_csv(train_path, sep='\t')
    test_df = pd.read_csv(test_path, sep='\t')

    train_cat1 = []
    train_cat2 = []
    train_cat3 = []

    test_cat1 = []
    test_cat2 = []
    test_cat3 = []

    for ele in train_df['category_name']:
        if isinstance(ele, str):
            categories = ele.split('/', 2)
            train_cat1.append(categories[0])
            train_cat2.append(categories[1])
            train_cat3.append(categories[2])
        else:
            train_cat1.append(None)
            train_cat2.append(None)
            train_cat3.append(None)


    for ele in test_df['category_name']:
        if isinstance(ele, str):
            categories = ele.split('/', 2)
            test_cat1.append(categories[0])
            test_cat2.append(categories[1])
            test_cat3.append(categories[2])
        else:
            test_cat1.append(None)
            test_cat2.append(None)
            test_cat3.append(None)

    # Convert to log(1 + x)
    train_df.loc[:, 'price'] = np.log(train_df['price'] + 1)
    train_df.drop('category_name', axis=1)
    train_df['cat1'] = train_cat1
    train_df['cat2'] = train_cat2
    train_df['cat3'] = train_cat3

    test_df.drop('category_name', axis=1)
    test_df['cat1'] = test_cat1
    test_df['cat2'] = test_cat2
    test_df['cat3'] = test_cat3

    label_column = 'price'
    ignore_columns = ['train_id']
    feature_columns = []
    for column in sorted(train_df.columns):
        if column != label_column and column not in ignore_columns:
            feature_columns.append(column)
    train_df = train_df[feature_columns + [label_column]]
    test_df = test_df[feature_columns]
    return train_df, test_df, label_column


def set_seed(seed):
    import mxnet as mx
    import torch as th
    th.manual_seed(seed)
    mx.random.seed(seed)
    np.random.seed(seed)
    random.seed(seed)


def run(args):
    set_seed(args.seed)
    if args.task == 'product_sentiment':
        train_df, test_df, label_column = load_machine_hack_product_sentiment(args.train_file,
                                                                              args.test_file)
    elif args.task == 'mercari_price':
        train_df, test_df, label_column = load_mercari_price_prediction(args.train_file,
                                                                        args.test_file)
    else:
        raise NotImplementedError
    if args.mode == 'stacking':
        predictor = TabularPredictor(label=label_column,
                                     eval_metric=args.eval_metric,
                                     path=args.exp_dir)
        predictor.fit(train_data=train_df,
                      hyperparameters='multimodal',
                      num_bag_folds=5,
                      num_stack_levels=1)
    elif args.mode == 'weighted':
        predictor = TabularPredictor(label=label_column,
                                     eval_metric=args.eval_metric,
                                     path=args.exp_dir)
        predictor.fit(train_data=train_df,
                      hyperparameters='multimodal')
    elif args.mode == 'single':
        predictor = TextPredictor(label=label_column,
                                  eval_metric=args.eval_metric,
                                  path=args.exp_dir)
        predictor.fit(train_data=train_df,
                      seed=args.seed)
    else:
        raise NotImplementedError
    if args.task == 'product_sentiment':
        test_probabilities = predictor.predict_proba(test_df, as_pandas=True)
        test_probabilities.to_csv(os.path.join(args.exp_dir, 'submission.csv'), index=False)
    elif args.task == 'mercari_price':
        test_predictions = predictor.predict(test_df, as_pandas=True)
        submission = pd.read_csv(args.sample_submission)
        submission.loc[:, 'price'] = np.exp(test_predictions['price']) - 1
        submission.to_csv(os.path.join(args.exp_dir, 'submission.csv'), index=False)
    else:
        raise NotImplementedError


if __name__ == '__main__':
    parser = get_parser()
    args = parser.parse_args()
    run(args)
