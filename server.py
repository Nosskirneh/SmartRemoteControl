#!/usr/bin/env python
import sys
import os
import fnmatch
sys.path.append("/storage/.python")
import serial
from time import sleep
from flask import *
import config
from credentials import *
import requests
import base64
from wakeonlan import wol

import threading
from datetime import datetime, date
import schedule
import holidays
from collections import OrderedDict
import time
from astral import Astral
import pytz

import logging
from logging.handlers import RotatingFileHandler


# Since the holiday object cannot be created with a years parameter if the CountryHoliday is used,
# we have to do a simple check just to populate the years property. The other solution would be to
# use the language constructor, for example .SE(years=yyyy)
all_holidays = holidays.CountryHoliday(config.HOLIDAY_COUNTRY)
datetime.now() in all_holidays


# Create flask application.
app = Flask(__name__)

def get_current_date_string():
    return datetime.now().strftime('%Y-%m-%dT%H:%M')

### APP ROUTES ###
@app.route("/")
def root():
    auth = request.cookies.get('auth')
    if auth == None or not is_auth_ok(auth):
        return render_template("login.html")

    activities = config.get_activities()
    holiday_names = list(OrderedDict.fromkeys([name.decode('utf-8') for _, name in sorted(all_holidays.items())]))
    return render_template("index.html",
                           activities=activities,
                           now=get_current_date_string,
                           holidays=holiday_names)


@app.route("/login", methods = ['POST'])
def login():
    form = request.form
    if 'username' not in form or 'password' not in form:
        return render_template("login.html")

    username = form['username']
    password = form['password']
    auth = base64.b64encode(username + ':' + password)

    response = make_response(redirect('/'))
    response.set_cookie('auth', auth)

    return response


@app.route("/command", methods=["POST"])
def command():
    name  = request.form.get("name")
    group = request.form.get("group")
    return activity(return_index(name, group))


@app.route("/checkAuth", methods=["GET"])
def check_auth():
    if is_auth_ok():
        return "OK", 200
    return "Unauthorized", 401


@app.route("/status", methods=["GET"])
def return_online():
    return "OK", 200


@app.route("/commands", methods=["GET"])
def get_commands():
    # Check authorization
    if not is_auth_ok():
        return "Unauthorized", 401
    return jsonify(activities)


@app.route("/schedule/enable/<string:identifier>", methods=["POST"])
def set_enabled(identifier):
    if not is_auth_ok():
        return "Unauthorized", 401

    index = return_schedule_index(identifier)
    event = activities["scheduled"][index]
    event["disabled"] = request.form.get('enabled') != "true"

    config.save_activities(activities)
    return "OK", 200


@app.route("/schedule/new", methods=["POST"])
def configure_new():
    return configure_schedule(None)

@app.route("/schedule/configure/<string:identifier>", methods=["POST"])
def configure_existing(identifier):
    return configure_schedule(identifier)

def configure_schedule(identifier):
    if not is_auth_ok():
        return "Unauthorized", 401

    form = request.form

    id = form.get('id')
    time = form.get('time')
    days = form.get('days')
    groups = form.get('groups')

    if not id or not time or time == '' or not groups:
        return "You need to provide name, time and commands.", 400

    groups = json.loads(groups)
    if len(groups) == 0:
        return "You need to provide commands.", 400

    if identifier == None and any(event["id"] == id for event in activities["scheduled"]):
        return "An event with that name does already exist.", 400

    enabled = form.get('enabled')
    fire_once = form.get('fireOnce')
    disabled_until = form.get('disabledUntil')
    exclude_all_holidays = form.get('excludeAllHolidays')
    excluded_holidays = form.get('excludedHolidays')

    wait_for_sunrise = form.get('waitForSunrise')
    wait_for_sunset = form.get('waitForSunset')
    on_sunny = form.get('onSunny')
    on_dark = form.get('onDark')

    if_executed_event_id = form.get('ifExecutedEventID')

    def fill_event():
        event["id"] = id
        event["time"] = time

        event.pop("waitForSunrise", None)
        event.pop("waitForSunset", None)
        event.pop("onSunny", None)
        event.pop("onDark", None)

        if wait_for_sunrise:
            event["waitForSunrise"] = True
        elif wait_for_sunset:
            event["waitForSunset"] = True
        elif on_sunny:
            event["onSunny"] = True
        elif on_dark:
            event["onDark"] = True

        if if_executed_event_id:
            event["ifExecutedEventID"] = if_executed_event_id

        if days:
            event["days"] = json.loads(days)

        event["disabled"] = enabled != "true"
        if disabled_until:
            event["disabledUntil"] = disabled_until

        if fire_once:
            event["fireOnce"] = fire_once == "true"

        formatted_groups = []
        for group in groups:
            for activity in group["activities"]:
                formatted_groups.append([activity, group["name"]])
        event["commands"] = formatted_groups

        event["excludeAllHolidays"] = exclude_all_holidays == "true"
        if excluded_holidays:
            event["excludedHolidays"] = json.loads(excluded_holidays)

    result = {}
    if identifier == None: # New event
        event = {}
        fill_event()
        activities["scheduled"].append(event)
        result["data"] = activities["scheduled"][-1]
        result["html"] = render_template("schedule-block.html.j2",
                                         event=activities["scheduled"][-1],
                                         index=len(activities["scheduled"]) - 1,
                                         now=get_current_date_string)
    else: # Existing event
        index = return_schedule_index(identifier)
        event = activities["scheduled"][index]
        fill_event()
        result["data"] = event

    config.save_activities(activities)
    return jsonify(result), 200


@app.route("/schedule/delete/<string:identifier>", methods=["POST"])
def delete(identifier):
    if not is_auth_ok():
        return "Unauthorized", 401

    index = return_schedule_index(identifier)

    if index == -1:
        return "Event does not exist.", 400

    activities["scheduled"].pop(index)

    config.save_activities(activities)
    return "OK", 200


def run_activity(index):
    count = 0
    for activity in activities["groups"]:
        for act in activity["activities"]:
            for i, codes in enumerate(act["codes"]):
                code = codes["data"].encode()
                group = codes["channel"].encode()
                if count is index:
                    if group == "IR":         # IR section
                        ser.write(code + ";") # Send IR code to Arduino
                        # print(ser.readlines())

                    elif (group == "MHZ433" or group == "NEXA"): # MHZ433 & NEXA section
                        ser.write(group + ": " + code + ";")

                    elif (group == "LED"):    # HyperionWeb
                        if (code == "CLEAR"):
                            try:
                                r = requests.post(REQ_ADDR + "/do_clear", data={"clear":"clear"})
                                r = requests.post(REQ_ADDR + "/set_value_gain", data={"valueGain":"20"})
                            except requests.ConnectionError:
                                return "Service Unavailable", 503
                        if (code == "BLACK"):
                            try:
                                r = requests.post(REQ_ADDR + "/set_color_name", data={"colorName":"black"})
                                r = requests.post(REQ_ADDR + "/set_value_gain", data={"valueGain":"100"})
                            except requests.ConnectionError:
                                return "Service Unavailable", 503

                    elif (group == "WOL"):    # Wake on LAN
                        wol.send_magic_packet(code)

                    if (i != len(codes) - 1): # Don't delay after last item
                        sleep(0.2)       # Wait ~200 milliseconds between codes.
            count = count + 1


@app.route("/activity/<int:index>", methods=["POST"])
def activity(index):
    # Check authorization
    if not is_auth_ok():
       return "Unauthorized", 401

    if index == -1:
        return "Not Implemented", 501

    run_activity(index)

    return "OK", 200


### METHODS ###
def is_auth_ok(auth = None):
    if "FLASK_ENV" in os.environ and os.environ["FLASK_ENV"] == "development":
        return True

    if auth == None:
        try:
            auth = request.headers["Authorization"].split()[1]
        except KeyError:
            return False

    user, pw = base64.b64decode(auth).split(":")
    return (user == username and pw == password)


def run_event(event):
    for cmd in event["commands"]:
        index = return_index(cmd[0], cmd[1])
        if index != -1:
            run_activity(index)

    if "fireOnce" in event and event["fireOnce"]:
        event["disabled"] = True
        config.save_activities(activities)


def return_schedule_index(identifier):
    count = 0
    for event in activities["scheduled"]:
        if event["id"] == identifier:
            return count
        count = count + 1
    return -1

def return_index(cmd, grp):
    count = 0
    for activity in activities["groups"]:
        g = activity["name"]
        for act in activity["activities"]:
            n = act["name"]
            if n == cmd and g == grp:
                return count
            count = count + 1
    return -1


did_run = {}

### Scheduling ###
def run_schedule():
    lastProcessedEvent = None
    hasClearedLastProcessedEventToday = False

    events = activities["scheduled"]
    allDays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    def is_valid_time_and_day():
        # If today is a holiday and all holidays should be excluded
        if "excludeAllHolidays" in event and event["excludeAllHolidays"] and now.date() in all_holidays:
            return False

        if "excludedHolidays" in event:
            # If today is a holiday and this holiday should be excluded
            if now.date() in all_holidays and dict(all_holidays.items())[now.date()] in event["excludedHolidays"]:
                return False

        return now.hour == hour and now.minute == minute and \
               ("days" not in event or currentDay in event["days"])

    def reschedule_event():
        # TODO: Perhaphs add the option to replace the generic execute_once
        #       to a custom method that reschedules with cloud data.
        time_str = (now + time_until).strftime("%H:%M")
        logger.debug("Reschedule for {}".format(time_str))
        schedule.every().day.at(time_str).do(execute_once, commands=event)

    def run_scheduled_event():
        did_run[event['id']] = True
        logger.debug("Executing scheduled event {}".format(event['id']))
        run_event(event)

    while True:
        now = datetime.now()
        dayIndex = datetime.today().weekday()
        currentDay = allDays[dayIndex]

        # Reset data structures keeping track of which events have run
        if len(events) == 1 and now.hour == "0" and now.minute == "0" and not hasClearedLastProcessedEventToday:
            hasClearedLastProcessedEventToday = True
            # Reset this in case the same event is the only one event being fired
            lastProcessedEvent = None
            did_run.clear()

        for event in events:
            [hour, minute] = [int(x) for x in event["time"].split(":")]

            # Is event disabled?
            if ("disabled" in event and event["disabled"]) or ("disabledUntil" in event and
                                        event["disabledUntil"] >= now.strftime('%Y-%m-%d')):
                continue

            if lastProcessedEvent == event["id"] or not is_valid_time_and_day():
                continue

            lastProcessedEvent = event["id"]

            if "ifExecutedEventID" in event and event["ifExecutedEventID"] not in did_run:
                continue

            if "onDark" in event:
                is_dark, _ = get_sun_info()
                if is_dark:
                    run_scheduled_event()
            elif "onSunny" in event:
                is_dark, _ = get_sun_info()
                if not is_dark:
                    run_scheduled_event()
            elif "waitForSunrise" in event:
                is_dark, time_until = get_sun_info()
                if not is_dark:
                    run_scheduled_event()
                else:
                    reschedule_event()
            elif "waitForSunset" in event:
                is_dark, time_until = get_sun_info()
                if is_dark:
                    run_scheduled_event()
                else:
                    reschedule_event()
            else:
                run_scheduled_event()

        schedule.run_pending()
        sleep(5)


# There is no other way to schedule only once other than doing this.
def execute_once(event):
    run_event(event)

    did_run[event['id']] = True
    return schedule.CancelJob


# Returns if it is dark or light, and the time until the next sunrise/sunset
# True means it is dark, False means it is sunny
def get_sun_info():
    city_name = "Stockholm"
    a = Astral()
    city = a[city_name]
    today = date.today()
    sun = city.sun(date=today, local=True)
    utc = pytz.UTC
    currentTime = utc.localize(datetime.utcnow())
    # Is it between sunrise and sunset?
    if sun["sunrise"] <= currentTime <= sun["sunset"]:
        if sun["sunset"] >= currentTime:
            event = "sunset"
            timediff = sun["sunset"] - currentTime
        if sun["sunset"] <= currentTime:
            event = "sunrise"
            timediff = currentTime - sun["sunrise"]

        logger.debug("It's sunny outside, {} in {}".format(event, timediff))
        return (False, timediff)
    else:
        timediff = sun["sunrise"] - currentTime
        logger.debug("It's dark outside, {} until sunrise".format(timediff))
        return (True, timediff)


def init_comport():
    # Find the right USB port
    matches = []

    for root, dirnames, filenames in os.walk("/dev"):
        for filename in fnmatch.filter(filenames, "ttyUSB*"):
            matches.append(os.path.join(root, filename))

    ser          = serial.Serial()
    ser.port     = matches[0]
    ser.baudrate = 9600
    ser.timeout  = 0
    ser.xonxoff  = False       # disable software flow control
    ser.rtscts   = False       # disable hardware (RTS/CTS) flow control
    ser.dsrdtr   = False       # disable hardware (DSR/DTR) flow control

    if ser.isOpen():
        print("### Serial conenction already open!")
    else:
        try:
            ser.open()
            print(" * Serial connection open!")
        except Exception, e:
            print(" * Error open serial port: " + str(e))
    return ser

def init_logger():
    log_level = logging.DEBUG
    log_filename = 'log.txt'
    logger = logging.getLogger('root')
    logger.setLevel(log_level)
    formatter = logging.Formatter('%(asctime)s %(message)s')

    # 5 MB logging
    file_handler = RotatingFileHandler(log_filename, mode='a', maxBytes=5000 * 1000,
                                       backupCount=2, encoding='utf-8')
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger


# This will only run once, not twice
if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    # Setup logging to file
    logger = init_logger()

    # Load variables
    activities = config.get_activities() # Parse activity configuration.
    REQ_ADDR = "http://192.168.0.20:1234"

    # Initialize COM-port
    ser = init_comport()

    thread = threading.Thread(target=run_schedule, args=())
    thread.daemon = True
    thread.start()

    logger.debug("Server started")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True, threaded=True)
