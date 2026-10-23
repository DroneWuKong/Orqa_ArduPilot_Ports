#!/usr/bin/env python3
"""Receive ArduPilot's live DataFlash blocks; ACK only after durable storage."""
import argparse
import os
from pathlib import Path
import signal
import time

from link import Link
from storage import Store

START, STOP = 2147483646, 2147483645
BLOCK = 200


class Stream:
    def __init__(self, capture, status, max_bytes=1024*1024*1024, window=256):
        self.capture, self.status = capture, status
        self.max_bytes, self.window = max_bytes, window
        self.next = 0
        self.pending = {}
        self.started = False
        self.last_gap = 0

    def accept(self, sequence, data):
        data = bytes(data)
        if len(data) != BLOCK or sequence < 0 or sequence >= START or (sequence+1)*BLOCK > self.max_bytes:
            raise ValueError("invalid or excessive remote-log block")
        if sequence < self.next:
            if os.pread(self.capture.fd, BLOCK, sequence*BLOCK) != data:
                raise ValueError("conflicting block; possible FC restart, preserving prior stream")
            self.status(sequence)  # already durably committed
            return
        if sequence - self.next >= self.window:
            raise ValueError("remote-log reorder window exceeded")
        if sequence in self.pending and self.pending[sequence] != data:
            raise ValueError("conflicting duplicate block")
        if sequence == 0 and not data.startswith(b"\xa3\x95\x80"):
            raise ValueError("stream does not start with a DataFlash FMT record")
        self.pending[sequence] = data
        self.started = True
        if self.next not in self.pending and time.monotonic() - self.last_gap > 0.5:
            self.status(self.next, False)
            self.last_gap = time.monotonic()

    def flush(self):
        committed = []
        while self.next in self.pending:
            self.capture.append(self.pending.pop(self.next))
            committed.append(self.next)
            self.next += 1
        if committed:
            self.capture.sync()
            for sequence in committed:
                self.status(sequence)


def session(link, store, shutdown, max_bytes):
    link.wait_heartbeat()
    last_start = last_flush = 0
    last_data = time.monotonic()
    with store.new("stream") as capture:
        stream = Stream(capture, link.status, max_bytes=max_bytes)
        reason = "operator stop"
        try:
            while not shutdown():
                message = link.recv()
                link.ready()
                store.check()
                now = time.monotonic()
                if not stream.started and now - last_start > 1:
                    link.status(START)
                    last_start = now
                if message and message.get_type() == "REMOTE_LOG_DATA_BLOCK":
                    if (message.get_srcComponent() != 155 or message.target_system != link.source
                            or message.target_component != link.component):
                        continue
                    stream.accept(message.seqno, message.data)
                    last_data = now
                if now - last_flush >= 0.1:
                    stream.flush()
                    last_flush = now
                if now - last_data > 30:
                    raise TimeoutError("no remote-log data for 30 seconds; check LOG_BACKEND_TYPE and competing receiver")
        except (OSError, RuntimeError, ValueError, TimeoutError) as error:
            reason = str(error)
            raise
        finally:
            # Never stop an unrelated receiver: only stop after receiving OUR stream.
            if stream.started:
                try:
                    link.status(STOP)
                except OSError:
                    pass
            # A live protocol has no EOF/tail length. Do not label it complete.
            # Failure paths keep .partial (including unacknowledged data).
            if reason == "operator stop":
                stream.flush()
                receipt = capture.finish("stream.bin", {"kind": "live-dataflash", "complete": False,
                    "reason": reason, "contiguous_blocks": stream.next, "source_system": link.system,
                    "note": "Protocol has no EOF; final partial FC block and producer drops are not recoverable here."})
                print(receipt, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mount", type=Path, default=Path("/sdcard"))
    parser.add_argument("--port", type=int, default=14561)
    parser.add_argument("--system-id", type=int, default=1)
    parser.add_argument("--source-id", type=int, default=245)
    parser.add_argument("--reserve-mib", type=int, default=256)
    parser.add_argument("--max-mib", type=int, default=1024)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.reserve_mib < 1 or not 1 <= args.max_mib <= 16384:
        parser.error("invalid storage limits")
    stopped = False
    def stop(*unused):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with Store(args.mount, "ardupilot", "live", args.reserve_mib*1024*1024) as store:
        if args.check:
            print("SD storage ready; link and firmware not tested")
            return
        link = Link(args.port, args.system_id, args.source_id)
        try:
            session(link, store, lambda: stopped, args.max_mib*1024*1024)
        finally:
            link.close()


if __name__ == "__main__":
    main()
