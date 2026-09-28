# Quick setup: Windows

The minimum steps to fly the team's SITL aircraft on Windows. For explanations and
troubleshooting, see [README-WINDOWS.md](README-WINDOWS.md).

## Requirements

- Windows 10 or 11, 64-bit Intel or AMD (FlightGear does not support ARM PCs)
- 16 GB RAM recommended (8 GB minimum), 20 GB free disk space
- Virtualization enabled in the BIOS (Docker Desktop tells you if it is not)
- A GitHub account with access to `PurdueAerialRoboticsTeam/RND-SiTL-JSBSIM`

## 1. Install

First WSL 2: open **PowerShell as administrator**, run the command below, restart
Windows, then create the Ubuntu username and password it asks for.

```powershell
wsl --install
```

Then:

| Application | Download | Notes |
|---|---|---|
| Docker Desktop | [docker.com](https://docs.docker.com/desktop/setup/install/windows-install/) | Choose **WSL 2**. Open it and leave it running. In **Settings → Resources → WSL integration**, turn on **Ubuntu**. |
| QGroundControl | [qgroundcontrol.com](https://docs.qgroundcontrol.com/Stable_V5.0/en/qgc-user-guide/getting_started/download_and_install.html) | Windows installer. |
| FlightGear | [flightgear.org](https://www.flightgear.org/download/) | Windows installer. Keep the default install folder. |

## 2. Get the code (once)

Open **Ubuntu** from the Start menu. Run every command from here on in Ubuntu,
not PowerShell. Do not clone with Git for Windows: its line endings break the
simulator.

```bash
sudo apt update && sudo apt install -y git gh
gh auth login          # GitHub.com, HTTPS, log in with a web browser
gh auth setup-git
cd ~
git clone --recursive https://github.com/PurdueAerialRoboticsTeam/RND-SiTL-JSBSIM.git
```

## 3. Build the image (once)

```bash
cd ~/RND-SiTL-JSBSIM/sitl-docker
docker compose build
```

This takes 10 to 30 minutes the first time.

## 4. Fly

**Ubuntu window 1**, start FlightGear (the 3D view). Allow it through Windows
Firewall on private networks if asked:

```bash
cd ~/RND-SiTL-JSBSIM/sitl-docker
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w fgview.ps1)"
```

**Ubuntu window 2**, start the simulator. The first start compiles ArduPilot for
a few minutes; later starts take seconds:

```bash
cd ~/RND-SiTL-JSBSIM/sitl-docker
docker compose run --rm --service-ports -e FGVIEW_HOST=host.docker.internal sitl
```

**QGroundControl**: **Application Settings → Comm Links → Add**. Type **TCP**,
host `127.0.0.1`, port `5760`. Save, select it, **Connect**.

Stop with **Ctrl+C** in both Ubuntu windows.

## Every day

```bash
cd ~/RND-SiTL-JSBSIM
git pull
git submodule update --init --recursive
```

Then repeat step 4. The files are in File Explorer at
`\\wsl$\Ubuntu\home\<your Ubuntu username>\RND-SiTL-JSBSIM`. To share an aircraft
edit:

```bash
git add -A
git commit -m "Rascal: describe what you changed"
git pull --rebase
git push
```
