#!/usr/bin/env python

import os
import sys
import time
import logging
import json
import subprocess
import fcntl

def _apply_config_override(argv):
    if "--config" not in argv:
        return
    idx = argv.index("--config")
    if idx + 1 >= len(argv):
        print("error: --config requires a path")
        raise SystemExit(2)
    # Apply before importing CONFIG so config.py picks up the override.
    os.environ["KILN_CONFIG"] = argv[idx + 1]
    del argv[idx:idx + 2]


_apply_config_override(sys.argv)

import bottle
from gevent.pywsgi import WSGIServer
from geventwebsocket.handler import WebSocketHandler
from geventwebsocket import WebSocketError
from bottle import abort

from config import CONFIG
from lib.oven import SimulatedOven, RealOven
from lib.controller import ControllerService
from lib.ovenWatcher import OvenWatcher

logging.basicConfig(level=CONFIG.logging.level, format=CONFIG.logging.format)
log = logging.getLogger("kiln-controller")
log.info("Starting kiln controller")

script_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, script_dir)
profile_path = CONFIG.profiles.kiln_profiles_directory

_lock_handle = None


def acquire_lock():
    global _lock_handle
    lock_path = CONFIG.server.lock_file
    lock_dir = os.path.dirname(lock_path)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
    _lock_handle = open(lock_path, "a+")
    try:
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.error("kiln controller already running (lock: %s)", lock_path)
        sys.exit(1)
    _lock_handle.seek(0)
    _lock_handle.truncate()
    _lock_handle.write(str(os.getpid()))
    _lock_handle.flush()

def create_app(oven, controller, ovenWatcher):
    app = bottle.Bottle()

    @app.route('/')
    def index():
        return bottle.template('index')

    @app.route('/state')
    def state():
        return bottle.template('state')

    @app.get('/api/stats')
    def handle_api_stats():
        log.info("/api/stats command received")
        if hasattr(oven, 'pid') and hasattr(oven.pid, 'pidstats'):
            return json.dumps(oven.pid.pidstats)

    @app.get('/api/history')
    def handle_history_list():
        log.info("/api/history command received")
        history_dir = CONFIG.history.directory
        if not CONFIG.history.enabled:
            return json.dumps({"enabled": False, "runs": []})
        try:
            files = [f for f in os.listdir(history_dir) if f.endswith(".jsonl")]
        except FileNotFoundError:
            files = []
        files.sort(reverse=True)
        return json.dumps({"enabled": True, "runs": files})

    @app.get('/api/history/<run_id>')
    def handle_history_run(run_id):
        log.info("/api/history/%s command received" % run_id)
        if not CONFIG.history.enabled:
            return abort(404, "history disabled")
        if not run_id.endswith(".jsonl"):
            run_id = run_id + ".jsonl"
        safe_name = os.path.basename(run_id)
        history_dir = CONFIG.history.directory
        filepath = os.path.join(history_dir, safe_name)
        if not os.path.isfile(filepath):
            return abort(404, "history not found")
        return bottle.static_file(safe_name, root=history_dir, mimetype="application/x-ndjson")

    @app.post('/api')
    def handle_api():
        log.info("/api is alive")
        payload = bottle.request.json
        if not isinstance(payload, dict) or 'cmd' not in payload:
            # Guard against malformed or empty JSON to avoid server errors.
            return { "success": False, "error": "invalid request" }

        if payload['cmd'] == 'run':
            if not controller.validate_pin(payload.get('pin')):
                return { "success" : False, "error" : "invalid pin" }
            wanted = payload['profile']
            log.info('api requested run of profile = %s' % wanted)

            startat = 0
            if 'startat' in payload:
                startat = payload['startat']

            allow_seek = True
            if startat > 0:
                allow_seek = False

            ok, err = controller.run_profile_by_name(wanted, startat=startat, allow_seek=allow_seek)
            if not ok:
                return { "success": False, "error": err }
            return { "success": True }

        if payload['cmd'] == 'pause':
            log.info("api pause command received")
            controller.pause()

        if payload['cmd'] == 'resume':
            log.info("api resume command received")
            controller.resume()

        if payload['cmd'] == 'stop':
            log.info("api stop command received")
            controller.stop()

        if payload['cmd'] == 'shutdown':
            log.info("api shutdown command received")
            ok, err = controller.shutdown(payload.get('pin'))
            if not ok:
                return { "success" : False, "error" : err }
            return { "success" : True }

        if payload['cmd'] == 'memo':
            log.info("api memo command received")
            memo = payload['memo']
            log.info("memo=%s" % (memo))

        if payload['cmd'] == 'stats':
            log.info("api stats command received")
            if hasattr(oven, 'pid') and hasattr(oven.pid, 'pidstats'):
                return json.dumps(oven.pid.pidstats)

        return { "success" : True }

    @app.route('/assets/<filename:path>')
    def send_assets(filename):
        log.debug("serving asset %s" % filename)
        return bottle.static_file(
            filename,
            root=os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), "public", "assets"),
        )

    def get_profiles():
        return json.dumps(controller.get_profiles())

    def save_profile(profile, force=False):
        return controller.save_profile(profile, force)

    def delete_profile(profile):
        return controller.delete_profile(profile)

    def get_config():
        return json.dumps({
            "temp_scale": CONFIG.run.temp_scale,
            "time_scale_slope": CONFIG.run.time_scale_slope,
            "time_scale_profile": CONFIG.run.time_scale_profile,
            "kwh_rate": CONFIG.cost.kwh_rate,
            "currency_type": CONFIG.cost.currency_type,
            "kiln_name": CONFIG.ui.kiln_name,
        })

    @app.route('/control')
    def handle_control():
        wsock = get_websocket_from_request()
        log.info("websocket (control) opened")
        while True:
            try:
                message = wsock.receive()
                if message:
                    log.info("Received (control): %s" % message)
                    try:
                        msgdict = json.loads(message)
                    except json.JSONDecodeError:
                        # Bad input should not crash the websocket loop.
                        wsock.send(json.dumps({"resp": "FAIL", "error": "invalid json"}))
                        continue
                    if msgdict.get("cmd") == "RUN":
                        log.info("RUN command received")
                        if not controller.validate_pin(msgdict.get("pin")):
                            wsock.send(json.dumps({"resp": "FAIL", "error": "invalid pin"}))
                            continue
                        profile_obj = msgdict.get('profile')
                        if profile_obj:
                            ok, err = controller.run_profile(profile_obj)
                            if not ok:
                                wsock.send(json.dumps({"resp": "FAIL", "error": err}))
                                continue
                        else:
                            log.error("RUN command missing profile")
                            continue
                    elif msgdict.get("cmd") == "SIMULATE":
                        log.info("SIMULATE command received")
                    elif msgdict.get("cmd") == "STOP":
                        log.info("Stop command received")
                        controller.stop()
                    elif msgdict.get("cmd") == "SHUTDOWN":
                        log.info("Shutdown command received")
                        ok, err = controller.shutdown(msgdict.get("pin"))
                        if not ok:
                            wsock.send(json.dumps({"resp": "FAIL", "error": err}))
                            continue
                        wsock.send(json.dumps({"resp": "OK"}))
                    elif msgdict.get("cmd") == "SHUTDOWN_CHECK":
                        ok, err = can_shutdown()
                        if not ok:
                            wsock.send(json.dumps({"resp": "FAIL", "cmd": "SHUTDOWN_CHECK", "error": err}))
                            continue
                        wsock.send(json.dumps({"resp": "OK", "cmd": "SHUTDOWN_CHECK"}))
                time.sleep(1)
            except WebSocketError as e:
                log.error(e)
                break
        log.info("websocket (control) closed")

    @app.route('/storage')
    def handle_storage():
        wsock = get_websocket_from_request()
        log.info("websocket (storage) opened")
        while True:
            try:
                message = wsock.receive()
                if not message:
                    break
                log.debug("websocket (storage) received: %s" % message)

                try:
                    msgdict = json.loads(message)
                except Exception:
                    msgdict = {}

                if message == "GET":
                    log.info("GET command received")
                    wsock.send(get_profiles())
                elif msgdict.get("cmd") == "DELETE":
                    log.info("DELETE command received")
                    profile_obj = msgdict.get('profile')
                    ok, err = delete_profile(profile_obj)
                    if ok:
                        msgdict["resp"] = "OK"
                    else:
                        # Let the client know the delete failed so UI can surface it.
                        msgdict["resp"] = "FAIL"
                        if err:
                            msgdict["error"] = err
                    wsock.send(json.dumps(msgdict))
                elif msgdict.get("cmd") == "PUT":
                    log.info("PUT command received")
                    profile_obj = msgdict.get('profile')
                    force = True
                    if profile_obj:
                        ok, err = save_profile(profile_obj, force)
                        if ok:
                            msgdict["resp"] = "OK"
                        else:
                            # Let the client know the save failed so UI can surface it.
                            msgdict["resp"] = "FAIL"
                            if err:
                                msgdict["error"] = err
                        log.debug("websocket (storage) sent: %s" % message)

                        wsock.send(json.dumps(msgdict))
                        wsock.send(get_profiles())
                time.sleep(1)
            except WebSocketError:
                break
        log.info("websocket (storage) closed")

    @app.route('/config')
    def handle_config():
        wsock = get_websocket_from_request()
        log.info("websocket (config) opened")
        while True:
            try:
                message = wsock.receive()
                wsock.send(get_config())
            except WebSocketError:
                break
            time.sleep(1)
        log.info("websocket (config) closed")

    @app.route('/status')
    def handle_status():
        wsock = get_websocket_from_request()
        ovenWatcher.add_observer(wsock)
        log.info("websocket (status) opened")
        while True:
            try:
                message = wsock.receive()
                wsock.send("Your message was: %r" % message)
            except WebSocketError:
                break
            time.sleep(1)
        log.info("websocket (status) closed")

    return app



def get_websocket_from_request():
    env = bottle.request.environ
    wsock = env.get('wsgi.websocket')
    if not wsock:
        abort(400, 'Expected WebSocket request.')
    return wsock


def request_shutdown():
    try:
        subprocess.run(
            ["sudo", "-n", "shutdown", "-h", "+1", "kiln-controller shutdown"],
            check=True,
            capture_output=True,
            text=True,
        )
        return True, None
    except subprocess.CalledProcessError as exc:
        err = exc.stderr.strip() if exc.stderr else "shutdown failed"
        return False, err


def can_shutdown():
    try:
        candidates = ["shutdown", "/sbin/shutdown", "/usr/sbin/shutdown"]
        last_err = None
        for cmd in candidates:
            try:
                subprocess.run(
                    ["sudo", "-n", "-l", cmd],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return True, None
            except subprocess.CalledProcessError as exc:
                last_err = exc.stderr.strip() or exc.stdout.strip() or "shutdown not permitted"
        return False, last_err or "shutdown not permitted"
    except FileNotFoundError:
        return False, "sudo not available"


def build_runtime():
    if CONFIG.simulation.simulate:
        log.info("SIMULATION KILN")
        oven = SimulatedOven()
    else:
        log.info("LIVE KILN")
        oven = RealOven()

    controller = ControllerService(oven, profile_path, can_shutdown, request_shutdown)
    ovenWatcher = OvenWatcher(oven)
    app = create_app(oven, controller, ovenWatcher)
    return app

def main():
    acquire_lock()
    ip = "0.0.0.0"
    port = CONFIG.server.listening_port
    log.info("listening on %s:%d" % (ip, port))

    app = build_runtime()
    server = WSGIServer((ip, port), app,
                        handler_class=WebSocketHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
