# Template fixed-wing aircraft

A starting point for modelling the team aircraft in JSBSim for the JSON
backend: a V-tail aircraft with ailerons, flaps and spoilers on one servo per
surface, retractable tricycle gear with separate nose and main retract servos,
nose-wheel steering, wheel brakes, and an electric ducted fan (EDF).

**Every number is a placeholder** for a generic 2.5 kg, 1.6 m span aircraft.
The structure (inputs, servo map, subsystems) is meant to stay; the numbers
are meant to be replaced. **`MODELING-GUIDE.md` is the step-by-step guide
to filling in every value from CAD and XFLR5**; the table at the end of this
file lists where each one lives.

## Fly it

Docker, from `sitl-docker/`:

```bash
docker compose run --rm --service-ports -e SIM_BACKEND=json -e JSBSIM_MODEL=template sitl
```

Natively, from the repository root (two terminals):

```bash
libraries/SITL/examples/JSON/JSBSim/jsbsim_json_bridge.py --aircraft template
```

```bash
Tools/autotest/sim_vehicle.py -v ArduPlane --frame plane --model JSON:127.0.0.1 \
  --add-param-file test-aircraft/template/firmwares/ardupilot_template.param
```

Two RC channels are used directly; keep both at 1000 for normal flight:

- **RC6**: spoilers (airbrake, `RC6_OPTION 210`), 1000 stowed to 2000 full.
- **RC7**: wheel brakes (SERVO13 is RC7 passed through), 1000 off to 2000 full.

## Servo outputs

| SERVO | Surface or function | `SERVOn_FUNCTION` | JSBSim input |
|---|---|---|---|
| 1 | Left aileron | 4 Aileron | `fcs/aileron-left-cmd-norm` |
| 2 | Right aileron | 4 Aileron | `fcs/aileron-right-cmd-norm` (inverted in `Controls.xml`) |
| 3 | EDF | 70 Throttle | `fcs/edf-throttle-cmd-norm` |
| 4 | Left ruddervator | 79 V-tail left | `fcs/ruddervator-left-cmd-norm` (inverted) |
| 5 | Right ruddervator | 80 V-tail right | `fcs/ruddervator-right-cmd-norm` (inverted) |
| 6 | Left flap | 3 Flap auto | `fcs/flap-left-cmd-norm` |
| 7 | Right flap | 3 Flap auto | `fcs/flap-right-cmd-norm` |
| 8 | Left spoiler | 110 Airbrake | `fcs/spoiler-left-cmd-norm` |
| 9 | Right spoiler | 110 Airbrake | `fcs/spoiler-right-cmd-norm` |
| 10 | Nose gear retract | 29 Landing gear | `fcs/gear-nose-cmd-norm` → gear unit 0 |
| 11 | Main gear retract (both) | 29 Landing gear | `fcs/gear-main-cmd-norm` → gear units 1 and 2 |
| 12 | Nose-wheel steering | 26 Ground steering | `fcs/steer-cmd-norm` |
| 13 | Wheel brakes | 57 RCIN7 | `fcs/left-brake-cmd-norm`, `fcs/right-brake-cmd-norm` |

Signs: every surface input is +1 = trailing edge down. ArduPlane's V-tail
outputs move the trailing edge *up* above 1500, so the ruddervator rows are
inverted; ailerons above 1500 mean roll right, so the right aileron row is
inverted. `Controls.xml` explains each.

## How the subsystems work

- **Surfaces** (`FlightControl.xml`, `Aero.xml`): each surface is its own
  term in the aerodynamics, so one reversed or stuck servo flies the way it
  would on the aircraft. Each V-tail panel's force is split by the tail's 35°
  dihedral into pitch (cos 35°) and yaw (sin 35°); ArduPlane's V-tail mixer
  drives both panels together for pitch and opposite for yaw.
- **Flaps**: each side adds lift (+0.2 CL at 30°), drag and a nose-down
  moment. ArduPlane sets 50% for takeoff (`TKOFF_FLAP_PCNT`) and 100% for
  landing (`LAND_FLAP_PERCNT`).
- **Spoilers**: each side removes lift (−0.15 CL) and adds drag (+0.04 CD).
  ArduPlane's automatic airbrakes need a negative `THR_MIN`, which also turns
  on reverse thrust (zero throttle at 1500); an EDF cannot reverse, so they
  are manual on RC6.
- **Landing gear** (`Gear.xml`, `FlightControl.xml`): each wheel's position is
  its retract servo's PWM, 1000 = up, 2000 = down, moving at the servo's speed
  (the `lag` on its `Controls.xml` row, 0.14 s by default). A wheel only takes
  load when fully down. Each leg adds drag while extended. Belly, nose,
  wingtip and tail contacts make a wheels-up landing scrape. ArduPlane deploys
  the gear at boot, retracts it when the takeoff completes and deploys it for
  landing (`LGR_*`).
- **Brakes**: the main wheels' brake groups, both from SERVO13, so braking
  amount is the RC7 stick position.
- **EDF** (`Systems/edf.xml`): fan = throttle through a 0.3 s lag; thrust =
  static thrust × a thrust-vs-fan table × (1 − airspeed / exhaust speed),
  applied along the fan axis (`template.xml`). Thrust falls off with speed,
  unlike a propeller table with no airspeed data. `edf/rpm` is reported.

## Tested

2026-10-25, natively, with the bridge in lockstep at 1200 Hz:

- Open loop, JSBSim only (21 checks): every surface moves the aircraft the
  right way on its own and through ArduPlane's PWM sense; EDF 19.6 N static,
  63% fan one time constant after a step, thrust falling with airspeed as
  modelled; flaps +0.40 CL, spoilers −0.30 CL and +0.08 CD; nose gear
  retracts alone and the nose drops onto the airframe; braking from 10 m/s
  takes 32 s with no brake, 3.7 s at 50% and 2.2 s at 100%; nose wheel +1
  turns right.
- Full ArduPlane mission: AUTO takeoff with half flaps, gear retracted at
  takeoff complete, 18.0 m/s cruise at 45% throttle, spoilers on RC6 (TECS
  held airspeed by adding throttle and descending), gear deployed and full
  flaps for the AUTO landing, flare, and full brakes on RC7: stopped 22 m
  after touchdown.
- `libraries/SITL/examples/JSON/JSBSim/tests/test_template.py` repeats the
  key checks on every test run.

## Replacing the placeholders

| What | Placeholder | File | Replace from |
|---|---|---|---|
| Wing area, span, chord, tail geometry | 0.40 m², 1.6 m, 0.25 m, 35° V-tail 0.55 m aft | `Metrics.xml` | Design / XFLR5 |
| IMU position | at the CG | `Metrics.xml` `EYEPOINT` | Autopilot mounting |
| Airframe mass, CG, inertia (without battery and payload, about the airframe's own CG) | 1.7 kg, 0.512 m, 0.15 / 0.20 / 0.33 kg·m² | `Mass.xml` | CAD, then weigh and swing test |
| Battery, payload | 0.6 kg, 0.2 kg; JSBSim adds them to the inertia from their positions | `Mass.xml` point masses | Components (add a battery's own `<ixx>`… from CAD) |
| Lift, drag, pitch vs alpha | CL0 0.25, slope 4.62/rad, CLmax 1.2, CD0 0.03 | `Aero.xml` tables | XFLR5 polars, drag build-up |
| Stability and damping derivatives | Cma −0.8, Cmq −12, Clp −0.45, Cnb 0.08 … | `Aero.xml` | XFLR5 stability analysis |
| Control effectiveness per surface | ailerons 0.10/rad, V-tail panels 0.175/rad … | `Aero.xml` | XFLR5 control polars |
| Surface throws | ailerons ±20°, V-tail ±30°, flaps 30° | `FlightControl.xml` | Measured on the aircraft |
| EDF | 19.6 N static, 60 m/s exhaust, 0.3 s spool, table | `Systems/edf.xml` | Datasheet, thrust stand |
| EDF position | 0.80 m aft, on the centreline | `template.xml` | CAD |
| Gear positions, springs | nose 0.20 m, mains 0.56 m ±0.15 m | `Gear.xml` | CAD, gear stiffness |
| Servo speeds | 0.14 s each | `Controls.xml` `lag=` | Servo datasheets |
| Airspeeds, trim throttle | 13 / 18 / 28 m/s, 45% | `firmwares/ardupilot_template.param` | From the model's stall speed and drag |

The aircraft modeling plan (`sitl-docker/AIRCRAFT-MODELING-PLAN.md` on the
`aircraft-modeling` branch) describes the XFLR5 workflow for these numbers.
To start a new aircraft from this one, follow step 0 of `MODELING-GUIDE.md`:
copy the folder, rename `template.xml` and the parameter file to the new
name, and change the `name` in its `<fdm_config>`.
