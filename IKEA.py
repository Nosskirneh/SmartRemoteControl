from datetime import datetime, timedelta
import json
from logging import Logger
import uuid
from pytradfri import Gateway
from pytradfri.api.libcoap_api import APIFactory
from pytradfri.group import Group
from pytradfri.command import Command
from pytradfri.error import RequestTimeout
from typing import Callable, Iterable, Tuple, Union

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
    
    @staticmethod
    def get_hex_color_dimmer_state_light_control(group_members) -> Tuple[Iterable, Iterable, Iterable]:
        # These properties exists on the group as well, but they are incorrect for some reason
        return zip(*map(lambda light: (light.light_control.lights[0].hex_color,
                                       light.light_control.lights[0].state,
                                       light.light_control.lights[0].dimmer),
                        filter(lambda device: device.has_light_control,
                                group_members)
                        ))

    def export_group(self, group: Group) -> dict[str, Union[str, int]]:
        hex_colors, states, dimmers = self.get_hex_color_dimmer_state_light_control(self.group_members[group.id])
        return {
            "name": group.name,
            "id": group.id,
            "state": any(states),
            "dimmer": dimmers[0],
            "color": '#' + str(self.average_hex_color(list(hex_colors)))
        }

    def export_groups(self) -> list[str]:
        return list(map(self.export_group, self.get_groups()))
    
    def load_group_members(self, group: Group):
        try:
            self.group_members[group.id] = self.api(group.members())
        except RequestTimeout:
            self.logger.error("Trådfri timed out!")

    def load_groups(self):
        self.groups: dict[int, Group] = {}
        self.group_members: dict[int, Iterable] = {}
        self.dirty_group_ids: set[int] = set()
        try:
            devices_commands = self.api(self.gateway.get_groups())
            groups = self.api(devices_commands)
            for group in groups:
                self.groups[group.id] = group
                self.load_group_members(group)
            self.groups_last_updated = datetime.now()
        except RequestTimeout:
            self.logger.error("Trådfri timed out!")
            self.groups_last_updated = None

    def load_group(self, group_id: int):
        try:
            group = self.api(self.gateway.get_group(group_id))
            self.groups[group.id] = group
            self.load_group_members(group)
        except RequestTimeout:
            self.logger.error("Trådfri timed out!")

    def get_state(self, group_id: int, refresh_data=True) -> int:
        if refresh_data:
            self.load_group(group_id)
        _, states, _ = self.get_hex_color_dimmer_state_light_control(self.group_members[group_id])
        return any(states)

    def get_dimmer(self, group_id: int, refresh_data=True) -> int:
        if refresh_data:
            self.load_group(group_id)
        g_dim_value = self.groups[group_id].dimmer
        _, _, dim_values = self.get_hex_color_dimmer_state_light_control(self.group_members[group_id])
        if (dim_values[0] != g_dim_value):
            # Someone used the normal remote, and something is broken (either IKEAs gateway or pytradfri),
            # and the lights in the group does not have the dim value of the group itself. This results
            # in that we cannot use set with the group's value, because it already believes it has set it.
            # To solve this, we simply set a dirty flag and use that later to modify the value.
            self.dirty_group_ids.add(group_id)
        elif group_id in self.dirty_group_ids:
            self.dirty_group_ids.remove(group_id)
        return dim_values[0]

    def get_groups(self) -> Iterable[Group]:
        # Only update every 5 minutes at most
        if (len(self.groups) == 0 or not self.groups_last_updated or
            datetime.now() > self.groups_last_updated + timedelta(minutes=5)):
            self.load_groups()
        return self.groups.values()

    def set_state(self, group_id: int, new_state: bool) -> bool:
        return self.run_api_command_for_group(lambda lg: lg.set_state(new_state),
                                              lambda lg: self.update_group(lg, 'state', int(new_state)),
                                              group_id)

    def set_dimmer(self, group_id: int, value: int) -> bool:
        if group_id in self.dirty_group_ids:
            value -= 1
        return self.run_api_command_for_group(lambda lg: lg.set_dimmer(value, transition_time=3),
                                              lambda lg: self.update_group(lg, 'dimmer', value),
                                              group_id)

    def set_hex_color(self, group_id: int, value: str) -> bool:
        return self.run_api_command_for_group(lambda lg: lg.set_hex_color(value, transition_time=1),
                                              lambda lg: self.update_group(lg, 'color_hex', value),
                                              group_id)

    def run_api_command_for_group(self,
                                  command_function: Callable[[Group], Command],
                                  update_function: Callable[[Group], None],
                                  group_id: int) -> bool:
        light_group = self.groups[group_id]
        try:
            self.api(command_function(light_group))
        except RequestTimeout:
            return False
        update_function(light_group)
        return True

    # This is a bit hacky, but allows to update the state of the device without
    # refetching it through the gateway
    def update_group(self, group: Group, key: str, new_value: Union[int, str]):
        setattr(group.raw, key, new_value)

        for member in self.group_members[group.id]:
            if not member.has_light_control:
                continue
            for light in member.light_control.lights:
                setattr(light.raw, key, new_value)
