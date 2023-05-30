"""Plugin for the Sony A6000.  It supports one parameter, which is interpreted
as the path to ARW files of a previous run.  At the same time, the path to
current run’s ARW files is printed after everthing has been read from the
camera.

Example settings::

  sony_a6000:
    make: Sony
    model: ILCE-6000
    lenses: ["1", "2"]
    reuse_dir_prefix: /tmp/kamscan_a6000
"""

import time, os, os.path, uuid, datetime, subprocess
from contextlib import contextmanager
from pathlib import Path
import click
from ..utils import silent_call
from .utils.dcraw import DCRawSource
from .utils.reuser import Reuser


class Source(DCRawSource, Reuser):
    """Class with abstracts the interface to a Sony A6000.  Actually, the only
    A6000-specific thing yet is the “ARW” extension.
    """

    def __init__(self, configuration, old_reuse_dir):
        """Class constructor.

        :param dict[str, object] configuration: global configuration, as read
          from ``configuration.yaml``.
        :param old_reuse_dir: directory with the ARW files; if None, they are read
          from the camera

        :type old_reuse_dir: str or NoneType
        """
        super().__init__(configuration, old_reuse_dir)

    def images(self, tempdir, for_calibration=False):
        """Returns in iterator over the images from the camera.  With the space
        key, you take a new image, and with the enter key, you take the last
        image.

        :param pathlib.Path tempdir: temporary directoy, managed by the caller,
          where the raw images are stored
        :param bool for_calibration: Whether the images are taken for
          calibration.  If ``True``, the ARWs are not kept for re-use.

        :returns: iterator over the image files; each item is a tuple which
          consists of the page index (starting at zero), whether it is the last
          page, and the path to the image file
        :rtype: iterator[tuple[int, bool, pathlib.Path]]
        """
        if not for_calibration and self.old_reuse_dir:
            yield from self.consume_reuse_dir(tempdir)
            return
        index = 0
        last_page = False
        raw_paths = set()
        while not last_page:
            print("Please press SPACE to take a new picture, and ENTER to take the last one.")
            while (ch := click.getchar()) not in " \r":
                pass
            last_page = ch == "\r"
            if not last_page:
                print("Wait …")
            path = tempdir/f"{index:06}.ARW"
            raw_paths.add(path)
            cycles_left = 5
            while cycles_left:
                path.unlink(missing_ok=True)
                try:
                    silent_call(["gphoto2", "--capture-image-and-download", f"--filename={path}"], timeout=5)
                except subprocess.TimeoutExpired:
                    print("ERROR: gphoto2 had a timeout.  Retry.")
                else:
                    if path.exists():
                        break
                    print("ERROR: gphoto2 wrote no image.  Retry.")
                time.sleep(2)
                cycles_left -= 1
            yield index, last_page, path
            index += 1
        if not for_calibration:
            self.fill_reuse_dir(raw_paths)
