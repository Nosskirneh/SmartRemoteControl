import os
import json

# Change to directory of script so relative file references work.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

HOLIDAY_COUNTRY = 'SE'
TIMEZONE = 'Europe/Stockholm'

# Name of configuration file.
FILE_NAME = 'activities.json'

def get_activities():
    with open(FILE_NAME) as file:
        return json.load(file)

def save_activities(activities):
    with open(FILE_NAME, 'w') as file:
        json.dump(activities, file, indent=2, separators=(',', ': '))
