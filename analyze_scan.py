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

    def __init__(self, x, y, scaling, *args, **kwars):
        super().__init__(*args, **kwars)
        # FixMe: Make use of x, y, and scaling
        ...
        file_width, file_height = subprocess.check_output(["identify", self.source]).decode().split()[2].split("x")
        self.file_width, self.file_height = int(file_width), int(file_height)

    def on_touch_down(self, touch):
        image_width, image_height = self.norm_image_size
        offset_x = (self.width - image_width) / 2
        offset_y = (self.height - image_height) / 2
        x = (touch.x - offset_x) * self.file_width / image_width
        y = self.file_height - (touch.y - offset_y) * self.file_height / image_height
        raise Result(x, y)


class AnalyzeApp(App):

    def __init__(self, x, y, scaling, source, *args, **kwargs):
        self.x = x
        self.y = y
        self.scaling = scaling
        self.source = source
        super().__init__(*args, **kwargs)

    def build(self):
        return ImageWindow(self.x, self.y, self.scaling, source=self.source)

    def run(self):
        try:
            super().run()
        except Result as result:
            return result.x, result.y

x, y = AnalyzeApp(3000, 2000, 0.1, "DSC06499.ppm").run()
print(x, y)
