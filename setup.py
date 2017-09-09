#!/usr/bin/python3

from distutils.core import setup, Extension

undistort = Extension("undistort",
                      sources=["undistort.cc"],
                      include_dirs=["/usr/local/include/lensfun"],
                      libraries=["lensfun"],
                      extra_compile_args=["-std=c++11"])

setup(name="undistort",
      ext_modules=[undistort],
)
