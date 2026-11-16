"""Optional parts-library addon bridge. Vendored from neka-nat/freecad-mcp (MIT)."""

import os
from functools import cache

import FreeCAD
import FreeCADGui


def insert_part_from_library(relative_path):
    parts_lib_path = os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "parts_library")
    part_path = os.path.join(parts_lib_path, relative_path)
    if not os.path.exists(part_path):
        raise FileNotFoundError(f"Not found: {part_path}")
    FreeCADGui.ActiveDocument.mergeProject(part_path)


@cache
def get_parts_list():
    parts_lib_path = os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "parts_library")
    if not os.path.exists(parts_lib_path):
        return []
    parts = []
    for root, _, files in os.walk(parts_lib_path):
        for file in files:
            if file.endswith(".FCStd"):
                parts.append(os.path.relpath(os.path.join(root, file), parts_lib_path))
    return parts
