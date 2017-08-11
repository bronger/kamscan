undistort: undistort.cc
	c++ -O2 -I /usr/local/include/lensfun -L /usr/local/lib undistort.cc -o undistort -llensfun
