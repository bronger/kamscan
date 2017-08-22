#!/usr/bin/python3

import argparse, pickle, time, os, tempfile, shutil, subprocess, json, multiprocessing, datetime
from contextlib import contextmanager
from pathlib import Path


calibration_file_path = Path.home()/"aktuell/kamscan_calibration.pickle"

parser = argparse.ArgumentParser(description="Scan a document.")
parser.add_argument("--calibration", action="store_true", help="take a calibration image")
parser.add_argument("--mode", default="mono", choices={"gray", "color", "mono"}, help="colour mode of resulting pages")
parser.add_argument("filepath", type=Path, help="path to the PDF file for storing")
args = parser.parse_args()


def path_to_own_program(name):
    return (Path(__file__).parent/name).resolve()


class Camera:
    path = Path("/media/bronger/3937-6637/DCIM")

    def __init__(self):
        self.red, self.green, self.blue = 2.986434, 1.000000, 1.248604
        self.exposure_correction = 1
        with self._camera_connected():
            self.paths = self._collect_paths()

    def set_correction(self, correction_data):
        self.red, self.green, self.blue = correction_data.red, correction_data.green, correction_data.blue
        self.exposure_correction = correction_data.exposure_correction

    def path_exists(self):
        while True:
            try:
                return self.path.exists()
            except PermissionError as error:
                print(error)
                time.sleep(1)

    @contextmanager
    def _camera_connected(self):
        if not self.path_exists():
            print("Bitte Kamera einstöpseln.")
        while not self.path_exists():
            time.sleep(1)
        yield
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

    def images(self):
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir = Path(tempdir)
            print("Bitte Bilder machen.  Dann:")
            with self._camera_connected():
                paths = self._collect_paths()
                new_paths = paths - self.paths
                paths_with_timestamps = []
                for path in new_paths:
                    output = subprocess.check_output(
                        ["exiv2", "-g", "Exif.Photo.DateTimeOriginal", str(path)]).decode().strip()
                    paths_with_timestamps.append((datetime.datetime.strptime(output[-19:], "%Y:%m:%d %H:%M:%S"), path))
                paths_with_timestamps.sort()
                path_tripletts = set()
                i = 0
                for __, path in paths_with_timestamps:
                    path_tripletts.add((path, tempdir/path.name, tempdir/"{:06}.ARW".format(i)))
                    i += 1
                rsync = subprocess.Popen(["rsync"] + [str(path[0]) for path in path_tripletts] + [str(tempdir)])
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


def call_dcraw(path, extra_options=[]):
    dcraw_call = ["dcraw", "-t", "5", "-o", "0", "-M", "-g", "1", "1", "-W"] + extra_options + [str(path)]
    output_path = path.with_suffix(".pgm") if "-d" in dcraw_call else path.with_suffix(".ppm")
    return output_path, subprocess.Popen(dcraw_call)


class CorrectionData:

    def __init__(self):
        self.coordinates = 8 * [None]
        self.red = self.green = self.blue = None
        self.exposure_correction = None

    def coordinates_as_strings(self):
        return [str(coordinate) for coordinate in self.coordinates]

    def __repr__(self):
        return """links oben: {}, {}  rechts oben: {}, {}  links unten: {}, {}  rechts unten: {}, {}
rot: {}  grün: {}  blau: {}
Belichtungskorrektur: {}""".format(*(self.coordinates + [self.red, self.green, self.blue, self.exposure_correction]))


def analyze_scan(x, y, scaling, filepath, number_of_points):
    output = subprocess.check_output([str(path_to_own_program("analyze_scan.py")), str(x), str(y), str(scaling),
                                      str(filepath), str(number_of_points)]).decode()
    try:
        result = json.loads(output)
    except json.decoder.JSONDecodeError:
        print("Invalid JSON: {}".format(repr(output)))
        raise
    return result

def analyze_calibration_image():
    one_image_processed = False
    for path in camera.images():
        assert not one_image_processed
        path, dcraw = call_dcraw(path)
        assert dcraw.wait() == 0
        raw_points = analyze_scan(2000, 3000, 0.1, path, 4)
        points = [analyze_scan(x, y, 1, path, 1)[0] for x, y in raw_points]
        red, green, blue = [float(subprocess.check_output(
            ["convert", "-extract", "100x100+1950+2950", str(path),
             "-channel", channel, "-separate", "-format", "%[mean]", "info:"]).decode())
                            for channel in ("Red", "Green", "Blue")]
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
    correction_data.red = red * camera.red / green
    correction_data.green = camera.green
    correction_data.blue = blue * camera.blue / green
    correction_data.exposure_correction = 65535 / green
    return correction_data


def get_correction_data():
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
camera.set_correction(correction_data)


def process_image(filepath, output_path):
    filepath, dcraw = call_dcraw(filepath, ["-d"] if args.mode in {"gray", "mono"} else [])
    assert dcraw.wait() == 0
    x0, y0, width, height = json.loads(
        subprocess.check_output([str(path_to_own_program("undistort")), str(filepath)] +
                                correction_data.coordinates_as_strings()).decode())
    convert_call = ["convert", "-extract", "{}x{}+{}+{}".format(width, height, x0, y0), str(filepath)]
    if args.mode == "color":
        convert_call.extend(["-profile", "/home/bronger/.config/darktable/color/in/nex7_matrix.icc",
                             "-set", "colorspace", "XYZ", "-colorspace", "sRGB"])
    elif args.mode == "gray":
        convert_call.extend(["-set", "colorspace", "gray"])
    elif args.mode == "mono":
        convert_call.extend(["-set", "colorspace", "gray", "-dither", "FloydSteinberg", "-depth", "1", "-compress", "group4"])
    tiff_filepath = filepath.with_suffix(".tiff")
    convert_call.append(str(tiff_filepath))
    subprocess.check_call(convert_call)
    pdf_filepath = output_path/filepath.with_suffix(".pdf").name
    subprocess.check_call(["tesseract", str(tiff_filepath), str(pdf_filepath.parent/pdf_filepath.stem), "-l", "eng", "pdf"])
    return pdf_filepath

with tempfile.TemporaryDirectory() as tempdir:
    tempdir = Path(tempdir)
    pool = multiprocessing.Pool()
    results = set()
    for path in camera.images():
        results.add(pool.apply_async(process_image, (path, tempdir)))
    pool.close()
    pool.join()
    pdfs = []
    for result in results:
        pdfs.append(result.get())
    pdfs.sort()

    subprocess.check_call(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite", "-sOutputFile={}".format(args.filepath)] +
                          [str(pdf) for pdf in pdfs])

subprocess.check_call(["evince", str(args.filepath)])
