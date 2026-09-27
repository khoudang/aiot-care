"""Three-node command contract; UI percentages become PWM bytes on the wire."""

DEVICES = {
    "patient": {"fan", "buzzer"},  # Light GPIO has not been documented yet.
    "living": {"light", "fan", "auto"},
    "kitchen": {"light", "buzzer", "window", "exhaust"},
}


def build_command(room, device, state=None, value=None):
    room = "patient" if room == "bed" else room
    if device not in DEVICES.get(room, set()):
        raise ValueError("Unsupported room/device or unassigned hardware")
    if state is not None and not (type(state) is bool or
                                  type(state) is int and state in (0, 1)):
        raise ValueError("state must be boolean or 0/1")
    if value is not None:
        if device != "fan" or type(value) is not int or not 0 <= value <= 100:
            raise ValueError("Only fan accepts integer percent 0..100")
    if state is None and value is None:
        raise ValueError("Missing state/value")
    command = {"cmd": device}
    if state is not None:
        command["state"] = int(state)
        command[device] = bool(state)
    if value is not None:
        command["value"] = (value * 255 + 50) // 100
    return room, command
