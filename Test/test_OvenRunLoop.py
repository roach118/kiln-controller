import datetime
import json

from config import CONFIG
import lib.oven as oven_module
from lib.oven import Oven
from lib.profile import Profile


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


class ControlledClock:
    def __init__(self, start=0.0):
        self.now = float(start)

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += float(seconds)


class DummyStatus:
    def over_error_limit(self):
        return False


class DummyTempSensor:
    def __init__(self, oven):
        self.oven = oven
        self.last_ok_time = None
        self.fatal_reason = None
        self.status = DummyStatus()

    def temperature(self):
        self.last_ok_time = oven_module.time.time()
        return self.oven.temp_value


class DummyBoard:
    def __init__(self, oven):
        self.temp_sensor = DummyTempSensor(oven)


class DummyHistory:
    def __init__(self):
        self.ticks = []
        self.started = False

    def start_run(self, profile, startat, config_snapshot):
        self.started = True

    def append_tick(self, state):
        self.ticks.append(state)

    def end_run(self, reason):
        return None


class ControlledOven(Oven):
    def __init__(self):
        self.temp_value = 25.0
        self.board = DummyBoard(self)
        super().__init__()
        self.history = DummyHistory()

    def heat_then_cool(self):
        with self.state_lock:
            self.heat = 1.0
        self.sleep_with_abort(1)
        self.temp_value += 5.0


def test_run_iteration_updates_runtime_and_history(monkeypatch):
    clock = ControlledClock(start=0.0)

    orig_datetime = datetime.datetime

    class FakeDateTime(orig_datetime):
        @classmethod
        def now(cls, tz=None):
            return orig_datetime.fromtimestamp(clock.time(), tz)

    monkeypatch.setattr(oven_module.time, "time", clock.time)
    monkeypatch.setattr(oven_module.time, "sleep", clock.sleep)
    monkeypatch.setattr(oven_module.datetime, "datetime", FakeDateTime)

    oven = ControlledOven()
    profile = Profile(json.dumps({"name": "test", "data": [[0, 25], [60, 50]]}))
    with ConfigOverride(CONFIG.restart, automatic_restarts=False), ConfigOverride(
        CONFIG.safety, heating_stall_enabled=False
    ), ConfigOverride(CONFIG.run, kiln_must_catch_up=False):
        oven.run_profile(profile, allow_seek=False)
        oven.run_iteration(sleep=False)
        oven.run_iteration(sleep=False)

    assert oven.runtime >= 1.0
    assert oven.history.started is True
    assert len(oven.history.ticks) >= 1
