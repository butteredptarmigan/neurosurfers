"""SSVEP detection: an extendable base class.

To try a new algorithm (CCA, FBCCA, PSD ratio, ...), subclass `SsvepDetector`
and implement `score_frequency`. Everything else (input validation, scoring all
candidate frequencies, picking the most probable one) is inherited, so different
algorithms can be compared through the same interface:

    detectors = [FbccaDetector(freqs, fs), ToolboxCcaDetector(freqs, fs)]
    results = {type(d).__name__: d.detect(eeg_window) for d in detectors}

Implementations: fbcca_detector.py (own FBCCA), ssvep_toolbox_detectors.py
(SSVEPAnalysisToolbox); ssvep_methods.py selects one by name.

EEG windows use the same layout as SignalEngine: shape (n_channels, n_samples).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Sequence

import numpy as np


@dataclass(frozen=True)
class DetectionResult:
    """Outcome of one detection: a score per candidate frequency and the winner."""

    scores: Dict[float, float]
    best_frequency_hz: float


class SsvepDetector(ABC):
    """Scores how strongly an EEG window contains SSVEP at each candidate frequency.

    A higher score means a more probable SSVEP response at that frequency.
    Scores only need to be comparable between frequencies of the same window.
    """

    def __init__(self, frequencies_hz: Sequence[float], sampling_rate_hz: float):
        self._validate_configuration(frequencies_hz, sampling_rate_hz)
        self.frequencies_hz = tuple(float(f) for f in frequencies_hz)
        self.sampling_rate_hz = float(sampling_rate_hz)

    # --- Extension point ---------------------------------------------------

    @abstractmethod
    def score_frequency(self, eeg_window: np.ndarray, frequency_hz: float) -> float:
        """Score for one candidate frequency. `eeg_window` is (n_channels, n_samples)."""

    # --- Public interface --------------------------------------------------

    def score_frequencies(self, eeg_window: np.ndarray) -> Dict[float, float]:
        """Score for every candidate frequency.

        Override this instead of `score_frequency` when the algorithm computes
        all frequencies jointly (e.g. one FFT shared by all of them).
        """
        self._validate_window(eeg_window)
        return {f: self.score_frequency(eeg_window, f) for f in self.frequencies_hz}

    def most_probable_frequency(self, eeg_window: np.ndarray) -> float:
        scores = self.score_frequencies(eeg_window)
        return max(scores, key=scores.get)

    def detect(self, eeg_window: np.ndarray) -> DetectionResult:
        scores = self.score_frequencies(eeg_window)
        return DetectionResult(scores=scores, best_frequency_hz=max(scores, key=scores.get))

    # --- Validation --------------------------------------------------------

    @staticmethod
    def _validate_configuration(frequencies_hz: Sequence[float], sampling_rate_hz: float) -> None:
        if len(frequencies_hz) == 0:
            raise ValueError("At least one candidate frequency is required.")
        if any(f <= 0 for f in frequencies_hz):
            raise ValueError(f"Frequencies must be positive, got {list(frequencies_hz)}.")
        if len(set(frequencies_hz)) != len(frequencies_hz):
            raise ValueError(f"Frequencies must be unique, got {list(frequencies_hz)}.")
        if sampling_rate_hz <= 0:
            raise ValueError(f"Sampling rate must be positive, got {sampling_rate_hz}.")
        nyquist_hz = sampling_rate_hz / 2
        too_fast = [f for f in frequencies_hz if f >= nyquist_hz]
        if too_fast:
            raise ValueError(
                f"Frequencies {too_fast} Hz are not below the Nyquist frequency "
                f"({nyquist_hz:.1f} Hz) of a {sampling_rate_hz:.1f} Hz recording."
            )

    @staticmethod
    def _validate_window(eeg_window: np.ndarray) -> None:
        if eeg_window.ndim != 2:
            raise ValueError(
                f"EEG window must be 2-D (n_channels, n_samples), got shape {eeg_window.shape}."
            )
        if eeg_window.shape[0] == 0 or eeg_window.shape[1] == 0:
            raise ValueError(f"EEG window must not be empty, got shape {eeg_window.shape}.")
