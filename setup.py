#!/usr/bin/python3

from distutils.core import setup, Extension

undistort = Extension("undistort",
                      sources=["undistort.cc"],
                      libraries=["lensfun"],
                      extra_compile_args=["-std=c++11"])

setup(name="undistort",
      ext_modules=[undistort],
)
