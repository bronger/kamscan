"""Abstract base class for cameras supported by dcraw.  It provides the
``raw_to_pnm`` method.
"""

import time, os, os.path, uuid, datetime
from contextlib import contextmanager
from pathlib import Path
from ...utils import silent_call


class DCRawSource:
    """Abstract base class for cameras supported by dcraw.
    """

    @staticmethod
    def raw_to_pnm(path, for_preview=False, gray=False, b=None, asynchronous=False):
        """Calls dcraw to convert a raw image to a PNM file.  In case of `gray`
        being ``False``, it is a PPM file, otherwise, it is a PGM file.  If
        `for_preview` is ``True``, the colour depth is 8 bit, and various
        colour space transformations of dcraw are applied in order to make the
        result look nice.  But if `for_preview` is ``False`` (the default), the
        result is as raw as possible, i.e. 16 bit, linear, no colour space
        transformation.

        :param pathlib.Path path: path to the raw image file
        :param bool for_preview: 
        :param bool gray: wether to produce a greyscale file; if ``False``,
          demosaicing is applied
        :param float b: exposure correction; all intensities are multiplied by this
          value
        :param bool asynchronous: whether to call dcraw asynchronously

        :returns: output path of the PNM file; if dcraw was called
          asynchronously, the dcraw ``Popen`` object is returned, too
        :rtype: pathlib.Path or tuple[pathlib.Path, subprocess.Popen]
        """
        dcraw_call = ["dcraw", "-t", 5]
        if not for_preview:
            dcraw_call.extend(["-o", 0, "-M", "-6", "-g", 1, 1, "-r", 1, 1, 1, 1, "-W"])
        if gray:
            dcraw_call.append("-d")
        if b is not None:
            dcraw_call.extend(["-b", b])
        dcraw_call.append(path)
        output_path = path.with_suffix(".pgm") if "-d" in dcraw_call else path.with_suffix(".ppm")
        dcraw = silent_call(dcraw_call, asynchronous)
        if asynchronous:
            return output_path, dcraw
        else:
            assert output_path.exists()
            return output_path
