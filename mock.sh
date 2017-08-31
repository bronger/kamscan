#!/bin/sh
set -e
rm -Rf /tmp/kamscan
mkdir -p /tmp/kamscan/3937-6637/DCIM
if [ "$1" != "--empty" ]
then
    cp /tmp/kamscan_mock/*.ARW /tmp/kamscan/3937-6637/DCIM
fi
sudo mv /tmp/kamscan/3937-6637 /media/bronger
