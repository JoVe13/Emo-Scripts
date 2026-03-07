#!/usr/bin/env python3
"""
emo_carry.py  –  Enable or disable EMO's carry mode without the app.

Protocol (reverse-engineered from MainActivity + SettingActivity + CarryModeFragment):

  The sneaky part: on firmware >= 21, the app sends Setting("in") FIRST and only
  proceeds after receiving setting_rsp result=1. Without this handshake the firmware
  silently ignores carry_on / carry_off. On exit, Setting("out") must also be sent.
  Carry mode itself is only available on firmware > 35 (or version "2.8.0").

  Full flow:
    1. → {"type":"sta_req","data":{"request":[1]}}        version check
    2. ← {"type":"sta_rsp","data":{"version":{"name":"...","number":N},...}}
    3. → {"type":"sta_req","data":{"request":[12]}}        read preferences
    4. ← {"type":"sta_rsp","data":{"preference":{"carry":0,...},...}}
    5. → {"type":"setting_req","data":{"op":"in"}}         REQUIRED handshake
    6. ← {"type":"setting_rsp","data":{"result":1}}        firmware is ready
    7. → {"type":"setting_req","data":{"op":"carry_on"}}   (or "carry_off")
    8. ← {"type":"setting_rsp","data":{"result":1}}        success
    9. → {"type":"setting_req","data":{"op":"out"}}        close settings session

Usage:
  python emo_carry.py --on               # enable carry mode
  python emo_carry.py --off              # disable carry mode
  python emo_carry.py --toggle           # flip current state
  python emo_carry.py --status           # just print current state

  python emo_carry.py --on --emo CC:DB:A7:A2:11:9A

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

# Firmware version thresholds (from NavSetFragment + MainActivity source)
SETTING_IN_MIN_VERSION  = 21   # setting_req "in"/"out" handshake required
CARRY_MODE_MIN_VERSION  = 35   # carry mode available on firmware > 35 or "2.8.0"


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

def cmd_carry_on() -> bytes:
    return frame(json.dumps({"type": "setting_req", "data": {"op": "carry_on"}}))

def cmd_carry_off() -> bytes:
    return frame(json.dumps({"type": "setting_req", "data": {"op": "carry_off"}}))

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

    async def wait_for(msg_type: str, timeout: float = 15.0):
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

    async def wait_setting_rsp(timeout: float = 10.0):
        """Wait for setting_rsp and return result code."""
        msg = await wait_for("setting_rsp", timeout=timeout)
        return (msg.get("data") or {}).get("result", 0)

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
            version_num  = 99
            version_name = "unknown"

        # Carry mode availability check
        carry_available = (version_num > CARRY_MODE_MIN_VERSION
                           or "2.8.0" in version_name)
        if not carry_available and not args.status:
            print(f"\n[WARN] Carry mode requires firmware > {CARRY_MODE_MIN_VERSION} or version '2.8.0'.")
            print(f"       Your firmware: {version_name} (#{version_num})")
            print("       Attempting anyway – it may not work on older firmware.")

        # ── Step 2: read current preference state ─────────────────────────────
        print("[BLE ->] Requesting preference state ...")
        await ble_write(client, cmd_preference_req())
        try:
            rsp = await wait_for("sta_rsp", timeout=8)
            preference = (rsp.get("data") or {}).get("preference") or {}
            carry_now  = preference.get("carry", 0)
            print(f"[INFO] Carry mode is currently: {'ON' if carry_now else 'OFF'}")
            for key in ("volume", "temperature", "schedule", "always_reply", "wake_sens"):
                if key in preference:
                    print(f"[INFO]   {key} = {preference[key]}")
        except TimeoutError:
            print("[WARN] Could not read preferences – assuming carry is OFF.")
            carry_now = 0

        if args.status:
            print(f"\nCarry mode: {'✓ ENABLED' if carry_now else '✗ DISABLED'}")
            await client.stop_notify(CHAR_UUID)
            return

        # Decide target state
        if args.toggle:
            target_on = not carry_now
        elif args.on:
            target_on = True
        else:
            target_on = False

        if target_on == bool(carry_now):
            print(f"\nCarry mode is already {'ON' if carry_now else 'OFF'} – nothing to do.")
            await client.stop_notify(CHAR_UUID)
            return

        # ── Step 3: setting_in handshake (required on firmware >= 21) ─────────
        needs_handshake = (version_num >= SETTING_IN_MIN_VERSION)
        if needs_handshake:
            print("[BLE ->] Sending setting_in handshake ...")
            await ble_write(client, cmd_setting_in())
            try:
                result = await wait_setting_rsp(timeout=10)
                if result == 1:
                    print("[INFO] Settings session opened ✓")
                else:
                    print(f"[ERR] setting_in rejected (result={result}) – EMO may not be ready.")
                    await client.stop_notify(CHAR_UUID)
                    return
            except TimeoutError:
                print("[ERR] No response to setting_in – aborting.")
                await client.stop_notify(CHAR_UUID)
                return
        else:
            print(f"[INFO] Firmware #{version_num} < {SETTING_IN_MIN_VERSION}, skipping setting_in.")

        # ── Step 4: send carry_on / carry_off ─────────────────────────────────
        action = "carry_on" if target_on else "carry_off"
        print(f"[BLE ->] Sending: {action} ...")
        await ble_write(client, cmd_carry_on() if target_on else cmd_carry_off())

        try:
            result = await wait_setting_rsp(timeout=10)
            if result == 1:
                print(f"\n✓ SUCCESS – Carry mode is now {'ON' if target_on else 'OFF'}!")
            else:
                print(f"\n✗ FAILED  – EMO returned result={result}.")
        except TimeoutError:
            print("\n[ERR] No setting_rsp received for carry command.")

        # ── Step 5: setting_out (close the settings session) ──────────────────
        if needs_handshake:
            print("[BLE ->] Sending setting_out ...")
            await ble_write(client, cmd_setting_out())
            try:
                await wait_setting_rsp(timeout=8)
                print("[INFO] Settings session closed ✓")
            except TimeoutError:
                pass  # Not critical

        await client.stop_notify(CHAR_UUID)


def main():
    p = argparse.ArgumentParser(
        description="Enable/disable EMO carry mode without the app.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--on",     action="store_true", help="Enable carry mode")
    mode.add_argument("--off",    action="store_true", help="Disable carry mode")
    mode.add_argument("--toggle", action="store_true", help="Flip current carry mode state")
    mode.add_argument("--status", action="store_true", help="Print current carry mode state")
    p.add_argument("--emo", default=None, help="EMO BLE MAC address (auto-scanned if omitted)")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()