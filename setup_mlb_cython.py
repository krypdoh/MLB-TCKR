"""
Build script for mlb_ticker_utils_cython.pyx

Usage:
    python setup_mlb_cython.py build_ext --inplace

Requirements:
    pip install cython numpy
    Visual C++ Build Tools 2022 ("Desktop development with C++")
"""

from setuptools import setup, Extension
import numpy as np

try:
    from Cython.Build import cythonize
except ImportError:
    raise SystemExit("Cython is required. Install with: pip install cython")

compiler_directives = {
    "language_level": "3",
    "boundscheck": False,
    "wraparound": False,
    "cdivision": True,
    "nonecheck": False,
    "embedsignature": False,
    "optimize.use_switch": True,
    "optimize.unpack_method_calls": True,
}

import sys
if sys.platform == "win32":
    extra_compile_args = ["/O2", "/fp:fast", "/GL"]  # Global optimization
    extra_link_args = ["/LTCG"]  # Link-time code generation
else:
    extra_compile_args = ["-O3", "-ffast-math", "-march=native"]
    extra_link_args = ["-O3"]

ext = Extension(
    name="mlb_ticker_utils_cython",
    sources=["mlb_ticker_utils_cython.pyx"],
    include_dirs=[np.get_include()],
    extra_compile_args=extra_compile_args,
    extra_link_args=extra_link_args,
)

setup(
    name="mlb_ticker_utils_cython",
    ext_modules=cythonize(
        [ext],
        compiler_directives=compiler_directives,
        annotate=False,
    ),
)
