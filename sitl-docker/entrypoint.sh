#!/usr/bin/env bash
# Launch ArduPilot SITL with the JSBSim flight dynamics model.
set -euo pipefail

# --- Escape hatches ---------------------------------------------------------
# `docker compose run sitl bash`        -> interactive shell
# `docker compose run sitl build`       -> compile ArduPilot and exit
# `docker compose run sitl --speedup 5` -> args appended to sim_vehicle.py
case "${1:-}" in
  bash|sh|/bin/bash|/bin/sh) exec "$@" ;;
esac

AP_DIR="${AP_DIR:-/opt/ardupilot}"
WAF_TARGETS="${WAF_TARGETS:-plane}"
BUILD="${BUILD:-1}"                     # 0 = skip the waf build at startup

# --- ArduPilot source (this repository, bind-mounted from the host) ---------
if [ ! -e "${AP_DIR}/waf" ]; then
  echo "FATAL: no ArduPilot source at ${AP_DIR}." >&2
  echo "       Run docker compose from the sitl-docker folder of the repository." >&2
  exit 1
fi
if [ ! -e "${AP_DIR}/modules/waf/waf-light" ]; then
  echo "FATAL: git submodules are missing. On the host, in the repository, run:" >&2
  echo "         git submodule update --init --recursive" >&2
  exit 1
fi
# A Windows checkout made with core.autocrlf=true breaks every script here.
BRIDGE="${AP_DIR}/libraries/SITL/examples/JSON/JSBSim/jsbsim_json_bridge.py"
if grep -q $'\r' "${AP_DIR}/Tools/autotest/sim_vehicle.py" "${AP_DIR}/modules/waf/waf-light" "${BRIDGE}" 2>/dev/null; then
  echo "FATAL: the repository was checked out with Windows (CRLF) line endings." >&2
  echo "       Clone it again inside WSL, or with: git config --global core.autocrlf false" >&2
  exit 1
fi
if [ ! -w "${AP_DIR}" ]; then
  echo "FATAL: the repository is not writable by uid $(id -u) in the container." >&2
  echo "       Rebuild with --build-arg UID=\$(id -u) --build-arg GID=\$(id -g)." >&2
  exit 1
fi

build_ardupilot() {
  ( cd "${AP_DIR}" \
    && ./waf configure --board sitl \
    && ./waf ${WAF_TARGETS} -j "$(nproc)" )
}

if [ "${1:-}" = "build" ]; then
  build_ardupilot
  exit $?
fi
if [ "${BUILD}" = "1" ]; then
  echo "Building ArduPilot from the repository (incremental) ..."
  build_ardupilot
fi

VEHICLE="${VEHICLE:-ArduPlane}"
FRAME="${FRAME:-jsbsim}"                # jsbsim | jsbsim:Rascal | jsbsim:MyModel
SIM_BACKEND="${SIM_BACKEND:-jsbsim}"    # jsbsim (C++ backend, 4 channels) | json (bridge, all channels)
LOCATION="${LOCATION:-CMAC}"            # named entry in Tools/autotest/locations.txt
CUSTOM_LOCATION="${CUSTOM_LOCATION:-}"  # lat,lng,alt,heading - overrides LOCATION
SPEEDUP="${SPEEDUP:-1}"
INSTANCE="${INSTANCE:-0}"
WIPE_EEPROM="${WIPE_EEPROM:-0}"
USE_MAVPROXY="${USE_MAVPROXY:-0}"
MAVPROXY_OUT="${MAVPROXY_OUT:-}"        # comma separated --out endpoints
FGVIEW_HOST="${FGVIEW_HOST:-}"          # host running FlightGear, enables 3D view
RUN_DIR="${RUN_DIR:-/home/sitl/work}"
LOG_TO_STDOUT="${LOG_TO_STDOUT:-1}"
EXTRA_ARGS="${EXTRA_ARGS:-}"

# --- JSON backend (SIM_BACKEND=json) ---------------------------------------
# The aircraft defaults to the model named in FRAME (jsbsim:Model), else Rascal.
JSBSIM_MODEL="${JSBSIM_MODEL:-$([[ "${FRAME}" == *:* ]] && echo "${FRAME#*:}" || echo Rascal)}"
JSBSIM_AIRCRAFT_DIR="${JSBSIM_AIRCRAFT_DIR:-}"  # folder holding <model>/<model>.xml; default test-aircraft, then Tools/autotest/aircraft
JSBSIM_CONTROLS="${JSBSIM_CONTROLS:-}"          # Controls.xml; default the model's own, else SERVO1..4
JSON_FRAME="${JSON_FRAME:-}"                    # base parameters: jsbsim-json (plane-jsbsim.parm) | plane (models/plane.parm)
PARAM_FILES="${PARAM_FILES:-}"                  # comma separated parameter files added on top
BRIDGE_ARGS="${BRIDGE_ARGS:-}"                  # extra bridge options, see jsbsim_json_bridge.py --help

# An aircraft that ships its own ArduPilot parameters, as PteroSimAircrafts'
# do in firmwares/ardupilot_<model>.param, flies with them on top of
# models/plane.parm, the base they are written for, unless told otherwise.
if [ "${SIM_BACKEND:-}" = "json" ] && [ -z "${JSON_FRAME}" ] && [ -z "${PARAM_FILES}" ]; then
  for d in ${JSBSIM_AIRCRAFT_DIR:-test-aircraft Tools/autotest/aircraft}; do
    [[ "${d}" = /* ]] || d="${AP_DIR}/${d}"
    if [ -f "${d}/${JSBSIM_MODEL}/${JSBSIM_MODEL}.xml" ]; then
      own="${d}/${JSBSIM_MODEL}/firmwares/ardupilot_${JSBSIM_MODEL}.param"
      if [ -f "${own}" ]; then
        JSON_FRAME=plane
        PARAM_FILES="${own}"
      fi
      break
    fi
  done
fi
JSON_FRAME="${JSON_FRAME:-jsbsim-json}"

SIM_VEHICLE="${AP_DIR}/Tools/autotest/sim_vehicle.py"

# --- Sanity checks ----------------------------------------------------------
case "${SIM_BACKEND}" in
  jsbsim)
    # The backend calls execlp("JSBSim", ...), so the name must match exactly.
    if ! command -v JSBSim >/dev/null 2>&1; then
      echo "FATAL: JSBSim binary not found on PATH." >&2
      exit 1
    fi ;;
  json)
    if ! python3 -c "import jsbsim" 2>/dev/null; then
      echo "FATAL: JSBSim's Python module is missing. Rebuild the image: docker compose build" >&2
      exit 1
    fi ;;
  *)
    echo "FATAL: SIM_BACKEND must be jsbsim or json, not '${SIM_BACKEND}'." >&2
    exit 1 ;;
esac
# At runtime the backend writes jsbsim_start_N.xml, jsbsim_fgout_N.xml and
# aircraft/<model>/reset.xml into the autotest directory.
if [ ! -w "${AP_DIR}/Tools/autotest" ]; then
  echo "FATAL: ${AP_DIR}/Tools/autotest is not writable." >&2
  echo "       The JSBSim backend generates XML into that directory at runtime." >&2
  exit 1
fi

mkdir -p "${RUN_DIR}"
cd "${RUN_DIR}"

# --- Assemble the command ---------------------------------------------------
sim_frame="${FRAME}"
[ "${SIM_BACKEND}" = "json" ] && sim_frame="${JSON_FRAME}"
args=( "${SIM_VEHICLE}"
       --vehicle "${VEHICLE}"
       --frame "${sim_frame}"
       --instance "${INSTANCE}"
       --speedup "${SPEEDUP}"
       --no-rebuild )
if [ "${SIM_BACKEND}" = "json" ]; then
  args+=( --model JSON:127.0.0.1 )
  IFS=',' read -ra pfiles <<< "${PARAM_FILES}"
  for f in "${pfiles[@]}"; do
    [ -z "${f}" ] && continue
    [[ "${f}" = /* ]] || f="${AP_DIR}/${f}"
    if [ ! -r "${f}" ]; then
      echo "FATAL: parameter file ${f} not found." >&2
      exit 1
    fi
    args+=( --add-param-file "${f}" )
  done
fi

if [ -n "${CUSTOM_LOCATION}" ]; then
  args+=( --custom-location "${CUSTOM_LOCATION}" )
else
  args+=( --location "${LOCATION}" )
fi

[ "${WIPE_EEPROM}" = "1" ] && args+=( --wipe-eeprom )

# Any --out endpoint implies MAVProxy has to run to do the forwarding.
[ -n "${MAVPROXY_OUT}" ] && USE_MAVPROXY=1

if [ "${USE_MAVPROXY}" = "1" ]; then
  IFS=',' read -ra outs <<< "${MAVPROXY_OUT}"
  for o in "${outs[@]}"; do
    [ -n "${o}" ] && args+=( --out "${o}" )
  done
else
  args+=( --no-mavproxy )
fi

fg_target="disabled"
if [ -n "${FGVIEW_HOST}" ]; then
  # SITL parses --fg as a numeric address and performs no DNS lookup, so names
  # such as host.docker.internal must be resolved here or packets go nowhere.
  fg_ip="$(getent ahostsv4 "${FGVIEW_HOST}" 2>/dev/null | awk '{print $1; exit}')"
  fg_ip="${fg_ip:-${FGVIEW_HOST}}"
  fg_target="${fg_ip}:5503 (${FGVIEW_HOST})"
  args+=( --enable-fgview -A "--fg ${fg_ip}" )
fi

# shellcheck disable=SC2206
[ -n "${EXTRA_ARGS}" ] && args+=( ${EXTRA_ARGS} )
args+=( "$@" )

base_port=$(( 5760 + INSTANCE * 10 ))
cat <<EOF
--------------------------------------------------------------------
 ArduPilot SITL + JSBSim
   vehicle    : ${VEHICLE}
   backend    : ${SIM_BACKEND}$([ "${SIM_BACKEND}" = "json" ] && echo " (aircraft ${JSBSIM_MODEL}, frame ${sim_frame}${PARAM_FILES:+, params ${PARAM_FILES}})")
   frame      : ${sim_frame}
   location   : ${CUSTOM_LOCATION:-${LOCATION}}
   speedup    : ${SPEEDUP}x
   run dir    : ${RUN_DIR}
   MAVProxy   : $([ "${USE_MAVPROXY}" = "1" ] && echo "yes -> ${MAVPROXY_OUT:-console only}" || echo "no")
   FlightGear : ${fg_target}

 Connect your GCS from the host to:  tcp://127.0.0.1:${base_port}
 $([ "${SIM_BACKEND}" = "json" ] && echo "The JSBSim bridge waits for SITL, which starts on the first GCS connection." || echo "JSBSim starts on the first GCS connection, not at boot.")
--------------------------------------------------------------------
EOF

# There is no terminal emulator in a container, so run_in_terminal_window.sh
# detaches SITL into /tmp/<Vehicle>.log instead of showing it. Mirror that file
# to stdout so autopilot and JSBSim output reach `docker compose logs`.
if [ "${LOG_TO_STDOUT}" = "1" ]; then
  SITL_LOG="/tmp/${VEHICLE}.log"
  : > "${SITL_LOG}"
  ( tail -n +1 -F "${SITL_LOG}" 2>/dev/null | sed -u "s/^/[${VEHICLE}] /" ) &
fi

# --- JSON backend: start the bridge first ----------------------------------
# It runs in the background next to SITL and stops with the container. SITL
# sends to 9002 + 10 * instance.
if [ "${SIM_BACKEND}" = "json" ]; then
  bridge_args=( --aircraft "${JSBSIM_MODEL}" --port $(( 9002 + INSTANCE * 10 )) )
  if [ -n "${CUSTOM_LOCATION}" ]; then
    bridge_args+=( --home "${CUSTOM_LOCATION}" )
  else
    bridge_args+=( --location "${LOCATION}" )
  fi
  # relative paths are relative to the repository, like PARAM_FILES
  [ -n "${JSBSIM_AIRCRAFT_DIR}" ] && [[ "${JSBSIM_AIRCRAFT_DIR}" != /* ]] && JSBSIM_AIRCRAFT_DIR="${AP_DIR}/${JSBSIM_AIRCRAFT_DIR}"
  [ -n "${JSBSIM_CONTROLS}" ] && [[ "${JSBSIM_CONTROLS}" != /* ]] && JSBSIM_CONTROLS="${AP_DIR}/${JSBSIM_CONTROLS}"
  [ -n "${JSBSIM_AIRCRAFT_DIR}" ] && bridge_args+=( --aircraft-dir "${JSBSIM_AIRCRAFT_DIR}" )
  [ -n "${JSBSIM_CONTROLS}" ] && bridge_args+=( --controls "${JSBSIM_CONTROLS}" )
  # shellcheck disable=SC2206
  [ -n "${BRIDGE_ARGS}" ] && bridge_args+=( ${BRIDGE_ARGS} )
  BRIDGE_LOG="${RUN_DIR}/bridge.log"
  : > "${BRIDGE_LOG}"
  python3 "${BRIDGE}" "${bridge_args[@]}" > "${BRIDGE_LOG}" 2>&1 &
  bridge_pid=$!
  ( tail -n +1 -F "${BRIDGE_LOG}" 2>/dev/null | sed -u "s/^/[bridge] /" ) &
  for _ in $(seq 1 100); do
    grep -q "waiting for SITL" "${BRIDGE_LOG}" && break
    if ! kill -0 "${bridge_pid}" 2>/dev/null; then
      sleep 0.5
      echo "FATAL: the JSBSim bridge exited, see the [bridge] lines above." >&2
      exit 1
    fi
    sleep 0.2
  done
fi

exec "${args[@]}"
