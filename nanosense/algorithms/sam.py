"""Spectral Angle Mapper utilities."""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

import numpy as np


def _sanitize_pair(
    wavelengths: Sequence[float], intensities: Sequence[float]
) -> Tuple[np.ndarray, np.ndarray]:
    wl = np.asarray(wavelengths, dtype=float)
    intens = np.asarray(intensities, dtype=float)
    if wl.ndim != 1 or intens.ndim != 1:
        raise ValueError("Spectrum arrays must be one-dimensional.")
    if wl.size != intens.size:
        raise ValueError("Wavelength and intensity arrays must have the same length.")
    paired = np.column_stack([wl, intens])
    mask = np.isfinite(paired[:, 0]) & np.isfinite(paired[:, 1])
    paired = paired[mask]
    if paired.shape[0] < 2:
        raise ValueError("Spectrum must contain at least two finite pairs.")
    order = np.argsort(paired[:, 0])
    paired = paired[order]
    return paired[:, 0], paired[:, 1]


def _interpolate_to_target(
    target_wavelengths: np.ndarray,
    source_wavelengths: np.ndarray,
    source_values: np.ndarray,
) -> np.ndarray:
    mask = (target_wavelengths >= source_wavelengths[0]) & (
        target_wavelengths <= source_wavelengths[-1]
    )
    if not np.any(mask):
        raise ValueError("Wavelength ranges do not overlap.")
    interpolated = np.interp(
        target_wavelengths[mask], source_wavelengths, source_values
    )
    result = np.full_like(target_wavelengths, np.nan, dtype=float)
    result[mask] = interpolated
    return result


def compute_sam_angle(
    reference_wavelengths: Sequence[float],
    reference_values: Sequence[float],
    sample_wavelengths: Sequence[float],
    sample_values: Sequence[float],
    *,
    points: Optional[int] = None,
) -> Optional[float]:
    """
    Compute the spectral angle (in degrees) between a reference and a sample.

    Args:
        reference_wavelengths: Wavelength axis of the reference spectrum.
        reference_values: Intensity values of the reference spectrum.
        sample_wavelengths: Wavelength axis of the sample spectrum.
        sample_values: Intensity values of the sample spectrum.
        points: Optional number of interpolation points. Defaults to the smaller
            length of the two spectra.

    Returns:
        float angle in degrees, or None if the spectra cannot be compared.
    """

    try:
        ref_wl, ref_vals = _sanitize_pair(reference_wavelengths, reference_values)
        sample_wl, sample_vals = _sanitize_pair(sample_wavelengths, sample_values)
    except ValueError:
        return None

    overlap_min = max(ref_wl[0], sample_wl[0])
    overlap_max = min(ref_wl[-1], sample_wl[-1])
    if overlap_max <= overlap_min:
        return None

    target_points = points or min(ref_wl.size, sample_wl.size)
    target = np.linspace(overlap_min, overlap_max, target_points)
    ref_interp = _interpolate_to_target(target, ref_wl, ref_vals)
    sample_interp = _interpolate_to_target(target, sample_wl, sample_vals)

    mask = np.isfinite(ref_interp) & np.isfinite(sample_interp)
    ref_vec = ref_interp[mask]
    sample_vec = sample_interp[mask]
    if ref_vec.size < 2 or sample_vec.size < 2:
        return None

    ref_norm = np.linalg.norm(ref_vec)
    sample_norm = np.linalg.norm(sample_vec)
    if ref_norm == 0 or sample_norm == 0:
        return None

    cosine = np.clip(np.dot(ref_vec, sample_vec) / (ref_norm * sample_norm), -1.0, 1.0)
    angle_rad = np.arccos(cosine)
    return float(np.degrees(angle_rad))


__all__ = ["compute_sam_angle"]
