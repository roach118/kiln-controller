#!/usr/bin/env python
import datetime
import time

import adafruit_bitbangio as bitbangio
from digitalio import DigitalInOut

from config import CONFIG

try:
    import board
except NotImplementedError:
    print("not running a recognized blinka board, exiting...")
    raise SystemExit(1)

########################################################################
#
# To test your thermocouple...
#
# Edit config.toml and set the following in that file to match your
# hardware setup: hardware.spi_sclk, hardware.spi_mosi, hardware.spi_miso, hardware.spi_cs
#
# then run this script...
# 
# ./test-thermocouple.py
#
# It will output a temperature in degrees every second. Touch your
# thermocouple to heat it up and make sure the value changes. Accuracy
# of my thermocouple is .25C.
########################################################################

spi = None
spi_pins = (CONFIG.hardware.spi_sclk, CONFIG.hardware.spi_mosi, CONFIG.hardware.spi_miso)
if any(spi_pins) and not all(spi_pins):
    # Avoid partially configured software SPI that would fail later.
    print("error: hardware.spi_sclk/spi_mosi/spi_miso must be all set or all omitted")
    raise SystemExit(1)

if all(spi_pins):
    spi = bitbangio.SPI(CONFIG.hardware.spi_sclk, CONFIG.hardware.spi_mosi, CONFIG.hardware.spi_miso)
    print("Software SPI selected for reading thermocouple")
    print("SPI configured as:\n")
    print("    hardware.spi_sclk = %s" % (CONFIG.hardware.spi_sclk))
    print("    hardware.spi_mosi = %s" % (CONFIG.hardware.spi_mosi))
    print("    hardware.spi_miso = %s" % (CONFIG.hardware.spi_miso))
    print("    hardware.spi_cs   = %s\n" % (CONFIG.hardware.spi_cs))
else:
    spi = board.SPI()
    print("Hardware SPI selected for reading thermocouple")

if CONFIG.hardware.spi_cs is None:
    print("error: hardware.spi_cs must be set to read the thermocouple")
    raise SystemExit(1)

cs = DigitalInOut(CONFIG.hardware.spi_cs)
cs.switch_to_output(value=True)
sensor = None

print("\nboard: %s" % (board.board_id))
if(CONFIG.thermocouple.max31855):
    import adafruit_max31855
    print("thermocouple: adafruit max31855")
    sensor = adafruit_max31855.MAX31855(spi, cs)
if(CONFIG.thermocouple.max31856):
    import adafruit_max31856
    print("thermocouple: adafruit max31856")
    sensor = adafruit_max31856.MAX31856(
        spi,
        cs,
        thermocouple_type=CONFIG.thermocouple.type,
    )
    print("thermocouple type: %s" % CONFIG.thermocouple.type)
    if CONFIG.thermocouple.ac_freq_50hz:
        sensor.noise_rejection = 50
    else:
        sensor.noise_rejection = 60

if sensor is None:
    print("error: thermocouple.model must be set to max31855 or max31856")
    raise SystemExit(1)

print("Degrees displayed in C\n")

temp = 0
while True:
    time.sleep(1)
    try:
        if CONFIG.thermocouple.max31855:
            temp = sensor.temperature_NIST
        else:
            temp = sensor.temperature
            for k, v in sensor.fault.items():
                if v:
                    print("fault: %s" % k)
        temp += CONFIG.run.thermocouple_offset
        scale = "C"
        print("%s %0.2f%s" %(datetime.datetime.now(),temp,scale))
    except Exception as error:
        print("error: " , error)
