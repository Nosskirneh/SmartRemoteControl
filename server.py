#!/usr/bin/env python
import sys
import os
import fnmatch
sys.path.append("/storage/.python")
import serial
import time
from flask import *
import config
import requests
from wakeonlan import wol


# Create flask application.
app = Flask(__name__)

# Get activity configuration.
activities = config.get_activities()


if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
	REQ_ADDR = "http://192.168.0.20:1234"
	MAC_ADDR = "08-2E-5F-0E-81-56"

	tv_IsOn = False

	# Find the right COM port
	matches = []

	for root, dirnames, filenames in os.walk('/dev'):
	    for filename in fnmatch.filter(filenames, 'ttyUSB*'):
	        matches.append(os.path.join(root, filename))

	ser = serial.Serial()
	ser.port = matches[0]
	ser.baudrate = 9600
	ser.timeout = 0
	ser.xonxoff = False     #disable software flow control
	ser.rtscts = False     #disable hardware (RTS/CTS) flow control
	ser.dsrdtr = False       #disable hardware (DSR/DTR) flow control

	if ser.isOpen():
		print "### Serial conenction already open!"
	else:
		try:
			ser.open()
			print "### Serial connection open!"
		except Exception, e:
			print "### Error open serial port: " + str(e)

	print ser



@app.route('/')
def root():
	return render_template('index.html', activities=activities)

@app.route('/activity/<int:index>', methods=['POST'])
def activity(index):
	
	global tv_IsOn

	# IR remote
	for IRcode in activities[index].get('IR', []):

		# don't switch power when already on/off
		if (IRcode == "SONY: C A90" and tv_IsOn == True and activities[index].get('name') == "PLEX ON"):
			print "TV is already on."
			break
		elif (IRcode == "SONY: C A90" and tv_IsOn == False and \
			(activities[index].get('name') == "PLEX ON" or activities[index].get('name') == "TV ON/OFF")):
			tv_IsOn = True

		if (IRcode == "SONY: C A90" and tv_IsOn == False and activities[index].get('name') == "PLEX OFF"):
			print "TV is already off."
			break
		elif (IRcode == "SONY: C A90" and tv_IsOn == True and \
			(activities[index].get('name') == "PLEX OFF" or activities[index].get('name') == "TV ON/OFF")):
			tv_IsOn = False

		ser.write(IRcode + ";")
		print ser.readlines()

		if (IRcode != activities[index].get('IR', [])[-1]): #Don't delay on last item
			# Wait ~300 milliseconds between codes.
			time.sleep(0.3)

	# 433 MHz
	for MHZcode in activities[index].get('MHZ', []):
		ser.write(MHZcode + ";")

	# HyperionWeb
	for LEDcode in activities[index].get('LED', []):
		if (LEDcode == "CLEAR"):
			r = requests.post(REQ_ADDR + "/do_clear", data={'clear':'clear'})
			r = requests.post(REQ_ADDR + "/set_value_gain", data={'valueGain':'30'})
		if (LEDcode == "BLACK"):
			r = requests.post(REQ_ADDR + "/set_color_name", data={'colorName':'black'})
			r = requests.post(REQ_ADDR + "/set_value_gain", data={'valueGain':'100'})

	# Wake on LAN
	for WOLcode in activities[index].get('WOL', []):
		wol.send_magic_packet(MAC_ADDR)



	return 'OK'


if __name__ == '__main__':
	# Create a server listening for external connections on the default
	# port 5000.  Enable debug mode for better error messages and live
	# reloading of the server on changes.  Also make the server threaded
	# so multiple connections can be processed at once (very important
	# for using server sent events).
	app.run(host='0.0.0.0', debug=True, threaded=True) 
