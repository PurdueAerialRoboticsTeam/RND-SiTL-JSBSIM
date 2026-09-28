#!/usr/bin/env bash
# Verify a fresh build of the SITL container end to end (macOS / Linux / WSL).
#   ./smoke-test.sh            # use cached layers
#   NO_CACHE=1 ./smoke-test.sh # full rebuild, ~25 minutes
set -uo pipefail

CONTAINER=ardupilot-sitl
pass=0; fail=0

check() {  # check <label> <command...>
  local label="$1"; shift
  if "$@" >/tmp/smoke.out 2>&1; then
    echo "  ok   ${label}"; pass=$((pass+1))
  else
    echo "  FAIL ${label}"; sed 's/^/       /' /tmp/smoke.out | head -15; fail=$((fail+1))
  fi
}

in_container() { docker compose run --rm --no-deps sitl bash -c "$1"; }

cleanup() { docker compose down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== 0. docker daemon =="
if ! docker info >/dev/null 2>&1; then
  echo "  FAIL docker daemon not reachable - start Docker Desktop"; exit 1
fi
echo "  ok   daemon reachable"

echo "== 1. compose file parses =="
check "docker compose config" docker compose config -q

echo "== 2. build =="
if [ "${NO_CACHE:-0}" = "1" ]; then
  docker compose build --no-cache --progress plain || exit 1
else
  docker compose build || exit 1
fi
docker compose run --rm --no-deps -T sitl build || exit 1

echo "== 3. image contents =="
check "JSBSim on PATH"          in_container 'command -v JSBSim'
check "arduplane built"         in_container 'test -x /opt/ardupilot/build/sitl/bin/arduplane'
check "autotest writable"       in_container 'test -w /opt/ardupilot/Tools/autotest'
check "not running as root"     in_container '[ "$(id -u)" -ne 0 ]'
check "pymavlink present"       in_container 'python3 -c "import pymavlink"'
check "entrypoint LF endings"   in_container '! grep -q "$(printf "\r")" /usr/local/bin/entrypoint.sh'
check "jsbsim params exist"     in_container 'test -f /opt/ardupilot/Tools/autotest/default_params/plane-jsbsim.parm'

echo "== 4. start the simulator =="
docker compose up -d || exit 1
echo -n "  waiting for SERIAL0 to bind"
for _ in $(seq 1 60); do
  if docker compose logs 2>&1 | grep -q "SERIAL0 on TCP port 5760"; then break; fi
  echo -n "."; sleep 2
done
echo
check "SERIAL0 bound" bash -c "docker compose logs 2>&1 | grep -q 'SERIAL0 on TCP port 5760'"

echo "== 5. flight test (arms and climbs) =="
docker cp smoke_test.py "${CONTAINER}:/tmp/smoke_test.py" >/dev/null
if docker exec "${CONTAINER}" python3 /tmp/smoke_test.py; then
  echo "  ok   flight test"; pass=$((pass+1))
else
  echo "  FAIL flight test"; fail=$((fail+1))
fi

echo "== 6. JSBSim really started =="
check "JSBSim backend line"   bash -c "docker compose logs 2>&1 | grep -q 'JSBSim backend started'"
check "JSBSim execution line" bash -c "docker compose logs 2>&1 | grep -q 'JSBSim Execution beginning'"

echo
echo "passed ${pass}, failed ${fail}"
[ "${fail}" -eq 0 ] || exit 1
echo "Container is good to go."
