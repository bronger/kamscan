==========
Kamscan
==========

Kamscan implements a camera-based scan station for documents.  It does so as a
command line tool, making the process very convenient and efficient.

It captures pictures with a photo camera and converts them to a PDF document.
Additionally, it leverages OCR software to embed the text as text in the PDF,
making the PDF searchable and indexable.


Prerequisites
==============

You need

- Unix-like OS
- Python 3.7
- Lensfun (modifier_api branch)
- GCC
- Tesseract 4
- pdftk
- ImageMagick 6.8
- Argyll CMS (in particular, cctiff)
- dcraw
- Kivy
- pytz
- click (Python package)
- ruamel.yaml


Installation
============

1. Clone this repo.
2. ``make undistort``

Note that you cannot simply make a link in your ``PATH`` pointing to
``kamscan.py``.  Instead, you have to write a trivial shell script named
``kamscan`` that calls it explicitly, like::

    #!/bin/sh

    PYTHONPATH=~/src python -m kamscan.kamscan "$@"

(In my case, kamscan installed in ``~/src/kamscan``.)  This is because
``kamscan.py`` uses relative imports, and it looks for its utilities in the
directory it was called in.

Then, you can call ``kamscan --help`` as a starting point.


Camera setup
===============

The camera setup must be in a way that you take pictures similar to this::

    ,--image border----------.
    |                        |
    |  ,-paper border----.   |
    |  |                  |  |
    |  |   |  |  |  |  |  |  |
    |  |   |  |  |  |  |  |  |
    |  |   |  |  |  |  |  |  |
    |  |                  |  |
    |  x-----------------´   |
    |                        |
    `-----------------------´

The code that feeds the images into the core processing units rotates these
images by 90° clockwise.  This way, any text printed on the pages is readable
without turning your head.

The setup need not be perfect.  Any inhomogeneous illumination or tilting of
the paper will be corrected.


Two-side setup
--------------

::

    ,--image border----------.
    |                        |
    |  ,-paper border----.   |
    |  |        |        |   |
    |  | -----  | -----  |   |
    |  | -----  | -----  |   |
    |  | -----  | -----  |   |
    |  |        |        |   |
    |  x--------+--------´   |
    |                        |
    `------------------------´

Usage
=======

Some hints going beyond the output of ``kamscan.py --help``:

- Profiles are stored only for one day.  After that, Kamscan assumes that they
  are inaccurate.
- Switching between different page sizes, colour modes, or two-side mode does
  not need different profiles.  Instead, create a new profile for a different
  *setup*, e.g.:

  - different illumination
  - a glass panel on top of the sheets
  - sheets in bigger distance because they are too large for the small one

  Of course, if you return to the former profile, you must be able to reproduce
  its setup accurately.
- Bear in mind that the height of the sheet used for creating the profile is
  assumed to be A4 by default.  Use ``--full-height`` with other heights.
- The alignment point for everything you scan is always the top left corner (in
  reading orientation) of the rectangle used for calibration, marked with
  “``x``” in the above diagrams.  Accordingly, the two edges of the calibration
  rectangle originating in this point are the alignment lines for everything
  you scan.


Limitations
============

Any bent pages are a problem.  They should be as flat as possible because no
correction of any curvature takes place.


Adding a new camera model
=========================

Place a new script in ``sources/``.  The name of the script (without the
``.py``) must match the name of the key in the configuration file under
“sources”.

The API that the class must fulfil is simple:

- name it “Source”
- accept the arguments “configuration” and “params” in the constructor
- define the methods “images” and “raw_to_pnm”


Constructor arguments
---------------------

“configuration” is a nested dictionary with the part of the configuration file
that belongs to the source.

“params” is the value that was passed with the ``--params`` argument on the
command line.  If no such argument was given, it is ``None``.  If it was only a
single value, it is that value.  If it was a comma-separated list of key=value
pairs, it is a dictionary with those pairs.


The method “images”
-------------------

This iterator yields the raw images from the camera in the order that they were
taken.  It yields a tuple of image index (starting with 0), whether it is the
last page, and the path to the image.  There must be at least one image in the
iterator.


The method “raw_to_pnm”
-----------------------

This method converts a camera raw file into a PNM.  It does so as raw as
possible, i.e. no corrections.  In particular, the colour space must be linear.
It takes the following parameters:

``path``
  The path to the raw file.  The output file must have the same path but with
  the extension ``.ppm`` (colour) or ``.pgm`` (grey).

``for_preview``
  (Default: ``False``.)  If ``True``, generate a pnm that looks decently
  instead of being raw.  In particular, it should be white-balanced and
  gamma-corrected.

``gray``
  (Default: ``False``.)  Whether a PGM should be produced.

``b``
  Exposure correction; all intensities are multiplied by this value.  Default
  is no exposure correction.

``asynchronous``
  (Default: ``False``.)  If ``True``, the external process that does the
  conversion is called asynchronously.

The return type depends on the last parameter ``asynchronous``.  If it is
``False``, the path to the PNM path is returned.  Otherwise, a tuple is
returned with the output path and the external process (of the type
``subprocess.Popen``).
