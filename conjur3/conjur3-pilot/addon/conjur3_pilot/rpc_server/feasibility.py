"""Pre-execution feasibility checks for parametric CAD operations.

A pre-execution feasibility gate: action specifications are evaluated against
domain-specific geometric checks before the kernel is invoked, and an
infeasible action produces a structured failure report.

Each check is a pure function: it takes the proposed parameters (and any
already-known geometric context) and returns either:

  - `None`  — the action is feasible, proceed
  - `dict`  — a failure detail block ready to be passed to `ValidationError`,
              with keys `failure_type`, `suggestion`, and `details`.

The caller (in `rpc_server.py`) uses the `_check()` helper to convert a
failure dict into a `ValidationError`, which then routes through `_err()`
into the structured corrective-reprompt payload defined in the response
contract. The kernel is never invoked when a check fails.

Module is FreeCAD-independent — operates on plain numbers and dicts — so it
can be unit-tested without the FreeCAD interpreter.
"""

from __future__ import annotations

import math
from typing import Any


FailureDetail = dict[str, Any]


# ---------------------------------------------------------------------------
# Generic parameter-sanity checks
# ---------------------------------------------------------------------------


def check_positive(name: str, value: float) -> FailureDetail | None:
    """Reject non-positive values for parameters that must be > 0.

    Used for radius, length, depth, angle — any parameter where a zero or
    negative value is geometrically meaningless or produces a degenerate
    feature.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return {
            "failure_type": "invalid_parameter",
            "suggestion": f"{name} must be a number, got {value!r}",
            "details": {"parameter": name, "value": value},
        }
    if v <= 0:
        return {
            "failure_type": "non_positive_parameter",
            "suggestion": f"{name} must be greater than 0; got {v}",
            "details": {"parameter": name, "value": v, "minimum": 0,
                        "exclusive": True},
        }
    return None


# ---------------------------------------------------------------------------
# Fillet / chamfer
# ---------------------------------------------------------------------------


def check_fillet_radius(
    radius: float,
    min_adjacent_edge_length: float,
) -> FailureDetail | None:
    """Fillet radius must be positive and not exceed half the shortest edge.

    OCCT's fillet algorithm fails (or produces an invalid solid) when the
    radius is larger than the half-length of the shortest adjacent edge,
    because the swept arc consumes both endpoints of the edge.
    """
    fail = check_positive("radius", radius)
    if fail:
        return fail
    if min_adjacent_edge_length <= 0:
        return {
            "failure_type": "degenerate_edge",
            "suggestion": "the selected edge has zero or negative length",
            "details": {"min_adjacent_edge_length": min_adjacent_edge_length},
        }
    max_allowed = min_adjacent_edge_length / 2.0
    if float(radius) > max_allowed:
        return {
            "failure_type": "infeasible_fillet",
            "suggestion": (
                f"fillet radius {radius}mm exceeds half the shortest adjacent "
                f"edge length ({min_adjacent_edge_length:.3f}mm); reduce radius "
                f"to <= {max_allowed:.3f}mm or fillet a longer edge"
            ),
            "details": {
                "radius": float(radius),
                "min_adjacent_edge_length": float(min_adjacent_edge_length),
                "max_allowed_radius": max_allowed,
            },
        }
    return None


def check_chamfer_size(
    size: float,
    min_adjacent_edge_length: float,
) -> FailureDetail | None:
    """Chamfer leg length must be positive and not exceed half the shortest edge.

    Same geometric reasoning as fillet — at half the edge length the chamfer
    consumes the entire edge and the operation degenerates.
    """
    fail = check_positive("size", size)
    if fail:
        return fail
    if min_adjacent_edge_length <= 0:
        return {
            "failure_type": "degenerate_edge",
            "suggestion": "the selected edge has zero or negative length",
            "details": {"min_adjacent_edge_length": min_adjacent_edge_length},
        }
    max_allowed = min_adjacent_edge_length / 2.0
    if float(size) > max_allowed:
        return {
            "failure_type": "infeasible_chamfer",
            "suggestion": (
                f"chamfer size {size}mm exceeds half the shortest adjacent "
                f"edge length ({min_adjacent_edge_length:.3f}mm); reduce size "
                f"to <= {max_allowed:.3f}mm or chamfer a longer edge"
            ),
            "details": {
                "size": float(size),
                "min_adjacent_edge_length": float(min_adjacent_edge_length),
                "max_allowed_size": max_allowed,
            },
        }
    return None


# ---------------------------------------------------------------------------
# Pocket / pad
# ---------------------------------------------------------------------------


def check_pocket_depth(
    depth: float,
    body_extent_along_normal: float | None = None,
) -> FailureDetail | None:
    """Pocket depth must be positive; warn if it exceeds the body extent."""
    fail = check_positive("depth", depth)
    if fail:
        return fail
    if body_extent_along_normal is not None:
        if float(depth) > float(body_extent_along_normal):
            return {
                "failure_type": "pocket_exceeds_body",
                "suggestion": (
                    f"pocket depth {depth}mm exceeds body extent along the "
                    f"sketch normal ({body_extent_along_normal:.3f}mm); the cut "
                    f"will pierce through — use `pocket_through` instead, or "
                    f"reduce depth to <= {body_extent_along_normal:.3f}mm"
                ),
                "details": {
                    "depth": float(depth),
                    "body_extent_along_normal": float(body_extent_along_normal),
                },
            }
    return None


# ---------------------------------------------------------------------------
# Gear-tooth undercut
# ---------------------------------------------------------------------------


def check_gear_undercut(
    teeth: int,
    pressure_angle_deg: float = 20.0,
    *,
    safety_margin_teeth: int = 2,
) -> FailureDetail | None:
    """Reject gears whose tooth count is below the safe undercut-free minimum.

    Theoretical minimum for an involute pinion to avoid undercut is
    `2/sin²(α)`, where α is the pressure angle. We add a safety margin (default
    2 teeth) over the theoretical minimum because the theoretical value
    produces mushy tooth profiles with zero margin for manufacturing error.
    """
    if teeth is None:
        return None
    try:
        z = int(teeth)
        pa = float(pressure_angle_deg)
    except (TypeError, ValueError):
        return {
            "failure_type": "invalid_parameter",
            "suggestion": "teeth must be an integer and pressure_angle_deg a number",
            "details": {"teeth": teeth, "pressure_angle_deg": pressure_angle_deg},
        }
    if pa <= 0 or pa >= 90:
        return {
            "failure_type": "invalid_pressure_angle",
            "suggestion": "pressure_angle_deg must be in (0, 90); typical values are 14.5°, 20°, 25°",
            "details": {"pressure_angle_deg": pa},
        }
    if z <= 0:
        return check_positive("teeth", z)
    z_theory = 2.0 / (math.sin(math.radians(pa)) ** 2)
    z_safe = math.ceil(z_theory) + safety_margin_teeth
    if z < z_safe:
        # Compute alternative: how many teeth needed at 25° PA?
        z_safe_25 = math.ceil(2.0 / (math.sin(math.radians(25.0)) ** 2)) + safety_margin_teeth
        suggestion = (
            f"{z} teeth at {pa}° pressure angle is below the safe undercut-free "
            f"minimum of {z_safe} (theoretical min = {math.ceil(z_theory)}). "
            f"Either increase teeth to >= {z_safe}, or raise pressure angle "
            f"(25° allows teeth >= {z_safe_25}), or apply a positive profile "
            f"shift coefficient (~0.3-0.5)"
        )
        return {
            "failure_type": "gear_undercut",
            "suggestion": suggestion,
            "details": {
                "teeth": z,
                "pressure_angle_deg": pa,
                "min_safe_teeth": z_safe,
                "theoretical_min_teeth": math.ceil(z_theory),
                "min_safe_teeth_at_25deg": z_safe_25,
            },
        }
    return None


# ---------------------------------------------------------------------------
# Countersunk hole geometry
# ---------------------------------------------------------------------------


def check_countersink_geometry(
    counterbore_diam: float,
    bore_diam: float,
    counterbore_depth: float,
    total_depth: float,
) -> FailureDetail | None:
    """Counterbore must be wider than the through bore and shallower than total."""
    for name, val in [("counterbore_diam", counterbore_diam),
                       ("bore_diam", bore_diam),
                       ("counterbore_depth", counterbore_depth),
                       ("total_depth", total_depth)]:
        fail = check_positive(name, val)
        if fail:
            return fail
    if float(counterbore_diam) <= float(bore_diam):
        return {
            "failure_type": "infeasible_countersink",
            "suggestion": (
                f"counterbore diameter ({counterbore_diam}mm) must exceed "
                f"the bore diameter ({bore_diam}mm); a counterbore narrower "
                f"than the bore has no recess to seat the fastener head"
            ),
            "details": {
                "counterbore_diam": float(counterbore_diam),
                "bore_diam": float(bore_diam),
            },
        }
    if float(counterbore_depth) >= float(total_depth):
        return {
            "failure_type": "infeasible_countersink",
            "suggestion": (
                f"counterbore depth ({counterbore_depth}mm) must be less than "
                f"total depth ({total_depth}mm); the through-bore needs at "
                f"least some material below the counterbore"
            ),
            "details": {
                "counterbore_depth": float(counterbore_depth),
                "total_depth": float(total_depth),
            },
        }
    return None
