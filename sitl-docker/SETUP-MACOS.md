# Quick setup: macOS

The minimum steps to fly the team's SITL aircraft on a Mac. For explanations and
troubleshooting, see [README-MACOS.md](README-MACOS.md).

## Requirements

- Mac with Apple Silicon or Intel, 8 GB RAM or more, 20 GB free disk space
- A GitHub account with access to `PurdueAerialRoboticsTeam/RND-SiTL-JSBSIM`

## 1. Install

| Application | Download | Notes |
|---|---|---|
| Docker Desktop | [docker.com](https://docs.docker.com/desktop/setup/install/mac-install/) | Pick Apple silicon or Intel. Open it and leave it running. |
| GitHub Desktop | [desktop.github.com](https://desktop.github.com/) | Sign in with your GitHub account. |
| QGroundControl | [qgroundcontrol.com](https://docs.qgroundcontrol.com/Stable_V5.0/en/qgc-user-guide/getting_started/download_and_install.html) | Mac disk image. Drag to Applications. |
| FlightGear | [flightgear.org](https://www.flightgear.org/download/) | macOS disk image. Must end up at `/Applications/FlightGear.app`. |

## 2. Get the code (once)

In GitHub Desktop: **File → Clone Repository**, pick
`PurdueAerialRoboticsTeam/RND-SiTL-JSBSIM`, click **Clone**. By default it lands in
`~/Documents/GitHub/RND-SiTL-JSBSIM`.

## 3. Build the image (once)

In Terminal:

```bash
cd ~/Documents/GitHub/RND-SiTL-JSBSIM/sitl-docker
docker compose build
```

This takes 10 to 30 minutes the first time.

## 4. Fly

**Terminal window 1**, start FlightGear (the 3D view):

```bash
cd ~/Documents/GitHub/RND-SiTL-JSBSIM/sitl-docker
bash ./fgview.sh
```

**Terminal window 2**, start the simulator. The first start compiles ArduPilot
for a few minutes; later starts take seconds:

```bash
cd ~/Documents/GitHub/RND-SiTL-JSBSIM/sitl-docker
docker compose run --rm --service-ports -e FGVIEW_HOST=host.docker.internal sitl
```

**QGroundControl**: **Application Settings → Comm Links → Add**. Type **TCP**,
host `127.0.0.1`, port `5760`. Save, select it, **Connect**.

Stop with **Control+C** in both Terminal windows.

## Every day

In GitHub Desktop, **Fetch origin** then **Pull origin**, then repeat step 4.
To share an aircraft edit, commit it in GitHub Desktop and click **Push origin**.
