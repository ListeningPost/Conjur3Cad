# Conjur3 — full FreeCAD GUI inside a container, viewable via noVNC,
# driven by the conjur3-pilot MCP over HTTP/SSE so the Anthropic Messages
# API (and any other remote MCP client) can call it.
#
# Stack (all running together inside one container):
#   Xvfb            → headless X server on :0
#   fluxbox         → minimal window manager
#   x11vnc          → exposes :0 over VNC on :5900 (localhost only)
#   websockify+noVNC → browser-accessible VNC at :6080
#   FreeCAD (GUI)   → loads the Conjur3 workbench → addon auto-starts
#                     its XML-RPC bridge on :9875 (localhost only)
#   conjur3-pilot   → FastMCP server, streamable-http on :8765
#   cloudflared     → (optional, dev only) public trycloudflare.com URL
#
# Build args:
#   FASTENERS_WB_REF  — tag/branch of shaise/FreeCAD_FastenersWB to install
#   CLOUDFLARED_VER   — cloudflared release to download (or "skip" to omit)

# ---------------------------------------------------------------------------
# Stage 1: clone the Fasteners Workbench.
# ---------------------------------------------------------------------------
FROM alpine/git:latest AS fasteners
ARG FASTENERS_WB_REPO=https://github.com/shaise/FreeCAD_FastenersWB.git
ARG FASTENERS_WB_REF=master
RUN git clone --depth 1 --branch "${FASTENERS_WB_REF}" "${FASTENERS_WB_REPO}" /opt/FastenersWorkbench \
 && rm -rf /opt/FastenersWorkbench/.git

# ---------------------------------------------------------------------------
# Stage 2: runtime — FreeCAD GUI + VNC + MCP wrapper.
# ---------------------------------------------------------------------------
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG CLOUDFLARED_VER=2024.10.0

# Base packages: FreeCAD GUI + a virtual display + VNC + noVNC + a WM,
# plus pip for the MCP wrapper and curl/ca-certs for cloudflared.
#
# Ubuntu 24.04's main repo doesn't ship freecad. The freecad-maintainers stable
# PPA is added for a newer build than universe's; as of late 2026 it provides
# 0.21.2 for 24.04, not 1.0.x, so that is what this image runs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
        gnupg \
        ca-certificates \
 && add-apt-repository -y universe \
 && add-apt-repository -y ppa:freecad-maintainers/freecad-stable \
 && apt-get update && apt-get install -y --no-install-recommends \
        freecad \
        xvfb \
        x11vnc \
        novnc \
        websockify \
        fluxbox \
        xdotool \
        python3 \
        python3-pip \
        python3-venv \
        curl \
        netcat-openbsd \
        tini \
 && rm -rf /var/lib/apt/lists/*

# cloudflared — optional dev tunneler. Pinned by build arg; set to "skip"
# to omit it from the image entirely.
RUN if [ "${CLOUDFLARED_VER}" != "skip" ]; then \
      curl -fsSL -o /usr/local/bin/cloudflared \
        "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VER}/cloudflared-linux-amd64" \
      && chmod +x /usr/local/bin/cloudflared ; \
    fi

# FreeCAD Mod dir for root (the container runs as root).
ENV FREECAD_MOD_DIR=/root/.local/share/FreeCAD/Mod
RUN mkdir -p "${FREECAD_MOD_DIR}"
COPY --from=fasteners /opt/FastenersWorkbench ${FREECAD_MOD_DIR}/FastenersWorkbench
COPY conjur3-pilot/addon/conjur3_pilot ${FREECAD_MOD_DIR}/Conjur3

# MCP wrapper package. Install into an isolated venv so we don't fight
# Ubuntu 24.04's externally-managed system Python or its debian-installed
# typing_extensions / pyjwt etc. The venv's bin goes on PATH so the
# `conjur3-pilot` console script is reachable from the entrypoint.
WORKDIR /opt/conjur3
COPY conjur3-pilot ./conjur3-pilot
RUN python3 -m venv /opt/conjur3/venv \
 && /opt/conjur3/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/conjur3/venv/bin/pip install --no-cache-dir ./conjur3-pilot
ENV PATH="/opt/conjur3/venv/bin:${PATH}"

# Display + noVNC defaults.
#
# QTWEBENGINE_DISABLE_SANDBOX and QTWEBENGINE_CHROMIUM_FLAGS are critical:
# FreeCAD's Addon Manager pulls in Qt WebEngine, which embeds chromium.
# Chromium aborts the process when running as root without --no-sandbox,
# which silently kills FreeCAD a few seconds after startup. We're root inside
# this container by design (single-tenant tooling), so we disable the sandbox.
# XDG_RUNTIME_DIR is also explicit so Qt doesn't spam "defaulting to..." warnings.
ENV DISPLAY=:0 \
    VNC_PORT=5900 \
    NOVNC_PORT=6080 \
    MCP_PORT=8765 \
    RPC_PORT=9875 \
    SCREEN_GEOMETRY=1440x900x24 \
    XDG_RUNTIME_DIR=/tmp/runtime-root \
    QTWEBENGINE_DISABLE_SANDBOX=1 \
    QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox \
    PYTHONUNBUFFERED=1

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 6080 8765
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
