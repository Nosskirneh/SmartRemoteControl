import os
import json

# Change to directory of script so relative file references work.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Name of configuration file.
FILE_NAME = 'activities.json'

def get_activities():
    with open(FILE_NAME) as data_file:    
        return json.load(data_file)