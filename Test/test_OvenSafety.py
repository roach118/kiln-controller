import time

from config import CONFIG
from lib.oven import Oven


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


class DummyStatus:
    def over_error_limit(self):
        return False


class DummyTempSensor:
    def __init__(self, temp=25.0):
        self.temp = temp
        self.last_ok_time = time.time()
        self.fatal_reason = None
        self.status = DummyStatus()

    def temperature(self):
        return self.temp


class DummyBoard:
    def __init__(self, temp_sensor):
        self.temp_sensor = temp_sensor


class DummyOven(Oven):
    def __init__(self, temp_sensor):
        self.board = DummyBoard(temp_sensor)
        super().__init__()


def test_sensor_stale_aborts():
    sensor = DummyTempSensor()
    oven = DummyOven(sensor)
    with ConfigOverride(CONFIG.run, sensor_stale_timeout_seconds=1), ConfigOverride(
        CONFIG.restart, automatic_restarts=False
    ):
        with oven.state_lock:
            oven.state = "RUNNING"
        sensor.last_ok_time = time.time() - 5
        with oven.state_lock:
            oven.check_sensor_stale()
        assert oven.last_abort_reason == "sensor_stale"
        assert oven.state == "IDLE"


def test_sensor_fault_aborts():
    sensor = DummyTempSensor()
    oven = DummyOven(sensor)
    with ConfigOverride(CONFIG.restart, automatic_restarts=False):
        with oven.state_lock:
            oven.state = "RUNNING"
        sensor.fatal_reason = "sensor_ramp_anomaly"
        with oven.state_lock:
            oven.check_sensor_faults()
        assert oven.last_abort_reason == "sensor_ramp_anomaly"
        assert oven.state == "IDLE"


def test_safe_start_timeout_aborts():
    sensor = DummyTempSensor()
    oven = DummyOven(sensor)
    with ConfigOverride(CONFIG.run, safe_start_min_good_samples=3, safe_start_timeout_seconds=1), ConfigOverride(
        CONFIG.restart, automatic_restarts=False
    ):
        with oven.state_lock:
            oven.state = "RUNNING"
            oven.safe_start_time = time.time() - 5
        assert oven.safe_start_ready() is False
        assert oven.last_abort_reason == "safe_start_timeout"


def test_safe_start_ready_after_samples():
    sensor = DummyTempSensor()
    oven = DummyOven(sensor)
    with ConfigOverride(CONFIG.run, safe_start_min_good_samples=2, sensor_time_wait=1), ConfigOverride(
        CONFIG.restart, automatic_restarts=False
    ):
        with oven.state_lock:
            oven.state = "RUNNING"
            oven.safe_start_time = time.time()
        sensor.last_ok_time = time.time()
        assert oven.safe_start_ready() is False
        sensor.last_ok_time = time.time()
        assert oven.safe_start_ready() is True


def test_loop_watchdog_aborts():
    sensor = DummyTempSensor()
    oven = DummyOven(sensor)
    with ConfigOverride(CONFIG.run, loop_watchdog_timeout_seconds=1), ConfigOverride(
        CONFIG.restart, automatic_restarts=False
    ):
        with oven.state_lock:
            oven.state = "RUNNING"
            oven.loop_last_tick = time.time() - 5
            oven.check_loop_watchdog()
        assert oven.last_abort_reason == "loop_stalled"


def test_heating_stall_aborts():
    sensor = DummyTempSensor()
    oven = DummyOven(sensor)
    with ConfigOverride(
        CONFIG.safety,
        heating_stall_enabled=True,
        heating_stall_window_seconds=1,
        heating_stall_min_temp_rise=1.0,
        heating_stall_min_heater_output=0.5,
        heating_stall_min_target_delta=5.0,
        ignore_heating_stall=False,
    ), ConfigOverride(CONFIG.restart, automatic_restarts=False):
        with oven.state_lock:
            oven.state = "RUNNING"
            oven.target = 200.0
            oven.pid.pidstats = {"out": 1.0}
            oven.heat_check_time = time.time() - 2
            oven.heat_check_temp = 100.0
        oven.check_heating_progress(100.2)
        assert oven.last_abort_reason == "aborted"
        assert oven.state == "IDLE"


def test_cost_uses_heat_seconds():
    sensor = DummyTempSensor()
    oven = DummyOven(sensor)
    with ConfigOverride(CONFIG.cost, kwh_rate=1.0, kw_elements=1.0):
        with oven.state_lock:
            oven.heat = 2.0
            oven.cost = 0.0
            oven.heat_total_seconds = 0.0
            oven.update_cost()
        assert round(oven.cost, 6) == round(2.0 / 3600.0, 6)
        assert oven.heat_total_seconds == 2.0
