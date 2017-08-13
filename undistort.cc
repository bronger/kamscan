#include <fstream>
#include <vector>
#include <iterator>
#include <iostream>
#include <string>
#include "lensfun.h"

class Image {
public:
    int width, height;
    int channel_size;
    lfPixelFormat pixel_format;
    std::vector<char> data;

    Image(int width, int height, lfPixelFormat pixel_format);
    Image() {};
    int get(int x, int y, int channel);
    void set(int x, int y, int channel, int value);
};

Image::Image(int width, int height, lfPixelFormat pixel_format) :
    width(width), height(height), pixel_format(pixel_format)
{
    switch (pixel_format) {
    case LF_PF_U8:
        channel_size = 1;
        break;
    case LF_PF_U16:
        channel_size = 2;
        break;
    default:
        throw std::string("Invalid pixel format");
    }
    data.resize(width * height * channel_size * 3);
}

int Image::get(int x, int y, int channel) {
    if (x < 0 || x >= width || y < 0 || y >= height)
        return 0;
    int position = channel_size * (3 * (y * width + x) + channel);
    return int(data[position]);
}

void Image::set(int x, int y, int channel, int value) {
    if (x >= 0 && x < width && y >= 0 && y < height) {
        int position = channel_size * (3 * (y * width + x) + channel);
        data[position] = char(value);
    }
}

std::istream& operator >>(std::istream &inputStream, Image &other)
{
    std::string magic_number;
    int maximum_color_value;
    inputStream >> magic_number;
    if (magic_number != "P6")
        throw std::string("Invalid input file.  Must start with 'P6'.");
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
        throw std::string("Invalid PPM file: Maximum color value must be 255 or 65535.");
    }
    size_t size = other.width * other.height * other.channel_size * 3;
    other.data.resize(size);
    inputStream.read(other.data.data(), size);
    return inputStream;
}

std::ostream& operator <<(std::ostream &outputStream, const Image &other)
{
    outputStream << "P6" << "\n"
                 << other.width << " "
                 << other.height << "\n"
                 << (other.pixel_format == LF_PF_U8 ? "255" : "65535") << "\n";
    outputStream.write(other.data.data(), other.data.size());
    return outputStream;
}

int main(int argc, char* argv[]) {
    if (argc != 2) {
        std::cerr << "You must give path to input file.\n";
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
    const lfLens **lenses = ldb.FindLenses(camera, NULL, "E 50mm f/1.8 OSS");
    if (lenses && !lenses[1])
        lens = lenses[0];
    else if (!lenses[1]) {
        std::cerr << "Lens name ambiguous\n";
    } else {
        std::cerr << "Cannot find lens in database\n";
        lf_free(lenses);
        return -1;
    }
    lf_free(lenses);

    Image image;
    {
        std::ifstream file(argv[1], std::ios::binary);
        file >> image;
    }

    lfModifier modifier(camera->CropFactor, image.width, image.height, image.pixel_format);
    if (!modifier.EnableDistortionCorrection(lens, 50)) {
        std::cerr << "Failed to activate undistortion\n";
        return -1;
    }
    if (!modifier.EnableTCACorrection(lens, 50)) {
        std::cerr << "Failed to activate un-TCA\n";
        return -1;
    }
    std::vector<float> res(image.width * image.height * 2 * 3);
    modifier.ApplySubpixelGeometryDistortion(0, 0, image.width, image.height, res.data());

    Image new_image(image.width, image.height, image.pixel_format);
    for (int x = 0; x < image.width; x++)
        for (int y = 0; y < image.height; y++) {
            int position = 2 * 3 * (y * image.width + x);
            int source_x_R = int(res[position]);
            int source_y_R = int(res[position + 1]);
            int source_x_G = int(res[position + 2]);
            int source_y_G = int(res[position + 3]);
            int source_x_B = int(res[position + 4]);
            int source_y_B = int(res[position + 5]);
            new_image.set(x, y, 0, image.get(source_x_R, source_y_R, 0));
            new_image.set(x, y, 1, image.get(source_x_G, source_y_G, 1));
            new_image.set(x, y, 2, image.get(source_x_B, source_y_B, 2));
        }
    std::ofstream file("out.ppm", std::ios::binary);
    file << new_image;
    
    return 0;
}
