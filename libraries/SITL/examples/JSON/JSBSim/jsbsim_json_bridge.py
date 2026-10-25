#!/usr/bin/env python3
'''
JSBSim physics backend for ArduPilot SITL over the JSON interface.

Runs JSBSim in-process and answers each SITL servo packet with exactly one
JSBSim step and one JSON state line (lockstep). Start it, then start SITL
with --model JSON:127.0.0.1, e.g.

  ./jsbsim_json_bridge.py --aircraft Rascal --location CMAC
  sim_vehicle.py -v ArduPlane --frame jsbsim-json --location CMAC

The plan for this backend is sitl-docker/JSBSIM-JSON-PLAN.md.

AP_FLAKE8_CLEAN
'''

import argparse
import os
import select
import socket
import sys
import time

import jsbsim

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

# Phase 1 bindings, the same as the C++ jsbsim backend (SIM_JSBSim.cpp):
# SERVO1..4 drive aileron, elevator, throttle and rudder. Each is filtered the
# way SITL filters servos for that backend, a first-order lag whose time
# constant is SIM_SERVO_SPEED (ServoModel::apply_simple_filter).
DEFAULT_BINDINGS = (
    # channel, property, normalisation
    (0, 'fcs/aileron-cmd-norm', 'angle'),
    (1, 'fcs/elevator-cmd-norm', 'angle'),
    (2, 'fcs/throttle-cmd-norm', 'range'),
    (3, 'fcs/rudder-cmd-norm', 'angle'),
)


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


class Binding:
    def __init__(self, channel, prop, kind, lag):
        self.channel = channel
        self.prop = prop
        self.kind = kind
        self.filter = ServoLag(lag)

    def normalise(self, pwm):
        if self.kind == 'range':
            return min(max((pwm - 1000) / 1000.0, 0.0), 1.0)
        return min(max((pwm - 1500) / 500.0, -1.0), 1.0)

    def reset(self):
        self.filter.value = None


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

    def __init__(self, root, aircraft, home, agl_m, pitch_deg, bindings, debug_level=0):
        self.home = home
        self.agl_m = agl_m
        self.pitch_deg = pitch_deg
        self.bindings = bindings
        self.rate_hz = None

        self.fdm = jsbsim.FGFDMExec(root)
        self.fdm.set_debug_level(debug_level)
        if not self.fdm.load_model(aircraft):
            raise RuntimeError("JSBSim could not load aircraft %s from %s" % (aircraft, root))
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
        '''what happens after every initial condition: engines on, settle on the ground'''
        for n in range(self.num_engines):
            self.fdm['propulsion/engine[%u]/set-running' % n] = 1
        for b in self.bindings:
            b.reset()
        try:
            self.fdm.do_trim(2)  # ground trim, as the C++ backend's script does
        except Exception as ex:
            print("bridge: ground trim failed (%s), continuing untrimmed" % ex)

    def reset(self):
        self.fdm.reset_to_initial_conditions(0)
        self._start()

    def set_rate(self, rate_hz):
        if rate_hz > 0 and rate_hz != self.rate_hz:
            self.rate_hz = rate_hz
            self.fdm.set_dt(1.0 / rate_hz)

    def apply_servos(self, pwm):
        dt = self.fdm.get_delta_t()
        for b in self.bindings:
            value = pwm[b.channel]
            if value == 0:
                # channel not output by ArduPilot: hold the last command
                continue
            self.fdm[b.prop] = b.filter.apply(b.normalise(value), dt)

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

    def __init__(self, model, stats):
        self.model = model
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

        t0 = time.perf_counter()
        self.model.set_rate(pkt.frame_rate)
        self.model.apply_servos(pkt.pwm)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--aircraft', default='Rascal', help='JSBSim aircraft under <root>/aircraft')
    parser.add_argument('--root', default=DEFAULT_ROOT, help='JSBSim root directory (default: %(default)s)')
    home = parser.add_mutually_exclusive_group()
    home.add_argument('--location', default='CMAC', help='name from Tools/autotest/locations.txt')
    home.add_argument('--home', help='lat,lng,alt,heading; overrides --location')
    parser.add_argument('--bind', default='127.0.0.1', help='address to listen on')
    parser.add_argument('--port', type=int, default=9002, help='UDP port SITL sends servo packets to')
    parser.add_argument('--agl', type=float, default=1.3, help='initial height above ground, m')
    parser.add_argument('--pitch', type=float, default=13.0, help='initial pitch, deg')
    parser.add_argument('--servo-lag', type=float, default=0.14,
                        help='servo time constant, s, as SIM_SERVO_SPEED; 0 disables')
    parser.add_argument('--stats', type=float, default=10.0, help='seconds between timing reports, 0 disables')
    parser.add_argument('--jsbsim-debug', type=int, default=0, help='JSBSim debug level')
    args = parser.parse_args()
    # keep log lines in order with SITL's when both go to one file or docker log
    sys.stdout.reconfigure(line_buffering=True)

    home_pos = parse_home(args.home) if args.home else read_location(args.location, DEFAULT_ROOT)
    bindings = [Binding(ch, prop, kind, args.servo_lag) for ch, prop, kind in DEFAULT_BINDINGS]
    model = JSBSimModel(args.root, args.aircraft, home_pos, args.agl, args.pitch, bindings, args.jsbsim_debug)

    print("bridge: JSBSim %s, aircraft %s, %u engine(s), home %.6f,%.6f,%.1f,%.0f" % (
        jsbsim.__version__, args.aircraft, model.num_engines, *home_pos))
    for b in bindings:
        print("bridge:   SERVO%-2u -> %-24s %s, lag %.2fs" % (b.channel + 1, b.prop, b.kind, b.filter.tau))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind, args.port))
    print("bridge: waiting for SITL on udp %s:%u" % (args.bind, args.port))
    try:
        run(sock, Bridge(model, Stats(args.stats)))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
