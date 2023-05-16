import time, os, os.path
from pathlib import Path
from ..utils import silent_call


class Source:
    """Class with abstracts the interface to a camera.

    :var path: Path to the directory which contains the image files if the
      camera's storage is mounted.  All subdirectories are searched for images
      as well.
    :type path: pathlib.Path
    """

    def __init__(self, configuration):
        """Class constructor.

        :param configuration: global configuration, as read from
          ``configuration.yaml``.
        :type configuration: dict[str, object]
        """
        self.path = Path(configuration["camera_mount_path"])
        with self._camera_connected():
            self.paths = self._collect_paths()

    def _path_exists(self):
        """Returns whether the mount point of the camera exists.

        :returns: whether the mount point of the camera exists
        :rtype: bool
        """
        cycles_left = 5
        while cycles_left:
            cycles_left -= 1
            try:
                return self.path.exists()
            except PermissionError as error:
                time.sleep(1)

    @contextmanager
    def _camera_connected(self, wait_for_disconnect=True):
        """Context manager for a mounted camera storage.

        :param bool wait_for_disconnect: whether to explicitly wait for the
          camera baing unplugged
        """
        if not self._path_exists():
            print("Please plug-in camera.")
        while not self._path_exists():
            time.sleep(1)
        yield
        if wait_for_disconnect:
            print("Please unplug camera.")
            while self._path_exists():
                time.sleep(1)

    def _collect_paths(self):
        """Returns all paths on the camera storage that refer to images.

        :returns: all image paths on the camera storage
        :rtype: set[pathlib.Path]
        """
        result = set()
        for root, __, filenames in os.walk(str(self.path)):
            for filename in filenames:
                if os.path.splitext(filename)[1] in {".JPG", ".ARW"}:
                    filepath = Path(root)/filename
                    result.add(filepath)
        return result

    def images(self, tempdir, wait_for_disconnect=True):
        """Returns in iterator over the new images on the camera storage.  “New” means
        here that they were added after the last call to this generator, or
        after the instatiation of this `Source` object.

        The newly found image files are removed from the camera storage.

        :param pathlib.Path tempdir: temporary directoy, managed by the caller,
          where the raw images are stored
        :param bool wait_for_disconnect: whether to explicitly wait for the
          camera baing unplugged

        :returns: iterator over the image files; each item is a tuple which
          consists of the page index (starting at zero), the number of pages,
          and the path to the image file
        :rtype: iterator[tuple[int, pathlib.Path]]
        """
        print("Please take pictures.  Then:")
        with self._camera_connected(wait_for_disconnect):
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
            while path_tuples:
                for path_tuple in path_tuples:
                    old_path, intermediate_path, destination, page_index = path_tuple
                    if intermediate_path.exists():
                        os.rename(str(intermediate_path), str(destination))
                        os.remove(str(old_path))
                        path_tuples.remove(path_tuple)
                        yield page_index, page_count, destination
                        break
            assert rsync.wait() == 0
