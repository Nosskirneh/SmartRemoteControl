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
    activities = config.get_activities()
    holiday_names = list(OrderedDict.fromkeys([name.decode('utf-8') for _, name in sorted(all_holidays.items())]))
    template = render_template("index.html",
                               activities=activities,
                               now=get_current_date_string,
                               holidays=holiday_names)
    return template


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


@app.route("/schedule/configure/new", methods=["POST"])
def configure_new():
    return configure_schedule(None)

@app.route("/schedule/configure/<string:identifier>", methods=["POST"])
def configure_existing(identifier):
    return configure_schedule(identifier)

def configure_schedule(identifier):
    if not is_auth_ok():
        return "Unauthorized", 401

    id = request.form.get('id')
    time = request.form.get('time')
    days = request.form.get('days')
    groups = request.form.get('groups')

    if not id or not time or time == '' or not groups or len(groups) == 0:
        return "You need to provide name, time and commands.", 400

    if identifier == None and any(event["id"] == id for event in activities["scheduled"]):
        return "An event with that name does already exist.", 400

    enabled = request.form.get('enabled')
    fire_once = request.form.get('fireOnce')
    disabled_until = request.form.get('disabledUntil')
    exclude_all_holidays = request.form.get('excludeAllHolidays')
    excluded_holidays = request.form.get('excludedHolidays')

    def fill_event():
        event["id"] = id
        event["time"] = time
        if days:
            event["days"] = json.loads(days)

        event["disabled"] = enabled != "true"
        if disabled_until:
            event["disabledUntil"] = disabled_until

        if fire_once:
            event["fireOnce"] = fire_once == "true"

        formatted_groups = []
        for group in json.loads(groups):
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


@app.route("/activity/<int:index>", methods=["POST"])
def activity(index):
    if index == -1:
        return "Not Implemented", 501

    # Check authorization
    if not is_auth_ok():
       return "Unauthorized", 401

    count = 0
    for activity in activities["groups"]:
        for act in activity["activities"]:
            for i, codes in enumerate(act["codes"]):
                code = codes["data"].encode()
                group = codes["channel"].encode()
                if count is index:
                    if group == "IR":         # IR section
                        ser.write(code + ";") # Send IR code to Arduino
                        print(ser.readlines())

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

    return "OK", 200


### METHODS ###
def is_auth_ok():
    if "FLASK_ENV" in os.environ and os.environ["FLASK_ENV"] == "development":
        return True

    try:
        auth = request.headers["Authorization"].split()[1]
        user, pw = base64.b64decode(auth).split(":")
        return (user == username and pw == password)
    except KeyError:
        return False


def run_event(event):
    auth = base64.b64encode(username + ":" + password)
    with app.test_client() as client:
        for cmd in event["commands"]:
            client.post("/activity/" + str(return_index(cmd[0], cmd[1])),
                        headers = {"Authorization": "Basic " + auth})

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


### Scheduling ###
def run_schedule():
    lastEvent = None
    events = activities["scheduled"]
    didTurnOnMorningLights = False
    hasClearedLastEventToday = False

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

    while True:
        now = datetime.now()
        dayIndex = datetime.today().weekday()
        currentDay = allDays[dayIndex]

        # Reset in case the same event is only one event being fired
        if len(events) == 1 and now.hour == "0" and now.minute == "0" and not hasClearedLastEventToday:
            hasClearedLastEventToday = True
            lastEvent = None

        for event in events:
            [hour, minute] = [int(x) for x in event["time"].split(":")]

            # Is event disabled?
            if ("disabled" in event and event["disabled"]) or ("disabledUntil" in event and
                                        event["disabledUntil"] >= now.strftime('%Y-%m-%d')):
                continue

            # Evening
            if event["id"] == "evening":
                # If it's already dark by the time specified in the events dict, fire the commands.
                # Otherwise, schedule the commands to be executed on this date + timediff.
                if lastEvent != event["id"] and is_valid_time_and_day():
                    lastEvent = event["id"]
                    sunEvent = time_until_next_sun_event()
                    if sunEvent[0]:
                        run_event(event)
                    else:
                        # TODO: Perhaphs replace the generic execute_once to a custom
                        #       method that reschedules with cloud data.
                        timeStr = (now + sunEvent[1]).strftime("%H:%M")
                        print("Should schedule for %s" % (timeStr))
                        schedule.every().day.at(timeStr).do(execute_once, commands=event)

            # Morning
            elif event["id"] == "morning":
                # If it is dark by the time specified in the events dict, simply fire the commands.
                if lastEvent != event["id"] and is_valid_time_and_day():
                    lastEvent = event["id"]
                    sunEvent = time_until_next_sun_event()
                    if sunEvent[0]:
                        didTurnOnMorningLights = True
                        run_event(event)

            # Morning off
            elif event["id"] == "morning_off":
                # If it is light by the time specified in the events dict, simply fire the commands.
                # Otherwise, schedule the commands to be executed on this date + timediff.
                # Only fire this if `morning` was executed.
                if lastEvent != event["id"] and didTurnOnMorningLights and \
                   is_valid_time_and_day():
                    lastEvent = event["id"]
                    sunEvent = time_until_next_sun_event()
                    if not sunEvent[0]:
                        run_event(event)
                    else:
                        timeStr = (now + sunEvent[1]).strftime("%H:%M")
                        print("Should schedule for %s" % (timeStr))
                        schedule.every().day.at(timeStr).do(execute_once, commands=event)

            # Events that don't need any custom rules, like evening off
            else:
                # If the time match with the specified in the events dict, simply fire the commands.
                if lastEvent != event["id"] and is_valid_time_and_day():
                    lastEvent = event["id"]
                    run_event(event)

        schedule.run_pending()
        sleep(1)


# There is no other way to schedule only once other than doing this.
def execute_once(event):
    run_event(event)
    return schedule.CancelJob


# Returns if it is dark or light, and the time until the next sunrise/sunset
# True means it is dark, False means it is sunny
def time_until_next_sun_event():
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
        logging.debug("It's sunny outside, %s in %s" % (event, timediff))
        print("It's sunny outside, %s in %s" % (event, timediff))
        return (False, timediff)
    else:
        timediff = sun["sunrise"] - currentTime
        logging.debug("It's dark outside, %s until sunrise" % (timediff))
        print("It's dark outside, %s until sunrise" % (timediff))
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


# This will only run once, not twice
if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    # Setup logging to file
    logging.basicConfig(filename="log.txt", level=logging.DEBUG, format="%(asctime)s %(message)s")

    # Load variables
    activities = config.get_activities() # Parse activity configuration.
    REQ_ADDR = "http://192.168.0.20:1234"

    # Initialize COM-port
    ser = init_comport()

    thread = threading.Thread(target=run_schedule, args=())
    thread.daemon = True
    thread.start()

    logging.debug("Server started")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True, threaded=True)
