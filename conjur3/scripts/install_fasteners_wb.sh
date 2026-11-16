#!/usr/bin/env bash
# install_fasteners_wb.sh — clone (or update) the FreeCAD Fasteners Workbench
# into a target Mod directory. Idempotent; safe to run as part of a docker
# build or a local setup.
#
# Usage:
#   ./scripts/install_fasteners_wb.sh                       # default user Mod dir
#   FREECAD_MOD_DIR=/opt/freecad/Mod ./scripts/install_fasteners_wb.sh
#   FASTENERS_WB_REF=v0.6.10 ./scripts/install_fasteners_wb.sh   # pin a tag
#
# Env:
#   FREECAD_MOD_DIR    Target FreeCAD Mod directory. Defaults to
#                      $HOME/.local/share/FreeCAD/Mod on Linux.
#   FASTENERS_WB_REPO  Git URL. Defaults to the upstream Shai Seger repo.
#   FASTENERS_WB_REF   Branch/tag/commit to check out. Defaults to "master".
set -euo pipefail

REPO="${FASTENERS_WB_REPO:-https://github.com/shaise/FreeCAD_FastenersWB.git}"
REF="${FASTENERS_WB_REF:-master}"
TARGET_PARENT="${FREECAD_MOD_DIR:-$HOME/.local/share/FreeCAD/Mod}"
TARGET="$TARGET_PARENT/FastenersWorkbench"

mkdir -p "$TARGET_PARENT"

if [ -d "$TARGET/.git" ]; then
  echo "[fasteners-wb] Updating existing checkout at $TARGET"
  git -C "$TARGET" fetch --depth 1 origin "$REF"
  git -C "$TARGET" checkout --detach FETCH_HEAD
else
  if [ -d "$TARGET" ] && [ -n "$(ls -A "$TARGET" 2>/dev/null)" ]; then
    echo "[fasteners-wb] $TARGET exists and is non-empty but not a git repo." >&2
    echo "[fasteners-wb] Refusing to overwrite. Remove it manually if you want a fresh install." >&2
    exit 1
  fi
  echo "[fasteners-wb] Cloning $REPO @ $REF into $TARGET"
  git clone --depth 1 --branch "$REF" "$REPO" "$TARGET"
fi

echo "[fasteners-wb] Installed at $TARGET"
echo "[fasteners-wb] FreeCAD should pick this up on next launch (Mod auto-load)."
