import datetime
from typing import Tuple

def get_hour_minute(time: str) -> Tuple[str, str]:
    return [int(x) for x in time.split(":")]

def time_in_range(start: datetime.time, end: datetime.time, time: datetime.time) -> bool:
    """Returns true if time is in the range [start, end]"""
    if start <= end:
        return start <= time <= end
    else:
        return start <= time or time <= end
