'''
Tests for the SITL JSON protocol helpers. No JSBSim needed.

Run from libraries/SITL/examples/JSON/JSBSim with: python -m pytest tests

AP_FLAKE8_CLEAN
'''

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sitl_protocol import (  # noqa: E402
    Lockstep,
    REPEAT,
    RESET,
    STEP,
    build_servo_packet,
    encode_state,
    newest_packet,
    parse_servo_packet,
)


def test_parse_16_channel_packet():
    pwm = tuple(range(1000, 1016))
    pkt = parse_servo_packet(build_servo_packet(1200, 42, pwm))
    assert pkt.frame_rate == 1200
    assert pkt.frame_count == 42
    assert pkt.pwm == pwm


def test_parse_32_channel_packet():
    pwm = tuple(range(1100, 1132))
    pkt = parse_servo_packet(build_servo_packet(400, 7, pwm))
    assert len(pkt.pwm) == 32
    assert pkt.pwm == pwm


def test_parse_rejects_other_data():
    good = build_servo_packet(1200, 1, [1500] * 16)
    assert parse_servo_packet(b'') is None
    assert parse_servo_packet(good[:-2]) is None
    assert parse_servo_packet(b'\x00\x00' + good[2:]) is None


def test_lockstep_rules():
    ls = Lockstep()
    assert ls.classify(0) == STEP
    ls.record(0, b'a')
    assert ls.classify(0) == REPEAT
    assert ls.classify(1) == STEP
    assert ls.classify(5) == STEP
    ls.record(5, b'b')
    assert ls.classify(2) == RESET
    assert ls.last_reply == b'b'


def test_newest_packet_keeps_highest_count():
    p = [parse_servo_packet(build_servo_packet(1200, n, [1500] * 16)) for n in (3, 5, 4)]
    newest, skipped = newest_packet([(p[0], 'a'), (None, 'x'), (p[1], 'b'), (p[2], 'c')])
    assert newest[0].frame_count == 5
    assert newest[1] == 'b'
    assert skipped == 2


def test_newest_packet_resends_are_not_skips():
    p = parse_servo_packet(build_servo_packet(1200, 9, [1500] * 16))
    newest, skipped = newest_packet([(p, 'a'), (p, 'a')])
    assert newest[0].frame_count == 9
    assert skipped == 0


def test_newest_packet_nothing_valid():
    assert newest_packet([(None, 'a')]) == (None, 0)


def sample_state():
    return {
        'timestamp': 1.25,
        'gyro': (0.1, -0.2, 0.3),
        'accel_body': (0.0, 0.0, -9.81),
        'latitude': -35.363261,
        'longitude': 149.16523,
        'altitude': 585.3,
        'attitude': (0.01, 0.2, 6.1),
        'velocity': (1.0, 2.0, -0.5),
        'velocity_wind': (0.0, 0.0, 0.0),
        'airspeed': 2.2,
    }


def test_encode_state_is_one_json_line():
    data = encode_state(sample_state())
    assert data.startswith(b'\n') and data.endswith(b'\n')
    assert data.count(b'\n') == 2
    msg = json.loads(data.decode())
    assert msg['timestamp'] == 1.25
    assert msg['imu']['accel_body'] == [0.0, 0.0, -9.81]
    assert msg['latitude'] == -35.363261


def test_encode_state_key_order_for_strstr():
    # SIM_JSON looks keys up with strstr(): the first "velocity" must be the
    # velocity field, not the start of "velocity_wind"
    data = encode_state(sample_state())
    assert data.find(b'"velocity"') < data.find(b'"velocity_wind"')
