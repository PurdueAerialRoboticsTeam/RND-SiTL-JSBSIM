'''
ArduPilot SITL JSON protocol: servo packets in, JSON state out, and the
lockstep bookkeeping between them. No JSBSim here, so it can be tested alone.

The packet formats are defined in libraries/SITL/SIM_JSON.h and
libraries/SITL/examples/JSON/readme.md.

AP_FLAKE8_CLEAN
'''

import json
import struct
from dataclasses import dataclass

MAGIC_16 = 18458
MAGIC_32 = 29569

_HEADER = struct.Struct('<HHI')
_FORMATS = {
    MAGIC_16: struct.Struct('<HHI16H'),
    MAGIC_32: struct.Struct('<HHI32H'),
}


@dataclass(frozen=True)
class ServoPacket:
    frame_rate: int
    frame_count: int
    pwm: tuple


def parse_servo_packet(data):
    '''return a ServoPacket, or None if data is not a SITL servo packet'''
    if len(data) < _HEADER.size:
        return None
    magic = _HEADER.unpack_from(data)[0]
    fmt = _FORMATS.get(magic)
    if fmt is None or len(data) != fmt.size:
        return None
    fields = fmt.unpack(data)
    return ServoPacket(frame_rate=fields[1], frame_count=fields[2], pwm=fields[3:])


def build_servo_packet(frame_rate, frame_count, pwm):
    '''the inverse of parse_servo_packet, used by tests'''
    magic = MAGIC_32 if len(pwm) == 32 else MAGIC_16
    return _FORMATS[magic].pack(magic, frame_rate, frame_count, *pwm)


STEP = 'step'
REPEAT = 'repeat'
RESET = 'reset'


class Lockstep:
    '''
    Decides what to do with each servo packet so that one SITL frame is
    exactly one physics step:

    - a new frame_count is a new frame: step once and reply;
    - the same frame_count again is SITL resending after a timeout: reply
      with the previous state, do not step;
    - a lower frame_count means SITL restarted: reset the physics, then step.
    '''

    def __init__(self):
        self.last_count = None
        self.last_reply = None

    def classify(self, frame_count):
        if self.last_count is None:
            return STEP
        if frame_count == self.last_count:
            return REPEAT
        if frame_count < self.last_count:
            return RESET
        return STEP

    def record(self, frame_count, reply):
        self.last_count = frame_count
        self.last_reply = reply


def newest_packet(packets):
    '''
    from a burst of (packet, address) pairs, return the newest valid one and
    how many distinct new frames were skipped to get there
    '''
    newest = None
    counts = set()
    for pkt, addr in packets:
        if pkt is None:
            continue
        counts.add(pkt.frame_count)
        if newest is None or pkt.frame_count >= newest[0].frame_count:
            newest = (pkt, addr)
    skipped = max(0, len(counts) - 1)
    return newest, skipped


def encode_state(state):
    '''
    encode a state dict as one line for SIM_JSON. SIM_JSON finds keys with
    strstr(), so "velocity" must come before "velocity_wind".
    '''
    msg = {
        'timestamp': state['timestamp'],
        'imu': {
            'gyro': list(state['gyro']),
            'accel_body': list(state['accel_body']),
        },
        'latitude': state['latitude'],
        'longitude': state['longitude'],
        'altitude': state['altitude'],
        'attitude': list(state['attitude']),
        'velocity': list(state['velocity']),
        'velocity_wind': list(state['velocity_wind']),
        'airspeed': state['airspeed'],
    }
    return ('\n' + json.dumps(msg, separators=(',', ':')) + '\n').encode('ascii')
