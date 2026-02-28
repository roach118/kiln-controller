import threading,logging,json,time,datetime
from collections import deque
from config import CONFIG
try:
    from .oven import Oven
except ImportError:
    from oven import Oven
log = logging.getLogger(__name__)

class OvenWatcher(threading.Thread):
    def __init__(self,oven):
        self.last_profile = None
        self.last_log = deque(maxlen=CONFIG.run.backlog_max_points)
        self.started = None
        self.recording = False
        self.last_state = None
        self.last_profile_name = None
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
            oven_state = self.oven.get_state()
            state = oven_state.get("state")
            profile_name = oven_state.get("profile")

            if self.last_state != "RUNNING" and state == "RUNNING":
                self.last_log = deque(maxlen=CONFIG.run.backlog_max_points)
                self.started = datetime.datetime.now()
                self.recording = True
            if self.last_profile_name != profile_name and profile_name:
                self.last_log = deque(maxlen=CONFIG.run.backlog_max_points)
                self.started = datetime.datetime.now()
                self.recording = state == "RUNNING"

            # record state for any new clients that join
            if state == "RUNNING":
                self.last_log.append(oven_state)
            else:
                self.recording = False
            self.notify_all(oven_state)
            self.last_state = state
            self.last_profile_name = profile_name
            time.sleep(self.oven.time_step)

    def lastlog_subset(self,maxpts=50):
        '''send about maxpts from lastlog by skipping unwanted data'''
        last_log = list(self.last_log)
        totalpts = len(last_log)
        if (totalpts <= maxpts):
            return last_log
        last_runtime = last_log[-1].get("runtime")
        if last_runtime is None:
            every_nth = int(totalpts / (maxpts - 1))
            return last_log[::every_nth]

        recent_cutoff = last_runtime - CONFIG.run.backlog_older_window_seconds
        older_interval = CONFIG.run.backlog_older_sample_seconds
        older_selected = []
        recent_selected = []
        last_older_runtime = None

        for entry in last_log:
            runtime = entry.get("runtime")
            if runtime is None:
                continue
            if runtime < recent_cutoff:
                if last_older_runtime is None or (runtime - last_older_runtime) >= older_interval:
                    older_selected.append(entry)
                    last_older_runtime = runtime
            else:
                recent_selected.append(entry)

        return older_selected + recent_selected

    def record(self, profile):
        self.last_profile = profile
        self.last_log = deque(maxlen=CONFIG.run.backlog_max_points)
        self.started = datetime.datetime.now()
        self.recording = True
        #we just turned on, add first state for nice graph
        self.last_log.append(self.oven.get_state())

    def add_observer(self,observer):
        if self.last_profile:
            p = {
                "name": self.last_profile.name,
                "data": self.last_profile.data, 
                "type" : "profile"
            }
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
