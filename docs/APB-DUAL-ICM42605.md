# MRM2-10 dual-ICM42605 Copter candidate

## What is known

The MRM2-10 FC reported `INS_GYR_ID=INS_ACC_ID=3473674` and
`INS_GYR2_ID=INS_ACC2_ID=3473698` on 2026-11-20. The ArduPilot device type
in both IDs is `0x35`, ICM42605. The installed 4.8.0-dev image identifies as
`0922bced`; its owner reports many flights. That is evidence for the installed
image on that aircraft, not for this repository's 4.7.2 build.

The retained 2026-10-26 `installed-hwdef.dat` associated with that image uses
`ROTATION_YAW_180` for SPI1 and `ROTATION_YAW_90` for SPI4. Its SHA256 is
`548e31466e2209b9476959f93e9e0102090115104a348c517add0754389f9fbc`.
The complete original build inputs were not recovered, so this file is a
candidate source reference; it does not prove the exact read-back binary was
built from that file.

The previously compared 4.7.2 and the 4.8.0-dev sources read the ICM42605 FIFO axes into
`Vector3f` in the same order, then call the same backend orientation methods.
Their `Vector3::rotate()` cases for these yaw rotations are unchanged:

| Rotation | Source vector to board vector before calibration |
|---|---|
| `ROTATION_YAW_180` | `(x,y,z) -> (-x,-y,z)` |
| `ROTATION_YAW_90` | `(x,y,z) -> (-y,x,z)` |
| Previous generic `ROTATION_PITCH_180` | `(x,y,z) -> (-x,y,-z)` |

This compares software operations. Physical chip mounting and each sensor's
actual body axes still require a props-off check. The Nov. 4 Betaflight
reference unit reports the same chip population, but its alignment enums and
motor mapping are not ArduPilot evidence.

## Build selection

`apb-dual-icm42605-copter` is an experimental Copter build at the revision in
[upstream.lock.json](../upstream.lock.json). The board
overlay changes only the two IMU probe rotations; it inherits the generic APB
pins, board ID 1189, and 384 KiB application offset. The old `apb-copter`
target remains the mixed MPU6000/ICM42605 population; `apb-icm42688-copter`
remains the dual ICM42688 population. APB build and collect commands require
the explicitly observed population:

```sh
python scripts/build.py build work/ardupilot --target apb-dual-icm42605-copter \
  --sensor-population apb-dual-icm42605
python scripts/build.py collect work/ardupilot --target apb-dual-icm42605-copter \
  --sensor-population apb-dual-icm42605 --output artifacts/apb-dual-icm42605
```

The candidate is in CI so its APJ, ELF and BIN can be checked at the pinned
source and toolchain. It is included in tagged prereleases under the same
hardware-unvalidated policy as other targets. CI does not establish axis,
output or flight behavior.
Do not use the existing v0.1.0-rc2 `apb-copter.apj` on this population.

## Outstanding hardware checks for the candidate

1. Preserve the current 4.8 APJ, full parameter/calibration backup, logs and
   a working recovery path. Check the actual unit's bootloader ID and upload
   behavior; shared board ID 1189 alone is insufficient.
2. With props removed and the unit disarmed, confirm each IMU separately in
   ArduPilot by rolling, pitching and yawing the airframe. Both sensors must
   agree with physical body axes. Confirm their stationary readings agree.
3. With props removed, verify the motor output-to-corner mapping and motor
   direction on this aircraft, then verify RC, mode, failsafe, compass/GPS,
   logging, battery and prearm behavior. Review parameter migration from the fielded 4.8 image to the selected
   candidate using copies of the saved settings.
4. Only after those checks, conduct a controlled manual hover and inspect its
   log for attitude, IMU clipping/vibration, motor saturation and failsafes.

The recent MRM2-10 log review found increased accelerometer clipping. That
issue also needs attention before accepting a different build or copying its
tune. No parameter, bootloader or firmware change is made by this repository
update. ArduPilot's [firmware loading guidance](https://ardupilot.org/copter/docs/common-loading-firmware.html)
also calls for a parameter backup and review across firmware versions.
