import logging
import os
import warnings
from io import BytesIO
from typing import Any, Dict, List, Optional, Union

import numpy as np
import PIL
import pytesseract
import torch
from nptyping import NDArray
from PIL import ImageFile
from torch import nn
from torchvision import transforms
from transformers import AutoTokenizer

from ..constants import AUTOMM, BBOX
from .collator import PadCollator, StackCollator
from .utils import construct_processor, mean_std

logger = logging.getLogger(AUTOMM)

# Disable tokenizer parallelism
os.environ["TOKENIZERS_PARALLELISM"] = "false"


class DocumentProcessor:
    """
    Prepare document data for Document Classification.
    OCR (Optical character recognition) is applied to get the document texts and bounding boxes.
    Both texts and images will be processed.
    """

    def __init__(
        self,
        model: nn.Module,
        train_transform_types: List[str],
        val_transform_types: List[str],
        norm_type: Optional[str] = None,
        size: Optional[int] = None,
        text_max_len: Optional[int] = 512,
    ):
        """
        Parameters
        ----------
        model
            The model using this data processor.
        train_transform_types
            A list of image transforms used in training. Note that the transform order matters.
        val_transform_types
            A list of image transforms used in validation/test/prediction. Note that the transform order matters.
        norm_type
            How to normalize an image. We now support:
            - inception
                Normalize image by IMAGENET_INCEPTION_MEAN and IMAGENET_INCEPTION_STD from timm
            - imagenet
                Normalize image by IMAGENET_DEFAULT_MEAN and IMAGENET_DEFAULT_STD from timm
            - clip
                Normalize image by mean (0.48145466, 0.4578275, 0.40821073) and
                std (0.26862954, 0.26130258, 0.27577711), used for CLIP.
        size
            The width / height of a square image.
        text_max_len
            The max text length of tokenizer. Default: 512.
        """
        self.prefix = model.prefix
        self.model = model

        # For document image processing.
        self.size = size
        self.train_transform_types = train_transform_types
        self.val_transform_types = val_transform_types
        self.mean, self.std = mean_std(norm_type)
        self.normalization = transforms.Normalize(self.mean, self.std)
        self.train_processor = construct_processor(self.size, self.normalization, self.train_transform_types)
        self.val_processor = construct_processor(self.size, self.normalization, self.val_transform_types)

        # Store OCR results
        self.documents = {}

        # Whether only text is used (automatically detected).
        # If True, normal text foundation models (e.g., bert-base) can be used.
        self.is_text_only_flag = model.is_text_only_flag

        # For document text processing.
        self.tokenizer = model.tokenizer
        if text_max_len is None or text_max_len <= 0:
            self.text_max_len = self.tokenizer.model_max_length
        else:
            if text_max_len < self.tokenizer.model_max_length:
                warnings.warn(
                    f"provided max length: {text_max_len} "
                    f"is smaller than {model.checkpoint_name}'s default: {self.tokenizer.model_max_length}"
                )
            self.text_max_len = min(text_max_len, self.tokenizer.model_max_length)

        self.tokenizer.model_max_length = self.text_max_len

    @staticmethod
    def get_pretrained_tokenizer(
        tokenizer_name: str,
        checkpoint_name: str,
    ):
        return AutoTokenizer.from_pretrained(checkpoint_name)

    def collate_fn(self, text_column_names: Optional[List] = None) -> Dict:
        """
        Collate multimodal features into a batch.
        This function will be used when creating Pytorch DataLoader.

        Returns
        -------
        A dictionary containing one model's collator function for multimodal data.
        """
        fn = {}

        fn.update(
            {
                self.model.text_token_ids_key: PadCollator(pad_val=self.tokenizer.pad_token_id),
                self.model.text_attention_mask_key: PadCollator(pad_val=0),
                self.model.text_bbox_key: PadCollator(pad_val=0),
                self.model.text_segment_ids_key: PadCollator(pad_val=0),
            }
        )
        # If not text only, document images will be used.
        if not self.is_text_only_flag:
            fn.update(
                {
                    self.model.document_pixel_value_key: PadCollator(pad_val=0),
                }
            )
        return fn

    @staticmethod
    def normalize_box(box, width, height):
        """
        Normalize the bounding boxes.

        Parameters
        ----------
        box
            The bounding box to be processed.
        width
            Width of the document image.
        height
            Height of the document image.

        Returns
        -------
        A normalized bounding box.
        """
        return [
            int(1000 * (box[0] / width)),
            int(1000 * (box[1] / height)),
            int(1000 * (box[2] / width)),
            int(1000 * (box[3] / height)),
        ]

    def apply_ocr(self, doc_image):
        """
        Apply OCR on document images to ecognize and “read” the text embedded in document images.
        Specifically, Python-tesseract, a wrapper for Google's Tesseract-OCR Engine, will be used.

        Parameters
        ----------
        doc_image
            The document image.

        Returns
        -------
        A dictionary with recognized text and corresponding bounding boxes.
        """
        results = {}
        width, height = doc_image.size

        # apply ocr to the document image.
        ocr_df = pytesseract.image_to_data(doc_image, output_type="data.frame")
        float_cols = ocr_df.select_dtypes("float").columns
        ocr_df = ocr_df.dropna().reset_index(drop=True)
        ocr_df[float_cols] = ocr_df[float_cols].round(0).astype(int)
        ocr_df = ocr_df.replace(r"^\s*$", np.nan, regex=True)
        ocr_df = ocr_df.dropna().reset_index(drop=True)

        # get the words and actual (unnormalized) bounding boxes.
        words = list(ocr_df.text)
        words = [str(w) for w in words]
        coordinates = ocr_df[["left", "top", "width", "height"]]
        actual_boxes = []
        for idx, row in coordinates.iterrows():
            # the row comes in (left, top, width, height) format.
            x, y, w, h = tuple(row)
            # we turn it into (left, top, left+width, top+height) to get the actual box.
            actual_box = [x, y, x + w, y + h]
            actual_boxes.append(actual_box)

        # normalize the bounding boxes.
        boxes = []
        for box in actual_boxes:
            boxes.append(self.normalize_box(box, width, height))

        assert len(words) == len(boxes)

        results["words"] = words
        results[BBOX] = boxes
        return results

    def process_one_sample(
        self,
        document_features: Dict[str, Union[NDArray[(Any,), Any], list]],
        feature_modalities: Dict[str, Union[NDArray[(Any,), Any], list]],
        is_training: bool,
        image_mode: Optional[str] = "RGB",
    ):
        """
        Read documents, process them, and stack them. One sample has one document image.

        Parameters
        ----------
        document_features
            One sample has one document image column in a pd.DataFrame.
        feature_modalities
            What modality each column belongs to.
        is_training
            Whether to process document images in the training mode.
        image_mode
            A string which defines the type and depth of a pixel in the image.
            For example, RGB, RGBA, CMYK, and etc.

        Returns
        -------
        A dictionary containing one sample's document and its features.
        """
        ret = {}
        for per_col_name, per_col_image_features in document_features.items():
            # Open the document image.
            try:
                doc_image = PIL.Image.open(per_col_image_features[0])
            except Exception as e:
                raise e

            # The OCR process is time-consuming, so apply OCR on each image only once.
            if per_col_image_features[0] not in self.documents:
                ocr_res = self.apply_ocr(doc_image)
                # store the ocr results.
                self.documents.update({per_col_image_features[0]: ocr_res})
            else:
                # reuse the ocr results.
                ocr_res = self.documents[per_col_image_features[0]]

            words = ocr_res["words"]
            doc_image = doc_image.convert(image_mode)

            if is_training:
                doc_image = self.train_processor(doc_image)
            else:
                doc_image = self.val_processor(doc_image)

            normalized_word_boxes = ocr_res[BBOX]

            # Truncation of token_boxes
            token_boxes = []
            for word, box in zip(words, normalized_word_boxes):
                word_tokens = self.tokenizer.tokenize(word)
                token_boxes.extend([box] * len(word_tokens))
            pad_token_box = [0, 0, 0, 0]
            special_tokens_count = 2
            if len(token_boxes) > self.text_max_len - special_tokens_count:
                token_boxes = token_boxes[: (self.text_max_len - special_tokens_count)]
            # add bounding boxes of cls + sep tokens
            token_boxes = [[0, 0, 0, 0]] + token_boxes + [[1000, 1000, 1000, 1000]]

            if self.is_text_only_flag:
                sent = " ".join(words)
                encoding = self.tokenizer(sent, padding="max_length", truncation=True, return_token_type_ids=True)
                input_ids = self.tokenizer(sent, truncation=True)["input_ids"]
            else:
                sent = words
                encoding = self.tokenizer(
                    sent,
                    boxes=normalized_word_boxes,
                    padding="max_length",
                    truncation=True,
                    return_token_type_ids=True,
                )
                input_ids = self.tokenizer(sent, boxes=normalized_word_boxes, truncation=True)["input_ids"]

            # Padding of token_boxes up the bounding boxes to the sequence length.
            padding_length = self.text_max_len - len(input_ids)
            token_boxes += [pad_token_box] * padding_length

            ret.update(
                {
                    self.model.text_token_ids_key: np.array(encoding.input_ids, dtype=np.int32),
                    self.model.text_attention_mask_key: encoding.attention_mask,
                    self.model.text_bbox_key: np.array(token_boxes, dtype=np.int32),
                    self.model.text_segment_ids_key: np.array(encoding.token_type_ids, dtype=np.int32),
                }
            )
            if not self.is_text_only_flag:
                ret.update({self.model.document_pixel_value_key: doc_image})

        return ret

    def __call__(
        self,
        all_features: Dict[str, Union[NDArray[(Any,), Any], list]],
        feature_modalities: Dict[str, Union[NDArray[(Any,), Any], list]],
        is_training: bool,
    ) -> Dict:
        """
        Extract one sample's multimodal data.

        Parameters
        ----------
        all
            All the raw input data.
        is_training
            Whether to do processing in the training mode.

        Returns
        -------
        A dictionary containing one sample's features and/or labels.
        """

        ret = self.process_one_sample(all_features, feature_modalities, is_training)

        return ret
