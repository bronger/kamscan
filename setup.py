#!/usr/bin/env python

from distutils.core import setup, Extension

undistort = Extension("undistort",
                      sources=["undistort.cc"],
                      libraries=["lensfun"])

setup(name="undistort",
      ext_modules=[undistort],
)
