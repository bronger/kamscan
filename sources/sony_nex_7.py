"""Plugin for the Sony NEX-7, which does not support tethering.  It supports
one parameter, which is interpreted as the path to ARW files of a previous run.
At the same time, the path to current run’s ARW files is printed after
everthing has been read from the camera.

Example settings::

  sony_nex_7:
    camera: "1"
    lenses: ["1", "2"]
    camera_mount_path: /media/bronger/3937-6637/DCIM
    reuse_dir_prefix: /tmp/kamscan_nex_7
"""

import time, os, os.path, uuid, datetime
from contextlib import contextmanager
from pathlib import Path
from ..utils import silent_call


class Source:
    """Class with abstracts the interface to a Sony NEX-7.

    :var pathlib.Path mount_path: Path to the directory which contains the
      image files if the camera's storage is mounted.  All subdirectories are
      searched for images as well.
    """

    def __init__(self, configuration, old_reuse_dir):
        """Class constructor.

        :param dict[str, object] configuration: global configuration, as read
          from ``configuration.yaml``.
        :param old_reuse_dir: directory with the ARW files; if None, they are read
          from the camera

        :type old_reuse_dir: str or NoneType
        """
        self.mount_path = Path(configuration["camera_mount_path"])
        self.reuse_dir_prefix = configuration.get("reuse_dir_prefix")
        self.old_reuse_dir = old_reuse_dir
        self.paths = None

    def _prepare_reuse_dir(self):
        if self.reuse_dir_prefix:
            reuse_dir = Path(self.reuse_dir_prefix + "-" + uuid.uuid4().hex[:8])
            os.makedirs(reuse_dir)
            return reuse_dir

    def _mount_path_exists(self):
        """Returns whether the mount point of the camera exists.

        :returns: whether the mount point of the camera exists
        :rtype: bool
        """
        cycles_left = 5
        while cycles_left:
            cycles_left -= 1
            try:
                return self.mount_path.exists()
            except PermissionError as error:
                time.sleep(1)

    @contextmanager
    def _camera_connected(self, wait_for_disconnect=True):
        """Context manager for a mounted camera storage.

        :param bool wait_for_disconnect: whether to explicitly wait for the
          camera being unplugged
        """
        if not self._mount_path_exists():
            print("Please plug-in camera.")
        while not self._mount_path_exists():
            time.sleep(1)
        yield
        if wait_for_disconnect:
            print("Please unplug camera.")
            while self._mount_path_exists():
                time.sleep(1)

    def _collect_paths(self):
        """Returns all paths on the camera storage that refer to images.

        :returns: all image paths on the camera storage
        :rtype: set[pathlib.Path]
        """
        result = set()
        for root, __, filenames in os.walk(str(self.mount_path)):
            for filename in filenames:
                if os.path.splitext(filename)[1] in {".JPG", ".ARW"}:
                    filepath = Path(root)/filename
                    result.add(filepath)
        return result

    def images(self, tempdir, for_calibration=False):
        """Returns in iterator over the new images on the camera storage.  “New” means
        here that they were added after the last call to this generator, or
        after the instatiation of this `Source` object.

        The newly found image files are removed from the camera storage.

        :param pathlib.Path tempdir: temporary directoy, managed by the caller,
          where the raw images are stored
        :param bool for_calibration: Whether the images are taken for
          calibration.  If ``True``, the ARWs are not kept, and we wait for a
          disconnect of the camera, so that a subsequent call does not
          immediately look for new images.

        :returns: iterator over the image files; each item is a tuple which
          consists of the page index (starting at zero), whether it is the last
          page, and the path to the image file
        :rtype: iterator[tuple[int, bool, pathlib.Path]]
        """
        if not for_calibration and self.old_reuse_dir:
            with os.scandir(self.old_reuse_dir) as it:
                raw_files = [Path(entry.path) for entry in it]
            silent_call(["cp", "--reflink=auto"] + list(raw_files) + [tempdir])
            raw_files.sort()
            raw_files = [tempdir/path.name for path in raw_files]
            page_count = len(raw_files)
            for page_index, raw_file in enumerate(raw_files):
                yield page_index, page_index == page_count - 1, raw_file
            return
        if self.paths is None:
            with self._camera_connected():
                self.paths = self._collect_paths()
        print("Please take pictures.  Then:")
        with self._camera_connected(wait_for_disconnect=for_calibration):
            paths = self._collect_paths()
            new_paths = paths - self.paths
            paths_with_timestamps = []
            for path in new_paths:
                output = silent_call(["exiv2", "-g", "Exif.Photo.DateTimeOriginal", path],
                                     swallow_stdout=False).stdout.strip()
                paths_with_timestamps.append((datetime.datetime.strptime(output[-19:], "%Y:%m:%d %H:%M:%S"), path))
            paths_with_timestamps.sort()
            path_tuples = set()
            page_count = 0
            for __, path in paths_with_timestamps:
                path_tuples.add((path, tempdir/path.name, tempdir/"{:06}.ARW".format(page_count), page_count))
                page_count += 1
            rsync = silent_call(["rsync"] + [path[0] for path in path_tuples] + [tempdir], asynchronous=True)
            raw_paths = set()
            if not path_tuples:
                raise Exception("No images found.")
            while path_tuples:
                for path_tuple in path_tuples:
                    old_path, intermediate_path, destination, page_index = path_tuple
                    if intermediate_path.exists():
                        os.rename(str(intermediate_path), str(destination))
                        raw_paths.add(destination)
                        os.remove(str(old_path))
                        path_tuples.remove(path_tuple)
                        yield page_index, page_index == page_count - 1, destination
                        break
            assert rsync.wait() == 0
            if not for_calibration:
                if reuse_dir := self._prepare_reuse_dir():
                    silent_call(["cp", "--reflink=auto"] + list(raw_paths) + [reuse_dir])
                    print(f"You may pass “--params {reuse_dir}” to re-use the raw files")

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
