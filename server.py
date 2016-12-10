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
import time
from astral import Astral
import pytz


# Create flask application.
app = Flask(__name__)

### APP ROUTES ###
@app.route('/')
def root():
    return render_template('index.html', activities=activities)

@app.route('/command', methods=['POST'])
def command():
    name  = request.args.get('name')
    group = request.args.get('group')
    return activity(return_index(name, group))

@app.route('/status', methods=['GET'])
def returnOnline():
    return 'OK', 200

@app.route('/getCommands', methods=['GET'])
def getCommands():
    # Check authorization
    if not isAuthOK():
       return 'Unauthorized', 401
    return jsonify(activities)

@app.route('/activity/<int:index>', methods=['POST'])
def activity(index):
    global tv_IsOn
    if index == -1:
        return 'Not Implemented', 501

    # Check authorization
    if not isAuthOK():
       return 'Unauthorized', 401

    for activity, groups in activities[index][0].iteritems():
        for group, codes in groups.iteritems():
            for code in codes:
                if group == "IR":           # IR section
                    if (code == "SONY: C A90" and tv_IsOn == True and activity == "PLEX ON"):
                        # don't switch power when already on/off
                        print "TV is already on."
                        break
                    elif (code == "SONY: C A90" and tv_IsOn == False and \
                        (activity == "PLEX ON" or activity == "TV ON/OFF")):
                        tv_IsOn = True

                    if (code == "SONY: C A90" and tv_IsOn == False and activity == "PLEX OFF"):
                        print "TV is already off."
                        break
                    elif (code == "SONY: C A90" and tv_IsOn == True and \
                        (activity == "PLEX OFF" or activity == "TV ON/OFF")):
                        tv_IsOn = False

                    ser.write(code + ";")   # Send IR code to Arduino
                    print ser.readlines()

                    if (code != codes[-1]): # Don't delay after last item
                        time.sleep(0.3)     # Wait ~300 milliseconds between codes.

                elif (group == "MHZ433" or group == "NEXA"): # MHZ433 & NEXA section
                    ser.write(group + ": " + code + ";")

                elif (group == "LED"):      # HyperionWeb
                    if (code == "CLEAR"):
                        try:
                            r = requests.post(REQ_ADDR + "/do_clear", data={'clear':'clear'})
                            r = requests.post(REQ_ADDR + "/set_value_gain", data={'valueGain':'20'})
                        except requests.ConnectionError:
                            return 'Service Unavailable', 503
                    if (code == "BLACK"):
                        try:
                            r = requests.post(REQ_ADDR + "/set_color_name", data={'colorName':'black'})
                            r = requests.post(REQ_ADDR + "/set_value_gain", data={'valueGain':'100'})
                        except requests.ConnectionError:
                            return 'Service Unavailable', 503

                elif (group == "WOL"):      # Wake on LAN
                    wol.send_magic_packet(MAC_ADDR)

    return 'OK', 200


### METHODS ###
def isAuthOK():
    auth = request.headers['Authorization'].split()[1]
    user, pw = base64.b64decode(auth).split(":")
    if not (user == username and pw == password):
        return False
    return True

def run_command(commands):
    auth = base64.b64encode(username + ":" + password)
    with app.test_client() as client:
        for cmd in commands:
            sleep(1)
            client.post('/activity/' + str(return_index(cmd[0], cmd[1])),
                headers={'Authorization': "Basic " + auth});

def morning():
    commands = [["1 ON", "mhz433"]]
    lights_on(commands)

def morning_off():
    while isitdark() is True:
        sleep(1)
    commands = [["1 OFF", "mhz433"]]
    lights_on(commands)

def evening():
    commands = [["4 ON", "mhz433"], ["1 ON", "mhz433"], ["1 ON", "nexa"], ["2 ON", "nexa"], ["3 ON", "nexa"]]
    lights_on(commands)

def evening_off():
    commands = [["4 OFF", "mhz433"], ["1 OFF", "mhz433"], ["1 ON", "nexa"], ["2 OFF", "nexa"], ["3 OFF", "nexa"]]
    run_command(commands)

def lights_on(commands):
    while isitdark() is False:
        sleep(1)
    run_command(commands)

def isitdark():
    city_name = "Stockholm"
    a = Astral()
    city = a[city_name]
    today_date = date.today()
    sun = city.sun(date=today_date, local=True)
    utc = pytz.UTC
    if sun['sunrise'] <= utc.localize(datetime.utcnow()) <= sun['sunset']:
        if sun['sunset'] >= utc.localize(datetime.utcnow()):
            event = "sunset"
            timediff = sun['sunset'] - utc.localize(datetime.utcnow())
        if sun['sunset'] <= utc.localize(datetime.utcnow()):
            event = "sunrise"
            timediff = utc.localize(datetime.utcnow()) - sun['sunrise']
        print("It's sunny outside: not trigerring (%s in %s)" % (event, timediff))
        return False
    else:
        print("It's dark outside: triggering")
        return True

def run_schedule():
    """ Method that runs forever """
    # Turn on/off lights
    schedule.every().day.at("15:00").do(evening)
    schedule.every().day.at("02:00").do(evening_off)

    schedule.every().day.at("06:00").do(morning)
    schedule.every().day.at("07:30").do(morning_off)

    while True:
        schedule.run_pending()
        sleep(1)

def return_index(cmd, grp):
    for index, act in enumerate(activities):
        n = act[0].keys()[0] # name
        g = act[1]           # group
        if n == cmd and g == grp:
            return index
    return -1

def init_comport():
    # Find the right USB port
    matches = []

    for root, dirnames, filenames in os.walk('/dev'):
        for filename in fnmatch.filter(filenames, 'ttyUSB*'):
            matches.append(os.path.join(root, filename))

    ser          = serial.Serial()
    ser.port     = matches[0]
    ser.baudrate = 9600
    ser.timeout  = 0
    ser.xonxoff  = False       # disable software flow control
    ser.rtscts   = False       # disable hardware (RTS/CTS) flow control
    ser.dsrdtr   = False       # disable hardware (DSR/DTR) flow control

    if ser.isOpen():
        print "### Serial conenction already open!"
    else:
        try:
            ser.open()
            print " * Serial connection open!"
        except Exception, e:
            print " * Error open serial port: " + str(e)
    return ser

# This will only run once, not twice
if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    # Load variables
    activities = config.get_activities() # Parse activity configuration.
    REQ_ADDR = "http://192.168.0.20:1234"
    MAC_ADDR = "08-2E-5F-0E-81-56"
    tv_IsOn = False

    # Initialize COM-port 
    ser = init_comport()

    # Scheduler thread - run_schedule()
    thread = threading.Thread(target=run_schedule, args=())
    thread.daemon = True # Daemonize thread
    thread.start()       # Start the execution


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=True, threaded=True) 
