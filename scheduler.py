from logging import Logger
from typing import Callable, Iterable
import pytz
import schedule
from datetime import datetime, date, timedelta
from astral.geocoder import lookup, database
from astral.location import Location
from time import sleep
import threading
import util

class Scheduler:
    def __init__(self,
                 logger: Logger,
                 execute_callback: Callable[[dict], None],
                 cloud_check: Callable[[int], bool],
                 scheduled_events: dict,
                 timezone: pytz.timezone,
                 all_holidays: Iterable):
        self.logger = logger
        self.execute_callback = execute_callback
        self.cloud_check = cloud_check
        self.scheduled_events = scheduled_events
        self.timezone = timezone
        self.all_holidays = all_holidays
        self.executed_scheduled_events = {}

    def start(self):
        self.thread = threading.Thread(target=self.run_schedule, args=())
        self.thread.daemon = True
        self.thread.start()

    def run_schedule(self):
        all_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        def is_valid_time_and_day() -> bool:
            # If today is a holiday and all holidays should be excluded
            if "excludeAllHolidays" in event and event["excludeAllHolidays"] and now.date() in self.all_holidays:
                return False

            if "excludedHolidays" in event:
                # If today is a holiday and this holiday should be excluded
                if now.date() in self.all_holidays and dict(self.all_holidays.items())[now.date()] in event["excludedHolidays"]:
                    return False

            return now.hour == hour and now.minute == minute and \
                ("days" not in event or currentDay in event["days"])

        def reschedule_event():
            time_str = (now + time_until).strftime("%H:%M")
            self.logger.debug("Reschedule for {}".format(time_str))
            schedule.every().day.at(time_str).do(self.execute_once, event=event)

        def run_scheduled_event():
            self.executed_scheduled_events[event['id']] = True
            self.logger.debug("Executing scheduled event {}".format(event['id']))
            self.execute_callback(event)

        def try_reschedule_for_cloud_check() -> bool:
            if "preponeWhenCloudy" not in event:
                return False

            cloudy_settings = event["preponeWhenCloudy"]
            cloudy_offset = timedelta(minutes=cloudy_settings["minutes_offset"])
            cloudy_threshold = cloudy_settings["threshold"]

            time_str = max(now, now + time_until - cloudy_offset).strftime("%H:%M")
            self.logger.debug("Schedule cloud check for {}".format(time_str))
            schedule.every().day.at(time_str).do(self.execute_cloud_check_once,
                                                 event=event, cloudy_offset=cloudy_offset,
                                                 cloudy_threshold=cloudy_threshold)
            return True

        while True:
            now = datetime.now(self.timezone)
            dayIndex = datetime.today().weekday()
            currentDay = all_days[dayIndex]

            for event in self.scheduled_events:
                hour, minute = util.get_hour_minute(event["time"])

                # Is event disabled?
                if ("disabled" in event and event["disabled"]) or ("disabledUntil" in event and
                                            event["disabledUntil"] >= now.strftime('%Y-%m-%d')):
                    continue

                # Skip event if we already processed it or if the day and time is not matching
                if event["id"] in self.executed_scheduled_events or not is_valid_time_and_day():
                    continue

                if "ifExecutedEventID" in event and event["ifExecutedEventID"] not in self.executed_scheduled_events:
                    continue

                if "onDark" in event:
                    is_dark, _ = self.get_sun_info()
                    if is_dark:
                        run_scheduled_event()
                elif "onSunny" in event:
                    is_dark, _ = self.get_sun_info()
                    if not is_dark:
                        run_scheduled_event()
                elif "waitForSunrise" in event:
                    is_dark, time_until = self.get_sun_info()
                    if not is_dark:
                        run_scheduled_event()
                    elif not try_reschedule_for_cloud_check():
                        reschedule_event()
                elif "waitForSunset" in event:
                    is_dark, time_until = self.get_sun_info()
                    if is_dark:
                        run_scheduled_event()
                    elif not try_reschedule_for_cloud_check():
                        reschedule_event()
                else:
                    run_scheduled_event()

            schedule.run_pending()

            # Reset data structures keeping track of which events have run
            if now.hour == 0 and now.minute == 0:
                self.executed_scheduled_events.clear()
            sleep(60)

    # There is no other way to schedule only once other than doing this.
    def execute_once(self, event: dict):
        self.logger.debug("Executing rescheduled event {}".format(event['id']))
        self.execute_callback(event)

        self.executed_scheduled_events[event['id']] = True
        return schedule.CancelJob

    def execute_cloud_check_once(self, event: dict, cloudy_offset: int, cloudy_threshold: int):
        self.logger.debug("Executing cloud check for event {}".format(event['id']))
        if self.cloud_check(cloudy_threshold):
            self.execute_callback(event)
            self.executed_scheduled_events[event['id']] = True
        else:
            now = datetime.now(self.timezone)
            time_str = (now + cloudy_offset).strftime("%H:%M")
            schedule.every().day.at(time_str).do(self.execute_once, event=event)

        return schedule.CancelJob

    # Returns if it is dark or light, and the time until the next sunrise/sunset
    # True means it is dark, False means it is sunny
    def get_sun_info(self) -> tuple[bool, timedelta]:
        city_name = self.timezone.zone.split('/')[1]
        city = Location(lookup(city_name, database()))
        today = date.today()
        sun = city.sun(date=today, local=True)
        current_time = datetime.now(self.timezone)
        # Is it between sunrise and sunset?
        if sun["sunrise"] <= current_time <= sun["sunset"]:
            if sun["sunset"] >= current_time:
                event = "sunset"
                timediff = sun[event] - current_time
            if sun["sunset"] <= current_time:
                event = "sunrise"
                timediff = current_time - sun[event]

            self.logger.debug("It's sunny outside, {} in {}".format(event, timediff))
            return (False, timediff)
        else:
            sun_tomorrow = city.sun(date=today + timedelta(days=1), local=True)
            timediff = sun_tomorrow["sunrise"] - current_time
            self.logger.debug("It's dark outside, {} until sunrise".format(timediff))
            return (True, timediff)
