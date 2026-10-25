# Plan: modeling the team aircraft for JSBSim from XFLR5

Status: plan only, nothing implemented yet. Branch: `aircraft-modeling`.

Related: `sitl-docker/JSBSIM-JSON-PLAN.md` on the `jsbsim-json-backend`
branch. That plan runs a model in SITL over the JSON interface and uses it for
tuning (its §11). This plan produces the model: a JSBSim aircraft folder for
the team aircraft, built from XFLR5 and the other design data, with every
number traceable to a source and an uncertainty range for the tuning sweeps.

## 1. Goal

- A JSBSim model of the team aircraft **before it is built**, good enough
  for a safe first-flight tune (tuning plan §11.1, §11.3).
- Every number in the model has a **source** and an **uncertainty**, so the
  robustness sweep knows how far to vary it.
- A repeatable pipeline: change the design in XFLR5 or the mass budget,
  re-export, re-generate, re-validate. No hand-edited XML that drifts from
  the design.
- A path to correct the model after the aircraft is built and flown
  (measurements, then flight logs).

The model is for simulation of an unmanned R&D aircraft; it does not replace
ground tests or the field process for a first flight.

## 2. Pipeline

```
XFLR5 project (.xfl)                 CAD / mass budget        Prop + motor data      Drag buildup
  airfoil polars (Type 1 batch)        masses, CG, inertia      APC / UIUC tables      fuselage, gear,
  plane polar (α sweep)                servo, battery, payload  motor datasheet        interference
  stability polars (Type 7)                                     thrust stand (later)
  control polars (Type 7 + controls)
        │ text / CSV exports               │                       │                    │
        └───────────────┬──────────────────┴───────────────────────┴────────────────────┘
                        ▼
            model/model-card.yaml       single source of truth: value, unit, source, uncertainty
                        │
                        ▼  Tools/aircraft_model/generate.py
            JSBSim aircraft folder      Metrics, Mass (+ variants), Aero, FlightControl,
                        │               Propulsion, Gear, Controls.xml, ArduPilot params
                        ▼  Tools/aircraft_model/validate.py
            checks V1..V6 (§9)          against XFLR5 trim, static margin, eigenmodes, envelope
                        ▼
            SITL over JSON (backend plan) → preliminary tune → field → logs → correct model card
```

## 3. Aircraft folder

Same split-file layout as PteroSimAircrafts (JSBSim loads each section with
`file=`):

```
Tools/autotest/aircraft/<Team>/
├── <Team>.xml                 top level: <metrics file=…/> <mass_balance file=…/> …
├── <Team>-<variant>.xml       generated: same, pointing at a Mass variant (§8)
├── Metrics.xml  Mass.xml  Mass-<variant>.xml
├── Aero.xml  FlightControl.xml  Gear.xml  Propulsion.xml
├── Engines/                   electric engine + propeller tables
├── Controls.xml               servo channel → JSBSim property (backend plan §5)
├── firmwares/ardupilot_<team>.param
└── model/
    ├── model-card.yaml        every input number, with source and uncertainty
    ├── xflr5/                 the .xfl project and its exports, XFLR5 version noted
    ├── mass-budget.csv        component masses and positions
    ├── prop/                  propeller data files
    └── validation/            output of validate.py (plots, eigenvalue tables)
```

Generated XML is committed (SITL needs it), but only `model/` is edited by
hand. Each generated file starts with a header saying so and naming the model
card commit.

## 4. XFLR5: setup

Reference: *XFLR5 v6.02 Guidelines* (A. Deperrois). The team should note its
own XFLR5 version in `model/xflr5/VERSION`; v6.33 changed the stability
derivative scheme to centred differences, so derivatives from older versions
differ slightly (mostly `Xw`).

1. **Units: SI.** JSBSim XML accepts unit attributes (`unit="M2"`,
   `unit="KG*M2"`), so there is no need to work in feet in XFLR5. The
   generator converts where JSBSim needs it.
2. **Axes.** XFLR5's geometric axes (x aft, y starboard, z up) are the same
   as JSBSim's structural frame (x aft, y right, z up), so geometry positions
   carry over directly (metres → JSBSim with `unit="M"`).
3. **Airfoil polars (Type 1, batch).** One set per airfoil, covering:
   - Reynolds numbers from the slowest speed at the smallest chord (tip,
     tail) to the fastest speed at the largest chord (root). XFLR5 interpolates
     in this mesh and only warns, then clamps, outside it.
   - α from below zero lift to well past stall (e.g. −10° to +20°), so
     the plane polars reach CLmax.
   - For each surface with a control, the flapped airfoil at the deflections
     of interest (e.g. ±5°, ±10°, ±20°) so viscous drag with deflection is
     available. Define each flap as XFLR5 recommends: two foils at the same
     span station, one with the flap break and one without.
4. **Plane.** Wing, elevator (horizontal tail) and fin with their control
   surfaces as flaps. Model the fuselage only for geometry reference: the
   guide reports that body modeling does not improve precision, and its drag
   comes from the buildup (§6) anyway. Use VLM2 (ring vortex) as the main
   method, viscous on.
5. **Mass and inertia in XFLR5.** Enter structure masses for each wing and
   body and **point masses** for motor, battery, servos, receiver, autopilot,
   payload, ballast. XFLR5's inertia is "a rough order of magnitude"; use it
   only until CAD mass properties exist, and use the CAD/mass budget numbers
   in the model card when they do. Set point masses so the CG lands where the
   design says (the guide warns a literal placement can miss it).

## 5. XFLR5: analyses to run and export

| # | Analysis | Settings | What the model takes from it |
|---|---|---|---|
| A1 | Plane polar, α sweep | Fixed speed (cruise), VLM2 viscous, α −6° … beyond the linear range, moments about the CG | CL(α), CD(α), Cm(α) tables; CL0, CLα, Cm0, Cmα; zero-lift α |
| A2 | Same at slow and fast speeds | Speeds at ~1.3 Vstall and ~Vmax | Reynolds effect on CD; whether tables need a speed dimension |
| A3 | Wing-only LLT | α through stall | CLmax and the shape near stall (LLT is the non-linear method; VLM is linear and does not stall) |
| A4 | Stability polar (Type 7), no controls | Steady level flight at slow, cruise, fast trim points | Trimmed α and speed; CLq, Cmq, CYβ, CYp, CYr, Clβ, Clp, Clr, Cnβ, Cnp, Cnr; the 8 eigenmodes for validation (§9 V4) |
| A5 | Stability polars with **one control at a time** | Control variable = elevator flap; then aileron flaps (left and right min/max opposite, as the guide says); then rudder flap; then wing flaps. Range e.g. −10° … +10° | Control derivatives: CLδe, Cmδe, CDδe; Clδa, Cnδa, CYδa; Clδr, Cnδr, CYδr; CLδf, Cmδf, CDδf |
| A6 | Sideslip sweep, if the team's XFLR5 version has one | Fixed α, β −15° … +15° | CY(β), Cl(β), Cn(β) beyond the linear derivative; otherwise use A4's linear terms |

**Control derivatives.** XFLR5's stability output gives the *dimensional*
control derivatives. The generator converts them to coefficients with the
same normalisation the guide uses for stability derivatives
(force ÷ (q·S), moment ÷ (q·S·c̄) for pitch, ÷ (q·S·b) for roll and yaw,
per radian). As a cross-check, and as the fallback if a version does not
report them, take finite differences of CL, Cm, Cl, Cn between control
polar points at two deflections.

**Sign conventions** (XFLR5, from the guide): wing/elevator tilt positive
leading edge up; any wing or elevator flap positive **trailing edge down**;
rudder positive **trailing edge to starboard**. Moments: roll positive
starboard wing down, pitch positive nose up, yaw positive nose to starboard.
The generator converts to JSBSim's conventions (§7).

**Exports**, all into `model/xflr5/`:
- the `.xfl` project, and the XFLR5 version;
- A1–A3, A6 polars as CSV (Polars → export, "comma separated" option);
- A4, A5 operating points' stability data as text (the guide: derivative
  values "can be exported to a text file for use in other flight simulation
  codes"), one file per trim point and control;
- the eigenvalue table for each A4 trim point.

If the team's XFLR5 can export the plane to AVL format, also keep that file:
AVL gives non-dimensional control derivatives directly and is a useful
independent check of A5.

## 6. What XFLR5 does not provide, and where it comes from

| Missing | Why it matters | Source | Default uncertainty |
|---|---|---|---|
| Parasite drag of fuselage, gear, antennas, interference | XFLR5 drag comes from 2D polars; the guide says both methods "tend to underestimate the drag". Too little drag = optimistic speed, glide, TECS | Component drag buildup (Raymer or Hoerner form factors and wetted areas), added as ΔCD0 | ±30% |
| Post-stall CL, CD, Cm | VLM is linear: no stall. Stall matters for `AIRSPEED_MIN`, takeoff, and failsafe tests | CLmax from A3 (or 2D Clmax × ~0.9); beyond it blend to flat-plate values (CN ≈ 2 sin α) over a few degrees | CLmax ±10%, post-stall ±50% (mark low confidence) |
| CLα̇, Cmα̇ (downwash lag) | Adds short-period damping, often comparable to the tail's Cmq share | Tail-volume estimate (Etkin): Cmα̇ ≈ −2·a_t·η·V_H·(l_t/c̄)·dε/dα, CLα̇ ≈ 2·a_t·η·V_H·dε/dα; dε/dα from A1 (tail local α vs wing α) or ≈ 2·CLα_w/(π·AR) | ±50% |
| Propeller thrust and power | Thrust, climb, speed, TECS | APC performance files or UIUC propeller database → CT(J), CP(J) tables; later a thrust stand | ±10%, ±5% after thrust stand |
| Motor and ESC | Power limit and throttle response time (tuning plan §11.2) | Motor datasheet (max power); first-order throttle lag, time constant from a thrust-stand step (until then ~0.1 s, an assumption) | lag ×0.5 … ×2 |
| Propeller slipstream over the tail | Elevator and rudder power at low speed and high throttle | Not modelled initially; flag if the tail sits in the prop wash | — |
| Servo speed, throw, backlash | Actuator lag in the loop | Servo datasheet speed; throws from the design, measured after build | lag ×1 … ×2 |
| Ground contact | Takeoff and landing behaviour, ground trim | Gear or skid positions from CAD; spring from allowed static deflection, damping a fraction of critical; friction coefficients for the surface | ±50% (ground only) |
| Ground effect | Landing flare | Optional standard factor on CL and CDi vs h/b | — |

## 7. Generating the JSBSim files

`Tools/aircraft_model/generate.py` (Python, `AP_FLAKE8_CLEAN`) reads the
model card and writes the aircraft folder. A separate
`Tools/aircraft_model/import_xflr5.py` parses the XFLR5 exports into the
model card's `aero` section, recording which export each value came from.

### Metrics.xml

`wingarea`, `wingspan`, `chord` (mean aerodynamic chord), `htailarea`,
`htailarm`, `vtailarea`, `vtailarm` from XFLR5's plane definition (use the
same reference area and span XFLR5 used: the projected planform by default).
`AERORP` = the point XFLR5's moments are taken about (the CG for stability
polars; set A1's moment reference to the same point). `EYEPOINT` = the
autopilot's IMU position (the bridge reads accelerations there). `VRP`.

### Mass.xml

`emptywt`, `ixx`, `iyy`, `izz`, `ixz` in `KG*M2`, CG `location` in `M`, and
`<pointmass>` entries for battery, payload and a zero-mass **ballast** point
used for CG variants. Set `negated_crossproduct_inertia` explicitly (JSBSim
v1.3.3 reads it in `FGMassBalance`) and write in the header which sign
convention `ixz` follows, so the CAD value goes in with the right sign.

### Aero.xml

Forces in wind axes (`LIFT`, `DRAG`, `SIDE`), moments in **stability axes**
(`<axis name="ROLL" frame="STABILITY">`, supported by JSBSim v1.3.3), which
is the frame XFLR5 computes its derivatives in. Every term is
`coefficient × aero/qbar-psf × metrics/Sw-sqft` (× `metrics/bw-ft` for roll
and yaw, × `metrics/cbarw-ft` for pitch), times a scale property where the
tuning sweep needs one:

| Axis | Terms | Scale property (default 1.0) |
|---|---|---|
| LIFT | CL(α) table incl. post-stall; CLq · q̂; CLα̇ · α̇̂; CLδe · δe; CLδf · δf | `scale/lift` on CL(α) |
| DRAG | CD(α) table + ΔCD0 buildup; CDβ; CDδe; CDδf | `scale/drag` |
| SIDE | CYβ · β; CYp · p̂; CYr · r̂; CYδr · δr | |
| ROLL | Clβ · β; Clp · p̂; Clr · r̂; Clδa · δa; Clδr · δr | `scale/roll-power` on Clδa, `scale/roll-damping` on Clp |
| PITCH | Cm(α) table; Cmq · q̂; Cmα̇ · α̇̂; Cmδe · δe; Cmδf · δf | `scale/pitch-power` on Cmδe, `scale/pitch-damping` on Cmq and Cmα̇ |
| YAW | Cnβ · β; Cnp · p̂; Cnr · r̂; Cnδa · δa; Cnδr · δr | `scale/yaw-power` on Cnδr, `scale/yaw-damping` on Cnr |

Normalised rates use JSBSim's existing properties, as the Rascal model does:
p̂ = `aero/bi2vel` × `velocities/p-aero-rad_sec` (r̂ likewise),
q̂ = `aero/ci2vel` × `velocities/q-aero-rad_sec`,
α̇̂ = `aero/ci2vel` × `aero/alphadot-rad_sec`.
`aero/alpha-rad`, `aero/beta-rad` for angles; surface positions from
`fcs/*-pos-rad`.

The `scale/*` names are the interface to the tuning plan's `--scale`
option; they are declared with `<property value="1">` so they exist before
the bridge sets them.

### Control sign conventions in the generated model

| Surface | XFLR5 positive | JSBSim property, positive | Conversion |
|---|---|---|---|
| Elevator | trailing edge down | `fcs/elevator-pos-rad`: trailing edge down (nose down) | none |
| Flaps | trailing edge down | `fcs/flap-pos-rad`: down | none |
| Rudder | trailing edge to starboard (nose right) | `fcs/rudder-pos-rad`: trailing edge left (nose left), the convention the PteroSim c172p notes | negate δr derivatives |
| Ailerons | per-side flaps, trailing edge down | `fcs/aileron-pos-rad`: positive rolls right (left aileron down, right up) | δa derivative from the A5 aileron polar, sign set so +δa gives +Cl |

The table is checked by V3 (§9), not assumed. The ArduPilot side
(`SERVOn_REVERSED`) and `Controls.xml` are then set per the backend plan §5
so that each is reversed in exactly one place.

### FlightControl.xml

One channel per surface: `fcs/<surface>-cmd-norm` → `<actuator>` (`<lag>`
from servo speed; `<rate_limit>`; `<deadband_width>`/`<hysteresis_width>`
left at 0 until measured) → `<aerosurface_scale>` to ±max throw in radians →
`fcs/<surface>-pos-rad`. Mixing for elevons or V-tails, if the design has
them, is done by ArduPilot, not here: per-surface `fcs/servo-N-cmd-norm`
inputs, as PteroSim's `advanced_plane` does. Throttle: `fcs/throttle-cmd-norm`
→ first-order lag (motor/ESC time constant) → `fcs/throttle-pos-norm`.

### Propulsion.xml, Engines/

Electric engine (`<power unit="WATTS">` = motor max power) and propeller
(diameter, blades, `ixx`, CT(J) and CP(J) tables from the prop data, thrust
line location and angle from CAD).

### Gear.xml

Contact points (wheels or belly skid, wingtips and tail as `STRUCTURE`
contacts so a wingtip strike behaves), `spring_coeff` from weight ÷ allowed
static deflection, `damping_coeff` as a fraction of critical, friction
coefficients for grass or tarmac.

### Controls.xml and parameters

`Controls.xml` binds the team aircraft's servo outputs (backend plan §5);
`firmwares/ardupilot_<team>.param` holds `SERVOn_FUNCTION`, throws, the
reversals, and the airspeeds and limits taken from validation V5. The
backend's parameter-file cross-check reads this file.

## 8. Uncertainty and variants

The model card holds a nominal value and a range for every item that drives
handling. The generator turns them into two things the tuning sweep (backend
plan §11.3) uses:

- **Aero factors**: the `scale/*` properties above, set at runtime by the
  bridge's `--scale`. Ranges come from the model card (defaults: control
  power ±30%, damping ±30%, drag ±30%).
- **Mass variants**: JSBSim's inertia properties are read-only at runtime,
  so `generate.py --variants` writes `Mass-<variant>.xml` and
  `<Team>-<variant>.xml` for inertia ×0.8 and ×1.2 and for CG at the forward
  and aft limits. The bridge selects one with `--variant`. Small CG shifts
  can also move the ballast point at runtime
  (`inertia/pointmass-location-X-inches[n]`).

## 9. Validation (before the aircraft exists)

`Tools/aircraft_model/validate.py` loads the generated model with the JSBSim
Python module (same pinned version as the backend) and writes a report to
`model/validation/`. Each check compares against XFLR5 or hand calculation;
tolerances are starting points for the team to adjust.

| # | Check | Pass |
|---|---|---|
| V1 | Geometry and mass: wing area, span, MAC, mass, CG, inertia read back from JSBSim (`inertia/*`, `metrics/*`) equal the model card | exact (unit conversion only) |
| V2 | Trim: JSBSim full trim (`simulation/do_simple_trim` = 1) at the A4 trim speeds; compare α, elevator, CL with XFLR5's trimmed points | α within 0.5°, elevator within 1° |
| V3 | Control signs: from trim, a small step on each `*-cmd-norm`; check the sign of the body rate response (+aileron → +p, +elevator → nose down, +rudder → nose left) and the moment it produces against the derivative | every sign right |
| V4 | Eigenmodes: linearise at each trim point (`jsbsim.FGLinearization`, `system_matrix()`) and compare eigenvalues with XFLR5's: short period, roll, Dutch roll, phugoid, spiral | short period, roll, Dutch roll frequency and damping within ~15%; phugoid and spiral (drag-sensitive) report only |
| V5 | Envelope: stall speed, best glide, max level speed, climb rate at full throttle; compared with hand calculation or a motor/prop calculator | sanity; values feed `AIRSPEED_MIN`, `AIRSPEED_CRUISE`, `AIRSPEED_MAX`, `TRIM_THROTTLE` with margin |
| V6 | SITL: ArduPlane with the team param file flies a FBWA and AUTO circuit over JSON (backend plan Phase 1–2) | completes; servo directions confirmed |

A student study of XFLR5 found the short-period and roll-subsidence modes
well predicted and drag- and fuselage-dependent derivatives poorly predicted
([Politecnico di Torino thesis](https://webthesis.biblio.polito.it/15521/1/tesi.pdf)),
which is why V4's tolerances differ by mode and why drag carries the widest
uncertainty.

## 10. After the build, then after flight

Each step replaces a design estimate in the model card with a measurement and
narrows its uncertainty; regenerate and re-run validation after each.

1. **Weigh and balance**: mass and CG of the built aircraft, per
   configuration (battery, payload).
2. **Inertia swing test**: bifilar pendulum (yaw) and compound/trifilar
   pendulum (roll, pitch). The most valuable single measurement: CAD inertia
   is often 20–30% off.
3. **Servo bench**: throws at full PWM, speed, slop.
4. **Thrust stand**: static thrust and power vs throttle, and a throttle step
   for the motor/ESC time constant.
5. **Flight logs**: steps and AUTOTUNE flights → the backend plan's
   `--replay` (§11.4) compares logged and simulated responses; correct the
   aero scale factors and fold them back into the model card as the new
   nominal values with narrower ranges.

## 11. Phases

1. **Model card schema and importer.** `model-card.yaml` schema (value,
   unit, source, uncertainty, notes), `import_xflr5.py` for A1–A6 exports,
   tested on a small example XFLR5 project committed for the purpose.
2. **Generator.** All files in §7, variants in §8, generated-file headers.
   First target: a known model, e.g. regenerate a Rascal-like aircraft from a
   hand-written card and compare behaviour with the existing Rascal.
3. **Validation.** `validate.py` V1–V5 with report output.
4. **Team aircraft, design data.** Run the XFLR5 analyses in §5, the drag
   buildup, prop and motor data; generate; validate; fly V6 in SITL.
5. **Post-build updates.** §10 steps 1–4 as the aircraft is built.
6. **Post-flight correction.** §10 step 5, with the backend plan's replay.

## 12. Risks

| Risk | Mitigation |
|---|---|
| XFLR5 underestimates drag | Drag buildup ΔCD0 and a ±30% drag factor in the sweep; correct from the first flights' glide and cruise throttle |
| No stall in VLM | LLT/2D CLmax plus a blended post-stall table marked low confidence; take `AIRSPEED_MIN` with margin above the modeled stall |
| Sign errors between XFLR5, JSBSim and ArduPilot | One conversion table (§7), checked by V3, then the backend's parameter cross-check |
| XFLR5 inertia taken as truth | Used only until CAD mass properties exist; swing test after build |
| Model looks validated because it matches XFLR5 | V2 and V4 only prove the conversion is faithful to XFLR5, not that XFLR5 is right. The uncertainty ranges and the field process cover the rest |
| XFLR5's own scope | The guide states the code was written "for the design of model sailplanes"; that matches a small UAV, but it is a reason to keep the uncertainty ranges wide until flight data exists |

## 13. Out of scope

- CFD or wind-tunnel testing.
- Aeroelastic effects, flutter.
- VTOL / QuadPlane lift systems (to be added if the design has them).
- Changes to the JSBSim backend or bridge; those are in the backend plan.
