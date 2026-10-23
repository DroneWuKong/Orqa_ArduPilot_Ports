# APB i.MX DataFlash logging

This package supplies **live ArduPilot DataFlash recording and verified
post-flight archival** to the Linux-owned microSD. It does not use PX4 ULog,
open the UART, change FC parameters, erase onboard flash, format a card or
restart telemetry when storage fails. Hardware qualification is still required.

## What runs where

APB UART4 PC10/PC11 → i.MX `/dev/ttymxc2` → existing mavlink-router → dedicated
loopback endpoints: live recorder 14561, archive worker 14562. Files go to
`/sdcard/ardupilot`. The existing router remains the only UART owner.

- `recorder.py`: native REMOTE_LOG_DATA_BLOCK protocol, bounded reordering,
  duplicate/conflict checks, retransmission requests and ACK **after fsync**.
  Source FC system ID defaults to 1, FC log component to 155. Receiver IDs are
  245/191 (live) and 246/191 (archive); reserve these IDs across the routed network.
- `archive.py`: disarmed-only LOG_REQUEST_LIST/LOG_REQUEST_DATA recovery of
  onboard logs. It checks every offset/length, retries missing bytes and requires
  two complete reads with equal SHA256 plus an unchanged inventory. It never
  sends LOG_ERASE. `--watch` archives at startup and after observed disarms,
  following thirty seconds continuously disarmed; it aborts if arming occurs.
- `storage.py`: checks a real read-write SD mount through mountinfo/sysfs,
  rejects eMMC/root/symlinks, pins the opened directory, reserves 256 MiB and
  stops on media removal, replacement or I/O failure. One writer per role.
  No retention deletion: export/remove old logs manually before the reserve fills.

**Live is not a complete-log guarantee.** The upstream stream has no EOF or
final partial-block length and can drop producer records under bandwidth/buffer
pressure. Cleanly stopped live files end `.stream.bin`; their receipts explicitly
say `complete: false`. Aborted captures remain `.partial` and are not auto-deleted.
Use the archive worker to recover the full advertised onboard byte range,
including the tail. W25 page padding may remain in archived DataFlash files.
Even `complete: true` means a verified transfer, not loss-free FC logging or
flight qualification. Inspect ArduPilot logger drop counters as well.

A capture is finalized only when its matching JSON receipt exists and its
SHA256 matches. The receipt is published last. A crash can leave a data file
with only a `.json.partial` receipt; preserve it for inspection, not as a
verified complete capture. This package is GPL-3.0-or-later; see COPYING.

## Install on a disarmed bench

Download `companion-apb.tar.gz` and `SHA256SUMS` from this repository's tagged
prerelease, verify the archive checksum, and extract it. Or use this directory
from the exact port source commit. Python 3.10+, Linux/glibc with renameat2,
systemd, an SD filesystem supporting fsync/atomic rename, and the existing
MAVLink router are required. FAT/exFAT do not need hard-link support.

From the extracted directory (or `companion/apb`):

```sh
sudo python3 -m venv /opt/orqa-ardupilot-logger/venv
sudo /opt/orqa-ardupilot-logger/venv/bin/pip install -r requirements.txt
sudo python3 install.py --repair-vendor-mount
```

The optional mount repair accepts only the inspected Scarthgap v1.0.5 vendor
helper SHA256 `501cf034fb6afb04f4fb8036139ab9b131d005c19863d522c95a76d8616452f6`.
It preserves it as `/etc/udev/scripts/orqa-drive-mounting.sh.pre-orqa-logging`
and replaces only the SD path; USB behavior is delegated to that backup.
It fixes quiet-command status checks and asynchronous success reporting, rejects
non-SD media and mounts synchronously with `nosuid,nodev,noexec`.

If the earlier PX4 SD repair is already installed, **keep it** and omit
`--repair-vendor-mount`. Do not replace a working mount helper just to switch
FC firmware. Unknown/custom files are rejected before installation writes.
`--root /path/to/staging-root` is supported. The installer never enables or
restarts services or installs dependencies. A failed/unknown mount must be
resolved rather than bypassing the guard; no-card boot simply leaves logging
unavailable and the service retries without taking down telemetry.

## Configure and activate

Back up FC parameters first. Verify the matching APB sensor variant, USB ID,
factory bootloader layout and axes. Existing saved parameters override defaults.

- UART4 is ArduPilot SERIAL4: MAVLink2 (`SERIAL4_PROTOCOL=2`), 230400 baud
  (`SERIAL4_BAUD=230`). Confirm the router UART baud matches.
- Onboard W25 logging defaults to `LOG_BACKEND_TYPE=4`. **Keep this for archive
  only.** To enable both onboard and live logging, explicitly select
  `LOG_BACKEND_TYPE=6` on the bench and reboot. MAVLink logging is already compiled
  into these builds; no custom firmware change is needed.
- Start with the upstream `LOG_MAV_RATEMAX=10` and `LOG_MAV_BUFSIZE=8`; do not
  assume every high-rate log fits the 230400 link. Keep onboard logging enabled.
- Use `LOG_DISARMED=0` for stable post-flight archives. Persistent logging while
  disarmed can change the newest log during verification; that transfer must fail.
  ArduPilot can also keep logging after disarm or prearm failures. Older closed
  logs remain recoverable with `--log-id N`; changes to another log do not
  invalidate an otherwise verified selected-log transfer.
- A missing live receiver can cause ArduPilot's logging/prearm check to fail
  when the MAVLink backend is enabled. Do not disable prearm checks to hide it:
  restore the receiver or explicitly return to block-only logging on the bench.
- Only one live DataFlash receiver and one onboard log-download client may use
  this FC at a time. Disable competing native router/GCS remote logging and
  do not run a GCS log download concurrently with the archive worker.

Stop/disable the old PX4 recorder when changing firmware families. Confirm the
core router loads `/etc/mavlink-router/config.d`, and ports/IDs above are unused.
The additive `91-orqa-ardupilot-logging.conf` supplies the two new endpoints.
Activation requires one planned telemetry interruption, **never in flight**:

```sh
sudo systemctl daemon-reload
sudo systemctl restart mavlink-router.service
sudo /opt/orqa-ardupilot-logger/venv/bin/python /usr/local/lib/orqa-ardupilot/recorder.py --check
sudo systemctl enable --now orqa-ardupilot-archive.service
# Only after enabling LOG_BACKEND_TYPE=6:
sudo systemctl enable --now orqa-ardupilot-recorder.service
journalctl -u orqa-ardupilot-recorder -u orqa-ardupilot-archive -f
```

`--check` checks SD storage only. It is not a link or sensor test. For custom FC
IDs, ports or reserve sizes, use systemd ExecStart overrides and update the
router endpoint consistently. To archive just one log manually, stop the archive
worker, then run `archive.py --log-id N`; no live recorder stop is required.
Full archives are intentionally read twice and can take minutes. Each archive
cycle keeps its own copy; capacity is finite and nothing is automatically erased.

## Acceptance and recovery

Run `python -m unittest discover -s tests -v` from the repository after installing
these requirements. Tests include actual pymavlink wire encoding/DataFlash
decoding and fault injection; they are **host tests**, not device evidence.

On the actual APB, props off: test each IMU axis, log start/disarm/re-arm, extract
and parse a full archive, verify receipt SHA256, and compare with a GCS download.
Then exercise no-card boot, low space, read-only media, disconnect/reconnect,
duplicate packets, recorder restart, concurrent telemetry and controlled power
loss with sacrificial media. Record FC logger drops, telemetry latency and SD
errors. Do not intentionally pull a mounted card holding valuable logs.

An error retains partial files and stops the affected worker; systemd retries.
It does not restart the core router or fix a corrupt filesystem. Investigate
missing heartbeats, wrong backend/IDs, another receiver, actual SD mount and
media errors in that order. Never force a rootfs fallback. Never equate an ACK
with a guarantee against all SD-controller power-loss behavior.

Rollback: disable/stop the two `orqa-ardupilot-*` units, move only
`91-orqa-ardupilot-logging.conf` out of the router's loaded config directory,
then restart the router once on the bench. Return `LOG_BACKEND_TYPE` to its saved
value as appropriate. Keep captured logs. The common SD repair can remain;
to undo it, restore only the verified `.pre-orqa-logging` helper backup while
disarmed. Do not remove a shared mount helper still used by another package.

Protocol evidence: [ArduPilot log transfer](https://ardupilot.org/dev/docs/mavlink-log-download.html),
[pinned streaming backend](https://github.com/ArduPilot/ardupilot/blob/fb773567896014da007bca58358704d4a0d8516f/libraries/AP_Logger/AP_Logger_MAVLink.cpp),
[pinned download backend](https://github.com/ArduPilot/ardupilot/blob/fb773567896014da007bca58358704d4a0d8516f/libraries/AP_Logger/AP_Logger_MAVLinkLogTransfer.cpp).
