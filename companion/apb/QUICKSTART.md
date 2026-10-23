# APB logging — quick start

Use the companion package for the firmware you actually flashed: PX4,
ArduPilot or Betaflight. Each bundle identifies its own profile; no guessing or
automatic firmware switching. The same commands work in all three packages.
The i.MX writes the SD card.

**These commands run on the APB Linux companion, not your PC or flight controller.**
Keep the extracted package for later setup/rollback. Python 3.10+ and systemd
are required. For MAVLink profiles, the existing router must already own UART4
and load `/etc/mavlink-router/config.d`; PX4 requires the tested v4 router.
This helper does not install/replace the core router or a Linux image.

## 1. Prepare once

- Back up settings. Props off, FC disarmed, correct firmware/sensor variant.
- Insert a working SD card. Do not format or erase anything for this setup.
- Confirm the FC settings below. Existing saved settings override defaults.
- Stop/disable a previous firmware family's logger explicitly before switching.
  Betaflight also needs the MAVLink router stopped/disabled on the bench so MSP
  can own the UART. The tool refuses conflicts; it never stops another family.

| Firmware | Required settings | What gets stored |
|---|---|---|
| PX4 | Matching APB logging firmware, MAVLink2 UART4 at 230400, SDLOG_MODE not -1 | Compact live ULog, not full-rate tuning data |
| ArduPilot | SERIAL4_PROTOCOL=2, SERIAL4_BAUD=230, LOG_BACKEND_TYPE=4; LOG_DISARMED=0 recommended | Verified onboard-log recovery after disarm |
| Betaflight | UART4 MSP at 115200, blackbox_device=FLASH | Blackbox offload after disarm, not live streaming |

For full details and firmware/parameter rollback, see [README.md](README.md).
Confirm the existing MAVLink router uses the same UART baud for PX4/ArduPilot.
Do not remove a live-logging backend until its FC parameters are restored on
the bench; an absent ArduPilot live receiver can affect the logging/prearm check.

## 2. Install and start

Verify the downloaded package checksum, extract it, and open the directory
containing `easy.py`. **Older releases without easy.py do not have this helper**;
use a new CI companion bundle or this repository's current `companion/apb`
directory in full. Do not mix individual files from different revisions.

~~~sh
sudo python3 easy.py setup --activate --bench
~~~

`--bench` means you have verified disarmed/props-off state and the FC settings.
It is an explicit acknowledgment, not automatic detection of a safe aircraft.
For PX4/ArduPilot, activation restarts the existing router once, interrupting
telemetry. Never run setup/start/stop/rollback in flight.

Setup installs pinned Python dependencies into the package's dedicated venv
(ArduPilot/Betaflight), preflights destination files, and repairs only the
recognized vendor SD helper with a backup. Existing/custom mount helpers are
preserved. It never formats SD, deletes logs, changes FC parameters, flashes
firmware, or automatically chooses a different logger.

To install without starting: `sudo python3 easy.py setup --bench`.
Then start with `sudo python3 easy.py start --bench`.
ArduPilot live logging is optional: after explicitly setting
`LOG_BACKEND_TYPE=6` and rebooting on the bench, add `--live` to setup with
activation or to start. This retains the archive worker. Live streams have no
complete-log guarantee; keep onboard recording enabled.

Networkless installation: add `--wheels /path/to/wheelhouse` to setup. Supply
the pinned dependencies and their dependencies as wheels for the companion's
Python version/ARM64 architecture. Python venv/pip support must already exist.
The tool does not change OS package repositories.

## 3. Check it

~~~sh
sudo python3 easy.py status
sudo python3 easy.py logs
~~~

Status reports runtime dependencies, UART presence, actual SD mount/free space,
conflicting services, and recorder service state. Add `--live` when checking
the optional ArduPilot live recorder, or `--json` for machine-readable output.
Any failed required check returns a nonzero exit code with an explanation.
`logs --follow` follows the recorder journals.

An active service is **not proof of a received/complete log**. Read the journal,
confirm files appear in `/sdcard/px4`, `/sdcard/ardupilot`, or
`/sdcard/betaflight`, and open them with the correct log parser. For ArduPilot
and Betaflight, a finalized capture needs its JSON receipt and matching SHA256;
preserve `.partial` files. Archive offloads can take minutes.

## Stop or undo activation

~~~sh
sudo python3 easy.py stop --bench
# Also remove this profile's router endpoint from service, retaining a backup:
sudo python3 easy.py rollback --bench
~~~

Stop disables only this profile's recorder units. Rollback additionally moves
its unchanged router endpoint to `/var/lib/orqa-logging/rollback` and restarts
the core router if it was active. Customized endpoints are refused.
Both preserve logs, dependencies, runtime files and the shared SD repair.
This is companion deactivation, not firmware/FC-parameter rollback.
To reactivate after rollback, run setup again.

If any command fails, inspect its error and run status/logs. A partly completed
setup can be rerun after fixing the issue; unrecognized files are never
overwritten. Do not delete backups or force changes to bypass a guard.

For image builders/tests only: `python3 easy.py setup --root /path/to/staging`
stages files without dependencies, network calls or host service operations.
It cannot be combined with activation/live/dependency options.

Physical SD persistence, UART load and power-loss behavior still require the
APB bench checks. This convenience layer does not confer hardware qualification.
