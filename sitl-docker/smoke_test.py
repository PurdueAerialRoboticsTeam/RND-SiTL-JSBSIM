#!/usr/bin/env python3
"""End-to-end check: connect, arm in TAKEOFF, confirm the aircraft climbs.

Run inside the container:  docker exec -i <container> python3 - < smoke_test.py
A climb only happens if JSBSim is actually stepping the physics, so this is a
real test of the FDM, not just of the MAVLink link.
"""
import sys
import time

from pymavlink import mavutil

PLANE_MODE_TAKEOFF = 13
TARGET_ALT_M = 20.0
CONNECT_TIMEOUT = 60
FIX_TIMEOUT = 180
CLIMB_TIMEOUT = 180


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


print("connecting to tcp:127.0.0.1:5760 ...")
m = mavutil.mavlink_connection("tcp:127.0.0.1:5760")
if not m.wait_heartbeat(timeout=CONNECT_TIMEOUT):
    fail("no heartbeat - SITL not listening or port already taken")
print(f"  heartbeat from system {m.target_system}")

print("waiting for 3D GPS fix ...")
deadline = time.time() + FIX_TIMEOUT
while time.time() < deadline:
    msg = m.recv_match(type="GPS_RAW_INT", blocking=True, timeout=5)
    if msg and msg.fix_type >= 3:
        print(f"  fix_type={msg.fix_type} sats={msg.satellites_visible}")
        break
else:
    fail("never got a 3D fix - physics probably frozen (JSBSim not running)")

print("setting TKOFF_ALT=80 ...")
m.mav.param_set_send(
    m.target_system, m.target_component,
    b"TKOFF_ALT", 80.0, mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
)
time.sleep(1)

print("mode TAKEOFF ...")
m.mav.set_mode_send(
    m.target_system,
    mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
    PLANE_MODE_TAKEOFF,
)
time.sleep(2)

print("arming (retrying while prearm checks settle) ...")
armed = False
deadline = time.time() + 90
while time.time() < deadline:
    m.mav.command_long_send(
        m.target_system, m.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 0, 0, 0, 0, 0, 0,
    )
    hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
    if hb and hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
        armed = True
        break
    txt = m.recv_match(type="STATUSTEXT", blocking=False)
    if txt:
        print(f"  {txt.text}")
    time.sleep(3)

if not armed:
    fail("could not arm - check STATUSTEXT above for the prearm reason")
print("  armed")

print(f"waiting for climb above {TARGET_ALT_M:.0f} m ...")
peak = -1e9
deadline = time.time() + CLIMB_TIMEOUT
while time.time() < deadline:
    msg = m.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=5)
    if not msg:
        continue
    alt = msg.relative_alt / 1000.0
    peak = max(peak, alt)
    if alt >= TARGET_ALT_M:
        print(f"  altitude {alt:.1f} m")
        print("\nPASS: aircraft armed and climbed - JSBSim is driving the sim")
        sys.exit(0)

fail(f"never climbed past {TARGET_ALT_M:.0f} m (peak {peak:.1f} m)")
