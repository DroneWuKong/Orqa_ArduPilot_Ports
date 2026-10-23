#!/bin/sh
# Preserve vendor USB behavior; repair only the SD mount path.
if [ "$1" = sdcard ]; then
    exec /usr/bin/python3 /usr/local/lib/orqa-logging/mount_sd.py "$2"
fi
exec /bin/sh /etc/udev/scripts/orqa-drive-mounting.sh.pre-orqa-logging "$@"
