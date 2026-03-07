#!/usr/bin/env python3

import asyncio
import json
import socket
import argparse
import threading
import sys
import io
from pathlib import Path

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    sys.exit("bleak not installed – run: pip install bleak")

try:
    import mss
except ImportError:
    sys.exit("mss not installed – run: pip install mss")

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow not installed – run: pip install pillow")


CHAR_UUID   = "0000ffe1-0000-1000-8000-00805f9b34fb"
CHUNK_SIZE  = 20
CHUNK_DELAY = 0.02  # 20ms between chunks
SCREEN_W    = 320
SCREEN_H    = 240


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


# ── Screenshot helper ─────────────────────────────────────────────────────────

def capture_screen_png() -> bytes:
    """Grab primary monitor, resize to 320x240, return as PNG bytes."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]   # 1 = primary screen
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    img = img.resize((SCREEN_W, SCREEN_H), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, compress_level=9)
    return buf.getvalue()


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


# ── Send one image round-trip ─────────────────────────────────────────────────

async def send_image(client, args, img: bytes, queue: asyncio.Queue):
    """Start TCP server, send set_eye BLE command, wait for result=1."""

    async def wait_eye_rsp(want=1, timeout=60):
        loop = asyncio.get_event_loop()
        end = loop.time() + timeout
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

    ready, done = threading.Event(), threading.Event()
    threading.Thread(target=serve_image,
                     args=(args.port, img, ready, done), daemon=True).start()
    ready.wait(timeout=5)
    await asyncio.sleep(0.2)

    print(f"[BLE ->] set_eye  server={args.ip}:{args.port}  img={len(img)} bytes")
    await ble_write(client, cmd_set_eye(args.ip, args.port, len(img), args.tran)) # -----------------------------------------------------------------------------------------

    print("[BLE] Waiting for confirmation ...")
    await wait_eye_rsp(want=1, timeout=60)
    done.wait(timeout=5)
    print("[BLE] Image accepted ✓")


# ── Main ──────────────────────────────────────────────────────────────────────

async def run(args):
    # Load initial image
    path = Path(args.image)
    if not path.exists():
        sys.exit(f"File not found: {path}")
    img = path.read_bytes()
    if len(img) > 102400:
        pil = Image.open(path).convert("RGBA")
        pil.thumbnail((128, 128))
        buf = io.BytesIO()
        pil.save(buf, format="PNG", optimize=True)
        img = buf.getvalue()
        print(f"[INFO] Auto-resized to {len(img)} bytes")
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

    print(f"[BLE] Connecting to {addr} ...")
    async with BleakClient(addr, timeout=20) as client:
        print(f"[BLE] Connected  MTU={client.mtu_size}")
        await client.start_notify(CHAR_UUID, on_notify)
        await asyncio.sleep(0.3)

        # Enter customization mode
        print("[BLE ->] customize in")
        print(cmd_in)
        await ble_write(client, cmd_in())
        print("[BLE] Waiting for ready ...")

        async def wait_ready(timeout=30):
            end = loop.time() + timeout
            while True:
                left = end - loop.time()
                if left <= 0:
                    raise TimeoutError("Timed out waiting for EMO ready")
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=min(left, 1.0))
                except asyncio.TimeoutError:
                    continue
                if msg.get("type") == "eye_rsp" and (msg.get("data") or {}).get("result") == 1:
                    return

        await wait_ready()
        print("[BLE] EMO ready ✓")

        # ── Round 1: send the user-provided image ─────────────────────────────
        await send_image(client, args, img, queue)

        # ── Loop: screenshot → resize to 320x240 → send ───────────────────────
        frame_n = 0
        print(f"\n[LOOP] Starting screenshot loop (interval={args.interval}s). Press Ctrl+C to stop.\n")
        try:
            while True:
                frame_n += 1
                print(f"[LOOP] Capturing screenshot #{frame_n} ...")
                screen_png = capture_screen_png()
                print(f"[LOOP] {len(screen_png)} bytes  ({SCREEN_W}x{SCREEN_H})")
                await send_image(client, args, screen_png, queue)
                await asyncio.sleep(args.interval)

        except KeyboardInterrupt:
            print("\n[LOOP] Stopped by user.")

        # Exit customization mode
        print("[BLE ->] customize out")
        await ble_write(client, cmd_out())
        try:
            end = loop.time() + 10
            while True:
                left = end - loop.time()
                if left <= 0:
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=min(left, 1.0))
                except asyncio.TimeoutError:
                    continue
                if msg.get("type") == "eye_rsp" and (msg.get("data") or {}).get("result") == 1:
                    break
        except Exception:
            pass

        await client.stop_notify(CHAR_UUID)

    print("\nDone!")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image",    required=True,  help="PNG file to display first")
    p.add_argument("--ip",       required=True,  help="Your LAN IP (same Wi-Fi as EMO)")
    p.add_argument("--port",     type=int,   default=9090)
    p.add_argument("--emo",      default=None)
    p.add_argument("--tran",     type=int,   default=128)
    p.add_argument("--timeout",  type=float, default=30)
    p.add_argument("--interval", type=float, default=0.5,
                   help="Seconds to wait between screenshot frames (default 0.5)")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()