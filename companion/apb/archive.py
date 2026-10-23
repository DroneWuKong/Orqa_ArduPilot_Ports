#!/usr/bin/env python3
"""Disarmed-only, non-erasing DataFlash archive through the existing router."""
import argparse
import hashlib
from pathlib import Path
import signal
import time

from link import Armed, Link
from storage import Store


class Archive:
    def __init__(self, link, store, timeout=3):
        self.link, self.store, self.timeout = link, store, timeout

    def receive(self, kind, deadline):
        while time.monotonic() < deadline:
            message = self.link.recv()
            self.link.ready(disarmed=True)
            self.store.check()
            if message and message.get_type() == kind and message.get_srcComponent() == 1:
                return message
        return None

    def end(self):
        self.link.conn.mav.log_request_end_send(self.link.system, 1)

    def listing(self):
        self.link.ready(disarmed=True)
        entries = {}
        expected = None
        try:
            for attempt in range(3):
                self.link.conn.mav.log_request_list_send(self.link.system, 1, 0, 65535)
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    item = self.receive("LOG_ENTRY", deadline)
                    if item is None:
                        break
                    if item.num_logs == 0:
                        return {}
                    if not 1 <= item.num_logs <= 2048 or not 1 <= item.id <= item.num_logs:
                        raise ValueError("invalid log inventory")
                    if expected is not None and item.num_logs != expected:
                        raise ValueError("log inventory changed during listing")
                    expected = item.num_logs
                    entry = {"id": item.id, "size": item.size, "time_utc": item.time_utc}
                    if item.id in entries and entries[item.id] != entry:
                        raise ValueError("log changed during listing")
                    entries[item.id] = entry
                    if len(entries) == expected:
                        return entries
                self.end()
            raise TimeoutError("incomplete log inventory")
        finally:
            self.end()

    def chunk(self, log_id, offset, size):
        if not 1 <= size <= 900:
            raise ValueError("invalid transfer window")
        data, seen = bytearray(size), bytearray(size)
        for attempt in range(4):
            self.link.ready(disarmed=True)
            start = seen.index(0)
            self.link.conn.mav.log_request_data_send(self.link.system, 1, log_id, offset+start, size-start)
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                message = self.receive("LOG_DATA", deadline)
                if message is None:
                    break
                if message.id != log_id or not offset <= message.ofs < offset+size:
                    continue  # delayed response from another window
                if not 1 <= message.count <= 90 or message.ofs+message.count > offset+size:
                    raise ValueError("truncated, oversized or premature EOF in LOG_DATA")
                pos = message.ofs-offset
                payload = bytes(message.data[:message.count])
                if len(payload) != message.count:
                    raise ValueError("short LOG_DATA payload")
                for i, value in enumerate(payload, pos):
                    if seen[i] and data[i] != value:
                        raise ValueError("conflicting retransmission")
                    data[i], seen[i] = value, 1
                if all(seen):
                    return bytes(data)
            self.end()  # finish/cancel this window before retrying its holes
        raise TimeoutError("missing log bytes after bounded retries")

    def download(self, entry, inventory):
        size, log_id = entry["size"], entry["id"]
        if not 1 <= size <= 1024*1024*1024:
            raise ValueError("invalid or excessive onboard log size")
        self.store.check(size)
        with self.store.new("dataflash") as capture:
            try:
                for offset in range(0, size, 900):
                    data = self.chunk(log_id, offset, min(900, size-offset))
                    if offset == 0 and not data.startswith(b"\xa3\x95\x80"):
                        raise ValueError("log does not start with DataFlash FMT")
                    capture.append(data)
                capture.sync()
                # Second full read detects changing logs/IDs, beyond packet CRC.
                verify = hashlib.sha256()
                for offset in range(0, size, 900):
                    verify.update(self.chunk(log_id, offset, min(900, size-offset)))
                if verify.hexdigest() != capture.hash.hexdigest():
                    raise ValueError("onboard log changed during archive verification")
                if self.listing() != inventory:
                    raise ValueError("log inventory changed during archive")
                return capture.finish("bin", {"kind": "archived-dataflash", "complete": True,
                    "source_system": self.link.system, "onboard_log": entry,
                    "verification": "two full reads, matching SHA256 and stable inventory",
                    "scope": "complete advertised onboard byte range; does not prove producer had no drops"})
            finally:
                self.end()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mount", type=Path, default=Path("/sdcard"))
    parser.add_argument("--port", type=int, default=14562)
    parser.add_argument("--system-id", type=int, default=1)
    parser.add_argument("--source-id", type=int, default=246)
    parser.add_argument("--reserve-mib", type=int, default=256)
    parser.add_argument("--log-id", type=int, help="default: archive all available onboard logs")
    parser.add_argument("--watch", action="store_true", help="archive at startup and after observed disarms")
    args = parser.parse_args()
    if args.reserve_mib < 1:
        parser.error("reserve must be positive")
    def stop(*unused):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    with Store(args.mount, "ardupilot", "archive", args.reserve_mib*1024*1024) as store:
        link = Link(args.port, args.system_id, args.source_id)
        try:
            link.wait_heartbeat()
            archive = Archive(link, store)
            pending, disarmed_since = True, None
            while True:
                link.recv()
                link.ready()
                store.check()
                try:
                    link.ready(disarmed=True)
                    if disarmed_since is None:
                        disarmed_since = time.monotonic()
                    if pending and (not args.watch or time.monotonic()-disarmed_since >= 10):
                        inventory = archive.listing()
                        if args.log_id is not None and args.log_id not in inventory:
                            raise ValueError("requested log not found")
                        for log_id, entry in sorted(inventory.items()):
                            if args.log_id is None or log_id == args.log_id:
                                print(archive.download(entry, inventory), flush=True)
                        pending = False
                    if not args.watch:
                        return
                except Armed:
                    if not args.watch:
                        raise
                    pending, disarmed_since = True, None
        finally:
            link.close()


if __name__ == "__main__":
    main()
