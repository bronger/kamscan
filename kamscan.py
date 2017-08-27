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

def silent_call(arguments):
    subprocess.check_call(arguments, stdout=silent(), stderr=silent())

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
        while True:
            try:
                return self.path.exists()
            except PermissionError as error:
                print(error)
                time.sleep(1)

    @contextmanager
    def _camera_connected(self, wait_for_disconnect=True):
        if not self.path_exists():
            print("Bitte Kamera einstöpseln.")
        while not self.path_exists():
            time.sleep(1)
        yield
        if wait_for_disconnect:
            print("Bitte Kamera ausstöpseln.")
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
        print("Bitte Bilder machen.  Dann:")
        with self._camera_connected(wait_for_disconnect):
            paths = self._collect_paths()
            new_paths = paths - self.paths
            paths_with_timestamps = []
            for path in new_paths:
                output = subprocess.check_output(
                    ["exiv2", "-g", "Exif.Photo.DateTimeOriginal", str(path)], stderr=silent()).decode().strip()
                paths_with_timestamps.append((datetime.datetime.strptime(output[-19:], "%Y:%m:%d %H:%M:%S"), path))
            paths_with_timestamps.sort()
            path_tripletts = set()
            i = 0
            for __, path in paths_with_timestamps:
                path_tripletts.add((path, tempdir/path.name, tempdir/"{:06}.ARW".format(i)))
                i += 1
            rsync = subprocess.Popen(["rsync"] + [str(path[0]) for path in path_tripletts] + [str(tempdir)],
                                     stdout=silent(), stderr=silent())
            while path_tripletts:
                for triplett in path_tripletts:
                    old_path, intermediate_path, destination = triplett
                    if intermediate_path.exists():
                        os.rename(str(intermediate_path), str(destination))
                        os.remove(str(old_path))
                        path_tripletts.remove(triplett)
                        yield destination
                        break
            assert rsync.wait() == 0

camera = Camera()


def call_dcraw(path, extra_raw, gray=False, b=None, asynchronous=False):
    dcraw_call = ["dcraw", "-t", "5"]
    if extra_raw:
        dcraw_call.extend(["-o", "0", "-M", "-6", "-g", "1", "1", "-r", "1", "1", "1", "1", "-W"])
    if gray:
        dcraw_call.append("-d")
    if b is not None:
        dcraw_call.extend(["-b", str(b)])
    dcraw_call.append(str(path))
    output_path = path.with_suffix(".pgm") if "-d" in dcraw_call else path.with_suffix(".ppm")
    if asynchronous:
        dcraw = subprocess.Popen(dcraw_call, stdout=silent(), stderr=silent())
        return output_path, dcraw
    else:
        silent_call(dcraw_call)
        assert output_path.exists()
        return output_path


class CorrectionData:

    def __init__(self):
        self.coordinates = 8 * [None]
        self.height_in_cm = page_height

    def coordinates_as_strings(self):
        return [str(coordinate) for coordinate in self.coordinates]

    def density(self, height_in_pixel):
        return height_in_pixel / (self.height_in_cm / 2.54)

    def __repr__(self):
        return "links oben: {}, {}  rechts oben: {}, {}  links unten: {}, {}  rechts unten: {}, {}".format(*self.coordinates)


def analyze_scan(x, y, scaling, filepath, number_of_points):
    output = subprocess.check_output([str(path_to_own_program("analyze_scan.py")), str(x), str(y), str(scaling),
                                      str(filepath), str(number_of_points)], stderr=silent()).decode()
    result = json.loads(output)
    return result

def analyze_calibration_image():
    one_image_processed = False
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir = Path(tempdir)
        for old_path in camera.images(tempdir):
            assert not one_image_processed
            path = call_dcraw(old_path, extra_raw=False)
            raw_points = analyze_scan(2000, 3000, 0.1, path, 4)
            points = [analyze_scan(x, y, 1, path, 1)[0] for x, y in raw_points]

            path_gray, dcraw_gray = call_dcraw(old_path, extra_raw=True, gray=True, asynchronous=True)
            path = call_dcraw(old_path, extra_raw=True)
            shutil.move(str(path), str(profile_root/"flatfield.ppm"))
            assert dcraw_gray.wait() == 0
            shutil.move(str(path_gray), str(profile_root/"flatfield.pgm"))
            one_image_processed = True
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


os.makedirs(str(profile_root), exist_ok=True)
calibration_file_path = profile_root/"calibration.pickle"

def get_correction_data():
    print("Kalibrationsbild ist nötig …")
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


def process_image(filepath, output_path):
    filepath = call_dcraw(filepath, extra_raw=True, gray=args.mode in {"gray", "mono"}, b=0.9)
    flatfield_path = (profile_root/"flatfield").with_suffix(".pgm" if args.mode in {"gray", "mono"} else ".ppm")
    tempfile = (filepath.parent/(filepath.stem + "-temp")).with_suffix(filepath.suffix)
    silent_call(["convert", str(filepath), str(flatfield_path), "-compose", "dividesrc", "-composite",
                           str(tempfile)])
    os.rename(str(tempfile), str(filepath))
    x0, y0, width, height = json.loads(
        subprocess.check_output([str(path_to_own_program("undistort")), str(filepath)] +
                                correction_data.coordinates_as_strings(), stderr=silent()).decode())
    density = correction_data.density(height)
    if args.height is not None:
        height = args.height / 2.54 * density
    if args.width is not None:
        width = args.width / 2.54 * density
    filepath_tiff = filepath.with_suffix(".tiff")
    tempfile_tiff = tempfile.with_suffix(".tiff")
    silent_call(["convert", "-extract", "{}x{}+{}+{}".format(width, height, x0, y0),
                           str(filepath), str(filepath_tiff)])
    if args.mode == "color":
        silent_call(["cctiff", "/home/bronger/.config/darktable/color/in/nex7_matrix.icc",
                               str(filepath_tiff), str(tempfile_tiff)])
    else:
        os.rename(str(filepath_tiff), str(tempfile_tiff))
    convert_call = ["convert", str(tempfile_tiff), "-linear-stretch", "2%x1%"]
    if args.mode == "color":
        convert_call.extend(["-set", "colorspace", "Lab", "-depth", "8", "-colorspace", "sRGB"])
    elif args.mode == "gray":
        convert_call.extend(["-set", "colorspace", "gray", "-gamma", "2.2", "-depth", "8"])
    elif args.mode == "mono":
        convert_call.extend(["-level", "0,75%", "-set",
                             "colorspace", "gray", "-dither", "FloydSteinberg", "-depth", "1", "-compress", "group4"])
    convert_call.extend(["-density", str(density), str(filepath_tiff)])
    silent_call(convert_call)
    pdf_filepath = output_path/filepath.with_suffix(".pdf").name
    silent_call(["tesseract", str(filepath_tiff), str(pdf_filepath.parent/pdf_filepath.stem), "-l", args.language, "pdf"])
    return pdf_filepath

with tempfile.TemporaryDirectory() as tempdir:
    tempdir = Path(tempdir)
    pool = multiprocessing.Pool()
    results = set()
    for path in camera.images(tempdir, wait_for_disconnect=False):
        results.add(pool.apply_async(process_image, (path, tempdir)))
    print("Rest can be done in background.  You may now press Ctrl-Z and \"bg\" this script.")
    pool.close()
    pool.join()
    pdfs = []
    for result in results:
        pdfs.append(result.get())
    pdfs.sort()
    silent_call(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite", "-sOutputFile={}".format(args.filepath)] +
                [str(pdf) for pdf in pdfs])

silent_call(["evince", str(args.filepath)])
