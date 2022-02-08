import torch
import json
from torch import nn
from timm import create_model
from .utils import assign_layer_ids, init_weights
from ..constants import IMAGE, IMAGE_VALID_NUM, LABEL, LOGITS, FEATURES
from typing import Optional


class TimmAutoModelForImagePrediction(nn.Module):
    def __init__(
            self,
            prefix: str,
            checkpoint_name: str,
            num_classes: Optional[int] = 0,
            mix_choice: Optional[str] = "all_logits",
    ):
        super().__init__()
        # if num_classes==0, then create_model would automatically set self.model.head = nn.Identity()
        print(f"initializing {checkpoint_name}")
        self.model = create_model(checkpoint_name, pretrained=True, num_classes=0)
        self.out_features = self.model.num_features
        self.head = nn.Linear(self.out_features, num_classes) if num_classes > 0 else nn.Identity()
        self.head.apply(init_weights)

        self.mix_choice = mix_choice
        print(f"mix_choice: {mix_choice}")

        self.image_key = f"{prefix}_{IMAGE}"
        self.image_valid_num_key = f"{prefix}_{IMAGE_VALID_NUM}"
        self.label_key = f"{prefix}_{LABEL}"

        self.name_to_id = self.get_layer_ids()
        self.head_layer_names = [n for n, layer_id in self.name_to_id.items() if layer_id == 0]

    def forward(
            self,
            batch: dict,
    ):
        images = batch[self.image_key]
        image_valid_num = batch[self.image_valid_num_key]
        if self.mix_choice == "all_images":  # mix inputs
            mixed_images = images.sum(dim=1) / image_valid_num[:, None, None, None]  # mixed shape: (b, 3, h, w)
            features = self.model(mixed_images)
            logits = self.head(features)

        elif self.mix_choice == "all_logits":  # mix outputs
            b, n, c, h, w = images.shape  # n <= max_img_num_per_col
            features = self.model(images.reshape((b * n, c, h, w)))  # (b*n, num_features)
            logits = self.head(features)
            steps = torch.arange(0, n).type_as(image_valid_num)
            image_masks = (steps.reshape((1, -1)) < image_valid_num.reshape((-1, 1))).type_as(logits)  # (b, n)
            features = features.reshape((b, n, -1)) * image_masks[:, :, None]  # (b, n, num_features)
            logits = logits.reshape((b, n, -1)) * image_masks[:, :, None]  # (b, n, num_classes)
            features = features.sum(dim=1)  # (b, num_features)
            logits = logits.sum(dim=1)  # (b, num_classes)

        else:
            raise ValueError(f"unknown mix_choice: {self.mix_choice}")

        return {
            LOGITS: logits,
            FEATURES: features,
        }

    def get_layer_ids(self,):
        """
        Assign id to each layer. Layer ids will be used in layerwise lr decay.
        Returns
        -------

        """
        model_prefix = "model"
        pre_encoder_patterns = ("embed", "cls_token", "stem", "bn1", "conv1")
        post_encoder_patterns = ("head", "norm", "bn2")
        names = [n for n, _ in self.named_parameters()]

        name_to_id, names = assign_layer_ids(
            names=names,
            pre_encoder_patterns=pre_encoder_patterns,
            post_encoder_patterns=post_encoder_patterns,
            model_pre=model_prefix,
        )

        if len(names) > 0:
            print(f"outer layers are treated as head: {names}")
        for n in names:
            assert n not in name_to_id
            name_to_id[n] = 0

        return name_to_id
