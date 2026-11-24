# Maintenance and releases

The scheduled workflow checks upstream stable releases every Monday at 06:23 UTC.
It proposes only newer numeric releases; it does not track development branches,
merge PRs, approve reviews, update toolchains silently, publish releases or flash
hardware. ArduPilot proposals require matching Copter/Plane versions and commits.
A patch conflict or compiler incompatibility blocks the build for human review.

The updater needs repository workflow permission to create pull requests.
Opening or updating a PR with GITHUB_TOKEN creates a PR workflow run that
requires approval from someone with write access. The updater also dispatches
the build workflow on the candidate branch. A maintainer can select **Approve
workflows to run** on the PR and verify **All firmware checks** on the final revision.
Closed proposals are not automatically reopened. Enable Actions failure
notifications; schedules may be delayed or disabled by GitHub for inactive repos.

## Review an update

1. Read upstream release notes and compare the old/new commits in the lock.
2. Review patch applicability and all changes to sensor, serial, storage,
   timer/DMA, bootloader and parameter behavior.
3. Require the complete **All firmware checks** status on the current PR commit.
4. Review every target manifest and any change in flash usage.
   Artifact checks require at least 16 KiB of physical flash headroom; linker
   scripts separately enforce reserved parameter/config regions.
5. Re-run the relevant physical bench checks; do not inherit qualification
   merely because the previous release passed.
6. Merge only after human review. The main push produces a fresh build.

### Copter 4.7.3 software checks

Copter 4.7.3 changes the fresh-storage default for `LOIT_OPTIONS` from 1 to 0.
Bit 0 enables coordinated Loiter turns. Read the parameter on fresh simulator
storage for each revision, then boot the candidate using a copy of simulator
storage containing an explicitly saved value. Record the values after reboot.

The [upstream 4.7.3 Copter run](https://github.com/ArduPilot/ardupilot/actions/runs/43534434222/job/132263345138)
recorded 290.22 ANG messages/s in `ATTITUDE_FAST`. The
[4.7.2 run](https://github.com/ArduPilot/ardupilot/actions/runs/38317705922/job/115074666260)
recorded 400.05/s. Compare both pins on one idle host, one simulator at a time.
For each checkout, build Copter SITL and run
`Tools/autotest/autotest.py --speedup=100 test.CopterTests1d.ATTITUDE_FAST`.
Keep the DataFlash BIN named by “Rate sample log” in the test output. Compare
ANG records per simulated second, logger rejected writes (`DSF.Dp`), and main
loop rate (`PM.LR`). Repeat both at the same lower speedup if either misses the
upstream 395–405/s range. Record the runner conditions with the results.

#### Paired results, 23 November 2026

Both pins were built for native Copter SITL on one Debian 13 x86-64 host with
GCC 14.2 and Python 3.12.14. The unmodified upstream test ran twice per pin at
each speed, reversing the order for the second trial. The last logged
`DSF.Dp` is the cumulative count of rejected backend writes across message types.

| Pin | Speedup | ANG records/s, trials 1 and 2 | Last DSF.Dp, trials 1 and 2 |
| --- | --- | --- | --- |
| 4.7.2 `fb773567` | 100× | 314.80, 247.29 | 6,930, 11,711 |
| 4.7.3 `d9c5097c` | 100× | 328.91, 251.24 | 6,190, 9,697 |
| 4.7.2 `fb773567` | 10× | 400.01, 400.01 | 0, 0 |
| 4.7.3 `d9c5097c` | 10× | 400.06, 400.05 | 0, 0 |

All recorded `PM.LR` samples were 399–400 Hz. High-speed simulation reproduced
the logging loss on both pins. Both passed at 10× using the upstream tolerance.
These runs exercised the host file backend. APB W25 logging remains a separate
hardware check.

With fresh simulator storage, `LOIT_OPTIONS` read 1 on 4.7.2 and 0 on 4.7.3.
On 4.7.2 the test explicitly saved 0 and then 1. Booting 4.7.3 with a copy of
that simulated EEPROM returned 1.

## Publish

In Actions, manually run **Publish approved prerelease** from main, supplying
the successful main-push build run ID for the current main commit and a new
tag such as v0.1.0-rc1. It rejects failed, partial, dirty or mismatched builds,
verifies artifact checksums and publishes only a hardware-unvalidated prerelease.
It does not overwrite existing releases. No automatic stable release exists.

Artifacts expire after 30 days; a published release provides persistent download
links and SHA256SUMS. Download the matching manifest and keep it with the firmware.
Releases also include `companion-apb.tar.gz`, exported from the same checked
commit, with installation/rollback instructions. Its checksum is in SHA256SUMS.
CI runs companion protocol/storage tests alongside firmware checks. Changes to
the companion's wire protocol or runtime dependencies require host fault tests
and a fresh physical bench check; neither inherits qualification from firmware CI.
Source reproduction requires the exact upstream commit/submodule pins in the
lock plus this repository at the manifest's port revision. Port source and GPL
license are included in tagged releases. Build tools are checksum-verified;
host OS packages are not a bit-for-bit container snapshot, so do not infer
byte-identical outputs across arbitrary host environments.

## Scope and licensing

This is a focused downstream overlay/build repository, not a GitHub network
fork of the entire upstream tree. It retains upstream code attribution and
GPL-3.0-or-later licensing. Changes were AI-assisted and require human review.
We prefer small fixes that can be offered upstream after validation. No upstream
PR is opened automatically, and no Orqa endorsement or flight certification is
claimed.
