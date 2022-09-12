import os
import fnmatch
import serial
import requests
import wakeonlan as wol
from typing import Union

class ChannelHandler:
    def __init__(self, channels):
        self.channels = channels

    def handle_simple_code(self, channel: str, data: str) -> Union[None, tuple[str, int]]:
        raise NotImplementedError

class WakeOnLanHandler(ChannelHandler):
    def __init__(self):
        super().__init__(["WOL"])

    def handle_simple_code(self, channel: str, data: str) -> Union[None, tuple[str, int]]:
        wol.send_magic_packet(data)
        return True

class HyperionWebHandler(ChannelHandler):
    REQ_ADDR = "http://192.168.0.20:1234"

    def __init__(self):
        super().__init__(["LED"])

    def handle_simple_code(self, _, data) -> Union[None, tuple[str, int]]:
        if data == "CLEAR":
            try:
                requests.post(self.REQ_ADDR + "/do_clear", data={"clear":"clear"})
                requests.post(self.REQ_ADDR + "/set_value_gain", data={"valueGain":"20"})
            except requests.ConnectionError:
                return "Service Unavailable", 503
        if data == "BLACK":
            try:
                requests.post(self.REQ_ADDR + "/set_color_name", data={"colorName":"black"})
                requests.post(self.REQ_ADDR + "/set_value_gain", data={"valueGain":"100"})
            except requests.ConnectionError:
                return "Service Unavailable", 503

class ArduinoHandler(ChannelHandler):
    def __init__(self):
        super().__init__(["MHZ433", "NEXA", "IR"])

        if os.environ.get("DEBUG") is None:
            # Initialize COM-port
            self.ser = self.init_comport()

    def handle_simple_code(self, channel, data) -> Union[None, tuple[str, int]]:
        if channel == "IR":
            self.ser_write(data + ";") # Send IR code to Arduino

        elif channel == "MHZ433" or channel == "NEXA":
            self.ser_write(channel + ": " + data + ";")

    def ser_write(self, data):
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

