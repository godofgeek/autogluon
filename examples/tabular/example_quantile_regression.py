""" Example script for quantile regression with tabular data, demonstrating simple use-case """
import numpy as np
from autogluon.tabular import TabularDataset, TabularPredictor

# Training time:
train_data = TabularDataset('https://autogluon.s3.amazonaws.com/datasets/Inc/train.csv')  # can be local CSV file as well, returns Pandas DataFrame
train_data = train_data.head(1000)  # subsample for faster demo
print(train_data.head())

label = 'age'  # specifies which column do we want to predict
save_path = 'ag_models/'  # where to save trained models
quantile_levels = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]  # which quantiles of numeric label-variable we want to predict
num_quantiles = len(quantile_levels)

predictor = TabularPredictor(label=label, path=save_path, problem_type='quantile', quantile_levels=quantile_levels)
predictor.fit(train_data, calibrate=True, num_bag_folds=5) # calibration (conformalization)

# Inference time:
test_data = TabularDataset('https://autogluon.s3.amazonaws.com/datasets/Inc/test.csv')  # another Pandas DataFrame
predictor = TabularPredictor.load(save_path)  # Unnecessary, we reload predictor just to demonstrate how to load previously-trained predictor from file
y_pred = predictor.predict(test_data)
print(y_pred)  # each column contains estimates for one target quantile-level

# Check coverage
y_pred = y_pred.to_numpy()
y_target = test_data[label].to_numpy()
for i in range(num_quantiles // 2):
    low_idx = i
    high_idx = num_quantiles - i - 1
    low_quantile = quantile_levels[low_idx]
    high_quantile = quantile_levels[high_idx]
    pred_coverage = np.mean((y_pred[:, low_idx] <= y_target) & (y_pred[:, high_idx] >= y_target))
    target_coverage = high_quantile - low_quantile
    print("Target coverage {:.2f} => Predicted coverage {:.2f}".format(target_coverage, pred_coverage))

# Leader board
ldr = predictor.leaderboard(test_data)  # evaluate performance of every trained model
print(f"Quantile-regression evaluated using metric = {predictor.eval_metric}")
