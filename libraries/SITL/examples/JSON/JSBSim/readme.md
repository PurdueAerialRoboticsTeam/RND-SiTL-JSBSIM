# JSBSim over the JSON SITL interface

`jsbsim_json_bridge.py` runs a JSBSim aircraft in-process and connects it to
ArduPilot SITL through the JSON backend (`--model JSON:<host>`). Unlike the
built-in `jsbsim` frame, which sends four channels over JSBSim's text
console, the JSON interface carries all 16 servo outputs (32 with
`SERVO_32_ENABLE=1`).

Design and roadmap: `sitl-docker/JSBSIM-JSON-PLAN.md`.

Servo outputs are bound to JSBSim properties by the aircraft's
`Controls.xml`, in the [PteroSimAircrafts](https://github.com/PteroLabsAI/PteroSimAircrafts)
format (`controls.py`; rules in the plan's section 5). An aircraft without one,
such as the Rascal, gets SERVO1..4 on aileron, elevator, throttle and rudder,
exactly like the `jsbsim` frame. PteroSimAircrafts' fixed-wing aircraft are
covered in `pterosim/README.md`.

## Requirements

- JSBSim's Python module, the same version as the `JSBSim` binary the team
  uses (`JSBSIM_REF` in `sitl-docker/Dockerfile`):
  `pip install jsbsim==1.3.3`. It installs a ready-made wheel on macOS and
  Linux x86_64 and compiles from source on Linux arm64 (needs CMake and a
  C++ compiler). The Docker image already has it.
- ArduPlane built for SITL (`./waf configure --board sitl && ./waf plane`).

## Running

Start the bridge, then SITL. The bridge waits for SITL.

```bash
cd libraries/SITL/examples/JSON/JSBSim
./jsbsim_json_bridge.py --aircraft Rascal --location CMAC
```

```bash
Tools/autotest/sim_vehicle.py -v ArduPlane --frame jsbsim-json --location CMAC
```

Use the same location for both: the bridge starts JSBSim there, and SITL
uses it as home.

Options (`--help` for all):

| Option | Default | |
|---|---|---|
| `--aircraft` | `Rascal` | model name |
| `--aircraft-dir` | `Tools/autotest/aircraft` | folder holding `<aircraft>/<aircraft>.xml`, e.g. a PteroSimAircrafts checkout |
| `--controls` | the aircraft's `Controls.xml` | another bindings file, or `none` for the built-in SERVO1..4 |
| `--location` / `--home` | `CMAC` | name from `Tools/autotest/locations.txt`, or `lat,lng,alt,heading` |
| `--port` | `9002` | UDP port SITL sends servo packets to |
| `--servo-lag` | `0.14` | servo time constant in seconds, as `SIM_SERVO_SPEED`, for rows without `lag=`; `0` disables |
| `--start-engines` | off | start every engine at reset; otherwise a `Motor` row starts its engine on the first throttle above 1% |
| `--agl`, `--pitch` | `1.3`, `13` | initial height above ground (m) and pitch (deg), as the `jsbsim` frame |
| `--stats` | `10` | seconds between timing reports; `0` disables |

## How it works

Lockstep: every servo packet from SITL gets exactly one JSBSim step of
`1/frame_rate` seconds (SITL's `SIM_RATE_HZ`) and one JSON reply.

- A repeated `frame_count` (SITL resending after a timeout) gets the previous
  reply again, without stepping.
- A lower `frame_count` (SITL restarted) resets JSBSim to its initial
  conditions.
- Stale packets queued while the bridge was busy are dropped; only the
  newest is used.

JSBSim's ground is placed at the home altitude, so the altitude sent to SITL
(above sea level) matches SITL's home.

Engines: with the built-in bindings every engine runs from the start, as with
the `jsbsim` frame. With a `Controls.xml`, a `Motor` row starts its engine on
the first throttle command above 1%, as PteroSim does; a piston engine also
gets full-rich mixture and both magnetos unless a row binds those.

The timing report shows the time per frame. At SITL's default 1200 Hz the
budget is 833 µs; the bridge typically needs well under 100 µs.

## Tests

```bash
cd libraries/SITL/examples/JSON/JSBSim
python -m pytest tests
```

`tests/test_sitl_protocol.py` and `tests/test_controls.py` need nothing but
Python; `tests/test_bridge.py` needs the `jsbsim` module and also flies the
Rascal for a few seconds.
