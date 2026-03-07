# Emo-Scripts
A lot of scripts for the robot EMO!

# The Scripts/Files
## carry.py
### Usage:
--on: Enable carry mode            python carry.py --on
--off: Disable carry mode          python carry.py --off
--toggle: flip current state       python carry.py --toggle
--status: just print current state python carry.py --status

### What it does
It puts EMO in carry mode.

## custom_image.py
### Usage:
--image: Directory of the image.                                             python custom_image.py --image C:\blablabla\image.png **required** 
--ip: The IP of your PC.                                                     python custom_image.py --ip 192.168.70.112            **required**
--port: The port this script will use. Only change if you now what ya doing! python custom_image.py --port 9090         
--emo: MAC address of your emo. Without it will scan for your emo.           python custom_image.py --emo 00:1A:2B:3C:4D:5E
--tran                                                                       python custom_image.py --tran 128
--timeout: How long to wait.                                                 python custom_image.py --timeout 30

### What it does
Lets you show on emo a custom image.
