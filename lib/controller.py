import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

from config import CONFIG
from .profile import Profile

log = logging.getLogger(__name__)


class ControllerService:
    def __init__(self, oven, profile_path, can_shutdown_fn, request_shutdown_fn):
        self.oven = oven
        self.profile_path = profile_path
        self.can_shutdown = can_shutdown_fn
        self.request_shutdown = request_shutdown_fn

    def validate_pin(self, pin) -> bool:
        try:
            return int(pin) == int(CONFIG.security.pin)
        except (TypeError, ValueError):
            return False

    def get_profiles(self) -> list:
        try:
            profile_files = os.listdir(self.profile_path)
        except Exception:
            profile_files = []
        profiles = []
        for filename in profile_files:
            with open(os.path.join(self.profile_path, filename), 'r') as f:
                profiles.append(json.load(f))
        return profiles

    def find_profile(self, wanted: str) -> Optional[Dict[str, Any]]:
        profiles = self.get_profiles()
        for profile in profiles:
            if profile.get('name') == wanted:
                return profile
        return None

    def validate_profile(self, profile_obj: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        profile_json = json.dumps(profile_obj)
        try:
            Profile(profile_json)
        except ValueError as exc:
            log.error("profile validation failed: %s", exc)
            return False, str(exc)
        return True, None

    def save_profile(self, profile_obj: Dict[str, Any], force: bool = False) -> Tuple[bool, Optional[str]]:
        ok, err = self.validate_profile(profile_obj)
        if not ok:
            return False, err
        filename = profile_obj['name'] + ".json"
        if "/" in filename or "\\" in filename:
            log.error("profile name contains path separators")
            return False, "profile name contains invalid characters"
        filepath = os.path.join(self.profile_path, filename)
        if not force and os.path.exists(filepath):
            log.error("Could not write, %s already exists", filepath)
            return False, "profile already exists"
        with open(filepath, 'w+') as f:
            f.write(json.dumps(profile_obj))
        log.info("Wrote %s", filepath)
        return True, None

    def delete_profile(self, profile_obj: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        filename = profile_obj['name'] + ".json"
        filepath = os.path.join(self.profile_path, filename)
        try:
            os.remove(filepath)
            log.info("Deleted %s", filepath)
            return True, None
        except FileNotFoundError:
            return False, "profile not found"
        except Exception as exc:
            log.exception("Failed to delete %s", filepath)
            return False, str(exc)

    def run_profile(self, profile_obj: Dict[str, Any], startat: float = 0, allow_seek: bool = True) -> Tuple[bool, Optional[str]]:
        if self.oven.state in ("RUNNING", "PAUSED"):
            return False, "kiln already running"
        profile_json = json.dumps(profile_obj)
        try:
            profile = Profile(profile_json)
        except ValueError as exc:
            log.error("profile validation failed: %s", exc)
            return False, str(exc)
        self.oven.run_profile(profile, startat=startat, allow_seek=allow_seek)
        return True, None

    def run_profile_by_name(self, name: str, startat: float = 0, allow_seek: bool = True) -> Tuple[bool, Optional[str]]:
        profile_obj = self.find_profile(name)
        if profile_obj is None:
            return False, f"profile {name} not found"
        return self.run_profile(profile_obj, startat=startat, allow_seek=allow_seek)

    def pause(self) -> None:
        # Avoid a race with the oven run loop by holding the state lock.
        state_lock = getattr(self.oven, "state_lock", None)
        if state_lock:
            with state_lock:
                self.oven.state = 'PAUSED'
        else:
            self.oven.state = 'PAUSED'

    def resume(self) -> None:
        # Avoid a race with the oven run loop by holding the state lock.
        state_lock = getattr(self.oven, "state_lock", None)
        if state_lock:
            with state_lock:
                self.oven.state = 'RUNNING'
        else:
            self.oven.state = 'RUNNING'

    def stop(self) -> None:
        self.oven.abort_run()

    def shutdown(self, pin) -> Tuple[bool, Optional[str]]:
        if not self.validate_pin(pin):
            return False, "invalid pin"
        if self.oven.state != 'IDLE':
            return False, "kiln must be idle to shutdown"
        ok, err = self.request_shutdown()
        if not ok:
            return False, err
        return True, None
