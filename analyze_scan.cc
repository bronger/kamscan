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
    int apertureSize = 31;
    double k = 0.01;

    /// Load source image and convert it to gray
    src = imread(argv[1], 1);
    cvtColor(src, src_gray, CV_BGR2GRAY);

    /// Detecting corners
    cornerHarris(src_gray, dst, blockSize, apertureSize, k, BORDER_DEFAULT);

    /// Normalizing
    normalize(dst, dst_norm, 0, 255, NORM_MINMAX, CV_32FC1, Mat());
    convertScaleAbs(dst_norm, dst_norm_scaled);

    int occurences[4][256];
    for (int i = 0; i < 4; i++)
        fill(occurences[i], occurences[i] + 256, 0);

    for (int j = 0; j < dst_norm.rows; j++) {
        for (int i = 0; i < dst_norm.cols; i++) {
            int index = (int) dst_norm.at<float>(j, i);
            int quadrant;
            if (i < dst_norm.cols / 2)
                quadrant = j < dst_norm.rows / 2 ? 0 : 1;
            else
                quadrant = j < dst_norm.rows / 2 ? 2 : 3;
            occurences[quadrant][index]++;
        }
    }
    cout << "\n";
    int threshold;
    int corners_found[4] = {0, 0, 0, 0};
    for (threshold = 255; threshold >= 0; threshold--) {
        bool corner_in_every_quadrant = true;
        for (int i = 0; i < 4; i++) {
            corners_found[i] += occurences[i][threshold];
            if (corners_found[i] == 0)
                corner_in_every_quadrant = false;
        }
        if (corner_in_every_quadrant)
            break;
    }
    cout << "{\"threshold\": " << threshold << ",\n";
    cout << " \"points\": [";
    bool first = true;
    for (int j = 0; j < dst_norm.rows; j++) {
        for (int i = 0; i < dst_norm.cols; i++) {
            if ((int) dst_norm.at<float>(j, i) >= threshold) {
                if (!first) cout << ", "; else first = false;
                cout << "[" << i << ", " << j << "]";
            }
        }
    }
end_loop:
    cout << "]}\n";
}
