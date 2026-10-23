# Audit and provenance

Initial upstream: ArduPilot/ardupilot Copter-4.7.2 and Plane-4.7.2, both
fb773567896014da007bca58358704d4a0d8516f.

The F405 patch applies to upstream files and is intentionally small:
- Both imu1 and imu2 originally named SPI1/DEVID1/GYRO1_CS. The new definition
  uses imu1 for both alternative chip drivers. This removes redundant aliases;
  it does not claim a reproduced hardware initialization failure.
- README battery pins 13/12 contradicted hwdef pins 11/13. Documentation now
  agrees with the unchanged ADC wiring and voltage/current scale defaults.

APB starts from the supplied stock APB hwdef preserved in the prior
orqa-apb-arducopter-dev-20261014 worktree. Evidence and factory ID analysis:
https://github.com/DroneWuKong/Orqa_H7_PX4_Ports/tree/master/reference/orqa-apb

The stock definition had no STM32 SD mapping but selected filesystem logging,
and commented MPU6000 while only probing Invensensev3. We select onboard block
logging, restore the legacy Invensense probe, explicitly set companion baud,
and split the later ICM42688P rotation into a separately named variant.
AP_BOOTLOADER_FLASHING_ENABLED=0 is intentional: the APB application uses the
existing factory bootloader and this project supplies no replacement binary.

The stock APB motor ordering is retained, including differences from other
firmware families. H7/F405 upstream motor/timer maps and flight algorithms are
not rewritten to mirror PX4; the RTOS/drivers and firmware conventions differ.
Hardware axes, storage retention, UART, DMA and power-loss behavior remain
unqualified. These changes are AI-assisted and should receive human review.
