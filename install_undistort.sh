#!/bin/sh
set -e

sudo rm /usr/local/lib/python3.6/dist-packages/undistort* || true
cd ~/src/kamscan
sudo rm -Rf build
./setup.py build && sudo ./setup.py install
python3 -c "import undistort"
