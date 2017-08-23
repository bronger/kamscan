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

    def images(self, tempdir):
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


def call_dcraw(path, extra_raw, gray=False, b=None):
    dcraw_call = ["dcraw", "-t", "5"]
    if extra_raw:
        dcraw_call.extend(["-o", "0", "-M", "-6", "-g", "1", "1", "-r", "1", "1", "1", "1", "-W"])
    if gray:
        dcraw_call.append("-d")
    if b is not None:
        dcraw_call.extend(["-b", str(b)])
    dcraw_call.append(str(path))
    subprocess.check_call(dcraw_call)
    output_path = path.with_suffix(".pgm") if "-d" in dcraw_call else path.with_suffix(".ppm")
    assert output_path.exists()
    return output_path


class CorrectionData:

    def __init__(self):
        self.coordinates = 8 * [None]

    def coordinates_as_strings(self):
        return [str(coordinate) for coordinate in self.coordinates]

    def __repr__(self):
        return "links oben: {}, {}  rechts oben: {}, {}  links unten: {}, {}  rechts unten: {}, {}".format(*self.coordinates)


def analyze_scan(x, y, scaling, filepath, number_of_points):
    output = subprocess.check_output([str(path_to_own_program("analyze_scan.py")), str(x), str(y), str(scaling),
                                      str(filepath), str(number_of_points)]).decode()
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

            path = call_dcraw(old_path, extra_raw=True, gray=True)
            shutil.move(str(path), str(calibration_file_path.parent/"kamscan_flatfield.pgm"))
            path = call_dcraw(old_path, extra_raw=True)
            shutil.move(str(path), str(calibration_file_path.parent/"kamscan_flatfield.ppm"))
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


def process_image(filepath, output_path):
    filepath = call_dcraw(filepath, extra_raw=True, gray=args.mode in {"gray", "mono"}, b=0.9)
    flatfield_path = (calibration_file_path.parent/"kamscan_flatfield").with_suffix(
        ".pgm" if args.mode in {"gray", "mono"} else ".ppm")
    tempfile = (filepath.parent/(filepath.stem + "-temp")).with_suffix(filepath.suffix)
    subprocess.check_call(["convert", str(filepath), str(flatfield_path), "-compose", "dividesrc", "-composite",
                           str(tempfile)])
    os.rename(str(tempfile), str(filepath))
    x0, y0, width, height = json.loads(
        subprocess.check_output([str(path_to_own_program("undistort")), str(filepath)] +
                                correction_data.coordinates_as_strings()).decode())
    subprocess.check_call(["convert", "-extract", "{}x{}+{}+{}".format(width, height, x0, y0), str(filepath), str(tempfile)])
    os.rename(str(tempfile), str(filepath))
    convert_call = ["convert", str(filepath)]
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
    for path in camera.images(tempdir):
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
