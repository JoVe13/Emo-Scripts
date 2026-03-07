#!/usr/bin/env python3

import asyncio
import json
import socket
import struct
import argparse
import threading
import sys
from pathlib import Path

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    sys.exit("bleak not installed – run: pip install bleak")


CHAR_UUID   = "0000ffe1-0000-1000-8000-00805f9b34fb"
CHUNK_SIZE  = 20
CHUNK_DELAY = 0.02  # 20ms between chunks


# ── BLE helpers ───────────────────────────────────────────────────────────────

def frame(json_str: str) -> bytes:
    payload = json_str.encode("utf-8")
    n = len(payload)
    return bytes([0xBB, 0xAA, n & 0xFF, n >> 8]) + payload

def cmd_in():
    return frame(json.dumps({"type": "customize_req", "data": {"op": "in"}}))

def cmd_out():
    return frame(json.dumps({"type": "customize_req", "data": {"op": "out"}}))

def cmd_set_eye(ip, port, length, tran):
    return frame(json.dumps({
        "type": "customize_req",
        "data": {
            "op":     "set_eye",
            # "color":  [0, 0, 0], # [75, 0, 255]
            "server": {"ip": ip, "port": port},
            "image":  {"name": "sticker.png", "length": length, "tran": tran},
        }
    }))

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


# ── TCP image server ──────────────────────────────────────────────────────────

def serve_image(port: int, img: bytes, ready: threading.Event, done: threading.Event):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(1)
    srv.settimeout(90)
    ready.set()
    print(f"[TCP] Listening on 0.0.0.0:{port} ...")
    try:
        conn, addr = srv.accept()
        print(f"[TCP] EMO connected from {addr}")
        conn.settimeout(30)
        with conn:
            buf = bytearray()
            while True:
                try:
                    chunk = conn.recv(1024)
                except socket.timeout:
                    print("[TCP] Timed out waiting for EMO request")
                    break
                if not chunk:
                    print("[TCP] EMO closed connection")
                    break
                buf.extend(chunk)
                print(f"[TCP] EMO sent: {bytes(buf)!r}")
                buf.clear()

                conn.sendall(img)
                print(f"[TCP] Sent {len(img)} raw bytes")

                ack = bytearray()
                try:
                    while len(ack) < 2:
                        b = conn.recv(2 - len(ack))
                        if not b:
                            break
                        ack.extend(b)
                except socket.timeout:
                    pass
                print(f"[TCP] EMO ack: {bytes(ack)!r}")
                if ack.lower() == b"ok":
                    print("[TCP] Transfer confirmed by EMO ✓")
                    break

    except socket.timeout:
        print("[TCP] Timed out – EMO never connected.")
        print("      Check: correct IP? Windows Firewall allowing port", port, "?")
    except Exception as e:
        print(f"[TCP] Error: {e}")
    finally:
        srv.close()
        done.set()


# ── Main ──────────────────────────────────────────────────────────────────────

async def run(args):
    path = Path(args.image)
    if not path.exists():
        sys.exit(f"File not found: {path}")
    img = path.read_bytes()
    if len(img) > 102400:
        try:
            from PIL import Image
            import io
            pil = Image.open(path).convert("RGBA")
            pil.thumbnail((128, 128))
            buf = io.BytesIO()
            pil.save(buf, format="PNG", optimize=True)
            img = buf.getvalue()
            print(f"[INFO] Auto-resized to {len(img)} bytes")
        except ImportError:
            sys.exit("Image > 100 KB and Pillow not installed – run: pip install pillow")
    if len(img) > 102400:
        sys.exit("Image still > 100 KB – use a smaller image.")
    print(f"[INFO] Image: {path.name}  {len(img)} bytes  tran={args.tran}")

    if args.ip in ("127.0.0.1", "localhost"):
        sys.exit("ERROR: --ip must be your real LAN IP (e.g. 192.168.1.x), not 127.0.0.1.\n"
                 "       EMO connects to this IP over Wi-Fi to fetch the image.")

    # Find EMO
    addr = args.emo
    if not addr:
        print("[BLE] Scanning ...")
        for d in await BleakScanner.discover(timeout=10):
            if d.name and "EMO" in d.name.upper():
                addr = d.address
                print(f"[BLE] Found {d.name}  {d.address}")
                break
        if not addr:
            sys.exit("No EMO found. Pass --emo <MAC> explicitly.")

    loop   = asyncio.get_event_loop()
    queue  = asyncio.Queue()
    parser = BleParser()

    def on_notify(_, data: bytes):
        print(f"[BLE <-] raw  {data.hex()}")
        msg = parser.feed(bytes(data))
        if msg:
            print(f"[BLE <-] json {msg}")
            loop.call_soon_threadsafe(queue.put_nowait, msg)

    async def wait_eye_rsp(want=1, timeout=None):
        end = loop.time() + (timeout or args.timeout)
        while True:
            left = end - loop.time()
            if left <= 0:
                raise TimeoutError("Timed out waiting for eye_rsp")
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=min(left, 1.0))
            except asyncio.TimeoutError:
                continue
            if msg.get("type") == "eye_rsp":
                r = (msg.get("data") or {}).get("result")
                if r == want:
                    return
                ERRORS = {0: "generic fail", 2: "server unreachable",
                          3: "image download failed – check IP/firewall",
                          4: "EMO not on Wi-Fi", 5: "empty image",
                          8: "colour error", 9: "sticker set failed", 10: "interrupted"}
                raise RuntimeError(f"eye_rsp result={r}: {ERRORS.get(r, 'unknown')}")

    print(f"[BLE] Connecting to {addr} ...")
    async with BleakClient(addr, timeout=20) as client:
        print(f"[BLE] Connected  MTU={client.mtu_size}")
        await client.start_notify(CHAR_UUID, on_notify)
        await asyncio.sleep(0.3)

        print("[BLE ->] customize in")
        print(cmd_in)
        await ble_write(client, cmd_in())
        print("[BLE] Waiting for ready ...")
        await wait_eye_rsp(want=1)
        print("[BLE] EMO ready ✓")

        ready, done = threading.Event(), threading.Event()
        threading.Thread(target=serve_image,
                         args=(args.port, img, ready, done), daemon=True).start()
        ready.wait(timeout=5)
        await asyncio.sleep(0.2)

        print(f"[BLE ->] set_eye  server={args.ip}:{args.port}  img={len(img)} bytes")
        await ble_write(client, cmd_set_eye(args.ip, args.port, len(img), args.tran)) # -----------------------------------------------------------------------------------------

        print("[BLE] Waiting for confirmation (up to 60 s) ...")
        await wait_eye_rsp(want=1, timeout=60)
        print("[BLE] Image accepted ✓")

        print("[BLE ->] customize out")
        await ble_write(client, cmd_out())
        try:
            await wait_eye_rsp(want=1, timeout=10)
        except TimeoutError:
            pass

        await client.stop_notify(CHAR_UUID)

    done.wait(timeout=5)
    print("\nDone! EMO should now show your custom image.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image",   required=True, help="PNG file to display")
    p.add_argument("--ip",      required=True, help="Your LAN IP (same Wi-Fi as EMO)")
    p.add_argument("--port",    type=int, default=9090)
    p.add_argument("--emo",     default=None)
    p.add_argument("--tran",    type=int, default=128)
    p.add_argument("--timeout", type=float, default=30)
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()