import json

from config import CONFIG
from lib.controller import ControllerService


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


class DummyOven:
    def __init__(self):
        self.state = "IDLE"
        self.runs = 0

    def run_profile(self, profile, startat=0, allow_seek=True):
        self.runs += 1
        self.state = "RUNNING"

    def abort_run(self):
        self.state = "IDLE"


def test_controller_run_stop(tmp_path):
    oven = DummyOven()
    service = ControllerService(
        oven=oven,
        profile_path=str(tmp_path),
        can_shutdown_fn=lambda: (True, None),
        request_shutdown_fn=lambda: (True, None),
    )
    profile_obj = {"name": "test", "data": [[0, 0], [60, 100]]}

    ok, err = service.run_profile(profile_obj)
    assert ok is True
    assert err is None
    assert oven.state == "RUNNING"

    ok, err = service.run_profile(profile_obj)
    assert ok is False
    assert "running" in err

    service.stop()
    assert oven.state == "IDLE"


def test_controller_save_profile(tmp_path):
    oven = DummyOven()
    service = ControllerService(
        oven=oven,
        profile_path=str(tmp_path),
        can_shutdown_fn=lambda: (True, None),
        request_shutdown_fn=lambda: (True, None),
    )
    profile_obj = {"name": "test", "data": [[0, 0], [60, 100]]}
    ok, err = service.save_profile(profile_obj, force=False)
    assert ok is True
    assert err is None

    ok, err = service.save_profile(profile_obj, force=False)
    assert ok is False
    assert err == "profile already exists"


def test_controller_shutdown_requires_pin_and_idle(tmp_path):
    oven = DummyOven()
    service = ControllerService(
        oven=oven,
        profile_path=str(tmp_path),
        can_shutdown_fn=lambda: (True, None),
        request_shutdown_fn=lambda: (True, None),
    )
    with ConfigOverride(CONFIG.security, pin=1234):
        ok, err = service.shutdown(pin="1111")
        assert ok is False
        assert err == "invalid pin"

        oven.state = "RUNNING"
        ok, err = service.shutdown(pin="1234")
        assert ok is False
        assert "idle" in err

        oven.state = "IDLE"
        ok, err = service.shutdown(pin="1234")
        assert ok is True
        assert err is None


def test_controller_shutdown_propagates_error(tmp_path):
    oven = DummyOven()
    service = ControllerService(
        oven=oven,
        profile_path=str(tmp_path),
        can_shutdown_fn=lambda: (True, None),
        request_shutdown_fn=lambda: (False, "permission denied"),
    )
    with ConfigOverride(CONFIG.security, pin=4321):
        ok, err = service.shutdown(pin="4321")
        assert ok is False
        assert err == "permission denied"
