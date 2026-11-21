# APB logging release audit — 2026-10-24

**Result: the three published releases contain matching firmware and companion
packages. No missing listed asset, checksum mismatch, source-revision mismatch,
or companion-file mismatch was found. Physical APB validation is NOT TESTED.**

| Stack | Release | Port commit | Published assets | SHA256SUMS entries | Host tests rerun |
|---|---|---|---:|---:|---:|
| PX4 | [v0.1.0-rc3](https://github.com/DroneWuKong/Orqa_H7_PX4_Ports/releases/tag/v0.1.0-rc3) | `84d228c63dc80945ee36ab3f872286dbc3c43571` | 23 | 22 | 80 pass |
| ArduPilot | [v0.1.0-rc2](https://github.com/DroneWuKong/Orqa_ArduPilot_Ports/releases/tag/v0.1.0-rc2) | `ee71ab28c3a90791a442ffdb0397f9d78245fb9b` | 35 | 34 | 122 pass |
| Betaflight | [v0.1.0-rc3](https://github.com/DroneWuKong/Orqa_Betaflight_Ports/releases/tag/v0.1.0-rc3) | `ca30cf5cba1fc0ab74cc147ea2fd26707277fd74` | 23 | 22 | 104 pass |

SHA256SUMS does not list itself: its bytes were checked against GitHub's asset
digest. All 81 asset sizes/digests matched GitHub metadata; all 78 listed file
hashes matched the downloaded SHA256SUMS. These checks establish byte consistency,
not a cryptographic signature or a fresh reproducible firmware build.

## Checks performed

- Retrieved current default branches, merge status, release inventories and
  referenced successful build-run metadata. The cited merge commit, release tag,
  manifest port revision and successful workflow head agree in each repository.
  No later open PR or issue was returned by the repository searches at audit time.
- Downloaded **all** assets, not only the companion archives. Validated the exact
  expected filename set, manifest artifact hashes, clean-worktree flags and
  `hardware_validated: false` in all 20 firmware manifests.
- Compared 962 recorded source-input hash entries to tagged source. The three
  generated PX4 `extras/*_bootloader.bin` entries match the released bootloader
  bytes; these generated files are not missing repository inputs (see prior PR #7).
- Compared every companion file byte-for-byte with its tagged `companion/apb`
  tree: PX4 10 files, ArduPilot 16, Betaflight 12. All include easy.py, profile,
  quick start, installer, required runtime files, units and endpoint/configuration
  where applicable. ArduPilot/BF include pinned requirements and COPYING.
- Compared the complete ArduPilot/BF `port-source.tar.gz` contents to the tags
  (39/33 files). PX4 has no separately named port-source asset; its exact Git tag
  is the source reference. A standalone source tarball is not an installation
  dependency for its complete companion bundle.
- Decoded all seven PX4 packages and eight ArduPilot APJs: exact BIN payload,
  image size, expected board ID and upstream revision agree. ArduPilot ELF load
  bounds/vectors were checked with repository validators; allocated ELF sections
  reconstructed with erased-flash fill matched the BINs. All five Betaflight
  HEX payloads decoded exactly to BIN, contained the expected board identifier,
  and passed repository vector/ELF-bound checks. PX4 ELF files are not published,
  so their layout was not independently rerun from release bytes; it is covered
  by the referenced successful CI and manifests, not a new local ELF check.
- Extracted all three real companion downloads and ran clean and repeat
  `easy.py setup --root <temporary-directory>` installs successfully. No physical
  service activation, FC flashing, parameter write or APB SD write was performed.
- Reran `python -m unittest discover -s tests -v` in each source tree: 306 total
  passing host tests. The common easy.py suite contributes 42 tests **per repo**;
  these are duplicated coverage, not 126 unique physical validations.
- Built native mavlink-router at the required commit and ran the actual PX4
  `tests/probe_apb_router.py`: disabled/normal/split/gap/open-failure/supervisor
  scenarios all passed, including parsing, duplicates, simulated SD interruption
  and telemetry surviving recorder shutdown. SD identity is simulated there.

Successful published runs (metadata verified, firmware not rebuilt in this audit):
[PX4](https://github.com/DroneWuKong/Orqa_H7_PX4_Ports/actions/runs/39988593462),
[ArduPilot](https://github.com/DroneWuKong/Orqa_ArduPilot_Ports/actions/runs/39988602833),
[Betaflight](https://github.com/DroneWuKong/Orqa_Betaflight_Ports/actions/runs/39987420246).

## Pairing and transport

| Stack | Select APB firmware | Companion archive | Protocol and logging |
|---|---|---|---|
| PX4 rc3 | `orqa_apb_default.px4` | `orqa-apb-companion.tar.gz` → `apb/` | UART4 MAVLink 2 / 230400; compact live ULog; pinned router v4 required |
| ArduPilot rc2 | `apb-copter.apj` or `apb-plane.apj`; for dual ICM42688 use `apb-icm42688-copter.apj` or `apb-icm42688-plane.apj` | `companion-apb.tar.gz` → `companion-apb/` | SERIAL4 MAVLink 2 / 230400; verified disarmed archive by default; live opt-in |
| Betaflight rc3 | `apb-mpu6000-icm42605.hex` or `apb-icm42688.hex` | `companion-apb.tar.gz` → `companion-apb/` | UART4 MSP / 115200; verified disarmed Blackbox offload |

Choose the physical board/sensor population and vehicle explicitly. APB PX4 and
ArduPilot use application origin 0x08060000 and factory board ID 1189; the ID alone
is insufficient (ArduPilot documents an upstream ID collision). Betaflight starts
at 0x08000000 and can replace an ArduPilot/PX4 bootloader. A logger installation
never performs these flashing steps. Keep a recovery method when changing stacks.

Upstream pins are PX4 v1.15.4 `99c40407ffd7ac184e2d7b4b293f36f10fe561ef`,
ArduPilot Copter/Plane 4.7.2 `fb773567896014da007bca58358704d4a0d8516f`, and
Betaflight 2026.6.2 `e0b7bb01b17b21351057e9ead2d1ab39dd44fa16`.
The ArduPilot lock names the Copter tag; downloaded Copter and Plane binaries
both report V4.7.2. The differing rc numbers are package release labels, not an
inter-stack mismatch.

The i.MX owns the SD card. PX4/ArduPilot use the existing core router as sole
UART owner; PX4's additional recorder router is UDP-only. Betaflight cannot use
that same MAVLink path: stop and disable the router and other logger families
on the bench before MSP. Also inspect manual UART users/getty processes, UDP
ports, receiver IDs and competing GCS log clients; easy.py cannot discover them all.

## Dependencies and installation limits

Python 3.10+, systemd and working native SD/mount utilities are prerequisites.
The helper does not supply a Linux image, OS venv/pip package or core router.
PX4 needs tested mavlink-router v4 commit `42529d55b665e0a9a29e424e186f514c56c2e5b5`
and no third-party Python runtime package. ArduPilot pins pymavlink 2.4.49,
pyserial 3.5, lxml 5.3.0 and fastcrc 0.5.0. Betaflight pins pyserial 3.5.
ArduPilot/BF require Linux libc renameat2 and SD fsync/non-replacing rename support.

The pinned Python packages installed/imported on the audit's x86_64 Python 3.12
host. An ARM64 CPython 3.12 wheel download resolved all four ArduPilot dependencies
(including Betaflight's pyserial); lxml's selected wheel requires glibc >= 2.28.
**Those ARM64 wheels were not executed on an APB.** Actual OS/Python/glibc,
network/TLS, venv, router version/configuration and filesystem operation remain
bench prerequisites. Offline wheels are not included in the release archives.

Install without activation with `setup --bench`; start later with `start --bench`.
For PX4/ArduPilot, each start restarts the active core router once to load the
endpoint. Setup --activate performs preflight first but is not a fully atomic
transaction: a failed later step can leave dependencies/files installed. Inspect
errors/status and rerun the same package; never delete unknown files to force it.
Staging does not install dependencies or activate systemd and is not an APB install.

## Verified documentation defects and corrections

1. PX4's prominent firmware table still linked to rc2 despite the rc3 logging
   introduction. The introduction called those downloads historical, but the
   table invited installing the old APB application with the new companion.
   Link the complete table and checksum page to rc3; keep the rc2 size table
   explicitly historical.
2. The shared quick start and ArduPilot/BF READMEs recommended moving current/CI
   companion sources for older bundles without specifying the matching firmware
   revision. Replace that with an explicit same-release/source pairing rule.
3. PX4's low-level manual installer always requests vendor mount repair and
   rejects a different existing repair; easy.py preserves it. State the distinct
   paths and direct already-repaired systems to `easy.py setup --bench`.
4. The quick-start rollback wording implied every profile had a router endpoint.
   Scope that to PX4/ArduPilot; BF rollback does not restore/re-enable MAVLink.
   Clarify ArduPilot's live-to-archive sequence: omitting --live does not stop an
   already enabled live unit. Align manual rollback with FC-backend restoration.
5. The existing broad bench pages mix output/arming/flight tests with logging.
   Add a separate disarmed checklist with exact evidence, persistence, integrity,
   ownership, interruption/recovery and rollback criteria. Existing closed logs
   are required for archive validation; an empty inventory cannot pass it.
6. Link PX4's topic definition to tagged source so the link also works from an
   extracted companion bundle, and align its manual Python minimum with easy.py.

These corrections change documentation, not firmware or runtime behavior. The
published release assets and tags are preserved. New documents apply alongside
the old downloads; they are included in companion archives only when a future
release is deliberately packaged. No new firmware release is implied by a docs PR.

## Hardware boundary and acceptance

Use [BENCH_ACCEPTANCE.md](../companion/apb/BENCH_ACCEPTANCE.md). All physical
rows are **NOT TESTED** in this audit: no APB, its actual Linux image, serial link,
SD card or power-control access was used. PASS requires the recorded combination
to meet SD persistence/hash checks, UART ownership, conflict absence, parsed logs,
load/latency limits, recovery and reversible deactivation. Optional live logging
has its own result. Interrupted PX4 ULogs need inspection; they have no receipt.
ArduPilot live receipts must remain `complete: false`. Archive `complete: true`
means a verified transfer, not proof of loss-free producer logging.

Prior fixes were checked before adding work: PX4 PRs #6/#7 (storage and repeated
builds), ArduPilot #1/#2 (ELF validation and archive/live transport), Betaflight
#1/#2/#3 (offload, serial timeout, test dependencies). Their relevant checks remain
passing; this audit does not reopen those as new defects.

## This repository's download verification

The [asset ledger](APB_RELEASE_ASSETS_2026-10-24.json) records the downloaded
filenames, byte counts, digests and comparison results for this release.

Download the selected application, its same-stem `.manifest.json`, the companion
archive and `SHA256SUMS` from this repository's release above. In a clean download
directory, use the following check **before extraction**. Replace the example
application only with the exact board/sensor/vehicle variant from the table; the
companion name stays specific to this repository. This reads files only.

```sh
python3 - apb-copter.apj companion-apb.tar.gz <<'PY'
import hashlib, pathlib, sys
firmware, companion = map(pathlib.Path, sys.argv[1:])
selected = [firmware, firmware.with_suffix('.manifest.json'), companion]
lines = pathlib.Path('SHA256SUMS').read_text().splitlines()
sums = {}
for line in lines:
    digest, name = line.split(None, 1)
    if name in sums:
        raise SystemExit('Duplicate checksum entry: ' + name)
    sums[name] = digest
for path in selected:
    if not path.is_file() or path.name not in sums:
        raise SystemExit('Missing selected file or checksum: ' + str(path))
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != sums[path.name]:
        raise SystemExit('Checksum mismatch: ' + str(path))
    print('OK', path)
PY
```

Stop if the check fails. A successful `sha256sum --ignore-missing` alone could
otherwise overlook a missing selected file. Compare the manifest port revision
with the table above. After all three selected files pass, extract into a fresh
directory (never over an older package):

```sh
mkdir verified-companion
tar -xzf companion-apb.tar.gz -C verified-companion
cd verified-companion/companion-apb
python3 easy.py --help
```

Read QUICKSTART.md and the linked bench checklist before running setup on APB.
The firmware application is flashed separately using its documented board-specific
process; none of the verification commands above flashes or starts anything.
