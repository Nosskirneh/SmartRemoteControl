#!/usr/bin/env python3
import operator
import sys
import os
from threading import Thread
from time import sleep
from typing import Callable, List, Tuple
from flask import *
from http import HTTPStatus
import config
from credentials import *
import base64
from collections import ChainMap
from IKEA import TradfriHandler
from scheduler import Scheduler
from weather import WeatherManager
from channel_handler import ChannelHandler, SonyTVAPIHandler
import util

from datetime import datetime, time
import holidays
from collections import OrderedDict
import pytz

import logging
from logging.handlers import RotatingFileHandler

# Create flask application.
app = Flask(__name__)

def get_current_date_string():
    return datetime.now().strftime('%Y-%m-%dT%H:%M')

def respond(http_status: HTTPStatus, content: str = None) -> Tuple[str, int]:
    return http_status.phrase if content == None else content, http_status.value

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
    return activity(group, return_activity_index(name, group))

@app.route("/checkAuth", methods=["GET"])
def check_auth():
    if is_auth_ok():
        return respond(HTTPStatus.OK)
    return respond(HTTPStatus.UNAUTHORIZED)


@app.route("/status", methods=["GET"])
def return_online():
    return respond(HTTPStatus.OK)


@app.route("/commands", methods=["GET"])
def get_commands():
    # Check authorization
    if not is_auth_ok():
        return respond(HTTPStatus.UNAUTHORIZED)
    commands = activities.copy()
    commands["tradfri_groups"] = tradfri_handler.export_groups()
    return jsonify(commands)

## Scheduling
@app.route("/schedule/run/<string:identifier>", methods=["POST"])
def manually_run_event(identifier):
    if not is_auth_ok():
        return respond(HTTPStatus.UNAUTHORIZED)

    _, event = return_schedule_index(identifier)
    run_event(event)
    return respond(HTTPStatus.OK)


@app.route("/schedule/enable/<string:identifier>", methods=["POST"])
def set_enabled(identifier):
    if not is_auth_ok():
        return respond(HTTPStatus.UNAUTHORIZED)

    _, event = return_schedule_index(identifier)
    event["disabled"] = request.form.get('enabled') != "true"

    config.save_activities(activities)
    return respond(HTTPStatus.OK)


@app.route("/schedule/new", methods=["POST"])
def configure_new():
    return configure_schedule(None)

@app.route("/schedule/configure/<string:identifier>", methods=["POST"])
def configure_existing(identifier):
    return configure_schedule(identifier)

def configure_schedule(identifier: str) -> Tuple[str, int]:
    if not is_auth_ok():
        return respond(HTTPStatus.UNAUTHORIZED)

    form = request.form

    id = form.get('id')
    time = form.get('time')
    days = form.get('days')
    groups = form.get('groups')

    if not id or not time or time == '' or not groups:
        return respond(HTTPStatus.BAD_REQUEST, "You need to provide name, time and commands.")

    groups = json.loads(groups)
    if len(groups) == 0:
        return respond(HTTPStatus.BAD_REQUEST, "You need to provide commands.")

    if identifier == None and any(event["id"] == id for event in activities["scheduled"]):
        return respond(HTTPStatus.BAD_REQUEST, "An event with that name does already exist.")

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
        _, event = return_schedule_index(identifier)
        fill_event()
        result["data"] = event

    config.save_activities(activities)
    return respond(HTTPStatus.OK, jsonify(result))


@app.route("/schedule/delete/<string:identifier>", methods=["POST"])
def delete(identifier):
    if not is_auth_ok():
        return respond(HTTPStatus.UNAUTHORIZED)

    index = return_schedule_index(identifier)

    if index == -1:
        return respond(HTTPStatus.NOT_FOUND, "Event does not exist: {}".format(identifier))

    activities["scheduled"].pop(index)

    config.save_activities(activities)
    return respond(HTTPStatus.OK)


def run_activity(group: dict, index: int):
    for activity_group in activities["groups"]:
        if activity_group["name"] != group:
            continue

        activity = activity_group["activities"][index]
        for code_configuration in activity["codes"]:
            channel = code_configuration["channel"]
            if channel not in channel_handlers:
                logger.error("Channel {} not found!".format(channel))
                continue

            channel_handlers[channel].handle_code(channel, code_configuration["data"])


@app.route("/activity/<group>/<int:index>", methods=["POST"])
def activity(group, index):
    # Check authorization
    if not is_auth_ok():
       return respond(HTTPStatus.UNAUTHORIZED)

    if index == -1:
        return respond(HTTPStatus.NOT_IMPLEMENTED)

    run_activity(group, index)
    return respond(HTTPStatus.OK)

## Trådfri
@app.route("/tradfri/<int:group_id>/dimmer/<int:value>", methods=["POST"])
def tradfri_dimmer(group_id, value):
    # Check authorization
    if not is_auth_ok():
       return respond(HTTPStatus.UNAUTHORIZED)

    if not tradfri_handler.set_dimmer(group_id, value):
        return respond(HTTPStatus.NOT_FOUND)
    return respond(HTTPStatus.OK)


@app.route("/tradfri/<int:group_id>/color/<string:value>", methods=["POST"])
def tradfri_color(group_id, value):
    # Check authorization
    if not is_auth_ok():
       return respond(HTTPStatus.UNAUTHORIZED)

    if value.startswith('#'):
        value = value.lstrip('#')

    if not tradfri_handler.set_hex_color(group_id, value):
        return respond(HTTPStatus.NOT_FOUND)
    return respond(HTTPStatus.OK)


@app.route("/tradfri/<int:group_id>/<string:on_off>", methods=["POST"])
def tradfri_on_off(group_id, on_off):
    # Check authorization
    if not is_auth_ok():
       return respond(HTTPStatus.UNAUTHORIZED)

    if on_off not in ("on", "off"):
        return respond(HTTPStatus.METHOD_NOT_ALLOWED, "Use the on/off endpoint")

    if not tradfri_handler.set_state(group_id, on_off == "on"):
        return respond(HTTPStatus.NOT_FOUND, "Device not found")
    return respond(HTTPStatus.OK)


## Webhooks
@app.route("/webhook/invoke/<string:webhook_id>", methods=["POST"])
def webhooks_exec(webhook_id):
    # Check authorization
    if not is_auth_ok():
       return respond(HTTPStatus.UNAUTHORIZED)

    webhooks = activities["webhooks"]
    if webhook_id not in webhooks:
        return respond(HTTPStatus.NOT_FOUND, "No such webhook configured: {}".format(webhook_id))

    # Verify that we should run this now
    def parse_operator_value(input: str) -> Tuple[Callable, int]:
        ops = {
            '=' : operator.eq,
            '!=' : operator.ne,
            '>=' : operator.ge,
            '<=' : operator.le,
            '>' : operator.gt,
            '<' : operator.lt,
        }
        head = input.rstrip('0123456789')
        tail = input[len(head):]
        return ops[head], int(tail)

    def exec_webhook_part(part: dict) -> bool:
        if "conditional" in part:
            conditional = part["conditional"]
            if "within-time" in conditional:
                within_time = conditional["within-time"]
                start_hour, start_minute = util.get_hour_minute(within_time["start"])
                end_hour, end_minute = util.get_hour_minute(within_time["end"])

                now = datetime.now(pytz.timezone(config.TIMEZONE))
                start = time(start_hour, start_minute)
                end = time(end_hour, end_minute)

                if not util.time_in_range(start, end, now.time()):
                    return False # Condition was not met

            if "tradfri" in conditional:
                for device, conditions in conditional["tradfri"].items():
                    has_updated = False
                    if "light-state" in conditions:
                        light_state_cond = conditions["light-state"]
                        has_updated = True
                        if tradfri_handler.get_state(int(device)) != light_state_cond:
                            return False # Condition was not met

                    if "dimmer" in conditions:
                        current_value = tradfri_handler.get_dimmer(int(device), not has_updated)
                        op, cond_value = parse_operator_value(conditions["dimmer"])
                        if not op(current_value, cond_value):
                            return False # Condition was not met

            if "sony-bravia-tv" in conditional and "is-on" in conditional["sony-bravia-tv"]:
                required = conditional["sony-bravia-tv"]["is-on"]
                is_on = SonyTVAPIHandler.is_on()
                if required != is_on:
                    return False

        # If we got here, all conditions were met
        run_plain_and_tradfri(part["actions"])
        return True

    webhook = webhooks[webhook_id]
    for part in webhook:
        exec_webhook_part(part)
    return respond(HTTPStatus.OK)


### METHODS ###
def is_auth_ok(auth: str = None) -> bool:
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
    return user == USERNAME and pw == PASSWORD

def run_plain(commands: List):
    for data, group in commands:
        index = return_activity_index(data, group)
        if index != -1:
            thread = Thread(target=run_activity, args=(group, index))
            thread.start()
            yield thread

def run_tradfri(device_config: dict):
    for device_id_str in device_config:
        device_commands = device_config[device_id_str]
        device_id = int(device_id_str)
        if "light-state" in device_commands:
            tradfri_handler.set_state(device_id, device_commands["light-state"])
        if "color" in device_commands:
            tradfri_handler.set_hex_color(device_id, device_commands["color"])
        if "dimmer" in device_commands:
            tradfri_handler.set_dimmer(device_id, int(device_commands["dimmer"]))

def run_plain_and_tradfri(container: dict):
    if "plain" in container:
        threads = run_plain(container["plain"])

    if "tradfri" in container:
        run_tradfri(container["tradfri"])

    if threads:
        for thread in threads:
            thread.join()

def run_event(event: dict):
    if "commands" in event:
        run_plain_and_tradfri(event["commands"])

    if "fireOnce" in event and event["fireOnce"]:
        event["disabled"] = True
        config.save_activities(activities)


def return_schedule_index(identifier: str) -> Tuple[int, dict]:
    count = 0
    for event in activities["scheduled"]:
        if event["id"] == identifier:
            return count, event
        count += 1
    return -1, None

def return_activity_index(command: str, group: str) -> int:
    count = 0
    for activity in activities["groups"]:
        g = activity["name"]
        if g != group:
            continue
        for act in activity["activities"]:
            n = act["name"]
            if n == command:
                return count
            count += 1
    return -1


def init_logger() -> logging.Logger:
    log_level = logging.DEBUG
    log_filename = 'log.txt'
    logger = logging.getLogger('root')
    logger.setLevel(log_level)
    formatter = logging.Formatter('%(asctime)s %(message)s')

    def customTime(*_):
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
    # Since the holiday object cannot be created with a years parameter if the CountryHoliday is used,
    # we have to do a simple check just to populate the years property. The other solution would be to
    # use the language constructor, for example .SE(years=yyyy)
    all_holidays = holidays.CountryHoliday(config.HOLIDAY_COUNTRY)
    datetime.now() in all_holidays

    activities = config.get_activities() # Parse activity configuration

    # Setup logging to file
    logger = init_logger()

    tradfri_handler = TradfriHandler(IKEA_GATEWAY_IP, IKEA_GATEWAY_KEY, logger)
    weather_manager = WeatherManager(OPEN_WEATHER_MAP_KEY, OPEN_WEATHER_MAP_LAT, OPEN_WEATHER_MAP_LON)
    scheduler = Scheduler(logger, lambda event: run_event(event),
                          lambda threshold: weather_manager.is_cloudy(threshold),
                          activities["scheduled"], pytz.timezone(config.TIMEZONE), all_holidays)
    scheduler.start()

    channel_handlers: dict[str, ChannelHandler] = dict(ChainMap(*map(lambda listener: dict([(channel, listener) for channel in listener.channels]),
                                                                     [clazz(logger=logger) for clazz in ChannelHandler.__subclasses__()])))

    logger.debug("Server started")

    from waitress import serve
    # Most common browsers send 6 requests at once. We don't really care
    # that much since we're waiting for the response from the tradfri
    # gateway either way, but increasing the number of threads to 6 gets
    # rid of some warning logs about waiting requests.
    serve(app, host="0.0.0.0", port=3000, threads=6)
