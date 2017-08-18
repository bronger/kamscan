#!/usr/bin/python3

import subprocess, json, sys
from kivy.app import App
from kivy.uix.image import Image
from kivy.config import Config


Config.set("kivy", "log_enable", "0")


class Result(Exception):
    def __init__(self, points, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.points = points


class ImageWindow(Image):

    def __init__(self, x, y, scaling, source, number_of_points, *args, **kwargs):
        raw_width, raw_height = subprocess.check_output(["identify", source]).decode().split()[2].split("x")
        raw_width, raw_height = int(raw_width), int(raw_height)
        self.crop_width = min(raw_width, 1100 / scaling)
        self.crop_height = min(raw_height, 900 / scaling)
        self.x0 = x - self.crop_width / 2
        self.y0 = y - self.crop_height / 2
        if self.x0 < 0:
            self.crop_width += self.x0
            self.x0 = 0
        if self.x0 + self.crop_width > raw_width:
            self.crop_width = raw_width - self.x0
        if self.y0 < 0:
            self.crop_height += self.y0
            self.y0 = 0
        if self.y0 + self.crop_height > raw_height:
            self.crop_height = raw_height - self.y0
        subprocess.check_call(["convert", "-extract", "{}x{}+{}+{}".format(self.crop_width, self.crop_height,
                                                                           self.x0, self.y0), source, "+repage",
                               "-resize", "{}%".format(scaling * 100), "/tmp/analyze_scan.ppm"])
        kwargs["source"] = "/tmp/analyze_scan.ppm"
        super().__init__(*args, **kwargs)
        self.number_of_points = number_of_points
        self.points = []

    def on_touch_down(self, touch):
        image_width, image_height = self.norm_image_size
        offset_x = (self.width - image_width) / 2
        offset_y = (self.height - image_height) / 2
        x = (touch.x - offset_x) * self.crop_width / image_width
        y = self.crop_height - (touch.y - offset_y) * self.crop_height / image_height
        self.points.append((int(x + self.x0), int(y + self.y0)))
        if len(self.points) == self.number_of_points:
            raise Result(self.points)


class AnalyzeApp(App):

    def __init__(self, x, y, scaling, source, number_of_points, *args, **kwargs):
        self.x = x
        self.y = y
        self.scaling = scaling
        self.source = source
        self.number_of_points = number_of_points
        super().__init__(*args, **kwargs)

    def build(self):
        return ImageWindow(self.x, self.y, self.scaling, self.source, self.number_of_points)

    def run(self):
        try:
            super().run()
        except Result as result:
            return result.points


result = AnalyzeApp(int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), sys.argv[4], int(sys.argv[5])).run()
json.dump(result, sys.stdout)
