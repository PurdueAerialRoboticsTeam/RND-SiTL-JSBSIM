# syntax=docker/dockerfile:1
###############################################################################
# ArduPilot SITL + JSBSim
#
# Portable across macOS (Intel and Apple Silicon), Linux and WSL2.
# Everything is compiled from source for the *native* CPU architecture of the
# machine doing the build, so there is no QEMU emulation and no Rosetta.
###############################################################################
ARG UBUNTU_VERSION=24.04
FROM ubuntu:${UBUNTU_VERSION}

ARG DEBIAN_FRONTEND=noninteractive

# --- What to build ----------------------------------------------------------
# ArduPilot is NOT in the image. Its source is this git repository, which is
# bind-mounted at /opt/ardupilot and compiled by entrypoint.sh at startup.
ARG JSBSIM_REPO=https://github.com/JSBSim-Team/jsbsim.git
# Pinned to a release tag so every computer builds the same JSBSim. The
# Python module for the JSON backend is installed at the same version.
ARG JSBSIM_REF=v1.3.3
# Set to "-march=native -mtune=native" ONLY if the image will never leave this
# machine. Leave empty for a portable image.
ARG NATIVE_FLAGS=""
ARG UID=1000
ARG GID=1000

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=UTC

# --- System packages --------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ccache cmake g++ gawk make \
      git rsync wget curl unzip ca-certificates \
      libtool libxml2-dev libxslt1-dev zlib1g-dev libexpat1-dev pkg-config \
      python3 python3-dev python3-venv \
      procps iproute2 iputils-ping socat tzdata \
  && rm -rf /var/lib/apt/lists/*

# --- JSBSim -----------------------------------------------------------------
# ArduPilot's SITL backend literally does execlp("JSBSim", ...), so the binary
# must be named exactly "JSBSim" and be on PATH.
RUN git clone --depth 1 --branch "${JSBSIM_REF}" "${JSBSIM_REPO}" /tmp/jsbsim \
 && cmake -S /tmp/jsbsim -B /tmp/jsbsim/build \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_CXX_FLAGS_RELEASE="-O3 ${NATIVE_FLAGS}" \
      -DCMAKE_C_FLAGS_RELEASE="-O3 ${NATIVE_FLAGS}" \
      -DBUILD_DOCS=OFF \
      -DBUILD_PYTHON_MODULE=OFF \
 && cmake --build /tmp/jsbsim/build -j "$(nproc)" \
 && install -m 0755 /tmp/jsbsim/build/src/JSBSim /usr/local/bin/JSBSim \
 && JSBSim --version || true \
 && rm -rf /tmp/jsbsim

# --- Unprivileged user ------------------------------------------------------
# Ubuntu 24.04 ships a default "ubuntu" user on uid 1000; remove it so we can
# own that uid ourselves (keeps bind-mounted log files owned by you on Linux).
RUN if id -u ubuntu >/dev/null 2>&1; then userdel -r ubuntu 2>/dev/null || true; fi \
 && groupadd -g "${GID}" sitl \
 && useradd -m -u "${UID}" -g "${GID}" -s /bin/bash sitl \
 && mkdir -p /opt/ardupilot /opt/venv /home/sitl/work \
 && chown -R sitl:sitl /opt/ardupilot /opt/venv /home/sitl

# --- Python environment -----------------------------------------------------
# A venv avoids PEP 668 "externally managed environment" errors on 24.04.
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:/usr/lib/ccache:${PATH}"

USER sitl
RUN python3 -m venv "${VIRTUAL_ENV}" \
 && pip install --no-cache-dir --upgrade pip setuptools wheel \
 && pip install --no-cache-dir \
      "empy==3.3.4" \
      pexpect future lxml numpy pyserial requests \
      pymavlink dronecan MAVProxy

# JSBSim's Python module, for the JSON backend (SIM_BACKEND=json). Same
# release as the JSBSim binary above, so JSBSIM_REF must be a release tag.
# PyPI has wheels for x86_64; on arm64 (Apple Silicon, Raspberry Pi) pip
# compiles the same release from its source package, which takes a few
# minutes.
RUN pip install --no-cache-dir "jsbsim==${JSBSIM_REF#v}" \
 && python3 -c "import jsbsim; print('JSBSim Python module', jsbsim.__version__)"

# --- ArduPilot --------------------------------------------------------------
# /opt/ardupilot is only a mount point for the repository on the host. The host
# checkout can be owned by a different uid than "sitl" (native Linux), which
# git otherwise refuses to operate on.
RUN git config --global --add safe.directory '*'

ENV AP_DIR=/opt/ardupilot \
    PATH="/opt/ardupilot/Tools/autotest:${PATH}"

USER root
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh
USER sitl

WORKDIR /home/sitl/work

# 5760 = autopilot serial0 (MAVLink over TCP), 5762/5763 = serial1/serial2
EXPOSE 5760 5762 5763 14550/udp

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
