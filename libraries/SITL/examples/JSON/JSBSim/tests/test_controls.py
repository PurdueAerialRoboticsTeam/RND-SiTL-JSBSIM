'''
Tests for Controls.xml parsing and the PWM to property rules. No JSBSim needed.

Run from libraries/SITL/examples/JSON/JSBSim with: python -m pytest tests

AP_FLAKE8_CLEAN
'''

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import controls  # noqa: E402


def write(tmp_path, body, root='<control_bindings stack="ArduPilot">'):
    path = tmp_path / 'Controls.xml'
    path.write_text('<?xml version="1.0"?>\n%s\n%s\n</control_bindings>\n' % (root, body))
    return str(path)


# the ArduPilot rows of PteroSimAircrafts' c172p, plus rows for other stacks
C172P = '''
  <binding stack="PX4" channel="0" type="Motor" index="0" in="0 1" out="0 1" label="io320"/>
  <binding stack="ArduPilot" channel="0" type="Aileron" in="-1 1" out="-1 1" label="aileron"/>
  <binding stack="ArduPilot" channel="1" type="Elevator" in="-1 1" out="-1 1" label="elevator"/>
  <binding stack="ArduPilot" channel="2" type="Motor" index="0" in="0 1" out="0 1" label="io320"/>
  <binding stack="ArduPilot" channel="3" type="Rudder" in="-1 1" out="-1 1" label="rudder"/>
  <binding stack="ArduPilot" channel="3" property="fcs/steer-cmd-norm" in="-1 1" out="-1 1" invert="1" label="nosewheel"/>
  <binding stack="ArduPilot" channel="4" type="Flaps" in="0 1" out="0 1" label="flaps"/>
  <binding stack="Manual" channel="3" type="Rudder" in="-1 1" out="-1 1" invert="1" label="rudder"/>
'''


def by_property(rows):
    return {p: r for r in rows for p in r.properties}


def test_only_ardupilot_rows_are_used(tmp_path):
    rows, warnings = controls.load(write(tmp_path, C172P))
    assert len(rows) == 6
    assert warnings == []
    assert set(by_property(rows)) == {
        'fcs/aileron-cmd-norm', 'fcs/elevator-cmd-norm', 'fcs/throttle-cmd-norm[0]',
        'fcs/rudder-cmd-norm', 'fcs/steer-cmd-norm', 'fcs/flap-cmd-norm'}


def test_rows_without_stack_apply_to_ardupilot(tmp_path):
    rows, _ = controls.load(write(tmp_path, '<binding channel="7" property="fcs/x" in="-1 1" out="-1 1"/>'))
    assert rows[0].channel == 7


def test_elevator_and_rudder_channels_are_mirrored(tmp_path):
    rows = by_property(controls.load(write(tmp_path, C172P))[0])
    # ArduPlane above 1500 is nose up / yaw right; JSBSim +1 is trailing edge down / left
    assert rows['fcs/elevator-cmd-norm'].output(2000, 0.001) == -1.0
    assert rows['fcs/rudder-cmd-norm'].output(2000, 0.001) == -1.0
    # the nosewheel shares the rudder channel, so it sees the mirrored value and inverts it back
    assert rows['fcs/steer-cmd-norm'].output(2000, 0.001) == 1.0
    assert rows['fcs/aileron-cmd-norm'].output(2000, 0.001) == 1.0
    assert rows['fcs/throttle-cmd-norm[0]'].output(2000, 0.001) == 1.0


def test_property_rows_alone_are_not_mirrored(tmp_path):
    rows, _ = controls.load(write(tmp_path, '<binding channel="1" property="fcs/elevator-cmd-norm" in="-1 1" out="-1 1"/>'))
    assert rows[0].output(2000, 0.001) == 1.0


def test_normalisation_follows_the_input_range():
    servo = controls.Row(0, ['p'], (-1, 1), (-1, 1))
    motor = controls.Row(2, ['p'], (0, 1), (0, 1))
    assert servo.output(1500, 0.001) == 0.0
    assert servo.output(1000, 0.001) == -1.0
    assert servo.output(2200, 0.001) == 1.0
    assert motor.output(1000, 0.001) == 0.0
    assert motor.output(1500, 0.001) == 0.5
    assert motor.output(900, 0.001) == 0.0


def test_narrow_input_range_and_output_scaling():
    # PteroSim's quiver: ESC 1050..1950 arrives as 0.05..0.95 and is stretched to 0..1
    esc = controls.Row(0, ['p'], (0.05, 0.95), (0, 1))
    assert esc.output(1050, 0.001) == pytest.approx(0.0)
    assert esc.output(1950, 0.001) == pytest.approx(1.0)
    # orca: collective 0..1 read as 0..0.5 rad
    collective = controls.Row(2, ['p'], (0, 1), (0, 0.5))
    assert collective.output(2000, 0.001) == pytest.approx(0.5)


def test_invert_mirrors_inside_the_input_range():
    assert controls.Row(0, ['p'], (-1, 1), (-1, 1), invert=True).output(1750, 0.001) == pytest.approx(-0.5)
    assert controls.Row(0, ['p'], (0, 1), (0, 1), invert=True).output(1250, 0.001) == pytest.approx(0.75)


def test_lag_is_a_first_order_filter():
    row = controls.Row(0, ['p'], (0, 1), (0, 1), lag=0.14)
    assert row.output(1000, 0.001) == 0.0
    for _ in range(140):
        v = row.output(2000, 0.001)
    # after one time constant a first-order lag is about 63% of the way
    assert 0.6 < v < 0.66
    row.reset()
    assert row.output(2000, 0.001) == 1.0


def test_brake_type_writes_both_wheels(tmp_path):
    rows, _ = controls.load(write(tmp_path, '<binding channel="6" type="Brake"/>'))
    assert rows[0].properties == ('fcs/left-brake-cmd-norm', 'fcs/right-brake-cmd-norm')


def test_indexed_types_use_the_engine_index(tmp_path):
    rows, _ = controls.load(write(tmp_path, '''
      <binding channel="8" type="Motor" index="0"/>
      <binding channel="9" type="Motor" index="1"/>
      <binding channel="10" type="Collective" index="0" in="0 1" out="0 0.5"/>'''))
    assert [r.properties[0] for r in rows] == [
        'fcs/throttle-cmd-norm[0]', 'fcs/throttle-cmd-norm[1]', 'propulsion/engine[0]/collective-ctrl-rad']


@pytest.mark.parametrize('body, message', [
    ('<binding channel="40" type="Aileron"/>', 'outside'),
    ('<binding channel="x" type="Aileron"/>', 'not a number'),
    ('<binding channel="1" type="Wing"/>', 'unknown type'),
    ('<binding channel="1" type="Aileron" in="1 1"/>', 'no width'),
    ('<binding channel="1" type="Aileron" out="1"/>', 'not two numbers'),
    ('<binding channel="0" type="Aileron"/><binding channel="1" type="Aileron"/>', 'written by SERVO1 and SERVO2'),
])
def test_load_errors(tmp_path, body, message):
    with pytest.raises(controls.BindingError, match=message):
        controls.load(write(tmp_path, body))


def test_wrong_root_element(tmp_path):
    path = tmp_path / 'Controls.xml'
    path.write_text('<bindings/>')
    with pytest.raises(controls.BindingError, match='control_bindings'):
        controls.load(str(path))


def test_gimbal_rows_are_warned_and_skipped(tmp_path):
    rows, warnings = controls.load(write(tmp_path, '<binding channel="4" type="Gimbal" index="0" in="-1 1" out="-45 45"/>'))
    assert rows == []
    assert 'Gimbal' in warnings[0]


def test_missing_properties_are_reported():
    rows = [controls.Row(0, ['fcs/aileron-cmd-norm']), controls.Row(1, ['fcs/servo-9-cmd-norm'])]
    with pytest.raises(controls.BindingError, match='fcs/servo-9-cmd-norm'):
        controls.check_properties(rows, lambda p: p == 'fcs/aileron-cmd-norm')


def test_bindings_apply_skip_zero_and_start_motors():
    written = {}
    started = []
    rows = [controls.Row(0, ['fcs/aileron-cmd-norm'], (-1, 1), (-1, 1)),
            controls.Row(2, ['fcs/throttle-cmd-norm[0]'], type_name='Motor', index=0),
            controls.Row(20, ['fcs/servo-20'], (-1, 1), (-1, 1))]
    b = controls.Bindings(rows, written.__setitem__, started.append)
    pwm = [0, 1500, 1000] + [0] * 13
    b.apply(pwm, 0.001)
    assert 'fcs/aileron-cmd-norm' not in written  # PWM 0: not output, property untouched
    assert written['fcs/throttle-cmd-norm[0]'] == 0.0
    assert started == []
    pwm[2] = 1500
    b.apply(pwm, 0.001)
    b.apply(pwm, 0.001)
    assert started == [0]  # once, on the first command above 0.01
    assert 'fcs/servo-20' not in written  # channel 21 needs 32-channel packets
    b.reset()
    b.apply(pwm, 0.001)
    assert started == [0, 0]
