import threading,logging,json,time,datetime
import config
from oven import Oven
log = logging.getLogger(__name__)

class OvenWatcher(threading.Thread):
    def __init__(self,oven):
        self.last_profile = None
        self.last_log = []
        self.started = None
        self.recording = False
        self.observers = []
        self.observers_lock = threading.Lock()
        threading.Thread.__init__(self)
        self.daemon = True
        self.oven = oven
        self.start()

# FIXME - need to save runs of schedules in near-real-time
# FIXME - this will enable re-start in case of power outage
# FIXME - re-start also requires safety start (pausing at the beginning
# until a temp is reached)
# FIXME - re-start requires a time setting in minutes.  if power has been
# out more than N minutes, don't restart
# FIXME - this should not be done in the Watcher, but in the Oven class

    def run(self):
        while True:
            oven_state = self.convert_state_for_display(self.oven.get_state())
           
            # record state for any new clients that join
            if oven_state.get("state") == "RUNNING":
                self.last_log.append(oven_state)
            else:
                self.recording = False
            self.notify_all(oven_state)
            time.sleep(self.oven.time_step)

    def lastlog_subset(self,maxpts=50):
        '''send about maxpts from lastlog by skipping unwanted data'''
        totalpts = len(self.last_log)
        if (totalpts <= maxpts):
            return self.last_log
        every_nth = int(totalpts / (maxpts - 1))
        return self.last_log[::every_nth]

    def record(self, profile):
        self.last_profile = profile
        self.last_log = []
        self.started = datetime.datetime.now()
        self.recording = True
        #we just turned on, add first state for nice graph
        self.last_log.append(self.convert_state_for_display(self.oven.get_state()))

    def add_observer(self,observer):
        if self.last_profile:
            p = {
                "name": self.last_profile.name,
                "data": self.last_profile.data, 
                "type" : "profile"
            }
            p = self.convert_profile_for_display(p)
        else:
            p = None
        
        backlog = {
            'type': "backlog",
            'profile': p,
            'log': self.lastlog_subset(),
            #'started': self.started
        }
        print(backlog)
        backlog_json = json.dumps(backlog)
        try:
            print(backlog_json)
            observer.send(backlog_json)
        except:
            log.error("Could not send backlog to new observer")

        with self.observers_lock:
            self.observers.append(observer)

    def notify_all(self,message):
        message_json = json.dumps(message)
        log.debug("sending to %d clients: %s"%(len(self.observers),message_json))

        with self.observers_lock:
            observers = list(self.observers)
        for wsock in observers:
            if wsock:
                try:
                    wsock.send(message_json)
                except:
                    log.error("could not write to socket %s"%wsock)
                    with self.observers_lock:
                        if wsock in self.observers:
                            self.observers.remove(wsock)
            else:
                with self.observers_lock:
                    if wsock in self.observers:
                        self.observers.remove(wsock)

    def convert_state_for_display(self, state):
        if config.temp_scale.lower() != "f":
            return state

        converted = dict(state)
        for key in ("temperature", "target"):
            if key in converted:
                converted[key] = c_to_f(converted[key])
        if "heat_rate" in converted:
            converted["heat_rate"] = c_delta_to_f(converted["heat_rate"])
        if "pidstats" in converted and converted["pidstats"]:
            pidstats = dict(converted["pidstats"])
            for key in ("setpoint", "ispoint"):
                if key in pidstats:
                    pidstats[key] = c_to_f(pidstats[key])
            for key in ("err", "errDelta"):
                if key in pidstats:
                    pidstats[key] = c_delta_to_f(pidstats[key])
            converted["pidstats"] = pidstats
        return converted

    def convert_profile_for_display(self, profile):
        if config.temp_scale.lower() != "f":
            return profile
        converted = dict(profile)
        converted["data"] = [[secs, c_to_f(temp)] for secs, temp in profile["data"]]
        converted["temp_units"] = "f"
        return converted


def c_to_f(temp):
    return (temp * 9 / 5) + 32


def c_delta_to_f(temp):
    return temp * 9 / 5
