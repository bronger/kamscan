#include "opencv2/highgui/highgui.hpp"
#include "opencv2/imgproc/imgproc.hpp"
#include <iostream>
#include <stdio.h>
#include <stdlib.h>

using namespace cv;
using namespace std;

int main(int argc, char** argv) {
    Mat src, src_gray;
    Mat dst, dst_norm, dst_norm_scaled;
    dst = Mat::zeros(src.size(), CV_32FC1);

    /// Detector parameters
    int blockSize = 2;
    int apertureSize = 3;
    double k = 0.04;

    /// Load source image and convert it to gray
    src = imread(argv[1], 1);
    cvtColor(src, src_gray, CV_BGR2GRAY);

    /// Detecting corners
    cornerHarris(src_gray, dst, blockSize, apertureSize, k, BORDER_DEFAULT);

    /// Normalizing
    normalize(dst, dst_norm, 0, 255, NORM_MINMAX, CV_32FC1, Mat());
    convertScaleAbs(dst_norm, dst_norm_scaled);

    int occurences[256];
    fill(occurences, occurences + 256, 0);

    for (int j = 0; j < dst_norm.rows; j++) {
        for (int i = 0; i < dst_norm.cols; i++) {
            int index = (int) dst_norm.at<float>(j, i);
            occurences[index]++;
        }
    }
    int threshold;
    int corners_found = 0;
    int four_corners = -1;
    int five_corners = -1;
    for (threshold = 255; threshold >= 0; threshold--) {
        corners_found += occurences[threshold];
        if (four_corners == -1 && corners_found >= 4)
            four_corners = threshold;
        if (five_corners == -1 && corners_found >= 5) {
            five_corners = threshold;
            break;
        }
    }
    cout << "{\"threshold_4_corners\": " << four_corners << ",\n"
         << " \"threshold_5_corners\": " << five_corners << ",\n";
    cout << " \"points\": [";
    int counter = 0;
    for (int j = 0; j < dst_norm.rows; j++) {
        for (int i = 0; i < dst_norm.cols; i++) {
            if ((int) dst_norm.at<float>(j, i) >= four_corners) {
                if (counter > 0) cout << ", ";
                cout << "[" << i << ", " << j << "]";
                counter++;
//                if (counter == 4) goto end_loop;
            }
        }
    }
end_loop:
    cout << "]}\n";
}
