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
        self.data = self.mgr.one_call(lat=self.lat, lon=self.lon, exclude='minutely,hourly,daily,alerts')
        self.last_updated = datetime.now()

    def is_cloudy(self, threshold):
        # Only update every 20 minutes at most
        if not self.last_updated or datetime.now() > self.last_updated + timedelta(minutes=20):
            self.load_data()
        return self.data.current.clouds > threshold
