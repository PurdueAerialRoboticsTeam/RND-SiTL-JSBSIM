# Team ArduPilot SITL + JSBSim

This repository is ArduPilot (imported from `Plane-4.7.0`) plus a Docker setup
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

## First-time setup

You need Git, Docker Desktop and access to this private GitHub repository.
For the applications and step-by-step instructions, follow
[README-MACOS.md](README-MACOS.md) or [README-WINDOWS.md](README-WINDOWS.md).
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
git fetch --depth 1 https://github.com/ArduPilot/ardupilot.git tag Plane-4.7.0 tag Plane-4.7.1
git diff Plane-4.7.0 Plane-4.7.1 | git apply --3way
```

Resolve any conflicts with the team's edits, update submodules to the new
release's commits, then commit.
