# Team ArduPilot SITL + JSBSim

This repository is ArduPilot (`Plane-4.7.2`, plus upstream commit `e5e9709`
fixing JSON rangefinder input) plus a Docker setup
that runs ArduPlane SITL with the JSBSim flight model. Everyone clones the same
repository, so everyone flies the same source and the same aircraft files.

- **Docker image**: build tools and JSBSim only. Build it once per computer.
- **ArduPilot source and aircraft models**: this repository, on your computer.
  The container mounts it and compiles it every time the simulator starts, so
  your edits are always what runs. No image rebuild is needed after an edit.

```
<repo>/
├── ArduPlane/, libraries/ …       ArduPilot source
├── Tools/autotest/aircraft/       JSBSim aircraft models (Rascal is the default)
└── sitl-docker/                   this folder: Docker setup, guides, logs in work/
```

## How it works

```
GitHub repo (RND-SiTL-JSBSIM)
      │  git clone: copies the ArduPilot source and aircraft files to your computer
      ▼
RND-SiTL-JSBSIM/ on your computer       the files you edit
      │  mounted into the container at /opt/ardupilot (live, not a copy)
      ▼
Docker container (image: build tools + JSBSim, no ArduPilot)
      │  on every start: compiles ArduPilot from your local files
      ▼
ArduPlane SITL + JSBSim run the freshly compiled code
```

1. **Cloning puts ArduPilot on your computer.** The full source, including the
   aircraft models in `Tools/autotest/aircraft/`, is ordinary files in your
   clone. That is the only copy of ArduPilot involved.
2. **The container uses those files directly.** `docker-compose.yml` mounts the
   repository folder into the container. Nothing is copied into the image, so
   there is no ArduPilot image to pull or update: the image only holds the
   compilers, Python tools and JSBSim.
3. **Every start compiles from your local files.** The first start compiles
   everything (about 4 minutes); later starts recompile only what changed (a
   few seconds). Edit a file, stop the simulator with Ctrl+C, start it again,
   and your edit is what flies.

When do you need to do what?

| You changed | What to do |
|---|---|
| An aircraft file or ArduPilot source | Restart the simulator. No image rebuild. |
| Pulled teammates' changes with `git pull` | Restart the simulator. Rebuild the image first only if the pull changed `Dockerfile` or `entrypoint.sh`. |
| `Dockerfile` (for example the JSBSim version) | `docker compose build`, then restart. |
| `entrypoint.sh` | `docker compose build`, then restart (it is copied into the image). |

Compiled ArduPilot is not shared through git. Each computer compiles its own
into `build/`, which git ignores. The compiled program differs between Apple
Silicon Macs and Intel/AMD PCs, and would be stale after every edit anyway.

## First-time setup

You need Git, Docker Desktop, QGroundControl, FlightGear and access to this
private GitHub repository.

- **Quick setup** (minimum steps): [SETUP-MACOS.md](SETUP-MACOS.md),
  [SETUP-WINDOWS.md](SETUP-WINDOWS.md)
- **Detailed guides** (explanations, troubleshooting): [README-MACOS.md](README-MACOS.md),
  [README-WINDOWS.md](README-WINDOWS.md)

In short:

```bash
git clone --recursive https://github.com/PurdueAerialRoboticsTeam/RND-SiTL-JSBSIM.git
cd RND-SiTL-JSBSIM/sitl-docker
docker compose build
docker compose run --rm --service-ports sitl
```

`--recursive` matters: ArduPilot needs its git submodules. If you forgot it, run
`git submodule update --init --recursive` in the repository.

**Windows:** clone and run inside WSL (Ubuntu), not on the C: drive. Git for
Windows converts line endings to CRLF, which breaks the scripts the container
runs, and compiling from the Windows drive through Docker is very slow.
[README-WINDOWS.md](README-WINDOWS.md) walks through it.

**Linux:** the container runs as uid 1000. If `id -u` prints something else,
build with `docker compose build --build-arg UID=$(id -u) --build-arg GID=$(id -g)`.

## Everyday workflow

Get everyone else's changes, then start the simulator. It recompiles only what
changed:

```bash
git pull
git submodule update --init --recursive
docker compose run --rm --service-ports sitl
```

Edit aircraft files in `Tools/autotest/aircraft/Rascal/` (the airframe is
`Rascal.xml`, the engine and propeller are in `Engines/`) or any ArduPilot
source. Stop the simulator with Ctrl+C and start it again to pick up the edit.

Share your change:

```bash
git add -A
git commit -m "Rascal: describe what you changed"
git pull --rebase
git push
```

Compile without starting the simulator (useful to check a source edit):

```bash
docker compose run --rm sitl build
```

## JSON backend: all 16 servo channels

The default backend (`SIM_BACKEND=jsbsim`) is ArduPilot's own, which drives
only SERVO1..4 (aileron, elevator, throttle, rudder). `SIM_BACKEND=json` runs
JSBSim in a bridge over SITL's JSON interface instead: every servo output can
drive any JSBSim input, mapped per aircraft by a `Controls.xml` in the
[PteroSimAircrafts](https://github.com/PteroLabsAI/PteroSimAircrafts) format.
The bridge is `libraries/SITL/examples/JSON/JSBSim/`; its readme covers the
details.

Rebuild the image once after pulling this change (it adds JSBSim's Python
module; on Apple Silicon this compiles for a few minutes):

```bash
docker compose build
```

The Rascal, with the same bindings as the default backend:

```bash
docker compose run --rm --service-ports -e SIM_BACKEND=json sitl
```

The bridge's output appears in the log as `[bridge]` lines, including the
binding table and a timing report every 10 seconds.

### Test aircraft with more channels

`test-aircraft/` holds fixed-wing aircraft from
[PteroSimAircrafts](https://github.com/PteroLabsAI/PteroSimAircrafts), each
with its own `Controls.xml` and ArduPlane parameters:

```bash
# Cessna 172: SERVO1-5, including flaps on SERVO5
docker compose run --rm --service-ports -e SIM_BACKEND=json -e JSBSIM_MODEL=c172p sitl
# PX4's small electric test plane
docker compose run --rm --service-ports -e SIM_BACKEND=json -e JSBSIM_MODEL=advanced_plane sitl
```

What each aircraft is, what was tested and its known limits are in
`test-aircraft/README.md`. VTOL aircraft are not supported yet.

| Variable | Default | |
|---|---|---|
| `SIM_BACKEND` | `jsbsim` | `json` for the bridge |
| `JSBSIM_MODEL` | model in `FRAME`, else `Rascal` | aircraft name, looked for in `test-aircraft/` then `Tools/autotest/aircraft/` |
| `JSBSIM_AIRCRAFT_DIR` | those two folders | another folder holding `<model>/<model>.xml` |
| `JSBSIM_CONTROLS` | the model's own `Controls.xml`, else SERVO1..4 | bindings file |
| `JSON_FRAME` | `plane` if the model has `firmwares/ardupilot_<model>.param`, else `jsbsim-json` | base parameters: `jsbsim-json` (`plane-jsbsim.parm`, for the Rascal) or `plane` (`models/plane.parm`) |
| `PARAM_FILES` | the model's `firmwares/ardupilot_<model>.param`, if any | parameter files added on top, comma separated |
| `BRIDGE_ARGS` | none | extra bridge options (`jsbsim_json_bridge.py --help`) |

Relative paths are relative to the repository. Do not mix `plane-jsbsim.parm`
with the test aircraft: it reverses elevator and rudder, and their bindings
already do.

## Files you should not commit

These are regenerated on every run and are ignored by git:

- `Tools/autotest/aircraft/*/reset.xml`
- `Tools/autotest/jsbsim_start_*.xml`, `Tools/autotest/jsbsim_fgout_*.xml`
- `build/` (compiled output)
- `sitl-docker/work/` (parameters in `eeprom.bin`, dataflash logs, terrain)

## Adding another aircraft

Copy `Tools/autotest/aircraft/Rascal` to `Tools/autotest/aircraft/<Model>`,
rename `Rascal.xml` to `<Model>.xml`, and set `FRAME: jsbsim:<Model>` in
`docker-compose.yml` (or pass `-e FRAME=jsbsim:<Model>` to `docker compose run`).

## Updating to a newer ArduPilot release

The repository does not carry ArduPilot's history. To move to a newer release,
apply the upstream changes between the two tags as one commit:

```bash
git fetch --depth 1 https://github.com/ArduPilot/ardupilot.git tag Plane-4.7.2 tag Plane-4.7.3
git diff --binary Plane-4.7.2 Plane-4.7.3 -- . ':(exclude).github/workflows' ':(exclude)modules' \
  | git apply --3way --index
git diff Plane-4.7.2 Plane-4.7.3 -- modules   # submodule pins that moved
```

The upstream CI workflows are excluded because this repository removed them.
For each submodule the last command lists, set the new pin with
`git update-index --cacheinfo 160000,<new commit>,modules/<name>`. Resolve any
conflicts with the team's edits, then commit.
