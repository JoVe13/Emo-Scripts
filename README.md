# Emo-Scripts
A lot of scripts for the robot EMO!

# EMO MAY NOT BE CONNECTED WITH THE APP WHEN USING 1 OF THESE!

# The Scripts/Files
## carry.py
### Usage:
- --on: Enable carry mode            python carry.py --on
- --off: Disable carry mode          python carry.py --off
- --toggle: flip current state       python carry.py --toggle
- --status: just print current state python carry.py --status

### What it does
It puts EMO in carry mode.

## custom_image.py
### Usage:
- --image: Directory of the image.                                             python custom_image.py --image C:\blablabla\image.png **required** 
- --ip: The IP of your PC.                                                     python custom_image.py --ip 192.168.70.112            **required**
- --port: The port this script will use. Only change if you now what ya doing! python custom_image.py --port 9090         
- --emo: MAC address of your emo. Without it will scan for your emo.           python custom_image.py --emo 00:1A:2B:3C:4D:5E
- --tran                                                                       python custom_image.py --tran 128
- --timeout: How long the script will wait.                                    python custom_image.py --timeout 30

### What it does
Lets you show on emo a custom image.

## desktop_on_emo.py
### Usage:
- --image: PNG file to display first                    python desktop_on_emo.py --image C:\blablabla\image.png **required**
- --ip: Your LAN IP                                     python desktop_on_emo.py --ip 192.168.70.112            **required**
- --port: The port the script will use                  python desktop_on_emo.py --port 9090
- --emo: Emo's mac address                              python desktop_on_emo.py --emo 00:1A:2B:3C:4D:5E
- --tran                                                python desktop_on_emo.py --tran 128
- --timeout: How long the script will wait              python desktop_on_emo.py --timeout 30
- --interval: Seconds to wait between screenshot frames python desktop_on_emo.py --interval 0                   WARNING! DEFAULT = 0.5, THIS MAKES IT SLOWER! USE FOR MAX SPEED!

### What it does
Lets you show your desktop on emo. It is really slow.

## power_off.py
### Usage:
- --emo: Emo's mac address          python power_off.py --emo
- --force: Skip confirmation prompt python power_off.py --force

### What it does
Powers emo off.

## run.py
### Usage:
- --animation: Play animation (Hi, devil, etc.). Look in the file "all_animations.txt" for all the animations you can choose.
- --speak: Let emo say something (hello, i am a robot, etc.)
- --move: Let emo walk (forward, left, right, back, etc.)
- --move_time: How long emo moves (1, 1.0, 1.7, 0.6, 10.2, etc.")

### What it does
Let emo do an action!

## settings.py
### Usage:
- --temperature   c | f
- --length        metric | imperial
- --auto-update   on | off
- --sched-sound   on | off
- --schedule      on | off
- --flowerfire    on | off
- --hourtime      on | off           (24-hour clock)
- --role          dj | singer | party
- --always-reply  on | off
- --news          human | emo
- --volume        mute | low | med | high

### What it does
Change a setting of emo!

## volume.py
### Usage:
- --set: Set volume to a specific level (mute/low/med/high)
- --up: Increase volume one step
- --down: Decrease volume one step
- --status: Show current volume level

### What it does
Changes the volume.

## wifi.py
### Usage:
- --scan: Ask EMO to scan nearby networks and pick one interactively
- --ssid: WiFi network name to connect to directly
- --password: WiFi password (omit or empty string for open networks)
- --emo: EMO BLE MAC address (auto-scanned if omitted)

### What it does
Connects emo with wifi.
