import json
from types import SimpleNamespace

from lib.history import HistoryLogger


class DummyProfile:
    def __init__(self, name="Test Profile", data=None):
        self.name = name
        self.data = data or [[0, 0], [60, 100]]


def make_config(tmp_path, enabled=True, tick_seconds=30):
    history = SimpleNamespace(
        enabled=enabled,
        tick_seconds=tick_seconds,
        directory=str(tmp_path),
    )
    return SimpleNamespace(history=history)


def read_lines(path):
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle.readlines()]


def test_history_start_tick_end(tmp_path):
    config = make_config(tmp_path, enabled=True, tick_seconds=9999)
    logger = HistoryLogger(config)
    profile = DummyProfile(name="Test/Profile 1")

    logger.start_run(profile, startat=0, config_snapshot={"pid": {}})
    assert logger.filepath is not None

    logger.append_tick({"state": "RUNNING", "temperature": 100})
    logger.append_tick({"state": "RUNNING", "temperature": 101})
    history_path = logger.filepath
    logger.end_run("completed")

    lines = read_lines(history_path)
    assert lines[0]["type"] == "start"
    assert lines[1]["type"] == "tick"
    assert lines[2]["type"] == "end"


def test_history_disabled_no_file(tmp_path):
    config = make_config(tmp_path, enabled=False, tick_seconds=1)
    logger = HistoryLogger(config)
    profile = DummyProfile()

    logger.start_run(profile, startat=0, config_snapshot={})
    assert logger.filepath is None
    logger.append_tick({"state": "RUNNING"})
    logger.end_run("completed")
