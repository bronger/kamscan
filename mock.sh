#!/bin/sh
# Two parameters: mode and count.  mode must be gray, color, or two-side.
# count is is number of (identical) scans.
set -e
rm -Rf /tmp/kamscan
mkdir -p /tmp/kamscan/3937-6637/DCIM
if [ "$2" != "0" ]
then
    cp ~/temp/kamscan_mock/$1.ARW /tmp/kamscan/3937-6637/DCIM
fi
count=1
while [ $count -lt $2 ]
do
    ln /tmp/kamscan/3937-6637/DCIM/$1.ARW /tmp/kamscan/3937-6637/DCIM/$count.ARW
    count=`expr $count + 1`
done
sudo mv /tmp/kamscan/3937-6637 /media/bronger
