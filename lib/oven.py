import threading
import time
import datetime
import logging
import json
import atexit
from config import CONFIG
import os
import digitalio
import busio
import adafruit_bitbangio as bitbangio
import statistics
from lib.history import HistoryLogger
from lib.profile import Profile

log = logging.getLogger(__name__)
SSR_TRANSITION_TIME = None

class DupFilter(object):
    def __init__(self):
        self.msgs = set()

    def filter(self, record):
        rv = record.msg not in self.msgs
        self.msgs.add(record.msg)
        return rv

class Duplogger():
    def __init__(self):
        self.log = logging.getLogger("%s.dupfree" % (__name__))
        dup_filter = DupFilter()
        self.log.addFilter(dup_filter)
    def logref(self):
        return self.log

duplog = Duplogger().logref()

class Output(object):
    '''This represents a GPIO output that controls a solid
    state relay to turn the kiln elements on and off.
    inputs
        CONFIG.hardware.gpio_heat
        CONFIG.hardware.gpio_heat_invert
    '''
    def __init__(self):
        self.active = False
        self.heater = digitalio.DigitalInOut(CONFIG.hardware.gpio_heat)
        self.heater.direction = digitalio.Direction.OUTPUT 
        self.off = CONFIG.hardware.gpio_heat_invert
        self.on = not self.off
        self.heater.value = self.off
        self.current_value = self.off
        # Live hardware safety: ensure SSR off on process exit.
        atexit.register(self.safe_off)

    def set_output(self, value):
        self._set_output(value)

    def heat(self,sleepfor):
        self._set_output(self.on)
        time.sleep(sleepfor)

    def cool(self,sleepfor):
        '''no active cooling, so sleep'''
        self._set_output(self.off)
        time.sleep(sleepfor)

    def safe_off(self):
        '''live hardware safety: force SSR off without sleeping'''
        try:
            self._set_output(self.off)
        except Exception:
            log.exception("failed to force SSR off")

    def _set_output(self, value):
        global SSR_TRANSITION_TIME
        if value != self.current_value:
            self.heater.value = value
            self.current_value = value
            SSR_TRANSITION_TIME = time.time()
        else:
            self.heater.value = value

# wrapper for blinka board
class Board(object):
    '''This represents a blinka board where this code
    runs.
    '''
    def __init__(self):
        log.info("board: %s" % (self.name))
        self.temp_sensor.start()

class RealBoard(Board):
    '''Each board has a thermocouple board attached to it.
    Any blinka board that supports SPI can be used. The
    board is automatically detected by blinka.
    '''
    def __init__(self):
        self.name = None
        self.load_libs()
        self.temp_sensor = self.choose_tempsensor()
        Board.__init__(self) 

    def load_libs(self):
        import board
        self.name = board.board_id

    def choose_tempsensor(self):
        if CONFIG.thermocouple.max31855:
            return Max31855()
        if CONFIG.thermocouple.max31856:
            return Max31856()

class SimulatedBoard(Board):
    '''Simulated board used during simulations.
    See CONFIG.simulation.simulate
    '''
    def __init__(self):
        self.name = "simulated"
        self.temp_sensor = TempSensorSimulated()
        Board.__init__(self) 

class TempSensor(threading.Thread):
    '''Used by the Board class. Each Board must have
    a TempSensor.
    '''
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.time_step = CONFIG.run.sensor_time_wait
        self.status = ThermocoupleTracker()
        self.last_ok_time = None
        self.last_temp = None
        self.last_temp_time = None
        self.anomaly_window = []
        self.fatal_reason = None

    def _accept_temp(self, temp):
        # Shared ramp safety for both simulated and real sensors.
        max_ramp = CONFIG.run.temp_ramp_max_c_per_sec
        if max_ramp <= 0:
            return True
        now = time.time()
        if self.last_temp is None or self.last_temp_time is None:
            self.last_temp = temp
            self.last_temp_time = now
            self._record_anomaly(False)
            return True
        dt = now - self.last_temp_time
        if dt <= 0:
            self.last_temp = temp
            self.last_temp_time = now
            self._record_anomaly(False)
            return True
        ramp = abs(temp - self.last_temp) / dt
        if ramp > max_ramp:
            self._record_anomaly(True)
            log.warning("discarding temp reading: ramp %.2f C/s exceeds %.2f", ramp, max_ramp)
            return False
        self.last_temp = temp
        self.last_temp_time = now
        self._record_anomaly(False)
        return True

    def _record_anomaly(self, is_anomaly):
        window = CONFIG.run.temp_ramp_anomaly_window
        max_anomalies = CONFIG.run.temp_ramp_anomaly_max
        self.anomaly_window.append(is_anomaly)
        if len(self.anomaly_window) > window:
            self.anomaly_window = self.anomaly_window[-window:]
        if max_anomalies <= 0:
            return
        if sum(1 for entry in self.anomaly_window if entry) > max_anomalies:
            log.error("too many ramp anomalies; marking sensor fault")
            self.fatal_reason = "sensor_ramp_anomaly"

class TempSensorSimulated(TempSensor):
    '''Simulates a temperature sensor '''
    def __init__(self):
        TempSensor.__init__(self)
        self.simulated_temperature = CONFIG.simulation.t_env
    def temperature(self):
        temp = self.simulated_temperature
        self._accept_temp(temp)
        self.last_ok_time = time.time()
        self.status.good()
        return temp

class TempSensorReal(TempSensor):
    '''real temperature sensor that takes many measurements
       during the time_step
       inputs
           CONFIG.run.temperature_average_samples 
    '''
    def __init__(self):
        TempSensor.__init__(self)
        self.sleeptime = self.time_step / float(CONFIG.run.temperature_average_samples)
        self.temptracker = TempTracker() 
        self.spi_setup()
        self.cs = digitalio.DigitalInOut(CONFIG.hardware.spi_cs)

    def spi_setup(self):
        # Live hardware only: use configured SPI pins when available.
        if (CONFIG.hardware.spi_sclk is not None and
            CONFIG.hardware.spi_mosi is not None and
            CONFIG.hardware.spi_miso is not None):
            self.spi = bitbangio.SPI(CONFIG.hardware.spi_sclk, CONFIG.hardware.spi_mosi, CONFIG.hardware.spi_miso)
            log.info("Software SPI selected for reading thermocouple")
        else:
            import board
            self.spi = board.SPI();
            log.info("Hardware SPI selected for reading thermocouple")

    def get_temperature(self):
        '''read temp from tc'''
        # Live hardware only: ignore reads near SSR transitions.
        quiet_window = CONFIG.run.ssr_quiet_window_ms / 1000.0
        if quiet_window > 0 and SSR_TRANSITION_TIME:
            if 0 <= (time.time() - SSR_TRANSITION_TIME) <= quiet_window:
                return None
        try:
            temp = self.raw_temp() # raw_temp provided by subclasses
            if not self._accept_temp(temp):
                return None
            self.status.good()
            self.last_ok_time = time.time()
            return temp
        except ThermocoupleError as tce:
            if tce.ignore:
                log.error("Problem reading temp (ignored) %s" % (tce.message))
                self.status.good()
            else:
                log.error("Problem reading temp %s" % (tce.message))
                self.status.bad()
        return None

    def temperature(self):
        '''average temp over a duty cycle'''
        return self.temptracker.get_avg_temp()

    def run(self):
        while True:
            temp = self.get_temperature()
            if temp:
                self.temptracker.add(temp)
            time.sleep(self.sleeptime)

class TempTracker(object):
    '''creates a sliding window of N temperatures per
       CONFIG.run.sensor_time_wait
    '''
    def __init__(self):
        self.size = CONFIG.run.temperature_average_samples
        self.temps = [0 for i in range(self.size)]
  
    def add(self,temp):
        self.temps.append(temp)
        while(len(self.temps) > self.size):
            del self.temps[0]

    def get_avg_temp(self, chop=25):
        '''
        take the median of the given values. this used to take an avg
        after getting rid of outliers. median works better.
        '''
        return statistics.median(self.temps)

class ThermocoupleTracker(object):
    '''Keeps sliding window to track successful/failed calls to get temp
       over the last two duty cycles.
    '''
    def __init__(self):
        self.size = CONFIG.run.temperature_average_samples * 2 
        self.status = [True for i in range(self.size)]
        self.limit = 30

    def good(self):
        '''True is good!'''
        self.status.append(True)
        del self.status[0]

    def bad(self):
        '''False is bad!'''
        self.status.append(False)
        del self.status[0]

    def error_percent(self):
        errors = sum(i == False for i in self.status) 
        return (errors/self.size)*100

    def over_error_limit(self):
        if self.error_percent() > self.limit:
            return True
        return False

class Max31855(TempSensorReal):
    '''each subclass expected to handle errors and get temperature'''
    def __init__(self):
        TempSensorReal.__init__(self)
        log.info("thermocouple MAX31855")
        import adafruit_max31855
        self.thermocouple = adafruit_max31855.MAX31855(self.spi, self.cs)

    def raw_temp(self):
        try:
            return self.thermocouple.temperature_NIST
        except RuntimeError as rte:
            if rte.args and rte.args[0]:
                raise Max31855_Error(rte.args[0])
            raise Max31855_Error('unknown')

class ThermocoupleError(Exception):
    '''
    thermocouple exception parent class to handle mapping of error messages
    and make them consistent across adafruit libraries. Also set whether
    each exception should be ignored based on settings in CONFIG.py.
    '''
    def __init__(self, message):
        self.ignore = False
        self.message = message
        self.map_message()
        self.set_ignore()
        super().__init__(self.message)

    def set_ignore(self):
        if self.message == "not connected" and CONFIG.thermocouple.ignore_tc_lost_connection == True:
            self.ignore = True
        if self.message == "short circuit" and CONFIG.thermocouple.ignore_tc_short_errors == True:
            self.ignore = True
        if self.message == "unknown" and CONFIG.thermocouple.ignore_tc_unknown_error == True:
            self.ignore = True
        if self.message == "cold junction range fault" and CONFIG.thermocouple.ignore_tc_cold_junction_range_error == True:
            self.ignore = True
        if self.message == "thermocouple range fault" and CONFIG.thermocouple.ignore_tc_range_error == True:
            self.ignore = True
        if self.message == "cold junction temp too high" and CONFIG.thermocouple.ignore_tc_cold_junction_temp_high == True:
            self.ignore = True
        if self.message == "cold junction temp too low" and CONFIG.thermocouple.ignore_tc_cold_junction_temp_low == True:
            self.ignore = True
        if self.message == "thermocouple temp too high" and CONFIG.thermocouple.ignore_tc_temp_high == True:
            self.ignore = True
        if self.message == "thermocouple temp too low" and CONFIG.thermocouple.ignore_tc_temp_low == True:
            self.ignore = True
        if self.message == "voltage too high or low" and CONFIG.thermocouple.ignore_tc_voltage_error == True:
            self.ignore = True

    def map_message(self):
        try:
            self.message = self.map[self.orig_message]
        except KeyError:
            self.message = "unknown"

class Max31855_Error(ThermocoupleError):
    '''
    All children must set self.orig_message and self.map
    '''
    def __init__(self, message):
        self.orig_message = message
        # this purposefully makes "fault reading" and
        # "Total thermoelectric voltage out of range..." unknown errors
        self.map = {
            "thermocouple not connected" : "not connected",
            "short circuit to ground" : "short circuit",
            "short circuit to power" : "short circuit",
            }
        super().__init__(message)

class Max31856_Error(ThermocoupleError):
    def __init__(self, message):
        self.orig_message = message
        self.map = {
            "cj_range" : "cold junction range fault",
            "tc_range" : "thermocouple range fault",
            "cj_high"  : "cold junction temp too high",
            "cj_low"   : "cold junction temp too low",
            "tc_high"  : "thermocouple temp too high",
            "tc_low"   : "thermocouple temp too low",
            "voltage"  : "voltage too high or low", 
            "open_tc"  : "not connected"
            }
        super().__init__(message)

class Max31856(TempSensorReal):
    '''each subclass expected to handle errors and get temperature'''
    def __init__(self):
        TempSensorReal.__init__(self)
        log.info("thermocouple MAX31856")
        import adafruit_max31856
        self.thermocouple = adafruit_max31856.MAX31856(self.spi,self.cs,
                                        thermocouple_type=CONFIG.thermocouple.type)
        if (CONFIG.thermocouple.ac_freq_50hz == True):
            self.thermocouple.noise_rejection = 50
        else:
            self.thermocouple.noise_rejection = 60

    def raw_temp(self):
        # The underlying adafruit library does not throw exceptions
        # for thermocouple errors. Instead, they are stored in 
        # dict named self.thermocouple.fault. Here we check that
        # dict for errors and raise an exception.
        # and raise Max31856_Error(message)
        temp = self.thermocouple.temperature
        for k,v in self.thermocouple.fault.items():
            if v:
                raise Max31856_Error(k)
        return temp

class Oven(threading.Thread):
    '''parent oven class. this has all the common code
       for either a real or simulated oven'''
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.state_lock = threading.RLock()
        self.temperature = 0
        self.time_step = CONFIG.run.sensor_time_wait
        self.history = HistoryLogger(CONFIG)
        self.last_abort_reason = None
        self.reset()

    def reset(self):
        with self.state_lock:
            self.cost = 0
            self.heat_total_seconds = 0.0
            self.state = "IDLE"
            self.profile = None
            self.start_time = 0
            self.runtime = 0
            self.totaltime = 0
            self.target = 0
            self.heat = 0
            self.heat_rate = 0
            self.heat_rate_temps = []
            self.pid = PID(ki=CONFIG.pid.ki, kd=CONFIG.pid.kd, kp=CONFIG.pid.kp)
            self.catching_up = False
            self.heat_check_time = None
            self.heat_check_temp = None
            self.loop_last_tick = time.time()
            self.safe_start_time = None
            self.safe_start_good = 0
            self.temperature = 0
            sensor = getattr(self.board, "temp_sensor", None)
            if sensor:
                sensor.fatal_reason = None
                sensor.anomaly_window = []
                sensor.last_temp = None
                sensor.last_temp_time = None

    @staticmethod
    def get_start_from_temperature(profile, temp):
        target_temp = profile.get_target_temperature(0)
        if temp > target_temp + 5:
            startat = profile.find_next_time_from_temperature(temp)
            log.info("seek_start is in effect, starting at: {} s, {} deg".format(round(startat), round(temp)))
        else:
            startat = 0
        return startat

    def set_heat_rate(self,runtime,temp):
        '''heat rate is the heating rate in degrees/hour
        '''
        # arbitrary number of samples
        # the time this covers changes based on a few things
        numtemps = 60
        self.heat_rate_temps.append((runtime,temp))
         
        # drop old temps off the list
        if len(self.heat_rate_temps) > numtemps:
            self.heat_rate_temps = self.heat_rate_temps[-1*numtemps:]
        time2 = self.heat_rate_temps[-1][0]
        time1 = self.heat_rate_temps[0][0]
        temp2 = self.heat_rate_temps[-1][1]
        temp1 = self.heat_rate_temps[0][1]
        if time2 > time1:
            self.heat_rate = ((temp2 - temp1) / (time2 - time1))*3600

    def run_profile(self, profile, startat=0, allow_seek=True):
        log.debug('run_profile run on thread' + threading.current_thread().name)
        runtime = startat * 60
        if allow_seek:
            if self.state == 'IDLE':
                if CONFIG.run.seek_start:
                    temp = self.board.temp_sensor.temperature()  # Defined in a subclass
                    runtime += self.get_start_from_temperature(profile, temp)

        with self.state_lock:
            self.reset()
            self.startat = startat * 60
            self.runtime = runtime
            self.start_time = datetime.datetime.now() - datetime.timedelta(seconds=self.startat)
            self.profile = profile
            self.totaltime = profile.get_duration()
            self.state = "RUNNING"
            self.last_abort_reason = None
            self.safe_start_time = time.time()
            self.safe_start_good = 0
        log.info("Running schedule %s starting at %d minutes" % (profile.name,startat))
        log.info("Starting")
        self.history.start_run(profile, startat, self.get_history_config_snapshot())

    def abort_run(self, reason="aborted"):
        log.error("aborting run: %s", reason)
        with self.state_lock:
            self.last_abort_reason = reason
        self.history.end_run(reason)
        self.reset()
        self.save_automatic_restart_state()

    def get_start_time(self):
        return datetime.datetime.now() - datetime.timedelta(milliseconds = self.runtime * 1000)

    def kiln_must_catch_up(self):
        '''shift the whole schedule forward in time by one time_step
        to wait for the kiln to catch up'''
        if CONFIG.run.kiln_must_catch_up == True:
            temp = self.board.temp_sensor.temperature() + \
                CONFIG.run.thermocouple_offset
            # kiln too cold, wait for it to heat up
            if self.target - temp > CONFIG.run.pid_control_window:
                log.info("kiln must catch up, too cold, shifting schedule")
                self.start_time = self.get_start_time()
                self.catching_up = True;
                return
            # kiln too hot, wait for it to cool down
            if temp - self.target > CONFIG.run.pid_control_window:
                log.info("kiln must catch up, too hot, shifting schedule")
                self.start_time = self.get_start_time()
                self.catching_up = True;
                return
            self.catching_up = False;

    def update_runtime(self):

        runtime_delta = datetime.datetime.now() - self.start_time
        if runtime_delta.total_seconds() < 0:
            runtime_delta = datetime.timedelta(0)

        self.runtime = runtime_delta.total_seconds()

    def update_target_temp(self):
        self.target = self.profile.get_target_temperature(self.runtime)

    def reset_if_emergency(self):
        '''reset if the temperature is way TOO HOT, or other critical errors detected'''
        if (self.board.temp_sensor.temperature() + CONFIG.run.thermocouple_offset >=
            CONFIG.run.emergency_shutoff_temp):
            log.info("emergency!!! temperature too high")
            if CONFIG.run.ignore_temp_too_high == False:
                self.abort_run("emergency")
        
        if self.board.temp_sensor.status.over_error_limit():
            log.info("emergency!!! too many errors in a short period")
            if CONFIG.thermocouple.ignore_tc_too_many_errors == False:
                self.abort_run("emergency")

    def reset_if_schedule_ended(self):
        if self.runtime > self.totaltime:
            log.info("schedule ended, shutting down")
            log.info("total cost = %s%.2f" % (CONFIG.cost.currency_type,self.cost))
            self.abort_run("completed")

    def update_cost(self):
        if self.heat:
            cost = (CONFIG.cost.kwh_rate * CONFIG.cost.kw_elements) * ((self.heat)/3600)
        else:
            cost = 0
        self.cost = self.cost + cost
        self.heat_total_seconds += self.heat

    def get_state(self):
        with self.state_lock:
            state = {
                'cost': self.cost,
                'runtime': self.runtime,
                'temperature': self.temperature,
                'target': self.target,
                'state': self.state,
                'heat': self.heat,
                'heat_seconds': self.heat_total_seconds,
                'heat_rate': self.heat_rate,
                'totaltime': self.totaltime,
                'kwh_rate': CONFIG.cost.kwh_rate,
                'currency_type': CONFIG.cost.currency_type,
                'profile': self.profile.name if self.profile else None,
                'pidstats': self.pid.pidstats,
                'catching_up': self.catching_up,
                'abort_reason': self.last_abort_reason,
            }
        return state

    def get_history_config_snapshot(self):
        return {
            "temp_scale": CONFIG.run.temp_scale,
            "pid": {"kp": CONFIG.pid.kp, "ki": CONFIG.pid.ki, "kd": CONFIG.pid.kd},
            "safety": {
                "heating_stall_enabled": CONFIG.safety.heating_stall_enabled,
                "heating_stall_window_seconds": CONFIG.safety.heating_stall_window_seconds,
                "heating_stall_min_temp_rise": CONFIG.safety.heating_stall_min_temp_rise,
                "heating_stall_min_heater_output": CONFIG.safety.heating_stall_min_heater_output,
                "heating_stall_min_target_delta": CONFIG.safety.heating_stall_min_target_delta,
            },
        }

    def reset_heating_progress(self):
        self.heat_check_time = None
        self.heat_check_temp = None

    def check_sensor_stale(self):
        if self.state != "RUNNING":
            return
        timeout = CONFIG.run.sensor_stale_timeout_seconds
        if timeout <= 0:
            return
        last_ok = getattr(self.board.temp_sensor, "last_ok_time", None)
        if last_ok is None:
            return
        if (time.time() - last_ok) > timeout:
            log.error(
                "sensor stale for %.1fs (timeout %.1fs, last_ok=%s); aborting run",
                time.time() - last_ok,
                timeout,
                datetime.datetime.fromtimestamp(last_ok).isoformat(timespec="seconds"),
            )
            self.abort_run("sensor_stale")

    def check_sensor_faults(self):
        if self.state != "RUNNING":
            return
        reason = getattr(self.board.temp_sensor, "fatal_reason", None)
        if reason:
            log.error("sensor fault detected: %s", reason)
            self.abort_run(reason)

    def check_loop_watchdog(self):
        if self.state != "RUNNING":
            return
        timeout = CONFIG.run.loop_watchdog_timeout_seconds
        if timeout <= 0:
            return
        now = time.time()
        if (now - self.loop_last_tick) > timeout:
            log.error("control loop stalled for %.1fs; aborting run", now - self.loop_last_tick)
            self.abort_run("loop_stalled")

    def sleep_with_abort(self, duration):
        completed, _ = self.sleep_with_abort_elapsed(duration)
        return completed

    def sleep_with_abort_elapsed(self, duration):
        start = time.time()
        end = start + max(0, duration)
        while True:
            if self.state not in ("RUNNING", "PAUSED"):
                return False, time.time() - start
            remaining = end - time.time()
            if remaining <= 0:
                break
            time.sleep(min(0.1, remaining))
        return True, time.time() - start

    def safe_start_ready(self):
        required = CONFIG.run.safe_start_min_good_samples
        if required <= 0:
            return True
        timeout = CONFIG.run.safe_start_timeout_seconds
        if timeout > 0 and self.safe_start_time:
            if (time.time() - self.safe_start_time) > timeout:
                log.error("safe start timed out; aborting run")
                self.abort_run("safe_start_timeout")
                return False
        last_ok = getattr(self.board.temp_sensor, "last_ok_time", None)
        with self.state_lock:
            if last_ok and (time.time() - last_ok) <= CONFIG.run.sensor_time_wait * 2:
                self.safe_start_good += 1
            else:
                self.safe_start_good = 0
            return self.safe_start_good >= required

    def check_heating_progress(self, temp):
        if not CONFIG.safety.heating_stall_enabled:
            return
        if self.state != "RUNNING":
            self.reset_heating_progress()
            return
        pidstats = getattr(self.pid, "pidstats", {}) or {}
        heat_output = float(pidstats.get("out", 0))
        if heat_output < CONFIG.safety.heating_stall_min_heater_output:
            self.reset_heating_progress()
            return
        if (self.target - temp) < CONFIG.safety.heating_stall_min_target_delta:
            self.reset_heating_progress()
            return
        now = time.time()
        if self.heat_check_time is None:
            self.heat_check_time = now
            self.heat_check_temp = temp
            return
        if (now - self.heat_check_time) < CONFIG.safety.heating_stall_window_seconds:
            return
        delta = temp - self.heat_check_temp
        if delta < CONFIG.safety.heating_stall_min_temp_rise:
            log.error(
                "heating stalled: output %.2f, temp rise %.2fC over %.0fs"
                % (
                    heat_output,
                    delta,
                    CONFIG.safety.heating_stall_window_seconds,
                )
            )
            if not CONFIG.safety.ignore_heating_stall:
                self.abort_run()
            self.reset_heating_progress()
            return
        self.heat_check_time = now
        self.heat_check_temp = temp

    def save_state(self):
        with open(CONFIG.restart.automatic_restart_state_file, 'w', encoding='utf-8') as f:
            json.dump(self.get_state(), f, ensure_ascii=False, indent=4)

    def state_file_is_old(self):
        '''returns True is state files is older than 15 mins default
                   False if younger
                   True if state file cannot be opened or does not exist
        '''
        if os.path.isfile(CONFIG.restart.automatic_restart_state_file):
            state_age = os.path.getmtime(CONFIG.restart.automatic_restart_state_file)
            now = time.time()
            minutes = (now - state_age)/60
            if(minutes <= CONFIG.restart.automatic_restart_window):
                return False
        return True

    def save_automatic_restart_state(self):
        # only save state if the feature is enabled
        if not CONFIG.restart.automatic_restarts == True:
            return False
        self.save_state()

    def should_i_automatic_restart(self):
        # only automatic restart if the feature is enabled
        if not CONFIG.restart.automatic_restarts == True:
            return False
        if self.state_file_is_old():
            duplog.info("automatic restart not possible. state file does not exist or is too old.")
            return False

        try:
            with open(CONFIG.restart.automatic_restart_state_file) as infile:
                d = json.load(infile)
        except Exception as exc:
            # Avoid crashing the control loop if the state file is corrupt.
            duplog.info("automatic restart not possible; failed to read state file: %s", exc)
            return False
        if d["state"] != "RUNNING":
            duplog.info("automatic restart not possible. state = %s" % (d["state"]))
            return False
        return True

    def automatic_restart(self):
        try:
            with open(CONFIG.restart.automatic_restart_state_file) as infile:
                d = json.load(infile)
            startat = d["runtime"]/60
            filename = "%s.json" % (d["profile"])
            profile_path = os.path.abspath(os.path.join(os.path.dirname( __file__ ), '..', 'storage','profiles',filename))

            log.info("automatically restarting profile = %s at minute = %d" % (profile_path,startat))
            with open(profile_path) as infile:
                profile_json = json.dumps(json.load(infile))
            profile = Profile(profile_json)
            self.run_profile(profile, startat=startat, allow_seek=False)  # We don't want a seek on an auto restart.
            self.cost = d["cost"]
            time.sleep(1)
        except Exception:
            # Prevent corrupted restart state or missing profiles from crashing the loop.
            log.exception("automatic restart failed")

    def set_ovenwatcher(self,watcher):
        log.info("ovenwatcher set in oven class")
        self.ovenwatcher = watcher

    def run_iteration(self, sleep=True):
        log.debug('Oven running on ' + threading.current_thread().name)
        temp = self.read_temperature()
        history_snapshot = None
        with self.state_lock:
            self.loop_last_tick = time.time()
            temp_valid = temp is not None
            if not temp_valid:
                # If the sensor is missing, abort to avoid running blind.
                if self.state == "RUNNING":
                    self.abort_run("sensor_missing")
            else:
                self.temperature = temp
                self.set_heat_rate(self.runtime, temp)
            if self.state == "RUNNING":
                self.check_loop_watchdog()
                self.check_sensor_stale()
                self.check_sensor_faults()
                if temp_valid:
                    self.check_heating_progress(self.temperature)
                history_snapshot = self.get_state()
            state = self.state
        if history_snapshot:
            self.history.append_tick(history_snapshot)
        if state == "IDLE":
            if self.should_i_automatic_restart() == True:
                self.automatic_restart()
            if sleep:
                time.sleep(1)
            return state
        if state == "PAUSED":
            with self.state_lock:
                self.start_time = self.get_start_time()
                self.update_runtime()
                self.update_target_temp()
            self.heat_then_cool()
            self.reset_if_emergency()
            self.reset_if_schedule_ended()
            return state
        if state == "RUNNING":
            with self.state_lock:
                self.update_cost()
                self.save_automatic_restart_state()
                self.kiln_must_catch_up()
                self.update_runtime()
                self.update_target_temp()
            self.heat_then_cool()
            self.reset_if_emergency()
            self.reset_if_schedule_ended()
            return state
        return state

    def run(self):
        while True:
            self.run_iteration()

    def read_temperature(self):
        try:
            sensor = self.board.temp_sensor
        except AttributeError:
            log.error("temperature sensor missing; cannot read temperature")
            return None
        try:
            temp = sensor.temperature()
        except Exception:
            log.exception("temperature read failed")
            return None
        if temp is None:
            return None
        return temp + CONFIG.run.thermocouple_offset

class SimulatedOven(Oven):

    def __init__(self):
        self.board = SimulatedBoard()
        self.t_env = CONFIG.simulation.t_env
        self.c_heat = CONFIG.simulation.c_heat
        self.c_oven = CONFIG.simulation.c_oven
        self.p_heat = CONFIG.simulation.p_heat
        self.R_o_nocool = CONFIG.simulation.R_o_nocool
        self.R_ho_noair = CONFIG.simulation.R_ho_noair
        self.R_ho = self.R_ho_noair
        self.speedup_factor = CONFIG.simulation.speedup_factor

        # set temps to the temp of the surrounding environment
        self.t = CONFIG.simulation.t_env  # deg C temp of oven
        self.t_h = self.t_env #deg C temp of heating element

        super().__init__()

        self.start_time = self.get_start_time();

        # start thread
        self.start()
        log.info("SimulatedOven started")

    # runtime is in sped up time, start_time is actual time of day
    def get_start_time(self):
        return datetime.datetime.now() - datetime.timedelta(milliseconds = self.runtime * 1000 / self.speedup_factor)

    def update_runtime(self):
        runtime_delta = datetime.datetime.now() - self.start_time
        if runtime_delta.total_seconds() < 0:
            runtime_delta = datetime.timedelta(0)

        self.runtime = runtime_delta.total_seconds() * self.speedup_factor

    def update_target_temp(self):
        self.target = self.profile.get_target_temperature(self.runtime)

    def heating_energy(self,pid):
        # using pid here simulates the element being on for
        # only part of the time_step
        self.Q_h = self.p_heat * self.time_step * pid

    def temp_changes(self):
        #temperature change of heat element by heating
        self.t_h += self.Q_h / self.c_heat

        #energy flux heat_el -> oven
        self.p_ho = (self.t_h - self.t) / self.R_ho

        #temperature change of oven and heating element
        self.t += self.p_ho * self.time_step / self.c_oven
        self.t_h -= self.p_ho * self.time_step / self.c_heat

        #temperature change of oven by cooling to environment
        self.p_env = (self.t - self.t_env) / self.R_o_nocool
        self.t -= self.p_env * self.time_step / self.c_oven
        self.temperature = self.t
        self.board.temp_sensor.simulated_temperature = self.t

    def heat_then_cool(self):
        now_simulator = self.start_time + datetime.timedelta(milliseconds = self.runtime * 1000)
        if not self.safe_start_ready():
            with self.state_lock:
                self.heat = 0.0
            self.sleep_with_abort(self.time_step / self.speedup_factor)
            return
        pid = self.pid.compute(self.target,
                               self.board.temp_sensor.temperature() +
                               CONFIG.run.thermocouple_offset, now_simulator)

        heat_on = float(self.time_step * pid)
        heat_off = float(self.time_step * (1 - pid))

        self.heating_energy(pid)
        self.temp_changes()

        # self.heat is for the front end to display if the heat is on
        with self.state_lock:
            self.heat = 0.0
            if heat_on > 0:
                self.heat = heat_on

        log.info("simulation: -> %dW heater: %.0f -> %dW oven: %.0f -> %dW env" % (int(self.p_heat * pid),
            self.t_h,
            int(self.p_ho),
            self.t,
            int(self.p_env)))

        time_left = self.totaltime - self.runtime

        try:
            log.info("temp=%.2f, target=%.2f, error=%.2f, pid=%.2f, p=%.2f, i=%.2f, d=%.2f, heat_on=%.2f, heat_off=%.2f, run_time=%d, total_time=%d, time_left=%d" %
                (self.pid.pidstats['ispoint'],
                self.pid.pidstats['setpoint'],
                self.pid.pidstats['err'],
                self.pid.pidstats['pid'],
                self.pid.pidstats['p'],
                self.pid.pidstats['i'],
                self.pid.pidstats['d'],
                heat_on,
                heat_off,
                self.runtime,
                self.totaltime,
                time_left))
        except KeyError:
            pass

        # we don't actually spend time heating & cooling during
        # a simulation, so sleep.
        self.sleep_with_abort(self.time_step / self.speedup_factor)


class RealOven(Oven):

    def __init__(self):
        self.board = RealBoard()
        self.output = Output()
        self.reset()

        # call parent init
        Oven.__init__(self)

        # start thread
        self.start()

    def reset(self):
        super().reset()
        self.output.cool(0)

    def heat_then_cool(self):
        # Live hardware safety: ensure SSR turns off on any exception.
        try:
            if not self.safe_start_ready():
                with self.state_lock:
                    self.heat = 0.0
                self.output.set_output(self.output.off)
                self.sleep_with_abort(self.time_step)
                return
            pid = self.pid.compute(self.target,
                                   self.board.temp_sensor.temperature() +
                                   CONFIG.run.thermocouple_offset, datetime.datetime.now())

            heat_on = float(self.time_step * pid)
            heat_off = float(self.time_step * (1 - pid))

            # self.heat is for the front end to display if the heat is on
            with self.state_lock:
                self.heat = 0.0
            if heat_on:
                self.output.set_output(self.output.on)
                completed, on_elapsed = self.sleep_with_abort_elapsed(heat_on)
                with self.state_lock:
                    self.heat = on_elapsed
                if not completed:
                    return
            if heat_off:
                self.output.set_output(self.output.off)
                if not self.sleep_with_abort(heat_off):
                    return
            time_left = self.totaltime - self.runtime
            try:
                log.info("temp=%.2f, target=%.2f, error=%.2f, pid=%.2f, p=%.2f, i=%.2f, d=%.2f, heat_on=%.2f, heat_off=%.2f, run_time=%d, total_time=%d, time_left=%d" %
                    (self.pid.pidstats['ispoint'],
                    self.pid.pidstats['setpoint'],
                    self.pid.pidstats['err'],
                    self.pid.pidstats['pid'],
                    self.pid.pidstats['p'],
                    self.pid.pidstats['i'],
                    self.pid.pidstats['d'],
                    heat_on,
                    heat_off,
                    self.runtime,
                    self.totaltime,
                    time_left))
            except KeyError:
                pass
        except Exception:
            log.exception("heater control error; aborting run")
            self.abort_run("heater_error")
        finally:
            self.output.safe_off()

class PID():

    def __init__(self, ki=1, kp=1, kd=1):
        self.ki = ki
        self.kp = kp
        self.kd = kd
        self.lastNow = datetime.datetime.now()
        self.iterm = 0
        self.lastErr = 0
        self.pidstats = {}

    # FIX - this was using a really small window where the PID control
    # takes effect from -1 to 1. I changed this to various numbers and
    # settled on -50 to 50 and then divide by 50 at the end. This results
    # in a larger PID control window and much more accurate control...
    # instead of what used to be binary on/off control.
    def compute(self, setpoint, ispoint, now):
        timeDelta = (now - self.lastNow).total_seconds()
        if timeDelta <= 0:
            timeDelta = 1e-6
            self.iterm = 0
            self.lastErr = 0

        window_size = 100

        error = float(setpoint - ispoint)

        # this removes the need for CONFIG.run.stop_integral_windup
        # it turns the controller into a binary on/off switch
        # any time it's outside the window defined by
        # CONFIG.run.pid_control_window
        icomp = 0
        output = 0
        out4logs = 0
        dErr = 0
        if error < (-1 * CONFIG.run.pid_control_window):
            log.info("kiln outside pid control window, max cooling")
            output = 0
            # it is possible to set self.iterm=0 here and also below
            # but I dont think its needed
        elif error > (1 * CONFIG.run.pid_control_window):
            log.info("kiln outside pid control window, max heating")
            output = 1
            if CONFIG.run.throttle_below_temp and CONFIG.run.throttle_percent:
                if setpoint <= CONFIG.run.throttle_below_temp:
                    output = CONFIG.run.throttle_percent/100
                    log.info("max heating throttled at %d percent below %d degrees to prevent overshoot" % (CONFIG.run.throttle_percent,CONFIG.run.throttle_below_temp))
        else:
            icomp = (error * timeDelta * (1/self.ki))
            self.iterm += (error * timeDelta * (1/self.ki))
            dErr = (error - self.lastErr) / timeDelta
            output = self.kp * error + self.iterm + self.kd * dErr
            output = sorted([-1 * window_size, output, window_size])[1]
            out4logs = output
            output = float(output / window_size)
            
        self.lastErr = error
        self.lastNow = now

        # no active cooling
        if output < 0:
            output = 0

        self.pidstats = {
            'time': time.mktime(now.timetuple()),
            'timeDelta': timeDelta,
            'setpoint': setpoint,
            'ispoint': ispoint,
            'err': error,
            'errDelta': dErr,
            'p': self.kp * error,
            'i': self.iterm,
            'd': self.kd * dErr,
            'kp': self.kp,
            'ki': self.ki,
            'kd': self.kd,
            'pid': out4logs,
            'out': output,
        }

        return output
