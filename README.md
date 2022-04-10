Smart Remote Control
====================

Use a Arduino Uno and a Raspberry pi to control 433 MHz relay switches (NEXA and others), IKEA Trådfri, IR and WOL devices and HyperionWeb.

![page](/preview/preview.png)

Uses Arduino libraries:
* A modified version of [IRremote](https://github.com/tdicola/Arduino_IRremote)
* [RCSwitch](https://github.com/sui77/rc-switch)
* [NexaCtrl](https://github.com/calle-gunnarsson/NexaCtrl)

All of these are located in this repo under Arduino/libraries.


## Installation
pip3 install pyserial wakeonlan pytradfri aiocoap schedule holidays astral flask numpy waitress

coap-client is required to be built:
https://raspberry-valley.azurewebsites.net/CoAP-Getting-Started/
