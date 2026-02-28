import importlib.util
import io
import json
import os

from geventwebsocket import WebSocketError

MODULE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "kiln-controller.py"))
spec = importlib.util.spec_from_file_location("kiln_controller", MODULE_PATH)
kiln_controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kiln_controller)
create_app = kiln_controller.create_app


class DummyController:
    def __init__(self, pin_ok=True, shutdown_ok=True, save_ok=True, delete_ok=True):
        self.pin_ok = pin_ok
        self.shutdown_ok = shutdown_ok
        self.save_ok = save_ok
        self.delete_ok = delete_ok
        self.run_calls = []
        self.stop_calls = 0
        self.saved_profiles = []
        self.profiles = []

    def validate_pin(self, pin):
        return self.pin_ok

    def run_profile(self, profile):
        self.run_calls.append(profile)
        return True, None

    def shutdown(self, pin):
        if self.shutdown_ok:
            return True, None
        return False, "shutdown denied"

    def stop(self):
        self.stop_calls += 1

    def get_profiles(self):
        return self.profiles

    def save_profile(self, profile, force=False):
        if not self.save_ok:
            return False, "save failed"
        self.saved_profiles.append(profile)
        return True, None

    def delete_profile(self, profile):
        if self.delete_ok:
            return True, None
        return False, "delete failed"


class DummyWatcher:
    def __init__(self):
        self.observers = []

    def add_observer(self, wsock):
        self.observers.append(wsock)


class DummyWebSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []

    def receive(self):
        if not self.messages:
            raise WebSocketError("closed")
        msg = self.messages.pop(0)
        if isinstance(msg, Exception):
            raise msg
        return msg

    def send(self, data):
        self.sent.append(data)


def call_ws(app, path, wsock):
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "80",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "wsgi.input": io.BytesIO(),
        "CONTENT_LENGTH": "0",
        "wsgi.websocket": wsock,
    }

    def start_response(status, headers, exc_info=None):
        return None

    app(environ, start_response)


def test_ws_control_shutdown_ok(monkeypatch):
    controller = DummyController(pin_ok=True, shutdown_ok=True)
    watcher = DummyWatcher()
    app = create_app(object(), controller, watcher)
    monkeypatch.setattr(kiln_controller.time, "sleep", lambda _: None)

    msg = json.dumps({"cmd": "SHUTDOWN", "pin": "1234"})
    wsock = DummyWebSocket([msg, WebSocketError("closed")])
    call_ws(app, "/control", wsock)
    assert any("OK" in sent for sent in wsock.sent)


def test_ws_control_invalid_pin(monkeypatch):
    controller = DummyController(pin_ok=False)
    watcher = DummyWatcher()
    app = create_app(object(), controller, watcher)
    monkeypatch.setattr(kiln_controller.time, "sleep", lambda _: None)

    msg = json.dumps({"cmd": "RUN", "pin": "bad", "profile": {"name": "p", "data": [[0, 0], [1, 1]]}})
    wsock = DummyWebSocket([msg, WebSocketError("closed")])
    call_ws(app, "/control", wsock)
    assert any("invalid pin" in sent for sent in wsock.sent)
    assert controller.run_calls == []


def test_ws_storage_get(monkeypatch):
    controller = DummyController()
    controller.profiles = [{"name": "test", "data": []}]
    watcher = DummyWatcher()
    app = create_app(object(), controller, watcher)
    monkeypatch.setattr(kiln_controller.time, "sleep", lambda _: None)

    wsock = DummyWebSocket(["GET", None])
    call_ws(app, "/storage", wsock)
    assert json.loads(wsock.sent[0])[0]["name"] == "test"


def test_ws_storage_put(monkeypatch):
    controller = DummyController()
    watcher = DummyWatcher()
    app = create_app(object(), controller, watcher)
    monkeypatch.setattr(kiln_controller.time, "sleep", lambda _: None)

    profile = {"name": "new", "data": [[0, 0], [1, 1]]}
    msg = json.dumps({"cmd": "PUT", "profile": profile})
    wsock = DummyWebSocket([msg, None])
    call_ws(app, "/storage", wsock)
    assert controller.saved_profiles[0]["name"] == "new"
    assert any("\"resp\": \"OK\"" in sent for sent in wsock.sent)


def test_ws_config_sends_config(monkeypatch):
    controller = DummyController()
    watcher = DummyWatcher()
    app = create_app(object(), controller, watcher)
    monkeypatch.setattr(kiln_controller.time, "sleep", lambda _: None)

    wsock = DummyWebSocket(["PING", WebSocketError("closed")])
    call_ws(app, "/config", wsock)
    payload = json.loads(wsock.sent[0])
    assert "temp_scale" in payload


def test_ws_status_echo(monkeypatch):
    controller = DummyController()
    watcher = DummyWatcher()
    app = create_app(object(), controller, watcher)
    monkeypatch.setattr(kiln_controller.time, "sleep", lambda _: None)

    wsock = DummyWebSocket(["hello", WebSocketError("closed")])
    call_ws(app, "/status", wsock)
    assert watcher.observers[0] is wsock
    assert "Your message was" in wsock.sent[0]


def test_ws_control_shutdown_check(monkeypatch):
    controller = DummyController()
    watcher = DummyWatcher()
    app = create_app(object(), controller, watcher)
    monkeypatch.setattr(kiln_controller.time, "sleep", lambda _: None)
    monkeypatch.setattr(kiln_controller, "can_shutdown", lambda: (True, None))

    msg = json.dumps({"cmd": "SHUTDOWN_CHECK"})
    wsock = DummyWebSocket([msg, WebSocketError("closed")])
    call_ws(app, "/control", wsock)
    assert any("\"cmd\": \"SHUTDOWN_CHECK\"" in sent for sent in wsock.sent)


def test_ws_control_shutdown_check_fail(monkeypatch):
    controller = DummyController()
    watcher = DummyWatcher()
    app = create_app(object(), controller, watcher)
    monkeypatch.setattr(kiln_controller.time, "sleep", lambda _: None)
    monkeypatch.setattr(kiln_controller, "can_shutdown", lambda: (False, "no sudo"))

    msg = json.dumps({"cmd": "SHUTDOWN_CHECK"})
    wsock = DummyWebSocket([msg, WebSocketError("closed")])
    call_ws(app, "/control", wsock)
    assert any("FAIL" in sent and "no sudo" in sent for sent in wsock.sent)


def test_ws_storage_put_fail(monkeypatch):
    controller = DummyController(save_ok=False)
    watcher = DummyWatcher()
    app = create_app(object(), controller, watcher)
    monkeypatch.setattr(kiln_controller.time, "sleep", lambda _: None)

    profile = {"name": "bad", "data": [[0, 0], [1, 1]]}
    msg = json.dumps({"cmd": "PUT", "profile": profile})
    wsock = DummyWebSocket([msg, None])
    call_ws(app, "/storage", wsock)
    assert any("\"resp\": \"FAIL\"" in sent for sent in wsock.sent)
    assert any("save failed" in sent for sent in wsock.sent if "FAIL" in sent)


def test_ws_storage_delete_fail(monkeypatch):
    controller = DummyController(delete_ok=False)
    watcher = DummyWatcher()
    app = create_app(object(), controller, watcher)
    monkeypatch.setattr(kiln_controller.time, "sleep", lambda _: None)

    profile = {"name": "gone", "data": []}
    msg = json.dumps({"cmd": "DELETE", "profile": profile})
    wsock = DummyWebSocket([msg, None])
    call_ws(app, "/storage", wsock)
    assert any("\"resp\": \"FAIL\"" in sent for sent in wsock.sent)
    assert any("delete failed" in sent for sent in wsock.sent if "FAIL" in sent)
