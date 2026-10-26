# Filling in the template from CAD and XFLR5

How to replace every placeholder in `test-aircraft/template/` with the team
aircraft's data, in the order that works: each step only needs numbers from
the steps before it. Every value in the files has a short label next to it;
this guide says where each one comes from.

Sources:

- **CAD**: geometry, positions, mass properties, surface throws.
- **XFLR5**: aerodynamics (polars, stability and control derivatives).
- **Datasheets and bench tests**: EDF, servos, gear.
- **Hand formulas** for what neither tool gives (spoiler effect, parasite drag,
  downwash lag, gear springs). The formulas are below.

The background, limits and validation plan for XFLR5 models are in the
aircraft modeling plan (`sitl-docker/AIRCRAFT-MODELING-PLAN.md` on the
`aircraft-modeling` branch).

## Order of operations

| Step | What | Source | Files |
|---|---|---|---|
| 0 | Copy the template, choose the reference frame | — | new folder |
| 1 | Reference geometry | CAD | `Metrics.xml` |
| 2 | Positions: IMU, EDF, wheels, airframe contacts | CAD | `Metrics.xml`, `template.xml`, `Gear.xml` |
| 3 | Mass, CG, inertia | CAD | `Mass.xml` |
| 4 | Surface throws | CAD (linkage limits) | `FlightControl.xml` |
| 5 | XFLR5 model: airfoils, plane, inertia | CAD + step 3 | XFLR5 project |
| 6 | Lift, drag, pitch vs angle of attack | XFLR5 + drag build-up | `Aero.xml` tables |
| 7 | Stability and damping derivatives | XFLR5 stability polar | `Aero.xml` |
| 8 | Control derivatives, one surface at a time | XFLR5 control polars | `Aero.xml` |
| 9 | Spoilers, gear drag, downwash lag | Hand formulas | `Aero.xml` |
| 10 | EDF | Datasheet / thrust stand, CAD | `Systems/edf.xml`, `template.xml` |
| 11 | Gear springs, friction, steering | Step 3 loads, CAD | `Gear.xml` |
| 12 | Servo speeds | Servo datasheets | `Controls.xml` |
| 13 | ArduPlane parameters | Steps 3, 6, 10 | `firmwares/*.param` |
| 14 | Check it | Bridge, tests, XFLR5 | — |

---

## Step 0: copy the template and choose the reference frame

**Copy, do not edit in place.** Keep `template` as the reference:

```bash
cp -r test-aircraft/template test-aircraft/<name>
cd test-aircraft/<name>
mv template.xml <name>.xml
mv firmwares/ardupilot_template.param firmwares/ardupilot_<name>.param
```

Then change `name="template"` in `<name>.xml`'s `<fdm_config>` to `<name>`.
The template's tests (`libraries/SITL/examples/JSON/JSBSim/tests/test_template.py`)
check its placeholder mass, CG and thrust, so they would fail on purpose if
the template itself were changed.

**Reference frame.** Every position in the files is in JSBSim's structural
frame: metres from a chosen origin, **x aft, y right, z up**.

- **Origin**: the nose tip is convenient. Any fixed point works.
- **x-axis, the fuselage reference line**: a straight line along the aircraft
  you can find in CAD: the fuselage centreline, the motor thrust axis, or the
  wing root chord. JSBSim's body x-axis is parallel to it, so pitch 0° means
  this line is level and **angle of attack is measured from it**.
- Set CAD's coordinate system to this frame (or note the conversion), and
  build the XFLR5 plane in the **same** frame (XFLR5's geometry axes are
  already x aft, y right, z up). Wing and tail incidence go into the geometry,
  relative to this line.

If CAD uses x forward, flip the sign of every x it gives you. If it uses
z down, flip z. (Flipping both leaves products of inertia unchanged; flipping
one changes their sign; see step 3.)

## Step 1: reference geometry (CAD) → `Metrics.xml`

These normalise every aerodynamic coefficient, so they must be the values
XFLR5 uses in step 5 (XFLR5 reports its reference area, span and MAC in the
plane definition).

| Value | From |
|---|---|
| `wingarea` | Wing planform area projected on the x-y plane (XFLR5's default reference area). |
| `wingspan` | Projected span, tip to tip. |
| `chord` | Mean aerodynamic chord (MAC). |
| `htailarea`, `vtailarea` | V-tail total panel area × cos(dihedral) and × sin(dihedral). Informational: the aerodynamics come from XFLR5. |
| `htailarm`, `vtailarm` | x distance from the CG (step 3) to the tail's quarter-chord MAC. Informational. |
| `AERORP` | The point the aerodynamic **moments** are about. Set it to the CG from step 3, and set XFLR5's moment reference point (step 5) to the same point. |
| `VRP` | Leave at 0 (only used for FlightGear 3D models). |

## Step 2: positions (CAD)

| Value | File | From |
|---|---|---|
| `EYEPOINT` | `Metrics.xml` | The autopilot's IMU position. The bridge sends accelerations measured here. |
| EDF `location` | `<name>.xml` | Fan centre (where the thrust acts). |
| EDF `direction` | `<name>.xml` | Thrust axis in **body axes** (x forward, y right, z down): (1, 0, 0) for a fan on the fuselage reference line; for a fan angled up by θ, (cos θ, 0, −sin θ). |
| Wheel `location`s | `Gear.xml` | The tyre's contact point with the ground, **strut extended (no load)**. Order must stay nose, left main, right main (units 0, 1, 2). |
| Airframe contacts | `Gear.xml` | The lowest points of the nose, belly, tail, wingtips and V-tail tips: what touches first in a wheels-up landing or wing strike. Add or remove contacts as the shape needs. |

## Step 3: mass, CG, inertia (CAD) → `Mass.xml`

Split the model in CAD into **airframe** (everything that does not change
between flights) and **variable items** (battery, payload).

| Value | From |
|---|---|
| `emptywt` | Airframe mass, without battery and payload. |
| `CG` location | Airframe CG, in the step 0 frame. |
| `ixx`, `iyy`, `izz` | Airframe moments of inertia **about the airframe's own CG**, along the frame's axes. |
| `ixz` | Airframe product of inertia, **+∫ x·z dm** about its CG (`negated_crossproduct_inertia="false"`). Check whether your CAD tool reports the plain integral or its negative, and whether its axes match (see step 0). Usually small; aft-and-high mass (a V-tail) and forward-and-low mass (a battery under the nose) make it positive. At run time JSBSim's `inertia/ixz-slugs_ft2` shows the inertia-matrix element, the **negative** of Ixz (enter +0.01, it shows −0.01). |
| Point mass `weight`, `location` | Each battery and payload item: mass and CG. |
| Point mass own inertia | Optional: add `<ixx>`, `<iyy>`, `<izz>` inside a `<pointmass>` for a large battery (JSBSim has no box shape). |

JSBSim combines these every step: airframe inertia moved to the total CG,
plus each point mass's mass × distance². Moving or reweighing the battery
then changes the CG and inertia correctly with no other edits.

Alternative: put **everything** in the airframe numbers and set the point
masses to 0 kg. Keep one zero-mass point mass as ballast for CG sweeps.

Write down the **total mass and CG** JSBSim reports (the bridge prints them;
or `inertia/weight-lbs`, `inertia/cg-x-in`): steps 5, 11 and 13 need them.

## Step 4: surface throws (CAD) → `FlightControl.xml`

For each surface, the deflection at full servo travel, in radians:

| Surface | Value |
|---|---|
| Ailerons, ruddervators | `<range>` min and max of the `aerosurface_scale` (± throw). If up and down throws differ, use the two values. |
| Flaps | `<gain>` and `<clipto> <max>`: full flap angle. |
| Spoilers | Stay 0..1 (fraction deployed); their effect is set in step 9. |

Measure from CAD with the linkage at its limits, then on the built aircraft.
The positive direction for every surface is trailing edge down.

## Step 5: the XFLR5 model

1. **Airfoils**: load each section's airfoil; run batch **Type 1** polars
   over the Reynolds numbers the aircraft sees (slowest speed at the tip
   chord, fastest speed at the root chord) and angles of attack from below
   zero lift to past stall (about −10° to +20°). XFLR5 interpolates in these
   polars; outside them it warns and uses the nearest.
2. **Plane** in the step 0 frame:
   - **Wing** with its incidence, dihedral, twist; ailerons and flaps as flaps
     (XFLR5's recommended way: two airfoils at the same span station, one
     with the flap break, one without).
   - **V-tail** as the elevator surface with its dihedral (35° in the
     template), ruddervators as flaps on it. No separate fin.
   - Fuselage: geometry reference only; XFLR5's guidelines report it does
     not improve the results, and its drag comes from step 6's build-up.
3. **Mass and inertia**: in the plane's inertia dialog, enter the **total**
   mass, CG and inertia from step 3 manually (XFLR5's own estimate is "a rough
   order of magnitude"). The stability analysis (step 7) needs them.
4. **Moment reference point** = `AERORP` (the CG).
5. Note your XFLR5 version: v6.33 changed the derivative calculation slightly.

## Step 6: lift, drag, pitch vs angle of attack → `Aero.xml` tables

**Analysis**: a plane polar at cruise speed (VLM2, viscous), α from about −6°
to just past the linear range. Add a **wing-only LLT** analysis (non-linear)
through stall for CLmax: the VLM is linear and does not stall.

| `Aero.xml` function | Column 2 of its table |
|---|---|
| `CL_alpha` | CL at each α (radians in column 1). From the VLM2 polar in the linear range; up to CLmax from the LLT; beyond, keep the template's blend to a flat plate (CL ≈ 1.05 sin 2α) and treat it as low confidence. |
| `CD_alpha` | CD from the polar **plus ΔCD0** from a drag build-up (below). Past stall keep the template's shape (separation drag, then flat plate, back to CD0 at 180°). |
| `Cm_alpha` | Cm about the CG from the polar; keep the template's shape beyond ±20°. |

**ΔCD0, the drag XFLR5 misses** (fuselage, interference, antennas; its
guidelines say both methods underestimate drag). Per component, standard
build-up (Raymer):

ΔCD0 = Σ (Cf × FF × Q × S_wet) / S_ref

with Cf the skin-friction coefficient at the component's Reynolds number
(≈ 0.455 / (log10 Re)^2.58 turbulent), FF its form factor (fuselage
≈ 1 + 60/f³ + f/400, f = length/diameter), Q the interference factor (1.0
to 1.3), S_wet its wetted area from CAD, S_ref = `wingarea`. Do **not**
include the landing gear here; it has its own terms (step 9).

Recompute the table entries at the template's α points, or change the points
(column 1 in radians, increasing).

## Step 7: stability and damping derivatives → `Aero.xml`

**Analysis**: a **Type 7 stability polar**, steady level flight, no controls,
at the cruise trim point (XFLR5 trims Cm = 0 itself and reports the trim
speed and α). Export the operating point's stability data to a text file.

XFLR5's non-dimensional derivatives are per radian, in **stability axes**
(`Aero.xml`'s moments are in stability axes too), with rates normalised as
p b/2V, q c/2V, r b/2V, the same as JSBSim's `aero/bi2vel`, `aero/ci2vel`.
They go in directly:

| XFLR5 | `Aero.xml` function |
|---|---|
| CLq | `CL_q` |
| Cmq | `Cm_q` |
| CYb | `CY_beta` |
| CYr | `CY_r` (CYp has no template term; add one like `CY_r` if it matters) |
| Clb, Clp, Clr | `Cl_beta`, `Cl_p`, `Cl_r` |
| Cnb, Cnp, Cnr | `Cn_beta`, `Cn_p`, `Cn_r` |

Cma and CLa are already in the step 6 tables (their slopes); check they
agree with the stability output.

**Not from XFLR5**: the downwash-lag terms `CL_alphadot`, `Cm_alphadot`.
Tail-volume estimate (Etkin):

- dε/dα ≈ 2 CLα_wing / (π AR)  (or from XFLR5: tail local α vs wing α)
- V_H = tail area × tail arm / (wing area × MAC), with the tail's
  *projected horizontal* area (`htailarea`, `htailarm`)
- a_t = the tail's lift slope (≈ 3–4 /rad), η ≈ 0.9
- `Cm_alphadot` ≈ −2 a_t η V_H (l_t / c̄) dε/dα
- `CL_alphadot` ≈ 2 a_t η V_H dε/dα

Uncertainty ±50%; it mostly adds pitch damping.

## Step 8: control derivatives, one surface at a time → `Aero.xml`

**Analysis**: a Type 7 stability polar per surface, with **one control
variable deflecting only that surface**, e.g. left aileron flap −10° … +10°.
Run it for: left aileron, left flap, left ruddervator. (Define each control
on one side only; if your XFLR5 version only offers both sides of a surface
together, deflect them antisymmetrically and symmetrically and split the
results into left and right.)

XFLR5 sign conventions (its guidelines): wing and elevator flaps positive
**trailing edge down**, the same as the template. Moments: roll positive right
wing down, pitch positive nose up, yaw positive nose right: the same as
JSBSim.

**Getting the per-radian coefficient** from two control-polar points at
deflections δ1 and δ2 (radians):

Cx_δ = (Cx(δ2) − Cx(δ1)) / (δ2 − δ1)  for Cx = CL, CD, CY, Cl, Cm, Cn

(XFLR5 also prints *dimensional* control derivatives; to convert:
force ÷ (q S), pitch moment ÷ (q S c̄), roll and yaw moments ÷ (q S b).)

| Surface | `Aero.xml` functions (left) | Right side |
|---|---|---|
| Aileron | `Cl_aileron_left`, `Cn_aileron_left`, `CD_aileron_left` | Same magnitudes; **Cl and Cn change sign** |
| Ruddervator | `CL_`, `CY_`, `Cl_`, `Cm_`, `Cn_`, `CD_ruddervator_left` | CL, Cm, CD the same; **CY, Cl, Cn change sign** |
| Flap | `CL_flap_left`, `CD_flap_left`, `Cm_flap_left`, `Cl_flap_left` | CL, CD, Cm the same; **Cl changes sign** |

The `CD_aileron_*` and `CD_ruddervator_*` terms use |δ| (drag either way):
take the average of the drag rise at +δ and −δ, divided by |δ|.

The template's hand-derived V-tail split (0.175/rad × cos and sin of the
dihedral) is replaced entirely by these XFLR5 numbers.

## Step 9: spoilers, gear drag (hand formulas) → `Aero.xml`

XFLR5 cannot model spoilers (separated flow) or wheels.

**Spoilers**, per side, at full deployment (the coefficient is "fully
deployed", the effect scales linearly with the 0..1 command):

- `CD_spoiler_*` ≈ 1.2 × (spoiler area × sin(max angle)) / `wingarea`
- `CL_spoiler_*` ≈ −(fraction of the wing's lift behind the spoiler's span),
  roughly −CL_cruise × (spoiler span / semi-span) × 0.5–0.8
- `Cl_spoiler_*` ≈ `CL_spoiler` × (spanwise centre of the spoiler / `wingspan`),
  sign: the left spoiler rolls left (negative), the right one positive
- `Cn_spoiler_*` ≈ `CD_spoiler` × (spanwise centre / `wingspan`), left
  negative

These are rough (±50%); refine from flight logs.

**Gear legs**, per leg, with the leg down (`CD_gear_nose`, `_left`, `_right`):

CD_leg ≈ (C_D,wheel × wheel frontal area + C_D,strut × strut frontal area) / `wingarea`

with C_D,wheel ≈ 0.25 (faired) to 0.4 (bare), C_D,strut ≈ 1.0 (flat) to
1.2 (round wire). Frontal areas from CAD.

## Step 10: EDF → `Systems/edf.xml`

| Value | From |
|---|---|
| `edf/static-thrust-lbs` | Datasheet static thrust at full throttle and your cell count, in lbf (N ÷ 4.448, kgf × 2.205). Better: a thrust stand with your battery. |
| `edf/exhaust-velocity-fps` | Datasheet "efflux speed", in ft/s (m/s ÷ 0.3048). If not given: Ve ≈ √(T / (ρ A_exit)) with T static thrust (N), ρ ≈ 1.2 kg/m³, A_exit the exhaust area (m²). |
| Thrust table | Thrust stand: static thrust at 0, 25, 50, 75, 100 % throttle, each ÷ full thrust. Without a stand, keep ≈ throttle². |
| `c1` (lag filter) | 1 ÷ spool time constant. Thrust stand: throttle step 0→100 %, time to 63 % of the final thrust. Without one: 0.2–0.4 s for a 70 mm fan. |
| `edf/max-rpm` | Datasheet, for the rpm output only. |
| Position, direction | Step 2, in `<name>.xml`. |

## Step 11: gear (step 3 loads, CAD) → `Gear.xml`

Static load per wheel, from the total mass m (step 3) and the x positions of
the CG (x_cg), nose wheel (x_n) and mains (x_m):

- nose load = m g (x_m − x_cg) / (x_m − x_n)
- each main = (m g − nose load) / 2

| Value | From |
|---|---|
| `spring_coeff` | Load ÷ static compression you want (or measure): e.g. 1 cm under its load. |
| `damping_coeff` | ≈ 2 × 0.5 × √(spring × load / g) (half critical damping). |
| `static_friction`, `dynamic_friction` | Tyre on runway: about 0.8 / 0.5 on tarmac, 0.6 / 0.4 on grass. |
| `rolling_friction` | 0.02 tarmac, 0.05 short grass. |
| `max_steer` | Nose-wheel angle at full steering servo travel (CAD linkage). |
| Airframe contacts | Spring several times the wheels' (5000 N/m in the template) so the airframe stops a wheels-up aircraft quickly. |

## Step 12: servo speeds → `Controls.xml`

Each row's `lag` (seconds) is the servo's first-order time constant
(the bridge's default is 0.14 s for every row without `lag=`).

- From a datasheet "t seconds per 60°" and a surface needing Δ degrees of
  servo travel for full throw: full travel takes t × Δ / 60; use about half
  of that as the time constant.
- Better: command a step and measure the time to 63 % of the way.
- Landing gear retract servos are usually much slower (1–3 s full travel);
  set their rows' `lag` accordingly.

## Step 13: ArduPlane parameters → `firmwares/ardupilot_<name>.param`

The servo map (`SERVOn_FUNCTION`, MIN/MAX/TRIM) stays. Recompute:

| Parameter | From |
|---|---|
| Stall speed V_s | √(2 m g / (ρ S CLmax)) with total mass (step 3), `wingarea`, CLmax clean and with full flaps (steps 6, 8); ρ at the field's altitude (1.157 kg/m³ at CMAC's 584 m). |
| `AIRSPEED_MIN` | ≈ 1.3–1.4 × V_s clean. |
| `AIRSPEED_CRUISE` | Best range or the mission's speed; check the EDF can hold it (next row). |
| `AIRSPEED_MAX` | Structural or controllability limit, and below where EDF thrust runs out. |
| `TRIM_THROTTLE` | Drag at cruise D = ½ρV²S CD(cruise CL) equals EDF thrust T0 × fraction(fan) × (1 − V/Ve); solve for the fan setting; percent. |
| `TKOFF_ROTATE_SPD` | ≈ 1.1–1.2 × V_s with takeoff flaps. |
| `TECS_LAND_ARSPD` | ≈ 1.2–1.3 × V_s with full flaps. |
| `TKOFF_FLAP_PCNT`, `LAND_FLAP_PERCNT` | Takeoff and landing flap settings as a percentage of full flap. |
| `MIXING_GAIN` | 0.5 keeps the V-tail mixer from saturating; raise it if pitch or yaw authority is short (check the V-tail outputs reach their ends in a steep turn). |

## Step 14: check it

In order, each with the copied aircraft's name:

1. **It loads**, all 13 bindings resolve, and it rests level on three wheels:
   start the bridge (`jsbsim_json_bridge.py --aircraft <name>`) and read its
   startup lines (mass, CG, binding table).
2. **Matches XFLR5 at trim**: compare JSBSim's trimmed α and ruddervator
   angle at cruise with XFLR5's Type 7 trim point (the modeling plan's check
   V2).
3. **Matches XFLR5's modes**: linearise JSBSim at the same trim
   (`jsbsim.FGLinearization`) and compare short period, roll, Dutch roll
   with XFLR5's eigenvalues (check V4: frequency and damping within ~15 %).
4. **Signs**: each surface moves the aircraft the right way on its own and
   through ArduPlane's outputs. Copy `tests/test_template.py` for the new
   aircraft and update its expected mass, CG and thrust.
5. **Flies**: `docker compose run --rm --service-ports -e SIM_BACKEND=json -e JSBSIM_MODEL=<name> sitl`,
   AUTO takeoff, circuit, landing; check the gear, flaps, spoilers and brakes
   outputs in a GCS and the run's logs in `sitl-docker/work/runs/`.

After the aircraft is built, replace estimates with measurements (weigh and
balance, inertia swing test, servo bench, thrust stand), then correct the
aerodynamics from flight logs (the tuning plan on the `tuning-workflow`
branch).
