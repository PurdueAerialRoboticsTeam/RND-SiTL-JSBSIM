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

    def apply_servos(self, pwm):
        pass

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
    return model, jb.Bridge(model, jb.Stats(0))


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


def test_servo_lag_matches_first_order_filter():
    lag = jb.ServoLag(0.14)
    assert lag.apply(0.0, 0.001) == 0.0
    v = 0.0
    for _ in range(140):
        v = lag.apply(1.0, 0.001)
    # after one time constant a first-order lag is about 63% of the way
    assert 0.6 < v < 0.66


def test_servo_lag_zero_is_passthrough():
    lag = jb.ServoLag(0.0)
    assert lag.apply(0.3, 0.001) == 0.3
    assert lag.apply(-0.7, 0.001) == -0.7


def test_binding_normalisation_and_clamp():
    angle = jb.Binding(0, 'p', 'angle', 0)
    rng = jb.Binding(2, 'p', 'range', 0)
    assert angle.normalise(1500) == 0.0
    assert angle.normalise(2000) == 1.0
    assert angle.normalise(1000) == -1.0
    assert angle.normalise(2200) == 1.0
    assert rng.normalise(1000) == 0.0
    assert rng.normalise(1500) == 0.5
    assert rng.normalise(900) == 0.0


def test_parse_home_and_location():
    assert jb.parse_home('1,2,3,4') == [1.0, 2.0, 3.0, 4.0]
    lat, lng, alt, hdg = jb.read_location('CMAC', jb.DEFAULT_ROOT)
    assert (lat, lng, alt, hdg) == (-35.363261, 149.165230, 584.0, 353.0)
    with pytest.raises(ValueError):
        jb.read_location('NoSuchPlace', jb.DEFAULT_ROOT)


@pytest.fixture(scope='module')
def rascal():
    bindings = [jb.Binding(ch, prop, kind, 0.14) for ch, prop, kind in jb.DEFAULT_BINDINGS]
    home = jb.read_location('CMAC', jb.DEFAULT_ROOT)
    return jb.JSBSimModel(jb.DEFAULT_ROOT, 'Rascal', home, 1.3, 13.0, bindings)


def test_rascal_runs_in_lockstep(rascal):
    bridge = jb.Bridge(rascal, jb.Stats(0))
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
    bridge = jb.Bridge(rascal, jb.Stats(0))
    pwm = [1500, 1500, 1000, 1500] + [0] * 12
    for n in (10, 11):
        bridge.handle(parse_servo_packet(build_servo_packet(1200, n, pwm)))
    msg = json.loads(bridge.handle(parse_servo_packet(build_servo_packet(1200, 0, pwm))).decode())
    assert msg['timestamp'] == pytest.approx(1.0 / 1200)
