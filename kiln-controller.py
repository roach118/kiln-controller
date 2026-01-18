#!/usr/bin/env python

import time
import os
import sys
import logging
import json
import subprocess

import bottle
import gevent
import geventwebsocket
#from bottle import post, get
from gevent.pywsgi import WSGIServer
from geventwebsocket.handler import WebSocketHandler
from geventwebsocket import WebSocketError
from bottle import abort

# try/except removed here on purpose so folks can see why things break
from config import CONFIG

logging.basicConfig(level=CONFIG.logging.level, format=CONFIG.logging.format)
log = logging.getLogger("kiln-controller")
log.info("Starting kiln controller")

script_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, script_dir + '/lib/')
profile_path = CONFIG.profiles.kiln_profiles_directory

from oven import SimulatedOven, RealOven, Profile
from ovenWatcher import OvenWatcher

app = bottle.Bottle()

if CONFIG.simulation.simulate == True:
    log.info("this is a simulation")
    oven = SimulatedOven()
else:
    log.info("this is a real kiln")
    oven = RealOven()
ovenWatcher = OvenWatcher(oven)
# this ovenwatcher is used in the oven class for restarts
oven.set_ovenwatcher(ovenWatcher)

@app.route('/')
def index():
    return bottle.redirect('/picoreflow/index.html')

@app.route('/state')
def state():
    return bottle.redirect('/picoreflow/state.html')

@app.get('/api/stats')
def handle_api():
    log.info("/api/stats command received")
    if hasattr(oven,'pid'):
        if hasattr(oven.pid,'pidstats'):
            return json.dumps(oven.pid.pidstats)


@app.post('/api')
def handle_api():
    log.info("/api is alive")


    # run a kiln schedule
    if bottle.request.json['cmd'] == 'run':
        if not validate_pin(bottle.request.json.get('pin')):
            return { "success" : False, "error" : "invalid pin" }
        wanted = bottle.request.json['profile']
        log.info('api requested run of profile = %s' % wanted)

        # start at a specific minute in the schedule
        # for restarting and skipping over early parts of a schedule
        startat = 0;      
        if 'startat' in bottle.request.json:
            startat = bottle.request.json['startat']

        #Shut off seek if start time has been set
        allow_seek = True
        if startat > 0:
            allow_seek = False

        # get the wanted profile/kiln schedule
        profile = find_profile(wanted)
        if profile is None:
            return { "success" : False, "error" : "profile %s not found" % wanted }

        # FIXME juggling of json should happen in the Profile class
        profile_json = json.dumps(profile)
        profile = Profile(profile_json)
        oven.run_profile(profile, startat=startat, allow_seek=allow_seek)
        ovenWatcher.record(profile)

    if bottle.request.json['cmd'] == 'pause':
        log.info("api pause command received")
        oven.state = 'PAUSED'

    if bottle.request.json['cmd'] == 'resume':
        log.info("api resume command received")
        oven.state = 'RUNNING'

    if bottle.request.json['cmd'] == 'stop':
        log.info("api stop command received")
        oven.abort_run()

    if bottle.request.json['cmd'] == 'shutdown':
        log.info("api shutdown command received")
        if not validate_pin(bottle.request.json.get('pin')):
            return { "success" : False, "error" : "invalid pin" }
        if oven.state != 'IDLE':
            return { "success" : False, "error" : "kiln must be idle to shutdown" }
        ok, err = request_shutdown()
        if not ok:
            return { "success" : False, "error" : err }
        return { "success" : True }

    if bottle.request.json['cmd'] == 'memo':
        log.info("api memo command received")
        memo = bottle.request.json['memo']
        log.info("memo=%s" % (memo))

    # get stats during a run
    if bottle.request.json['cmd'] == 'stats':
        log.info("api stats command received")
        if hasattr(oven,'pid'):
            if hasattr(oven.pid,'pidstats'):
                return json.dumps(oven.pid.pidstats)

    return { "success" : True }

def find_profile(wanted):
    '''
    given a wanted profile name, find it and return the parsed
    json profile object or None.
    '''
    #load all profiles from disk
    profiles = get_profiles()
    json_profiles = json.loads(profiles)

    # find the wanted profile
    for profile in json_profiles:
        if profile['name'] == wanted:
            return profile
    return None

@app.route('/picoreflow/:filename#.*#')
def send_static(filename):
    log.debug("serving %s" % filename)
    return bottle.static_file(filename, root=os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), "public"))


def get_websocket_from_request():
    env = bottle.request.environ
    wsock = env.get('wsgi.websocket')
    if not wsock:
        abort(400, 'Expected WebSocket request.')
    return wsock


def validate_pin(pin):
    try:
        return int(pin) == int(CONFIG.security.pin)
    except (TypeError, ValueError):
        return False


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


@app.route('/control')
def handle_control():
    wsock = get_websocket_from_request()
    log.info("websocket (control) opened")
    while True:
        try:
            message = wsock.receive()
            if message:
                log.info("Received (control): %s" % message)
                msgdict = json.loads(message)
                if msgdict.get("cmd") == "RUN":
                    log.info("RUN command received")
                    if not validate_pin(msgdict.get("pin")):
                        wsock.send(json.dumps({"resp": "FAIL", "error": "invalid pin"}))
                        continue
                    profile_obj = msgdict.get('profile')
                    if profile_obj:
                        profile_json = json.dumps(profile_obj)
                        profile = Profile(profile_json)
                    else:
                        log.error("RUN command missing profile")
                        continue
                    oven.run_profile(profile)
                    ovenWatcher.record(profile)
                elif msgdict.get("cmd") == "SIMULATE":
                    log.info("SIMULATE command received")
                    #profile_obj = msgdict.get('profile')
                    #if profile_obj:
                    #    profile_json = json.dumps(profile_obj)
                    #    profile = Profile(profile_json)
                    #simulated_oven = Oven(simulate=True, time_step=0.05)
                    #simulation_watcher = OvenWatcher(simulated_oven)
                    #simulation_watcher.add_observer(wsock)
                    #simulated_oven.run_profile(profile)
                    #simulation_watcher.record(profile)
                elif msgdict.get("cmd") == "STOP":
                    log.info("Stop command received")
                    oven.abort_run()
                elif msgdict.get("cmd") == "SHUTDOWN":
                    log.info("Shutdown command received")
                    if not validate_pin(msgdict.get("pin")):
                        wsock.send(json.dumps({"resp": "FAIL", "error": "invalid pin"}))
                        continue
                    if oven.state != "IDLE":
                        wsock.send(json.dumps({"resp": "FAIL", "error": "kiln must be idle to shutdown"}))
                        continue
                    ok, err = request_shutdown()
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
            except:
                msgdict = {}

            if message == "GET":
                log.info("GET command received")
                wsock.send(get_profiles())
            elif msgdict.get("cmd") == "DELETE":
                log.info("DELETE command received")
                profile_obj = msgdict.get('profile')
                if delete_profile(profile_obj):
                  msgdict["resp"] = "OK"
                wsock.send(json.dumps(msgdict))
                #wsock.send(get_profiles())
            elif msgdict.get("cmd") == "PUT":
                log.info("PUT command received")
                profile_obj = msgdict.get('profile')
                #force = msgdict.get('force', False)
                force = True
                if profile_obj:
                    #del msgdict["cmd"]
                    if save_profile(profile_obj, force):
                        msgdict["resp"] = "OK"
                    else:
                        msgdict["resp"] = "FAIL"
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


def get_profiles():
    try:
        profile_files = os.listdir(profile_path)
    except:
        profile_files = []
    profiles = []
    for filename in profile_files:
        with open(os.path.join(profile_path, filename), 'r') as f:
            profiles.append(json.load(f))
    return json.dumps(profiles)


def save_profile(profile, force=False):
    profile_json = json.dumps(profile)
    filename = profile['name']+".json"
    filepath = os.path.join(profile_path, filename)
    if not force and os.path.exists(filepath):
        log.error("Could not write, %s already exists" % filepath)
        return False
    with open(filepath, 'w+') as f:
        f.write(profile_json)
        f.close()
    log.info("Wrote %s" % filepath)
    return True

def delete_profile(profile):
    profile_json = json.dumps(profile)
    filename = profile['name']+".json"
    filepath = os.path.join(profile_path, filename)
    os.remove(filepath)
    log.info("Deleted %s" % filepath)
    return True

def get_config():
    return json.dumps({"temp_scale": CONFIG.run.temp_scale,
        "time_scale_slope": CONFIG.run.time_scale_slope,
        "time_scale_profile": CONFIG.run.time_scale_profile,
        "kwh_rate": CONFIG.cost.kwh_rate,
        "currency_type": CONFIG.cost.currency_type})    

def main():
    ip = "0.0.0.0"
    port = CONFIG.server.listening_port
    log.info("listening on %s:%d" % (ip, port))

    server = WSGIServer((ip, port), app,
                        handler_class=WebSocketHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
