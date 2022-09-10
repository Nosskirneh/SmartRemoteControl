from pyowm.owm import OWM
from datetime import datetime, timedelta

class WeatherManager:
    def __init__(self, key, lat, lon):
        owm = OWM(key)
        self.mgr = owm.weather_manager()
        self.lat = lat
        self.lon = lon
        self.last_updated = None

    def load_data(self):
        self.data = self.mgr.one_call(lat=self.lat, lon=self.lon, exclude='current,minutely,daily,alerts')
        self.last_updated = datetime.now()

    def is_cloudy(self, threshold, hour_offset=0):
        assert hour_offset < 46
        # Only update every 20 minutes at most
        if not self.last_updated or datetime.now() > self.last_updated + timedelta(minutes=20):
            self.load_data()
        # There seems to be two hours before the current hour here
        # even though the docs state otherwise
        return self.data.forecast_hourly[2 + hour_offset].clouds > threshold
