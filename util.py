import datetime
from typing import Tuple, Union
import json
import os

def get_hour_minute(time: str) -> Tuple[str, str]:
    return [int(x) for x in time.split(":")]

def time_in_range(start: datetime.time, end: datetime.time, time: datetime.time) -> bool:
    """Returns true if time is in the range [start, end]"""
    if start <= end:
        return start <= time <= end
    else:
        return start <= time or time <= end

def load_json_file(filename: str) -> Union[dict, list]:
    with open(filename) as file:
        return json.load(file)

def is_debug() -> bool:
    return os.environ.get("DEBUG") is not None
