#!/usr/bin/python3
#-*- mode: python -*-

import argparse, pickle, time, os, tempfile, shutil, subprocess
from contextlib import contextmanager
from pathlib import Path


calibration_file_path = Path.home()/"aktuell/kamscan_calibration.pickle"

parser = argparse.ArgumentParser(description="Scan a document.")
parser.add_argument("--calibration", action="store_true", help="take a calibration image")
args = parser.parse_args()


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

    @staticmethod
    def _wait_for_excess_processes(processes, max_processes=4):
        while len({process for process in processes if process.poll() is not None}) > max_processes:
            time.sleep(1)

    @contextmanager
    def download(self):
        tempdir = Path(tempfile.mkdtemp())
        processes = set()
        with self._camera_connected():
            paths = self._collect_paths()
            new_paths = paths - self.paths
            for path in new_paths:
                if path.suffix == ".ARW":
                    self._wait_for_excess_processes(processes)
                    process = subprocess.Popen(["dcraw", "-4", "-c", str(path), ">", str(tempdir/path.name), "&&",
                                                "rm", str(path)], shell=True)
                    processes.add(process)
        self._wait_for_excess_processes(processes, max_processes=0)
        yield tempdir
        shutil.rmtree(str(tempdir), ignore_errors=True)

camera = Camera()


class CorrectionData:
    x0 = y0 = None
    x1 = y1 = None

def analyze_calibration_image():
    with camera.download() as directory:
        filenames = os.listdir(str(directory))
        assert len(filenames) == 1
        # TBD: Work with filenames[0]
        ...

def get_correction_data():
    correction_data = analyze_calibration_image()
    pickle.dump(open(str(calibration_file_path), "wb"), correction_data)
    return correction_data

if args.calibration:
    correction_data = get_correction_data()
else:
    try:
        correction_data = pickle.load(open(str(calibration_file_path), "rb"))
    except FileNotFoundError:
        correction_data = get_correction_data()


with camera.download() as directory:
    # TBD: Process images
    ...
