"""Unit tests for the pre-execution feasibility gate."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "addon" / "conjur3_pilot" / "rpc_server"),
)

from feasibility import (  # noqa: E402
    check_chamfer_size,
    check_countersink_geometry,
    check_fillet_radius,
    check_gear_undercut,
    check_pocket_depth,
    check_positive,
)


# ---------------------------------------------------------------------------
# check_positive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("v", [1, 1.0, 0.001, 1e6])
def test_positive_passes_positive_values(v):
    assert check_positive("radius", v) is None


@pytest.mark.parametrize("v", [0, 0.0, -1, -0.001])
def test_positive_rejects_zero_and_negative(v):
    fail = check_positive("radius", v)
    assert fail is not None
    assert fail["failure_type"] == "non_positive_parameter"
    assert fail["details"]["parameter"] == "radius"


def test_positive_rejects_non_numeric():
    fail = check_positive("radius", "not a number")
    assert fail is not None
    assert fail["failure_type"] == "invalid_parameter"


# ---------------------------------------------------------------------------
# check_fillet_radius
# ---------------------------------------------------------------------------


def test_fillet_passes_when_radius_is_under_half_edge():
    assert check_fillet_radius(2.0, 10.0) is None
    assert check_fillet_radius(4.99, 10.0) is None
    assert check_fillet_radius(5.0, 10.0) is None  # exactly half is allowed


def test_fillet_rejects_radius_over_half_edge():
    fail = check_fillet_radius(5.01, 10.0)
    assert fail is not None
    assert fail["failure_type"] == "infeasible_fillet"
    assert fail["details"]["max_allowed_radius"] == 5.0
    assert "5.000mm" in fail["suggestion"] or "5.0mm" in fail["suggestion"]


def test_fillet_rejects_non_positive_radius():
    fail = check_fillet_radius(0, 10.0)
    assert fail["failure_type"] == "non_positive_parameter"


def test_fillet_rejects_zero_length_edge():
    fail = check_fillet_radius(1.0, 0)
    assert fail["failure_type"] == "degenerate_edge"


# ---------------------------------------------------------------------------
# check_chamfer_size
# ---------------------------------------------------------------------------


def test_chamfer_passes_when_size_is_under_half_edge():
    assert check_chamfer_size(1.5, 4.0) is None


def test_chamfer_rejects_size_over_half_edge():
    fail = check_chamfer_size(2.5, 4.0)
    assert fail["failure_type"] == "infeasible_chamfer"
    assert fail["details"]["max_allowed_size"] == 2.0


# ---------------------------------------------------------------------------
# check_pocket_depth
# ---------------------------------------------------------------------------


def test_pocket_passes_within_body_extent():
    assert check_pocket_depth(5.0, body_extent_along_normal=10.0) is None


def test_pocket_passes_when_extent_unknown():
    """If the body extent isn't supplied, only the positive-depth check applies."""
    assert check_pocket_depth(5.0, body_extent_along_normal=None) is None


def test_pocket_rejects_non_positive_depth():
    fail = check_pocket_depth(0.0)
    assert fail["failure_type"] == "non_positive_parameter"


def test_pocket_rejects_depth_exceeding_body_extent():
    fail = check_pocket_depth(15.0, body_extent_along_normal=10.0)
    assert fail["failure_type"] == "pocket_exceeds_body"
    assert "pocket_through" in fail["suggestion"]


# ---------------------------------------------------------------------------
# check_gear_undercut
# ---------------------------------------------------------------------------


def test_gear_passes_above_safe_minimum():
    # At 20° pressure angle, theoretical min ≈ 17, safe = 19
    assert check_gear_undercut(teeth=20, pressure_angle_deg=20.0) is None
    assert check_gear_undercut(teeth=30, pressure_angle_deg=20.0) is None


def test_gear_rejects_below_safe_minimum_at_20_deg():
    """At 20° PA: 2/sin²(20°) ≈ 17.097 → ceil = 18 → +2 safety = 20."""
    fail = check_gear_undercut(teeth=12, pressure_angle_deg=20.0)
    assert fail["failure_type"] == "gear_undercut"
    assert fail["details"]["min_safe_teeth"] == 20
    assert fail["details"]["theoretical_min_teeth"] == 18


def test_gear_check_offers_pressure_angle_alternative():
    """Suggestion text helps the agent revise — should mention 25° escape hatch."""
    fail = check_gear_undercut(teeth=12, pressure_angle_deg=20.0)
    assert "25°" in fail["suggestion"] or "pressure angle" in fail["suggestion"].lower()


def test_gear_passes_when_pressure_angle_raised():
    """Raising PA from 14.5° to 25° lowers the safe minimum substantially."""
    # 14.5° PA needs ~32 teeth; 25° PA needs ~13
    assert check_gear_undercut(teeth=20, pressure_angle_deg=14.5) is not None
    assert check_gear_undercut(teeth=20, pressure_angle_deg=25.0) is None


def test_gear_rejects_invalid_pressure_angle():
    assert check_gear_undercut(teeth=20, pressure_angle_deg=0)["failure_type"] == "invalid_pressure_angle"
    assert check_gear_undercut(teeth=20, pressure_angle_deg=-5)["failure_type"] == "invalid_pressure_angle"
    assert check_gear_undercut(teeth=20, pressure_angle_deg=90)["failure_type"] == "invalid_pressure_angle"


def test_gear_rejects_non_positive_teeth():
    fail = check_gear_undercut(teeth=0, pressure_angle_deg=20.0)
    assert fail["failure_type"] == "non_positive_parameter"


def test_gear_skips_when_teeth_unknown():
    """If teeth isn't supplied, the check is a no-op (don't block on missing info)."""
    assert check_gear_undercut(teeth=None, pressure_angle_deg=20.0) is None


# ---------------------------------------------------------------------------
# check_countersink_geometry
# ---------------------------------------------------------------------------


def test_countersink_passes_well_formed():
    assert check_countersink_geometry(
        counterbore_diam=10.0, bore_diam=5.0,
        counterbore_depth=3.0, total_depth=12.0,
    ) is None


def test_countersink_rejects_counterbore_narrower_than_bore():
    fail = check_countersink_geometry(
        counterbore_diam=4.0, bore_diam=5.0,
        counterbore_depth=3.0, total_depth=12.0,
    )
    assert fail["failure_type"] == "infeasible_countersink"
    assert "narrower" in fail["suggestion"]


def test_countersink_rejects_counterbore_full_depth():
    fail = check_countersink_geometry(
        counterbore_diam=10.0, bore_diam=5.0,
        counterbore_depth=12.0, total_depth=12.0,
    )
    assert fail["failure_type"] == "infeasible_countersink"


def test_countersink_rejects_negative_dimensions():
    fail = check_countersink_geometry(
        counterbore_diam=-1, bore_diam=5.0,
        counterbore_depth=3.0, total_depth=12.0,
    )
    assert fail["failure_type"] == "non_positive_parameter"
