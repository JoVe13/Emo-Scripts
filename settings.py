#!/usr/bin/env python3
"""
emo_prefs.py  –  Change EMO preference settings without the app.

All settings live in the Preferences tab of SettingActivity and require
the setting_in/out handshake on firmware >= 21.

Settings covered (all confirmed BLE-sent, none are app-only):
  --temperature   c | f
  --length        metric | imperial
  --auto-update   on | off
  --sched-sound   on | off
  --schedule      on | off
  --flowerfire    on | off
  --hourtime      on | off           (24-hour clock)
  --role          dj | singer | party
  --always-reply  on | off
  --news          human | emo

Usage examples:
  python emo_prefs.py --status
  python emo_prefs.py --temperature f
  python emo_prefs.py --length imperial --hourtime on
  python emo_prefs.py --role dj --flowerfire off --auto-update on
  python emo_prefs.py --news emo --always-reply off
  python emo_prefs.py --emo CC:DB:A7:A2:11:9A --temperature c --volume high

  Multiple settings can be changed in one run — they are sent sequentially.

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

# Exact op strings from PreferenceFragment source
SETTINGS_MAP = {
    # (arg_value): op_string
    "temperature": {"c": "temp_c",               "f":        "temp_f"},
    "length":      {"metric": "length_metric",   "imperial": "length_imperial"},
    "auto_update": {"on": "auto_update_on",      "off":      "auto_update_off"},
    "sched_sound": {"on": "schedule_s_on",       "off":      "schedule_s_off"},
    "schedule":    {"on": "schedule_on",         "off":      "schedule_off"},
    "flowerfire":  {"on": "flowerfire_on",       "off":      "flowerfire_off"},
    "hourtime":    {"on": "24hourtime_on",       "off":      "24hourtime_off"},
    "role":        {"dj": "role_dj",             "singer":   "role_sing",    "party": "role_party"},
    "always_reply":{"on": "always_reply_on",     "off":      "always_reply_off"},
    "news":        {"human": "news_resource_human", "emo":   "news_resource_emo"},
    # Volume included for convenience (same session, from PreferenceFragment)
    "volume":      {"mute": "volume_mute", "low": "volume_low",
                    "med":  "volume_med",  "high": "volume_high"},
}

# Human-readable labels for status display
PREF_LABELS = {
    "volume":      {0: "mute", 1: "low",      2: "med",      3: "high"},
    "temperature": {0: "Celsius (°C)",        1: "Fahrenheit (°F)"},
    "length":      {0: "Metric",              1: "Imperial"},
    "auto_update": {0: "off",                 1: "on"},
    "schedule_sound": {0: "off",              1: "on"},
    "schedule":    {0: "off",                 1: "on"},
    "flowerfire":  {0: "off",                 1: "on"},
    "24hourtime":  {0: "off (12h)",           1: "on (24h)"},
    "always_reply":{0: "off",                 1: "on"},
    "news_resource":{0: "Human world",        1: "EMO's world"},
    "speaker_role":{0: "DJ",                  1: "Singer",    2: "Partygoer"},
}


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

def cmd_op(op: str) -> bytes:
    return frame(json.dumps({"type": "setting_req", "data": {"op": op}}))

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def print_status(pref: dict):
    rows = [
        ("Volume",        PREF_LABELS["volume"].get(pref.get("volume"), "?")),
        ("Temperature",   PREF_LABELS["temperature"].get(pref.get("temperature"), "?")),
        ("Length",        PREF_LABELS["length"].get(pref.get("length"), "?")),
        ("Auto-update",   PREF_LABELS["auto_update"].get(pref.get("auto_update"), "?")),
        ("Sched. sound",  PREF_LABELS["schedule_sound"].get(pref.get("schedule_sound"), "?")),
        ("Schedule",      PREF_LABELS["schedule"].get(pref.get("schedule"), "?")),
        ("Flower & Fire", PREF_LABELS["flowerfire"].get(pref.get("flowerfire"), "?")),
        ("24-hour time",  PREF_LABELS["24hourtime"].get(pref.get("24hourtime"), "?")),
        ("Always reply",  PREF_LABELS["always_reply"].get(pref.get("always_reply"), "?")),
        ("News source",   PREF_LABELS["news_resource"].get(pref.get("news_resource"), "?")),
        ("BT role",       PREF_LABELS["speaker_role"].get(pref.get("speaker_role"), "?")),
        ("Wake sens.",    str(pref.get("wake_sens", "?"))),
    ]
    print("\n── EMO Preferences ──────────────────────────────")
    for label, value in rows:
        print(f"  {label:<16} {value}")
    print("─────────────────────────────────────────────────\n")


# ── Main ──────────────────────────────────────────────────────────────────────

async def run(args):
    # Build the list of (label, op_string) to send
    changes = []
    arg_to_key = {
        "temperature": "temperature",
        "length":      "length",
        "auto_update": "auto_update",
        "sched_sound": "sched_sound",
        "schedule":    "schedule",
        "flowerfire":  "flowerfire",
        "hourtime":    "hourtime",
        "role":        "role",
        "always_reply":"always_reply",
        "news":        "news",
        "volume":      "volume",
    }
    for arg_name, key in arg_to_key.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            op = SETTINGS_MAP[key][val]
            changes.append((f"{key}={val}", op))

    if not changes and not args.status:
        print("Nothing to do. Use --status to read current settings, or pass one or more setting flags.")
        print("Run with --help for usage.")
        return

    # Find EMO
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
            rsp          = await wait_for("sta_rsp", timeout=8)
            version_data = (rsp.get("data") or {}).get("version") or {}
            version_name = version_data.get("name", "unknown")
            version_num  = version_data.get("number", 0)
            print(f"[INFO] EMO firmware: {version_name} (#{version_num})")
        except TimeoutError:
            print("[WARN] No version response – assuming modern firmware.")
            version_num = 99

        # ── Step 2: read current preferences ─────────────────────────────────
        print("[BLE ->] Reading current preferences ...")
        await ble_write(client, cmd_preference_req())
        try:
            rsp  = await wait_for("sta_rsp", timeout=8)
            pref = (rsp.get("data") or {}).get("preference") or {}
        except TimeoutError:
            print("[WARN] Could not read preferences.")
            pref = {}

        if args.status:
            print_status(pref)
            if not changes:
                await client.stop_notify(CHAR_UUID)
                return

        if not changes:
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

        # ── Step 4: send each change ──────────────────────────────────────────
        success, failed = [], []
        for label, op in changes:
            print(f"[BLE ->] Setting {label}  (op={op}) ...")
            await ble_write(client, cmd_op(op))
            try:
                rsp    = await wait_for("setting_rsp", timeout=10)
                result = (rsp.get("data") or {}).get("result", 0)
                if result == 1:
                    print(f"         ✓ OK")
                    success.append(label)
                else:
                    print(f"         ✗ Failed (result={result})")
                    failed.append(label)
            except TimeoutError:
                print(f"         ✗ Timed out")
                failed.append(label)

        # ── Step 5: setting_out ───────────────────────────────────────────────
        if needs_handshake:
            print("[BLE ->] Sending setting_out ...")
            await ble_write(client, cmd_setting_out())
            try:
                await wait_for("setting_rsp", timeout=8)
                print("[INFO] Settings session closed ✓")
            except TimeoutError:
                pass

        # ── Summary ───────────────────────────────────────────────────────────
        print("\n── Summary ──────────────────────────────────────")
        for label in success:
            print(f"  ✓  {label}")
        for label in failed:
            print(f"  ✗  {label}")
        print("─────────────────────────────────────────────────")

        await client.stop_notify(CHAR_UUID)


def main():
    p = argparse.ArgumentParser(
        description="Change EMO preference settings without the app.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--status",       action="store_true",
                   help="Print all current preference values")
    p.add_argument("--temperature",  choices=["c", "f"],
                   help="Temperature unit: c (Celsius) or f (Fahrenheit)")
    p.add_argument("--length",       choices=["metric", "imperial"],
                   help="Length unit")
    p.add_argument("--auto-update",  dest="auto_update",  choices=["on", "off"],
                   help="Automatic firmware updates")
    p.add_argument("--sched-sound",  dest="sched_sound",  choices=["on", "off"],
                   help="Schedule alarm sound")
    p.add_argument("--schedule",     choices=["on", "off"],
                   help="Schedule (daily routines)")
    p.add_argument("--flowerfire",   choices=["on", "off"],
                   help="Flower & Fire animation")
    p.add_argument("--hourtime",     choices=["on", "off"],
                   help="24-hour clock display (on=24h, off=12h)")
    p.add_argument("--role",         choices=["dj", "singer", "party"],
                   help="Bluetooth speaker role")
    p.add_argument("--always-reply", dest="always_reply", choices=["on", "off"],
                   help="Always reply to voice commands")
    p.add_argument("--news",         choices=["human", "emo"],
                   help="News source: human (Human world) or emo (EMO's world)")
    p.add_argument("--volume",       choices=["mute", "low", "med", "high"],
                   help="Volume level")
    p.add_argument("--emo",          default=None,
                   help="EMO BLE MAC address (auto-scanned if omitted)")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()