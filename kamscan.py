#!/usr/bin/python3

import argparse, pickle, time, os, tempfile, shutil, subprocess, json
from contextlib import contextmanager
from pathlib import Path


calibration_file_path = Path.home()/"aktuell/kamscan_calibration.pickle"

parser = argparse.ArgumentParser(description="Scan a document.")
parser.add_argument("--calibration", action="store_true", help="take a calibration image")
parser.add_argument("filepath", type=Path, help="path to the PDF file for storing")
args = parser.parse_args()


def wait_for_excess_processes(processes, max_processes=4):
    while len({process for process in processes if process.poll() is None}) > max_processes:
        time.sleep(1)


class Camera:
    path = Path("/media/bronger/3937-6637/DCIM")

    def __init__(self):
        with self._camera_connected():
            self.paths = self._collect_paths()

    @contextmanager
    def _camera_connected(self):
        if not self.path.exists():
            print("Bitte Kamera einstöpseln.")
        while not self.path.exists():
            time.sleep(1)
        yield
        print("Bitte Kamera ausstöpseln.")
        while self.path.exists():
            time.sleep(1)        

    def _collect_paths(self):
        result = set()
        for root, __, filenames in os.walk(str(self.path)):
            for filename in filenames:
                if os.path.splitext(filename)[1] in {".JPG", ".ARW"}:
                    filepath = Path(root)/filename
                    result.add(filepath)
        return result

    @contextmanager
    def download(self):
        tempdir = Path(tempfile.mkdtemp())
        processes = set()
        print("Bitte Bilder machen.  Dann:")
        with self._camera_connected():
            paths = self._collect_paths()
            new_paths = paths - self.paths
            for path in new_paths:
                if path.suffix == ".ARW":
                    wait_for_excess_processes(processes)
                    process = subprocess.Popen(
                        ["dcraw -c -t 5 '{0}' > '{1}.ppm' && rm '{0}'".format(path, tempdir/path.stem)], shell=True)
                    processes.add(process)
            wait_for_excess_processes(processes, max_processes=0)
        yield tempdir
        shutil.rmtree(str(tempdir), ignore_errors=True)

camera = Camera()


class CorrectionData:
    x0 = y0 = None
    x1 = y1 = None
    x2 = y2 = None
    x3 = y3 = None

    @property
    def coordinates(self):
        return [str(self.x0), str(self.y0), str(self.x1), str(self.y1),
                str(self.x2), str(self.y2), str(self.x3), str(self.y3)]

    def __repr__(self):
        return "links oben: {}, {}  rechts oben: {}, {}  links unten: {}, {}  rechts unten: {}, {}".format(
            self.x0, self.y0, self.x1, self.y1, self.x2, self.y2, self.x3, self.y3)

def analyze_scan(x, y, scaling, filepath, number_of_points):
    output = subprocess.check_output([str((Path(__file__).parent/"analyze_scan.py").resolve()), str(x), str(y), str(scaling),
                                      str(filepath), str(number_of_points)]).decode()
    print(repr(output))
    result = json.loads(output)
    return result

def analyze_calibration_image():
    with camera.download() as directory:
        filenames = os.listdir(str(directory))
        assert len(filenames) == 1
        filepath = directory/filenames[0]
        raw_points = analyze_scan(2000, 3000, 0.1, filepath, 4)
        points = [analyze_scan(x, y, 1, filepath, 1)[0] for x, y in raw_points]
    correction_data = CorrectionData()
    for point in points:
        if point[0] < 2000:
            if point[1] < 3000:
                correction_data.x0, correction_data.y0 = point
            else:
                correction_data.x2, correction_data.y2 = point
        else:
            if point[1] < 3000:
                correction_data.x1, correction_data.y1 = point
            else:
                correction_data.x3, correction_data.y3 = point
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


basename = args.filepath.parent/args.filepath.stem
intermediate_files = set()

with camera.download() as directory:
    processes = set()
    for i, filename in enumerate(os.listdir(str(directory))):
        filepath = directory/filename
        wait_for_excess_processes(processes)
        x0, y0, width, height = json.loads(
            subprocess.check_output([str((Path(__file__).parent/"undistort").resolve()), str(filepath)] +
                                    correction_data.coordinates).decode())
        out_filepath = Path("{}_{:04}.tif".format(basename, i))
        convert = subprocess.Popen(["convert", "-extract", "{}x{}+{}+{}".format(width, height, x0, y0),
                                    str(filepath), "-dither", "FloydSteinberg", "-compress", "group4", str(out_filepath)])
        intermediate_files.add(out_filepath)
        processes.add(convert)
    wait_for_excess_processes(processes, max_processes=0)


subprocess.check_call(["make_searchable_pdf.py", str(basename)])
for path in intermediate_files:
    os.remove(str(path))


subprocess.check_call(["evince", str(basename) + ".pdf"])
