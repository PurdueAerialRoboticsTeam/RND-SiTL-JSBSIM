import argparse # lets users give commands through the terminal
import subprocess # lets Python execute terminal commands
import os
from pathlib import Path

def start_simulator(aircraft):
    print(f"Starting PART Simulator with {aircraft}...")

    aircraft_models = {
        "c172": "c172p",
        "advanced": "advanced_plane"
    }

    model = aircraft_models[aircraft]

    subprocess.run([
        "docker", "compose", "run",
        "--rm",
        "--service-ports",
        "-e", "SIM_BACKEND=json",
        "-e", f"JSBSIM_MODEL={model}",
        "sitl"
    ])

def stop_simulator():
    print("Stopping PART Simulator...")
    subprocess.run(["docker", "compose", "down"])

def simulator_status():
    subprocess.run(["docker", "compose", "ps"]) # ps --> Process (Container) Status

def launch_flightgear():
    print("Launching FlightGear...")
    script_path = Path(__file__).parent / "fgview.sh"
    subprocess.Popen(["bash", str(script_path)], cwd = script_path.parent)

def main():
    parser = argparse.ArgumentParser(description="PART Simulator CLI")

    parser.add_argument("command", choices=["start", "stop", "status", "flightgear"], help="Choose a simualator command to execute: start, stop, status, or flightgear.")
    
    parser.add_argument(
        "--aircraft",
        choices=["c172", "advanced"],
        default="c172",
        help="Select the aircraft to simulate"
    )
    
    args = parser.parse_args()

    if args.command == "start":
        start_simulator(args.aircraft)
    elif args.command == "stop":
        stop_simulator()
    elif args.command == "status":
        simulator_status()
    elif args.command == "flightgear":
        launch_flightgear()

if __name__ == "__main__":
    main()

