#!/bin/sh
set -e
rm -Rf /tmp/kamscan
mkdir -p /tmp/kamscan/3937-6637/DCIM
if [ "$1" != "empty" ]
then
    cp /home/bronger/src/kamscan/DSC06499.ARW /tmp/kamscan/3937-6637/DCIM
fi
sudo mv /tmp/kamscan/3937-6637 /media/bronger
