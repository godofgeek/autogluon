#!/bin/bash

set -ex

PR_NUMBER=$(basename $1) # For push events, this will be master branch instead of PR number
COMMIT_SHA=$2

source $(dirname "$0")/env_setup.sh

setup_build_contrib_env
setup_mxnet_gpu
export CUDA_VISIBLE_DEVICES=0
bash docs/build_pip_install.sh
# only build for docs/object_detection
shopt -s extglob
rm -rf ./docs/tutorials/!(object_detection)
cd docs && rm -rf _build && d2lbook build rst

COMMAND_EXIT_CODE=$?
if [ $COMMAND_EXIT_CODE -ne 0 ]; then
    exit COMMAND_EXIT_CODE
fi

cd ..

if [[ -n $PR_NUMBER ]]; then BUCKET=autogluon-ci S3_PATH=s3://$BUCKET/build_docs/$PR_NUMBER/$COMMIT_SHA; else BUCKET=autogluon-ci-push S3_PATH=s3://$BUCKET/build_docs/$BRANCH/$COMMIT_SHA; fi
DOC_PATH=docs/_build/rst/tutorials/object_detection/
S3_PATH=$BUCKET/object_detection/

write_to_s3 $BUCKET $DOC_PATH $S3_PATH
