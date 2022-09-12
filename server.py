#!/usr/bin/env python3
import sys
import os
from time import sleep
from flask import *
import config
from credentials import *
import base64
from collections import ChainMap
from IKEA import TradfriHandler
from weather import WeatherManager
from channel_handler import ChannelHandler

import threading
from datetime import datetime, date, timedelta
import schedule
import holidays
from collections import OrderedDict
from astral.geocoder import lookup, database
from astral.location import Location
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
tradfri_handler = TradfriHandler(IKEA_GATEWAY_IP, IKEA_GATEWAY_KEY)
weather_manager = WeatherManager(OPEN_WEATHER_MAP_KEY, OPEN_WEATHER_MAP_LAT, OPEN_WEATHER_MAP_LON)

def get_current_date_string():
    return datetime.now().strftime('%Y-%m-%dT%H:%M')

### APP ROUTES ###
@app.route("/")
def root():
    auth = request.cookies.get('auth')
    if auth == None or not is_auth_ok(auth):
        return render_template("login.html")

    activities = config.get_activities()
    holiday_names = list(OrderedDict.fromkeys([name for _, name in sorted(all_holidays.items())]))
    return render_template("index.html",
                           activities=activities,
                           tradfri_groups=tradfri_handler.export_groups(),
                           suggested_colors=["FFA64D", "FFC47E", "F5FAF6"],
                           now=get_current_date_string,
                           holidays=holiday_names)


@app.route("/login", methods = ['POST'])
def login():
    form = request.form
    if 'username' not in form or 'password' not in form:
        return render_template("login.html")

    username = form['username']
    password = form['password']
    auth = base64.b64encode((username + ':' + password).encode('ascii'))

    response = make_response(redirect('/'))
    response.set_cookie('auth', auth)
    return response


@app.route("/command", methods=["POST"])
def command():
    name  = request.form.get("name")
    group = request.form.get("group")
    return activity(group, return_index(name, group))


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
    commands = activities.copy()
    commands["tradfri_groups"] = tradfri_handler.export_groups()
    return jsonify(commands)


@app.route("/schedule/run/<string:identifier>", methods=["POST"])
def manually_run_event(identifier):
    if not is_auth_ok():
        return "Unauthorized", 401

    index = return_schedule_index(identifier)
    event = activities["scheduled"][index]
    run_event(event)
    return "OK", 200


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

        commands = {}
        plain_formatted_groups = []
        for group in groups:
            group_activities = group["activities"]
            if type(group_activities) == list:
                for activity in group_activities:
                    plain_formatted_groups.append([activity, group["name"]])
            else:
                commands[group["name"]] = group_activities
        commands["plain"] = plain_formatted_groups
        event["commands"] = commands

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


def run_activity(group, index):
    for activity_group in activities["groups"]:
        if activity_group["name"] != group:
            continue

        activity = activity_group["activities"][index]
        for code_configuration in activity["codes"]:
            channel = code_configuration["channel"]
            if channel not in channel_handlers:
                return "Channel not found", 404
            result = channel_handlers[channel].handle_code(channel, code_configuration["data"])
            if result != None:
                return result

            if code_configuration != activity["codes"][-1]: # Don't delay after last item
                sleep(0.2)       # Wait ~200 milliseconds between codes.


@app.route("/activity/<group>/<int:index>", methods=["POST"])
def activity(group, index):
    # Check authorization
    if not is_auth_ok():
       return "Unauthorized", 401

    if index == -1:
        return "Not Implemented", 501

    run_activity(group, index)
    return "OK", 200


@app.route("/tradfri/<int:group_id>/dimmer/<int:value>", methods=["POST"])
def tradfri_dimmer(group_id, value):
    # Check authorization
    if not is_auth_ok():
       return "Unauthorized", 401

    if not tradfri_handler.set_dimmer(group_id, value):
        return "Device not found", 403
    return "OK", 200


@app.route("/tradfri/<int:group_id>/color/<string:value>", methods=["POST"])
def tradfri_color(group_id, value):
    # Check authorization
    if not is_auth_ok():
       return "Unauthorized", 401

    if value.startswith('#'):
        value = value.lstrip('#')

    if not tradfri_handler.set_hex_color(group_id, value):
        return "Device not found", 403
    return "OK", 200



@app.route("/tradfri/<int:group_id>/<string:on_off>", methods=["POST"])
def tradfri_on_off(group_id, on_off):
    # Check authorization
    if not is_auth_ok():
       return "Unauthorized", 401

    if on_off not in ("on", "off"):
        return "Use the on/off endpoint", 405

    if not tradfri_handler.set_state(group_id, on_off == "on"):
        return "Device not found", 403
    return "OK", 200



### METHODS ###
def is_auth_ok(auth = None):
    if "FLASK_ENV" in os.environ and os.environ["FLASK_ENV"] == "development":
        return True

    if request.remote_addr in WHITELISTED_IPS:
        return True

    if auth == None:
        try:
            auth = request.headers["Authorization"].split()[1]
        except KeyError:
            return False

    user, pw = base64.b64decode(auth).decode('utf-8').split(":")
    return (user == USERNAME and pw == PASSWORD)


def run_event(event):
    if "commands" in event:
        all_commands = event["commands"]
        if "plain" in all_commands:
            for (data, group) in all_commands["plain"]:
                index = return_index(data, group)
                if index != -1:
                    run_activity(group, index)

        if "tradfri" in all_commands:
            for device_id_str in all_commands["tradfri"]:
                device_commands = all_commands["tradfri"][device_id_str]
                device_id = int(device_id_str)
                if "light-state" in device_commands:
                    tradfri_handler.set_state(device_id, device_commands["light-state"])
                if "color" in device_commands:
                    tradfri_handler.set_hex_color(device_id, device_commands["color"])
                if "dimmer" in device_commands:
                    tradfri_handler.set_dimmer(device_id, int(device_commands["dimmer"]))

    if "fireOnce" in event and event["fireOnce"]:
        event["disabled"] = True
        config.save_activities(activities)


def return_schedule_index(identifier):
    count = 0
    for event in activities["scheduled"]:
        if event["id"] == identifier:
            return count
        count += 1
    return -1

def return_index(cmd, grp):
    count = 0
    for activity in activities["groups"]:
        g = activity["name"]
        if g != grp:
            continue
        for act in activity["activities"]:
            n = act["name"]
            if n == cmd:
                return count
            count += 1
    return -1


executed_scheduled_events = {}

### Scheduling ###
def run_schedule():
    events = activities["scheduled"]
    all_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    timezone = pytz.timezone(config.TIMEZONE)

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
        time_str = (now + time_until).strftime("%H:%M")
        logger.debug("Reschedule for {}".format(time_str))
        schedule.every().day.at(time_str).do(execute_once, event=event)

    def run_scheduled_event():
        executed_scheduled_events[event['id']] = True
        logger.debug("Executing scheduled event {}".format(event['id']))
        run_event(event)

    def try_reschedule_for_cloud_check():
        if "preponeWhenCloudy" not in event:
            return False
        
        cloudy_settings = event["preponeWhenCloudy"]
        cloudy_offset = timedelta(minutes=cloudy_settings["minutes_offset"])
        cloudy_threshold = cloudy_settings["threshold"]

        time_str = (now + time_until - cloudy_offset).strftime("%H:%M")
        logger.debug("Schedule cloud check for {}".format(time_str))
        schedule.every().day.at(time_str).do(execute_cloud_check_once, event=event, cloudy_offset=cloudy_offset,
                                                                       cloudy_threshold=cloudy_threshold, timezone=timezone)
        return True

    while True:
        now = datetime.now(timezone)
        dayIndex = datetime.today().weekday()
        currentDay = all_days[dayIndex]

        for event in events:
            [hour, minute] = [int(x) for x in event["time"].split(":")]

            # Is event disabled?
            if ("disabled" in event and event["disabled"]) or ("disabledUntil" in event and
                                        event["disabledUntil"] >= now.strftime('%Y-%m-%d')):
                continue

            # Skip event if we already processed it or if the day and time is not matching
            if event["id"] in executed_scheduled_events or not is_valid_time_and_day():
                continue

            if "ifExecutedEventID" in event and event["ifExecutedEventID"] not in executed_scheduled_events:
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
                elif not try_reschedule_for_cloud_check():
                    reschedule_event()
            elif "waitForSunset" in event:
                is_dark, time_until = get_sun_info()
                if is_dark:
                    run_scheduled_event()
                elif not try_reschedule_for_cloud_check():
                    reschedule_event()
            else:
                run_scheduled_event()

        schedule.run_pending()

        # Reset data structures keeping track of which events have run
        if now.hour == 0 and now.minute == 0:
            executed_scheduled_events.clear()
        sleep(60)


# There is no other way to schedule only once other than doing this.
def execute_once(event):
    logger.debug("Executing rescheduled event {}".format(event['id']))
    run_event(event)

    executed_scheduled_events[event['id']] = True
    return schedule.CancelJob


def execute_cloud_check_once(event, cloudy_offset, cloudy_threshold, timezone):
    logger.debug("Executing cloud check for event {}".format(event['id']))
    if weather_manager.is_cloudy(cloudy_threshold):
        run_event(event)
        executed_scheduled_events[event['id']] = True
    else:
        now = datetime.now(timezone)
        time_str = (now + cloudy_offset).strftime("%H:%M")
        schedule.every().day.at(time_str).do(execute_once, event=event)

    return schedule.CancelJob


# Returns if it is dark or light, and the time until the next sunrise/sunset
# True means it is dark, False means it is sunny
def get_sun_info() -> tuple[bool, timedelta]:
    city_name = config.TIMEZONE.split('/')[1]
    city = Location(lookup(city_name, database()))
    today = date.today()
    sun = city.sun(date=today, local=True)
    timezone = pytz.timezone(config.TIMEZONE)
    current_time = datetime.now(timezone)
    # Is it between sunrise and sunset?
    if sun["sunrise"] <= current_time <= sun["sunset"]:
        if sun["sunset"] >= current_time:
            event = "sunset"
            timediff = sun[event] - current_time
        if sun["sunset"] <= current_time:
            event = "sunrise"
            timediff = current_time - sun[event]

        logger.debug("It's sunny outside, {} in {}".format(event, timediff))
        return (False, timediff)
    else:
        sun_tomorrow = city.sun(date=today + timedelta(days=1), local=True)
        timediff = sun_tomorrow["sunrise"] - current_time
        logger.debug("It's dark outside, {} until sunrise".format(timediff))
        return (True, timediff)


def init_logger():
    log_level = logging.DEBUG
    log_filename = 'log.txt'
    logger = logging.getLogger('root')
    logger.setLevel(log_level)
    formatter = logging.Formatter('%(asctime)s %(message)s')

    def customTime(*args):
        timezone = pytz.timezone(config.TIMEZONE)
        now = datetime.now(timezone)
        return now.timetuple()

    formatter.converter = customTime

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


if __name__ == "__main__":
    # Setup logging to file
    logger = init_logger()

    # Load variables
    activities = config.get_activities() # Parse activity configuration.

    channel_handlers: dict[str, ChannelHandler] = dict(ChainMap(*map(lambda listener: dict([(channel, listener) for channel in listener.channels]),
                                                                     [clazz() for clazz in ChannelHandler.__subclasses__()])))

    thread = threading.Thread(target=run_schedule, args=())
    thread.daemon = True
    thread.start()

    logger.debug("Server started")

    from waitress import serve
    # Most common browsers send 6 requests at once. We don't really care
    # that much since we're waiting for the response from the tradfri
    # gateway either way, but increasing the number of threads to 6 gets
    # rid of some warning logs about waiting requests.
    serve(app, host="0.0.0.0", port=3000, threads=6)
