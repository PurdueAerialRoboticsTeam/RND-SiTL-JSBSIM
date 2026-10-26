# Test aircraft for the JSON backend

Fixed-wing JSBSim aircraft for testing the JSON backend
(`libraries/SITL/examples/JSON/JSBSim/`) with more than the Rascal's four
servo outputs. The bridge looks here first, then in `Tools/autotest/aircraft/`
(where the Rascal stays, because ArduPilot's C++ `jsbsim` backend only looks
there).

| Aircraft | What it is | Servo outputs | ArduPilot parameters |
|---|---|---|---|
| `c172p` | Cessna 172P: four-seat piston trainer, nose wheel, flaps 0/10/20/30° | SERVO1 aileron, SERVO2 elevator, SERVO3 throttle, SERVO4 rudder and nose wheel, SERVO5 flaps | `c172p/firmwares/ardupilot_c172p.param` |
| `advanced_plane` | PX4's small electric test plane (1.2 kg, 1.5 m span), tractor propeller, wheels | SERVO1 ailerons, SERVO2 elevator, SERVO3 throttle, SERVO4 rudder | `advanced_plane/firmwares/ardupilot_advanced_plane.param` |

## Where they come from

Copied from [PteroSimAircrafts](https://github.com/PteroLabsAI/PteroSimAircrafts)
commit `3aad5cc` (2026-10-22), without `meshes/` (3D models for PteroSim's
renderer; JSBSim does not read them, and the c172p's are 29 MB). Each folder
keeps its `LICENSE` and `NOTICE`: the c172p is GPL v2 (its JSBSim flight
model is LGPL), `advanced_plane` is BSD 3-Clause from PX4.

Changes from the source:

- `advanced_plane/Controls.xml`: ArduPilot rows added (the source has PX4
  and Manual rows only); the comment above them gives the signs.
- `advanced_plane/firmwares/ardupilot_advanced_plane.param`: new.

## Running

Docker, from `sitl-docker/`:

```bash
docker compose run --rm --service-ports -e SIM_BACKEND=json -e JSBSIM_MODEL=c172p sitl
docker compose run --rm --service-ports -e SIM_BACKEND=json -e JSBSIM_MODEL=advanced_plane sitl
```

The entrypoint finds the aircraft here and flies it with its own
`firmwares/ardupilot_<model>.param` on top of `Tools/autotest/models/plane.parm`.

Natively, from the repository root (two terminals):

```bash
libraries/SITL/examples/JSON/JSBSim/jsbsim_json_bridge.py --aircraft c172p
```

```bash
Tools/autotest/sim_vehicle.py -v ArduPlane --frame plane --model JSON:127.0.0.1 \
  --add-param-file test-aircraft/c172p/firmwares/ardupilot_c172p.param
```

## Tested

Both flown in SITL on 2026-10-25, natively and in Docker on Apple Silicon:
AUTO takeoff, a four-waypoint box, then RTL.

- `c172p`: climbs to 120 m, flies a 1.5 km box at about 38 m/s, banks up
  to 32°. The flaps (SERVO5) only move on an automatic landing
  (`LAND_FLAP_PERCNT 100`) or with `TKOFF_FLAP_PCNT` set; neither was
  exercised.
- `advanced_plane`: climbs to 60 m and flies a 300 m box, but its propeller
  table is flat (thrust never falls off with airspeed), so full throttle runs
  away past 100 m/s. The parameters cap throttle at 40%; it still climbs out
  at about 30 m/s and banks to 68°. Not suitable for tuning work until its
  propeller or throttle limits are fixed.

## Signs

PteroSim's convention, which the bridge follows: ArduPlane's elevator and
rudder outputs above 1500 mean nose up and yaw right, JSBSim's +1 means
trailing edge down and trailing edge left, so a channel with a typed
`Elevator` or `Rudder` row is mirrored around 1500. That is why these aircraft
use `models/plane.parm` (no `SERVOn_REVERSED`) and not the Rascal's
`plane-jsbsim.parm`, which reverses elevator and rudder itself. Property rows
are never mirrored.

## Adding another

Copy a JSBSim aircraft folder here (`<model>/<model>.xml`), give it a
`Controls.xml` with ArduPilot rows and, if it needs them, a
`firmwares/ardupilot_<model>.param`. VTOL aircraft from PteroSimAircrafts
need QuadPlane or Copter support in the Docker setup first.
