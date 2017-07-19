#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
from kivy.app import App
from kivy.uix.image import Image


class Result(Exception):
    def __init__(self, x, y, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.x, self.y = x, y


class ImageWindow(Image):

    def __init__(self, x, y, scaling, source, *args, **kwargs):
        raw_width, raw_height = subprocess.check_output(["identify", source]).decode().split()[2].split("x")
        self.crop_width = min(int(raw_width), 1100 / scaling)
        self.crop_height = min(int(raw_height), 900 / scaling)
        self.x0 = x - self.crop_width / 2
        self.y0 = y - self.crop_height / 2
        subprocess.check_call(["convert", "-extract", "{}x{}+{}+{}".format(self.crop_width, self.crop_height,
                                                                           self.x0, self.y0), source, "+repage",
                               "-resize", "{}%".format(scaling * 100), "/tmp/analyze_scan.ppm"])
        self.scaling = scaling
        kwargs["source"] = "/tmp/analyze_scan.ppm"
        super().__init__(*args, **kwargs)

    def on_touch_down(self, touch):
        image_width, image_height = self.norm_image_size
        offset_x = (self.width - image_width) / 2
        offset_y = (self.height - image_height) / 2
        x = (touch.x - offset_x) * self.crop_width / image_width
        y = self.crop_height - (touch.y - offset_y) * self.crop_height / image_height
        raise Result(x + self.x0, y + self.y0)


class AnalyzeApp(App):

    def __init__(self, x, y, scaling, source, *args, **kwargs):
        self.x = x
        self.y = y
        self.scaling = scaling
        self.source = source
        super().__init__(*args, **kwargs)

    def build(self):
        return ImageWindow(self.x, self.y, self.scaling, self.source)

    def run(self):
        try:
            super().run()
        except Result as result:
            return result.x, result.y

x, y = AnalyzeApp(3000, 2000, 0.1, "DSC06499.ppm").run()
print(x, y)
