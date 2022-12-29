import logging
import os

from ..constants import AUTOMM, RAY_TUNE_CHECKPOINT

logger = logging.getLogger(AUTOMM)


def hpo_trial(sampled_hyperparameters, predictor, checkpoint_dir=None, **_fit_args):
    from ray import tune

    _fit_args[
        "hyperparameters"
    ] = sampled_hyperparameters  # The original hyperparameters is the search space, replace it with the hyperparameters sampled
    _fit_args["save_path"] = tune.get_trial_dir()  # We want to save each trial to a separate directory
    logger.debug(f"hpo trial save_path: {_fit_args['save_path']}")
    if checkpoint_dir is not None:
        _fit_args["resume"] = True
        _fit_args["ckpt_path"] = os.path.join(checkpoint_dir, RAY_TUNE_CHECKPOINT)
    predictor._fit(**_fit_args)


def hyperparameter_tune(predictor, hyperparameter_tune_kwargs, resources, **_fit_args):
    from ray.air.config import CheckpointConfig

    from autogluon.core.hpo.ray_hpo import (
        AutommRayTuneAdapter,
        AutommRayTuneLightningAdapter,
        EmptySearchSpace,
        cleanup_checkpoints,
        cleanup_trials,
        run,
    )

    ray_tune_adapter = AutommRayTuneAdapter()
    if try_import_ray_lightning():
        ray_tune_adapter = AutommRayTuneLightningAdapter()
    search_space = _fit_args.get("hyperparameters", dict())
    metric = "val_" + _fit_args.get("validation_metric_name")
    mode = _fit_args.get("minmax_mode")
    save_path = _fit_args.get("save_path")
    time_budget_s = _fit_args.get("max_time")
    is_distill = False
    if _fit_args.get("teacher_predictor", None) is not None:
        is_distill = True
    try:
        run_config_kwargs = {
            "checkpoint_config": CheckpointConfig(
                num_to_keep=3,
                checkpoint_score_attribute=metric,
            ),
        }
        analysis = run(
            trainable=hpo_trial,
            trainable_args=_fit_args,
            search_space=search_space,
            hyperparameter_tune_kwargs=hyperparameter_tune_kwargs,
            metric=metric,
            mode=mode,
            save_dir=save_path,
            ray_tune_adapter=ray_tune_adapter,
            total_resources=resources,
            minimum_gpu_per_trial=1.0 if resources["num_gpus"] > 0 else 0.0,
            time_budget_s=time_budget_s,
            run_config_kwargs=run_config_kwargs,
            verbose=2,
        )
    except EmptySearchSpace:
        raise ValueError(
            "Please provide a search space using `hyperparameters` in order to do hyperparameter tune"
        )
    except Exception as e:
        raise e
    else:
        # find the best trial
        best_trial = analysis.get_best_trial(
            metric=metric,
            mode=mode,
        )
        if best_trial is None:
            raise ValueError(
                "MultiModalPredictor wasn't able to find the best trial."
                "Either all trials failed or"
                "it's likely that the time is not enough to train a single epoch for trials."
            )
        # clean up other trials
        logger.info("Removing non-optimal trials and only keep the best one.")
        cleanup_trials(save_path, best_trial.trial_id)
        best_trial_path = os.path.join(save_path, best_trial.trial_id)
        # reload the predictor metadata
        predictor = MultiModalPredictor._load_metadata(predictor=self, path=best_trial_path)
        # construct the model
        model = create_fusion_model(
            config=predictor._config,
            num_classes=predictor._output_shape,
            classes=predictor._classes,
            num_numerical_columns=len(predictor._df_preprocessor.numerical_feature_names),
            num_categories=predictor._df_preprocessor.categorical_num_categories,
            pretrained=False,  # set "pretrain=False" to prevent downloading online models
        )
        predictor._model = model
        # average checkpoint
        checkpoints_paths_and_scores = dict(
            (os.path.join(checkpoint, RAY_TUNE_CHECKPOINT), score)
            for checkpoint, score in analysis.get_trial_checkpoints_paths(best_trial, metric=metric)
        )
        # write checkpoint paths and scores to yaml file so that top_k_average could read it
        best_k_model_path = os.path.join(best_trial_path, BEST_K_MODELS_FILE)
        with open(best_k_model_path, "w") as yaml_file:
            yaml.dump(checkpoints_paths_and_scores, yaml_file, default_flow_style=False)

        with analysis.get_last_checkpoint(best_trial).as_directory() as last_ckpt_dir:
            predictor._top_k_average(
                model=predictor._model,
                save_path=best_trial_path,
                last_ckpt_path=last_ckpt_dir,
                minmax_mode=mode,
                is_distill=is_distill,
                top_k_average_method=predictor._config.optimization.top_k_average_method,
                val_df=_fit_args["val_df"],
                validation_metric_name=predictor._validation_metric_name,
            )
        cleanup_checkpoints(best_trial_path)
        # move trial predictor one level up
        contents = os.listdir(best_trial_path)
        for content in contents:
            shutil.move(
                os.path.join(best_trial_path, content),
                os.path.join(save_path, content),
            )
        shutil.rmtree(best_trial_path)
        predictor._save_path = save_path

        return predictor
