"""SSVEP detectors built on SSVEPAnalysisToolbox (pip: SSVEPAnalysisToolbox 0.0.5).

Toolbox: Z. Wang et al., https://github.com/pikipity/SSVEP-Analysis-Toolbox
Install into a conda env with setup_ssvep_toolbox.py (it also patches two
numpy incompatibilities of the toolbox).

Only the toolbox's training-free methods are wrapped, because they work on a
single streamed window with nothing but sine/cosine references:
    ToolboxCcaDetector    standard CCA            (Lin et al., 2006)
    ToolboxFbccaDetector  filter-bank CCA         (Chen et al., 2015)
    ToolboxOaccaDetector  online adaptive CCA     (Wong et al., 2021); it keeps
                          learning spatial filters from the windows it sees
The training-based methods (itCCA, eCCA, MsetCCA, MSCCA, TRCA, eTRCA, TDCA, ...)
need labelled calibration trials per stimulus and are therefore not wrapped.

Scores: CCA = rho; FBCCA = sum_n w(n) * rho_n^2 (Chen 2015, Lee 2023 eq. 4; the
toolbox itself ranks by sum_n w(n) * rho_n, which can pick a different winner);
OACCA = the toolbox's weighted sum of its three correlation terms.
"""

from abc import abstractmethod
from dataclasses import dataclass
from typing import Dict, List

import numpy as np
from SSVEPAnalysisToolbox.algorithms import OACCA, SCCA_qr
from SSVEPAnalysisToolbox.algorithms.basemodel import BaseModel
from SSVEPAnalysisToolbox.utils.algsupport import gen_ref_sin
from SSVEPAnalysisToolbox.utils.benchmarkpreprocess import (filterbank,
                                                           suggested_weights_filterbank)

from ssvep_detection import SsvepDetector

DEFAULT_NUM_HARMONICS = 5  # as in Lee et al. 2023 and the toolbox's Benchmark demos
DEFAULT_NUM_SUB_BANDS = 5
SUB_BAND_STEP_HZ = 8.0     # toolbox filter bank: band n passes 8n .. 90 Hz
SUB_BAND_UPPER_EDGE_HZ = 90.0


@dataclass(frozen=True)
class _SamplingInfo:
    """The toolbox filter bank reads the sampling rate from a dataset object's `srate`."""

    srate: float


class ToolboxDetector(SsvepDetector):
    """Adapter: a toolbox model behind the SsvepDetector interface.

    Toolbox models need reference signals as long as the window, so one fitted
    model is kept per window length.
    """

    def __init__(self, frequencies_hz, sampling_rate_hz, num_harmonics: int = DEFAULT_NUM_HARMONICS):
        super().__init__(frequencies_hz, sampling_rate_hz)
        self.num_harmonics = num_harmonics
        self._validate_harmonics()
        self._models: Dict[int, BaseModel] = {}

    # --- SsvepDetector interface -------------------------------------------

    def score_frequency(self, eeg_window: np.ndarray, frequency_hz: float) -> float:
        return self.score_frequencies(eeg_window)[frequency_hz]

    def score_frequencies(self, eeg_window: np.ndarray) -> Dict[float, float]:
        self._validate_window(eeg_window)
        model = self._model_for(eeg_window.shape[1])
        _, correlations = model.predict([self._sub_bands(eeg_window)])
        scores = self._combine_sub_bands(np.asarray(correlations[0]))
        return dict(zip(self.frequencies_hz, (float(s) for s in scores)))

    # --- Extension points ---------------------------------------------------

    @abstractmethod
    def _new_model(self) -> BaseModel:
        """An unfitted toolbox model."""

    @abstractmethod
    def _sub_bands(self, eeg_window: np.ndarray) -> np.ndarray:
        """Window as the toolbox expects it: (n_sub_bands, n_channels, n_samples)."""

    @abstractmethod
    def _combine_sub_bands(self, correlations: np.ndarray) -> np.ndarray:
        """(n_sub_bands, n_frequencies) correlations -> one score per frequency."""

    # --- Internals ----------------------------------------------------------

    def _model_for(self, n_samples: int) -> BaseModel:
        if n_samples not in self._models:
            model = self._new_model()
            model.fit(ref_sig=self._reference_signals(n_samples))
            self._models[n_samples] = model
        return self._models[n_samples]

    def _reference_signals(self, n_samples: int) -> List[np.ndarray]:
        return [gen_ref_sin(f, self.sampling_rate_hz, n_samples, self.num_harmonics, 0)
                for f in self.frequencies_hz]

    def _validate_harmonics(self) -> None:
        if self.num_harmonics < 1:
            raise ValueError("num_harmonics must be at least 1.")
        highest_harmonic_hz = self.num_harmonics * max(self.frequencies_hz)
        if highest_harmonic_hz >= self.sampling_rate_hz / 2:
            raise ValueError(
                f"Harmonic at {highest_harmonic_hz:.1f} Hz is not below the Nyquist "
                f"frequency ({self.sampling_rate_hz / 2:.1f} Hz); reduce num_harmonics.")


class ToolboxCcaDetector(ToolboxDetector):
    """Standard CCA: the largest canonical correlation with each frequency's references."""

    def _new_model(self) -> BaseModel:
        return SCCA_qr()

    def _sub_bands(self, eeg_window: np.ndarray) -> np.ndarray:
        return eeg_window[np.newaxis]

    def _combine_sub_bands(self, correlations: np.ndarray) -> np.ndarray:
        return correlations[0]


class ToolboxFbccaDetector(ToolboxDetector):
    """FBCCA with the toolbox's Chebyshev type I filter bank and weights n^-1.25 + 0.25."""

    def __init__(self, frequencies_hz, sampling_rate_hz,
                 num_harmonics: int = DEFAULT_NUM_HARMONICS,
                 num_sub_bands: int = DEFAULT_NUM_SUB_BANDS):
        super().__init__(frequencies_hz, sampling_rate_hz, num_harmonics)
        self.num_sub_bands = num_sub_bands
        self._validate_sub_bands()
        self._weights = np.asarray(suggested_weights_filterbank(num_sub_bands))

    def _new_model(self) -> BaseModel:
        return SCCA_qr(weights_filterbank=list(self._weights))

    def _sub_bands(self, eeg_window: np.ndarray) -> np.ndarray:
        return filterbank(_SamplingInfo(self.sampling_rate_hz), eeg_window, self.num_sub_bands)

    def _combine_sub_bands(self, correlations: np.ndarray) -> np.ndarray:
        return self._weights @ correlations ** 2

    def _validate_sub_bands(self) -> None:
        if self.num_sub_bands < 1:
            raise ValueError("num_sub_bands must be at least 1.")
        if SUB_BAND_STEP_HZ * self.num_sub_bands >= SUB_BAND_UPPER_EDGE_HZ:
            raise ValueError(f"At most {int(SUB_BAND_UPPER_EDGE_HZ // SUB_BAND_STEP_HZ) - 1} "
                             f"sub-bands fit below {SUB_BAND_UPPER_EDGE_HZ:.0f} Hz.")
        if self.sampling_rate_hz / 2 <= SUB_BAND_UPPER_EDGE_HZ:
            raise ValueError("The toolbox filter bank needs a sampling rate above 180 Hz.")


class ToolboxOaccaDetector(ToolboxFbccaDetector):
    """Online adaptive CCA on the FBCCA filter bank.

    Stateful: every window updates its spatial filters, so the detector should
    be reused across the whole session (and recreated for a new one).
    """

    def _new_model(self) -> BaseModel:
        return OACCA(weights_filterbank=list(self._weights))

    def _combine_sub_bands(self, correlations: np.ndarray) -> np.ndarray:
        return self._weights @ correlations
