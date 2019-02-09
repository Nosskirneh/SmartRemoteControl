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
import time
from astral import Astral
import pytz
import logging


# Create flask application.
app = Flask(__name__)

def getCurrentDateAsString():
    return datetime.now().strftime('%Y-%m-%dT%H:%M')

### APP ROUTES ###
@app.route("/")
def root():
    template = render_template("index.html", activities=config.get_activities(), now=getCurrentDateAsString)
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


@app.route("/schedule/configure/new", methods=["POST"])
def configure_new():
    return configure_schedule()

@app.route("/schedule/configure/<int:index>", methods=["POST"])
def configure_existing(index):
    return configure_schedule(index)

def configure_schedule(index = -1):
    if not is_auth_ok():
        return "Unauthorized", 401

    id = request.form.get('id')
    time = request.form.get('time')
    days = request.form.get('days')
    groups = request.form.get('groups')
    enabled = request.form.get('enabled')
    disabled_until = request.form.get('disabledUntil')

    if not id or not time or time == '' or not groups or len(groups) == 0:
        return "You need to provide name, time and commands.", 400

    def fill_event():
        event["id"] = id
        event["time"] = time
        if days:
            event["days"] = json.loads(days)

        event["disabled"] = enabled != "true"
        if disabled_until:
            event["disabledUntil"] = disabled_until

        formatted_groups = []
        for group in json.loads(groups):
            for activity in group["activities"]:
                formatted_groups.append([activity, group["name"]])
        event["commands"] = formatted_groups

    if index == -1:
        event = {}
        fill_event()
        activities["scheduled"].append(event)
    else:
        event = activities["scheduled"][index]
        fill_event()

    # config.save_activities(activities)
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
                        time.sleep(0.2)       # Wait ~200 milliseconds between codes.
            count = count + 1

    return "OK", 200


### METHODS ###
def is_auth_ok():
    try:
        auth = request.headers["Authorization"].split()[1]
        user, pw = base64.b64decode(auth).split(":")
        return (user == username and pw == password)
    except KeyError:
        return False


def run_commands(commands):
    auth = base64.b64encode(username + ":" + password)
    with app.test_client() as client:
        for cmd in commands:
            sleep(1)
            client.post("/activity/" + str(return_index(cmd[0], cmd[1])),
                        headers = {"Authorization": "Basic " + auth})


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
        if "exclude" in event:
            all_holidays = dict(holidays.SE().items())
            if "holiday" in event["exclude"] == "holidays" and now in holidays.SE():
                return False
            # If today is a holiday and this holiday should be excluded
            elif now.date() in all_holidays and all_holidays[now.date()] in event["exclude"]:
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
            if "disabled" in event and ("disabledUntil" not in event or
                                        event["disabledUntil"] >= now.strftime('%Y-%m-%d')):
                continue

            # Evening
            if event["id"] == "evening":
                # If it's already dark by the time specified in the events dict, fire the commands.
                # Otherwise, schedule the commands to be executed on this date + timediff.
                if lastEvent != event["id"] and is_valid_time_and_day():
                    lastEvent = event["id"]
                    sunEvent = timeUntilSunEvent()
                    if sunEvent[0]:
                        run_commands(event["commands"])
                    else:
                        # TODO: Perhaphs replace the generic execute_once to a custom
                        #       method that reschedules with cloud data.
                        timeStr = (now + sunEvent[1]).strftime("%H:%M")
                        print("Should schedule for %s" % (timeStr))
                        schedule.every().day.at(timeStr).do(execute_once, commands=event["commands"])

            # Morning
            elif event["id"] == "morning":
                # If it is dark by the time specified in the events dict, simply fire the commands.
                if lastEvent != event["id"] and is_valid_time_and_day():
                    lastEvent = event["id"]
                    sunEvent = timeUntilSunEvent()
                    if sunEvent[0]:
                        didTurnOnMorningLights = True
                        run_commands(event["commands"])

            # Morning off
            elif event["id"] == "morning_off":
                # If it is light by the time specified in the events dict, simply fire the commands.
                # Otherwise, schedule the commands to be executed on this date + timediff.
                # Only fire this if `morning` was executed.
                if lastEvent != event["id"] and didTurnOnMorningLights and \
                   is_valid_time_and_day():
                    lastEvent = event["id"]
                    sunEvent = timeUntilSunEvent()
                    if not sunEvent[0]:
                        run_commands(event["commands"])
                    else:
                        timeStr = (now + sunEvent[1]).strftime("%H:%M")
                        print("Should schedule for %s" % (timeStr))
                        schedule.every().day.at(timeStr).do(execute_once, commands=event["commands"])

            # Events that don't need any custom rules, like evening off
            else:
                # If the time match with the specified in the events dict, simply fire the commands.
                if lastEvent != event["id"] and is_valid_time_and_day():
                    lastEvent = event["id"]
                    run_commands(event["commands"])


        schedule.run_pending()
        sleep(1)


# There is no other way to schedule only once other than doing this.
def execute_once(commands="cmds"):
    run_commands(commands)
    return schedule.CancelJob


# Returns if it is dark or light, and the time until the next sunrise/sunset
# True means it is dark, False means it is sunny
def timeUntilSunEvent():
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
