#!/usr/bin/env bash
# Start FlightGear on the HOST as a view-only window for ArduPilot SITL.
# Run this BEFORE starting the container.
#
#   ./fgview.sh                  # Cessna 172P, ships with FlightGear
#   AIRCRAFT=Rascal110-JSBSim ./fgview.sh
#   AIRPORT=KSFO ./fgview.sh
set -euo pipefail

AIRCRAFT="${AIRCRAFT:-c172p}"   # purely cosmetic: --fdm=external drives it
AIRPORT="${AIRPORT:-YSCB}"      # YSCB = Canberra, nearest to the CMAC default
RATE="${RATE:-30}"              # Hz. 10 is the old default and looks jerky.
FGFS="${FGFS:-}"

if [ -z "${FGFS}" ]; then
  for candidate in \
      /Applications/FlightGear.app/Contents/MacOS/FlightGear \
      /Applications/FlightGear.app/Contents/MacOS/fgfs \
      "$(command -v fgfs 2>/dev/null || true)"
  do
    if [ -n "${candidate}" ] && [ -x "${candidate}" ]; then FGFS="${candidate}"; break; fi
  done
fi

if [ -z "${FGFS}" ]; then
  echo "FlightGear not found. Install it, or set FGFS=/path/to/binary." >&2
  echo "On macOS the executable inside the bundle is named 'FlightGear'." >&2
  exit 1
fi

echo "Using ${FGFS}"
echo "Listening for SITL FDM on UDP 5503 at ${RATE} Hz"

# The empty field between the two commas is the bind address; leaving it blank
# binds all interfaces, which is required to accept packets from the Docker VM.
exec "${FGFS}" \
  --native-fdm=socket,in,"${RATE}",,5503,udp \
  --fdm=external \
  --aircraft="${AIRCRAFT}" \
  --airport="${AIRPORT}" \
  --enable-terrasync \
  --timeofday=noon \
  --disable-sound \
  --disable-hud-3d \
  --disable-random-objects \
  --disable-ai-models \
  --geometry=1000x700 \
  "$@"
