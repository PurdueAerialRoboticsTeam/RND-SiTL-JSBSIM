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
| `Tools/autotest/aircraft/Rascal/Controls.xml` | new | Rascal bindings matching ArduPlane's default SERVO1..4. |
| `Tools/autotest/default_params/plane-jsbsim-json.parm` | new | Overrides on top of `plane-jsbsim.parm` for the JSON frame. |
| `Tools/autotest/pysim/vehicleinfo.py` | changed | New ArduPlane frame `jsbsim-json` with `"model": "JSON:127.0.0.1"`. The exact-match lookup in `options_for_frame()` runs before the `startswith("jsbsim")` fallback, so it does not collide with `jsbsim`. |
| `sitl-docker/Dockerfile` | changed | `pip install jsbsim==<same version as JSBSIM_REF>` into the venv; pin `JSBSIM_REF` to that tag. |
| `sitl-docker/entrypoint.sh` | changed | `SIM_BACKEND=jsbsim\|json`. For `json`: start the bridge in the background, then `sim_vehicle.py --frame jsbsim-json`. Kill the bridge on exit. |
| `sitl-docker/docker-compose.yml` | changed | `SIM_BACKEND`, `JSBSIM_MODEL` (aircraft name), `CONTROLS` (optional path) env vars. |
| `sitl-docker/smoke_test.py` | changed | Also run with `SIM_BACKEND=json`. |
| `libraries/SITL/SIM_JSON.cpp` | changed (small) | Fix the rangefinder loop (see §10). |

## 5. Binding file: `Controls.xml`

Same format as PteroSimAircrafts, read by the bridge only (JSBSim never reads it):

```xml
<control_bindings stack="ArduPilot">
  <binding stack="ArduPilot" channel="0" type="Aileron"  in="-1 1" out="-1 1" label="aileron"/>
  <binding stack="ArduPilot" channel="1" type="Elevator" in="-1 1" out="-1 1" invert="1" label="elevator"/>
  <binding stack="ArduPilot" channel="2" type="Motor" index="0" in="0 1" out="0 1" label="engine"/>
  <binding stack="ArduPilot" channel="3" type="Rudder"   in="-1 1" out="-1 1" invert="1" label="rudder"/>
  <binding stack="ArduPilot" channel="3" property="fcs/steer-cmd-norm" in="-1 1" out="-1 1" label="tailwheel"/>
  <binding stack="ArduPilot" channel="4" type="Flaps" in="0 1" out="0 1" label="flaps"/>
</control_bindings>
```

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
5. Write `fdm[property] = y`.

Fan-out is allowed: one channel may feed several rows (c172p drives rudder and
nosewheel from channel 3; ingenuity drives two motors from one RSC channel).
Fan-in is a load error: two rows writing the same property would fight.

SERVOn_MIN/MAX/TRIM/REVERSED stay ArduPilot's job, exactly as on a real
aircraft. The bindings only describe the airframe.

### Load-time validation (fail fast, print the row)

- channel out of range, malformed `in`/`out`, `in_min == in_max`
- `type` not in §6 and no `property`
- the property does not exist after the model loads
  (`fdm.get_property_manager().hasNode(...)`): a typo would otherwise create a
  new, unused property and the surface would silently never move
- two rows writing one property
- print a table of active rows at startup: channel → property, range, label

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
| JSBSim's own `<input>` sockets (`type="SOCKET"` text console; `type="QTJSBSIM"` UDP comma-separated property list) | Not used. The bridge sets properties in-process. Noted because a C++ fallback (§12) could use the UDP form. |

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

## 8. Timing

- SITL sends `frame_rate` = `SIM_RATE_HZ` (1200 Hz by default in SITL). The
  bridge sets JSBSim's `dt = 1/frame_rate` and calls `fdm.run()` once per
  packet. If the frame rate changes, `dt` follows.
- `frame_count` repeated → resend the last state without stepping (SITL
  resends after 1 s with no reply).
- `frame_count` goes backwards → SITL restarted → `reset_to_initial_conditions`
  and restart the counter.
- Budget at 1200 Hz is 833 µs per frame. Phase 1 measures Python's cost; if it
  does not fit, `plane-jsbsim-json.parm` sets `SIM_RATE_HZ 400` (ArduPlane's
  main loop runs at 50 Hz, 300 Hz with QuadPlane enabled, so 400 stays above
  both), and §12 applies if even that does not fit.

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

## 10. Bug to fix on the way: rangefinder parsing in SIM_JSON

`libraries/SITL/SIM_JSON.cpp:465` in this tree:

```cpp
for (uint8_t i=7; i<13; i++) {
    if ((received_bitmask &  1ULL << i) == 0) { continue; }
    rangefinder_m[i-7] = state.rng[i-7];
}
```

Bits 7..12 are `EULER_ATT`, `QUAT_ATT`, `VELOCITY`, `RNG_1..3` (see `DataKey`
in `SIM_JSON.h`), so `rng_4..6` are never read and `rng_1..3` are copied
whenever attitude or velocity arrive. Upstream master already has the fix:

```cpp
for (uint8_t i=0; i<6; i++) {
    if ((received_bitmask & (RNG_1 << i)) == 0) { continue; }
    rangefinder_m[i] = state.rng[i];
}
```

Apply it as its own commit (`SITL: fix JSON rangefinder bitmask indexing`).

## 11. Phases

Each phase ends with something that runs.

1. **Bridge skeleton, Rascal only.** Packet parse (16 and 32), JSBSim load,
   IC, built-in default bindings, JSON output from §7, lockstep and reset
   handling. Measure per-frame time at 1200 Hz. Done when ArduPlane arms,
   takes off in FBWA and flies an AUTO circuit at CMAC on `--frame
   jsbsim-json`, both natively and in Docker.
2. **`Controls.xml` support.** `controls.py`, the full type table (§6),
   validation, startup table, `Motor` auto-start. `Rascal/Controls.xml`
   reproducing the default behaviour. pytest for: PWM 0 skip, both
   normalisations, invert on both ranges, in→out map, clamping, fan-out,
   fan-in error, unknown property error, stack filtering.
3. **Prove all 16 channels.** A test aircraft config (Rascal plus
   `fcs/test-ch-N` properties declared in a small `<system>`), bind channels
   0..15, set `SERVOn_FUNCTION` to RCIN passthrough (51..66), sweep each RC
   input and check each property follows. Then fly a PteroSimAircrafts model
   that needs more than 4 channels with its own `Controls.xml` unmodified:
   `explora` (ArduPlane tailsitter, channels 4, 5, 8, 9, param file in
   `firmwares/ardupilot_explora.param`) or `c172p` (flaps on channel 4).
4. **Environment.** Wind and turbulence from bridge options; rangefinder;
   battery fields from configured properties.
5. **Docker integration and docs.** Dockerfile pip install, entrypoint
   `SIM_BACKEND`, compose variables, smoke test for both backends, readme and
   a section in `sitl-docker/README.md`.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Python too slow at 1200 Hz | Measure in Phase 1. `SIM_RATE_HZ 400` first; then move the hot loop to C++ against libJSBSim (same bindings file, same JSON). |
| `pip install jsbsim` version differs from the `JSBSim` binary built from `JSBSIM_REF=master` | Pin both to one release tag. The bridge does not use the binary, but aircraft files should be validated against one version. |
| IMU at `EYEPOINT` instead of CG/autopilot location gives lever-arm accelerations | Document it; set `EYEPOINT` to the autopilot position in each model. |
| PteroSim aircraft licences (GPL, LGPL, CERN-OHL-S, NASA media terms) | Copy an aircraft only with its `LICENSE` and `NOTICE`, and record the source commit. Copying is not part of this plan. |
| Gimbal / Gripper rows in PteroSim files have no JSBSim property | Ignored with a warning unless the row also has `property=`. |
| Home altitude mismatch (JSBSim ground vs ArduPilot home) | Set `ic/terrain-elevation-ft` from `--home`; Phase 1 checks that AGL on the ground is the gear height. |

## 13. Out of scope

- Changing or removing the existing `jsbsim` C++ backend.
- Copying PteroSimAircrafts models into this repository.
- Copter / QuadPlane default parameter sets beyond what Phase 3 needs.
- Upstreaming to ArduPilot (the §10 fix is already upstream).
