#!/usr/bin/env python3
"""
emo_volume.py  –  Change EMO's volume without the app.

Protocol (reverse-engineered from PreferenceFragment + BleJsonUtil):

  Volume is one of 4 levels mapped from the seekbar index:
    0 → volume_mute
    1 → volume_low
    2 → volume_med
    3 → volume_high

  Same setting_in/out handshake as carry mode is required (firmware >= 21).

  Full flow:
    1. → {"type":"sta_req","data":{"request":[1]}}          version check
    2. ← {"type":"sta_rsp","data":{"version":{...}}}
    3. → {"type":"sta_req","data":{"request":[12]}}          read current volume
    4. ← {"type":"sta_rsp","data":{"preference":{"volume":N,...}}}
    5. → {"type":"setting_req","data":{"op":"in"}}           open settings session
    6. ← {"type":"setting_rsp","data":{"result":1}}
    7. → {"type":"setting_req","data":{"op":"volume_high"}}  (or mute/low/med)
    8. ← {"type":"setting_rsp","data":{"result":1}}
    9. → {"type":"setting_req","data":{"op":"out"}}          close settings session

Usage:
  python emo_volume.py --set mute
  python emo_volume.py --set low
  python emo_volume.py --set med
  python emo_volume.py --set high
  python emo_volume.py --up           # increase by one step
  python emo_volume.py --down         # decrease by one step
  python emo_volume.py --status       # show current volume

  python emo_volume.py --set high --emo CC:DB:A7:A2:11:9A

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

# Exact op strings from mVolumeString[] in PreferenceFragment
VOLUME_LEVELS = ["volume_mute", "volume_low", "volume_med", "volume_high"]
VOLUME_NAMES  = ["mute", "low", "med", "high"]


# ── BLE helpers ───────────────────────────────────────────────────────────────

def frame(json_str: str) -> bytes:
    payload = json_str.encode("utf-8")
    n = len(payload)
    return bytes([0xBB, 0xAA, n & 0xFF, n >> 8]) + payload

def cmd_version_req() -> bytes:
    return frame(json.dumps({"type": "sta_req", "data": {"request": [1]}}))

def cmd_preference_req() -> bytes:
    return frame(json.dumps({"type": "sta_req", "data": {"request": [12]}}))

def cmd_setting_in() -> bytes:
    return frame(json.dumps({"type": "setting_req", "data": {"op": "in"}}))

def cmd_setting_out() -> bytes:
    return frame(json.dumps({"type": "setting_req", "data": {"op": "out"}}))

def cmd_volume(level_index: int) -> bytes:
    return frame(json.dumps({"type": "setting_req", "data": {"op": VOLUME_LEVELS[level_index]}}))

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

        # ── Step 1: firmware version ──────────────────────────────────────────
        print("[BLE ->] Requesting firmware version ...")
        await ble_write(client, cmd_version_req())
        try:
            rsp = await wait_for("sta_rsp", timeout=8)
            version_data = (rsp.get("data") or {}).get("version") or {}
            version_name = version_data.get("name", "unknown")
            version_num  = version_data.get("number", 0)
            print(f"[INFO] EMO firmware: {version_name} (#{version_num})")
        except TimeoutError:
            print("[WARN] No version response – assuming modern firmware.")
            version_num = 99

        # ── Step 2: read current volume ───────────────────────────────────────
        print("[BLE ->] Reading current preferences ...")
        await ble_write(client, cmd_preference_req())
        try:
            rsp        = await wait_for("sta_rsp", timeout=8)
            preference = (rsp.get("data") or {}).get("preference") or {}
            current    = preference.get("volume", 0)
            current    = max(0, min(3, current))  # clamp to 0–3
            print(f"[INFO] Current volume: {VOLUME_NAMES[current]} (level {current})")
        except TimeoutError:
            print("[WARN] Could not read preferences – assuming volume level 1 (low).")
            current = 1

        # ── Status-only mode ──────────────────────────────────────────────────
        if args.status:
            bar = "█" * (current + 1) + "░" * (3 - current)
            print(f"\nVolume: [{bar}]  {VOLUME_NAMES[current].upper()}")
            await client.stop_notify(CHAR_UUID)
            return

        # ── Determine target level ────────────────────────────────────────────
        if args.set:
            target = VOLUME_NAMES.index(args.set)
        elif args.up:
            target = min(3, current + 1)
        else:  # --down
            target = max(0, current - 1)

        if target == current:
            print(f"\nVolume is already {VOLUME_NAMES[current].upper()} – nothing to do.")
            await client.stop_notify(CHAR_UUID)
            return

        # ── Step 3: setting_in handshake ──────────────────────────────────────
        needs_handshake = (version_num >= SETTING_IN_MIN_VERSION)
        if needs_handshake:
            print("[BLE ->] Sending setting_in handshake ...")
            await ble_write(client, cmd_setting_in())
            try:
                rsp    = await wait_for("setting_rsp", timeout=10)
                result = (rsp.get("data") or {}).get("result", 0)
                if result == 1:
                    print("[INFO] Settings session opened ✓")
                else:
                    print(f"[ERR] setting_in rejected (result={result}).")
                    return
            except TimeoutError:
                print("[ERR] No response to setting_in – aborting.")
                return

        # ── Step 4: send volume command ───────────────────────────────────────
        print(f"[BLE ->] Setting volume to {VOLUME_NAMES[target].upper()} ...")
        await ble_write(client, cmd_volume(target))

        try:
            rsp    = await wait_for("setting_rsp", timeout=10)
            result = (rsp.get("data") or {}).get("result", 0)
            if result == 1:
                bar = "█" * (target + 1) + "░" * (3 - target)
                print(f"\n✓ Volume set to [{bar}]  {VOLUME_NAMES[target].upper()}")
            else:
                print(f"\n✗ Failed (result={result}).")
        except TimeoutError:
            print("\n[ERR] No setting_rsp received.")

        # ── Step 5: setting_out ───────────────────────────────────────────────
        if needs_handshake:
            print("[BLE ->] Sending setting_out ...")
            await ble_write(client, cmd_setting_out())
            try:
                await wait_for("setting_rsp", timeout=8)
                print("[INFO] Settings session closed ✓")
            except TimeoutError:
                pass

        await client.stop_notify(CHAR_UUID)


def main():
    p = argparse.ArgumentParser(
        description="Change EMO's volume without the app.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--set",    choices=VOLUME_NAMES,
                      help="Set volume to a specific level (mute/low/med/high)")
    mode.add_argument("--up",     action="store_true", help="Increase volume one step")
    mode.add_argument("--down",   action="store_true", help="Decrease volume one step")
    mode.add_argument("--status", action="store_true", help="Show current volume level")
    p.add_argument("--emo", default=None, help="EMO BLE MAC address (auto-scanned if omitted)")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()