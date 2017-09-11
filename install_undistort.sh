#!/bin/sh

sudo rm /usr/local/lib/python3.5/dist-packages/undistort*
sudo rm /usr/local/lib/python3.5/dist-packages/undistort.cpython-35m-x86_64-linux-gnu.so
cd ~/src/kamscan
sudo rm -Rf build
./setup.py build && sudo ./setup.py install && python3 -c "import undistort"
