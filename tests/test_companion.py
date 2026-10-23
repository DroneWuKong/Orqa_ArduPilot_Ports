import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

COMPANION = Path(__file__).resolve().parents[1] / "companion/apb"
sys.path.insert(0, str(COMPANION))
import storage


class StorageFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        device = self.path.stat().st_dev
        self.identity = ("42", f"{os.major(device)}:{os.minor(device)}")
        self.identity_patch = patch.object(storage, "card_identity", return_value=self.identity)
        self.identity_mock = self.identity_patch.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.identity_patch.stop)

    def store(self):
        return storage.Store(self.path, "ardupilot", "archive", 0)


class StorageTests(StorageFixture):
    def test_mount_directory_is_not_mount(self):
        with self.assertRaises(storage.NotReady):
            storage.mount_record("1 0 8:1 / / rw - ext4 /dev/sda rw", Path("/sdcard"))

    def test_readonly_mount_rejected(self):
        for options, super_options in (("ro", "rw"), ("rw", "ro")):
            with self.assertRaises(storage.NotReady):
                storage.mount_record(f"1 0 8:1 / /sdcard {options} - vfat /dev/mmcblk1p1 {super_options}", Path("/sdcard"))

    def test_mount_identity(self):
        self.assertEqual(storage.mount_record("41 0 179:1 / /sdcard rw - vfat /dev/mmcblk1p1 rw", Path("/sdcard")), ("41", "179:1"))

    def test_symlink_log_directory_rejected(self):
        (self.path / "ardupilot").symlink_to(self.path, target_is_directory=True)
        with self.assertRaises(OSError):
            self.store()

    def test_duplicate_writer_rejected(self):
        with self.store():
            with self.assertRaises(BlockingIOError):
                self.store()

    def test_mount_replacement_rejected(self):
        with self.store() as store:
            self.identity_mock.return_value = ("43", self.identity[1])
            with self.assertRaises(storage.NotReady):
                store.new("dataflash")

    def test_low_space(self):
        with self.store() as store:
            with self.assertRaises(storage.NotReady):
                store.check(2**63)

    def test_commit_receipt_and_bytes(self):
        with self.store() as store, store.new("dataflash") as capture:
            capture.append(b"verified bytes")
            receipt = capture.finish("bin", {"complete": True})
            output = self.path / "ardupilot" / receipt["file"]
            self.assertEqual(output.read_bytes(), b"verified bytes")
            self.assertEqual(receipt["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(json.loads(output.with_suffix(".bin.json").read_text()), receipt)
            self.assertFalse(receipt["hardware_validated"])

    def test_failed_capture_stays_partial(self):
        with self.store() as store, store.new("dataflash") as capture:
            name = capture.name
            capture.append(b"partial")
        self.assertEqual((self.path / "ardupilot" / name).read_bytes(), b"partial")
        self.assertFalse(list((self.path / "ardupilot").glob("*.bin")))

    def test_fsync_failure_cannot_complete(self):
        with self.store() as store, store.new("dataflash") as capture:
            capture.append(b"partial")
            with patch.object(storage.os, "fsync", side_effect=OSError("media failure")):
                with self.assertRaises(OSError):
                    capture.finish("bin", {"complete": True})
        self.assertFalse(list((self.path / "ardupilot").glob("*.bin")))

    def test_short_writes_are_completed(self):
        write = os.write
        with self.store() as store, store.new("dataflash") as capture:
            with patch.object(storage.os, "write", side_effect=lambda fd, data: write(fd, data[:2])):
                capture.append(b"abcdef")
            self.assertEqual(os.pread(capture.fd, 6, 0), b"abcdef")

    def test_existing_output_never_overwritten(self):
        with self.store() as store, store.new("dataflash") as capture:
            final = self.path / "ardupilot" / (capture.name.removesuffix(".partial") + ".bin")
            final.write_bytes(b"keep")
            capture.append(b"new")
            with self.assertRaises(FileExistsError):
                capture.finish("bin", {})
            self.assertEqual(final.read_bytes(), b"keep")


class StreamTests(StorageFixture):
    def stream(self, store):
        from recorder import Stream
        capture = store.new("stream")
        self.addCleanup(capture.close)
        self.acks = []
        return Stream(capture, lambda seq, ack=True: self.acks.append((seq, ack)))

    def test_reorder_and_durable_ack(self):
        with self.store() as store:
            stream = self.stream(store)
            stream.accept(1, b"b"*200)
            self.assertNotIn((1, True), self.acks)
            stream.accept(0, b"\xa3\x95\x80" + b"a"*197)
            stream.flush()
            self.assertEqual(stream.capture.size, 400)
            self.assertIn((0, True), self.acks)
            self.assertIn((1, True), self.acks)

    def test_sync_failure_never_acks(self):
        with self.store() as store:
            stream = self.stream(store)
            stream.accept(0, b"\xa3\x95\x80" + bytes(197))
            with patch.object(stream.capture, "sync", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    stream.flush()
            self.assertFalse(any(ack for seq, ack in self.acks))

    def test_duplicate_and_conflict(self):
        with self.store() as store:
            stream = self.stream(store)
            first = b"\xa3\x95\x80" + bytes(197)
            stream.accept(0, first)
            stream.flush()
            stream.accept(0, first)
            self.assertEqual(stream.capture.size, 200)
            with self.assertRaises(ValueError):
                stream.accept(0, first[:-1]+b"x")

    def test_invalid_start_and_unbounded_sequence(self):
        with self.store() as store:
            stream = self.stream(store)
            for seq, data in ((0, bytes(200)), (0, bytes(199)), (99999, bytes(200))):
                with self.assertRaises(ValueError):
                    stream.accept(seq, data)

    def test_native_mavlink_wire_and_dataflash_decode(self):
        from pymavlink.dialects.v20 import ardupilotmega as mav
        from pymavlink import DFReader
        fmt = struct.pack("<BBBBB4s16s64s", 0xa3, 0x95, 0x80, 129, 15, b"TEST", b"Qf", b"TimeUS,Value")
        raw = fmt + b"".join(struct.pack("<BBBQf", 0xa3, 0x95, 129, i*1000, float(i)) for i in range(50))
        sender, decoder = mav.MAVLink(None, srcSystem=1, srcComponent=155), mav.MAVLink(None)
        with self.store() as store:
            stream = self.stream(store)
            for seq in (1, 0, 2, 1):
                packet = mav.MAVLink_remote_log_data_block_message(245, 191, seq, raw[seq*200:(seq+1)*200]).pack(sender)
                decoded = None
                for byte in packet:
                    decoded = decoder.parse_char(bytes([byte])) or decoded
                self.assertEqual(decoded.get_srcComponent(), 155)
                stream.accept(decoded.seqno, decoded.data)
                stream.flush()
            path = self.path / "ardupilot" / stream.capture.name
            self.assertEqual(path.read_bytes(), raw[:600])
            reader = DFReader.DFReader_binary(str(path))
            self.assertEqual(reader.recv_match(type="TEST").Value, 0.0)


class ArchiveTests(unittest.TestCase):
    def archive(self, messages):
        from archive import Archive
        self.link = Mock()
        self.link.system = 1
        self.link.recv.side_effect = list(messages) + [None]*10000
        return Archive(self.link, Mock(), timeout=0.001)

    def packet(self, offset, data, log_id=1):
        packet = Mock(id=log_id, ofs=offset, count=len(data), data=data)
        packet.get_type.return_value = "LOG_DATA"
        packet.get_srcComponent.return_value = 1
        return packet

    def test_out_of_order_and_short_final_chunk(self):
        archive = self.archive([self.packet(90, b"b"*13), self.packet(0, b"a"*90)])
        self.assertEqual(archive.chunk(1, 0, 103), b"a"*90+b"b"*13)

    def test_zero_count_is_failure_not_completion(self):
        archive = self.archive([self.packet(0, b"")])
        with self.assertRaises(ValueError):
            archive.chunk(1, 0, 90)

    def test_conflicting_duplicate(self):
        archive = self.archive([self.packet(0, b"a"*90), self.packet(0, b"b"*90)])
        with self.assertRaises(ValueError):
            archive.chunk(1, 0, 180)

    def test_armed_aborts_before_request(self):
        archive = self.archive([])
        self.link.ready.side_effect = RuntimeError("armed")
        with self.assertRaises(RuntimeError):
            archive.chunk(1, 0, 90)
        self.link.conn.mav.log_request_data_send.assert_not_called()

    def test_missing_middle_window_is_retried(self):
        from collections import deque
        archive = self.archive([])
        pending = deque()
        self.link.recv.side_effect = lambda *args: pending.popleft() if pending else None
        calls = []
        def request(system, component, log_id, offset, size):
            calls.append((offset,size))
            if len(calls) == 1:
                pending.extend([self.packet(0,b"a"*90),self.packet(180,b"c"*90)])
            else:
                pending.append(self.packet(90,b"b"*90))
        self.link.conn.mav.log_request_data_send.side_effect = request
        self.assertEqual(archive.chunk(1,0,270), b"a"*90+b"b"*90+b"c"*90)
        self.assertEqual(calls,[(0,270),(90,180)])

    def test_truncated_log_never_passes(self):
        archive = self.archive([self.packet(0,b"a"*90)])
        with self.assertRaises(TimeoutError):
            archive.chunk(1,0,180)


class LinkTests(unittest.TestCase):
    def link(self):
        from link import Link
        connection = Mock()
        with patch("pymavlink.mavutil.mavlink_connection",return_value=connection):
            return Link(),connection

    def heartbeat(self, system=1, component=1, autopilot=3, armed=False):
        message = Mock(autopilot=autopilot,base_mode=128 if armed else 0)
        message.get_type.return_value = "HEARTBEAT"
        message.get_srcSystem.return_value = system
        message.get_srcComponent.return_value = component
        return message

    def test_wrong_source_is_ignored(self):
        link,conn = self.link()
        conn.recv_match.return_value = self.heartbeat(system=2)
        self.assertIsNone(link.recv())
        with self.assertRaises(RuntimeError):
            link.ready()

    def test_wrong_autopilot_and_component_rejected(self):
        for packet in (self.heartbeat(autopilot=12),self.heartbeat(component=155)):
            link,conn = self.link()
            conn.recv_match.return_value = packet
            link.recv()
            with self.assertRaises(RuntimeError):
                link.ready()

    def test_stale_heartbeat_and_armed_rejected(self):
        link,conn = self.link()
        conn.recv_match.return_value = self.heartbeat(armed=True)
        link.recv()
        link.ready()
        with self.assertRaises(RuntimeError):
            link.ready(disarmed=True)
        link.last_heartbeat = 0
        with self.assertRaises(RuntimeError):
            link.ready()

    def test_receiver_heartbeat_is_not_ground_station(self):
        link,conn = self.link()
        conn.recv_match.return_value = self.heartbeat()
        link.recv()
        self.assertEqual(conn.mav.heartbeat_send.call_args.args[:2],(18,8))


if __name__ == "__main__":
    unittest.main()
