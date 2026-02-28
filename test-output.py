#!/usr/bin/env python
import datetime
import time

from config import CONFIG
from lib.oven import Output

try:
    import board
except NotImplementedError:
    print("not running a recognized blinka board, exiting...")
    raise SystemExit(1)

########################################################################
#
# To test your gpio output to control a relay...
#
# Edit config.toml and set the following in that file to match your
# hardware setup: gpio_heat, gpio_heat_invert
#
# then run this script...
# 
# ./test-output.py
#
# This will switch the output on for five seconds and then off for five 
# seconds. Measure the voltage between the output and any ground pin.
# You can also run ./gpioreadall.py in another window to see the voltage
# on your configured pin change.
########################################################################

if CONFIG.hardware.gpio_heat is None:
    print("error: hardware.gpio_heat must be set to test output")
    raise SystemExit(1)

output = Output()
off = output.off
on = output.on

print("\nboard: %s" % (board.board_id))
print("heater configured as hardware.gpio_heat = %s\n" % (CONFIG.hardware.gpio_heat))
print("heater output pin configured as invert = %r\n" % (CONFIG.hardware.gpio_heat_invert))

while True:
    output.set_output(on)
    print("%s heater on" % datetime.datetime.now())
    time.sleep(5)
    output.set_output(off)
    print("%s heater off" % datetime.datetime.now())
    time.sleep(5)
