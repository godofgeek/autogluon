


<div align="left">
  <img src="https://user-images.githubusercontent.com/16392542/77208906-224aa500-6aba-11ea-96bd-e81806074030.png" width="350">
</div>

## AutoML for Image, Text, Time Series, and Tabular Data

[![Latest Release](https://img.shields.io/github/v/release/autogluon/autogluon)](https://github.com/autogluon/autogluon/releases)
[![Conda Forge](https://img.shields.io/conda/vn/conda-forge/autogluon.svg)](https://anaconda.org/conda-forge/autogluon)
[![Python Versions](https://img.shields.io/badge/python-3.8%20%7C%203.9%20%7C%203.10%20%7C%203.11-blue)](https://pypi.org/project/autogluon/)
[![Downloads](https://pepy.tech/badge/autogluon/month)](https://pepy.tech/project/autogluon)
[![GitHub license](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Discord](https://img.shields.io/discord/1043248669505368144?logo=discord&style=flat)](https://discord.gg/wjUmjqAc2N)
[![Twitter](https://img.shields.io/twitter/follow/autogluon?style=social)](https://twitter.com/autogluon)
[![Continuous Integration](https://github.com/autogluon/autogluon/actions/workflows/continuous_integration.yml/badge.svg)](https://github.com/autogluon/autogluon/actions/workflows/continuous_integration.yml)
[![Platform Tests](https://github.com/autogluon/autogluon/actions/workflows/platform_tests-command.yml/badge.svg?event=schedule)](https://github.com/autogluon/autogluon/actions/workflows/platform_tests-command.yml)

[Install Instructions](https://auto.gluon.ai/stable/install.html) | [Documentation](https://auto.gluon.ai/stable/index.html) | [Release Notes](https://auto.gluon.ai/stable/whats_new/index.html)

AutoGluon automates machine learning tasks enabling you to easily achieve strong predictive performance in your applications.  With just a few lines of code, you can train and deploy high-accuracy machine learning and deep learning models on image, text, time series, and tabular data.

## Example

```python
# First install package from terminal:
# pip install autogluon

from autogluon.tabular import TabularDataset, TabularPredictor
train_data = TabularDataset('https://autogluon.s3.amazonaws.com/datasets/Inc/train.csv')
test_data = TabularDataset('https://autogluon.s3.amazonaws.com/datasets/Inc/test.csv')
predictor = TabularPredictor(label='class').fit(train_data, time_limit=120)  # Fit models for 120s
leaderboard = predictor.leaderboard(test_data)
```

| AutoGluon Task      |                                                                                Quickstart                                                                                |                                                                                API                                                                                |
|:--------------------|:------------------------------------------------------------------------------------------------------------------------------------------------------------------------:|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------:|
| TabularPredictor    | [![Quick Start](https://img.shields.io/static/v1?label=&message=tutorial&color=grey)](https://auto.gluon.ai/stable/tutorials/tabular/tabular-quick-start.html) |                 [![API](https://img.shields.io/badge/api-reference-blue.svg)](https://auto.gluon.ai/stable/api/autogluon.tabular.TabularPredictor.html)                 |
| MultiModalPredictor | [![Quick Start](https://img.shields.io/static/v1?label=&message=tutorial&color=grey)](https://auto.gluon.ai/stable/tutorials/multimodal/multimodal_prediction/multimodal-quick-start.html)            | [![API](https://img.shields.io/badge/api-reference-blue.svg)](https://auto.gluon.ai/stable/api/autogluon.multimodal.MultiModalPredictor.html) |
| TimeSeriesPredictor | [![Quick Start](https://img.shields.io/static/v1?label=&message=tutorial&color=grey)](https://auto.gluon.ai/stable/tutorials/timeseries/forecasting-quick-start.html)            | [![API](https://img.shields.io/badge/api-reference-blue.svg)](https://auto.gluon.ai/stable/api/autogluon.timeseries.TimeSeriesPredictor.html) |

## Resources

See the [AutoGluon Website](https://auto.gluon.ai/stable/index.html) for documentation and instructions on:
- [Installing AutoGluon](https://auto.gluon.ai/stable/index.html#installation)
- [Learning with tabular data](https://auto.gluon.ai/stable/tutorials/tabular/tabular-quick-start.html)
  - [Tips to maximize accuracy](https://auto.gluon.ai/stable/tutorials/tabular/tabular-essentials.html#maximizing-predictive-performance) (if **benchmarking**, make sure to run `fit()` with argument `presets='best_quality'`).

- [Learning with multimodal data (image, text, etc.)](https://auto.gluon.ai/stable/tutorials/multimodal/multimodal_prediction/multimodal-quick-start.html)
- [Learning with time series data](https://auto.gluon.ai/stable/tutorials/timeseries/forecasting-quick-start.html)

Refer to the [AutoGluon Roadmap](https://github.com/autogluon/autogluon/blob/master/ROADMAP.md) for details on upcoming features and releases.

### Hands-on Tutorials / Talks
- [AutoGluon 1.0: Shattering the AutoML Ceiling with Zero Lines of Code](https://www.youtube.com/watch?v=5tvp_Ihgnuk) (AutoML Conf, 2023)
- [AutoGluon: The Story](https://automlpodcast.com/episode/autogluon-the-story) (The AutoML Podcast, 2023)
- [AutoGluon: AutoML for Tabular, Multimodal, and Time Series Data](https://youtu.be/Lwu15m5mmbs?si=jSaFJDqkTU27C0fa) (PyData Berlin, 2023)
- [Solving Complex ML Problems in a few Lines of Code with AutoGluon](https://www.youtube.com/watch?v=J1UQUCPB88I) (PyData Seattle, 2023)
- [The AutoML Revolution](https://www.youtube.com/watch?v=VAAITEds-28) (Fall AutoML School, 2022)

### Scientific Publications
- [AutoGluon-Tabular: Robust and Accurate AutoML for Structured Data](https://arxiv.org/pdf/2003.06505.pdf) (*Arxiv*, 2020)
- [Fast, Accurate, and Simple Models for Tabular Data via Augmented Distillation](https://proceedings.neurips.cc/paper/2020/hash/62d75fb2e3075506e8837d8f55021ab1-Abstract.html) (*NeurIPS*, 2020)
- [Benchmarking Multimodal AutoML for Tabular Data with Text Fields](https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/file/9bf31c7ff062936a96d3c8bd1f8f2ff3-Paper-round2.pdf) (*NeurIPS*, 2021)
- [XTab: Cross-table Pretraining for Tabular Transformers](https://proceedings.mlr.press/v202/zhu23k/zhu23k.pdf) (*ICML*, 2023)
- [AutoGluon-TimeSeries: AutoML for Probabilistic Time Series Forecasting](https://arxiv.org/abs/2308.05566) (*AutoML Conf*, 2023)
- [TabRepo: A Large Scale Repository of Tabular Model Evaluations and its AutoML Applications](https://arxiv.org/pdf/2311.02971.pdf) (*Under Review*, 2024)

### Articles
- [AutoGluon for tabular data: 3 lines of code to achieve top 1% in Kaggle competitions](https://aws.amazon.com/blogs/opensource/machine-learning-with-autogluon-an-open-source-automl-library/) (*AWS Open Source Blog*, Mar 2020)
- [AutoGluon overview & example applications](https://towardsdatascience.com/autogluon-deep-learning-automl-5cdb4e2388ec?source=friends_link&sk=e3d17d06880ac714e47f07f39178fdf2) (*Towards Data Science*, Dec 2019)

### Train/Deploy AutoGluon in the Cloud
- [AutoGluon Cloud](https://auto.gluon.ai/cloud/stable/index.html) (Recommended)
- [AutoGluon on SageMaker AutoPilot](https://auto.gluon.ai/stable/tutorials/cloud_fit_deploy/autopilot-autogluon.html)
- [AutoGluon on Amazon SageMaker](https://auto.gluon.ai/stable/tutorials/cloud_fit_deploy/cloud-aws-sagemaker-train-deploy.html)
- [AutoGluon Deep Learning Containers](https://github.com/aws/deep-learning-containers/blob/master/available_images.md#autogluon-training-containers) (Security certified & maintained by the AutoGluon developers)
- [AutoGluon Official Docker Container](https://hub.docker.com/r/autogluon/autogluon)
- [AutoGluon-Tabular on AWS Marketplace](https://aws.amazon.com/marketplace/pp/prodview-n4zf5pmjt7ism) (Not maintained by us)

## Contributing to AutoGluon

We are actively accepting code contributions to the AutoGluon project. If you are interested in contributing to AutoGluon, please read the [Contributing Guide](https://github.com/autogluon/autogluon/blob/master/CONTRIBUTING.md) to get started.

## Citing AutoGluon

If you use AutoGluon in a scientific publication, please cite the following paper:

Erickson, Nick, et al. ["AutoGluon-Tabular: Robust and Accurate AutoML for Structured Data."](https://arxiv.org/abs/2003.06505) arXiv preprint arXiv:2003.06505 (2020).

BibTeX entry:

```bibtex
@article{agtabular,
  title={AutoGluon-Tabular: Robust and Accurate AutoML for Structured Data},
  author={Erickson, Nick and Mueller, Jonas and Shirkov, Alexander and Zhang, Hang and Larroy, Pedro and Li, Mu and Smola, Alexander},
  journal={arXiv preprint arXiv:2003.06505},
  year={2020}
}
```

If you are using AutoGluon Tabular's model distillation functionality, please cite the following paper:

Fakoor, Rasool, et al. ["Fast, Accurate, and Simple Models for Tabular Data via Augmented Distillation."](https://proceedings.neurips.cc/paper/2020/hash/62d75fb2e3075506e8837d8f55021ab1-Abstract.html) Advances in Neural Information Processing Systems 33 (2020).

BibTeX entry:

```bibtex
@article{agtabulardistill,
  title={Fast, Accurate, and Simple Models for Tabular Data via Augmented Distillation},
  author={Fakoor, Rasool and Mueller, Jonas W and Erickson, Nick and Chaudhari, Pratik and Smola, Alexander J},
  journal={Advances in Neural Information Processing Systems},
  volume={33},
  year={2020}
}
```

If you use AutoGluon's multimodal text+tabular functionality in a scientific publication, please cite the following paper:

Shi, Xingjian, et al. ["Multimodal AutoML on Structured Tables with Text Fields."](https://openreview.net/forum?id=OHAIVOOl7Vl) 8th ICML Workshop on Automated Machine Learning (AutoML). 2021.

BibTeX entry:

```bibtex
@inproceedings{agmultimodaltext,
  title={Multimodal AutoML on Structured Tables with Text Fields},
  author={Shi, Xingjian and Mueller, Jonas and Erickson, Nick and Li, Mu and Smola, Alex},
  booktitle={8th ICML Workshop on Automated Machine Learning (AutoML)},
  year={2021}
}
```

If you use AutoGluon's time series forecasting functionality in a scientific publication, please cite the following paper:
```bibtex
@inproceedings{agtimeseries,
  title={{AutoGluon-TimeSeries}: {AutoML} for Probabilistic Time Series Forecasting},
  author={Shchur, Oleksandr and Turkmen, Caner and Erickson, Nick and Shen, Huibin and Shirkov, Alexander and Hu, Tony and Wang, Yuyang},
  booktitle={International Conference on Automated Machine Learning},
  year={2023}
}
```

## License

This library is licensed under the Apache 2.0 License.
