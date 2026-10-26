'''
Tests for the bridge's lockstep loop and servo handling, with a fake model,
plus a short run of the real Rascal model when the jsbsim module is present.

Run from libraries/SITL/examples/JSON/JSBSim with: python -m pytest tests

AP_FLAKE8_CLEAN
'''

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

pytest.importorskip('jsbsim')

import controls  # noqa: E402
import jsbsim_json_bridge as jb  # noqa: E402
from sitl_protocol import build_servo_packet, parse_servo_packet  # noqa: E402


class FakeModel:
    def __init__(self):
        self.t = 0.0
        self.rate_hz = None
        self.steps = 0
        self.resets = 0

    def reset(self):
        self.t = 0.0
        self.resets += 1

    def set_rate(self, rate_hz):
        self.rate_hz = rate_hz

    def dt(self):
        return 1.0 / self.rate_hz

    def step(self):
        self.t += 1.0 / self.rate_hz
        self.steps += 1
        return True

    def sim_time(self):
        return self.t

    def state(self):
        return {
            'timestamp': self.t,
            'gyro': (0, 0, 0),
            'accel_body': (0, 0, -9.81),
            'latitude': 0.0,
            'longitude': 0.0,
            'altitude': 0.0,
            'attitude': (0, 0, 0),
            'velocity': (0, 0, 0),
            'velocity_wind': (0, 0, 0),
            'airspeed': 0.0,
        }


def packet(count, rate=1200):
    return parse_servo_packet(build_servo_packet(rate, count, [1500] * 16))


def timestamp(reply):
    return json.loads(reply.decode())['timestamp']


def make_bridge():
    model = FakeModel()
    bindings = controls.Bindings(jb.default_rows(0.14), lambda name, value: None)
    return model, jb.Bridge(model, bindings, jb.Stats(0))


def test_resend_is_answered_without_stepping():
    model, bridge = make_bridge()
    replies = [bridge.handle(packet(n)) for n in (0, 1, 1, 2)]
    assert model.steps == 3
    assert len(replies) == 4
    assert replies[2] == replies[1]
    assert timestamp(replies[3]) > timestamp(replies[2])


def test_sitl_restart_resets_physics():
    model, bridge = make_bridge()
    replies = [bridge.handle(packet(n)) for n in (5, 6, 0)]
    assert model.resets == 1
    assert timestamp(replies[2]) < timestamp(replies[1])


def test_timestep_follows_frame_rate():
    model, bridge = make_bridge()
    bridge.handle(packet(0, rate=400))
    assert model.rate_hz == 400
    bridge.handle(packet(1, rate=1200))
    assert model.rate_hz == 1200


def test_default_rows_match_the_jsbsim_frame():
    rows = jb.default_rows(0.14)
    assert [(r.channel, r.properties[0]) for r in rows] == [
        (0, 'fcs/aileron-cmd-norm'), (1, 'fcs/elevator-cmd-norm'),
        (2, 'fcs/throttle-cmd-norm'), (3, 'fcs/rudder-cmd-norm')]
    # plane-jsbsim.parm reverses elevator and rudder itself, so nothing is mirrored here
    assert not any(r.mirrored or r.invert for r in rows)


def test_parse_home_and_location():
    assert jb.parse_home('1,2,3,4') == [1.0, 2.0, 3.0, 4.0]
    lat, lng, alt, hdg = jb.read_location('CMAC', jb.DEFAULT_ROOT)
    assert (lat, lng, alt, hdg) == (-35.363261, 149.165230, 584.0, 353.0)
    with pytest.raises(ValueError):
        jb.read_location('NoSuchPlace', jb.DEFAULT_ROOT)


@pytest.fixture(scope='module')
def rascal():
    home = jb.read_location('CMAC', jb.DEFAULT_ROOT)
    return jb.JSBSimModel(jb.DEFAULT_ROOT, 'Rascal', home, 1.3, 13.0)


def rascal_bridge(model):
    rows = jb.default_rows(0.14)
    controls.check_properties(rows, model.has_property)
    return jb.Bridge(model, controls.Bindings(rows, model.set_property, model.start_engine), jb.Stats(0))


def test_rascal_runs_in_lockstep(rascal):
    bridge = rascal_bridge(rascal)
    pwm = [1500, 1500, 1000, 1500] + [0] * 12
    first = json.loads(bridge.handle(parse_servo_packet(build_servo_packet(1200, 0, pwm))).decode())
    assert first['timestamp'] == pytest.approx(1.0 / 1200)
    # on the ground at home: altitude is home plus the height of the gear
    assert 584.0 < first['altitude'] < 586.0
    assert first['imu']['accel_body'][2] < -9.0

    pwm[2] = 2000
    for n in range(1, 6001):
        msg = json.loads(bridge.handle(parse_servo_packet(build_servo_packet(1200, n, pwm))).decode())
    assert msg['timestamp'] == pytest.approx(6001 / 1200.0)
    # five seconds at full throttle on the runway gets the Rascal rolling
    assert msg['airspeed'] > 10.0


def test_rascal_reset_restarts_time(rascal):
    bridge = rascal_bridge(rascal)
    pwm = [1500, 1500, 1000, 1500] + [0] * 12
    for n in (10, 11):
        bridge.handle(parse_servo_packet(build_servo_packet(1200, n, pwm)))
    msg = json.loads(bridge.handle(parse_servo_packet(build_servo_packet(1200, 0, pwm))).decode())
    assert msg['timestamp'] == pytest.approx(1.0 / 1200)


def test_aircraft_are_found_in_test_aircraft_then_autotest():
    assert jb.find_aircraft_dir('c172p') == jb.AIRCRAFT_SEARCH[0]
    assert jb.find_aircraft_dir('advanced_plane') == jb.AIRCRAFT_SEARCH[0]
    assert jb.find_aircraft_dir('Rascal') == jb.AIRCRAFT_SEARCH[1]
    assert jb.find_aircraft_dir('NoSuchPlane') is None
