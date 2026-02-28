import sys

from config import CONFIG
import lib.oven as oven_module
from lib.oven import Output, TempSensorReal, TempSensor


class ConfigOverride:
    def __init__(self, obj, **kwargs):
        self.obj = obj
        self.kwargs = kwargs
        self.old = {}

    def __enter__(self):
        for key, value in self.kwargs.items():
            self.old[key] = getattr(self.obj, key)
            setattr(self.obj, key, value)
        return self

    def __exit__(self, exc_type, exc, tb):
        for key, value in self.old.items():
            setattr(self.obj, key, value)


class DummyDirection:
    OUTPUT = "output"


class DummyDigitalInOut:
    def __init__(self, pin):
        self.pin = pin
        self.direction = None
        self.value = None


def test_output_sets_transition_time(monkeypatch):
    monkeypatch.setattr(oven_module.digitalio, "DigitalInOut", DummyDigitalInOut)
    monkeypatch.setattr(oven_module.digitalio, "Direction", DummyDirection)

    with ConfigOverride(CONFIG.hardware, gpio_heat=object(), gpio_heat_invert=False):
        oven_module.SSR_TRANSITION_TIME = None
        output = Output()
        output.set_output(output.on)
        first = oven_module.SSR_TRANSITION_TIME
        assert first is not None
        output.set_output(output.on)
        assert oven_module.SSR_TRANSITION_TIME == first


def test_temp_sensor_uses_software_spi(monkeypatch):
    monkeypatch.setattr(oven_module.digitalio, "DigitalInOut", DummyDigitalInOut)
    monkeypatch.setattr(oven_module.digitalio, "Direction", DummyDirection)
    called = {}

    def dummy_spi(sclk, mosi, miso):
        called["pins"] = (sclk, mosi, miso)
        return "soft-spi"

    monkeypatch.setattr(oven_module.bitbangio, "SPI", dummy_spi)

    with ConfigOverride(
        CONFIG.hardware,
        spi_sclk=object(),
        spi_mosi=object(),
        spi_miso=object(),
        spi_cs=object(),
    ):
        TempSensorReal()
    assert "pins" in called


def test_temp_sensor_uses_hardware_spi(monkeypatch):
    monkeypatch.setattr(oven_module.digitalio, "DigitalInOut", DummyDigitalInOut)
    monkeypatch.setattr(oven_module.digitalio, "Direction", DummyDirection)
    called = {}

    class DummyBoardModule:
        @staticmethod
        def SPI():
            called["hw"] = True
            return "hw-spi"

    monkeypatch.setitem(sys.modules, "board", DummyBoardModule)

    with ConfigOverride(
        CONFIG.hardware,
        spi_sclk=None,
        spi_mosi=None,
        spi_miso=None,
        spi_cs=object(),
    ):
        TempSensorReal()
    assert called.get("hw") is True
