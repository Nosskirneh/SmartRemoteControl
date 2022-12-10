import logging
import os
import fnmatch
import serial
import requests
import wakeonlan as wol
from typing import Union, List
from abc import ABC, abstractmethod
from util import load_json_file

class ChannelHandler(ABC):
    def __init__(self, channels: List[str], logger: logging.Logger):
        self.channels = channels
        self.logger = logger

    @abstractmethod
    def handle_code(self, channel: str, data: Union[str, dict]):
        pass

class WakeOnLanHandler(ChannelHandler):
    def __init__(self, **kwargs):
        super().__init__(["WOL"], **kwargs)

    def handle_code(self, _: str, data: Union[str, dict]):
        wol.send_magic_packet(data)

class HyperionWebHandler(ChannelHandler):
    REQ_ADDR = "http://localhost:1234"

    def __init__(self, **kwargs):
        super().__init__(["LED"], **kwargs)

    def handle_code(self, _, data: dict):
        try:
            requests.post(self.REQ_ADDR + "/" + data["endpoint"], data=data["data"])
        except (requests.ConnectionError, requests.Timeout):
            self.logger.error("HyperionWeb unavailable (503)")
            pass

class SonyTVAPIHandler(ChannelHandler):
    REQ_ADDR = "http://192.168.1.140"
    # This list of commands is based on the response from a Sony TV when
    # calling the cers/api/getRemoteCommandList endpoint.
    COMMANDS = load_json_file("sony_bravia.json")
    HEADERS = {"X-CERS-DEVICE-ID": "rpi", "X-CERS-DEVICE-INFO": "Linux/Python", 'Content-Type': 'application/xml'}

    def __init__(self, **kwargs):
        super().__init__(["SONY"], **kwargs)

    def handle_code(self, _, command: str):
        if command not in self.COMMANDS:
            return False
        command_info = self.COMMANDS[command]
        try:
            if command_info["type"] == "ircc":
                data = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:X_SendIRCC xmlns:u="urn:schemas-sony-com:service:IRCC:1">
      <IRCCCode>%s</IRCCCode>
    </u:X_SendIRCC>
  </s:Body>
</s:Envelope>""" % (command_info["value"])
                requests.post(self.REQ_ADDR + "/IRCC", data=data, headers=self.HEADERS)
            elif command_info["type"] == "url":
                requests.get(self.REQ_ADDR + command_info["value"], headers=self.HEADERS)
        except (requests.ConnectionError, requests.Timeout):
            self.logger.error("Sony TV unavailable (503)")
            pass

    @classmethod
    def is_on(self) -> bool:
        try:
            # When the TV has been in standby for some minutes,
            # it is no longer responding, hence the short timeout
            response = requests.get(self.REQ_ADDR + "/cers/api/getStatus",
                                    headers=self.HEADERS, timeout=1)
        except (requests.ConnectionError, requests.Timeout)
            pass
            return False

        # When the TV is off, the value is Others
        return "ExtInput" in response.content.decode("utf-8")

class ArduinoHandler(ChannelHandler):
    def __init__(self, **kwargs):
        super().__init__(["MHZ433", "NEXA", "IR"], **kwargs)

        if os.environ.get("DEBUG") is None:
            # Initialize COM-port
            self.ser = self.init_comport()

    def handle_code(self, channel, data):
        if channel == "IR":
            self.ser_write(data + ";") # Send IR code to Arduino

        elif channel == "MHZ433" or channel == "NEXA":
            self.ser_write(channel + ": " + data + ";")

    def ser_write(self, data: str):
        if os.environ.get("DEBUG") is None:
            self.ser.write(data.encode())

    @staticmethod
    def init_comport():
        # Find the right USB port
        matches = []

        for root, _, filenames in os.walk("/dev"):
            for filename in fnmatch.filter(filenames, "ttyUSB*"):
                matches.append(os.path.join(root, filename))

        ser          = serial.Serial()
        ser.port     = matches[-1]
        ser.baudrate = 9600
        ser.timeout  = 0
        ser.xonxoff  = False       # Disable software flow control
        ser.rtscts   = False       # Disable hardware (RTS/CTS) flow control
        ser.dsrdtr   = False       # Disable hardware (DSR/DTR) flow control

        if ser.isOpen():
            print("### Serial conenction already open!")
        else:
            try:
                ser.open()
                print(" * Serial connection open!")
            except Exception as e:
                print(" * Error open serial port: " + str(e))
        return ser

