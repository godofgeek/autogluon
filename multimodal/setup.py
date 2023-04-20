#!/usr/bin/env python
###########################
# This code block is a HACK (!), but is necessary to avoid code duplication. Do NOT alter these lines.
import importlib.util
import os

from setuptools import setup

filepath = os.path.abspath(os.path.dirname(__file__))
filepath_import = os.path.join(filepath, "..", "core", "src", "autogluon", "core", "_setup_utils.py")
spec = importlib.util.spec_from_file_location("ag_min_dependencies", filepath_import)
ag = importlib.util.module_from_spec(spec)
# Identical to `from autogluon.core import _setup_utils as ag`, but works without `autogluon.core` being installed.
spec.loader.exec_module(ag)
###########################

version = ag.load_version_file()
version = ag.update_version(version)

submodule = "multimodal"
install_requires = [
    # version ranges added in ag.get_dependency_version_ranges()
    "numpy",  # version range defined in `core/_setup_utils.py`
    "scipy",  # version range defined in `core/_setup_utils.py`
    "pandas",  # version range defined in `core/_setup_utils.py`
    "scikit-learn",  # version range defined in `core/_setup_utils.py`
    "Pillow",  # version range defined in `core/_setup_utils.py`
    "tqdm",  # version range defined in `core/_setup_utils.py`
    "boto3",  # version range defined in `core/_setup_utils.py`
    "requests>=2.21,<3",
    "jsonschema>=4.14,<4.18",
    "seqeval>=1.2.2,<1.3.0",
    "evaluate>=0.2.2,<0.4.0",
    "accelerate>=0.9,<0.17",
    "timm>=0.6.12,<0.7.0",
    "torch>=1.9,<1.14",
    "torchvision<0.15.0",
    "fairscale>=0.4.5,<0.4.14",
    "scikit-image>=0.19.1,<0.20.0",
    "pytorch-lightning>=1.9.0,<1.10.0",
    "text-unidecode>=1.3,<1.4",
    "torchmetrics>=0.11.0,<0.12.0",
    "transformers>=4.23.0,<4.27.0",
    "nptyping>=1.4.4,<2.5.0",
    "omegaconf>=2.1.1,<2.3.0",
    "sentencepiece>=0.1.95,<0.2.0",
    f"autogluon.core[raytune]=={version}",
    f"autogluon.features=={version}",
    f"autogluon.common=={version}",
    "pytorch-metric-learning>=1.3.0,<2.0",
    "nlpaug>=1.1.10,<1.2.0",
    "nltk>=3.4.5,<4.0.0",
    "openmim>0.1.5,<0.4.0",
    "defusedxml>=0.7.1,<0.7.2",
    "jinja2>=3.0.3,<3.2",
    "tensorboard>=2.9,<3",
    "pytesseract>=0.3.9,<0.3.11",
    "PyMuPDF<=1.21.1",
]

install_requires = ag.get_dependency_version_ranges(install_requires)

extras_require = {
    "tests": [
        "black>=22.3,<23.0",
        "isort>=5.10",
        "datasets>=2.3.2,<=2.3.2",
        "onnx>=1.13.0,<1.14.0",
        "onnxruntime>=1.13.0,<1.14.0;platform_system=='Darwin'",
        "onnxruntime-gpu>=1.13.0,<1.14.0;platform_system!='Darwin'",
        "tensorrt>=8.5.3.1,<8.5.4;platform_system=='Linux'",
    ]
}


# Compile for grounding dino
def get_extensions():
    import glob
    import torch
    from torch.utils.cpp_extension import CUDA_HOME, CppExtension, CUDAExtension

    this_dir = os.path.dirname(os.path.abspath(__file__))
    extensions_dir = os.path.join(
        this_dir, "src", "autogluon", "multimodal", "models", "groundingdino", "models", "GroundingDINO", "csrc"
    )

    main_source = os.path.join(extensions_dir, "vision.cpp")
    sources = glob.glob(os.path.join(extensions_dir, "**", "*.cpp"))
    source_cuda = glob.glob(os.path.join(extensions_dir, "**", "*.cu")) + glob.glob(
        os.path.join(extensions_dir, "*.cu")
    )

    sources = [main_source] + sources

    extension = CppExtension

    extra_compile_args = {"cxx": []}
    define_macros = []

    if CUDA_HOME is not None and (torch.cuda.is_available() or "TORCH_CUDA_ARCH_LIST" in os.environ):
        print("Compiling with CUDA")
        extension = CUDAExtension
        sources += source_cuda
        define_macros += [("WITH_CUDA", None)]
        extra_compile_args["nvcc"] = [
            "-DCUDA_HAS_FP16=1",
            "-D__CUDA_NO_HALF_OPERATORS__",
            "-D__CUDA_NO_HALF_CONVERSIONS__",
            "-D__CUDA_NO_HALF2_OPERATORS__",
        ]
    else:
        print("Compiling without CUDA")
        define_macros += [("WITH_HIP", None)]
        extra_compile_args["nvcc"] = []
        return None

    sources = [os.path.join(extensions_dir, s) for s in sources]
    include_dirs = [extensions_dir]

    ext_modules = [
        extension(
            "autogluon.multimodal.models.groundingdino._C",
            sources,
            include_dirs=include_dirs,
            define_macros=define_macros,
            extra_compile_args=extra_compile_args,
        )
    ]

    return ext_modules


if __name__ == "__main__":
    import torch

    ag.create_version_file(version=version, submodule=submodule)
    setup_args = ag.default_setup_args(version=version, submodule=submodule)
    setup_args["package_data"]["autogluon.multimodal"] = [
        "configs/data/*.yaml",
        "configs/model/*.yaml",
        "configs/optimization/*.yaml",
        "configs/environment/*.yaml",
        "configs/distiller/*.yaml",
        "configs/matcher/*.yaml",
    ]
    setup(
        install_requires=install_requires,
        extras_require=extras_require,
        ext_modules=get_extensions(),
        cmdclass={"build_ext": torch.utils.cpp_extension.BuildExtension},
        **setup_args,
    )
