import time

from config import CONFIG
import lib.oven as oven_module
from lib.oven import TempSensor, TempSensorReal


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


class DummyTempSensorReal(TempSensorReal):
    def __init__(self, raw_value=100.0):
        TempSensor.__init__(self)
        self.raw_value = raw_value

    def raw_temp(self):
        return self.raw_value


def test_ssr_quiet_window_discards_reading():
    sensor = DummyTempSensorReal()
    with ConfigOverride(CONFIG.run, ssr_quiet_window_ms=200):
        oven_module.SSR_TRANSITION_TIME = time.time()
        temp = sensor.get_temperature()
    oven_module.SSR_TRANSITION_TIME = None
    assert temp is None
    assert sensor.last_ok_time is None


def test_ssr_quiet_window_allows_reading_after_window():
    sensor = DummyTempSensorReal()
    with ConfigOverride(CONFIG.run, ssr_quiet_window_ms=100):
        oven_module.SSR_TRANSITION_TIME = time.time() - 1
        temp = sensor.get_temperature()
    oven_module.SSR_TRANSITION_TIME = None
    assert temp == sensor.raw_value
    assert sensor.last_ok_time is not None


def test_ramp_anomaly_marks_fatal():
    sensor = DummyTempSensorReal(raw_value=0.0)
    with ConfigOverride(
        CONFIG.run,
        temp_ramp_max_c_per_sec=0.1,
        temp_ramp_anomaly_window=3,
        temp_ramp_anomaly_max=1,
    ):
        sensor.last_temp = 0.0
        sensor.last_temp_time = time.time() - 1
        assert sensor._accept_temp(0.0) is True

        sensor.last_temp = 0.0
        sensor.last_temp_time = time.time() - 0.1
        assert sensor._accept_temp(10.0) is False

        sensor.last_temp = 0.0
        sensor.last_temp_time = time.time() - 0.1
        sensor._accept_temp(20.0)
    assert sensor.fatal_reason == "sensor_ramp_anomaly"
