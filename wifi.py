#!/usr/bin/env python3

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
CHUNK_DELAY = 0.02  # 20ms between chunks

# Minimum firmware version number that supports WiFi scan (wifi_syn)
WIFI_SCAN_MIN_VERSION = 18


# ── BLE packet helpers ────────────────────────────────────────────────────────

def frame(json_str: str) -> bytes:
    """Wrap JSON string in the [0xBB, 0xAA, len_lo, len_hi] BLE header."""
    payload = json_str.encode("utf-8")
    n = len(payload)
    return bytes([0xBB, 0xAA, n & 0xFF, n >> 8]) + payload


def cmd_version_req() -> bytes:
    """sta_req for version info (request=[1])."""
    return frame(json.dumps({"type": "sta_req", "data": {"request": [1]}}))


def cmd_wifi_scan_start() -> bytes:
    """Ask EMO to scan available WiFi networks."""
    return frame(json.dumps({"type": "wifi_syn", "data": {"operation": "start"}}))


def cmd_wifi_scan_stop() -> bytes:
    """Tell EMO to stop WiFi scanning (used on timeout)."""
    return frame(json.dumps({"type": "wifi_syn", "data": {"operation": "stop"}}))


def cmd_wifi_set(ssid: str, password: str) -> bytes:
    """Send WiFi credentials to EMO."""
    return frame(json.dumps({"type": "wifi_set", "data": {"ssid": ssid, "password": password}}))


async def ble_write(client: BleakClient, packet: bytes):
    """Write packet in 20-byte chunks, write-without-response."""
    chunks = [packet[i:i + CHUNK_SIZE] for i in range(0, len(packet), CHUNK_SIZE)]
    for chunk in chunks:
        await client.write_gatt_char(CHAR_UUID, chunk, response=False)
        if len(chunks) > 1:
            await asyncio.sleep(CHUNK_DELAY)


# ── BLE notification reassembler ──────────────────────────────────────────────

class BleParser:
    """Reassembles multi-chunk BLE notifications into complete JSON messages."""

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


# ── Main logic ────────────────────────────────────────────────────────────────

async def run(args):
    # Find EMO over BLE
    addr = args.emo
    if not addr:
        print("[BLE] Scanning for EMO ...")
        for d in await BleakScanner.discover(timeout=10):
            if d.name and "EMO" in d.name.upper():
                addr = d.address
                print(f"[BLE] Found {d.name}  {d.address}")
                break
        if not addr:
            sys.exit("No EMO device found. Try --emo <MAC> to specify address explicitly.")

    loop   = asyncio.get_event_loop()
    queue  = asyncio.Queue()
    parser = BleParser()

    def on_notify(_, data: bytes):
        msg = parser.feed(bytes(data))
        if msg:
            print(f"[BLE <-] {msg}")
            loop.call_soon_threadsafe(queue.put_nowait, msg)

    async def wait_for(msg_type: str, timeout: float = 30.0):
        """Wait for a specific BLE message type and return it."""
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

        # ── Step 1: request firmware version ─────────────────────────────────
        print("[BLE ->] Requesting firmware version ...")
        await ble_write(client, cmd_version_req())

        try:
            rsp = await wait_for("sta_rsp", timeout=5)
            version_data = (rsp.get("data") or {}).get("version") or {}
            version_name = version_data.get("name", "unknown")
            version_num  = version_data.get("number", 0)
            print(f"[INFO] EMO firmware: {version_name} (#{version_num})")
        except TimeoutError:
            print("[WARN] No version response – continuing anyway.")
            version_num = 0

        # ── Step 2: scan mode or direct mode ─────────────────────────────────
        if args.scan:
            if version_num < WIFI_SCAN_MIN_VERSION and version_num != 0:
                print(f"[WARN] EMO firmware #{version_num} is below {WIFI_SCAN_MIN_VERSION}.")
                print("       WiFi scan (wifi_syn) may not be supported. Continuing anyway...")

            print("[BLE ->] Asking EMO to scan WiFi networks ...")
            await ble_write(client, cmd_wifi_scan_start())

            print("[INFO] Waiting for EMO to scan nearby WiFi (up to 10 s) ...")
            try:
                rsp = await wait_for("wifi_list", timeout=10)
            except TimeoutError:
                print("[ERR] No wifi_list received – sending stop and aborting.")
                await ble_write(client, cmd_wifi_scan_stop())
                return

            result = (rsp.get("data") or {}).get("result", 0)
            if result != 1:
                print(f"[ERR] wifi_list result={result} (not 1). EMO scan failed.")
                return

            networks = (rsp.get("data") or {}).get("list") or []
            # Filter out blank SSIDs
            networks = [n for n in networks if n.get("ssid", "").strip()]

            if not networks:
                print("[ERR] EMO returned an empty network list.")
                return

            print("\n── Available WiFi networks ──────────────────────────────")
            for i, net in enumerate(networks):
                rssi = net.get("rssi", "?")
                print(f"  [{i + 1}] {net['ssid']}  (RSSI: {rssi} dBm)")
            print("─────────────────────────────────────────────────────────\n")

            while True:
                try:
                    choice = int(input(f"Pick a network [1-{len(networks)}]: "))
                    if 1 <= choice <= len(networks):
                        break
                except ValueError:
                    pass
                print(f"  Please enter a number between 1 and {len(networks)}.")

            ssid = networks[choice - 1]["ssid"]
            password = input(f"Password for '{ssid}' (leave blank for open network): ")

        else:
            # Direct mode – SSID and password from args
            if not args.ssid:
                sys.exit("ERROR: --ssid is required when not using --scan.")
            ssid     = args.ssid
            password = args.password if args.password is not None else ""

        # Validate lengths (app enforces ssid ≤31 bytes, password ≤63 bytes)
        if len(ssid.encode()) > 31:
            sys.exit(f"ERROR: SSID is too long ({len(ssid.encode())} bytes, max 31).")
        if len(password.encode()) > 63:
            sys.exit(f"ERROR: Password is too long ({len(password.encode())} bytes, max 63).")

        # ── Step 3: send WiFi credentials ────────────────────────────────────
        print(f"\n[BLE ->] Sending credentials: SSID='{ssid}'  password={'(empty)' if not password else '***'}")
        await ble_write(client, cmd_wifi_set(ssid, password))

        # ── Step 4: wait for wifi_rsp ─────────────────────────────────────────
        print("[INFO] Waiting for EMO to connect to WiFi (up to 30 s) ...")
        try:
            rsp = await wait_for("wifi_rsp", timeout=30)
        except TimeoutError:
            print("[ERR] No wifi_rsp received. EMO may still be connecting – check its screen.")
            return

        result = (rsp.get("data") or {}).get("result", 0)
        if result == 1:
            print(f"\n✓ SUCCESS – EMO connected to '{ssid}'!")
        else:
            print(f"\n✗ FAILED  – EMO could not connect (result={result}).")
            print("  Double-check the SSID and password and try again.")

        await client.stop_notify(CHAR_UUID)


def main():
    p = argparse.ArgumentParser(
        description="Connect EMO to WiFi without the official app.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--scan",     action="store_true",
                      help="Ask EMO to scan nearby networks and pick one interactively")
    mode.add_argument("--ssid",     default=None,
                      help="WiFi network name to connect to directly")

    p.add_argument("--password", default=None,
                   help="WiFi password (omit or empty string for open networks)")
    p.add_argument("--emo",      default=None,
                   help="EMO BLE MAC address (auto-scanned if omitted)")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()