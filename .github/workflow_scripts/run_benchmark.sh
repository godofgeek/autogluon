#!/bin/bash

set -ex

MODULE=$1
PRESET=$2
BENCHMARK=$3
TIME_LIMIT=$4
BRANCH_OR_PR_NUMBER=$5
SHA=$6

source $(dirname "$0")/env_setup.sh

setup_benchmark_env

/bin/bash CI/bench/generate_bench_config.sh $MODULE $PRESET $BENCHMARK $TIME_LIMIT $BRANCH_OR_PR_NUMBER
#copy the generated config file to test
echo "Printing the cloud config file"
cat $MODULE"_cloud_configs.yaml"
agbench run $MODULE"_cloud_configs.yaml" --wait

#if it is a PR fetch the cleaned file from master location here 
if [ $BRANCH_OR_PR_NUMBER != "master" ]
then
    aws s3 cp --recursive s3://autogluon-ci-benchmark/cleaned/master/latest/ ./results
fi

python CI/bench/evaluate.py --config_path ./ag_bench_runs/tabular/ --time_limit $TIME_LIMIT --branch_name $BRANCH_OR_PR_NUMBER
aws s3 cp --recursive ./results s3://autogluon-ci-benchmark/cleaned/$BRANCH_OR_PR_NUMBER/$SHA/
aws s3 rm --recursive s3://autogluon-ci-benchmark/cleaned/$BRANCH_OR_PR_NUMBER/latest/
aws s3 cp --recursive ./results s3://autogluon-ci-benchmark/cleaned/$BRANCH_OR_PR_NUMBER/latest/

cwd=`pwd`
echo "Printing paths and folder structure"
ls data/results/*
ls data/results/output/openml/ag_eval/pairwise/* | grep .csv > $cwd/agg_csv.txt
echo "Printing the agg_csv file"
cat agg_csv.txt
filename=`head -1 $cwd/agg_csv.txt`
prefix=$BRANCH_OR_PR_NUMBER/$SHA
agdash --per_dataset_csv  'data/results/output/openml/ag_eval/results_ranked_by_dataset_all.csv' --agg_dataset_csv $filename --s3_prefix benchmark-dashboard/$prefix --s3_bucket autogluon-staging --s3_region us-west-2 > $cwd/out.txt
tail -1 $cwd/out.txt > $cwd/website.txt
