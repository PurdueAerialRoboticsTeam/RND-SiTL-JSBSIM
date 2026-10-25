# Plan: preliminary tuning of the team aircraft in SITL

Status: plan only. Branch: `tuning-workflow`.

Goal: a **safe first-flight tune** for the team aircraft before it is built,
then field tuning, then a model corrected from flight logs that predicts the
tune at airspeeds not yet flown.

This plan is the procedure. It depends on two others:

| Plan | Branch | Provides |
|---|---|---|
| `sitl-docker/JSBSIM-JSON-PLAN.md` | `jsbsim-json-backend` | The JSON bridge and its tuning tools (its §11): `--scale`, `--variant`, `--replay`, `--imu-noise`, `rpm` output, `sweep.py` |
| `sitl-docker/AIRCRAFT-MODELING-PLAN.md` | `aircraft-modeling` | The team aircraft's JSBSim model, its `scale/*` properties, mass variants, and the uncertainty range of every input |

Prerequisites before §3 can start: backend Phases 1, 2 and 6; modeling
Phases 1–4.

Lockstep (backend plan §8) is what makes this work: a run depends only on
its inputs, so two tunes can be compared on identical manoeuvres and batches
can run unattended. The bridge's speed only changes how long a batch takes.

## 1. What the sim can and cannot set

| Set from the sim | Set conservatively in the sim, finish in the field | Not from the sim |
|---|---|---|
| Servo directions and throws (backend cross-check) | `RLL_RATE_P/I`, `PTCH_RATE_P/I`: low end of what is stable across all model variants (§3) | Final rate P/I/D |
| Stall speed → `AIRSPEED_MIN`, `AIRSPEED_CRUISE`, `AIRSPEED_MAX` with margin | `*_RATE_D`: 0 or near it (the sim has no structural modes and little noise, so it accepts far more D than the aircraft will) | Filter settings (`INS_GYRO_FILTER`, notches) |
| `TRIM_THROTTLE`, elevator trim implied by the CG | `RLL2SRV_TCONST`, `PTCH2SRV_TCONST`: relaxed (slower) | How much margin is enough for a first flight: a human decision, with ArduPilot's first-flight guidance |
| `RLL_RATE_FF`, `PTCH_RATE_FF` ballpark | TECS gains | |
| Pitch and roll limits, `THR_MAX`, takeoff and landing parameters | | |
| Failsafe rehearsal | | |

Field procedure after the sim tune is ArduPilot's normal one: first flight
in a stabilised mode (FBWA), check trim and directions, then AUTOTUNE in the
air. The sim's job is that the first AUTOTUNE starts from a safe place.
AUTOTUNE also runs in SITL, which rehearses the procedure, but its result is
the model's tune, not the aircraft's.

## 2. Making the sim honest for tuning

The sim is optimistic in predictable ways. Each item narrows the gap; the
right-hand column says which plan delivers it.

| Gap | Fix | Where |
|---|---|---|
| Timestep and transport delay | One frame of delay per step: 0.8 ms at `SIM_RATE_HZ 1200`, 2.5 ms at 400. Use 1200 for tuning runs if the bridge keeps up. | backend §8 |
| Servo speed | `lag` per `Controls.xml` row, or an `<actuator>` in the model's FCS, not both | backend §5 / modeling §7 |
| Servo backlash, deadband, bandwidth | `<actuator>` (`<hysteresis_width>`, `<deadband_width>`, `<lag>`, `<rate_limit>`); datasheet values, then measured on the built aircraft | modeling §7, §10 |
| Motor / ESC response | First-order throttle lag in the model's FCS, time constant from a thrust-stand step | modeling §6, §7 |
| IMU noise | SITL's own noise applies with the JSON backend (it keys off the throttle output): `SIM_GYR1_RND`, `SIM_ACC1_RND`, `SIM_VIB_FREQ_X/Y/Z`. Set from the real aircraft's logs once it flies (`VIBE`, batch sampler). | parameters |
| Motor-RPM vibration (`SIM_VIB_MOT_MAX`) | Needs per-motor RPM in the JSON state | backend §11 |
| Real recorded noise | `SIM_GYR_FILE_RW` / `SIM_ACC_FILE_RW` **replace** the simulated IMU with the file, so they suit open-loop filter tests only. For closed loop, the bridge's `--imu-noise` adds noise recorded on the real aircraft (batch sampler, matching throttle). | backend §11 |
| Airframe flex, flutter, servo stall under load | Not modelled. Expand the envelope in the field in steps (§5). | — |

## 3. Before the first flight: robustness sweep

There are no flight logs yet, so tune against a range of plausible models,
not one best guess. `sweep.py` (backend §11) launches SITL plus bridge per
variant, flies the test sequence below and scores each run. Aero factors use
the model's `scale/*` properties; mass, inertia and CG use generated mass
variants (modeling §8).

Default variant set (ranges from the model card's uncertainties):

| Factor | Range |
|---|---|
| Control power (roll, pitch, yaw) | ×0.7, ×1.0, ×1.3 |
| Damping (`Clp`, `Cmq`, `Cnr`) | ×0.7, ×1.0, ×1.3 |
| Inertia (`ixx`, `iyy`, `izz`) | ×0.8, ×1.0, ×1.2 |
| CG | forward limit, nominal, aft limit |
| Servo `lag` | ×1, ×2 |
| IMU noise | off, on |

Full factorial is too many runs; use the corners that matter (low control
power with high inertia, aft CG with low damping, …) plus a small random
sample. **Gains are accepted only if every variant passes.**

Test sequence (scripted over MAVLink with pymavlink, in FBWA and AUTO): roll
and pitch steps at three airspeeds, a 60° bank turn each way, a climb and
descent at `THR_MAX`, an AUTO circuit, a landing.

Pass criteria per run (thresholds set by the team before the first sweep):
- no sustained oscillation: rate-error power after a step below a threshold;
- overshoot and settling time within limits;
- no servo or throttle saturation longer than a set time;
- airspeed never below `AIRSPEED_MIN`;
- TECS height error within limits.

Output: one `.param` file for the first flight, plus the sweep report showing
the margin each variant had.

## 4. After the first flights: log replay and model correction

1. **Parameters.** Extract the `PARM` messages from the dataflash log to a
   `.param` file (`mavparms.py flight3.bin > flight3.param`, from pymavlink's
   tools; check it loads as a param file and trim non-parameter lines if
   needed). SITL loads it with `--add-param-file`, and the bridge's
   cross-check reads the same file, so the sim flies exactly what the
   aircraft flew.
2. **Open-loop replay.** The bridge's `--replay flight3.bin` drives JSBSim
   from the logged servo outputs with no SITL in the loop and writes logged
   vs simulated rates, attitude, airspeed and accelerations per segment.
   Use short segments (a few seconds around each step) so drift does not
   dominate.
3. **Correct the model.** Adjust the scale factors (control power, damping,
   inertia) until simulated steps match logged ones; by hand first, a
   least-squares fit later. Fold the corrected values back into the model
   card as new nominal values with narrower ranges (modeling §10).
4. **Closed-loop check.** Fly the logged mission in SITL with the extracted
   parameters and compare with the log again.

## 5. Predicting the tune at higher airspeeds

With a model corrected at the speeds already flown, fly the **same**
parameters in SITL at higher airspeeds before flying them for real:
`sweep.py --params flight3.param --airspeeds 18,22,26,30` runs the §3 test
sequence at each speed and reports where the pass criteria first fail.

Why it matters: control power grows with dynamic pressure (∝ V²) while
ArduPlane scales surface output by about `SCALING_SPEED` / airspeed (∝ 1/V),
so loop gain still rises roughly with airspeed. A model corrected at low speed
predicts this trend well, because it is the physics the model is built from.
It does not predict flex, flutter, servo stall under load, propeller data
beyond what was flown, or aerodynamics outside the flown range. Use the
prediction to choose the next speed step and the gains for it; expand the
envelope in the field in those steps, logging and correcting at each.

## 6. Decision points

| When | Decision | By |
|---|---|---|
| Before the first sweep | Pass-criteria thresholds; variant ranges if the model card's are too wide or narrow | Team |
| Before the first flight | Whether the sweep margins are enough; the first-flight parameter file | Team, with ArduPilot's first-flight guidance |
| After each flight | Whether the model correction is good enough to predict the next envelope step | Team |

## 7. Risks

| Risk | Mitigation |
|---|---|
| Sim-derived gains trusted too far | §1 limits what is taken from the sim; D and filters are set in the field; the sweep covers model uncertainty; first-flight margins are a human decision |
| Model corrected at low speed extrapolated beyond its validity | §5: predictions choose the next envelope step, they do not replace flying it |
| Sweep passes because the variant ranges are too narrow | Ranges come from the model card's uncertainties; widen them for anything not yet measured |
