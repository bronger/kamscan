#!/bin/sh
set -e
# Please install the profile first with:
#
# rsync -r --delete ~/temp/kamscan_mock/profiles/default/ ~/.config/kamscan/profiles/default/

./unmock.sh ; sleep 3
./mock.sh $1 0 ; sleep 3
./unmock.sh ; sleep 3
./mock.sh $1 $2 ; sleep 10
./unmock.sh
