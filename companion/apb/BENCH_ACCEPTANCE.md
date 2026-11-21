# APB logging: disarmed bench acceptance

This is a logging-only acceptance procedure for a particular board, Linux image,
firmware, configuration and SD card. It does not authorize arming, motor tests,
flight, or firmware-family changes. Start every row as **NOT TESTED**. Record
PASS/FAIL/BLOCKED with evidence; host simulations are a separate result column.
The timing limits below are proposed acceptance limits, not measured performance.

## Record and preserve before changing anything

Record board revision and IMU markings, FC firmware/port/upstream revisions,
application and companion SHA256, bootloader identity/layout, Linux image/kernel,
Python/glibc/router versions, card model/capacity/filesystem, power supply and
test operator/time. Save FC parameters, Linux service definitions/drop-ins,
enabled states, router configuration, mount-helper hashes, and existing logs.
Keep the extracted **matching** companion package and a known-good recovery image.
Do not install a bootloader to enable companion logging.

Remove propellers and isolate actuator power where possible. Independently
confirm FC disarmed state throughout. `--bench` is an operator acknowledgment,
not a sensor or interlock. No test below requires arming. Use an existing closed
onboard log for ArduPilot/Betaflight. If there is none, mark their integrity test
BLOCKED; an empty-flash result is not a successful offload. Do not arm merely to
create a test log. Armed-state fault cases remain host simulations in this plan.

## Profile and dependency checks

| Profile | UART4 / i.MX `/dev/ttymxc2` | Services and receiver |
|---|---|---|
| PX4 | MAVLink 2, 230400 | Core `mavlink-router.service` owns UART; `orqa-px4-recorder.service` runs a second, UDP-only router on loopback 14560; FC ID 1, native logger ID 2 reserved |
| ArduPilot archive | `SERIAL4_PROTOCOL=2`, `SERIAL4_BAUD=230`, `LOG_BACKEND_TYPE=4` | Core router owns UART; archive unit on loopback 14562, source 246/191; FC ID 1/component 1 |
| ArduPilot optional live | Same UART; `LOG_BACKEND_TYPE=6`, explicitly configured and rebooted on bench | Archive remains enabled; recorder on loopback 14561, source 245/191, FC log component 155 |
| Betaflight | MSP, 115200; `blackbox_device=FLASH` | `orqa-betaflight-archive.service` owns UART; MAVLink router and other families' loggers stopped **and disabled** |

Check actual saved FC settings; flashing does not reset them. UART4 is the FC
name, not a reason to guess a Linux device. PX4 maps this link to TEL1. MSP and
MAVLink are incompatible on this port; the previous MAVLink path will not keep
working with Betaflight MSP. Plan any independent telemetry path separately.

All profiles require Python 3.10+, systemd (`systemctl`, `journalctl`), a working
SD mount, and the required system utilities. The optional mount repair uses
`findmnt`, `systemd-mount` and `systemd-umount`; storage guards also use Linux
mountinfo/sysfs. Inspect with `findmnt -M /sdcard`, `lsblk`, and `fuser` or `lsof`.
Do not install OS packages using commands for a different Linux distribution.

- PX4 requires `/usr/bin/mavlink-routerd` from tested v4 commit
  `42529d55b665e0a9a29e424e186f514c56c2e5b5`. The helper's v4 version-string check
  does not prove that exact commit. No third-party Python runtime dependency.
- ArduPilot requires pymavlink 2.4.49, pyserial 3.5, lxml 5.3.0 and fastcrc 0.5.0.
- Betaflight requires pyserial 3.5.
- ArduPilot/Betaflight also require venv/pip support, libc `renameat2`, and SD
  filesystem support for fsync and non-replacing atomic rename. An import test
  alone does not establish filesystem support; finalized receipts exercise it.
- Offline wheels must match the actual Python ABI, ARM64 architecture and glibc.
  Dependency versions are pinned; no wheelhouse or router binary is bundled.
- The core MAVLink router must actually load `/etc/mavlink-router/config.d`.
  `easy.py status` checks file presence and known service states, not its effective
  command line, baud, all UART owners, UDP availability, or received FC identity.

## Required physical evidence

| ID | Procedure | Pass criterion |
|---|---|---|
| B1: provenance | Verify selected application, its manifest and companion against the same release's SHA256SUMS; compare manifest port commit to tag. Confirm physical sensor variant and application offset before any separately authorized flashing. | Every selected file exists and hashes match; no mixed tags/stacks/variants. APB PX4/ArduPilot application origin is 0x08060000; Betaflight starts at 0x08000000 and can replace their bootloader. |
| B2: ownership | Before activation inspect `systemctl cat`, enabled/active states, `fuser /dev/ttymxc2`, and `ss -lunp`. Repeat after activation and reboot. Include serial-getty, manually launched programs and vendor services. | Exactly the intended UART owner; no conflicting getty/manual process, logger, occupied UDP port or receiver ID. PX4's recorder child has no UART descriptor. No concurrent GCS log download/native stream. Do not start a competing process merely to test refusal. |
| B3: installation | Run `setup --bench`, then repeat it from the same package; compare configuration/FC backups. Start explicitly with `start --bench` (ArduPilot live only with explicit `--live`). Capture status JSON and journals. | Both installs succeed with identical managed content; only documented files/dependencies/mount repair change. No FC parameter or firmware changes. One planned core-router restart per MAVLink start; no unexpected service changes. Review mismatched existing files instead of deleting them. |
| B4: SD identity | Inspect the exact `/sdcard` mount and sysfs media type. Record free space and create captures through the actual logger. | Writable physical SD, not eMMC/rootfs/bind substitute/symlink. At least 256 MiB reserve **plus the full anticipated capture size**. Final data and metadata reside on this SD. |
| B5: log integrity | PX4: record 10 minutes disarmed, stop cleanly, parse ULog on host. ArduPilot/BF: recover an existing closed log/snapshot; stop archive worker before taking an independent GCS/Configurator download. | PX4: readable ULog metadata, expected identity/topics and timestamp continuity, no unexplained parser corruption or new streaming dropouts. ArduPilot/BF: final JSON receipt, exact byte count and SHA256, stable source identity/inventory, parser success and byte comparison with the independent download. Preserve any tool-normalized/padded raw files and explain differences; unresolved differences fail. |
| B6: contention | Observe 10 minutes with normal companion workload and logging disabled, then 10 minutes with logging active. Collect timestamped telemetry/heartbeat and transport-error counters without adding a second UART owner. BF uses a separately provisioned telemetry path or timestamped requests from the sole MSP owner. | No FC reset, router restart, unexpected disconnect, or new UART/protocol errors. For an existing 1 Hz heartbeat, no gap over 3 s. Where RTT is measurable, p95 increase at most 25 ms and p99 at most 100 ms over baseline. Missing measurements are BLOCKED, not PASS; retain raw data and metric definitions. |
| B7: orderly persistence | Finalize and hash data/receipts, shut down normally, then power-cycle and recheck. Repeat three times. | Previously finalized files/receipts survive byte-for-byte; mount and intended ownership return each boot. No formatting, stale mount marker, rootfs capture or re-enabled conflicting service. FC settings remain as recorded. |
| B8: media faults | On backed-up/sacrificial media test no-card boot, read-only mount, free space below reserve, and controlled mount/media disappearance. Restore a healthy mount after each case. | Logging pauses/fails with an attributable journal error, retains previous logs and partials, and never formats/deletes/falls back to rootfs. Core telemetry stays available. Recovery creates a new verifiable capture; it never relabels a partial as complete. |
| B9: interruption | Interrupt only the logging worker mid-capture, then restart. Separately test companion power interruption using sacrificial media; leave FC disarmed. Do not corrupt or remove valuable mounted media. | Previously finalized, synced captures still match saved hashes. Interrupted data remain inspectable; ArduPilot/BF never expose a complete receipt for incomplete bytes. PX4 `.ulg` has no completeness receipt: quarantine the interrupted session until parsed. Fresh recording/offload resumes after recovery, without duplicate owners or automatic erase. |
| B10: recovery deadline | After service restart or healthy media return, allow 90 s for service/handshake and initial new log/transfer progress; give a full two-pass archive its measured baseline duration plus 50%. | Progress within those bounds; complete integrity verification afterward. PX4 retries in 5 s, ArduPilot live in 10 s, archive services in 30 s; archive watch waits 30 s disarmed (ArduPilot) or 10 s (BF). Large transfers may take minutes. A stuck transfer is not PASS because systemd says active. |
| B11: stop/rollback | On bench use stop, then rollback from the retained matching package. Verify units inactive/disabled, route removed/backed up where applicable, saved log hashes unchanged, and no file growth over two snapshots 10 s apart. Reboot and inspect ownership again. | Only this family's units disabled. MAVLink endpoint backed up under `/var/lib/orqa-logging/rollback`; core router restarted once only if active. BF rollback does not re-enable MAVLink. Logs, runtime, venv and shared mount repair remain. Repeated rollback is harmless; setup plus start restores the selected profile. |

Optional ArduPilot live acceptance is separate: a clean `.stream.bin` receipt
must say `complete: false`; validate parsing and record stream/producer drops,
then recover a closed onboard archive for completeness. Do not mark live-only
capture equivalent to archived DataFlash. Returning to archive-only requires
restoring `LOG_BACKEND_TYPE=4` and rebooting on the bench, then stopping both
units and starting without `--live`. Omitting `--live` alone does not disable
an already enabled live unit. Keep safety/prearm checks intact.

`stop` retains the router endpoint. `rollback` is deactivation, not an uninstall
or restoration of FC parameters/firmware. It refuses a customized endpoint.
If endpoint backup fails (including separate `/etc` and `/var` filesystems),
record the error and actual stopped/remaining state; do not assume rollback
completed. Restore the saved configuration deliberately before a new activation.
The shared mount repair should remain unless all consumers are deactivated and
the original verified backup is deliberately restored. Keep existing mount
repairs when switching families; do not overwrite them with another installer.

## Evidence record and acceptance decision

For each ID record: status, exact command/configuration, start/end time, journal
and kernel log, mount/device identity, UART process/descriptor inventory, log and
receipt filenames/hashes, parser output, and any anomaly/recovery action.
Use `PASS / FAIL / BLOCKED / NOT TESTED / NOT APPLICABLE`; explain every N/A.
Retain pre/post configuration and service enabled-state snapshots. Record any
proposed timing-limit adjustment **before** a run and justify it separately.

All applicable rows must pass on the same recorded combination to call that
combination **disarmed logging bench accepted**. Optional live is a separate
qualification. Any failed persistence/integrity/ownership row blocks acceptance.
No APB hardware results are supplied with this checklist. Armed transitions,
motor outputs and flight remain outside its scope.

For software-only work, `easy.py setup --root /path/to/staging` and the host
tests exercise installation/fault cases without hardware, dependency installation
or service activation. Keep simulated identity/mounts confined to that environment;
they are not a substitute for the physical result column above.
