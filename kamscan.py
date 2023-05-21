#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

"""Takes pictures with a photo camera and converts them to a PDF document.

This script must reside in the same directory as its helpers ``undistort`` and
``analyze_scan.py``.  It requires Python 3.5.
"""

import argparse, pickle, time, os, tempfile, shutil, subprocess, json, multiprocessing, datetime, re, functools, importlib
from contextlib import contextmanager
from pathlib import Path
import pytz, argcomplete
from ruamel.yaml import YAML
import undistort
from . import utils
from .utils import silent_call


yaml = YAML()

try:
    configuration = yaml.load(Path.home()/".config/kamscan/configuration.yaml")
except FileNotFoundError:
    configuration = {}


formats = {"A2": (42, 59.4), "A3": (29.7, 42), "A4": (21, 29.7), "A5": (14.8, 21), "A6": (10.5, 14.8), "A7": (7.4, 10.5)}


data_root = Path(configuration["data_path"]) if "data_path" in configuration else Path.home()/".config/kamscan"
profiles_root = data_root/"profiles"

parser = argparse.ArgumentParser(description="Scan a document.")
parser.add_argument("--calibration", action="store_true", help="force taking a calibration image")
parser.add_argument("--mode", default="mono", choices={"gray", "color", "mono"},
                    help="colour mode of resulting pages; defaults to mono")
parser.add_argument("--full-height", type=float, help="height of full page in cm; defaults to 29.7")
parser.add_argument("--height", type=float, help="height of to-be-scanned area in cm; defaults to full page height")
parser.add_argument("--width", type=float, help="width of to-be-scanned area in cm; defaults to full page width")
parser.add_argument("--format", choices=set(formats), help="format of the page; defaults to full page height")
parser.add_argument("--quality", type=int, default=30,
                    help="JPEG quality for grayscale and color output in percent; defaults to 30")
parser.add_argument("--profile", default="default", help="name of profile to use")
parser.add_argument("--debug", action="store_true", help="debug mode; in particular, don't suppress output of subprocesses")
parser.add_argument("--language", default="deu", help="three-character language code; defaults to \"deu\"")
parser.add_argument("--two-side", action="store_true", help="whether two-side images should be assumed; this swaps the "
                    "meanings of --height and --width, with --width being the width of a double page")
parser.add_argument("--full-histogram", action="store_true", help="don’t do any contrast optimisation")
parser.add_argument("--no-ocr", action="store_true", help="suppress OCR (much faster)")
parser.add_argument("filepath", type=Path, help="path to the PDF file for storing; name without extension must match "
                    "YYYY-MM-DD_Title")
parser.add_argument("--source", default=configuration["default_source"], help="name of the images source")
parser.add_argument("--params",
                    help="parameters of the images source; may have the form --param VAL or --param PAR1=VAL1,PAR2=VAL2")
argcomplete.autocomplete(parser)
args = parser.parse_args()

utils.debug = args.debug

def parse_source_parameters():
    if not args.params or not args.params.strip():
        return None
    pairs = args.params.split(",")
    parameters = {}
    for pair in pairs:
        pair = pair.strip()
        key, sep, value = pair.partition("=")
        if not sep:
            assert len(pairs) == 1
            return pair
        parameters[key.strip()] = value.strip()
    return parameters
source_parameters = parse_source_parameters()

assert "/" not in args.profile
profile_root = profiles_root/args.profile

if args.full_height is None:
    page_height = 29.7
elif args.calibration:
    page_height = args.full_height
else:
    raise RuntimeError("You can give --full-height only with --calibration.")

assert args.filepath.parent.is_dir()

if args.format:
    assert args.width is None and args.height is None
    if args.two_side:
        height_in_cm, width_in_cm = formats[args.format]
    else:
        width_in_cm, height_in_cm = formats[args.format]
else:
    width_in_cm, height_in_cm = args.width, args.height

match = re.match(r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})_(?P<title>.*)$", args.filepath.stem)
if match:
    year, month, day = int(match.group("year")), int(match.group("month")), int(match.group("day"))
    if year == 0:
        year, month, day = 1970, 1, 1
        timestamp_accuracy = "none"
    elif month == 0:
        month, day = 1, 1
        timestamp_accuracy = "year"
    elif day == 0:
        day = 1
        timestamp_accuracy = "month"
    else:
        timestamp_accuracy = "full"
    timestamp = datetime.datetime(year, month, day, tzinfo=pytz.UTC)
    title = match.group("title").replace("_", " ")
else:
    raise RuntimeError("Invalid format for filepath.  Must be YYYY-MM-DD_Title.pdf.")

try:
    profile_data = configuration["sources"][args.source]["icc_profile"]
except KeyError:
    icc_path, icc_color_space = None, "RGB"
else:
    icc_path, icc_color_space = Path(profile_data["path"]), profile_data["color_space"]

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


def datetime_to_pdf(timestamp, timestamp_accuracy="full"):
    """Converts a timestamp to the format used by PDFtk in its `update_info`
    command.  For example, the timestamp 2017-09-01 14:23:45 CEDT is converted
    to ``D:20170901142345+02'00'``.

    :param datetime.datetime timestamp: the timestamp
    :param str timestamp_accuracy: Determines the significant parts of the
      timestamp.  Only those are output.  Possible values are ``"year"``,
      ``"month"``, ``"day"``, and ``"full"``.  For example, , ``"month"`` means
      the output may be ``"D:201709"``.

    :returns: the timestamp in PDF metedata format
    :rtype: str
    """
    if timestamp_accuracy == "year":
        timestamp = timestamp.strftime("D:%Y")
    elif timestamp_accuracy == "month":
        timestamp = timestamp.strftime("D:%Y%m")
    elif timestamp_accuracy == "day":
        timestamp = timestamp.strftime("D:%Y%m%d")
    elif timestamp_accuracy == "full":
        timestamp = timestamp.strftime("D:%Y%m%d%H%M%S%z")
        timestamp = "{}'{}'".format(timestamp[:-2], timestamp[-2:])
    return timestamp


source_module = importlib.import_module(".sources." + args.source, "kamscan")
source = source_module.Source(configuration["sources"][args.source], source_parameters)


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

    :raises RuntimeError: if more than two calibration images were found on the
      camera storage, or none
    """
    def get_points(path):
        temp_path = append_to_path_stem(path, "-unraw")
        # For avoiding a race with the flat field PPM generation.
        os.symlink(str(path), str(temp_path))
        ppm_path = source.raw_to_pnm(temp_path, for_preview=True)
        raw_points = analyze_scan(2000, 3000, 0.1, ppm_path, 4)
        return [analyze_scan(x, y, 1, ppm_path, 1)[0] for x, y in raw_points]
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir = Path(tempdir)
        for index, last_page, path in source.images(tempdir, for_calibration=True):
            if index > 1:
                raise RuntimeError("More than two calibration images found.")
            if index == 0:
                path_color, dcraw_color = source.raw_to_pnm(path, asynchronous=True)
                path_gray, dcraw_gray = source.raw_to_pnm(path, gray=True, asynchronous=True)
            if last_page:
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
    if profiles_root.exists():
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
              "1":
                make: Sony
                model: NEX-7
            lenses:
              "1":
                make: Sony
                model: E 50mm f/1.8 OSS (kamscan)

        Then, the user may enter, say, “1” for setting the profile to NEX-7.
        Note that the dictionary keys in the configuration file must be
        strings.

        :param str configuration_name: name of the dictionary in the
          configuration file, e.g. “cameras”
        :param str correction_attribute_name: name of the attribute in the
          `CorrectionData` singleton
        """
        if configuration_name in configuration:
            for name, make_and_model in configuration[configuration_name].items():
                make, model = make_and_model["make"], make_and_model["model"]
                print(f"{name}: {make}, {model}")
            while True:
                try:
                    make_and_model = configuration[configuration_name][input("? ")]
                except KeyError:
                    print("Invalid input.")
                else:
                    setattr(correction_data, correction_attribute_name, [make_and_model["make"], make_and_model["model"]])
                    break
        else:
            make = input(correction_attribute_name + " make? ")
            model = input(correction_attribute_name + " model? ")
            setattr(correction_data, correction_attribute_name, [make, model])
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
    filepath = source.raw_to_pnm(filepath, gray=args.mode in {"gray", "mono"}, b=0.9)
    flatfield_path = (profile_root/"flatfield").with_suffix(".pgm" if args.mode in {"gray", "mono"} else ".ppm")
    tempfile = append_to_path_stem(filepath, "-temp")
    silent_call(["convert", filepath, flatfield_path, "-compose", "dividesrc", "-composite", tempfile])
    os.rename(str(tempfile), str(filepath))
    x0, y0, width, height = undistort.undistort(str(filepath), *(correction_data.coordinates +
                                                                 correction_data.camera + correction_data.lens))
    return filepath, x0, y0, width, height


def calculate_pixel_dimensions(width, height):
    """Returns the pixel width and height of the page rectangle, and the DPI.  This
    is the page rectangle rather than the calibration rectangle, i.e. the
    ``--width`` and ``--height`` parameters (or the ``--format`` parameter, or
    the full page size as default) are used.  The returned dimensions denote
    the area that needs to be cropped out of the original image.

    :param float width: width of the calibration rectangle in pixels
    :param float height: height of the calibration rectangle in pixels

    :returns: width and height of the image crop in pixels, image density in
      DPI
    :rtype: float, float, float
    """
    density = correction_data.density(height)
    if args.two_side:
        if height_in_cm is not None:
            width = height_in_cm / 2.54 * density
        if width_in_cm is not None:
            height = width_in_cm / 2.54 * density
    else:
        if height_in_cm is not None:
            height = height_in_cm / 2.54 * density
        if width_in_cm is not None:
            width = width_in_cm / 2.54 * density
    return width, height, density


@functools.lru_cache(maxsize=2)
def get_levels(path):
    """Returns the black and white levels for this image.  This corresponds to
    Imagemagick convert's command ``-linear-stretch 2%x1%``.  The result could
    be passed to ``-level``.  The reason why this is necessary is that pages
    with very little text confuse ``-linear-stretch``.  It blacks out too much
    of the page, resulting is way too high contrast.  In contrast, this
    function caps the black result to 0.15.

    :param pathlib.Path path: path to the image file

    :returns: the black and white level, as fraction of 1
    :rtype: float, float
    """
    line_regex = re.compile(r"(?P<frequency>\d+): \(\s*\d+,\s*\d+,\s*\d+\) #[A-F0-9]{6} gray\((?P<value>\d+)\)$")
    frequencies = 256 * [0]
    for line in silent_call(["convert", path, "-colorspace", "gray", "-depth", "8", "-format", "%c", "histogram:info:-"],
                            swallow_stdout=False).stdout.splitlines():
        match = line_regex.match(line.strip())
        value, frequency = int(match.group("value")), int(match.group("frequency"))
        frequencies[value] += frequency
    number_of_samples = sum(frequencies)
    darkest_2_percent = 0
    for i, frequency in enumerate(frequencies):
        darkest_2_percent += frequency
        if darkest_2_percent > number_of_samples * 0.02:
            break
    brightest_1_percent = 0
    for j, frequency in enumerate(reversed(frequencies)):
        brightest_1_percent += frequency
        if brightest_1_percent > number_of_samples * 0.01:
            break
    return min(i / 255, 0.15), 1 - j / 255


def create_crop(filepath, width, height, x0, y0):
    """Crops the scan area out of the out-of-camera PNM file and saves it as a TIFF
    file.

    :param pathlib.Path filepath: path to the corrected PNM file; it is the
      result of `raw_to_corrected_pnm`
    :param float width: pixel width of the crop area
    :param float height: pixel height of the crop area
    :param float x0: x pixel coordinate of the top left corner of the crop area
    :param float y0: y pixel coordinate of the top left corner of the crop area

    :returns: path to the result image
    :rtype: pathlib.Path
    """
    filepath_tiff = filepath.with_suffix(".tiff")
    silent_call(["convert", "-extract", "{}x{}+{}+{}".format(width, height, x0, y0), "+repage", filepath, filepath_tiff])
    return filepath_tiff


def color_process_single_tiff(filepath, density, mode, suffix):
    """Applies some colour optimisation and puts the proper DPI value in the
    output's metadata.

    :param pathlib.Path filepath: path to the cropped TIFF file; it is the
      result of `create_crop`
    :param float density: DPI of the image
    :param str mode: colour mode; may be the values of the ``--mode`` option
      plus ``gray_linear``, which is used for an OCR-optimised crop
    :param str suffix: suffix to be appended to the stem to the resulting file
      name; *not* a file extension

    :returns: path to the result image
    :rtype: pathlib.Path
    """
    tempfile_tiff = append_to_path_stem(filepath, "-temp")
    if mode == "color" and icc_path:
        silent_call(["cctiff", "-N", icc_path, filepath, tempfile_tiff])
    else:
        shutil.copy(str(filepath), str(tempfile_tiff))
    filepath = append_to_path_stem(filepath, suffix)
    convert_call = ["convert", tempfile_tiff]
    if mode == "color":
        convert_call.extend(["-set", "colorspace", icc_color_space, "-colorspace", "RGB"] +
                            ([] if args.full_histogram else ["-level", "12.5%,100%"]) +
                            ["-depth", "8", "-colorspace", "sRGB"])
    elif mode == "gray":
        convert_call.extend(["-set", "colorspace", "gray"] +
                            ([] if args.full_histogram else ["-level", "10%,100%"]) +
                            ["-gamma", "2.2", "-depth", "8"])
    elif mode == "gray_linear":
        black, white = get_levels(tempfile_tiff)
        convert_call.extend(["-set", "colorspace", "gray", "-level", "{}%,{}%".format(black * 100, white * 100),
                             "-depth", "8"])
    elif mode == "mono":
        black, white = get_levels(tempfile_tiff)
        convert_call.extend(["-set", "colorspace", "gray"] +
                            ([] if args.full_histogram else ["-level", "{}%,{}%".format((1 - (1 - 0.1) * (1 - black)) * 100,
                                                                                        0.75 * white * 100)]) +
                            ["-dither", "None", "-monochrome", "-depth", "1"])
    convert_call.extend(["-density", density, filepath])
    silent_call(convert_call)
    return filepath


def split_two_side(page_index, last_page, filepath_tiff, width, height):
    """Crops the two pages out of the double-page scan.  Note that “width” is the
    height of the double page page (and thus also of the single page), and
    “height” is the width of the double page.

    :param int page_index: Index of the current page.  In two-side mode, this
      is the index of the current double page because separation of left and
      right happens in this function.
    :param bool last_page: whether it is the last page
    :param filepath_tiff: path to a TIFF with the scan area (i.e., the double
      page)
    :type filepath_tiff: pathlib.Path or NoneType
    :param float width: pixel width of the crop area
    :param float height: pixel height of the crop area

    :returns: Paths to the two page images, left and right (in this ordering);
      if it is the first double page, only the right half is returned.  If it
      is the last double page, only the left half is returned.  Thus, the
      resulting list either has one or two items.  The list consists of
      ``None``s if `filepath_tiff` was ``None``.
    :rtype: list[pathlib.Path] or list[NoneType]
    """
    first_page = page_index == 0
    only_one_page = first_page and last_page
    process_left = not first_page or only_one_page
    process_right = not last_page or only_one_page
    tiff_filepaths = []
    if filepath_tiff:
        if process_left:
            filepath_left_tiff = append_to_path_stem(filepath_tiff, "-0")
            left = silent_call(["convert", "-extract", "{0}x{1}+0+0".format(width, height / 2), "+repage", filepath_tiff,
                                "-rotate", "-90", filepath_left_tiff], asynchronous=True)
        if process_right:
            filepath_right_tiff = append_to_path_stem(filepath_tiff, "-1")
            silent_call(["convert", "-extract", "{0}x{1}+0+{1}".format(width, height / 2), "+repage", filepath_tiff,
                         "-rotate", "-90", filepath_right_tiff])
        if process_left:
            assert left.wait() == 0
            tiff_filepaths.append(filepath_left_tiff)
        if process_right:
            tiff_filepaths.append(filepath_right_tiff)
    else:
        if process_left:
            tiff_filepaths.append(None)
        if process_right:
            tiff_filepaths.append(None)
    return tiff_filepaths


def single_page_raw_pdfs(tiff_filepaths, ocr_tiff_filepaths, output_path):
    """Generates the PDF pairs that are merged to the final pages.  Every page of
    the final PDF consists of two layers: the invisible text layer and the
    scan.  Here, we generate for a single page, or two pages in two-side mode,
    the input PDFs needed for that.

    This means that the input lists either have one or two items.  In the
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
      discarded afterwards); may be a list of ``None``s if no OCR is done
    :param pathlib.Path output_path: directory where the PDFs are written to
    :type tiff_filepaths: list[pathlib.Path]
    :type ocr_filepaths: list[pathlib.Path] or list[NoneType]

    :returns: Tuples which contain for each input item the path to the
      text-only TIFF (the result of the OCR, may be ``None`` if no OCR is
      done), the path to the PDF with the scan, and the output path for the
      merged PDF.
    :rtype: set[tuple[pathlib.Path or NoneType, pathlib.Path, pathlib.Path]]
    """
    processes = set()
    result = set()
    for path, ocr_path in zip(tiff_filepaths, ocr_tiff_filepaths):
        pdf_filepath = output_path/path.with_suffix(".pdf").name
        if ocr_path:
            textonly_pdf_filepath = append_to_path_stem(pdf_filepath, "-textonly")
            textonly_pdf_pathstem = textonly_pdf_filepath.parent/textonly_pdf_filepath.stem
            tesseract = silent_call(["tesseract", ocr_path, textonly_pdf_pathstem , "-c", "textonly_pdf=1",
                                     "-l", args.language, "pdf"], asynchronous=True)
            processes.add(tesseract)
        else:
            textonly_pdf_filepath = None
        pdf_image_path = append_to_path_stem(path.with_suffix(".pdf"), "-image")
        if args.mode in {"color", "gray"}:
            if args.quality < 100:
                compression_options = ["-compress", "JPEG", "-quality", "{}%".format(args.quality)]
            else:
                compression_options = ["-compress", "lzw"]
        elif args.mode == "mono":
            compression_options = ["-compress", "Group4"]
        else:
            compression_options = []
        silent_call(["convert", path] + compression_options + [pdf_image_path])
        result.add((textonly_pdf_filepath, pdf_image_path, pdf_filepath))
    for process in processes:
        assert process.wait() == 0
    return result


def process_image(filepath, page_index, last_page, output_path):
    """Converts one raw image to a searchable single-page PDF.

    :param pathlib.Path filepath: path to the raw image file
    :param int page_index: Index of the current page.  In two-side mode, this
      is the index of the current double page because separation of left and
      right happens in this function.
    :param bool last_page: whether it is the last page
    :param pathlib.Path output_path: directory where the PDFs are written to

    :returns: path to the PDF, or the two PDFs in two-side mode
    :rtype: set[pathlib.Path]
    """
    filepath, x0, y0, width, height = raw_to_corrected_pnm(filepath)
    width, height, density = calculate_pixel_dimensions(width, height)
    filepath_tiff = create_crop(filepath, width, height, x0, y0)
    filepath_image_tiff = color_process_single_tiff(filepath_tiff, density, args.mode, "-image")
    if args.no_ocr:
        filepath_ocr_tiff = None
    else:
        filepath_ocr_tiff = color_process_single_tiff(filepath_tiff, density, "gray_linear", "-ocr")
    if args.two_side:
        tiff_filepaths = split_two_side(page_index, last_page, filepath_image_tiff, width, height)
        ocr_tiff_filepaths = split_two_side(page_index, last_page, filepath_ocr_tiff, width, height)
    else:
        tiff_filepaths = [filepath_image_tiff]
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
InfoKey: ModDate
InfoValue: {}
InfoBegin
InfoKey: Title
InfoValue: {}
""".format(datetime_to_pdf(now), title))
            if timestamp_accuracy != "none":
                info_file.write("""InfoBegin
InfoKey: CreationDate
InfoValue: {}
""".format(datetime_to_pdf(timestamp, timestamp_accuracy)))
        temp_filepath = tempdir/"temp.pdf"
        silent_call(["pdftk", filepath, "update_info_utf8", info_filepath, "output", temp_filepath])
        shutil.move(str(temp_filepath), str(filepath))

if __name__ == '__main__':
    start = None
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir = Path(tempdir)
        pool = multiprocessing.Pool()
        results = set()
        for index, last_page, path in source.images(tempdir):
            if start is None:
                start = time.time()
            results.add(pool.apply_async(process_image, (path, index, last_page, tempdir)))
        print("Rest can be done in background.  You may now press Ctrl-Z and \"bg\" this script.")
        pool.close()
        pool.join()
        pdfs = []
        for result in results:
            pdfs.extend(result.get())
        pdfs.sort()
        silent_call(["pdftk"] + [pdf for pdf in pdfs] + ["cat", "output", args.filepath])
        embed_pdf_metadata(args.filepath)
    if args.debug:
        print("Time elapsed in seconds:", time.time() - start)

    silent_call(["evince", args.filepath])
