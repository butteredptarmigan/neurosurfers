"""Registry of SSVEP detection methods, selectable by name (e.g. from the command line).

DETECTORS          fixed-window detectors: one decision per window
ADAPTIVE_METHODS   adaptive-window classifiers (Lee et al. 2023): the window grows
                   from trial onset until a statistical test separates the target;
                   each name maps to the fixed-window detector supplying its features
"""

from typing import Callable, Dict, Sequence

from abfcca_classifier import AbfccaClassifier
from fbcca_detector import FbccaDetector
from ssvep_detection import SsvepDetector
from ssvep_toolbox_detectors import (ToolboxCcaDetector, ToolboxFbccaDetector,
                                     ToolboxOaccaDetector)

DetectorFactory = Callable[[Sequence[float], float], SsvepDetector]

DETECTORS: Dict[str, DetectorFactory] = {
    "fbcca": FbccaDetector,
    "toolbox-cca": ToolboxCcaDetector,
    "toolbox-fbcca": ToolboxFbccaDetector,
    "toolbox-oacca": ToolboxOaccaDetector,
}
ADAPTIVE_METHODS: Dict[str, str] = {
    "abfcca": "toolbox-fbcca",
    "abcca": "toolbox-cca",
}
DEFAULT_METHOD = "fbcca"
ALL_METHODS = sorted(DETECTORS) + sorted(ADAPTIVE_METHODS)


def create_detector(method: str, frequencies_hz: Sequence[float],
                    sampling_rate_hz: float) -> SsvepDetector:
    if method not in DETECTORS:
        raise ValueError(f"Unknown SSVEP method '{method}'. Choose one of {sorted(DETECTORS)}.")
    return DETECTORS[method](frequencies_hz, sampling_rate_hz)


def is_adaptive(method: str) -> bool:
    return method in ADAPTIVE_METHODS


def create_adaptive_classifier(method: str, frequencies_hz: Sequence[float],
                               sampling_rate_hz: float) -> AbfccaClassifier:
    if method not in ADAPTIVE_METHODS:
        raise ValueError(f"Unknown adaptive method '{method}'. "
                         f"Choose one of {sorted(ADAPTIVE_METHODS)}.")
    feature_detector = create_detector(ADAPTIVE_METHODS[method], frequencies_hz, sampling_rate_hz)
    return AbfccaClassifier(feature_detector)
