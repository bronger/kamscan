=======
Kamscan
=======

Kamscan implements a camera-based scan station for documents.  It does so as a
command line tool, making the process very convennient and efficient.

It captures pictures with a photo camera and converts them to a PDF document.
Additionally, it leverages OCR software to embed the text as text in the PDF,
making the PDF searchable and indexable.


Prerequisites
=============

You need

- Unix-like OS
- Python 3.5
- Lensfun (modifier_api branch)
- gcc
- Tesseract 3.0.9
- ImageMagick 6.8
- Argyll CMS (in particular, cctiff)
- dcraw
- Python-daemon


Installation
============

1. Clone this repo.
2. ``make undistort``
3. ``./kamscan.py --help``


Camera setup
============




Limitations
===========

The limitations are serious at the current stage of development.  In fact, the
program is only useful to me, I'm afraid.

In particular, some things are hardcoded, e.g. the path to the input colour
profile of the camera or the path of the mount point of the camera on my
computer.  Also, the utility undistort.cc contains hardcoded things.  Moreover,
there is no place to add support for further camera models, especially those
with tethering support.
