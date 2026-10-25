# PteroSimAircrafts with ArduPlane

The bridge flies aircraft from
[PteroSimAircrafts](https://github.com/PteroLabsAI/PteroSimAircrafts) without
copying them into this repository: point `--aircraft-dir` at a checkout. The
bridge reads each aircraft's own `Controls.xml` and keeps its `ArduPilot` rows
(and rows naming no autopilot). This folder holds ArduPilot setups for
aircraft that ship without one.

Each aircraft keeps its own licence and notices in its PteroSimAircrafts folder.

## Fixed-wing aircraft tested

Flown in SITL on 2026-10-25 against PteroSimAircrafts commit `3aad5cc`: AUTO
takeoff, a four-waypoint box, then RTL, with the bridge in lockstep at 1200 Hz.

| Aircraft | Bindings | Parameters (on top of `Tools/autotest/models/plane.parm`) | Result |
|---|---|---|---|
| `c172p` | its own `Controls.xml` | its own `firmwares/ardupilot_c172p.param` | Takeoff, climb to 120 m, 1.5 km box at ~38 m/s, RTL |
| `advanced_plane` | `advanced_plane/Controls.xml` here (it ships PX4 rows only) | `advanced_plane/ardupilot_advanced_plane.param` here | Takeoff, climb to 60 m, 300 m box, RTL; see the note below |

`advanced_plane`'s propeller table is flat: thrust does not fall off with
airspeed, so full throttle runs away past 100 m/s. The parameters cap the
throttle at 40%, which still lets it climb out at about 30 m/s and bank to
68° in the box. Lower `TKOFF_THR_MAX` and `THR_MAX` further, or give the
model a real propeller table, before using it for tuning work.

VTOL aircraft (`explora`, `standard_vtol`, `tiltrotor`, `quadtailsitter`)
are not tested yet.

## ArduPilot sign convention

PteroSim's notes for the c172p say that ArduPlane's elevator and rudder
outputs above 1500 mean nose up and yaw right, while JSBSim's +1 is trailing
edge down and trailing edge left. The bridge follows it: a channel that
carries a typed `Elevator` or `Rudder` row is mirrored around 1500 before any
row on it reads it. Use these aircraft with `models/plane.parm` (no
`SERVOn_REVERSED`), not with `plane-jsbsim.parm`, which reverses elevator and
rudder itself. Property rows (`property=`) are never mirrored, which is why
`advanced_plane`'s bindings need no reversal.

## Running

Natively, from the repository root, with a PteroSimAircrafts checkout in
`sitl-docker/aircraft/PteroSimAircrafts` (git-ignored):

```bash
libraries/SITL/examples/JSON/JSBSim/jsbsim_json_bridge.py --aircraft c172p \
  --aircraft-dir sitl-docker/aircraft/PteroSimAircrafts --pitch 0 --agl 1
```

```bash
Tools/autotest/sim_vehicle.py -v ArduPlane --frame plane --model JSON:127.0.0.1 \
  --add-param-file sitl-docker/aircraft/PteroSimAircrafts/c172p/firmwares/ardupilot_c172p.param
```

In Docker, see "JSON backend" in `sitl-docker/README.md`.

`--pitch 0 --agl 1` start a nose-wheel aircraft level; the defaults (13°,
1.3 m) are the Rascal's tail-dragger stance.
