undistort: undistort.cc
	c++ -ggdb -O1 -I /usr/local/include/lensfun -L /usr/local/lib undistort.cc -o undistort -llensfun
