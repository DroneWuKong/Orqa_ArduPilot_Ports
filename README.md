# Orqa ArduPilot Ports

Audited Orqa board fixes and APB overlays on pinned stable ArduPilot, with
automated builds and review-gated upstream updates.

[![Build and verify](https://github.com/DroneWuKong/Orqa_ArduPilot_Ports/actions/workflows/build.yml/badge.svg)](https://github.com/DroneWuKong/Orqa_ArduPilot_Ports/actions/workflows/build.yml)

**Status: experimental, hardware-unvalidated.** Not an official Orqa release.
This repository does not change flight-control algorithms or certify hardware.

## Targets

| Build ID | Upstream/overlay board | Vehicle | Board ID |
|---|---|---|---:|
| quadcore-copter | OrqaH7QuadCore | Copter | 1204 |
| wingcore-plane | OrqaH7QuadCore | Plane | 1204 |
| f405-copter | OrqaF405Pro | Copter | 1155 |
| f405-plane | OrqaF405Pro | Plane | 1155 |
| apb-copter / apb-plane | OrqaAPB | Copter / Plane | 1189 |
| apb-icm42688-copter / apb-icm42688-plane | OrqaAPB-ICM42688 | Copter / Plane | 1189 |

Wingcore uses the shared H7 hardware target with Plane, not a new board ID.
APB's default population is MPU6000 + ICM42605; the later variant is dual
ICM42688P with its different SPI4 rotation. Select from actual chip markings,
then verify physical axes. H7 upstream sensor assumptions remain unchanged.

## Fixes and improvements

- Consolidate F405's two aliases for one physical SPI1 IMU into one device,
  retaining both MPU6000 and ICM42688P probes and their original rotations.
- Correct F405 battery documentation to voltage ADC 11 / current ADC 13.
- APB uses confirmed factory board ID 1189 and the 384 KiB application offset.
- Restore the missing MPU6000 probe in the supplied APB definition.
- Give APB's i.MX UART4 a 230400-baud default; saved parameters are not reset.
- Default APB logging to the onboard W25 block backend instead of a nonexistent
  STM32 filesystem. The microSD remains Linux-owned.
- Supply an SD-guarded i.MX live DataFlash recorder and verified post-flight
  recovery, with durable ACKs, retransmission handling and install/rollback tools.
- Separate sensor-population variants; preserve the factory APB bootloader
  rather than embedding an unverified replacement.
- Check source/compiler pins, APJ identity, APJ/BIN/ELF agreement, vectors
  and ELF load bounds; publish manifests and checksums.
- Weekly stable-update PRs and manual-only prerelease publication.

Details: [audit/provenance](docs/AUDIT.md), [bench checks](docs/TESTING.md),
[updates/releases](docs/MAINTENANCE.md).

## Easy APB logging setup

See the [APB quick start](companion/apb/QUICKSTART.md): one setup command, then
`status` and `logs`. Use the matching companion package on the i.MX; flashing
the FC alone does not install Linux logging. Select firmware and companion from
the same verified release/source revision. See the [release audit](docs/APB_RELEASE_AUDIT_2026-10-24.md)
and [disarmed logging checklist](companion/apb/BENCH_ACCEPTANCE.md).

## Downloads and flashing

Persistent downloads: [v0.1.0-rc2 prerelease](https://github.com/DroneWuKong/Orqa_ArduPilot_Ports/releases/tag/v0.1.0-rc2).
Choose the matching `.apj`; download `companion-apb.tar.gz` for the APB Linux
logging package and `SHA256SUMS` for verification. These are bench-test builds,
not hardware-qualified releases.

Alternatively download firmware-<build-ID> from a [successful Actions run](https://github.com/DroneWuKong/Orqa_ArduPilot_Ports/actions/workflows/build.yml).
Artifacts require sign-in and expire after 30 days.
[Tagged prereleases](https://github.com/DroneWuKong/Orqa_ArduPilot_Ports/releases)
are published only by manual approval.

Use the matching .apj in Mission Planner or another compatible uploader.
Each artifact also includes .bin, .elf, a manifest and SHA256SUMS. Back up settings,
missions and logs before switching firmware. Never force an ID mismatch.

H7/APB applications start at 0x08060000; F405 starts at 0x0800C000.
A raw .bin is not a complete image to flash at 0x08000000. Existing vendor
bootloaders with other private IDs require investigation, not forced uploads.
No replacement bootloaders or with_bl.hex files are produced here.

**APB ID warning:** Orqa's factory ID 1189 now collides with upstream
CORVON743V1. Our clearly named downstream factory alias preserves compatibility;
it is not a new registered allocation. Verify the physical APB, USB identity
0x35b6:0x0090, sensor population and flash layout as well as the number.
Never load an APB image onto another board just because its ID is 1189.

## Build (Linux x86_64)

Pinned stable base: Copter/Plane 4.7.2 at the same upstream commit.
Exact compiler, source and targets: [upstream.lock.json](upstream.lock.json).

~~~sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-build.txt -r companion/apb/requirements.txt
python scripts/build.py toolchain work/tools
export PATH="$PWD/work/tools/gcc-arm-none-eabi-10-2020-q4-major/bin:$PATH"
python scripts/build.py prepare work/ardupilot
python scripts/build.py build work/ardupilot --target apb-copter
python scripts/build.py collect work/ardupilot --target apb-copter --output artifacts/apb
python -m unittest discover -s tests -v
~~~

Git, make, a host C compiler, tar/bzip2 and Python are required.
Use a fresh source checkout for a new upstream revision. Installation refuses
unrecognized board edits and patch conflicts. No sudo or hardware access is used.
The toolchain installer refuses existing destinations; reuse its bin directory.

## Storage boundaries

ArduPilot DataFlash is not PX4 ULog. APB and F405 can log to onboard W25;
QuadCore/Wingcore retain upstream SD filesystem logging. APB's default block
logging is finite (16 MiB chip) and is not an unlimited SD archive.
Check LOG_BACKEND_TYPE on an existing installation: defaults do not override
saved values. Retrieve logs through the ground station before they are recycled.

The [APB companion package](companion/apb/README.md) implements native DataFlash
streaming and disarmed archival to i.MX SD, without reusing the PX4 ULog protocol.
Onboard logging stays the default; live streaming is explicit opt-in because an
absent receiver can affect the logging/prearm check. Archived logs are read twice
and verified; live streams have no EOF guarantee and are labeled accordingly.
Bandwidth, SD power-loss behavior and physical persistence still require the
documented bench tests. No successful hardware test is claimed by compilation.
