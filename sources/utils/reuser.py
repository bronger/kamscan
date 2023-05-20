import os, uuid
from pathlib import Path
from ...utils import silent_call


class Reuser:
    def __init__(self, configuration, old_reuse_dir):
        """Class constructor.

        :param dict[str, object] configuration: global configuration, as read
          from ``configuration.yaml``.
        :param old_reuse_dir: directory with the ARW files; if None, they are read
          from the camera

        :type old_reuse_dir: str or NoneType
        """
        self.reuse_dir_prefix = configuration.get("reuse_dir_prefix")
        self.old_reuse_dir = old_reuse_dir

    def consume_reuse_dir(self, tempdir):
        with os.scandir(self.old_reuse_dir) as it:
            raw_files = [Path(entry.path) for entry in it]
        silent_call(["cp", "--reflink=auto"] + list(raw_files) + [tempdir])
        raw_files.sort()
        raw_files = [tempdir/path.name for path in raw_files]
        page_count = len(raw_files)
        for page_index, raw_file in enumerate(raw_files):
            yield page_index, page_index == page_count - 1, raw_file

    def _prepare_reuse_dir(self):
        if self.reuse_dir_prefix:
            reuse_dir = Path(self.reuse_dir_prefix + "-" + uuid.uuid4().hex[:8])
            os.makedirs(reuse_dir)
            return reuse_dir
        
    def fill_reuse_dir(self, raw_paths):
        if reuse_dir := self._prepare_reuse_dir():
            silent_call(["cp", "--reflink=auto"] + list(raw_paths) + [reuse_dir])
            print(f"You may pass “--params {reuse_dir}” to re-use the raw files")
