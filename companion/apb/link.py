"""Dedicated loopback MAVLink endpoint; the existing router owns the UART."""
import time


class Armed(RuntimeError):
    pass


class Link:
    def __init__(self, port=14561, system=1, source=245):
        from pymavlink import mavutil
        if not 1024 <= port <= 65535 or not 1 <= system <= 255 or not 1 <= source <= 255 or source == system:
            raise ValueError("invalid MAVLink identity/port")
        self.system, self.source, self.component = system, source, 191
        self.conn = mavutil.mavlink_connection(f"udpin:127.0.0.1:{port}", source_system=source,
                                              source_component=self.component, dialect="ardupilotmega")
        self.last_heartbeat = 0
        self.last_sent = 0
        self.armed = None
        self.autopilot = None

    def recv(self, timeout=0.2):
        now = time.monotonic()
        if now - self.last_sent >= 1:
            # Onboard-controller heartbeat, NOT a GCS heartbeat/failsafe substitute.
            self.conn.mav.heartbeat_send(18, 8, 0, 0, 4)
            self.last_sent = now
        message = self.conn.recv_match(blocking=True, timeout=timeout)
        if message is None or message.get_srcSystem() != self.system:
            return None
        if message.get_type() == "HEARTBEAT" and message.get_srcComponent() == 1:
            self.last_heartbeat = time.monotonic()
            self.armed = bool(message.base_mode & 128)
            self.autopilot = message.autopilot
        return message

    def ready(self, disarmed=False):
        if self.autopilot != 3 or time.monotonic() - self.last_heartbeat > 3:
            raise RuntimeError("fresh ArduPilot autopilot heartbeat required")
        if disarmed and self.armed is not False:
            raise Armed("log archive requires disarmed flight controller")

    def wait_heartbeat(self, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.recv()
            if self.autopilot == 3 and time.monotonic() - self.last_heartbeat < 3:
                return
        raise TimeoutError("no ArduPilot heartbeat on dedicated router endpoint")

    def status(self, sequence, ack=True):
        self.conn.mav.remote_log_block_status_send(self.system, 1, sequence, int(ack))

    def close(self):
        self.conn.close()
