# Propellers-off acceptance

For a fully disarmed APB **logging-only** run, use the
[APB logging acceptance checklist](../companion/apb/BENCH_ACCEPTANCE.md).
The broader output/arming/flight checks below are separate work.

Software builds are not hardware qualification. Record board revision, IMU
markings, bootloader ID/layout, upstream and port commits, manifest, settings
backup, power source and media model before testing.

- Verify the exact sensor-population variant before flashing.
- Back up parameters/configuration, missions and logs. Keep known-good firmware
  and a tested recovery method. Never force a board-ID mismatch.
- Verify USB enumeration, detected IMUs and positive roll/pitch/yaw response
  on every enabled IMU. Do not arm with contradictory axes.
- Check barometer, battery voltage/current against measurements, RC protocol
  and loss failsafe, GPS, serial assignments and OSD.
- Test each motor/output with props removed: connector order, direction,
  protocol, timer-group compatibility and ESC telemetry.
- Check log creation, retrieval and parsing, then missing/full-media behavior.
  Verify settings survive a full power cycle.
- Run output, sensor, storage and serial workloads concurrently. Record errors,
  dropouts and latency; a successful compile does not test DMA contention.
- APB: follow [companion installation and acceptance](../companion/apb/README.md).
  Verify actual i.MX UART transport, a parsed SD log and its receipt checksum.
  Exercise missing/full/read-only media, reconnect and controlled power loss.
  Host protocol tests do not establish physical persistence.
- Retest after upstream updates, especially bootloader/layout, sensor and
  parameter changes. Only proceed to controlled flight after bench acceptance.

Keep actual logs and pass/fail/not-tested results. Never relabel a host test,
historical build receipt or source inference as physical qualification.
