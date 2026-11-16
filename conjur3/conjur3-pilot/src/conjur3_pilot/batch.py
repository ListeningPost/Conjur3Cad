"""Batch / headless replay path for woodbloks-ai DesignProgram JSON files.

Delegates to the existing woodbloks executor which spawns FreeCAD's bundled
Python as a subprocess. Useful for CI, STEP-only jobs, or environments without
a running FreeCAD GUI.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

# Make the sibling woodbloks package importable.
_WB_SRC = Path(__file__).resolve().parents[3] / "woodbloks-ai" / "src"
if _WB_SRC.exists() and str(_WB_SRC) not in sys.path:
    sys.path.insert(0, str(_WB_SRC))


def run(program_path: str, out_fcstd: str | None = None, out_step: str | None = None) -> dict[str, Any]:
    try:
        from woodbloks.ops.executor import execute  # type: ignore
        from woodbloks.ops.schema import DesignProgram  # type: ignore
    except ImportError as e:
        return {"success": False, "error": f"woodbloks package not available: {e}"}

    data = json.loads(Path(program_path).read_text())
    program = DesignProgram.model_validate(data)
    result = execute(program)
    if out_fcstd and result.get("fcstd_path"):
        shutil.copy(result["fcstd_path"], out_fcstd)
    if out_step and result.get("step_path"):
        shutil.copy(result["step_path"], out_step)
    return {"success": True, **result}
