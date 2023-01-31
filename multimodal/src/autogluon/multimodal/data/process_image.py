import ast
import logging
import warnings
from io import BytesIO
from typing import Dict, List, Optional, Union

import numpy as np
import PIL
import torch
from PIL import ImageFile
from timm.data.constants import (
    IMAGENET_DEFAULT_MEAN,
    IMAGENET_DEFAULT_STD,
    IMAGENET_INCEPTION_MEAN,
    IMAGENET_INCEPTION_STD,
)
from torch import nn
from torchvision import transforms

from .randaug import RandAugment

try:
    from torchvision.transforms import InterpolationMode

    BICUBIC = InterpolationMode.BICUBIC
except ImportError:
    BICUBIC = PIL.Image.BICUBIC

from ..constants import (
    AUTOMM,
    CLIP,
    CLIP_IMAGE_MEAN,
    CLIP_IMAGE_STD,
    COLUMN,
    IMAGE,
    IMAGE_BYTEARRAY,
    IMAGE_PATH,
    IMAGE_VALID_NUM,
    TIMM_IMAGE,
)
from .collator import PadCollator, StackCollator
from .trivial_augmenter import TrivialAugment
from .utils import extract_value_from_config, is_rois_input

logger = logging.getLogger(AUTOMM)
ImageFile.LOAD_TRUNCATED_IMAGES = True


class ImageProcessor:
    """
    Prepare image data for the model specified by "prefix". For multiple models requiring image data,
    we need to create a ImageProcessor for each related model so that they will have independent input.
    """

    def __init__(
        self,
        model: nn.Module,
        train_transform_types: List[str],
        val_transform_types: List[str],
        norm_type: Optional[str] = None,
        size: Optional[int] = None,
        max_img_num_per_col: Optional[int] = 1,
        missing_value_strategy: Optional[str] = "zero",
        requires_column_info: bool = False,
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
            The provided width / height of a square image.
        max_img_num_per_col
            The maximum number of images one sample can have.
        missing_value_strategy
            How to deal with a missing image. We now support:
            - skip
                Skip this sample
            -zero
                Use an image with zero pixels.
        requires_column_info
            Whether to require feature column information in dataloader.
        """
        self.train_transform_types = train_transform_types
        self.val_transform_types = val_transform_types
        logger.debug(f"image training transform type: {train_transform_types}")
        logger.debug(f"image validation transform type: {val_transform_types}")

        self.prefix = model.prefix
        self.missing_value_strategy = missing_value_strategy
        self.requires_column_info = requires_column_info
        self.size = None
        self.mean = None
        self.std = None

        if model is not None:
            print(type(model), model.config)
            self.size, self.mean, self.std = self.extract_default(model.config)
            print("Extracted size=", self.size, self.mean, self.std)
        if self.size is None:
            if size is not None:
                self.size = size
                logger.debug(f"using provided image size: {self.size}")
            else:
                raise ValueError("image size is missing")
        else:
            logger.debug(f"using detected image size: {self.size}")
        if self.mean is None or self.std is None:
            if norm_type is not None:
                self.mean, self.std = self.mean_std(norm_type)
                logger.debug(f"using provided normalization: {norm_type}")
            else:
                raise ValueError("image normalization mean and std are missing")
        else:
            logger.debug(f"using detected image normalization: {self.mean} and {self.std}")
        self.normalization = transforms.Normalize(self.mean, self.std)
        self.max_img_num_per_col = max_img_num_per_col
        if max_img_num_per_col <= 0:
            logger.debug(f"max_img_num_per_col {max_img_num_per_col} is reset to 1")
            max_img_num_per_col = 1
        self.max_img_num_per_col = max_img_num_per_col
        logger.debug(f"max_img_num_per_col: {max_img_num_per_col}")

        self.train_processor = self.construct_processor(self.train_transform_types)
        self.val_processor = self.construct_processor(self.val_transform_types)

    @property
    def image_key(self):
        return f"{self.prefix}_{IMAGE}"

    @property
    def image_valid_num_key(self):
        return f"{self.prefix}_{IMAGE_VALID_NUM}"

    @property
    def image_column_prefix(self):
        return f"{self.image_key}_{COLUMN}"

    def collate_fn(self, image_column_names: Optional[List] = None, per_gpu_batch_size: Optional[int] = None) -> Dict:
        """
        Collate images into a batch. Here it pads images since the image number may
        vary from sample to sample. Samples with less images will be padded zeros.
        The valid image numbers of samples will be stacked into a vector.
        This function will be used when creating Pytorch DataLoader.

        Returns
        -------
        A dictionary containing one model's collator function for image data.
        """
        fn = {}
        if self.requires_column_info:
            assert image_column_names, "Empty image column names."
            for col_name in image_column_names:
                fn[f"{self.image_column_prefix}_{col_name}"] = StackCollator()

        fn.update(
            {
                self.image_key: PadCollator(pad_val=0),
                self.image_valid_num_key: StackCollator(),
            }
        )

        return fn

    @staticmethod
    def mean_std(norm_type: str):
        """
        Get image normalization mean and std by its name.

        Parameters
        ----------
        norm_type
            Name of image normalization.

        Returns
        -------
        Normalization mean and std.
        """
        if norm_type == "inception":
            return IMAGENET_INCEPTION_MEAN, IMAGENET_INCEPTION_STD
        elif norm_type == "imagenet":
            return IMAGENET_DEFAULT_MEAN, IMAGENET_DEFAULT_STD
        elif norm_type == "clip":
            return CLIP_IMAGE_MEAN, CLIP_IMAGE_STD
        else:
            raise ValueError(f"unknown image normalization: {norm_type}")

    def extract_default(self, config=None):
        """
        Extract some default hyper-parameters, e.g., image size, mean, and std,
        from a pre-trained (timm or huggingface) checkpoint.

        Parameters
        ----------
        checkpoint_name
            Name of a pre-trained checkpoint.

        Returns
        -------
        image_size
            Image width/height.
        mean
            Image normalization mean.
        std
            Image normalizaiton std.
        """
        if self.prefix.lower().startswith(TIMM_IMAGE):
            image_size = config["input_size"][-1]
            mean = config["mean"]
            std = config["std"]
        elif self.prefix.lower().startswith(CLIP):
            extracted = extract_value_from_config(
                config=config.to_diff_dict(),
                keys=("image_size",),
            )
            if len(extracted) == 0:
                image_size = None
            elif len(extracted) >= 1:
                image_size = extracted[0]
                if isinstance(image_size, tuple):
                    image_size = image_size[-1]
            else:
                raise ValueError(f" more than one image_size values are detected: {extracted}")
            mean = None
            std = None
        else:
            raise ValueError(f"Unknown image processor prefix: {self.prefix}")
        print(image_size, mean, std)
        return image_size, mean, std

    def construct_processor(
        self,
        transform_types: List[str],
    ) -> transforms.Compose:
        """
        Build up an image processor from the provided list of transform types.

        Parameters
        ----------
        transform_types
            A list of image transform types.

        Returns
        -------
        A torchvision transform.
        """
        processor = []
        for trans_type in transform_types:
            args = None
            kargs = None
            if "(" in trans_type:
                trans_mode = trans_type[0 : trans_type.find("(")]
                if "{" in trans_type:
                    kargs = ast.literal_eval(trans_type[trans_type.find("{") : trans_type.rfind(")")])
                else:
                    args = ast.literal_eval(trans_type[trans_type.find("(") :])
            else:
                trans_mode = trans_type

            if trans_mode == "resize_to_square":
                processor.append(transforms.Resize((self.size, self.size), interpolation=BICUBIC))
            elif trans_mode == "resize_shorter_side":
                processor.append(transforms.Resize(self.size, interpolation=BICUBIC))
            elif trans_mode == "center_crop":
                processor.append(transforms.CenterCrop(self.size))
            elif trans_mode == "horizontal_flip":
                processor.append(transforms.RandomHorizontalFlip())
            elif trans_mode == "vertical_flip":
                processor.append(transforms.RandomVerticalFlip())
            elif trans_mode == "color_jitter":
                if kargs is not None:
                    processor.append(transforms.ColorJitter(**kargs))
                elif args is not None:
                    processor.append(transforms.ColorJitter(*args))
                else:
                    processor.append(transforms.ColorJitter(brightness=0.1, contrast=0.1, saturation=0.1))
            elif trans_mode == "affine":
                if kargs is not None:
                    processor.append(transforms.RandomAffine(**kargs))
                elif args is not None:
                    processor.append(transforms.RandomAffine(*args))
                else:
                    processor.append(transforms.RandomAffine(degrees=15, translate=(0.1, 0.1), scale=(0.9, 1.1)))
            elif trans_mode == "randaug":
                if kargs is not None:
                    processor.append(RandAugment(**kargs))
                elif args is not None:
                    processor.append(RandAugment(*args))
                else:
                    processor.append(RandAugment(2, 9))
            elif trans_mode == "trivial_augment":
                processor.append(TrivialAugment(IMAGE, 30))
            else:
                raise ValueError(f"unknown transform type: {trans_mode}")

        processor.append(transforms.ToTensor())
        processor.append(self.normalization)
        return transforms.Compose(processor)

    def process_one_sample(
        self,
        image_features: Dict[str, Union[List[str], List[bytearray]]],
        feature_modalities: Dict[str, List[str]],
        is_training: bool,
        image_mode: Optional[str] = "RGB",
    ) -> Dict:
        """
        Read images, process them, and stack them. One sample can have multiple images,
        resulting in a tensor of (n, 3, size, size), where n <= max_img_num_per_col is the available image number.

        Parameters
        ----------
        image_features
            One sample may have multiple image columns in a pd.DataFrame and multiple images
            inside each image column.
        feature_modalities
            What modality each column belongs to.
        is_training
            Whether to process images in the training mode.
        image_mode
            A string which defines the type and depth of a pixel in the image.
            For example, RGB, RGBA, CMYK, and etc.

        Returns
        -------
        A dictionary containing one sample's images and their number.
        """
        images = []
        zero_images = []
        ret = {}
        column_start = 0

        for per_col_name, per_col_image_features in image_features.items():
            for img_feature in per_col_image_features[: self.max_img_num_per_col]:
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message=(
                            "Palette images with Transparency expressed in bytes should be converted to RGBA images"
                        ),
                    )
                    is_zero_img = False
                    try:
                        if feature_modalities.get(per_col_name) == IMAGE_BYTEARRAY:
                            image_feature = BytesIO(img_feature)
                        else:
                            image_feature = img_feature
                        with PIL.Image.open(image_feature) as img:
                            img = img.convert(image_mode)
                    except Exception as e:
                        if self.missing_value_strategy.lower() == "zero":
                            logger.debug(f"Using a zero image due to '{e}'")
                            img = PIL.Image.new(image_mode, (self.size, self.size), color=0)
                            is_zero_img = True
                        else:
                            raise e

                if is_training:
                    img = self.train_processor(img)
                else:
                    img = self.val_processor(img)

                if is_zero_img:
                    zero_images.append(img)
                else:
                    images.append(img)

            if self.requires_column_info:
                # only count the valid images since they are put ahead of the zero images in the below returning
                ret[f"{self.image_column_prefix}_{per_col_name}"] = np.array(
                    [column_start, len(images)], dtype=np.int64
                )
                column_start = len(images)

        ret.update(
            {
                self.image_key: torch.tensor([])
                if len(images + zero_images) == 0
                else torch.stack(images + zero_images, dim=0),
                self.image_valid_num_key: len(images),
            }
        )
        return ret

    def __call__(
        self,
        images: Dict[str, List[str]],
        feature_modalities: Dict[str, Union[int, float, list]],
        is_training: bool,
    ) -> Dict:
        """
        Obtain one sample's images and customized them for a specific model.

        Parameters
        ----------
        images
            Images of one sample.
        feature_modalities
            The modality of the feature columns.
        is_training
            Whether to process images in the training mode.

        Returns
        -------
        A dictionary containing one sample's processed images and their number.
        """
        images = {k: [v] if isinstance(v, str) else v for k, v in images.items()}

        return self.process_one_sample(images, feature_modalities, is_training)

    def __getstate__(self):
        odict = self.__dict__.copy()  # get attribute dictionary
        del odict["train_processor"]  # remove augmenter to support pickle
        return odict

    def __setstate__(self, state):
        self.__dict__ = state
        if len(state["train_transform_types"]) > 0:
            self.train_processor = self.construct_processor(self.train_transform_types)
