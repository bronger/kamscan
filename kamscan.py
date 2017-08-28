#!/usr/bin/python3

"""Takes pictures with a photo camera and converts them to a PDF document.
Currently, this is specific to my (Torsten Bronger) specific setup.  In
particular, some things are hardcoded, e.g. the path to the input colour
profile of the camera or the path of the mount point of the camera on my
computer.  Also, the utility undistort.cc contains hardcoded things.

This script must reside in the same director as its helpers ``undistort`` and
``analyze_scan.py``.  It requires Python 3.5.
"""

import argparse, pickle, time, os, tempfile, shutil, subprocess, json, multiprocessing, datetime
from contextlib import contextmanager
from pathlib import Path


data_root = Path.home()/"aktuell/kamscan"

parser = argparse.ArgumentParser(description="Scan a document.")
parser.add_argument("--calibration", action="store_true", help="force taking a calibration image")
parser.add_argument("--mode", default="mono", choices={"gray", "color", "mono"},
                    help="colour mode of resulting pages; defaults to mono")
parser.add_argument("--full-height", type=float, help="height of full page in cm; defaults to 29.7")
parser.add_argument("--height", type=float, help="height of to-be-scanned area in cm; defaults to full page height")
parser.add_argument("--width", type=float, help="width of to-be-scanned area in cm; defaults to full page width")
parser.add_argument("--profile", default="default", help="name of profile to use")
parser.add_argument("--debug", action="store_true", help="debug mode; in particular, don't suppress output of subprocesses")
parser.add_argument("--language", default="deu", help="three-character language code; defaults to \"deu\"")
parser.add_argument("--two-side", action="store_true", help="whether two-side images should be assumed; this swaps the "
                    "meanings of --height and --width, with --width being the width of a double page")
parser.add_argument("filepath", type=Path, help="path to the PDF file for storing")
args = parser.parse_args()

assert "/" not in args.profile
profile_root = data_root/args.profile

if args.full_height is None:
    page_height = 29.7
elif args.calibration:
    page_height = args.full_height
else:
    raise Exception("You can give --full-height only with --calibration.")


def path_to_own_program(name):
    """Returns the path to an executable which resides in the same directory as
    this script.

    :param str name: name of the executable
    :returns: full path to the executable
    :rtype: Path
    """
    return (Path(__file__).parent/name).resolve()


def silent():
    """Used in subprocess calls to redirect stdout or stderr to ``/dev/null``,
    as in::

        subprocess.check_call([...], stderr=silent())
    """
    return open(os.devnull, "w") if not args.debug else None

def silent_call(arguments, asynchronous=False, swallow_stdout=True):
    environment = os.environ.copy()
    environment["OMP_THREAD_LIMIT"] = "1"
    kwargs = {"stdout": silent() if swallow_stdout else subprocess.PIPE, "stderr": silent(), "universal_newlines": True,
              "env": environment}
    arguments = list(map(str, arguments))
    if asynchronous:
        return subprocess.Popen(arguments, **kwargs)
    else:
        kwargs["check"] = True
        return subprocess.run(arguments, **kwargs)


class Camera:
    """Class with abstracts the interface to a camera.
    """
    path = Path("/media/bronger/3937-6637/DCIM")
    """Path to the directory which contains the image files if the camera's storage
    is mounted.  All subdirectories are searched for images as well.
    """

    def __init__(self):
        with self._camera_connected():
            self.paths = self._collect_paths()

    def path_exists(self):
        cycles_left = 5
        while cycles_left:
            cycles_left -= 1
            try:
                return self.path.exists()
            except PermissionError as error:
                time.sleep(1)

    @contextmanager
    def _camera_connected(self, wait_for_disconnect=True):
        if not self.path_exists():
            print("Please plug-in camera.")
        while not self.path_exists():
            time.sleep(1)
        yield
        if wait_for_disconnect:
            print("Please unplug camera.")
            while self.path_exists():
                time.sleep(1)

    def _collect_paths(self):
        result = set()
        for root, __, filenames in os.walk(str(self.path)):
            for filename in filenames:
                if os.path.splitext(filename)[1] in {".JPG", ".ARW"}:
                    filepath = Path(root)/filename
                    result.add(filepath)
        return result

    def images(self, tempdir, wait_for_disconnect=True):
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
            page_index = 0
            for __, path in paths_with_timestamps:
                path_tuples.add((path, tempdir/path.name, tempdir/"{:06}.ARW".format(page_index), page_index))
                page_index += 1
            rsync = silent_call(["rsync"] + [path[0] for path in path_tuples] + [tempdir], asynchronous=True)
            while path_tuples:
                for path_tuple in path_tuples:
                    old_path, intermediate_path, destination, page_index = path_tuple
                    if intermediate_path.exists():
                        os.rename(str(intermediate_path), str(destination))
                        os.remove(str(old_path))
                        path_tuples.remove(path_tuple)
                        if not path_tuples and page_index != 0:
                            page_index = -1
                        yield page_index, destination
                        break
            assert rsync.wait() == 0

camera = Camera()


def call_dcraw(path, extra_raw, gray=False, b=None, asynchronous=False):
    dcraw_call = ["dcraw", "-t", 5]
    if extra_raw:
        dcraw_call.extend(["-o", 0, "-M", "-6", "-g", 1, 1, "-r", 1, 1, 1, 1, "-W"])
    if gray:
        dcraw_call.append("-d")
    if b is not None:
        dcraw_call.extend(["-b", b])
    dcraw_call.append(str(path))
    output_path = path.with_suffix(".pgm") if "-d" in dcraw_call else path.with_suffix(".ppm")
    dcraw = silent_call(dcraw_call, asynchronous)
    if asynchronous:
        return output_path, dcraw
    else:
        assert output_path.exists()
        return output_path


class CorrectionData:

    def __init__(self):
        self.coordinates = 8 * [None]
        self.height_in_cm = page_height

    def density(self, height_in_pixel):
        return height_in_pixel / (self.height_in_cm / 2.54)

    def __repr__(self):
        return "links oben: {}, {}  rechts oben: {}, {}  links unten: {}, {}  rechts unten: {}, {}".format(*self.coordinates)


def analyze_scan(x, y, scaling, filepath, number_of_points):
    def clamp(x, max_):
        return min(max(x, 0), max_ - 1)
    output = silent_call([path_to_own_program("analyze_scan.py"), clamp(x, 4000), clamp(y, 6000), scaling,
                          filepath, number_of_points], swallow_stdout=False).stdout
    result = json.loads(output)
    return result

def analyze_calibration_image():
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir = Path(tempdir)
        for index, path in camera.images(tempdir):
            if index == 0:
                path_color, dcraw_color = call_dcraw(path, extra_raw=True, asynchronous=True)
                path_gray, dcraw_gray = call_dcraw(path, extra_raw=True, gray=True, asynchronous=True)
            elif index == -1:
                ppm_path = call_dcraw(path, extra_raw=False)
                raw_points = analyze_scan(2000, 3000, 0.1, ppm_path, 4)
                points = [analyze_scan(x, y, 1, ppm_path, 1)[0] for x, y in raw_points]
            else:
                raise Exception("More than two calibration images found.")
        assert index == -1
        assert dcraw_color.wait() == 0
        assert dcraw_gray.wait() == 0
        shutil.move(str(path_color), str(profile_root/"flatfield.ppm"))
        shutil.move(str(path_gray), str(profile_root/"flatfield.pgm"))
    correction_data = CorrectionData()
    center_x = sum(point[0] for point in points) / len(points)
    center_y = sum(point[1] for point in points) / len(points)
    for point in points:
        if point[0] < center_x:
            if point[1] < center_y:
                correction_data.coordinates[0:2] = point
            else:
                correction_data.coordinates[4:6] = point
        else:
            if point[1] < center_y:
                correction_data.coordinates[2:4] = point
            else:
                correction_data.coordinates[6:8] = point
    return correction_data


def prune_profiles():
    now = datetime.datetime.now()
    minutes = (now.hour * 60 + now.minute - 5 * 60) % (24 * 60)
    minutes = max(minutes, 4 * 60)
    silent_call(["find", data_root, "-mindepth", 1, "-mmin", "+{}".format(minutes), "-delete"])
os.makedirs(str(profile_root), exist_ok=True)
prune_profiles()
calibration_file_path = profile_root/"calibration.pickle"

def get_correction_data():
    print("Calibration is necessary.  First the flat field, then for the position …")
    correction_data = analyze_calibration_image()
    pickle.dump(correction_data, open(str(calibration_file_path), "wb"))
    return correction_data

if args.calibration:
    correction_data = get_correction_data()
else:
    try:
        correction_data = pickle.load(open(str(calibration_file_path), "rb"))
    except FileNotFoundError:
        correction_data = get_correction_data()


def process_image(filepath, page_index, output_path):
    filepath = call_dcraw(filepath, extra_raw=True, gray=args.mode in {"gray", "mono"}, b=0.9)
    flatfield_path = (profile_root/"flatfield").with_suffix(".pgm" if args.mode in {"gray", "mono"} else ".ppm")
    tempfile = (filepath.parent/(filepath.stem + "-temp")).with_suffix(filepath.suffix)
    silent_call(["convert", filepath, flatfield_path, "-compose", "dividesrc", "-composite", tempfile])
    os.rename(str(tempfile), str(filepath))
    x0, y0, width, height = json.loads(
        silent_call([path_to_own_program("undistort"), filepath] + correction_data.coordinates, swallow_stdout=False).stdout)
    density = correction_data.density(height)
    if args.height is not None:
        height = (args.width if args.two_side else args.height) / 2.54 * density
    if args.width is not None:
        width = (args.height if args.two_side else args.width) / 2.54 * density
    filepath_tiff = filepath.with_suffix(".tiff")
    tempfile_tiff = tempfile.with_suffix(".tiff")
    silent_call(["convert", "-extract", "{}x{}+{}+{}".format(width, height, x0, y0), filepath, filepath_tiff])
    if args.mode == "color":
        silent_call(["cctiff", "/home/bronger/.config/darktable/color/in/nex7_matrix.icc", filepath_tiff, tempfile_tiff])
    else:
        os.rename(str(filepath_tiff), str(tempfile_tiff))
    convert_call = ["convert", tempfile_tiff, "-linear-stretch", "2%x1%"]
    if args.mode == "color":
        convert_call.extend(["-set", "colorspace", "Lab", "-depth", "8", "-colorspace", "sRGB"])
    elif args.mode == "gray":
        convert_call.extend(["-set", "colorspace", "gray", "-gamma", "2.2", "-depth", "8"])
    elif args.mode == "mono":
        convert_call.extend(["-set", "colorspace", "gray", "-level", "10%,80%",
                             "-dither", "FloydSteinberg", "-depth", "1", "-compress", "group4"])
    convert_call.extend(["-density", density, filepath_tiff])
    silent_call(convert_call)
    tiff_filepaths = set()
    if args.two_side:
        if page_index != 0:
            filepath_left_tiff = filepath_tiff.with_suffix(".0.tiff")
            left = silent_call(["convert", "-extract", "{0}x{1}+0+0".format(width, height / 2), filepath_tiff,
                                "-rotate", "-90", filepath_left_tiff], asynchronous=True)
        if page_index != -1:
            filepath_right_tiff = filepath_tiff.with_suffix(".1.tiff")
            silent_call(["convert", "-extract", "{0}x{1}+0+{1}".format(width, height / 2), filepath_tiff,
                         "-rotate", "-90", filepath_right_tiff])
        if page_index != 0:
            assert left.wait() == 0
            tiff_filepaths.add(filepath_left_tiff)
        if page_index != -1:
            tiff_filepaths.add(filepath_right_tiff)
    else:
        tiff_filepaths = {filepath_tiff}
    result = set()
    processes = set()
    for path in tiff_filepaths:
        pdf_filepath = output_path/path.with_suffix(".pdf").name
        processes.add(silent_call(["tesseract", path, pdf_filepath.parent/pdf_filepath.stem, "-l", args.language, "pdf"],
                                  asynchronous=True))
        result.add(pdf_filepath)
    for process in processes:
        assert process.wait() == 0
    return result

with tempfile.TemporaryDirectory() as tempdir:
    tempdir = Path(tempdir)
    pool = multiprocessing.Pool()
    results = set()
    for index, path in camera.images(tempdir, wait_for_disconnect=False):
        results.add(pool.apply_async(process_image, (path, index, tempdir)))
    print("Rest can be done in background.  You may now press Ctrl-Z and \"bg\" this script.")
    pool.close()
    pool.join()
    pdfs = []
    for result in results:
        pdfs.extend(result.get())
    pdfs.sort()
    silent_call(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite", "-sOutputFile={}".format(args.filepath)] +
                [pdf for pdf in pdfs])

silent_call(["evince", args.filepath])
