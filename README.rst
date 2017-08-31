==========
Kamscan
==========

Kamscan implements a camera-based scan station for documents.  It does so as a
command line tool, making the process very convennient and efficient.

It captures pictures with a photo camera and converts them to a PDF document.
Additionally, it leverages OCR software to embed the text as text in the PDF,
making the PDF searchable and indexable.


Prerequisites
==============

You need

- Unix-like OS
- Python 3.5
- Lensfun (modifier_api branch)
- GCC
- Tesseract 4
- pdftk
- ImageMagick 6.8
- Argyll CMS (in particular, cctiff)
- dcraw
- Kivy


Installation
============

1. Clone this repo.
2. ``make undistort``
3. ``./kamscan.py --help``

Note that you cannot simply make a link in your ``PATH`` pointing to
``kamscan.py``.  Instead, you have to write a trivial shell script that calls
it explicitly, like::

    #!/bin/sh

    ~/src/kamscan/kamscan.py "$@"

This is because ``kamscan.py`` looks for its utilities in the directory it was
called in.


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

The limitations are serious at the current stage of development.  In fact, the
program is only useful to me, I'm afraid.

In particular, some things are hardcoded, e.g. the path to the input colour
profile of the camera or the path of the mount point of the camera on my
computer.  Also, the utility undistort.cc contains hardcoded things.  Moreover,
there is no place yet to add support for further camera models, especially
those with tethering support.

Moreover, any bent pages are a problem.  They should be as flat as possible
because no correction of any curvature takes place.
