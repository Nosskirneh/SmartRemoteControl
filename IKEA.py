import json
import uuid
from pytradfri import Gateway
from pytradfri.api.libcoap_api import APIFactory
from time import sleep

import numpy

CONFIG_FILE = "tradfri_psk.conf"

class RGB(numpy.ndarray):
  @classmethod
  def from_str(cls, hex):
    return numpy.array([int(hex[i:i+2], 16) for i in (0, 2, 4)]).view(cls)

  def __str__(self):
    self = self.astype(numpy.uint8)
    return ''.join(format(n, 'x') for n in self)

class TradfriHandler:
    def __init__(self, gateway_hostname, key):
        conf = self.load_psk(CONFIG_FILE)

        try:
            identity = conf[gateway_hostname].get("identity")
            psk = conf[gateway_hostname].get("key")
            api_factory = APIFactory(host=gateway_hostname, psk_id=identity, psk=psk)
        except KeyError:
            identity = uuid.uuid4().hex
            api_factory = APIFactory(host=gateway_hostname, psk_id=identity)

        psk = api_factory.generate_psk(key)

        conf[gateway_hostname] = {"identity": identity, "key": psk}
        self.save_psk(CONFIG_FILE, conf)
        self.api = api_factory.request
        self.gateway = Gateway()

    @staticmethod
    def load_psk(filename):
        try:
            with open(filename, encoding="utf-8") as fdesc:
                return json.loads(fdesc.read())
        except FileNotFoundError:
            return {}

    @staticmethod
    def save_psk(filename, config):
        data = json.dumps(config, sort_keys=True, indent=4)
        with open(filename, "w", encoding="utf-8") as fdesc:
            fdesc.write(data)

    @staticmethod
    def average_hex_color(colors):
        if len(colors) == 1:
            return colors[0]
        rgb_colors = [RGB.from_str(hex) for hex in colors]
        return (numpy.sum(rgb_colors, axis=0) // len(rgb_colors)).view(RGB)


    def export_group(self, group):
        # These properties exists on the group as well, but they are incorrect for some reason
        hex_colors, states = zip(*map(lambda light: (light.light_control.lights[0].hex_color,
                                                     light.light_control.lights[0].state),
                                      filter(lambda device: device.has_light_control,
                                             self.api(group.members()))
                                      ))
        return {
            "name": group.name,
            "id": group.id,
            "state": any(states),
            "dimmer": group.dimmer,
            "color": '#' + str(self.average_hex_color(list(hex_colors)))
        }

    def export_groups(self):
        return list(map(self.export_group, self.get_groups()))

    def get_groups(self):
        devices_commands = self.api(self.gateway.get_groups())
        return self.api(devices_commands)

    def get_group(self, group_id):
        return self.api(self.gateway.get_group(group_id))

    def set_state(self, group_id, new_state):
        light_group = self.get_group(group_id)
        if not light_group:
            return False
        self.api(light_group.set_state(new_state))
        return True

    def set_dimmer(self, group_id, value):
        light_group = self.get_group(group_id)
        if not light_group:
            return False
        self.api(light_group.set_dimmer(value, transition_time=1))
        return True

    def set_hex_color(self, group_id, value):
        light_group = self.get_group(group_id)
        if not light_group:
            return False
        self.api(light_group.set_hex_color(value, transition_time=1))
        return True
