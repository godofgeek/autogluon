""" Example: distilling AutoGluon's ensemble-predictor into a single model for regression. """

import os
from autogluon import TabularPrediction as task
from autogluon.utils.tabular import REGRESSION

subsample_size = 500
time_limits = 60
savedir = 'agModels/'
# shutil.rmtree(savedir, ignore_errors=True)  # Delete AutoGluon output directory to ensure previous runs' information has been removed.

regression_dataset = {'url': 'https://autogluon.s3-us-west-2.amazonaws.com/datasets/AmesHousingPriceRegression.zip',
                      'name': 'AmesHousingPriceRegression', 'problem_type': REGRESSION,
                      'label_column': 'SalePrice'}

dataset = regression_dataset
directory = dataset['name'] + "/"

train_file = 'train_data.csv'
test_file = 'test_data.csv'
train_file_path = directory + train_file
test_file_path = directory + test_file

if (not os.path.exists(train_file_path)) or (not os.path.exists(test_file_path)):  # fetch files from s3:
    print("%s data not found locally, so fetching from %s" % (dataset['name'],  dataset['url']))
    os.system("wget " + dataset['url'] + " -O temp.zip && unzip -o temp.zip && rm temp.zip")

train_data = task.Dataset(file_path=train_file_path)
test_data = task.Dataset(file_path=test_file_path)
train_data = train_data.head(subsample_size) # subsample for faster demo
test_data = test_data.head(subsample_size) # subsample for faster run
label_column = dataset['label_column']

# Fit model ensemble:
predictor = task.fit(train_data=train_data, label=label_column, output_directory=savedir,
                     cache_data=True, auto_stack=True, time_limits=time_limits, eval_metric='mean_absolute_error')

# Distill ensemble-predictor into single model:
time_limits = 60  # set = None to fully train distilled models

# aug_data below is optional, but this could be additional unlabeled data you may have. Here we use the training data for demonstration, but you should only use new data here:
aug_data = task.Dataset(file_path=train_file_path)
aug_data = aug_data.head(subsample_size)  # subsample for faster demo

distilled_model_names = predictor.distill(time_limits=time_limits, augment_args={'num_augmented_samples':100})  # default distillation (time_limits & augment_args are also optional, here set to suboptimal values to ensure quick runtime)

# Other variants demonstrating different usage options:
predictor.distill(time_limits=time_limits, hyperparameters={'GBM':{},'NN':{}}, teacher_preds='soft', augment_method='spunge', augment_args={'size_factor':1}, verbosity=3, models_name_suffix='spunge')

predictor.distill(time_limits=time_limits, teacher_preds='soft', augment_method='munge', augment_args={'size_factor':1,'max_size':100}, models_name_suffix='munge')

predictor.distill(augmentation_data=aug_data, time_limits=time_limits, teacher_preds='soft', models_name_suffix='extra')  # augmentation with "extra" unlabeled data.

predictor.distill(time_limits=time_limits, teacher_preds=None, models_name_suffix='noteacher')  # standard training without distillation.

# Compare performance of different models on test data after distillation:
ldr = predictor.leaderboard(test_data)
model_todeploy = distilled_model_names[0]

y_pred = predictor.predict(test_data, model_todeploy)
print(y_pred[:5])
