from datetime import datetime, timedelta
import json
from logging import Logger
import uuid
from pytradfri import Gateway
from pytradfri.api.libcoap_api import APIFactory
from pytradfri.group import Group
from pytradfri.command import Command
from pytradfri.error import RequestTimeout
from typing import Any, Callable, Iterable

import numpy

CONFIG_FILE = "tradfri_psk.conf"

class RGB(numpy.ndarray):
  @classmethod
  def from_str(cls, hex: str):
    return numpy.array([int(hex[i:i+2], 16) for i in (0, 2, 4)]).view(cls)

  def __str__(self):
    self = self.astype(numpy.uint8)
    return ''.join(format(n, 'x') for n in self)

class TradfriHandler:
    def __init__(self, gateway_hostname: str, key: str, logger: Logger):
        self.logger = logger
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
        self.load_groups()

    @staticmethod
    def load_psk(filename: str) -> dict:
        try:
            with open(filename, encoding="utf-8") as fdesc:
                return json.loads(fdesc.read())
        except FileNotFoundError:
            return {}

    @staticmethod
    def save_psk(filename: str, config: dict):
        data = json.dumps(config, sort_keys=True, indent=4)
        with open(filename, "w", encoding="utf-8") as fdesc:
            fdesc.write(data)

    @staticmethod
    def average_hex_color(colors: list[str]):
        if len(colors) == 1:
            return colors[0]
        rgb_colors = [RGB.from_str(hex) for hex in colors]
        return (numpy.sum(rgb_colors, axis=0) // len(rgb_colors)).view(RGB)


    def export_group(self, group: Group) -> dict[str, Any]:
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

    def export_groups(self) -> list[str]:
        return list(map(self.export_group, self.get_groups()))

    def load_groups(self):
        try:
            devices_commands = self.api(self.gateway.get_groups())
            groups = self.api(devices_commands)
            self.groups = {group.id:group for group in groups}
            self.groups_last_updated = datetime.now()
        except RequestTimeout:
            self.logger.error("Trådfri timed out!")
            self.groups = {}
            self.groups_last_updated = None

    def get_groups(self) -> Iterable[Group]:
        # Only update every 5 minutes at most
        if (len(self.groups) == 0 or not self.groups_last_updated or
            datetime.now() > self.groups_last_updated + timedelta(minutes=5)):
            self.load_groups()
        return self.groups.values()

    def get_group(self, group_id: str) -> Group:
        if group_id in self.groups:
            return self.groups[group_id]
        group = self.api(self.gateway.get_group(group_id))
        self.groups[group_id] = group
        return group

    def set_state(self, group_id: int, new_state: bool) -> bool:
        return self.run_api_command_for_group(lambda lg: lg.set_state(new_state),
                                              group_id)

    def set_dimmer(self, group_id: int, value: int) -> bool:
        return self.run_api_command_for_group(lambda lg: lg.set_dimmer(value, transition_time=1),
                                              group_id)

    def set_hex_color(self, group_id: int, value: str) -> bool:
        return self.run_api_command_for_group(lambda lg: lg.set_hex_color(value, transition_time=1),
                                              group_id)

    def run_api_command_for_group(self,
                                  command_function: Callable[[Group], Command],
                                  group_id: int) -> bool:
        light_group = self.get_group(group_id)
        if not light_group:
            return False
        self.api(command_function(light_group))
        return True