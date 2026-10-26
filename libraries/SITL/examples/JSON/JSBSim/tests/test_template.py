'''
Tests for test-aircraft/template: it loads, every binding resolves, and its subsystems
behave as documented. Guards the template against edits that silently break it.

Run from libraries/SITL/examples/JSON/JSBSim with: python -m pytest tests

AP_FLAKE8_CLEAN
'''

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

pytest.importorskip('jsbsim')

import controls  # noqa: E402
import jsbsim_json_bridge as jb  # noqa: E402

LBF_TO_N = 4.44822


def template():
    d = jb.find_aircraft_dir('template')
    m = jb.JSBSimModel(jb.DEFAULT_ROOT, 'template', jb.read_location('CMAC', jb.DEFAULT_ROOT), 0.5, 0.0,
                       aircraft_dir=d, start_engines=False)
    rows = controls.load(os.path.join(d, 'template', 'Controls.xml'))[0]
    return m, rows


def run(f, seconds):
    for _ in range(int(seconds * 1200)):
        f.run()


def test_every_servo_output_is_bound():
    m, rows = template()
    controls.check_properties(rows, m.has_property)
    assert sorted(r.channel + 1 for r in rows) == list(range(1, 14))
    assert not any(r.mirrored for r in rows)


def test_rests_on_its_wheels_at_the_design_mass_and_cg():
    m, _ = template()
    f = m.fdm
    assert f['inertia/weight-lbs'] * 0.45359 == pytest.approx(2.5, abs=0.01)
    assert f['inertia/cg-x-in'] * 0.0254 == pytest.approx(0.50, abs=0.005)
    assert abs(f['attitude/theta-deg']) < 2
    assert all(f['gear/unit[%u]/WOW' % i] for i in range(3))


def test_edf_spool_and_static_thrust():
    m, _ = template()
    f = m.fdm
    f['fcs/left-brake-cmd-norm'] = f['fcs/right-brake-cmd-norm'] = 1
    f['fcs/edf-throttle-cmd-norm'] = 1
    run(f, 0.3)
    # one time constant after a step; also proves the model was loaded at SITL's timestep
    assert f['edf/fan-norm'] == pytest.approx(0.632, abs=0.02)
    run(f, 2.7)
    u = f['velocities/u-aero-fps'] * 0.3048
    assert f['edf/thrust-lbs'] * LBF_TO_N / (1 - u / 60) == pytest.approx(19.6, abs=0.2)


def test_nose_and_main_gear_retract_independently():
    m, rows = template()
    f = m.fdm
    b = controls.Bindings(rows, m.set_property, m.start_engine)
    pwm = [1500, 1500, 1000, 1500, 1500, 1000, 1000, 1000, 1000, 1000, 2000, 1500, 1000, 0, 0, 0]
    agl_down = f['position/h-agl-ft']
    for _ in range(1200):
        b.apply(pwm, m.dt())
        f.run()
    assert f['gear/unit[0]/pos-norm'] == pytest.approx(0, abs=0.01)
    assert f['gear/unit[1]/pos-norm'] == pytest.approx(1, abs=0.01)
    assert f['gear/unit[2]/pos-norm'] == pytest.approx(1, abs=0.01)
    # with the nose wheel up, the nose rests on the airframe
    assert f['attitude/theta-deg'] < -5
    # half-way PWM leaves the leg half-way; a wheel that is not fully down carries no load
    # (JSBSim leaves its WOW flag stale, so check that the aircraft sits on its belly)
    pwm[10] = 1500
    for _ in range(1200):
        b.apply(pwm, m.dt())
        f.run()
    assert f['gear/unit[1]/pos-norm'] == pytest.approx(0.5, abs=0.01)
    assert f['position/h-agl-ft'] < agl_down


@pytest.mark.parametrize('servo_pwm, rate, sign', [
    ({1: 1800, 2: 1800}, 'p', 1),        # ArduPlane roll right
    ({4: 1800, 5: 1800}, 'q', 1),        # V-tail pitch up
    ({4: 1800, 5: 1200}, 'r', 1),        # V-tail yaw right
])
def test_ardupilot_commands_move_the_aircraft_the_right_way(servo_pwm, rate, sign):
    m, rows = template()
    f = m.fdm
    f['ic/h-agl-ft'] = 100 / 0.3048
    f['ic/vt-fps'] = 18 / 0.3048
    f.run_ic()
    b = controls.Bindings(rows, m.set_property, m.start_engine)
    pwm = [1500, 1500, 1450, 1500, 1500, 1000, 1000, 1000, 1000, 2000, 2000, 1500, 1000, 0, 0, 0]
    for _ in range(60):
        b.apply(pwm, m.dt())
        f.run()
    before = f['velocities/%s-rad_sec' % rate]
    for servo, value in servo_pwm.items():
        pwm[servo - 1] = value
    for _ in range(300):
        b.apply(pwm, m.dt())
        f.run()
    assert (f['velocities/%s-rad_sec' % rate] - before) * sign > 0.2
