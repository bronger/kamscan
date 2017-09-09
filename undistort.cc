/**
   \file undistort.cc

   Apply Lensfun corrections to a PNM file in place.  This means, the original
   file is overwritten.  The command line parameters are:
   - path to the PNM file
   - x coordinate of top left corner
   - y coordinate of top left corner
   - x coordinate of top right corner
   - y coordinate of top right corner
   - x coordinate of bottom left corner
   - y coordinate of bottom left corner
   - x coordinate of bottom right corner
   - y coordinate of bottom right corner
   - Lensfun name of camera make
   - Lensfun name of camera model
   - Lensfun name of lens make
   - Lensfun name of lens model

   All coordinates are pixel coordinates, with the top left of the image the
   origin.  The corners must be the corners of a perfect rectangle which was
   taken a picture of, e.g. a sheet of paper.  These are used for the
   perspective correction as well as the rotation, so that the edges of the
   rectangle are parellel to the image borders.

   The program returns the position and the dimensions of the rectangle <b>in
   the output image</b> to stdout in JSON format:

   \code{.json}
   [x₀, y₀, width, height]
   \endcode

   Here, x₀ and y₀ are the coordinates of the top left corner, and width and
   height are the dimensions of the rectangle.

   This program does not apply colour corrections such as vignetting
   correction, as those are handled by kamscan.py using flat field images.
*/
#include <Python.h>
#include <fstream>
#include <vector>
#include <iterator>
#include <iostream>
#include <string>
#include <algorithm>
#include <cmath>
#include "lensfun.h"

/** Class for bitmap data.

  In case of 2 bytes per channel, network byte order is assumed. */
class Image {
public:
    Image(int width, int height, int channel_size, int channels);
    Image() {};
    Image(const Image &image);
    /** Get the channel intensity at a certian coordinate.
      \param x x coordinate
      \param y y coordinate
      \param channel index of the channel (for greyscale, it is always zero;
        for RGB, it is 0, 1, or 2)
      \return raw integer value of the intensity of this channel at this
        position
    */
    int get(int x, int y, int channel);
    /** Get the channel intensity at a certian coordinate.  The coordinates are
      floats and may contain fractions.  In this case, the intensity is
      calculated using bilinear interpolation between the four pixels around
      this coordinate.
      \param x x coordinate
      \param y y coordinate
      \param channel index of the channel (for greyscale, it is always zero;
        for RGB, it is 0, 1, or 2)
      \return raw integer value of the intensity of this channel at this
        position
    */
    int get(float x, float y, int channel);
    /** Set the channel intensity at a certian coordinate.
      \param x x coordinate
      \param y y coordinate
      \param channel index of the channel (for greyscale, it is always zero;
        for RGB, it is 0, 1, or 2)
      \param value raw integer value of the intensity of this channel at this
        position
    */
    void set(int x, int y, int channel, int value);
    /** Determine the channel descriptions.  This is used by Lensfun internally
      and necessary if you want to apply colour corrections, e.g. vignetting
      correction.
      \return the components of each pixel
    */
    int components();
    /** Determine the pixel format à la Lensfun.  It is derived from
      channel_size.
      \return the pixel format as it is needed by Lensfun
     */
    lfPixelFormat pixel_format();
    int width, height; ///< width and height of the image in pixels
    int channels; ///< number of channels; may be 1 (greyscale) or 3 (RGB)
    /** the raw data (1:1 dump of the PNM content, without header)
     */
    std::vector<unsigned char> data;

private:
    friend std::istream& operator>>(std::istream &inputStream, Image &other);
    friend std::ostream& operator<<(std::ostream &outputStream, const Image &other);
    int channel_size; ///< width of one channel in bytes; may be 1 or 2
};

Image::Image(int width, int height, int channel_size, int channels) :
    width(width), height(height), channel_size(channel_size), channels(channels)
{
    data.resize(width * height * channel_size * channels);
}

Image::Image(const Image &image) :
    width(image.width), height(image.height), channel_size(image.channel_size), channels(image.channels) {
    data.resize(width * height * channel_size * channels);
}

int Image::get(int x, int y, int channel) {
    if (x < 0 || x >= width || y < 0 || y >= height)
        return 0;
    int position = channel_size * (channels * (y * width + x) + channel);
    int result = static_cast<int>(data[position]);
    if (channel_size == 2)
        result = (result << 8) + static_cast<int>(data[position + 1]);
    return result;
}

int Image::get(float x, float y, int channel) {
    float dummy;
    int x0 = static_cast<int>(x);
    int y0 = static_cast<int>(y);
    float i0 = static_cast<float>(get(x0, y0, channel));
    float i1 = static_cast<float>(get(x0 + 1, y0, channel));
    float i2 = static_cast<float>(get(x0, y0 + 1, channel));
    float i3 = static_cast<float>(get(x0 + 1, y0 + 1, channel));
    float fraction_x = std::modf(x, &dummy);
    float i01 = (1 - fraction_x) * i0 + fraction_x * i1;
    float i23 = (1 - fraction_x) * i2 + fraction_x * i3;
    float fraction_y = std::modf(y, &dummy);
    return static_cast<int>(std::round((1 - fraction_y) * i01 + fraction_y * i23));
}

void Image::set(int x, int y, int channel, int value) {
    if (x >= 0 && x < width && y >= 0 && y < height) {
        int position = channel_size * (channels * (y * width + x) + channel);
        if (channel_size == 1)
            data[position] = static_cast<unsigned char>(value);
        else if (channel_size == 2) {
            data[position] = static_cast<unsigned char>(value >> 8);
            data[position + 1] = static_cast<unsigned char>(value & 256);
        }
    }
}

int Image::components() {
    switch (channels) {
    case 1:
        return LF_CR_1(INTENSITY);
    case 3:
        return LF_CR_3(RED, GREEN, BLUE);
    default:
        throw std::runtime_error("Invalid value of 'channels'.");
    }
}

lfPixelFormat Image::pixel_format() {
    switch (channel_size) {
    case 1:
        return LF_PF_U8;
    case 2:
        return LF_PF_U16;
    default:
        throw std::runtime_error("Invalid value of 'channel_size'.");
    }
}

std::istream& operator>>(std::istream &inputStream, Image &other)
{
    std::string magic_number;
    int maximum_color_value;
    inputStream >> magic_number;
    if (magic_number == "P5")
        other.channels = 1;
    else if (magic_number == "P6")
        other.channels = 3;
    else
        throw std::runtime_error("Invalid input file.  Must start with 'P5' or 'P6'.");
    inputStream >> other.width >> other.height >> maximum_color_value;
    inputStream.get(); // skip the trailing white space
    switch (maximum_color_value) {
    case 255:
        other.channel_size = 1;
        break;
    case 65535:
        other.channel_size = 2;
        break;
    default:
        throw std::runtime_error("Invalid PPM file: Maximum color value must be 255 or 65535.");
    }
    size_t size = other.width * other.height * other.channel_size * other.channels;
    other.data.resize(size);
    inputStream.read(reinterpret_cast<char*>(other.data.data()), size);
    return inputStream;
}

std::ostream& operator<<(std::ostream &outputStream, const Image &other)
{
    outputStream << (other.channels == 3 ? "P6" : "P5") << "\n"
                 << other.width << " "
                 << other.height << "\n"
                 << (other.channel_size == 1 ? "255" : "65535") << "\n";
    outputStream.write(reinterpret_cast<const char*>(other.data.data()), other.data.size());
    return outputStream;
}

static PyObject *undistort(PyObject *self, PyObject *args) {
    const char *filename, *camera_make, *camera_model, *lens_make, *lens_model;
    float x0, y0, x1, y1, x2, y2, x3, y3;
    PyArg_ParseTuple(args, "sffffffffssss", &filename, &x0, &y0, &x1, &y1, &x2, &y2, &x3, &y3,
                     &camera_make, &camera_model, &lens_make, &lens_model);

    lfDatabase ldb;

    if (ldb.Load() != LF_NO_ERROR) {
        PyErr_SetString(PyExc_RuntimeError, "Database could not be loaded");
        return NULL;
    }

    const lfCamera *camera;
    const lfCamera **cameras = ldb.FindCamerasExt(camera_make, camera_model);
    if (cameras && !cameras[1])
        camera = cameras[0];
    else {
        std::vector<char> buffer(std::snprintf(nullptr, 0, "Cannot find unique camera in database.  %i cameras found.",
                                               (int)sizeof(cameras)));
        std::snprintf(&buffer[0], buffer.size(), "Cannot find unique camera in database.  %i cameras found.",
                      (int)sizeof(cameras));
        PyErr_SetString(PyExc_RuntimeError, buffer.data());
        lf_free(cameras);
        return NULL;
    }
    lf_free(cameras);

    const lfLens *lens;
    const lfLens **lenses = ldb.FindLenses(camera, lens_make, lens_model);
    if (lenses && !lenses[1]) {
        lens = lenses[0];
    } else if (!lenses) {
        PyErr_SetString(PyExc_RuntimeError, "Cannot find lens in database");
        lf_free(lenses);
        return NULL;
    } else {
        PyErr_SetString(PyExc_RuntimeError, "Lens name ambiguous");
        lf_free(lenses);
        return NULL;
    }
    lf_free(lenses);

    Image image;
    {
        std::ifstream file(filename, std::ios::binary);
        file >> image;
    }

    lfModifier modifier(camera->CropFactor, image.width, image.height, image.pixel_format());
    lfModifier pc_coord_modifier(camera->CropFactor, image.width, image.height, image.pixel_format(), true);
    lfModifier back_modifier(camera->CropFactor, image.width, image.height, image.pixel_format(), true);
    if (!modifier.EnableDistortionCorrection(lens, 50) || !back_modifier.EnableDistortionCorrection(lens, 50) ||
        !pc_coord_modifier.EnableDistortionCorrection(lens, 50)) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to activate undistortion");
        return NULL;
    }
    if (image.channels == 3)
        if (!modifier.EnableTCACorrection(lens, 50)) {
            PyErr_SetString(PyExc_RuntimeError, "Failed to activate un-TCA");
            return NULL;
        }
    std::vector<float> x, y;
    x.push_back(x0);
    y.push_back(y0);

    x.push_back(x2);
    y.push_back(y2);

    x.push_back(x1);
    y.push_back(y1);

    x.push_back(x3);
    y.push_back(y3);

    x.push_back(x0);
    y.push_back(y0);

    x.push_back(x1);
    y.push_back(y1);
    std::vector<float> x_undist, y_undist;
    for (int i = 0; i < x.size(); i++) {
        float result[2];
        pc_coord_modifier.ApplyGeometryDistortion(x[i], y[i], 1, 1, result);
        x_undist.push_back(result[0]);
        y_undist.push_back(result[1]);
    }
    if (!modifier.EnablePerspectiveCorrection(lens, 50, x_undist.data(), y_undist.data(), 6, 0) ||
        !back_modifier.EnablePerspectiveCorrection(lens, 50, x_undist.data(), y_undist.data(), 6, 0)) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to activate perspective correction");
        return NULL;
    }

    std::vector<float> res(image.width * image.height * 2 * image.channels);
    if (image.channels == 3)
        modifier.ApplySubpixelGeometryDistortion(0, 0, image.width, image.height, res.data());
    else
        modifier.ApplyGeometryDistortion(0, 0, image.width, image.height, res.data());
    Image new_image = image;
    for (int x = 0; x < image.width; x++)
        for (int y = 0; y < image.height; y++) {
            int position = 2 * image.channels * (y * image.width + x);
            float source_x_R = res[position];
            float source_y_R = res[position + 1];
            new_image.set(x, y, 0, image.get(source_x_R, source_y_R, 0));
            if (image.channels == 3) {
                float source_x_G = res[position + 2];
                float source_y_G = res[position + 3];
                float source_x_B = res[position + 4];
                float source_y_B = res[position + 5];
                new_image.set(x, y, 1, image.get(source_x_G, source_y_G, 1));
                new_image.set(x, y, 2, image.get(source_x_B, source_y_B, 2));
            }
        }
    std::ofstream file(filename, std::ios::binary);
    file << new_image;

    for (int i = 0; i < 4; i++) {
        float result[2];
        back_modifier.ApplyGeometryDistortion(x[i], y[i], 1, 1, result);
        x[i] = result[0];
        y[i] = result[1];
    }
    
    return Py_BuildValue("ffff", std::min(x[0], x[2]), std::min(y[0], y[1]),
                         std::max(x[1], x[3]) - std::min(x[0], x[2]), std::max(y[2], y[3]) - std::min(y[0], y[1]));
}

static PyMethodDef UndistortMethods[] = {
    {"undistort",  undistort, METH_VARARGS, "Undistort PNM image data."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef undistortmodule = {
   PyModuleDef_HEAD_INIT, "undistort", NULL, -1, UndistortMethods
};

PyMODINIT_FUNC
PyInit_undistort(void)
{
    return PyModule_Create(&undistortmodule);
}
