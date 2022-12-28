import logging
import os
import fnmatch
import serial
import requests
from requests.exceptions import ConnectionError
import wakeonlan as wol
from typing import Union, List
from abc import ABC, abstractmethod
from util import load_json_file
import atexit
from rpi_rf import RFDevice

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
        except (ConnectionError, requests.Timeout):
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
        except (ConnectionError, requests.Timeout):
            self.logger.error("Sony TV unavailable (503)")
            pass

    @classmethod
    def is_on(self) -> bool:
        try:
            # When the TV has been in standby for some minutes,
            # it is no longer responding, hence the short timeout
            response = requests.get(self.REQ_ADDR + "/cers/api/getStatus",
                                    headers=self.HEADERS, timeout=1)
        except (ConnectionError, requests.Timeout):
            pass
            return False

        # When the TV is off, the value is Others
        return "ExtInput" in response.content.decode("utf-8")


class MHZ433Base(ABC):
    GPIO_PIN = 26
    PROTOCOL = 0
    REPEAT = 3
    PULSE_LENGTH = 350

    GPIO_DEVICE = RFDevice(GPIO_PIN)
    GPIO_DEVICE.enable_tx()
    GPIO_DEVICE.tx_repeat = REPEAT

    atexit.register(lambda: MHZ433Base.GPIO_DEVICE.cleanup())

    @staticmethod
    def split_data(data: str) -> Union[int, bool]:
        new_state, device = data.split(' ')
        return int(device) - 1, new_state == "OFF"

    def send_code(self, code: int):
        self.GPIO_DEVICE.tx_code(code, self.PROTOCOL, self.PULSE_LENGTH)


class RC5Handler(ChannelHandler, MHZ433Base):
    PROTOCOL = 1
    PULSE_LENGTH = 350
    REPEAT = 10

    def __init__(self, **kwargs):
        super().__init__(["MHZ433"], **kwargs)
        self.codes = [
            (1381717, 1381716), # 1-1
            (1394005, 1394004), # 1-2
            (1397077, 1397076), # 1-3
            (1397845, 1397844), # 1-4
            (4527445, 4527444), # 2-1
            (4539733, 4539732), # 2-2
            (4542805, 4542804), # 2-3
            (4543573, 4543572), # 2-4
            (5313877, 5313876), # 3-1
            (5326165, 5326164), # 3-2
            (5329237, 5329236), # 3-3
            (5330005, 5330004), # 3-4
            (5510485, 5510484), # 4-1
            (5522773, 5522772), # 4-2
            (5525845, 5525844), # 4-3
            (5526613, 5526612)  # 4-4
        ]

    def handle_code(self, _, command: str):
        device_index, new_state = super().split_data(command)
        code = self.codes[device_index][new_state]
        super().send_code(code)


class NexaHandler(ChannelHandler, MHZ433Base):
    PROTOCOL = 6
    PULSE_LENGTH = 250

    def __init__(self, **kwargs):
        super().__init__(["NEXA"], **kwargs)
        self.controller_id = "00110111111100010011011110"
        self.nexa_channels = ["00", "01", "10", "11"]
        self.switches = ["00", "01", "10", "11"]
        self.states = ["0", "1"]
        self.group = "0"

    def handle_code(self, _, command: str):
        device_index, new_state = super().split_data(command)
        code = int(self.controller_id + self.group + self.states[new_state] +
                   self.nexa_channels[0] + self.switches[device_index], 2)
        super().send_code(code)


class ArduinoHandler(ChannelHandler):
    def __init__(self, **kwargs):
        super().__init__(["IR"], **kwargs)

        if os.environ.get("DEBUG") is None:
            # Initialize COM-port
            self.ser = self.init_comport()

    def handle_code(self, _, data: str):
        self.ser_write(data + ";") # Send IR code to Arduino

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
