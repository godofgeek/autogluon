import torch
import json
from torch import nn
import warnings
from transformers import AutoModel, AutoTokenizer
from ..constants import TEXT, TEXT_TOKEN_IDS, TEXT_SEGMENT_IDS, \
    TEXT_VALID_LENGTH, TEXT_SEGMENT_IDS, LABEL, LOGITS, FEATURES, WEIGHT
from typing import Optional, List, Tuple
from .utils import assign_layer_ids, init_weights


class HFAutoModelForTextPrediction(nn.Module):
    def __init__(
            self,
            prefix: str,
            checkpoint_name: str = 'microsoft/deberta-v3-base',
            num_classes: Optional[int] = 0,
    ):
        """Load a pretrained huggingface transformer backbone

        Parameters
        ----------
        prefix
            The model prefix
        checkpoint_name
            Name of the checkpoint. We support loading checkpoint from Huggingface Models list: https://huggingface.co/models
            For example, you may use
                English backbones:
                    - 'microsoft/deberta-v3-base'
                    - 'bert-base-uncased'
                    - 'google/electra-base-discriminator'
                    - 'distilroberta-base'
                Multilingual backbones:
                    - 'microsoft/mdeberta-v3-base'
                    - 'xlm-roberta-base'
        num_classes
            The number of classes
        """
        super().__init__()
        print(f"initializing {checkpoint_name}")
        self.model = AutoModel.from_pretrained(checkpoint_name)
        self.out_features = self.model.config.hidden_size

        self.head = nn.Linear(self.out_features, num_classes) if num_classes > 0 else nn.Identity()
        self.head.apply(init_weights)

        self.text_token_ids_key = f"{prefix}_{TEXT_TOKEN_IDS}"
        self.text_segment_ids_key = f"{prefix}_{TEXT_SEGMENT_IDS}"
        self.text_valid_length_key = f"{prefix}_{TEXT_VALID_LENGTH}"
        self.label_key = f"{prefix}_{LABEL}"

        self.name_to_id = self.get_layer_ids()
        self.head_layer_names = [n for n, layer_id in self.name_to_id.items() if layer_id == 0]

        if hasattr(self.model.config, 'type_vocab_size') and self.model.config.type_vocab_size <= 1:
            # Disable segment ids for models like RoBERTa
            self.disable_seg_ids = True
        else:
            self.disable_seg_ids = False

    def forward(
            self,
            batch: dict,
    ):
        """

        Parameters
        ----------
        batch
            The input batch data

        Returns
        -------

        """
        text_token_ids = batch[self.text_token_ids_key]
        if self.disable_seg_ids:
            text_segment_ids = None
        else:
            text_segment_ids = batch[self.text_segment_ids_key]
        text_valid_length = batch[self.text_valid_length_key]

        steps = torch.arange(0, text_token_ids.shape[1]).type_as(text_valid_length)
        text_masks = (steps.reshape((1, -1)) < text_valid_length.reshape((-1, 1))).type_as(text_token_ids)

        outputs = self.model(
            input_ids=text_token_ids,
            token_type_ids=text_segment_ids,
            attention_mask=text_masks,
        )
        cls_features = outputs.last_hidden_state[:, 0, :]

        logits = self.head(cls_features)

        return {
            LOGITS: logits,
            FEATURES: cls_features,
        }

    def get_layer_ids(self):
        """
        Assign id to each layer. Layer ids will be used in implementing the layer-wise learning rate decay.

        In the AutoModel scenario, this function may not always return the correct result.
        Thus, we will check

        Returns
        -------
        name_to_id
            A dictionary that contains the
        """
        model_prefix = "model"
        pre_encoder_patterns = ("embeddings", "LayerNorm", "wte", "wpe")
        post_encoder_patterns = ("head", "pooler", "ln_f")
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
