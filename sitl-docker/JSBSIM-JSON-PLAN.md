# Plan: JSBSim over the JSON SITL interface (16 servo channels)

Status: plan only, nothing implemented yet. Branch: `jsbsim-json-backend`.

## 1. Goal

Fly ArduPilot SITL against JSBSim through ArduPilot's **JSON** physics
interface (`--model JSON:<host>`), so that **every one of the 16 servo
outputs** (32 with `SERVO_32_ENABLE=1`) can drive any input a JSBSim aircraft
XML exposes. The channel-to-input mapping lives in a per-aircraft
`Controls.xml` next to the aircraft, in the same format as the
[PteroSimAircrafts](https://github.com/PteroLabsAI/PteroSimAircrafts)
repository, so aircraft from there can be dropped into
`Tools/autotest/aircraft/` and flown with no translation.

The existing `jsbsim` backend stays as it is and remains the default until the
new one is proven.

## 2. Why the current backend cannot do this

`libraries/SITL/SIM_JSBSim.cpp` (the `--frame jsbsim` backend):

| Limitation | Where |
|---|---|
| Only 4 channels are sent: SERVO1..4 as aileron, elevator, throttle, rudder | `send_servos()`, lines 345-348 |
| Elevon and V-tail mixing is hard-coded in C++ (`FRAME_ELEVON`, `FRAME_VTAIL`) | lines 349-363 |
| One engine only (`fcs/throttle-cmd-norm`, `engine[0]`) | lines 116, 369 |
| Control goes over JSBSim's text console socket (`set ...` / `iterate 1` per frame) | lines 365-374 |
| State comes back as the FlightGear `FGNetFDM` struct: fixed fields, no wind, no quaternion, 2 RPMs | `recv_fdm()` |
| Adding a channel means editing and recompiling ArduPilot | |

The JSON backend (`libraries/SITL/SIM_JSON.cpp`) already sends all 16 (or 32)
PWM values every frame and runs in lockstep. All that is missing is a physics
process on the other end that runs JSBSim.

## 3. Architecture

```
ArduPlane SITL  (--model JSON:127.0.0.1)
   │  UDP → :9002   binary servo packet: magic, frame_rate, frame_count, pwm[16|32]
   ▼
jsbsim_json_bridge.py
   │  1. parse packet               (16 or 32 channels, by magic)
   │  2. apply Controls.xml rows    (PWM → normalised → in/out map → property)
   │  3. fdm.run() × N              (JSBSim Python module, FGFDMExec in-process)
   │  4. read state properties      (IMU, position, velocity, attitude, airspeed, wind …)
   ▼
   UDP → back to the sender         one JSON line per frame
ArduPlane SITL
```

Decisions:

- **External bridge, not a new C++ SITL backend.** ArduPilot's own guidance for
  new physics is the JSON interface (`libraries/SITL/examples/JSON/`), it keeps
  our fork's diff against upstream small, and the bridge can be edited without
  recompiling ArduPilot. PteroSim uses the same split: its ArduPilot parameter
  files are launched with `sim_vehicle.py --model JSON:<host>`.
- **Python, using the `jsbsim` module** (`FGFDMExec` in-process). Direct
  property access replaces the text console and the FGNetFDM struct, and the
  bridge controls the timestep exactly. A C++ port is only needed if profiling
  (Phase 1) shows Python cannot hold the SITL frame rate.
- **Lockstep.** One servo packet in → JSBSim advanced by exactly one SITL frame
  → one JSON reply. SITL already handles speed-up and pausing.

## 4. Files

| File | New/changed | Purpose |
|---|---|---|
| `libraries/SITL/examples/JSON/JSBSim/jsbsim_json_bridge.py` | new | The bridge: socket loop, JSBSim setup, state output. Marked `AP_FLAKE8_CLEAN`. |
| `libraries/SITL/examples/JSON/JSBSim/controls.py` | new | Parses `Controls.xml`, validates rows, applies PWM to properties. No JSBSim import, so it can be unit tested alone. |
| `libraries/SITL/examples/JSON/JSBSim/readme.md` | new | How to run it, binding format, troubleshooting. |
| `libraries/SITL/examples/JSON/JSBSim/tests/test_controls.py` | new | pytest for the binding maths and parser. |
| `libraries/SITL/examples/JSON/JSBSim/pterosim/` | new | ArduPilot bindings and parameters for PteroSimAircrafts models that ship without them (`advanced_plane`). |
| `Tools/autotest/default_params/plane-jsbsim-json.parm` | new | Overrides on top of `plane-jsbsim.parm` for the JSON frame. |
| `Tools/autotest/pysim/vehicleinfo.py` | changed | New ArduPlane frame `jsbsim-json` with `"model": "JSON:127.0.0.1"`. The exact-match lookup in `options_for_frame()` runs before the `startswith("jsbsim")` fallback, so it does not collide with `jsbsim`. |
| `sitl-docker/Dockerfile` | changed | Build JSBSim's Python module from the same pinned source (`JSBSIM_REF=v1.3.3`, `-DBUILD_PYTHON_MODULE=ON`, install into `/opt/venv`). Not `pip install jsbsim`: PyPI 1.3.3 has no Linux aarch64 wheel, which is what Docker runs on Apple Silicon. |
| `sitl-docker/entrypoint.sh` | changed | `SIM_BACKEND=jsbsim\|json`. For `json`: start the bridge in the background, then `sim_vehicle.py --frame jsbsim-json`. Kill the bridge on exit. |
| `sitl-docker/docker-compose.yml` | changed | `SIM_BACKEND`, `JSBSIM_MODEL` (aircraft name), `CONTROLS` (optional path) env vars. |
| `sitl-docker/smoke_test.py` | changed | Also run with `SIM_BACKEND=json`. |
| `libraries/SITL/SIM_JSON.cpp` | done | Rangefinder loop fixed from upstream (see §10). |

## 5. Binding file: `Controls.xml`

Same format as PteroSimAircrafts, read by the bridge only (JSBSim never reads
it). The ArduPilot rows of PteroSimAircrafts' `c172p`:

```xml
<control_bindings stack="PX4" pilot="direct">
  <binding stack="ArduPilot" channel="0" type="Aileron" in="-1 1" out="-1 1" label="aileron"/>
  <binding stack="ArduPilot" channel="1" type="Elevator" in="-1 1" out="-1 1" label="elevator"/>
  <binding stack="ArduPilot" channel="2" type="Motor" index="0" in="0 1" out="0 1" label="io320"/>
  <binding stack="ArduPilot" channel="3" type="Rudder" in="-1 1" out="-1 1" label="rudder"/>
  <binding stack="ArduPilot" channel="3" property="fcs/steer-cmd-norm" in="-1 1" out="-1 1" invert="1" label="nosewheel"/>
  <binding stack="ArduPilot" channel="4" type="Flaps" in="0 1" out="0 1" label="flaps"/>
</control_bindings>
```

The Rascal has no `Controls.xml`: the bridge's built-in bindings (SERVO1..4
on aileron, elevator, throttle, rudder, as the `jsbsim` frame) already match
`plane-jsbsim.parm`.

### ArduPilot sign convention (typed Elevator and Rudder rows)

PteroSim's c172p notes: ArduPlane's elevator and rudder outputs above 1500 are
nose up and yaw right, JSBSim's `fcs/elevator-cmd-norm` and
`fcs/rudder-cmd-norm` +1 are trailing edge down and trailing edge left. A
channel that carries a typed `Elevator` or `Rudder` row is therefore mirrored
around 1500 before any row on it reads it; the c172p's nosewheel row, on the
rudder channel, inverts it back. Consequences:

- PteroSim aircraft are flown with `models/plane.parm` (no
  `SERVOn_REVERSED`), not `plane-jsbsim.parm`.
- Property rows (`property=`) are never mirrored; signs are set with
  `invert`.
- The parameter-file cross-check below warns when a mirrored channel also has
  `SERVOn_REVERSED 1`.

### Attributes

| Attribute | Meaning | Default |
|---|---|---|
| `channel` | Servo output, 0-based: `channel = SERVOn - 1`. 0..15, or 0..31 when 32-channel packets arrive. | required |
| `stack` | Autopilots this row applies to (space separated). The bridge keeps rows naming `ArduPilot` and rows with no `stack`. `PX4`, `BetaFlight`, `Manual` rows are ignored. | all |
| `type` + `index` | A named JSBSim input (table in §6). `index` selects the engine for per-engine types. | `index="0"` |
| `property` | Any JSBSim property path. Used instead of, or together with, `type`. | |
| `in` | Normalised input range, two numbers. Also selects the PWM conversion, below. | `0 1` |
| `out` | Range written to the property. | `0 1` |
| `invert` | `1` mirrors the value inside `in`: `x' = in_min + in_max - x` (−x for `-1 1`, 1−x for `0 1`). | `0` |
| `lag` | **Our extension** (PteroSim files do not use it). Time constant in seconds of a first-order lag: the model SITL applies with `SIM_SERVO_SPEED` when `SIM_SERVO_DELAY` and `SIM_SERVO_FILTER` are 0 (`ServoModel::apply_simple_filter`), so `0.14` matches SITL's default. `0` = no lag. | `0` |
| `label` | Free text for logs. | |

### PWM → property, per row

1. `pwm == 0` → channel not output by ArduPilot → **skip the row** (property
   keeps its last value or its XML default).
2. Normalise, choosing by the sign of `in_min` (the rule PteroSim documents in
   `orca` and `quiver`: "PWM 1000..2000 read as 0..1", and -1..1 for servos):
   - `in_min >= 0`: `x = (pwm - 1000) / 1000`
   - `in_min < 0`:  `x = (pwm - 1500) / 500`
3. Clamp `x` to `in`, apply `invert`.
4. Linear map `in → out`: `y = out_min + (x - in_min) * (out_max - out_min) / (in_max - in_min)`.
5. If `lag > 0`, filter `y` with that first-order lag over this frame's
   `dt`.
6. Write `fdm[property] = y`.

Fan-out is allowed: one channel may feed several rows (c172p drives rudder and
nosewheel from channel 3; ingenuity drives two motors from one RSC channel).
Fan-in is a load error: two rows writing the same property would fight.

### From ArduPilot parameters to JSBSim

The bridge receives PWM, never parameters. ArduPilot's servo parameters turn
demands into PWM; `Controls.xml` turns PWM into JSBSim properties. The two are
joined only by the channel number (`channel = SERVOn - 1`), so each aircraft
folder keeps both: `Controls.xml` and the ArduPilot parameter file it was
written against (PteroSim keeps `firmwares/ardupilot_<model>.param` beside
`Controls.xml` for the same reason).

| Concern | Owned by |
|---|---|
| Which function is on which output | `SERVOn_FUNCTION` |
| End points, centre, direction on the autopilot side | `SERVOn_MIN`, `SERVOn_MAX`, `SERVOn_TRIM`, `SERVOn_REVERSED` |
| Which JSBSim input an output drives, and its range | `Controls.xml`: `channel`, `type`/`property`, `in`/`out` |
| ArduPilot and JSBSim disagreeing on a sign | `SERVOn_REVERSED` **or** `invert`, never both (both = reversed twice) |
| Servo speed | `lag` on the row (SITL's `SIM_SERVO_SPEED` does not reach a JSON backend), or an `<actuator>` with `<rate_limit>` in the model's FCS, not both |
| Degrees of throw, mixing inside the model | The aircraft's JSBSim XML |

Rules that follow from the fixed PWM scale in step 2:

- **End points.** Full scale is PWM 1000..2000. If an aircraft's
  `SERVOn_MIN/MAX` are narrower, say 1100..1900, the surface never reaches
  full throw unless the row's `in` is narrowed to match: `in="-0.8 0.8"` for
  a servo, `in="0.1 0.9"` for a motor (PteroSim's `quiver` does this for
  1050..1950 with `in="0.05 0.95"`).
- **Trim.** −1..1 rows are centred on 1500. A `SERVOn_TRIM` other than 1500
  arrives as a standing offset (PteroSim's `explora` notes 1552 →
  +0.10), so either keep trims at 1500 in the sim parameter file or accept the
  offset as the real linkage's.
- **Direction.** Pick one place per surface. Today's `plane-jsbsim.parm`
  reverses elevator and rudder with `SERVO2_REVERSED` / `SERVO4_REVERSED`, so
  any `Controls.xml` used with it must not also `invert` them. PteroSim files
  written for their own parameter files (c172p) invert in `Controls.xml`
  instead; use them with their parameter file, not with `plane-jsbsim.parm`.

### Parameter-file cross-check

`Controls.xml` may name its parameter file:

```xml
<control_bindings stack="ArduPilot" params="firmwares/ardupilot_rascal.param">
```

Default: `Tools/autotest/default_params/plane-jsbsim.parm` plus
`plane-jsbsim-json.parm` (what the `jsbsim-json` frame loads), with
ArduPlane's default functions for SERVO1..4 (aileron, elevator, throttle,
rudder) where the files do not set them. At startup the bridge reads it (plain
`NAME value` lines, `#` comments) and prints a table, one line per channel:
`SERVOn`, `FUNCTION`, `MIN/MAX/TRIM/REVERSED`, and the rows bound to it. It
warns, without stopping, when:

- a bound channel has `SERVOn_FUNCTION` 0 (disabled) or unset with no
  ArduPlane default: the property will never move;
- a channel has a non-zero function but no row: ArduPilot drives an output the
  model ignores;
- `SERVOn_REVERSED 1` and the row has `invert="1"`, or the channel is
  mirrored (typed Elevator/Rudder): reversed twice;
- `SERVOn_MIN/MAX` differ from 1000/2000 while `in` is full scale, or
  `SERVOn_TRIM` is not 1500 on a −1..1 row: the end-point and trim rules above;
- a `type` and a function disagree in an obvious way, using a small table
  (`Aileron`↔4, `Elevator`↔19, `Rudder`↔21, `Motor`↔70 or 33..40 or 73/74,
  `Flaps`↔2/3, `Steering`↔26 …), so `Flaps` on a throttle output is flagged.

The parameter file is what the sim *starts* with; a parameter changed later
from the GCS is not seen. Phase 4 can add `--mavlink` to fetch the live
`SERVOn_*` values from SITL (read only) and re-run the same checks.

### Load-time validation (fail fast, print the row)

- channel out of range, malformed `in`/`out`, `in_min == in_max`
- `type` not in §6 and no `property`
- the property does not exist after the model loads
  (`fdm.get_property_manager().hasNode(...)`): a typo would otherwise create a
  new, unused property and the surface would silently never move
- two rows writing one property
- print a table of active rows at startup: channel → property, range, label
- then run the parameter-file cross-check above (warnings only)

When an aircraft has no `Controls.xml`, the bridge falls back to a built-in
table equal to today's `jsbsim` backend (SERVO1..4 → aileron, elevator,
throttle, rudder), so `Rascal` flies unchanged.

## 6. JSBSim inputs the bindings can drive

How a JSBSim aircraft takes inputs, and how each kind is reached from a
binding row.

### 6.1 Standard FCS command properties (`type=`)

Created by JSBSim itself (`FGFCS::bind`, `FGGroundReactions::bind`) for every
aircraft. The model's `<flight_control>` / `<system>` channels read them.

| `type` | Property | Typical `in`/`out` |
|---|---|---|
| `Aileron` | `fcs/aileron-cmd-norm` | -1 1 |
| `Elevator` | `fcs/elevator-cmd-norm` | -1 1 |
| `Rudder` | `fcs/rudder-cmd-norm` | -1 1 |
| `Flaps` | `fcs/flap-cmd-norm` | 0 1 |
| `Speedbrake` | `fcs/speedbrake-cmd-norm` | 0 1 |
| `Spoiler` | `fcs/spoiler-cmd-norm` | 0 1 |
| `PitchTrim` | `fcs/pitch-trim-cmd-norm` | -1 1 |
| `RollTrim` | `fcs/roll-trim-cmd-norm` | -1 1 |
| `YawTrim` | `fcs/yaw-trim-cmd-norm` | -1 1 |
| `Steering` | `fcs/steer-cmd-norm` | -1 1 |
| `BrakeLeft` | `fcs/left-brake-cmd-norm` | 0 1 |
| `BrakeRight` | `fcs/right-brake-cmd-norm` | 0 1 |
| `BrakeCenter` | `fcs/center-brake-cmd-norm` | 0 1 |
| `Brake` | left and right brake together | 0 1 |
| `Gear` | `gear/gear-cmd-norm` | 0 1 |

### 6.2 Per-engine commands (`type=` + `index=`)

JSBSim creates one of each per engine, in the order `<engine>` elements
appear in `<propulsion>`. `FGFCS` copies each `*-cmd-norm[n]` to
`*-pos-norm[n]` every frame unless the model's FCS writes the `pos` itself, so
binding the `cmd` property works in both cases.

| `type` | Property | Notes |
|---|---|---|
| `Motor` | `fcs/throttle-cmd-norm[n]` | Also sets `propulsion/engine[n]/set-running = 1` the first time the command exceeds 0.01 (PteroSim's behaviour), so electric motors and piston engines start without a script. |
| `Mixture` | `fcs/mixture-cmd-norm[n]` | Piston engines. |
| `PropAdvance` | `fcs/advance-cmd-norm[n]` | Variable-pitch / constant-speed propeller. |
| `PropFeather` | `fcs/feather-cmd-norm[n]` | |
| `Collective` | `propulsion/engine[n]/collective-ctrl-rad` | `FGRotor` thrusters (helicopters), as `orca` binds them. |
| `CyclicLateral` | `propulsion/engine[n]/lateral-ctrl-rad` | `FGRotor`. |
| `CyclicLongitudinal` | `propulsion/engine[n]/longitudinal-ctrl-rad` | `FGRotor`. |

### 6.3 Propulsion-wide commands (`type=`)

| `type` | Property | Notes |
|---|---|---|
| `Starter` | `propulsion/starter_cmd` | 0/1 |
| `Magneto` | `propulsion/magneto_cmd` | 0 off … 3 both; use `out="0 3"`, value rounded |
| `Cutoff` | `propulsion/cutoff_cmd` | turbines, 0/1 |

### 6.4 Any other property (`property=`)

Everything else an aircraft XML can read is a property, so a `property=` row
reaches it:

- **Model-defined command properties** declared in `<flight_control>` or a
  `<system>` file with `<property value="0">fcs/…</property>`. This is how
  PteroSim aircraft expose per-surface servos (`fcs/servo-0-cmd-norm` …
  `fcs/servo-5-cmd-norm` in `advanced_plane/FlightControl.xml`), mixed
  swashplate servos (`ingenuity`: `fcs/upper-swash-servo0..2`, demixed by
  `Systems/rotor_control.xml`), tilt and swivel commands (`ZLT-NT`), and so on.
- **Inputs of FCS components.** Every `<summer>`, `<gain>`,
  `<aerosurface_scale>`, `<actuator>`, `<kinematic>`, `<switch>`, `<pid>`,
  `<fcs_function>` reads its `<input>` properties (a leading `-` negates). A
  binding can write any of them, but the convention is to bind a dedicated
  `…-cmd-norm` property and let the model scale it.
- **External forces**: `<external_reactions>` `<force name="X">` reads its
  magnitude from `external_reactions/X/magnitude`. A parachute, tow hook or
  extra thruster can be driven from a spare servo this way.
- **Systems with an enable switch** (`ingenuity`'s `fcs/manual/enable`).

The type table in 6.1-6.3 is a convenience; `property=` is the general case.

### 6.5 Inputs that are not servo channels

Handled by the bridge, not by bindings:

| Input | How |
|---|---|
| Initial conditions (`<initialize>`: lat, lon, altitude, heading, speed) | Bridge `--home lat,lon,alt,hdg` (the entrypoint resolves `LOCATION` from `Tools/autotest/locations.txt`). Written to `ic/…` before `run_ic()`. `ic/terrain-elevation-ft` is set to the home altitude so JSBSim's ground is where ArduPilot expects it. |
| Ground trim (`simulation/do_simple_trim`) | Set to `2` once after start, as the current backend's script does. |
| Wind and turbulence (`atmosphere/psiw-rad`, `atmosphere/wind-mag-fps`, `atmosphere/turbulence/milspec/*`) | The JSON servo packet carries no wind, so `SIM_WIND_*` does not reach the bridge. Phase 4: `--wind dir,speed,turb` on the bridge; later, optionally read `SIM_WIND_*` over MAVLink. |
| JSBSim's own `<input>` sockets (`type="SOCKET"` text console; `type="QTJSBSIM"` UDP comma-separated property list) | Not used. The bridge sets properties in-process. Noted because a C++ fallback (§13) could use the UDP form. |

## 7. State sent back to ArduPilot (JSON fields)

| JSON field | JSBSim property | Conversion |
|---|---|---|
| `timestamp` | `simulation/sim-time-sec` | s |
| `imu.gyro` | `velocities/p-rad_sec`, `q-rad_sec`, `r-rad_sec` | body rad/s |
| `imu.accel_body` | `accelerations/a-pilot-x-ft_sec2`, `-y-`, `-z-` | × 0.3048. Specific force, so ≈ (0,0,−9.81) at rest, same as today's backend. Measured at the model's `EYEPOINT`; set that to the autopilot location in the aircraft XML. |
| `velocity` | `velocities/v-north-fps`, `v-east-fps`, `v-down-fps` | × 0.3048 |
| `latitude`, `longitude`, `altitude` | `position/lat-geod-deg`, `position/long-gc-deg`, `position/h-sl-meters` | deg, deg, m AMSL. SIM_JSON sets home from the first fix. |
| `attitude` | `attitude/phi-rad`, `theta-rad`, `psi-rad` | rad (or send `quaternion` computed from them) |
| `airspeed` | `velocities/vc-fps` | × 0.3048 (calibrated, as today's backend uses `vcas`) |
| `velocity_wind` | `atmosphere/total-wind-north-fps`, `-east-`, `-down-` | × 0.3048 |
| `rng_1` | `position/h-agl-ft` | × 0.3048 / (cos φ · cos θ), capped at a configured max range; only when `--rangefinder` is given |
| `battery.voltage`, `battery.current` | configurable property names (e.g. from a model `<system>`) | only when configured |

Property names are checked against the pinned JSBSim version in Phase 1.

## 8. Lockstep

The bridge runs in strict lockstep with SITL: JSBSim never advances unless
ArduPilot asked for a frame, and ArduPilot never advances unless JSBSim
answered. Speed-up is out of scope for now (SITL's `sync_frame_time()`
already throttles wall-clock time; the bridge only has to answer quickly).

### What SITL does (`libraries/SITL/SIM_JSON.cpp`)

1. `update()` sends one servo packet (`output_servos()`), then blocks in
   `recv_fdm()` until a JSON line arrives (100 ms receive timeouts, servo
   packet resent every ~1 s with the **same** `frame_count`).
2. It advances its own clock by `timestamp − last_timestamp` from the JSON,
   never by wall-clock time. A backwards `timestamp` is treated as a physics
   reset (`deltat = 0`).
3. `frame_count` increments once per packet sent, and resets to 0 when SITL
   restarts.
4. If the JSON contains `"no_lockstep": true`, SITL stops waiting and free-runs.
   The bridge never sends it.

### What the bridge does

```
state: last_count = None, last_reply = None

loop:
    pkt, addr = recv()                       # blocking, no timeout
    if magic not in (18458, 29569): drop
    if last_count is not None and pkt.frame_count == last_count:
        send(last_reply, addr)               # SITL resend: answer, do not step
        continue
    if last_count is not None and pkt.frame_count < last_count:
        fdm.reset_to_initial_conditions(0)   # SITL restarted
        re-run ground trim; clear engine auto-start flags
    dt = 1 / pkt.frame_rate                  # follows SIM_RATE_HZ changes
    if dt != fdm.get_delta_t(): fdm.set_dt(dt)
    apply bindings(pkt.pwm)
    fdm.run()                                # exactly one JSBSim step
    last_reply = build_json(fdm)             # timestamp = simulation/sim-time-sec
    send(last_reply, addr)
    last_count = pkt.frame_count
```

Rules that keep it deterministic:

- **One packet → one step → one reply.** No timers, threads or wall-clock
  reads in the loop. The same SITL inputs give the same flight every run.
- **Reply to the packet's source address**, so the bridge never needs to know
  SITL's port, and a restarted SITL is picked up automatically.
- **Timestamps strictly increase** within a session: `sim-time-sec` after the
  step. The first reply after a reset restarts near 0, which SITL already
  treats as a reset.
- **No stale packets.** Before handling a packet, drain the socket and keep
  only the newest one, so a burst of SITL resends after a pause does not make
  the bridge step several times for one frame. A drained packet with a new
  `frame_count` that is not the newest is logged as a dropped frame.
- **`frame_rate` is SITL's step, not a hint.** JSBSim's `dt` is set to
  exactly `1/frame_rate` so both clocks agree. SITL defaults to
  `SIM_RATE_HZ 1200` (833 µs per frame); Phase 1 measures the bridge's time
  per frame. If it is too slow, `plane-jsbsim-json.parm` sets
  `SIM_RATE_HZ 400` (ArduPlane's main loop runs at 50 Hz, 300 Hz with
  QuadPlane enabled, so 400 stays above both), and §13 applies if even that
  does not fit.

### Lockstep tests (Phase 1)

- Unit: a fake SITL socket sends counts 0,1,1,2 → bridge steps 3 times, replies 4
  times, the duplicate reply is byte-identical.
- Unit: counts 5,6,0 → reset is called once, timestamp of the reply to 0 is
  below the reply to 6.
- Integration: pause SITL for 10 s, resume, check that JSBSim's
  `sim-time-sec` and SITL's `SIM_TIME` (log `SIM` messages) still agree to
  within one frame.
- Integration: two identical 3-minute AUTO flights give identical dataflash
  `SIM` positions (determinism).

## 9. Docker and launch

```bash
# new backend
docker compose run --rm --service-ports -e SIM_BACKEND=json sitl
# another aircraft with its own Controls.xml
docker compose run --rm --service-ports -e SIM_BACKEND=json -e JSBSIM_MODEL=c172p sitl
```

The entrypoint, when `SIM_BACKEND=json`:

1. Resolves `LOCATION` / `CUSTOM_LOCATION` to `lat,lon,alt,hdg`.
2. Starts `python3 libraries/SITL/examples/JSON/JSBSim/jsbsim_json_bridge.py
   --root Tools/autotest --aircraft ${JSBSIM_MODEL} --home …` in the
   background, prefixing its output with `[bridge]`.
3. Runs `sim_vehicle.py --frame jsbsim-json …` (everything else unchanged:
   MAVProxy options, `--enable-fgview`).
4. Traps exit and stops the bridge.

FlightGear view keeps working: `--enable-fgview` / `--fg` is SITL's own output
from its vehicle state, independent of the physics backend.

## 10. Fixed: rangefinder parsing in SIM_JSON

Done on this branch: ArduPilot was updated to Plane-4.7.2, and the upstream
fix (`e5e9709`, not in any Plane release yet) was cherry-picked on top. Kept
here for the record. Before the fix, `libraries/SITL/SIM_JSON.cpp:465` read:

```cpp
for (uint8_t i=7; i<13; i++) {
    if ((received_bitmask &  1ULL << i) == 0) { continue; }
    rangefinder_m[i-7] = state.rng[i-7];
}
```

Bits 7..12 are `EULER_ATT`, `QUAT_ATT`, `VELOCITY`, `RNG_1..3` (see `DataKey`
in `SIM_JSON.h`), so `rng_4..6` were never read and `rng_1..3` were copied
whenever attitude or velocity arrived. Upstream's fix, now in this tree:

```cpp
for (uint8_t i=0; i<6; i++) {
    if ((received_bitmask & (RNG_1 << i)) == 0) { continue; }
    rangefinder_m[i] = state.rng[i];
}
```

## 11. Tuning support

The tuning procedure (what to take from the sim, the robustness sweep, log
replay, envelope expansion) is its own plan: `sitl-docker/TUNING-PLAN.md`
on the `tuning-workflow` branch. The aircraft model, its `scale/*`
properties and mass variants come from `sitl-docker/AIRCRAFT-MODELING-PLAN.md`
on the `aircraft-modeling` branch. This section specifies only what the
bridge provides for them (Phase 6).

### Model variation

```bash
jsbsim_json_bridge.py --aircraft Team --variant inertia-hi --scale scale/roll-power=0.7 ...
```

- `--scale PROP=VALUE` (repeatable): sets a `scale/…` property before
  `run_ic()`. The property must already exist in the model (declared with
  `<property value="1">`); an unknown one is a startup error, like an
  unknown binding property (§5).
- `--variant NAME`: loads `<aircraft>-<NAME>.xml` instead of
  `<aircraft>.xml`. Mass, inertia and CG change this way because JSBSim's
  inertia properties (`inertia/ixx-slugs_ft2` …) are read-only at runtime.
- `--set PROP=VALUE` (repeatable): any other property at startup, e.g.
  moving a ballast point mass (`inertia/pointmass-location-X-inches[n]`).
- The startup banner prints every scale, variant and set value, so a sweep
  log records exactly which model flew.

### Sensor realism

- `--imu-noise FILE`: adds recorded noise to `imu.gyro` and
  `imu.accel_body` before sending. FILE is extracted from the real
  aircraft's batch-sampler log (`INS_LOG_BAT_*`): noise sequences binned by
  throttle, played back for the current throttle with a seeded random
  start, so runs stay repeatable. Not `SIM_GYR_FILE_RW`: that replaces the
  simulated IMU instead of adding to it.
- `rpm`: per-engine `propulsion/engine[n]/propeller-rpm` in the JSON state,
  so `SIM_VIB_MOT_MAX` works. Needs an `rpm` array in SIM_JSON's keytable
  (`libraries/SITL/SIM_JSON.h`; check upstream first) feeding
  `Aircraft::rpm[]`.

### Log replay

`jsbsim_json_bridge.py --replay flight.bin [--segment START,END]...`

- Reads `RCOU` (C1..C14) and `RCO2` (C15, C16) PWM from the dataflash log
  with pymavlink and applies them through the same `Controls.xml` at the
  logged timestamps; JSBSim runs at the log's rate, no SITL.
- Each segment starts from the logged state: position (`POS`), attitude
  (`ATT`), velocity (`XKF1` or GPS), airspeed (`ARSP`), body rates (`IMU`).
- Writes `<log>-replay.csv` with logged and simulated roll/pitch/yaw rate,
  attitude, airspeed and body accelerations per segment, plus a plot per
  segment.
- Same `--scale` / `--variant` options, so a fit can vary them.

### Sweep runner

`libraries/SITL/examples/JSON/JSBSim/sweep.py`:

- input: a variant list (YAML: scale, variant and set values per run), a
  parameter file, optionally a list of airspeeds;
- per run: start the bridge with that variant, start SITL with
  `--frame jsbsim-json` and the parameters, fly the scripted test sequence
  over MAVLink (pymavlink), collect the dataflash log, stop both;
- score each run against the pass criteria in the tuning plan and write one
  summary table (run, variant, pass/fail per criterion, margins);
- runs are independent, so several can run at once on different SITL
  instances (`-I N`) with different bridge ports.

## 12. Phases

Each phase ends with something that runs.

1. **Bridge skeleton, Rascal only.** Packet parse (16 and 32), JSBSim load,
   IC, built-in default bindings, JSON output from §7, lockstep and reset
   handling. Measure per-frame time at 1200 Hz. Done when ArduPlane arms,
   takes off in FBWA and flies an AUTO circuit at CMAC on `--frame
   jsbsim-json`, both natively and in Docker.
   *Status: done natively (2026-10-25): the Rascal flies the same circuit as
   on the C++ backend, at about 60 µs per frame. Docker: see Phase 5.*
2. **`Controls.xml` support.** `controls.py`, the full type table (§6),
   validation, startup table, `Motor` auto-start, `lag`, and the
   parameter-file cross-check. Built-in bindings reproducing the default
   behaviour for aircraft without a `Controls.xml` (the Rascal). pytest for: PWM 0 skip, both normalisations,
   invert on both ranges, in→out map, clamping, `lag` against
   `ServoModel`'s numbers, fan-out, fan-in error, unknown property error,
   stack filtering, and each cross-check warning (disabled function, unbound
   function, double reversal, narrow end points, off-centre trim, type vs
   function). Check by flying: a step on each stick moves the matching
   surface the right way (JSBSim `fcs/*-pos-deg`).
   *Status: done except the parameter-file cross-check. Also `--aircraft-dir`
   for external aircraft folders, the ArduPilot sign convention (§5) and
   piston-engine start (mixture, magnetos).*
3. **Prove all 16 channels.** A test aircraft config (Rascal plus
   `fcs/test-ch-N` properties declared in a small `<system>`), bind channels
   0..15, set `SERVOn_FUNCTION` to RCIN passthrough (51..66), sweep each RC
   input and check each property follows. Then fly a PteroSimAircrafts model
   that needs more than 4 channels with its own `Controls.xml` unmodified:
   `explora` (ArduPlane tailsitter, channels 4, 5, 8, 9, param file in
   `firmwares/ardupilot_explora.param`) or `c172p` (flaps on channel 4).
   *Status: PteroSimAircrafts' fixed-wing `c172p` (its own bindings and
   parameters) and `advanced_plane` (bindings and parameters in
   `pterosim/`) fly AUTO takeoff, a box and RTL; see `pterosim/README.md`.
   The 16-channel sweep and the VTOL models are not done.*
4. **Environment.** Wind and turbulence from bridge options; rangefinder;
   battery fields from configured properties; optional `--mavlink` live
   `SERVOn_*` cross-check.
5. **Docker integration and docs.** JSBSim Python module built in the
   Dockerfile, entrypoint `SIM_BACKEND`, compose variables, smoke test for
   both backends, readme and a section in `sitl-docker/README.md`.
   *Status: Dockerfile (`pip install jsbsim==<JSBSIM_REF>`, compiled from
   source on arm64), entrypoint (`SIM_BACKEND`, `JSBSIM_MODEL`,
   `JSBSIM_AIRCRAFT_DIR`, `JSBSIM_CONTROLS`, `JSON_FRAME`, `PARAM_FILES`,
   `BRIDGE_ARGS`), compose and README done. Smoke test not yet extended.*
6. **Tuning tools (§11).** `--scale`, `--variant`, `--set`, `--imu-noise`,
   `rpm` in the JSON state, `--replay` with comparison output, `sweep.py`. Done when a robustness sweep on the team model runs
   unattended and a replay of a SITL-recorded log reproduces it (the model
   replaying its own flight must match closely; that proves the replay path
   before real logs exist).

## 13. Risks

| Risk | Mitigation |
|---|---|
| Python too slow at 1200 Hz | Measure in Phase 1. `SIM_RATE_HZ 400` first; then move the hot loop to C++ against libJSBSim (same bindings file, same JSON). |
| Python module and `JSBSim` binary from different JSBSim versions | Both are built from one checkout at the pinned `JSBSIM_REF` (now `v1.3.3`), so they cannot differ. |
| IMU at `EYEPOINT` instead of CG/autopilot location gives lever-arm accelerations | Document it; set `EYEPOINT` to the autopilot position in each model. |
| PteroSim aircraft licences (GPL, LGPL, CERN-OHL-S, NASA media terms) | Copy an aircraft only with its `LICENSE` and `NOTICE`, and record the source commit. Copying is not part of this plan. |
| Gimbal / Gripper rows in PteroSim files have no JSBSim property | Ignored with a warning unless the row also has `property=`. |
| `Controls.xml` and the parameter file drift apart (a function moved to another SERVOn, a reversal added in both places) | Parameter-file cross-check at startup (§5); live check over MAVLink in Phase 4. |
| A PteroSim aircraft flown with `plane-jsbsim.parm` instead of its own parameter file | Its rows assume its own reversals; the cross-check flags double reversals. Load its `firmwares/ardupilot_*.param` with it. |
| Home altitude mismatch (JSBSim ground vs ArduPilot home) | Set `ic/terrain-elevation-ft` from `--home`; Phase 1 checks that AGL on the ground is the gear height. |

## 14. Out of scope

- Changing or removing the existing `jsbsim` C++ backend.
- Copying PteroSimAircrafts models into this repository.
- Copter / QuadPlane default parameter sets beyond what Phase 3 needs.
- Upstreaming to ArduPilot (the §10 fix is already upstream).
