#!/usr/bin/env python3
'''
JSBSim physics backend for ArduPilot SITL over the JSON interface.

Runs JSBSim in-process and answers each SITL servo packet with exactly one
JSBSim step and one JSON state line (lockstep). Start it, then start SITL
with --model JSON:127.0.0.1, e.g.

  ./jsbsim_json_bridge.py --aircraft Rascal --location CMAC
  sim_vehicle.py -v ArduPlane --frame jsbsim-json --location CMAC

Servo outputs are bound to JSBSim properties by the aircraft's Controls.xml
(controls.py), or by built-in defaults equal to the jsbsim frame's when the
aircraft has none. The plan for this backend is sitl-docker/JSBSIM-JSON-PLAN.md.

AP_FLAKE8_CLEAN
'''

import argparse
import os
import select
import socket
import sys
import time

import jsbsim

import controls
from sitl_protocol import (
    Lockstep,
    REPEAT,
    RESET,
    encode_state,
    newest_packet,
    parse_servo_packet,
)

FT_TO_M = 0.3048
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), *(['..'] * 5)))
DEFAULT_ROOT = os.path.join(REPO_ROOT, 'Tools', 'autotest')
# where --aircraft is looked for when --aircraft-dir is not given, in order
AIRCRAFT_SEARCH = (os.path.join(REPO_ROOT, 'test-aircraft'), os.path.join(DEFAULT_ROOT, 'aircraft'))


def find_aircraft_dir(aircraft, search=AIRCRAFT_SEARCH):
    '''the first folder in search holding <aircraft>/<aircraft>.xml, or None'''
    for d in search:
        if os.path.exists(os.path.join(d, aircraft, aircraft + '.xml')):
            return d
    return None


def default_rows(lag):
    '''
    the C++ jsbsim backend's bindings (SIM_JSBSim.cpp): SERVO1..4 drive
    aileron, elevator, throttle and rudder, no mirroring (plane-jsbsim.parm
    reverses elevator and rudder with SERVO2/4_REVERSED instead), each with
    SITL's servo lag
    '''
    return [
        controls.Row(0, ['fcs/aileron-cmd-norm'], (-1, 1), (-1, 1), lag=lag),
        controls.Row(1, ['fcs/elevator-cmd-norm'], (-1, 1), (-1, 1), lag=lag),
        controls.Row(2, ['fcs/throttle-cmd-norm'], (0, 1), (0, 1), lag=lag),
        controls.Row(3, ['fcs/rudder-cmd-norm'], (-1, 1), (-1, 1), lag=lag),
    ]


def read_location(name, autotest_dir):
    '''look up NAME=lat,lng,alt,hdg in Tools/autotest/locations.txt'''
    path = os.path.join(autotest_dir, 'locations.txt')
    with open(path) as f:
        for line in f:
            line = line.split('#', 1)[0].strip()
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            if key.strip() == name:
                return parse_home(value)
    raise ValueError("location %s not found in %s" % (name, path))


def parse_home(text):
    parts = [float(x) for x in text.split(',')]
    if len(parts) != 4:
        raise ValueError("expected lat,lng,alt,heading, got %r" % text)
    return parts


class JSBSimModel:
    '''one JSBSim aircraft, stepped one SITL frame at a time'''

    def __init__(self, root, aircraft, home, agl_m, pitch_deg, aircraft_dir=None,
                 start_engines=True, debug_level=0, rate_hz=1200.0):
        self.start_engines = start_engines
        # properties written by bindings, which engine start must leave alone
        self.bound = set()

        self.fdm = jsbsim.FGFDMExec(root)
        self.fdm.set_debug_level(debug_level)
        # JSBSim's flight-control components (filters, actuators, delays) take the
        # timestep once, when the model loads, so it must be SITL's before loading
        self.fdm.set_dt(1.0 / rate_hz)
        self.rate_hz = rate_hz
        self.load_rate_hz = rate_hz
        self.rate_warned = False
        if aircraft_dir is not None:
            self.fdm.set_aircraft_path(aircraft_dir)
        if not self.fdm.load_model(aircraft):
            raise RuntimeError("JSBSim could not load aircraft %s from %s" % (
                aircraft, aircraft_dir or os.path.join(root, 'aircraft')))
        self.num_engines = self.fdm.get_propulsion().get_num_engines()

        lat, lng, alt, hdg = home
        self.fdm['ic/lat-geod-deg'] = lat
        self.fdm['ic/long-gc-deg'] = lng
        # put JSBSim's ground at the home altitude so its altitude above sea
        # level is the one SITL expects
        self.fdm['ic/terrain-elevation-ft'] = alt / FT_TO_M
        self.fdm['ic/h-agl-ft'] = agl_m / FT_TO_M
        self.fdm['ic/psi-true-deg'] = hdg
        self.fdm['ic/theta-deg'] = pitch_deg
        self.fdm['ic/vt-fps'] = 0
        self.fdm.run_ic()
        self._start()

    def _start(self):
        '''what happens after every initial condition: engines on if asked, settle on the ground'''
        if self.start_engines:
            for n in range(self.num_engines):
                self.start_engine(n)
        try:
            self.fdm.do_trim(2)  # ground trim, as the C++ backend's script does
        except Exception as ex:
            print("bridge: ground trim failed (%s), continuing untrimmed" % ex)

    def start_engine(self, n):
        '''
        start engine n so that it runs at idle, as PteroSim does on the first
        throttle command: a piston engine also needs mixture and magnetos,
        which are set unless a binding controls them
        '''
        if n >= self.num_engines:
            return
        for prop, on in (('fcs/mixture-cmd-norm[%u]' % n, 1.0), ('propulsion/magneto_cmd', 3)):
            if prop not in self.bound and self.has_property(prop) and self.fdm[prop] == 0:
                self.fdm[prop] = on
        # FGPropulsion::InitRunning(n); engine[n]/set-running does not start a piston engine
        self.fdm['propulsion/set-running'] = n

    def has_property(self, name):
        return self.fdm.get_property_manager().hasNode(name)

    def set_property(self, name, value):
        self.fdm[name] = value

    def reset(self):
        self.fdm.reset_to_initial_conditions(0)
        self._start()

    def set_rate(self, rate_hz):
        if rate_hz > 0 and rate_hz != self.rate_hz:
            self.rate_hz = rate_hz
            self.fdm.set_dt(1.0 / rate_hz)
            if rate_hz != self.load_rate_hz and not self.rate_warned:
                self.rate_warned = True
                print("bridge: warning: SITL runs at %u Hz but the model was loaded for %u Hz, so filters and "
                      "actuators in its flight controls run %.2f times too fast; start the bridge with --rate %u" % (
                          rate_hz, self.load_rate_hz, rate_hz / self.load_rate_hz, rate_hz))

    def dt(self):
        return self.fdm.get_delta_t()

    def step(self):
        return self.fdm.run()

    def sim_time(self):
        return self.fdm['simulation/sim-time-sec']

    def state(self):
        f = self.fdm
        return {
            'timestamp': f['simulation/sim-time-sec'],
            'gyro': (f['velocities/p-rad_sec'], f['velocities/q-rad_sec'], f['velocities/r-rad_sec']),
            'accel_body': (f['accelerations/a-pilot-x-ft_sec2'] * FT_TO_M,
                           f['accelerations/a-pilot-y-ft_sec2'] * FT_TO_M,
                           f['accelerations/a-pilot-z-ft_sec2'] * FT_TO_M),
            'latitude': f['position/lat-geod-deg'],
            'longitude': f['position/long-gc-deg'],
            'altitude': f['position/h-sl-meters'],
            'attitude': (f['attitude/phi-rad'], f['attitude/theta-rad'], f['attitude/psi-rad']),
            'velocity': (f['velocities/v-north-fps'] * FT_TO_M,
                         f['velocities/v-east-fps'] * FT_TO_M,
                         f['velocities/v-down-fps'] * FT_TO_M),
            'velocity_wind': (f['atmosphere/total-wind-north-fps'] * FT_TO_M,
                              f['atmosphere/total-wind-east-fps'] * FT_TO_M,
                              f['atmosphere/total-wind-down-fps'] * FT_TO_M),
            'airspeed': f['velocities/vc-fps'] * FT_TO_M,
        }


class Stats:
    '''time per frame, printed every interval seconds of wall clock'''

    def __init__(self, interval):
        self.interval = interval
        self.start = time.monotonic()
        self.frames = 0
        self.total = 0.0
        self.worst = 0.0

    def add(self, seconds):
        self.frames += 1
        self.total += seconds
        self.worst = max(self.worst, seconds)

    def report(self, model):
        now = time.monotonic()
        if self.interval <= 0 or now - self.start < self.interval or self.frames == 0:
            return
        print("bridge: %u frames in %.1fs, %.0f us/frame mean, %.0f us worst, sim time %.1fs, %u Hz" % (
            self.frames, now - self.start, 1e6 * self.total / self.frames, 1e6 * self.worst,
            model.sim_time(), model.rate_hz or 0))
        self.__init__(self.interval)


def receive_newest(sock):
    '''block for one datagram, then drain the socket and keep the newest frame'''
    data, addr = sock.recvfrom(1024)
    received = [(parse_servo_packet(data), addr)]
    while select.select([sock], [], [], 0)[0]:
        data, addr = sock.recvfrom(1024)
        received.append((parse_servo_packet(data), addr))
    return newest_packet(received)


class Bridge:
    '''one servo packet in, one reply out; see Lockstep for the rules'''

    def __init__(self, model, bindings, stats):
        self.model = model
        self.bindings = bindings
        self.stats = stats
        self.lockstep = Lockstep()

    def handle(self, pkt):
        action = self.lockstep.classify(pkt.frame_count)
        if action == REPEAT:
            return self.lockstep.last_reply
        if action == RESET:
            print("bridge: SITL restarted (frame %u after %u), resetting JSBSim" % (
                pkt.frame_count, self.lockstep.last_count))
            self.model.reset()
            self.bindings.reset()

        t0 = time.perf_counter()
        self.model.set_rate(pkt.frame_rate)
        self.bindings.apply(pkt.pwm, self.model.dt())
        self.model.step()
        reply = encode_state(self.model.state())
        self.stats.add(time.perf_counter() - t0)

        self.lockstep.record(pkt.frame_count, reply)
        self.stats.report(self.model)
        return reply


def run(sock, bridge):
    connected = None
    while True:
        newest, skipped = receive_newest(sock)
        if newest is None:
            continue
        pkt, addr = newest
        if skipped:
            print("bridge: dropped %u stale frame(s)" % skipped)
        if addr != connected:
            connected = addr
            print("bridge: SITL connected from %s:%u, %u channels" % (addr[0], addr[1], len(pkt.pwm)))
        sock.sendto(bridge.handle(pkt), addr)


def find_controls(args, aircraft_dir):
    '''the Controls.xml to use, or None for the built-in defaults'''
    if args.controls == 'none':
        return None
    if args.controls is not None:
        return args.controls
    path = os.path.join(aircraft_dir, args.aircraft, 'Controls.xml')
    return path if os.path.exists(path) else None


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--aircraft', default='Rascal', help='JSBSim aircraft name')
    parser.add_argument('--aircraft-dir', help='folder holding <aircraft>/<aircraft>.xml '
                        '(default: test-aircraft, then Tools/autotest/aircraft)')
    parser.add_argument('--root', default=DEFAULT_ROOT, help='JSBSim root directory (default: %(default)s)')
    parser.add_argument('--controls', help='Controls.xml to use (default: the aircraft\'s own, if any); '
                        '"none" for the built-in SERVO1..4 bindings')
    home = parser.add_mutually_exclusive_group()
    home.add_argument('--location', default='CMAC', help='name from Tools/autotest/locations.txt')
    home.add_argument('--home', help='lat,lng,alt,heading; overrides --location')
    parser.add_argument('--bind', default='127.0.0.1', help='address to listen on')
    parser.add_argument('--port', type=int, default=9002, help='UDP port SITL sends servo packets to')
    # JSBSim's ground trim settles every aircraft onto its gear from a level
    # start; a nose-up start (the jsbsim frame's 13 deg) crashes it for the c172p
    parser.add_argument('--agl', type=float, default=0.5, help='initial height above ground before ground trim, m')
    parser.add_argument('--pitch', type=float, default=0.0, help='initial pitch before ground trim, deg')
    parser.add_argument('--servo-lag', type=float, default=0.14,
                        help='servo time constant, s, as SIM_SERVO_SPEED, for rows without lag=; 0 disables')
    parser.add_argument('--start-engines', action='store_true',
                        help='start every engine at reset even with a Controls.xml (Motor rows start them otherwise)')
    parser.add_argument('--rate', type=float, default=1200.0,
                        help='SITL frame rate the model is loaded for, Hz (SIM_RATE_HZ, default %(default)s)')
    parser.add_argument('--stats', type=float, default=10.0, help='seconds between timing reports, 0 disables')
    parser.add_argument('--jsbsim-debug', type=int, default=0, help='JSBSim debug level')
    args = parser.parse_args()
    # keep log lines in order with SITL's when both go to one file or docker log
    sys.stdout.reconfigure(line_buffering=True)

    if args.aircraft_dir:
        aircraft_dir = os.path.abspath(args.aircraft_dir)
    else:
        aircraft_dir = find_aircraft_dir(args.aircraft)
        if aircraft_dir is None:
            print("bridge: aircraft %s not found in %s" % (args.aircraft, ' or '.join(AIRCRAFT_SEARCH)))
            return 1
    controls_path = find_controls(args, aircraft_dir)
    warnings = []
    if controls_path is None:
        rows = default_rows(args.servo_lag)
    else:
        try:
            rows, warnings = controls.load(controls_path, lag=args.servo_lag)
        except controls.BindingError as ex:
            print("bridge: %s" % ex)
            return 1

    home_pos = parse_home(args.home) if args.home else read_location(args.location, DEFAULT_ROOT)
    model = JSBSimModel(args.root, args.aircraft, home_pos, args.agl, args.pitch,
                        aircraft_dir=aircraft_dir,
                        start_engines=controls_path is None or args.start_engines,
                        debug_level=args.jsbsim_debug, rate_hz=args.rate)
    try:
        controls.check_properties(rows, model.has_property)
    except controls.BindingError as ex:
        print("bridge: %s" % ex)
        return 1
    model.bound = {p for r in rows for p in r.properties}
    bindings = controls.Bindings(rows, model.set_property, model.start_engine)

    print("bridge: JSBSim %s, aircraft %s from %s, %u engine(s), home %.6f,%.6f,%.1f,%.0f" % (
        jsbsim.__version__, args.aircraft, aircraft_dir, model.num_engines, *home_pos))
    print("bridge: bindings from %s" % (controls_path or 'built-in defaults (the jsbsim frame\'s)'))
    for r in rows:
        print("bridge:   %s" % r.describe())
    for w in warnings:
        print("bridge: warning: %s" % w)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind, args.port))
    print("bridge: waiting for SITL on udp %s:%u" % (args.bind, args.port))
    try:
        run(sock, Bridge(model, bindings, Stats(args.stats)))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
