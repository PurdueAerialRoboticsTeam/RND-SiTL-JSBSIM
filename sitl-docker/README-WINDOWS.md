# Build and run on Windows

This guide starts a simulated fixed-wing aircraft on your computer. **Docker Desktop** builds and runs ArduPilot and JSBSim; **QGroundControl** shows the aircraft and its controls; **FlightGear** shows a 3D view. The team's ArduPilot source and aircraft files come from a private GitHub repository that you clone inside WSL (Ubuntu). You do not need to install JSBSim, Python, or a compiler on Windows.

**Keep Docker Desktop running whenever you build or run the simulator.** Open it from the Start menu and wait until its engine says it is running before entering any `docker compose` command. Do not choose **Quit Docker Desktop** while the simulator is running.

Use a Windows 10 or 11 **64-bit PC** with an internet connection. For the resource settings below, a PC with at least **16 GB of RAM** and **4 logical processors** is recommended. The first build downloads source code and can take a while. Leave at least 20 GB of free disk space. FlightGear's Windows download does not support ARM-based PCs.

## 1. Install WSL 2 and create `.wslconfig`

Docker Desktop uses **Windows Subsystem for Linux 2 (WSL 2)** to run this project's Linux container. Install WSL 2 first. The project lives inside Ubuntu and you run its commands in the **Ubuntu** terminal: a folder on the C: drive would get Windows line endings from Git, which break the simulator, and compiles very slowly through Docker.

1. Open the **Start** menu, type `PowerShell`, right-click **Windows PowerShell**, and choose **Run as administrator**. Approve the Windows prompt.
2. In that administrator window, run:

   ```powershell
   wsl --install
   ```

3. Restart Windows when asked. The command also installs Ubuntu and asks you to create an Ubuntu username and password. Complete that prompt; you will use Ubuntu in step 3. If Ubuntu was not installed, run `wsl --install -d Ubuntu`.
4. Open a **normal** PowerShell window and run `wsl --status`. Check that the default version is **2**. If Docker later says WSL is outdated, run `wsl --update` in PowerShell and restart Windows. See [Microsoft's WSL installation guide](https://learn.microsoft.com/windows/wsl/install) if installation fails.

Next, **create a file named `.wslconfig` in your Windows user folder**. It does not exist by default. It tells WSL how much memory and how many processors Docker's build can use. Do this from your normal Windows account, not from an Ubuntu window:

1. Open **Notepad** from the Start menu. Paste these three lines exactly:

   ```ini
   [wsl2]
   memory=8GB
   processors=4
   ```

2. In Notepad, choose **File → Save As**. In the Save As window's **address bar**, type `%USERPROFILE%` and press **Enter**. This opens your Windows user folder, usually `C:\Users\YourName`.
3. Set **Save as type** to **All files (*.*)**. In **File name**, type `".wslconfig"` **including the quotation marks**, then click **Save**. The quotation marks prevent Notepad from adding `.txt`. The finished path should be `C:\Users\YourName\.wslconfig`, not the project folder and not `.wslconfig.txt`.
4. In your **normal PowerShell** window, check the file:

   ```powershell
   Get-Content "$env:USERPROFILE\.wslconfig"
   ```

   It should print the three configuration lines above. If PowerShell says it cannot find the file, check the Save As location and filename.
5. Quit Docker Desktop if it is already open. Then run `wsl --shutdown` in PowerShell to apply the new settings. Start Docker Desktop again after that. Microsoft documents the [file location and restart behavior](https://learn.microsoft.com/windows/wsl/wsl-config).

The `8GB` and `4` settings are for a PC with at least 16 GB of total RAM and 4 logical processors. On an 8 GB PC, use `memory=4GB` and `processors=2` instead; the build will be slower and may run out of memory.

## 2. Install the three applications

1. Download and install [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/). When the installer offers **Use WSL 2 instead of Hyper-V**, choose it. Open Docker Desktop from the Start menu and wait until it says the engine is running. Keep it open.
2. Download the **Windows installer** from [QGroundControl's stable download page](https://docs.qgroundcontrol.com/Stable_V5.0/en/qgc-user-guide/getting_started/download_and_install.html). Double-click the downloaded `.exe` and complete the installer.
3. Download the **Windows installer** from [FlightGear's official download page](https://www.flightgear.org/download/). Double-click the `.exe` and complete the installer. Keep the default installation location so this project's launcher can find it.

Docker downloads everything needed to build the simulator inside its container.

## 3. Get the project folder ready

1. In Docker Desktop, open **Settings → Resources → WSL integration** and check that integration is on for **Ubuntu**. Click **Apply & restart** if you changed it.
2. Open **Ubuntu** from the Start menu. All commands in this guide from here on go in this Ubuntu window unless it says otherwise.
3. Install Git and the GitHub command-line tool, then sign in to GitHub. Choose **GitHub.com**, **HTTPS**, and **Login with a web browser** when asked, and follow the prompts:

   ```bash
   sudo apt update && sudo apt install -y git gh
   gh auth login
   gh auth setup-git
   ```

4. Clone the team repository (replace `OWNER/REPO` with its name on GitHub) and go into its `sitl-docker` folder. The clone also downloads ArduPilot's submodules and takes a few minutes:

   ```bash
   cd ~
   git clone --recursive https://github.com/OWNER/REPO.git
   cd REPO/sitl-docker
   ls Dockerfile
   ```

   `ls Dockerfile` should print `Dockerfile`. If you open a new Ubuntu window later, run `cd ~/REPO/sitl-docker` first.

To browse or edit the files from Windows, type `\\wsl$\Ubuntu\home` in File Explorer's address bar, or run `explorer.exe .` in the Ubuntu window. [VS Code](https://code.visualstudio.com/) with its **WSL** extension also works well: run `code ..` from the `sitl-docker` folder.

## 4. Build the simulator

In the Ubuntu window, run:

```bash
docker compose build
```

Wait for the command to finish and show the prompt again. The first build can take tens of minutes because Docker downloads build tools and compiles JSBSim. Later runs use the built image. ArduPilot itself is compiled from your copy of the repository when the simulator starts: the first start takes several minutes, later starts only recompile what changed. If you see an error about connecting to Docker, open Docker Desktop and wait for its engine to start, then retry.

## 5. Start FlightGear

In the **same Ubuntu window**, run:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w fgview.ps1)"
```

This starts the Windows FlightGear launcher from Ubuntu. FlightGear should open with a Cessna 172 visual model. Keep this window and FlightGear open. The aircraft may sit still until QGroundControl connects in step 7. If Windows Firewall asks, allow FlightGear on **private networks** so it can receive the simulator's view data. This command's execution-policy setting applies only to the PowerShell process used to start this project's script.

## 6. Start the simulator

Open a **second** Ubuntu window and run:

```bash
cd ~/REPO/sitl-docker
docker compose run --rm --service-ports -e FGVIEW_HOST=host.docker.internal sitl
```

Leave this window open. ArduPilot compiles first; then you should see an `ArduPilot SITL + JSBSim` banner. A message such as `Waiting for connection` is expected until QGroundControl connects. The Cessna in FlightGear is only the picture; JSBSim inside Docker calculates how the simulated aircraft moves.

## 7. Connect QGroundControl

1. Open QGroundControl.
2. Open **Application Settings → Comm Links**. Choose **Add New Link** (or **Add**).
3. Name it `Docker SITL`, set **Type** to **TCP**, **Host** to `127.0.0.1`, and **Port** to `5760`.
4. Save the link, then select it and choose **Connect**.

QGroundControl should show an ArduPlane vehicle. Once connected, the simulator window should print `JSBSim backend started` and `JSBSim Execution beginning`. FlightGear should show the aircraft and update when it moves. Port 5760 accepts one TCP connection at a time, so use one QGroundControl connection to this simulator.

## 8. Stop and restart

To stop, disconnect QGroundControl, click the **simulator Ubuntu window**, and press **Ctrl+C**. Close FlightGear or press **Ctrl+C** in its Ubuntu window. Docker keeps the built image, so next time **open Docker Desktop, wait for its engine to start**, then resume at step 5; you do not need to build again. Keep Docker Desktop running until you finish using the simulator. Simulator settings and logs are saved in the project's `work` folder.

## 9. Edit and share aircraft files

The aircraft model is in the repository at `Tools/autotest/aircraft/Rascal`: `Rascal.xml` is the airframe, and `Engines` holds the engine and propeller. Edit the files (see step 3 for opening them from Windows), stop the simulator with **Ctrl+C**, and start it again (step 6) to fly your change.

In an Ubuntu window in the repository, share a change with:

```bash
git add -A
git commit -m "Rascal: describe what you changed"
git pull --rebase
git push
```

Get everyone else's changes before starting the simulator with `git pull` followed by `git submodule update --init --recursive`. Files the simulator regenerates on every run, such as `reset.xml`, are ignored by Git.

## If something does not work

- **`docker` is not found or Docker cannot connect:** Start Docker Desktop, wait for the engine to be running, check **Settings → Resources → WSL integration** is on for Ubuntu, then open a new Ubuntu window.
- **Docker says WSL is missing or outdated:** Revisit step 1, run `wsl --update` in PowerShell, restart Windows, then open Docker Desktop.
- **The build runs out of memory:** Check that `.wslconfig` is in your Windows user folder and does not end in `.txt`. Quit Docker Desktop, run `wsl --shutdown`, restart Docker Desktop, and try again. On a PC with less than 16 GB of RAM, the build may still need more memory than is available.
- **`no configuration file provided` or `Dockerfile` not found:** The Ubuntu window is in the wrong folder. Run `cd ~/REPO/sitl-docker`.
- **`checked out with Windows (CRLF) line endings`:** The repository was cloned with Git for Windows instead of inside Ubuntu. Clone it again in Ubuntu as in step 3.
- **`git submodules are missing`:** Run `git submodule update --init --recursive` in the repository.
- **FlightGear launcher says `fgfs.exe not found`:** Install FlightGear in its default folder, or read the launcher's `-Fgfs` option if you installed it somewhere else.
- **QGroundControl cannot connect:** Keep the simulator window open; confirm the link is **TCP**, host `127.0.0.1`, port `5760`. Close any other QGroundControl connection using that port.
- **FlightGear opens but does not move:** Connect QGroundControl first. If QGroundControl shows the aircraft but FlightGear stays still, allow FlightGear through Windows Firewall on private networks, then restart FlightGear and the simulator.
