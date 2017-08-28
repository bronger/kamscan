#include <fstream>
#include <vector>
#include <iterator>
#include <iostream>
#include <string>
#include <algorithm>
#include <cmath>
#include "lensfun.h"

class Image {
public:
    int width, height;
    int channel_size;
    int channels;
    int components;
    lfPixelFormat pixel_format;
    std::vector<unsigned char> data;

    Image(int width, int height, lfPixelFormat pixel_format, int channels);
    Image() {};
    int get(int x, int y, int channel);
    int get(float x, float y, int channel);
    void set(int x, int y, int channel, int value);
};

Image::Image(int width, int height, lfPixelFormat pixel_format, int channels) :
    width(width), height(height), pixel_format(pixel_format), channels(channels)
{
    switch (pixel_format) {
    case LF_PF_U8:
        channel_size = 1;
        break;
    case LF_PF_U16:
        channel_size = 2;
        break;
    default:
        throw std::runtime_error("Invalid pixel format");
    }
    switch (channels) {
    case 1:
        components = LF_CR_1(INTENSITY);
        break;
    case 3:
        components = LF_CR_3(RED, GREEN, BLUE);
        break;
    default:
        throw std::runtime_error("Invalid number of color channels");
    }
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

std::istream& operator >>(std::istream &inputStream, Image &other)
{
    std::string magic_number;
    int maximum_color_value;
    inputStream >> magic_number;
    if (magic_number == "P5") {
        other.channels = 1;
        other.components = LF_CR_1(INTENSITY);
    } else if (magic_number == "P6") {
        other.channels = 3;
        other.components = LF_CR_3(RED, GREEN, BLUE);
    }
    else
        throw std::runtime_error("Invalid input file.  Must start with 'P5' or 'P6'.");
    inputStream >> other.width >> other.height >> maximum_color_value;
    inputStream.get(); // skip the trailing white space
    switch (maximum_color_value) {
    case 255:
        other.pixel_format = LF_PF_U8;
        other.channel_size = 1;
        break;
    case 65535:
        other.pixel_format = LF_PF_U16;
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

std::ostream& operator <<(std::ostream &outputStream, const Image &other)
{
    outputStream << (other.channels == 3 ? "P6" : "P5") << "\n"
                 << other.width << " "
                 << other.height << "\n"
                 << (other.pixel_format == LF_PF_U8 ? "255" : "65535") << "\n";
    outputStream.write(reinterpret_cast<const char*>(other.data.data()), other.data.size());
    return outputStream;
}

int main(int argc, char* argv[]) {
    if (argc != 10) {
        std::cerr << "You must give path to input file as well as all four corner coordinates.\n";
        return -1;
    }

    lfDatabase ldb;

    if (ldb.Load() != LF_NO_ERROR) {
        std::cerr << "Database could not be loaded\n";
        return -1;
    }

    const lfCamera *camera;
    const lfCamera **cameras = ldb.FindCamerasExt(NULL, "NEX-7");
    if (cameras && !cameras[1])
        camera = cameras[0];
    else {
        std::cerr << "Cannot find unique camera in database.  " << sizeof(cameras) << " cameras found.\n";
        lf_free(cameras);
        return -1;
    }
    lf_free(cameras);

    const lfLens *lens;
    const lfLens **lenses = ldb.FindLenses(camera, NULL, "E 50mm f/1.8 OSS (kamscan)");
    if (lenses && !lenses[1]) {
        lens = lenses[0];
    } else if (!lenses) {
        std::cerr << "Cannot find lens in database\n";
        lf_free(lenses);
        return -1;
    } else {
        std::cerr << "Lens name ambiguous\n";
    }
    lf_free(lenses);

    Image image;
    {
        std::ifstream file(argv[1], std::ios::binary);
        file >> image;
    }

    lfModifier modifier(camera->CropFactor, image.width, image.height, image.pixel_format);
    lfModifier pc_coord_modifier(camera->CropFactor, image.width, image.height, image.pixel_format, true);
    lfModifier back_modifier(camera->CropFactor, image.width, image.height, image.pixel_format, true);
    if (!modifier.EnableDistortionCorrection(lens, 50) || !back_modifier.EnableDistortionCorrection(lens, 50) ||
        !pc_coord_modifier.EnableDistortionCorrection(lens, 50)) {
        std::cerr << "Failed to activate undistortion\n";
        return -1;
    }
    if (image.components == 3)
        if (!modifier.EnableTCACorrection(lens, 50)) {
            std::cerr << "Failed to activate un-TCA\n";
            return -1;
        }
    std::vector<float> x, y;
    x.push_back(std::stof(argv[2]));
    y.push_back(std::stof(argv[3]));

    x.push_back(std::stof(argv[6]));
    y.push_back(std::stof(argv[7]));

    x.push_back(std::stof(argv[4]));
    y.push_back(std::stof(argv[5]));

    x.push_back(std::stof(argv[8]));
    y.push_back(std::stof(argv[9]));

    x.push_back(std::stof(argv[2]));
    y.push_back(std::stof(argv[3]));

    x.push_back(std::stof(argv[4]));
    y.push_back(std::stof(argv[5]));
    std::vector<float> x_undist, y_undist;
    for (int i = 0; i < x.size(); i++) {
        float result[2];
        pc_coord_modifier.ApplyGeometryDistortion(x[i], y[i], 1, 1, result);
        x_undist.push_back(result[0]);
        y_undist.push_back(result[1]);
    }
    if (!modifier.EnablePerspectiveCorrection(lens, 50, x_undist.data(), y_undist.data(), 6, 0) ||
        !back_modifier.EnablePerspectiveCorrection(lens, 50, x_undist.data(), y_undist.data(), 6, 0)) {
        std::cerr << "Failed to activate perspective correction\n";
        return -1;
    }

    std::vector<float> res(image.width * image.height * 2 * image.channels);
    if (image.channels == 3)
        modifier.ApplySubpixelGeometryDistortion(0, 0, image.width, image.height, res.data());
    else
        modifier.ApplyGeometryDistortion(0, 0, image.width, image.height, res.data());
    Image new_image(image.width, image.height, image.pixel_format, image.channels);
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
    std::ofstream file(argv[1], std::ios::binary);
    file << new_image;

    for (int i = 0; i < 4; i++) {
        float result[2];
        back_modifier.ApplyGeometryDistortion(x[i], y[i], 1, 1, result);
        x[i] = result[0];
        y[i] = result[1];
    }
    std::cout << "[" << std::min(x[0], x[2]) << ", " << std::min(y[0], y[1]) <<
        ", " << std::max(x[1], x[3]) - std::min(x[0], x[2]) << ", " << std::max(y[2], y[3]) - std::min(y[0], y[1]) << "]\n";
    
    return 0;
}
