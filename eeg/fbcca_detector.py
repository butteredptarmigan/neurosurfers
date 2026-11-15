"""Filter-bank canonical correlation analysis (FBCCA) SSVEP detector.

Method: Chen et al., "Filter bank canonical correlation analysis for implementing
a high-speed SSVEP-based brain-computer interface", J. Neural Eng. 12 (2015).
Structure and default parameters follow the FBCCA reference implementation in
https://github.com/eugeneALU/CECNL_RealTimeBCI (fbcca.py).

For each candidate frequency:
  1. The EEG window is split into sub-bands (band k passes k*8 Hz .. 90 Hz), so
     that harmonics of the stimulus frequency are weighed separately.
  2. In each sub-band, the first canonical correlation rho_k is computed between
     the EEG and sine/cosine references at the fundamental and its harmonics.
  3. The score is sum_k w_k * rho_k^2, with w_k = k^-a + b.
"""

from typing import Dict, List, Sequence

import numpy as np
from scipy.linalg import orth
from scipy.signal import butter, sosfiltfilt

from ssvep_detection import SsvepDetector

SUB_BAND_STEP_HZ = 8.0
SUB_BAND_UPPER_EDGE_HZ = 90.0
FILTER_ORDER = 4


# --- Pure signal-processing helpers ----------------------------------------


def reference_signals(frequency_hz: float, n_samples: int, sampling_rate_hz: float,
                      num_harmonics: int) -> np.ndarray:
    """Sine and cosine references of the fundamental and its harmonics.

    Returns shape (2 * num_harmonics, n_samples).
    """
    time_s = np.arange(n_samples) / sampling_rate_hz
    rows = []
    for harmonic in range(1, num_harmonics + 1):
        phase = 2 * np.pi * harmonic * frequency_hz * time_s
        rows.extend([np.sin(phase), np.cos(phase)])
    return np.array(rows)


def first_canonical_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """Largest canonical correlation between x (n_features, n_samples) and y."""
    x_basis = orth(x.T - x.T.mean(axis=0))
    y_basis = orth(y.T - y.T.mean(axis=0))
    if x_basis.size == 0 or y_basis.size == 0:
        return 0.0
    correlation = np.linalg.svd(x_basis.T @ y_basis, compute_uv=False)[0]
    return float(min(correlation, 1.0))


def sub_band_weights(num_sub_bands: int, exponent: float, offset: float) -> np.ndarray:
    return np.arange(1, num_sub_bands + 1, dtype=float) ** (-exponent) + offset


# --- Detector --------------------------------------------------------------


class FbccaDetector(SsvepDetector):
    """SSVEP detector using filter-bank CCA with sine/cosine harmonic references."""

    def __init__(self, frequencies_hz: Sequence[float], sampling_rate_hz: float,
                 num_harmonics: int = 3, num_sub_bands: int = 5,
                 weight_exponent: float = 1.25, weight_offset: float = 0.25):
        super().__init__(frequencies_hz, sampling_rate_hz)
        self.num_harmonics = num_harmonics
        self.num_sub_bands = num_sub_bands
        self._weights = sub_band_weights(num_sub_bands, weight_exponent, weight_offset)
        self._validate_fbcca_configuration()
        self._band_filters = self._design_band_filters()

    # --- SsvepDetector interface -------------------------------------------

    def score_frequency(self, eeg_window: np.ndarray, frequency_hz: float) -> float:
        return self._weighted_correlation(self._filter_bank(eeg_window), frequency_hz)

    def score_frequencies(self, eeg_window: np.ndarray) -> Dict[float, float]:
        """Filters the window once and shares the sub-bands between all frequencies."""
        self._validate_window(eeg_window)
        sub_bands = self._filter_bank(eeg_window)
        return {f: self._weighted_correlation(sub_bands, f) for f in self.frequencies_hz}

    # --- Internals ----------------------------------------------------------

    def _filter_bank(self, eeg_window: np.ndarray) -> List[np.ndarray]:
        return [sosfiltfilt(band_filter, eeg_window, axis=1) for band_filter in self._band_filters]

    def _weighted_correlation(self, sub_bands: List[np.ndarray], frequency_hz: float) -> float:
        n_samples = sub_bands[0].shape[1]
        references = reference_signals(
            frequency_hz, n_samples, self.sampling_rate_hz, self.num_harmonics)
        correlations = np.array(
            [first_canonical_correlation(band, references) for band in sub_bands])
        return float(np.sum(self._weights * correlations ** 2))

    def _design_band_filters(self) -> List[np.ndarray]:
        return [
            butter(FILTER_ORDER, [self._lower_edge_hz(band), self._upper_edge_hz()],
                   btype="bandpass", fs=self.sampling_rate_hz, output="sos")
            for band in range(1, self.num_sub_bands + 1)
        ]

    @staticmethod
    def _lower_edge_hz(band_number: int) -> float:
        return band_number * SUB_BAND_STEP_HZ

    def _upper_edge_hz(self) -> float:
        return min(SUB_BAND_UPPER_EDGE_HZ, 0.9 * self.sampling_rate_hz / 2)

    def _validate_fbcca_configuration(self) -> None:
        if self.num_harmonics < 1 or self.num_sub_bands < 1:
            raise ValueError("num_harmonics and num_sub_bands must be at least 1.")
        highest_lower_edge = self._lower_edge_hz(self.num_sub_bands)
        if highest_lower_edge >= self._upper_edge_hz():
            raise ValueError(
                f"{self.num_sub_bands} sub-bands need a pass band starting at "
                f"{highest_lower_edge:.0f} Hz, above the usable upper edge "
                f"{self._upper_edge_hz():.0f} Hz at {self.sampling_rate_hz:.0f} Hz sampling."
            )
        highest_harmonic_hz = self.num_harmonics * max(self.frequencies_hz)
        if highest_harmonic_hz >= self.sampling_rate_hz / 2:
            raise ValueError(
                f"Harmonic at {highest_harmonic_hz:.1f} Hz is not below the Nyquist "
                f"frequency ({self.sampling_rate_hz / 2:.1f} Hz); reduce num_harmonics."
            )