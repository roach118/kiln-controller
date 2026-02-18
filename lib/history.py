import datetime
import json
import logging
import os
import re
import time

log = logging.getLogger(__name__)


class HistoryLogger:
    def __init__(self, config):
        self.config = config
        self.run_id = None
        self.filepath = None
        self.handle = None
        self.last_tick_time = 0.0

    @staticmethod
    def _safe_name(value):
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
        return safe.strip("_") or "run"

    @staticmethod
    def _timestamp():
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def _write(self, payload):
        if not self.handle:
            return
        self.handle.write(json.dumps(payload) + "\n")
        self.handle.flush()

    def start_run(self, profile, startat, config_snapshot):
        if not self.config.history.enabled:
            return
        # calling this will clear the state in case anything is stale
        self.end_run("restart")

        os.makedirs(self.config.history.directory, exist_ok=True)
        timestamp = self._timestamp()
        profile_name = self._safe_name(profile.name)

        self.run_id = f"{timestamp}_{profile_name}"

        filename = f"{self.run_id}.jsonl"
        self.filepath = os.path.join(self.config.history.directory, filename)
        self.handle = open(self.filepath, "a", encoding="utf-8")
        self.last_tick_time = 0.0
        self._write({
            "type": "start",
            "run_id": self.run_id,
            "timestamp": timestamp,
            "profile": profile.name,
            "profile_data": profile.data,
            "startat_minutes": startat,
            "config": config_snapshot,
        })

    def append_tick(self, state):
        if not self.config.history.enabled or not self.handle:
            return
        now = time.time()
        if (now - self.last_tick_time) < self.config.history.tick_seconds:
            return
        self.last_tick_time = now
        payload = dict(state)
        payload["type"] = "tick"
        payload["run_id"] = self.run_id
        self._write(payload)

    def end_run(self, reason):
        if not self.config.history.enabled or not self.handle:
            self.run_id = None
            self.filepath = None
            self.handle = None
            self.last_tick_time = 0.0
            return
        timestamp = self._timestamp()
        self._write({
            "type": "end",
            "run_id": self.run_id,
            "timestamp": timestamp,
            "reason": reason,
        })
        try:
            self.handle.close()
        except Exception:
            log.exception("failed to close history file")
        self.run_id = None
        self.filepath = None
        self.handle = None
        self.last_tick_time = 0.0
