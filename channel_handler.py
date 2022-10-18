import logging
import os
import fnmatch
import serial
import requests
import wakeonlan as wol
from typing import Union, List
from abc import ABC, abstractmethod

class ChannelHandler(ABC):
    def __init__(self, channels: List[str], logger: logging.Logger):
        self.channels = channels
        self.logger = logger

    @abstractmethod
    def handle_code(self, channel: str, data: Union[str, dict]):
        pass

class WakeOnLanHandler(ChannelHandler):
    def __init__(self, **kwargs):
        super().__init__(["WOL"], kwargs)

    def handle_code(self, _: str, data: Union[str, dict]):
        wol.send_magic_packet(data)

class HyperionWebHandler(ChannelHandler):
    REQ_ADDR = "http://localhost:1234"

    def __init__(self, **kwargs):
        super().__init__(["LED"], kwargs)

    def handle_code(self, _, data: dict):
        try:
            requests.post(self.REQ_ADDR + "/" + data["endpoint"], data=data["data"])
        except requests.ConnectionError:
            self.logger.error("HyperionWeb unavailable (503)")
            pass

class ArduinoHandler(ChannelHandler):
    def __init__(self, **kwargs):
        super().__init__(["MHZ433", "NEXA", "IR"], kwargs)

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

