'''
Servo channel bindings: which ArduPilot output drives which JSBSim property.

Reads a Controls.xml in the PteroSimAircrafts format
(https://github.com/PteroLabsAI/PteroSimAircrafts), e.g.

  <control_bindings stack="ArduPilot">
    <binding stack="ArduPilot" channel="0" type="Aileron" in="-1 1" out="-1 1"/>
    <binding stack="ArduPilot" channel="2" type="Motor" index="0" in="0 1" out="0 1"/>
    <binding channel="5" property="fcs/servo-1-cmd-norm" in="-1 1" out="-1 1" invert="1"/>
  </control_bindings>

channel is SERVOn - 1. Rows for other autopilots (PX4, Manual, ...) are
ignored. The full rules are in sitl-docker/JSBSIM-JSON-PLAN.md section 5.

No JSBSim import here: the caller passes property checks and setters in.

AP_FLAKE8_CLEAN
'''

import xml.etree.ElementTree as ET

STACK = 'ArduPilot'

# type -> JSBSim properties; '%u' takes the row's index (engine number)
TYPE_PROPERTIES = {
    'Aileron': ('fcs/aileron-cmd-norm',),
    'Elevator': ('fcs/elevator-cmd-norm',),
    'Rudder': ('fcs/rudder-cmd-norm',),
    'Flaps': ('fcs/flap-cmd-norm',),
    'Speedbrake': ('fcs/speedbrake-cmd-norm',),
    'Spoiler': ('fcs/spoiler-cmd-norm',),
    'PitchTrim': ('fcs/pitch-trim-cmd-norm',),
    'RollTrim': ('fcs/roll-trim-cmd-norm',),
    'YawTrim': ('fcs/yaw-trim-cmd-norm',),
    'Steering': ('fcs/steer-cmd-norm',),
    'BrakeLeft': ('fcs/left-brake-cmd-norm',),
    'BrakeRight': ('fcs/right-brake-cmd-norm',),
    'BrakeCenter': ('fcs/center-brake-cmd-norm',),
    'Brake': ('fcs/left-brake-cmd-norm', 'fcs/right-brake-cmd-norm'),
    'Gear': ('gear/gear-cmd-norm',),
    'Motor': ('fcs/throttle-cmd-norm[%u]',),
    'Mixture': ('fcs/mixture-cmd-norm[%u]',),
    'PropAdvance': ('fcs/advance-cmd-norm[%u]',),
    'PropFeather': ('fcs/feather-cmd-norm[%u]',),
    'Collective': ('propulsion/engine[%u]/collective-ctrl-rad',),
    'CyclicLateral': ('propulsion/engine[%u]/lateral-ctrl-rad',),
    'CyclicLongitudinal': ('propulsion/engine[%u]/longitudinal-ctrl-rad',),
    'Starter': ('propulsion/starter_cmd',),
    'Magneto': ('propulsion/magneto_cmd',),
    'Cutoff': ('propulsion/cutoff_cmd',),
}

# PteroSim types with no JSBSim equivalent; used only with property=
NO_PROPERTY_TYPES = ('Gimbal', 'Gripper', 'Servo')

# ArduPilot's sign convention, as PteroSim's c172p notes describe it:
# ArduPlane's elevator and rudder outputs above 1500 are nose up and yaw
# right, JSBSim's +1 commands are trailing edge down and trailing edge left.
# A channel carrying a typed Elevator or Rudder row is therefore mirrored
# around 1500 before any row on it reads it.
MIRRORED_TYPES = ('Elevator', 'Rudder')

# a motor starts on the first command above this, as in PteroSim
MOTOR_START_THRESHOLD = 0.01


class BindingError(Exception):
    pass


class ServoLag:
    '''first-order low-pass, as ArduPilot's LowPassFilterFloat with time constant tau'''

    def __init__(self, tau):
        self.tau = tau
        self.value = None

    def apply(self, target, dt):
        if self.value is None or self.tau <= 0:
            self.value = target
        else:
            self.value += (dt / (dt + self.tau)) * (target - self.value)
        return self.value


def _range(text, what, line):
    if text is None:
        return (0.0, 1.0)
    try:
        lo, hi = (float(x) for x in text.split())
    except ValueError:
        raise BindingError("%s: %s=%r is not two numbers" % (line, what, text))
    if lo == hi:
        raise BindingError("%s: %s=%r has no width" % (line, what, text))
    return lo, hi


class Row:
    '''one <binding>: a channel to one or more properties'''

    def __init__(self, channel, properties, in_range=(0.0, 1.0), out_range=(0.0, 1.0),
                 invert=False, lag=0.0, label='', type_name=None, index=0, typed=False):
        self.channel = channel
        self.properties = tuple(properties)
        self.in_min, self.in_max = in_range
        self.out_min, self.out_max = out_range
        self.invert = invert
        self.filter = ServoLag(lag)
        self.label = label
        self.type_name = type_name
        self.index = index
        self.typed = typed
        self.mirrored = False
        self.started = False

    def normalise(self, pwm):
        '''PWM to the row's input range: 1000..2000 -> 0..1, or 1000..2000 -> -1..1 centred on 1500'''
        if self.mirrored:
            pwm = 3000 - pwm
        if self.in_min >= 0:
            x = (pwm - 1000) / 1000.0
        else:
            x = (pwm - 1500) / 500.0
        lo, hi = min(self.in_min, self.in_max), max(self.in_min, self.in_max)
        x = min(max(x, lo), hi)
        if self.invert:
            x = self.in_min + self.in_max - x
        return x

    def output(self, pwm, dt):
        x = self.normalise(pwm)
        y = self.out_min + (x - self.in_min) * (self.out_max - self.out_min) / (self.in_max - self.in_min)
        return self.filter.apply(y, dt)

    def reset(self):
        self.filter.value = None
        self.started = False

    def describe(self):
        what = self.type_name or 'property'
        if self.type_name in ('Motor', 'Mixture', 'PropAdvance', 'PropFeather',
                              'Collective', 'CyclicLateral', 'CyclicLongitudinal'):
            what += '[%u]' % self.index
        flags = ''.join((' mirrored' if self.mirrored else '', ' invert' if self.invert else '',
                         ' lag %.2fs' % self.filter.tau if self.filter.tau > 0 else ''))
        return "SERVO%-2u %-14s -> %s in %g..%g out %g..%g%s%s" % (
            self.channel + 1, what, ', '.join(self.properties), self.in_min, self.in_max,
            self.out_min, self.out_max, flags, '  "%s"' % self.label if self.label else '')


def _applies(binding):
    stacks = binding.get('stack')
    if stacks is None:
        # no stack on the row means every autopilot
        return True
    return STACK in stacks.split()


def load(path, max_channels=32, lag=0.0):
    '''parse a Controls.xml into Rows for the ArduPilot stack; raises BindingError'''
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as ex:
        raise BindingError("cannot read %s: %s" % (path, ex))
    if root.tag != 'control_bindings':
        raise BindingError("%s: root element is <%s>, expected <control_bindings>" % (path, root.tag))

    rows = []
    warnings = []
    for n, b in enumerate(root.findall('binding')):
        line = "%s binding %u" % (path, n + 1)
        if not _applies(b):
            continue
        try:
            channel = int(b.get('channel'))
        except (TypeError, ValueError):
            raise BindingError("%s: channel=%r is not a number" % (line, b.get('channel')))
        if not 0 <= channel < max_channels:
            raise BindingError("%s: channel %u is outside 0..%u" % (line, channel, max_channels - 1))
        type_name = b.get('type')
        prop = b.get('property')
        index = int(b.get('index', '0'))
        if prop is not None:
            properties = [prop]
        elif type_name in TYPE_PROPERTIES:
            properties = [p % index if '%u' in p else p for p in TYPE_PROPERTIES[type_name]]
        elif type_name in NO_PROPERTY_TYPES:
            warnings.append("%s: type %s has no JSBSim property, row ignored" % (line, type_name))
            continue
        else:
            raise BindingError("%s: unknown type %r and no property=" % (line, type_name))
        rows.append(Row(channel, properties,
                        in_range=_range(b.get('in'), 'in', line),
                        out_range=_range(b.get('out'), 'out', line),
                        invert=b.get('invert', '0') == '1',
                        lag=float(b.get('lag', lag)),
                        label=b.get('label', ''),
                        type_name=type_name,
                        index=index,
                        typed=prop is None))

    mirrored_channels = {r.channel for r in rows if r.typed and r.type_name in MIRRORED_TYPES}
    for r in rows:
        r.mirrored = r.channel in mirrored_channels

    written = {}
    for r in rows:
        for p in r.properties:
            if p in written:
                raise BindingError("%s: %s is written by SERVO%u and SERVO%u" % (
                    path, p, written[p] + 1, r.channel + 1))
            written[p] = r.channel
    return rows, warnings


def check_properties(rows, has_property):
    '''raise BindingError for properties the loaded model does not have'''
    missing = sorted({p for r in rows for p in r.properties if not has_property(p)})
    if missing:
        raise BindingError("the model has no propert%s %s; check Controls.xml for typos" % (
            'y' if len(missing) == 1 else 'ies', ', '.join(missing)))


class Bindings:
    '''applies rows to a model each frame'''

    def __init__(self, rows, set_property, start_engine=None):
        self.rows = rows
        self.set_property = set_property
        self.start_engine = start_engine
        self.warned = set()

    def apply(self, pwm, dt):
        for r in self.rows:
            if r.channel >= len(pwm):
                if r.channel not in self.warned:
                    self.warned.add(r.channel)
                    print("bridge: SERVO%u is bound but SITL sends %u channels; set SERVO_32_ENABLE=1" % (
                        r.channel + 1, len(pwm)))
                continue
            value = pwm[r.channel]
            if value == 0:
                # channel not output by ArduPilot: hold the last command
                continue
            y = r.output(value, dt)
            for p in r.properties:
                self.set_property(p, y)
            if (r.type_name == 'Motor' and not r.started and self.start_engine is not None
                    and y > MOTOR_START_THRESHOLD):
                r.started = True
                self.start_engine(r.index)

    def reset(self):
        for r in self.rows:
            r.reset()
