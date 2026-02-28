#!/usr/bin/env python

import os
import sys
import csv
import time
import argparse
import statistics
import fcntl

try:
        sys.dont_write_bytecode = True
        from config import CONFIG
        sys.dont_write_bytecode = False

except ImportError:
        print("Could not import config file.")
        print("Create config.toml and adapt it for your setup.")
        exit(1)


def recordprofile(csvfile, targettemp):

    script_dir = os.path.dirname(os.path.realpath(__file__))
    sys.path.insert(0, script_dir)

    from lib.oven import RealOven, SimulatedOven

    # open the file to log data to
    f = open(csvfile, 'w')
    csvout = csv.writer(f)
    csvout.writerow(['time', 'temperature'])

    # construct the oven
    if CONFIG.simulation.simulate:
        oven = SimulatedOven()
        oven.target = targettemp * 2 # insures max heating for simulation
    else:
        oven = RealOven()

    # Main loop:
    #
    # * heat the oven to the target temperature at maximum burn.
    # * when we reach it turn the heating off completely.
    # * wait for it to decay back to the target again.
    # * quit
    #
    # We record the temperature every CONFIG.run.sensor_time_wait
    try:

        # heating to target temperature (degrees C)
        temp = 0
        sleepfor = CONFIG.run.sensor_time_wait
        stage = "heating"
        while(temp <= targettemp):
            if CONFIG.simulation.simulate:
                oven.heat_then_cool()
            else:
                oven.output.heat(sleepfor)
            temp = oven.board.temp_sensor.temperature() + CONFIG.run.thermocouple_offset
            
            print("stage = %s, actual = %.2f, target = %.2f" % (stage,temp,targettemp))
            csvout.writerow([time.time(), temp])
            f.flush()

        # overshoot past target and then cooling down to target
        stage = "cooling"
        if CONFIG.simulation.simulate:
            oven.target = 0
        while(temp >= targettemp):
            if CONFIG.simulation.simulate:
                oven.heat_then_cool()
            else:
                oven.output.cool(sleepfor)
            temp = oven.board.temp_sensor.temperature() + CONFIG.run.thermocouple_offset
            
            print("stage = %s, actual = %.2f, target = %.2f" % (stage,temp,targettemp))
            csvout.writerow([time.time(), temp])
            f.flush()

    finally:
        f.close()
        # ensure we always shut the oven down!
        if not CONFIG.simulation.simulate:
            oven.output.cool(0)


def line(a, b, x):
    return a * x + b


def invline(a, b, y):
    return (y - b) / a


def plot(xdata, ydata,
         tangent_min, tangent_max, tangent_slope, tangent_offset,
         lower_crossing_x, upper_crossing_x):
    from matplotlib import pyplot

    minx = min(xdata)
    maxx = max(xdata)
    miny = min(ydata)
    maxy = max(ydata)

    pyplot.scatter(xdata, ydata)

    pyplot.plot([minx, maxx], [miny, miny], '--', color='purple')
    pyplot.plot([minx, maxx], [maxy, maxy], '--', color='purple')

    pyplot.plot(tangent_min[0], tangent_min[1], 'v', color='red')
    pyplot.plot(tangent_max[0], tangent_max[1], 'v', color='red')
    pyplot.plot([minx, maxx], [line(tangent_slope, tangent_offset, minx), line(tangent_slope, tangent_offset, maxx)], '--', color='red')

    pyplot.plot([lower_crossing_x, lower_crossing_x], [miny, maxy], '--', color='black')
    pyplot.plot([upper_crossing_x, upper_crossing_x], [miny, maxy], '--', color='black')

    pyplot.show()


def calculate(filename, tangentdivisor, showplot):
    # parse the csv file
    xdata = []
    ydata = []
    filemintime = None
    with open(filename) as f:
        for row in csv.DictReader(f):
            try:
                time = float(row['time'])
                temp = float(row['temperature'])
                if filemintime is None:
                    filemintime = time

                xdata.append(time - filemintime)
                ydata.append(temp)
            except ValueError:
                continue  # just ignore bad values!

    # gather points for tangent line
    miny = min(ydata)
    maxy = max(ydata)
    midy = (maxy + miny) / 2
    yoffset = int((maxy - miny) / tangentdivisor)
    tangent_min = tangent_max = None
    for i in range(0, len(xdata)):
        rowx = xdata[i]
        rowy = ydata[i]

        if rowy >= (midy - yoffset) and tangent_min is None:
            tangent_min = (rowx, rowy)
        elif rowy >= (midy + yoffset) and tangent_max is None:
            tangent_max = (rowx, rowy)

    # calculate tangent line to the main temperature curve
    tangent_slope = (tangent_max[1] - tangent_min[1]) / (tangent_max[0] - tangent_min[0])
    tangent_offset = tangent_min[1] - line(tangent_slope, 0, tangent_min[0])

    # determine the point at which the tangent line crosses the min/max temperaturess
    lower_crossing_x = invline(tangent_slope, tangent_offset, miny)
    upper_crossing_x = invline(tangent_slope, tangent_offset, maxy)

    # compute parameters
    L = lower_crossing_x - min(xdata)
    T = upper_crossing_x - lower_crossing_x

    # Magic Ziegler-Nicols constants ahead!
    Kp = 1.2 * (T / L)
    Ti = 2 * L
    Td = 0.5 * L
    Ki = Kp / Ti
    Kd = Kp * Td

    # output to the user
    print("pid_kp = %s" % (Kp))
    print("pid_ki = %s" % (1 / Ki))
    print("pid_kd = %s" % (Kd))
    print("")
    print("# Suggested safety tuning (place under [run] in config.toml)")
    if len(xdata) > 1:
        deltas = [xdata[i] - xdata[i - 1] for i in range(1, len(xdata))]
        dt = statistics.median([d for d in deltas if d > 0])
    else:
        dt = CONFIG.run.sensor_time_wait
    ramps = []
    for i in range(1, len(ydata)):
        dt_i = xdata[i] - xdata[i - 1]
        if dt_i <= 0:
            continue
        ramps.append(abs(ydata[i] - ydata[i - 1]) / dt_i)
    if ramps:
        ramps_sorted = sorted(ramps)
        p95_index = int(0.95 * (len(ramps_sorted) - 1))
        p95 = ramps_sorted[p95_index]
        ramp_max = max(1.0, p95 * 2)
    else:
        ramp_max = 1.0
    anomaly_window = int(max(10, round(60 / max(dt, 1e-6))))
    anomaly_max = int(max(3, round(anomaly_window * 0.2)))
    loop_watchdog = max(10.0, dt * 5)
    safe_start_samples = max(3, int(round(6 / max(dt, 1e-6))))
    safe_start_timeout = max(30.0, safe_start_samples * dt * 3)
    sensor_stale_timeout = max(30.0, dt * 5)

    print("temp_ramp_max_c_per_sec = %.2f" % (ramp_max))
    print("temp_ramp_anomaly_window = %d" % (anomaly_window))
    print("temp_ramp_anomaly_max = %d" % (anomaly_max))
    print("loop_watchdog_timeout_seconds = %.0f" % (loop_watchdog))
    print("sensor_stale_timeout_seconds = %.0f" % (sensor_stale_timeout))
    print("safe_start_min_good_samples = %d" % (safe_start_samples))
    print("safe_start_timeout_seconds = %.0f" % (safe_start_timeout))
    print("ssr_quiet_window_ms = %d" % (int(CONFIG.run.ssr_quiet_window_ms)))
    print("profile_min_temp_c = %d  # adjust for your kiln" % (int(CONFIG.run.profile_min_temp_c)))
    print("profile_max_temp_c = %d  # adjust for your kiln" % (int(CONFIG.run.profile_max_temp_c)))


    if showplot:
        plot(xdata, ydata,
             tangent_min, tangent_max, tangent_slope, tangent_offset,
             lower_crossing_x, upper_crossing_x)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Kiln tuner')
    parser.add_argument('-c', '--calculate_only', action='store_true')
    parser.add_argument('-t', '--target_temp', type=float, default=200, help="Target temperature (degrees C, default 200C)")
    parser.add_argument('-d', '--tangent_divisor', type=float, default=8, help="Adjust the tangent calculation to fit better. Must be >= 2 (default 8).")
    parser.add_argument('-s', '--showplot', action='store_true', help="draw plot so you can see tanget line and possibly change")
    args = parser.parse_args()

    csvfile = "tuning.csv"
    target = args.target_temp
    tangentdivisor = args.tangent_divisor 

    # default behavior is to record profile to csv file tuning.csv
    # and then calculate pid values and print them
    if args.calculate_only:
        calculate(csvfile, tangentdivisor, args.showplot)
    else:
        lock_path = CONFIG.server.lock_file
        lock_dir = os.path.dirname(lock_path)
        if lock_dir:
            os.makedirs(lock_dir, exist_ok=True)
        lock_handle = open(lock_path, "a+")
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("kiln controller already running, stop it before tuning")
            sys.exit(1)
        recordprofile(csvfile, target)
        calculate(csvfile, tangentdivisor, args.showplot)
