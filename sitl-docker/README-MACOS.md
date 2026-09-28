# Build and run on macOS

This guide starts a simulated fixed-wing aircraft on your Mac. **Docker Desktop** builds and runs ArduPilot and JSBSim; **QGroundControl** shows the aircraft and its controls; **FlightGear** shows a 3D view; **GitHub Desktop** keeps your copy of the team's ArduPilot source and aircraft files in sync. You do not need to install JSBSim, Python, Homebrew, or a compiler on your Mac.

Use an Apple Silicon or Intel Mac with an internet connection and a macOS version supported by all three applications. The first build downloads source code and can take a while. Leave at least 20 GB of free disk space.

## 1. Install the four applications

1. Download [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/). Choose the download for **Apple silicon** (M-series Mac) or **Intel chip** as shown in **Apple menu → About This Mac**. Open the downloaded `.dmg`, drag Docker to **Applications**, then open Docker from Applications. Accept the setup prompts and wait until its engine is running. Keep Docker open.
2. Download the **Mac disk image** from [QGroundControl's stable download page](https://docs.qgroundcontrol.com/Stable_V5.0/en/qgc-user-guide/getting_started/download_and_install.html). Open the `.dmg` and drag QGroundControl to **Applications**. If macOS blocks QGroundControl when you first open it, use **System Settings → Privacy & Security → Open Anyway** after confirming you downloaded it from that official page; [Apple explains this first-launch step](https://support.apple.com/en-us/102445).
3. Download the **macOS disk image** from [FlightGear's official download page](https://www.flightgear.org/download/). Open the `.dmg` and place `FlightGear.app` in **Applications**. The included launcher expects `/Applications/FlightGear.app`.
4. Download [GitHub Desktop](https://desktop.github.com/), move it to **Applications**, open it, and sign in with the GitHub account that has access to the team repository.

These are the only applications you need to install. Docker downloads everything needed to build the simulator inside its container.

## 2. Get the project folder ready

The project is a private GitHub repository containing the ArduPilot source, the aircraft models, and this Docker setup in its `sitl-docker` folder.

1. In GitHub Desktop, choose **File → Clone Repository**, pick the team repository, choose where to put it, and click **Clone**. This takes a few minutes: it also downloads ArduPilot's submodules, which the build needs.
2. Open **Terminal** (press **Command+Space**, type `Terminal`, press **Return**). Type `cd` followed by a space, drag the repository's **`sitl-docker`** folder from Finder into the Terminal window, then press **Return**. This tells Terminal to work in that folder. Check that you are in the right place:

```bash
ls Dockerfile
```

If it says the file cannot be found, drag the `sitl-docker` folder (the one that directly contains `Dockerfile`) into Terminal after `cd ` and try again.

## 3. Build the simulator

In Terminal, run:

```bash
docker compose build
```

Wait for the command to finish and show the prompt again. The first build can take tens of minutes because Docker downloads build tools and compiles JSBSim. Later runs use the built image. ArduPilot itself is compiled from your copy of the repository when the simulator starts: the first start takes several minutes, later starts only recompile what changed. If you see an error about connecting to Docker, open Docker Desktop and wait for its engine to start, then retry.

## 4. Start FlightGear

In the **same Terminal window**, run:

```bash
bash ./fgview.sh
```

FlightGear should open with a Cessna 172 visual model. Keep this window and FlightGear open. The aircraft may sit still until QGroundControl connects in step 6. If macOS asks whether FlightGear may accept incoming network connections, allow it so it can receive the simulator's view data.

## 5. Start the simulator

Open a **second Terminal window** with **Command+N**. Type `cd` followed by a space, drag the same project folder into the new window, and press **Return**. Run:

```bash
docker compose run --rm --service-ports -e FGVIEW_HOST=host.docker.internal sitl
```

Leave this window open. ArduPilot compiles first; then you should see an `ArduPilot SITL + JSBSim` banner. A message such as `Waiting for connection` is expected until QGroundControl connects. The Cessna in FlightGear is only the picture; JSBSim inside Docker calculates how the simulated aircraft moves.

## 6. Connect QGroundControl

1. Open QGroundControl from Applications.
2. Open **Application Settings → Comm Links**. Choose **Add New Link** (or **Add**).
3. Name it `Docker SITL`, set **Type** to **TCP**, **Host** to `127.0.0.1`, and **Port** to `5760`.
4. Save the link, then select it and choose **Connect**.

QGroundControl should show an ArduPlane vehicle. Once connected, the simulator window should print `JSBSim backend started` and `JSBSim Execution beginning`. FlightGear should show the aircraft and update when it moves. Port 5760 accepts one TCP connection at a time, so use one QGroundControl connection to this simulator.

## 7. Stop and restart

To stop, disconnect QGroundControl, click the **simulator Terminal window**, and press **Control+C**. Close FlightGear or press **Control+C** in its Terminal window. Docker keeps the built image, so next time start at step 4; you do not need to build again. Simulator settings and logs are saved in the project's `work` folder.

## 8. Edit and share aircraft files

The aircraft model is in the repository at `Tools/autotest/aircraft/Rascal`: `Rascal.xml` is the airframe, and `Engines` holds the engine and propeller. Edit the files with any text editor, stop the simulator with **Control+C**, and start it again (step 5) to fly your change.

To share a change, open GitHub Desktop, check the list of changed files, type a summary, click **Commit to main**, then **Push origin**. To get everyone else's changes, click **Fetch origin** and then **Pull origin** before starting the simulator. Files the simulator regenerates on every run, such as `reset.xml`, are ignored and never show up as changes.

## If something does not work

- **`docker: command not found` or Docker cannot connect:** Start Docker Desktop, wait for its engine to be running, then open a new Terminal window in the project folder.
- **`no configuration file provided` or `Dockerfile` not found:** Terminal is in the wrong folder. Use `cd ` and drag the repository's `sitl-docker` folder into Terminal again.
- **`git submodules are missing`:** In GitHub Desktop choose **Repository → Open in Terminal** and run `git submodule update --init --recursive`.
- **The simulator stops with a compile error:** Someone's source edit does not build. Pull the latest changes; if it still fails, the error above the failure names the file and line.
- **FlightGear launcher says it cannot find FlightGear:** Put `FlightGear.app` directly in Applications so its path is `/Applications/FlightGear.app`.
- **QGroundControl cannot connect:** Keep the simulator window open; confirm the link is **TCP**, host `127.0.0.1`, port `5760`. Close any other QGroundControl connection using that port.
- **FlightGear opens but does not move:** Connect QGroundControl first. If QGroundControl shows the aircraft but FlightGear stays still, allow FlightGear to receive network connections in **System Settings → Network → Firewall**, then restart FlightGear and the simulator.
