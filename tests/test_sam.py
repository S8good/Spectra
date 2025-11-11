import pytest

from nanosense.algorithms import compute_sam_angle


def test_compute_sam_angle_matches_identical_vectors():
    ref_wl = [500, 510, 520]
    ref_vals = [1.0, 1.1, 1.2]
    sample_wl = [500, 510, 520]
    sample_vals = [1.0, 1.1, 1.2]
    angle = compute_sam_angle(ref_wl, ref_vals, sample_wl, sample_vals)
    assert angle is not None
    assert angle == pytest.approx(0.0, abs=1e-6)


def test_compute_sam_angle_handles_non_overlapping_ranges():
    ref_wl = [500, 510, 520]
    ref_vals = [1.0, 1.1, 1.2]
    sample_wl = [600, 610, 620]
    sample_vals = [0.9, 1.0, 1.1]
    angle = compute_sam_angle(ref_wl, ref_vals, sample_wl, sample_vals)
    assert angle is None
