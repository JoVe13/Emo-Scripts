import asyncio
import json
import sys
import argparse
from bleak import BleakScanner, BleakClient

# ── UUIDs ──────────────────────────────────────────────────────────────────────
SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHAR_UUID    = "0000ffe1-0000-1000-8000-00805f9b34fb"

# ── BLE chunk size (must match app setSplitWriteNum(20)) ───────────────────────
CHUNK_SIZE  = 20
CHUNK_DELAY = 0.02   # 20 ms between chunks


# ── All known animation names (from TheaterAnimsUtil) ─────────────────────────
ANIMATIONS = {
    # Emotions
    "angry":           ["mood_angry"],
    "excited":         ["mood_excited"],
    "happy":           ["mood_happy"],
    "upset":           ["mood_wronged"],
    "sad":             ["mood_sad"],
    "scared":          ["mood_scared"],
    "startled":        ["mood_shocked"],
    "what":            ["voice_wake_up"],
    "kiss":            ["interact_emotion_kiss1"],
    "hug":             ["interact_emotion_hug"],
    "hi":              ["Hi"],
    # Daily
    "sleep":           ["sleep_get_in_fast", "sleep_breath_2", "sleep_bubble_1"],
    "wakeup":          ["sleep_wake_up_fast"],
    "boxing":          ["Daily_Boxing_loop4"],
    "toothbrushing":   ["Daily_Brush_teeth_loop2"],
    "toast":           ["Daily_Eating2_loop1"],
    "newspaper":       ["Daily_Newspaper_start", "Daily_Newspaper_loop1"],
    "keyboard":        ["Daily_Work_loop1"],
    "cook":            ["Daily_Cook_loop3", "Daily_Cook_end"],
    "hamburger":       ["Daily_Eating_loop1"],
    "cleaning":        ["Daily_Wipe_glass_start", "Daily_Wipe_glass_end"],
    "tea":             ["Daily_Teatime_loop3"],
    "bartending":      ["Daily_Blending_loop3", "Daily_Blending_end"],
    "mining":          ["Find_coin"],
    "jump_up":         ["jump_up"],
    "parkour":         ["parkour"],
    "pinball":         ["pinball"],
    "aircraft_wars":   ["plane_war"],
    "drone":           ["Daily_UVA_loop3"],
    "juggling":        ["Daily_Juggling_loop2"],
    "rubiks_cube":     ["Daily_Magic_cube_end"],
    "paint":           ["Daily_Painting_loop2", "Daily_Painting_end"],
    "weaving":         ["Daily_Braid_loop2", "Daily_Braid_end"],
    "noodle":          ["Daily_Eating3_start", "Daily_Eating3_end"],
    "tv":              ["Daily_Watch_tv_loop1"],
    # Animals
    "cuckoo":          ["Cuckoo"],
    "cicada":          ["Cicada"],
    "cow":             ["Cattle"],
    "elephant":        ["Elephant"],
    "horse":           ["Horse"],
    "dog":             ["Dog"],
    "wolf":            ["Wolf"],
    "frog":            ["Frog"],
    "chicken":         ["Chicken"],
    "cat":             ["Cat"],
    "sheep":           ["Sheep"],
    "snake":           ["Snake"],
    "tiger":           ["Tiger"],
    "duck":            ["Duck"],
    "pig":             ["Pig"],
    "fox":             ["Fox"],
    # Camping
    "tent":            ["Camp_tent"],
    "fishing":         ["Camp_fishing_Casting", "Camp_fishing_Retrieve_1"],
    "campfire":        ["campfire_start"],
    "barbecue":        ["Camp_barbecue_loop1"],
    # Weapons
    "knife":           ["Fight_Radish_knife"],
    "slingshot":       ["Fight_Slingshot_hit"],
    "water_gun":       ["Fight_Water_Bubble_gun"],
    "boomerang":       ["Fight_Boomerang_miss"],
    # Music
    "piano":           ["emo_ensemble_piano_1"],
    "trumpet":         ["emo_trumpet_1"],
    "tambourine":      ["emo_tambourine_1"],
    "drum_kit":        ["emo_ensemble_drum_1"],
    "singing":         ["sings2_all"],
    "dj":              ["DJ1_ready", "DJ1_loop2"],
    "glow_sticks":     ["Partygoer_loop4"],
    "radio":           ["Partygoer_loop2"],
    # Holidays
    "easter":          ["Easter"],
    "april_fools":     ["april_fools_day"],
    "santa":           ["Christmas_Santa"],
    "christmas":       ["christmas"],
    "new_year":        ["new_years_day"],
    "spring_festival": ["Chinese_New_Year"],
    "fathers_day":     ["Fathers_Day"],
    "mothers_day":     ["Mothers_Day"],
    "valentines":      ["valentines_day"],
    "childrens_day":   ["childrens_day"],
    "thanksgiving":    ["thanksgiving"],
    "moon_day":        ["human_moon_day"],
    "halloween":       ["halloween"],
    "cyclops":         ["halloween_2022"],
    "birthday":        ["birthday_loop", "birthday_end"],
    # Games
    "rock":            ["R_P_S_R"],
    "scissors":        ["R_P_S_S"],
    "paper":           ["R_P_S_P"],
    "dice_1":          ["dice_one_1"],
    "dice_2":          ["dice_two_1"],
    "dice_3":          ["dice_three_1"],
    "dice_4":          ["dice_four_1"],
    "dice_5":          ["dice_five_1"],
    "dice_6":          ["dice_six_1"],
    "fireworks":       ["game_firework_end"],
    "game":            ["emo_play_a_game_loop1"],
    # Cool
    "demon":           ["devil"],
    "devil":           ["wake_up_angry"],
    "laser_eyes":      ["laser_eye_2"],
    "hands_up":        ["gesture_gun_don't_move_start", "gesture_gun_don't_move_loop"],
    "shot":            ["gesture_gun", "gesture_gun_stay1"],
    "zombie":          ["zombie_start1", "zombie_loop_walk1"],
    "photo":           ["photo3"],
    "alarm_anim":      ["alarm_shock_loop"],
    "light":           ["turn_on_light_1"],
    # Weather
    "cloudy":          ["Cloudy3_start", "Cloudy3_end"],
    "sunny":           ["Sunny3_start", "Sunny3_end"],
    "snowy":           ["Snow3_start", "Snow3_end"],
    "rainy":           ["Rain3_end"],
    # Zodiac
    "aquarius":        ["Sign_Aquarius"],
    "aries":           ["Sign_Aries"],
    "cancer":          ["Sign_Cancer"],
    "capricorn":       ["Sign_Capricorn"],
    "gemini":          ["Sign_Gemini"],
    "leo":             ["Sign_Leo"],
    "libra":           ["Sign_Libra"],
    "pisces":          ["Sign_Pisces"],
    "sagittarius":     ["Sign_Sagittarius"],
    "scorpio":         ["Sign_Scorpio"],
    "taurus":          ["Sign_Taurus"],
    "virgo":           ["Sign_Virgo"],
    # v3.1.0+
    "shower":          ["Daily_shower_start", "Daily_shower_loop1", "Daily_shower_end"],
    "poop":            ["Daily_poop_start", "Daily_poop_loop1", "Daily_poop_end"],
    "meditation":      ["Daily_meditation_start", "Daily_meditation_loop1", "Daily_meditation_end"],
    "banana":          ["Daily_banana_start", "Daily_banana_loop1", "Daily_banana_end"],
    "hypnosis":        ["Daily_hypnosis_start", "Daily_hypnosis_loop1", "Daily_hypnosis_end"],
    "fried_chicken":   ["Daily_fried_chicken"],
}


# ── Wire-format helpers ────────────────────────────────────────────────────────

def frame_message(json_str: str) -> bytes:
    payload = json_str.encode("utf-8")
    length  = len(payload)
    header  = bytes([0xBB, 0xAA, length & 0xFF, (length >> 8) & 0xFF])
    return header + payload


def split_chunks(data: bytes, size: int = CHUNK_SIZE) -> list:
    return [data[i:i + size] for i in range(0, len(data), size)]


# ── Message builders ───────────────────────────────────────────────────────────

def _theater(data: dict) -> bytes:
    clean = {k: v for k, v in data.items() if v is not None}
    return frame_message(json.dumps({"type": "theater_req", "data": clean}, separators=(",", ":")))


def make_theater_op(op: str) -> bytes:
    return _theater({"op": op})


def make_theater_play(anim_names: list) -> bytes:
    return _theater({"op": "play", "animations": anim_names})


def make_theater_tts(text: str) -> bytes:
    return _theater({"op": "speak", "txt": text})


# ── Response reassembler ───────────────────────────────────────────────────────

class ResponseAssembler:
    def __init__(self):
        self._buf   = None
        self._total = 0

    def feed(self, chunk: bytes):
        if len(chunk) < 2:
            return None

        if chunk[0] == 0xBB and chunk[1] == 0xAA:
            if len(chunk) < 4:
                return None
            self._total = chunk[2] + (chunk[3] << 8)
            self._buf   = bytearray(chunk[4:])
        elif chunk[0] == 0xDD and chunk[1] == 0xCC:
            return None
        else:
            if self._buf is not None:
                self._buf.extend(chunk)

        if self._buf is not None and len(self._buf) >= self._total:
            result    = bytes(self._buf[: self._total]).decode("utf-8", errors="replace")
            self._buf = None
            return result

        return None


# ── Session expiry ─────────────────────────────────────────────────────────────

class SessionExpiredError(Exception):
    pass


# ── High-level EMO client ──────────────────────────────────────────────────────

class EmoClient:

    def __init__(self, address: str):
        self.address          = address
        self._client          = BleakClient(address)
        self._assembler       = ResponseAssembler()
        self._queue           = asyncio.Queue()
        self._session_expired = False

    # ── Connection ────────────────────────────────────────────────────────────

    async def connect(self):
        print(f"Connecting to {self.address} …")
        await self._client.connect()
        await self._client.start_notify(CHAR_UUID, self._on_notify)
        print("Connected  (notifications enabled)")

    async def disconnect(self):
        try:
            await self._client.stop_notify(CHAR_UUID)
        except Exception:
            pass
        await self._client.disconnect()
        print("Disconnected.")

    # ── Notify handler ────────────────────────────────────────────────────────

    def _on_notify(self, _sender, data: bytearray):
        msg = self._assembler.feed(bytes(data))
        if msg:
            try:
                parsed = json.loads(msg)
                print(f"  <- {parsed}")
                if (parsed.get("type") == "theater_rsp"
                        and parsed.get("data", {}).get("result") == 10):
                    self._session_expired = True
                self._queue.put_nowait(parsed)
            except json.JSONDecodeError:
                pass

    # ── FIX 1: chunked write ──────────────────────────────────────────────────

    async def write(self, payload: bytes):
        if self._session_expired:
            raise SessionExpiredError("Cannot write — EMO session already expired")
        chunks = split_chunks(payload, CHUNK_SIZE)
        for chunk in chunks:
            await self._client.write_gatt_char(CHAR_UUID, bytearray(chunk), response=False)
            if len(chunks) > 1:
                await asyncio.sleep(CHUNK_DELAY)

    # ── Response waiter ───────────────────────────────────────────────────────

    async def wait_for(self, msg_type: str, timeout: float = 8.0):
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            if self._session_expired:
                raise SessionExpiredError("EMO session expired (result=10)")
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return None
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=min(remaining, 0.5))
                result = msg.get("data", {}).get("result")
                if result == 10:
                    raise SessionExpiredError("EMO session expired (result=10)")
                if msg.get("type") == msg_type:
                    return msg
            except asyncio.TimeoutError:
                pass

    # ── Theater session ───────────────────────────────────────────────────────

    async def theater_enter(self) -> bool:
        print("-> Entering theater mode …")
        await self.write(make_theater_op("in"))
        rsp = await self.wait_for("theater_rsp", timeout=10)
        if rsp and rsp.get("data", {}).get("result") == 1:
            print("   Theater mode ready")
            return True
        print("   WARNING: did not receive theater ready response")
        return False

    async def theater_exit(self):
        if self._session_expired:
            print("  (skipping theater exit — session already expired)")
            return
        print("-> Exiting theater mode …")
        try:
            await self.write(make_theater_op("out"))
            await self.wait_for("theater_rsp", timeout=8)
        except SessionExpiredError:
            pass
        except Exception as e:
            print(f"   Warning during theater exit: {e}")

    # ── Commands ──────────────────────────────────────────────────────────────

    async def play_animation(self, anim_key: str, wait_finish: bool = True):
        names = ANIMATIONS.get(anim_key)
        if names is None:
            print(f"  Unknown animation '{anim_key}', skipping.")
            return
        print(f"-> Playing '{anim_key}' : {names}")
        await self.write(make_theater_play(names))
        if wait_finish:
            rsp = await self.wait_for("theater_rsp", timeout=30)
            if rsp:
                result = rsp.get("data", {}).get("result")
                labels = {0: "error/busy", 1: "ack", 2: "done"}
                print(f"   Result: {result} ({labels.get(result, '?')})")

    async def speak(self, text: str, wait_finish: bool = True):
        print(f"-> Speak: \"{text}\"")
        await self.write(make_theater_tts(text))
        if wait_finish:
            await self.wait_for("theater_rsp", timeout=20)

    async def move(self, direction: str, duration: float = 1.0):
        assert direction in ("forward", "back", "left", "right")
        # print(f"-> Move {direction} for {duration:.1f}s")
        await self.write(make_theater_op(direction))
        await asyncio.sleep(float(duration))
        await self.write(make_theater_op("stop"))
        await self.wait_for("theater_rsp", timeout=5)


# ── Demo sequence ──────────────────────────────────────────────────────────────

async def run_demo(address: str, act: str, action: str, move_time: float):
    emo = EmoClient(address)
    await emo.connect()

    try:
        if not await emo.theater_enter():
            print("Could not enter theater mode. Aborting.")
            return

        async def main_loop(act: str, Input: str, move_time: float):
            print("\n=== Animation sequence start ===\n")
            
            if act == "anim":
                if Input != "":
                    await emo.play_animation(Input)
                else:
                    await emo.play_animation(action)
            elif act == "speak":
                if Input != "":
                    await emo.speak(Input)
                else:
                    await emo.speak(action)
            elif act == "move":
                if Input != "":
                    await emo.move(Input, move_time)
                else:
                    await emo.move(action, move_time)
            else:
                print("Please chose 1 argument (--animation, --speak or --move + --move_time). Chosen action: " + act)
                
            # print("Press ENTER to stop the connection with EMO...")
            # await asyncio.to_thread(input)
            
            print("\n=== Sequence complete ===\n")
            
            async def chose_next():
                move_time = 3
                
                next_act = input("Next action: ")
                next_action = ""
                if next_act == "animation" or next_act == "anim" or next_act == "a":
                    act = "anim"
                    next_action = input("Next animation name: ")
                elif next_act == "speak" or next_act == "s" or next_act == "talk" or next_act == "t":
                    act = "speak"
                    next_action = input("Next sentence: ")
                elif next_act == "move" or next_act == "m" or next_act == "movement" or next_act == "walk" or next_act == "w":
                    act = "move"
                    next_action = input("Next direction: ")
                    next_action = input("Move time: ")
                else:
                    print("please chose an existing option")
                    await chose_next()
                if next_action != "":
                    await main_loop(act, next_action, move_time)
            await chose_next()
        
        await main_loop(act, action, move_time)
        
    except SessionExpiredError as e:
        print(f"\n  Session expired mid-sequence: {e}")
    finally:
        await emo.theater_exit()
        await emo.disconnect()


# ── Scanner ────────────────────────────────────────────────────────────────────

async def scan_and_pick():
    print("Scanning for EMO devices (5 s) …")
    devices = await BleakScanner.discover(timeout=5.0)
    emos = [d for d in devices if d.name and d.name.upper().startswith("EMO")]
    if not emos:
        print("No EMO device found.")
        return None
    for i, d in enumerate(emos):
        print(f"  [{i}] {d.name}  {d.address}")
    if len(emos) == 1:
        return emos[0].address
    idx = int(input("Select device index: "))
    return emos[idx].address


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Let emo do any action")
    p.add_argument("--animation",  "-a",    help="Play animation (Hi, devil, etc.)")
    p.add_argument("--speak",      "-s",    help="Let emo say something (hello, i am a robot, etc.)")
    p.add_argument("--move",       "-m",    help="Let emo walk (forward, left, right, back, etc.)")
    p.add_argument("--move_time",  "-mt",    help="How long emo moves (1, 1.0, 1.7, 0.6, 10.2, etc.")
    args = p.parse_args()
    
    act = "anim"
    action = "hi"
    move_time = 1
    chosen = False
    
    if args.animation:
        action = args.animation
        act = "anim"
        chosen = True
    elif args.speak:
        action = args.speak
        act = "speak"
        chosen = True
    elif args.move:
        action = args.move
        move_time = args.move_time
        act = "move"
        chosen = True
    else:
        print("Please chose 1 argument (--animation, --speak or --move + move_time)")

    if chosen==True:
        # sys.argv[1] if len(sys.argv) > 1 else 
        addr = asyncio.run(scan_and_pick())
        if addr:
            asyncio.run(run_demo(addr, act, action, move_time))
        else:
            print("No device selected. Exiting.")
    else:

        print("Exiting")
