# Dual-ICM42605 APB coverage and qualification gate

The Nov. 4 reference unit reports ICM42605 on SPI1 and SPI4. Betaflight evidence
records chip-to-board alignments CW0FLIP and CW270FLIP. The current ArduPilot
base hwdef declares both probes with ROTATION_PITCH_180. Its ICM42688 variant
has a different SPI4 rotation. Neither configuration is established as correct
for the reference population by this evidence.

The underlying drivers can transform raw chip axes differently. Derive the
ArduPilot body-frame matrices from the pinned Invensensev3 driver and rotation
implementation before assigning enums. Then verify each IMU independently
with props removed. Do not copy Betaflight enum names/numbers, motor order,
tuning coefficients, or flight evidence into ArduPilot.

The machine-readable population record deliberately has no build target or
candidate rotation. It is a coverage record, not an unverified firmware image.
The optional explicit population guard rejects the generic APB target:

```
python scripts/build.py build work/apb --target apb-copter \
  --sensor-population apb-dual-icm42605
```

For a reviewed existing population, choose its matching target, for example
`--sensor-population apb-mpu6000-icm42605 --target apb-copter`. A successful
selection means a build exists; hardware_qualified remains false. Omitting
the option retains existing builder behavior and cannot identify attached chips.

To add the new target, preserve the existing variants and close these gates:

1. Derive both chip-to-body matrices using the pinned ArduPilot source and
   reference physical mounting; record the equations/source revision.
2. In a separate experimental board, build cleanly and perform individual
   roll/pitch/yaw sensor sweeps plus combined stationary consistency checks.
3. Verify the actual unit's bootloader/recovery path and flash offset before
   changing firmware families. Repository APJ board ID 1189 and 384 KiB offset
   do not prove a compatible bootloader is installed. The current Betaflight
   build starts at 0x08000000; do not write an APJ there as if formats matched.
4. Verify ArduPilot motor outputs/corners/directions with props removed and
   preserve the unit's parameter/calibration backups. Betaflight corner order
   is evidence for that setup only, not an ArduPilot mixer prescription.
5. Record the independent manual hover/log result before flight acceptance.

When the source/bench build-selection gates are complete, update the record,
add the explicit target to the lock/CI/docs, and attach the matching evidence.
Flight readiness remains a separate gate. No firmware, bootloader, existing
rotation, output map, or ArduPilot parameter is changed by this update.
