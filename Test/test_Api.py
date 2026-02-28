import importlib.util
import io
import json
import os

from config import CONFIG

MODULE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "kiln-controller.py"))
spec = importlib.util.spec_from_file_location("kiln_controller", MODULE_PATH)
kiln_controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kiln_controller)
create_app = kiln_controller.create_app


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


class DummyPid:
    def __init__(self):
        self.pidstats = {"p": 1.0}


class DummyOven:
    def __init__(self):
        self.pid = DummyPid()
        self.state = "IDLE"


class DummyController:
    def __init__(self, pin_ok=True, run_ok=True, shutdown_ok=True):
        self.pin_ok = pin_ok
        self.run_ok = run_ok
        self.shutdown_ok = shutdown_ok

    def validate_pin(self, pin):
        return self.pin_ok

    def run_profile_by_name(self, wanted, startat=0, allow_seek=True):
        if self.run_ok:
            return True, None
        return False, "profile not found"

    def shutdown(self, pin):
        if self.shutdown_ok:
            return True, None
        return False, "shutdown denied"

    def pause(self):
        return None

    def resume(self):
        return None

    def stop(self):
        return None

    def get_profiles(self):
        return []

    def save_profile(self, profile, force=False):
        return True, None

    def delete_profile(self, profile):
        return True


class DummyWatcher:
    def add_observer(self, wsock):
        return None


def call_app(app, method, path, json_body=None):
    payload = b""
    if json_body is not None:
        payload = json.dumps(json_body).encode("utf-8")
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "80",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "wsgi.input": io.BytesIO(payload),
        "CONTENT_LENGTH": str(len(payload)),
        "CONTENT_TYPE": "application/json",
    }
    status_headers = {}

    def start_response(status, headers, exc_info=None):
        status_headers["status"] = status
        status_headers["headers"] = headers

    body = b"".join(app(environ, start_response))
    return status_headers["status"], dict(status_headers["headers"]), body


def test_api_history_disabled(tmp_path):
    app = create_app(DummyOven(), DummyController(), DummyWatcher())
    with ConfigOverride(CONFIG.history, enabled=False, directory=str(tmp_path)):
        status, _headers, body = call_app(app, "GET", "/api/history")
    assert status.startswith("200")
    payload = json.loads(body.decode("utf-8"))
    assert payload["enabled"] is False
    assert payload["runs"] == []


def test_api_history_list_and_fetch(tmp_path):
    run_path = tmp_path / "20240101T000000Z_test.jsonl"
    run_path.write_text("{\"type\": \"start\"}\n", encoding="utf-8")
    app = create_app(DummyOven(), DummyController(), DummyWatcher())
    with ConfigOverride(CONFIG.history, enabled=True, directory=str(tmp_path)):
        status, _headers, body = call_app(app, "GET", "/api/history")
        payload = json.loads(body.decode("utf-8"))
        assert payload["enabled"] is True
        assert payload["runs"] == [run_path.name]

        status, headers, body = call_app(app, "GET", f"/api/history/{run_path.name}")
        assert status.startswith("200")
        assert headers.get("Content-Type") == "application/x-ndjson"
        assert body == b"{\"type\": \"start\"}\n"


def test_api_run_requires_pin():
    app = create_app(DummyOven(), DummyController(pin_ok=False), DummyWatcher())
    status, _headers, body = call_app(
        app,
        "POST",
        "/api",
        json_body={"cmd": "run", "pin": "1111", "profile": "test"},
    )
    assert status.startswith("200")
    assert b"invalid pin" in body


def test_api_run_success():
    app = create_app(DummyOven(), DummyController(pin_ok=True, run_ok=True), DummyWatcher())
    status, _headers, body = call_app(
        app,
        "POST",
        "/api",
        json_body={"cmd": "run", "pin": "1111", "profile": "test"},
    )
    assert status.startswith("200")
    assert b"success" in body


def test_api_stats_returns_pidstats():
    app = create_app(DummyOven(), DummyController(), DummyWatcher())
    status, _headers, body = call_app(app, "GET", "/api/stats")
    assert status.startswith("200")
    payload = json.loads(body.decode("utf-8"))
    assert payload["p"] == 1.0


def test_api_invalid_request_missing_json():
    app = create_app(DummyOven(), DummyController(), DummyWatcher())
    status, _headers, body = call_app(app, "POST", "/api")
    assert status.startswith("200")
    payload = json.loads(body.decode("utf-8"))
    assert payload["success"] is False


def test_api_invalid_request_missing_cmd():
    app = create_app(DummyOven(), DummyController(), DummyWatcher())
    status, _headers, body = call_app(app, "POST", "/api", json_body={"foo": "bar"})
    assert status.startswith("200")
    payload = json.loads(body.decode("utf-8"))
    assert payload["success"] is False
