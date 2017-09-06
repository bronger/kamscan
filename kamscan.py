#!/usr/bin/python3

"""Takes pictures with a photo camera and converts them to a PDF document.
Currently, this is specific to my (Torsten Bronger) specific setup.  In
particular, some things are hardcoded, e.g. the path to the input colour
profile of the camera or the path of the mount point of the camera on my
computer.  Also, the utility undistort.cc contains hardcoded things.

This script must reside in the same director as its helpers ``undistort`` and
``analyze_scan.py``.  It requires Python 3.5.
"""

import argparse, pickle, time, os, tempfile, shutil, subprocess, json, multiprocessing, datetime, re
from contextlib import contextmanager
from pathlib import Path
import pytz, yaml


try:
    configuration = yaml.load(open(str(Path.home()/".config/kamscan/configuration.yaml")))
except FileNotFoundError:
    configuration = {}


data_root = Path.home()/".config/kamscan"
profiles_root = data_root/"profiles"

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
parser.add_argument("--no-ocr", action="store_true", help="suppress OCR (much faster)")
parser.add_argument("filepath", type=Path, help="path to the PDF file for storing; name without extension must match "
                    "YYYY-MM-DD_Title")
args = parser.parse_args()

assert "/" not in args.profile
profile_root = profiles_root/args.profile

if args.full_height is None:
    page_height = 29.7
elif args.calibration:
    page_height = args.full_height
else:
    raise Exception("You can give --full-height only with --calibration.")

match = re.match(r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})_(?P<title>.*)$", args.filepath.stem)
if match:
    timestamp = datetime.datetime(int(match.group("year")), int(match.group("month")), int(match.group("day")),
                                  tzinfo=pytz.UTC)
    title = match.group("title").replace("_", " ")
else:
    raise Exception("Invalid format for filepath.  Must be YYYY-MM-DD_Title.pdf.")


def path_to_own_file(name):
    """Returns the path to a file which resides in the same directory as this
    script.

    :param str name: name of the file
    :returns: full path to the file
    :rtype: Path
    """
    return (Path(__file__).parent/name).resolve()


def append_to_path_stem(path, suffix):
    """Appends a suffix to the stem of a path.  The terms are important here.
    “Suffix” is not meant in the sense of the pathlib library, which uses this
    term in the sense of “file extension”.  On the other hand, “stem” is meant
    in the sense of pathlib, i.e. a file name (rather than a path) without any
    extension.  Thus, the call ::

        append_to_path_stem(Path("a/b/c.d"), "-e")

    will return ``Path("a/b/c-e.d")``.

    :param pathlib.Path path: original path
    :param str suffix: suffix to be appended
    :returns: path with the suffix appended
    :rtype: pathlib.Path
    """
    return (path.parent/(path.stem + suffix)).with_suffix(path.suffix)


def datetime_to_pdf(timestamp):
    """Converts a timestamp to the format used by PDFtk in its `update_info`
    command.  For example, the timestamp 2017-09-01 14:23:45 CEDT is converted
    to ``D:20170901142345+02'00'``.

    :param datetime.datetime timestamp: the timestamp
    :returns: the timestamp in PDF metedata format
    :rtype: str
    """
    timestamp = timestamp.strftime("D:%Y%m%d%H%M%S%z")
    return "{}'{}'".format(timestamp[:-2], timestamp[-2:])


def silent():
    """Used in subprocess calls to redirect stdout or stderr to ``/dev/null``,
    as in::

        subprocess.check_call([...], stderr=silent())

    It obeys the ``--debug`` option, i.e. if ``--debug`` is set, no redirection
    takes place.
    """
    return open(os.devnull, "w") if not args.debug else None

def silent_call(arguments, asynchronous=False, swallow_stdout=True):
    """Calls an external program.  stdout and stderr are swallowed by default.  The
    environment variable ``OMP_THREAD_LIMIT`` is set to one, because we do
    parallelism by ourselves.  In particular, Tesseract scales *very* badly (at
    least, version 4.0) with more threads.

    :param list[object] arguments: the arguments for the call.  They are
      converted to ``str`` implicitly.
    :param bool asynchronous: whether the program should be launched
      asynchronously
    :param bool swallow_stdout: if ``False``, stdout is caught and can be
      inspected by the caller (as a str rather than a byte string)

    :returns: if asynchronous, it returns a ``Popen`` object, otherwise, it
      returns a ``CompletedProcess`` object.
    :rtype: subprocess.Popen or subprocess.CompletedProcess

    :raises subprocess.CalledProcessError: if a synchronously called process
      returns a non-zero return code
    """
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
        after the instatiation of this `Camera` object.

        The newly found image files are removed from the camera storage.

        :param pathlib.Path tempdir: temporary directoy, managed by the caller,
          where the raw images are stored
        :param bool wait_for_disconnect: whether to explicitly wait for the
          camera baing unplugged

        :returns: iterator over the image files; each item is a tuple which
          consists of the page index (starting at zero) and the path to the
          image file; note that the last image is marked by having a page index
          of -1.
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
    """Calls dcraw to convert a raw image to a PNM file.  In case of `gray` being
    ``False``, it is a PPM file, otherwise, it is a PGM file.  If `extra_raw`
    is ``False``, the colour depth is 8 bit, and various colour space
    transformations of dcraw are applied in order to make the result look nice.

    :param pathlib.Path path: path to the raw image file
    :param bool extra_raw: whether the result is as raw as possible, i.e. 16
      bit, linear, no colour space transformation
    :param bool gray: wether to produce a greyscale file; if ``False``,
      demosaicing is applied
    :param float b: exposure correction; all intensities are multiplied by this
      value
    :param bool asynchronous: whether to call dcraw asynchronously

    :returns: output path of the PNM file; if dcraw was called asynchronously,
      the dcraw ``Popen`` object is returned, too
    :rtype: pathlib.Path or tuple[pathlib.Path, subprocess.Popen]
    """
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
    """Class holding data that belongs to an image calibration.  This data is part
    of a profile.  It is stored in the pickle file in the profile's directory.

    :var coordinates: The pixel coordinates of the rectangle measured during
      the calibration.  Note that this rectangle needn't necessarily be the
      enclosing area of all scans.  This is just the default.  In fact, the
      ``--width`` and ``--height`` parameters denote the actual scan size, and
      they can be even larger than the rectangle.  The four corners are stored
      in the order top left, top right, bottom left, bottom right.  First the x
      coordinate, then the y coordinate.
    :vartype coodinates: list[int]

    :var float height_in_cm: the real-world height (i.e., dimension in y
      direction) of the rectangle given by `coordinates` in centimetres.
    """

    def __init__(self):
        self.coordinates = 8 * [None]
        self.height_in_cm = page_height
        self.camera = None
        self.lens = None

    def density(self, height_in_pixel):
        """Returns the DPI (dots per inch) of the scan.

        :param int height_in_pixel: height of the scan area (i.e., dimension in
          y direction) in pixels

        :returns: dpi of the scan
        :rtype: float
        """
        return height_in_pixel / (self.height_in_cm / 2.54)

    def __repr__(self):
        """Returns a string representation of this object.  This is used only for
        debugging purposes.

        :returns: string representation of this object
        :rtype: str
        """
        return "links oben: {}, {}  rechts oben: {}, {}  links unten: {}, {}  rechts unten: {}, {}  " \
            "Kamera: '{}'  Objektiv: '{}'".format(*(self.coordinates + [self.camera, self.lens]))


def analyze_scan(x, y, scaling, filepath, number_of_points):
    """Lets the user find the four corners of the calibration rectangle.

    :returns: Pixel coordinates of the four corners of the calibration
      rectangle.  They are returned in no particular order.
    :rtype: list[tuple[int, int]]
    """
    def clamp(x, max_):
        return min(max(x, 0), max_ - 1)
    output = silent_call([path_to_own_file("analyze_scan.py"), clamp(x, 4000), clamp(y, 6000), scaling,
                          filepath, number_of_points], swallow_stdout=False).stdout
    result = json.loads(output)
    return result

def analyze_calibration_image():
    """Takes one or two calibration images from the camera and creates a profile
    from them.  Such a profile consists of three files:

    - pickle file with the correction data
    - PPM file with the colour flat field
    - PGM file with the greyscale flat field (also used for the monochromatic
      mode)

    For getting the pixel coordinates of the corners of the calibration
    rectangle, the external helper ``analyze_scan.py`` is called.

    If two images are provided, the first one is a flat field, and the second
    one is used for getting the corners of the calibration rectangle.  If one
    image is provided, is serves both, i.e. is must be an empty white sheet of
    paper.

    :returns: correction data for this scan
    :rtype: CorrectionData

    :raises Exception: if more than two calibration images were found on the
      camera storage, or none
    """
    def get_points(path):
        temp_path = append_to_path_stem(path, "-unraw")
        # For avoiding a race with the flat field PPM generation.
        os.rename(str(path), str(temp_path))
        ppm_path = call_dcraw(temp_path, extra_raw=False)
        raw_points = analyze_scan(2000, 3000, 0.1, ppm_path, 4)
        return [analyze_scan(x, y, 1, ppm_path, 1)[0] for x, y in raw_points]
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir = Path(tempdir)
        index = None
        for index, path in camera.images(tempdir):
            if index == 0:
                path_color, dcraw_color = call_dcraw(path, extra_raw=True, asynchronous=True)
                path_gray, dcraw_gray = call_dcraw(path, extra_raw=True, gray=True, asynchronous=True)
            elif index == -1:
                points = get_points(path)
            else:
                raise Exception("More than two calibration images found.")
        if index is None:
                raise Exception("No calibration image found.")
        elif index == 0:
            points = get_points(path)
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
    """Removes profiles that are older than 5 o'clock of today, and at least 4
    hours old.
    """
    now = datetime.datetime.now()
    minutes = (now.hour * 60 + now.minute - 5 * 60) % (24 * 60)
    minutes = max(minutes, 4 * 60)
    silent_call(["find", profiles_root, "-mindepth", 1, "-mmin", "+{}".format(minutes), "-delete"])
prune_profiles()
os.makedirs(str(profile_root), exist_ok=True)
calibration_file_path = profile_root/"calibration.pickle"

def get_correction_data():
    """Returns the correction data for the current profile.  If such data does not
    yet exist on disk, the user gets the opportunity to provide the necessary
    input for it (taking calibration images, click on corners).  The result of
    this is stored on disk.

    :returns: correction data for the current profile
    :rtype: CorrectionData
    """
    def input_choice(configuration_name, correction_attribute_name):
        """Sets an attribute in `correction_data` according to user input.  The user is
        given choices from the configuration file
        ``~/.config/kamscan/configuration.yaml``.  For example, it may
        contain::

            cameras:
              "1": NEX-7
              "2": Alpha 6500

        Then, the user may enter, say, “1” for setting the profile to NEX-7.
        Note that the dictionary keys in the configuration file must be
        strings.

        :param str configuration_name: name of the dictionary in the
          configuration file, e.g. “cameras”
        :param str correction_attribute_name: name of the attribute in the
          `CorrectionData` singleton
        """
        if configuration_name in configuration:
            for name, item in configuration[configuration_name].items():
                print("{}: {}".format(name, item))
            setattr(correction_data, correction_attribute_name, configuration[configuration_name][input("? ")])
        else:
            setattr(correction_data, correction_attribute_name, input(correction_attribute_name + "? "))
    print("Calibration is necessary.  First the flat field, then for the position, or one image for both …")
    correction_data = analyze_calibration_image()
    input_choice("cameras", "camera")
    print()
    input_choice("lenses", "lens")
    pickle.dump(correction_data, open(str(calibration_file_path), "wb"))
    return correction_data

if args.calibration:
    correction_data = get_correction_data()
else:
    try:
        correction_data = pickle.load(open(str(calibration_file_path), "rb"))
    except FileNotFoundError:
        correction_data = get_correction_data()


def raw_to_corrected_pnm(filepath):
    """Converts a RAW file into a corrected PNM file.  The applied corrections are:

    1. Vignetting
    2. Inhomogeneous illumination
    3. Exposure
    4. Coloured corners (“Italian flag syndrome”)
    5. White balance
    6. Sensor dust
    7. Reflections on a glass panel
    8. Perspective correction
    9. Lens distortion
    10. Transversal chromatic aberration (TCA) of the lens
    11. Rotation (page borders not parallel to image borders)

    What's not corrected is a non-planar page.

    The file extension of the result is ppm for colour mode, and pgm for grey
    and monochrome mode.

    The returned corner coordinates and dimensions refer to the pixel
    coordinates of the calibration rectangle.  Since the real-world height of
    this rectangle is known, this enables the software to crop the image
    properly to the the desired page.

    :param pathlib.Path filepath: path to the RAW file
    :returns: path to the PNM file, coordinates of the full page's origin, and
      its width and height; all in pixels from the top left
    :rtype: pathlib.Path, float, float, float, float
    """
    filepath = call_dcraw(filepath, extra_raw=True, gray=args.mode in {"gray", "mono"}, b=0.9)
    flatfield_path = (profile_root/"flatfield").with_suffix(".pgm" if args.mode in {"gray", "mono"} else ".ppm")
    tempfile = append_to_path_stem(filepath, "-temp")
    silent_call(["convert", filepath, flatfield_path, "-compose", "dividesrc", "-composite", tempfile])
    os.rename(str(tempfile), str(filepath))
    x0, y0, width, height = json.loads(
        silent_call([path_to_own_file("undistort"), filepath] + correction_data.coordinates +
                    [correction_data.camera, correction_data.lens], swallow_stdout=False).stdout)
    return filepath, x0, y0, width, height


def calculate_pixel_dimensions(width, height):
    """Returns the pixel width and height of the page rectangle, and the DPI.
    This is the page rectangle rather than the calibration rectangle, i.e. the
    ``--width`` and ``--height`` parameters (or their default values) are
    used.  The returned dimensions denote the area that needs to be cropped out
    of the original image.

    :param float width: width of the calibration rectangle in pixels
    :param float height: height of the calibration rectangle in pixels
    :returns: width and height of the image crop in pixels, image density in
      DPI
    :rtype: float, float, float
    """
    density = correction_data.density(height)
    if args.two_side:
        if args.height is not None:
            width = args.height / 2.54 * density
        if args.width is not None:
            height = args.width / 2.54 * density
    else:
        if args.height is not None:
            height = args.height / 2.54 * density
        if args.width is not None:
            width = args.width / 2.54 * density
    return width, height, density


def create_single_tiff(filepath, width, height, x0, y0, density, mode, suffix=None):
    """Crops the scan area out of the out-of-camera PNM file and saves it as a TIFF
    file.  Moreover, it applies some colour optimisation, and puts the proper
    DPI value in the output's metadata.

    :param pathlib.Path filepath: path to the corrected PNM file; it is the
      result of `raw_to_corrected_pnm`
    :param float width: pixel width of the crop area
    :param float height: pixel height of the crop area
    :param float x0: x pixel coordinate of the top left corner of the crop area
    :param float y0: y pixel coordinate of the top left corner of the crop area
    :param float density: DPI of the image
    :param str mode: colour mode; may be the values of the ``--mode`` option
      plus ``gray_linear``, which is used for an OCR-optimised crop
    :param str suffix: suffix to be appended to the stem to the resulting file
      name; *not* a file extension
    :returns: path to the result image
    :rtype: pathlib.Path
    """
    filepath_tiff = filepath.with_suffix(".tiff")
    if suffix:
        filepath_tiff = append_to_path_stem(filepath_tiff, suffix)
    silent_call(["convert", "-extract", "{}x{}+{}+{}".format(width, height, x0, y0), "+repage", filepath, filepath_tiff])
    tempfile_tiff = (filepath_tiff.parent/(filepath_tiff.stem + "-temp")).with_suffix(filepath_tiff.suffix)
    if mode == "color" and "icc_profile" in configuration:
        silent_call(["cctiff", configuration["icc_profile"], filepath_tiff, tempfile_tiff])
    else:
        os.rename(str(filepath_tiff), str(tempfile_tiff))
    convert_call = ["convert", tempfile_tiff]
    if mode == "color":
        convert_call.extend(["-set", "colorspace", "Lab", "-colorspace", "RGB", "-linear-stretch", "2%x1%",
                             "-depth", "8", "-colorspace", "sRGB"])
    elif mode == "gray":
        convert_call.extend(["-set", "colorspace", "gray", "-linear-stretch", "2%x1%", "-gamma", "2.2", "-depth", "8"])
    elif mode == "gray_linear":
        convert_call.extend(["-set", "colorspace", "gray", "-linear-stretch", "2%x1%", "-depth", "8"])
    elif mode == "mono":
        convert_call.extend(["-set", "colorspace", "gray", "-linear-stretch", "2%x1%", "-level", "10%,75%",
                             "-dither", "None", "-monochrome", "-depth", "1"])
    convert_call.extend(["-density", density, filepath_tiff])
    silent_call(convert_call)
    return filepath_tiff


def split_two_side(page_index, filepath_tiff, width, height):
    """Crops the two pages out of the double-page scan.  Note that “width” is the
    height of the double page page (and thus also of the single page), and
    “height” is the width of the double page.

    :param int page_index: Index of the current page.  In two-side mode, this
      is the index of the current double page because separation of left and
      right happens in this function.  Moreover, the last page has the index
      -1.
    :param pathlib.Path filepath_tiff: path to a TIFF with the scan area (i.e.,
      the double page)
    :param float width: pixel width of the crop area
    :param float height: pixel height of the crop area
    :returns: Paths to the two page images, left and right (in this ordering);
      if it is the first double page, only the right half is returned.  If it
      is the last double page, only the left half is returned.  Thus, the
      resulting list either has one or two items.
    :rtype: list[pathlib.Path]
    """
    if page_index != 0:
        filepath_left_tiff = append_to_path_stem(filepath_tiff, "-0")
        left = silent_call(["convert", "-extract", "{0}x{1}+0+0".format(width, height / 2), "+repage", filepath_tiff,
                            "-rotate", "-90", filepath_left_tiff], asynchronous=True)
    if page_index != -1:
        filepath_right_tiff = append_to_path_stem(filepath_tiff, "-1")
        silent_call(["convert", "-extract", "{0}x{1}+0+{1}".format(width, height / 2), "+repage", filepath_tiff,
                     "-rotate", "-90", filepath_right_tiff])
    tiff_filepaths = []
    if page_index != 0:
        assert left.wait() == 0
        tiff_filepaths.append(filepath_left_tiff)
    if page_index != -1:
        tiff_filepaths.append(filepath_right_tiff)
    return tiff_filepaths


def single_page_raw_pdfs(tiff_filepaths, ocr_tiff_filepaths, output_path):
    """Generates the PDF pairs that are merged to the final pages.  Every page of
    the final PDF consists of two layers: the invisible text layer and the
    scan.  Here, we generate for a single page, or two pages in two-side mode,
    the input PDFs needed for that.

    This means that the inpurt lists either have one or two items.  In the
    latter case, the ordering is left page, right page.  (As a side note, even
    in two-side mode there may be only one item, namely for the first and the
    last double page.)

    The output tuples contain everything the following code must know, namely
    the two input PDFs and the output PDF's name.  The latter is not generated
    here.  This is the task of caller.

    By the way, normally, we don't parallelise in function called from
    `process_image` because `process_image` itself is parallelised.  However, I
    make an exception for the exceptionally expensive Tesseract call.  This is
    beneficial for the single-page-scan case.  In other cases, at most two
    Tesseract processes will be spawned here, which should not be a big
    problem.

    :param tiff_filepaths: paths to the TIFFs that should form the final PDF
    :param ocr_tiff_filepaths: paths to the TIFFs that are used for OCR (and
      discarded afterwards)
    :param pathlib.Path output_path: directory where the PDFs are written to
    :type tiff_filepaths: list[pathlib.Path]
    :type ocr_filepaths: list[pathlib.Path]
    :returns: Tuples which contain for each input item the path to the
      text-only TIFF (the result of the OCR), the path to the PDF with the
      scan, and the output path for the merged PDF.
    :rtype: set[tuple[pathlib.Path, pathlib.Path, pathlib.Path]]
    """
    processes = set()
    result = set()
    for path, ocr_path in zip(tiff_filepaths, ocr_tiff_filepaths):
        pdf_filepath = output_path/path.with_suffix(".pdf").name
        if args.no_ocr:
            textonly_pdf_filepath = None
        else:
            textonly_pdf_filepath = append_to_path_stem(pdf_filepath, "-textonly")
            textonly_pdf_pathstem = textonly_pdf_filepath.parent/textonly_pdf_filepath.stem
            tesseract = silent_call(["tesseract", ocr_path, textonly_pdf_pathstem , "-c", "textonly_pdf=1",
                                     "-l", args.language, "pdf"], asynchronous=True)
            processes.add(tesseract)
        pdf_image_path = append_to_path_stem(path.with_suffix(".pdf"), "-image")
        if args.mode == "color":
            compression_options = ["-compress", "JPEG"]
        elif args.mode == "gray":
            compression_options = ["-compress", "JPEG", "-quality", "30%"]
        elif args.mode == "mono":
            compression_options = ["-compress", "Group4"]
        else:
            compression_options = []
        silent_call(["convert", path] + compression_options + [pdf_image_path])
        result.add((textonly_pdf_filepath, pdf_image_path, pdf_filepath))
    for process in processes:
        assert process.wait() == 0
    return result


def process_image(filepath, page_index, output_path):
    """Converts one raw image to a searchable single-page PDF.

    :param pathlib.Path filepath: path to the raw image file
    :param int page_index: Index of the current page.  In two-side mode, this
      is the index of the current double page because separation of left and
      right happens in this function.  Moreover, the last page has the index
      -1.
    :param pathlib.Path output_path: directory where the PDFs are written to

    :returns: path to the PDF, or the two PDFs in two-side mode
    :rtype: set[pathlib.Path]
    """
    filepath, x0, y0, width, height = raw_to_corrected_pnm(filepath)
    width, height, density = calculate_pixel_dimensions(width, height)
    filepath_tiff = create_single_tiff(filepath, width, height, x0, y0, density, args.mode)
    filepath_ocr_tiff = create_single_tiff(filepath, width, height, x0, y0, density, "gray_linear", "-ocr")
    if args.two_side:
        tiff_filepaths = split_two_side(page_index, filepath_tiff, width, height)
        ocr_tiff_filepaths = split_two_side(page_index, filepath_ocr_tiff, width, height)
    else:
        tiff_filepaths = [filepath_tiff]
        ocr_tiff_filepaths = [filepath_ocr_tiff]
    result = set()
    for textonly_pdf_filepath, pdf_image_path, pdf_filepath in \
        single_page_raw_pdfs(tiff_filepaths, ocr_tiff_filepaths, output_path):
        if textonly_pdf_filepath:
            silent_call(["pdftk", textonly_pdf_filepath, "multibackground", pdf_image_path, "output", pdf_filepath])
        else:
            shutil.move(str(pdf_image_path), str(pdf_filepath))
        result.add(pdf_filepath)
    return result


def embed_pdf_metadata(filepath):
    """Embeds metadata in a PDF.  It sets author, creator, title, and timestamp
    data.  Note that this data is partly taken from the global variables
    `timestamp` and `title`.  The given file is changed in place.

    :param pathlib.Path filepath: path to the PDF file
    """
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir = Path(tempdir)
        info_filepath = tempdir/"info.txt"
        with open(str(info_filepath), "w") as info_file:
            now = datetime.datetime.now(pytz.utc).astimezone(pytz.timezone("Europe/Amsterdam"))
            info_file.write("""InfoBegin
InfoKey: Author
InfoValue: Torsten Bronger
InfoBegin
InfoKey: Creator
InfoValue: Kamscan
InfoBegin
InfoKey: CreationDate
InfoValue: {}
InfoBegin
InfoKey: ModDate
InfoValue: {}
InfoBegin
InfoKey: Title
InfoValue: {}
        """.format(datetime_to_pdf(timestamp), datetime_to_pdf(now), title))
        temp_filepath = tempdir/"temp.pdf"
        silent_call(["pdftk", filepath, "update_info_utf8", info_filepath, "output", temp_filepath])
        shutil.move(str(temp_filepath), str(filepath))


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
    silent_call(["pdftk"] + [pdf for pdf in pdfs] + ["cat", "output", args.filepath])
    embed_pdf_metadata(args.filepath)

silent_call(["evince", args.filepath])
