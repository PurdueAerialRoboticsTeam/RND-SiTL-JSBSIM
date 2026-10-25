# JSBSim over the JSON SITL interface

`jsbsim_json_bridge.py` runs a JSBSim aircraft in-process and connects it to
ArduPilot SITL through the JSON backend (`--model JSON:<host>`). Unlike the
built-in `jsbsim` frame, which sends four channels over JSBSim's text
console, the JSON interface carries all 16 servo outputs (32 with
`SERVO_32_ENABLE=1`).

Design and roadmap: `sitl-docker/JSBSIM-JSON-PLAN.md`.

Current state (Phase 1): SERVO1..4 drive aileron, elevator, throttle and
rudder, exactly like the `jsbsim` frame, with the same servo lag. Per-aircraft
`Controls.xml` bindings for all channels come in Phase 2.

## Requirements

- JSBSim's Python module, the same version as the `JSBSim` binary the team
  uses (`JSBSIM_REF` in `sitl-docker/Dockerfile`):
  `pip install jsbsim==1.3.3` works on macOS and Linux x86_64.
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
| `--aircraft` | `Rascal` | model under `Tools/autotest/aircraft/` |
| `--location` / `--home` | `CMAC` | name from `Tools/autotest/locations.txt`, or `lat,lng,alt,heading` |
| `--port` | `9002` | UDP port SITL sends servo packets to |
| `--servo-lag` | `0.14` | servo time constant in seconds, as `SIM_SERVO_SPEED`; `0` disables |
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

The timing report shows the time per frame. At SITL's default 1200 Hz the
budget is 833 µs; the bridge typically needs well under 100 µs.

## Tests

```bash
cd libraries/SITL/examples/JSON/JSBSim
python -m pytest tests
```

`tests/test_sitl_protocol.py` needs nothing but Python; `tests/test_bridge.py`
needs the `jsbsim` module and also flies the Rascal for a few seconds.
