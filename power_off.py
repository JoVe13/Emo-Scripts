#!/usr/bin/env python3
"""
emo_poweroff.py  –  Power off EMO without the app.

Protocol (reverse-engineered from PowerOffFragment + BleJsonUtil + BleResultParse):

  The power-off lives inside SettingActivity, which requires the setting_in
  handshake on firmware >= 21 before EMO will accept any settings commands.

  Full flow:
    1. → {"type":"sta_req","data":{"request":[1]}}     version check
    2. ← {"type":"sta_rsp","data":{"version":{...}}}
    3. → {"type":"setting_req","data":{"op":"in"}}     open settings session (fw >= 21)
    4. ← {"type":"setting_rsp","data":{"result":1}}
    5. → {"type":"off_req"}                            power off command
    6. ← {"type":"off_rsp","data":{"result":1}}        EMO confirms then shuts down

Usage:
  python emo_poweroff.py
  python emo_poweroff.py --emo CC:DB:A7:A2:11:9A
  python emo_poweroff.py --force    # skip confirmation prompt

Install:  pip install bleak
"""

import asyncio
import json
import argparse
import sys

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    sys.exit("bleak not installed – run: pip install bleak")


CHAR_UUID   = "0000ffe1-0000-1000-8000-00805f9b34fb"
CHUNK_SIZE  = 20
CHUNK_DELAY = 0.02
SETTING_IN_MIN_VERSION = 21


# ── BLE helpers ───────────────────────────────────────────────────────────────

def frame(json_str: str) -> bytes:
    payload = json_str.encode("utf-8")
    n = len(payload)
    return bytes([0xBB, 0xAA, n & 0xFF, n >> 8]) + payload

def cmd_version_req() -> bytes:
    return frame(json.dumps({"type": "sta_req", "data": {"request": [1]}}))

def cmd_setting_in() -> bytes:
    return frame(json.dumps({"type": "setting_req", "data": {"op": "in"}}))

def cmd_power_off() -> bytes:
    return frame(json.dumps({"type": "off_req"}))

async def ble_write(client: BleakClient, packet: bytes):
    chunks = [packet[i:i + CHUNK_SIZE] for i in range(0, len(packet), CHUNK_SIZE)]
    for chunk in chunks:
        await client.write_gatt_char(CHAR_UUID, chunk, response=False)
        if len(chunks) > 1:
            await asyncio.sleep(CHUNK_DELAY)


# ── BLE notification reassembler ──────────────────────────────────────────────

class BleParser:
    def __init__(self):
        self._buf   = bytearray()
        self._total = 0

    def feed(self, data: bytes):
        if len(data) >= 4 and data[0] == 0xBB and data[1] == 0xAA:
            self._total = data[2] + data[3] * 256
            self._buf   = bytearray(data[4:])
        elif self._total:
            self._buf.extend(data)
        if self._total and len(self._buf) >= self._total:
            raw = bytes(self._buf[:self._total])
            self._total = 0
            self._buf   = bytearray()
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                pass
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

async def run(args):
    # Confirmation prompt
    if not args.force:
        answer = input("Are you sure you want to power off EMO? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return

    addr = args.emo
    if not addr:
        print("[BLE] Scanning for EMO ...")
        for d in await BleakScanner.discover(timeout=10):
            if d.name and "EMO" in d.name.upper():
                addr = d.address
                print(f"[BLE] Found {d.name}  {d.address}")
                break
        if not addr:
            sys.exit("No EMO found. Use --emo <MAC> to specify address explicitly.")

    loop   = asyncio.get_event_loop()
    queue  = asyncio.Queue()
    parser = BleParser()

    def on_notify(_, data: bytes):
        msg = parser.feed(bytes(data))
        if msg:
            print(f"[BLE <-] {msg}")
            loop.call_soon_threadsafe(queue.put_nowait, msg)

    async def wait_for(msg_type: str, timeout: float = 10.0):
        end = loop.time() + timeout
        while True:
            left = end - loop.time()
            if left <= 0:
                raise TimeoutError(f"Timed out waiting for '{msg_type}'")
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=min(left, 1.0))
            except asyncio.TimeoutError:
                continue
            if msg.get("type") == msg_type:
                return msg

    print(f"[BLE] Connecting to {addr} ...")
    async with BleakClient(addr, timeout=20) as client:
        print(f"[BLE] Connected  MTU={client.mtu_size}")
        await client.start_notify(CHAR_UUID, on_notify)
        await asyncio.sleep(0.3)

        # ── Step 1: get firmware version ──────────────────────────────────────
        print("[BLE ->] Requesting firmware version ...")
        await ble_write(client, cmd_version_req())
        try:
            rsp = await wait_for("sta_rsp", timeout=8)
            version_data = (rsp.get("data") or {}).get("version") or {}
            version_name = version_data.get("name", "unknown")
            version_num  = version_data.get("number", 0)
            print(f"[INFO] EMO firmware: {version_name} (#{version_num})")
        except TimeoutError:
            print("[WARN] No version response – assuming modern firmware, continuing.")
            version_num = 99

        # ── Step 2: setting_in handshake (required on firmware >= 21) ─────────
        if version_num >= SETTING_IN_MIN_VERSION:
            print("[BLE ->] Sending setting_in handshake ...")
            await ble_write(client, cmd_setting_in())
            try:
                rsp = await wait_for("setting_rsp", timeout=10)
                result = (rsp.get("data") or {}).get("result", 0)
                if result == 1:
                    print("[INFO] Settings session opened ✓")
                else:
                    print(f"[ERR] setting_in rejected (result={result}) – EMO may not be ready.")
                    return
            except TimeoutError:
                print("[ERR] No response to setting_in – aborting.")
                return
        else:
            print(f"[INFO] Firmware #{version_num} < {SETTING_IN_MIN_VERSION}, skipping setting_in.")

        # ── Step 3: send power off ────────────────────────────────────────────
        print("[BLE ->] Sending power off command ...")
        await ble_write(client, cmd_power_off())

        try:
            rsp = await wait_for("off_rsp", timeout=10)
            result = (rsp.get("data") or {}).get("result", 0)
            if result == 1:
                print("\n✓ EMO is powering off. Goodbye!")
            else:
                print(f"\n✗ Power off failed (result={result}).")
        except TimeoutError:
            # EMO may power off so fast it drops BLE before replying
            print("\n[INFO] No off_rsp received – EMO may have powered off immediately.")

        await client.stop_notify(CHAR_UUID)


def main():
    p = argparse.ArgumentParser(
        description="Power off EMO without the app.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--emo",   default=None, help="EMO BLE MAC address (auto-scanned if omitted)")
    p.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()