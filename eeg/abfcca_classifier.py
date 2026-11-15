"""ANCOVA-based adaptive window SSVEP classification (ABFCCA).

Method: T. Lee, S. Nam, D. J. Hyun, "Adaptive Window Method Based on FBCCA for
Optimal SSVEP Recognition", IEEE TNSRE 31 (2023), Section II-C, Algorithm 1.

The window grows from t0 (stimulus onset + 140 ms visual latency) in steps of
t_step. At every step the FBCCA scores of all stimulus frequencies are
softmax-normalised and stacked over time. Once the window reaches t_min, an
ANCOVA tests whether the features' regression lines over time have different
slopes; if they do, pairwise slope comparisons check whether the steepest slope
is significantly steeper than every other. If so (or when t_max is reached),
the stimulus with the largest current feature is the decision.

Numbered steps of the paper -> functions here:
    1  window_until_step            window from t0 to t = t0 + k * t_step
    2  normalized_features          FBCCA features, softmax-normalised (eq. 6)
       (stacking over time: AbfccaClassifier._feature_history)
    3  reached_maximum_window
    4  reached_minimum_window
    5  ancova_interaction_p_value   ANCOVA: frequency x time interaction
    6  pairwise_slope_p_values      multiple comparison of slopes (Tukey-Kramer,
                                    like MATLAB multcompare's default)
    7  steepest_slope_is_significant
    8  classify                     argmax of the current normalised features
`decide` chains steps 3-8 for one time step; AbfccaClassifier runs the loop
over time steps on streamed or recorded EEG.

Practical deviations from the paper:
  - Features start at a window of `first_feature_window_s` (default 0.2 s): the
    filter bank cannot filter shorter windows.
  - Defaults match the paper (t_min 0.5 s, t_max 4 s, t_step 50 ms, alpha 0.05,
    FBCCA with 5 sub-bands and 5 harmonics via ToolboxFbccaDetector).
"""

from dataclasses import dataclass
from itertools import combinations
from typing import List, Optional, Sequence, Tuple

import numpy as np
import statsmodels.api as sm
from scipy.stats import studentized_range

from ssvep_detection import SsvepDetector


@dataclass(frozen=True)
class AbfccaConfig:
    min_window_s: float = 0.5          # t_min
    max_window_s: float = 4.0          # t_max
    step_s: float = 0.05               # t_step
    alpha: float = 0.05                # significance level
    visual_latency_s: float = 0.14     # t0 = stimulus onset + this
    first_feature_window_s: float = 0.2


@dataclass(frozen=True)
class AdaptiveDecision:
    frequency_hz: float
    window_length_s: float             # measured from t0
    reason: str                        # "slope test" or "maximum window"
    features: Tuple[float, ...]        # normalised features at the decision


# --- Step 1: the growing window ----------------------------------------------


def window_length_s(step_index: int, config: AbfccaConfig) -> float:
    return step_index * config.step_s


def window_until_step(eeg_from_t0: np.ndarray, step_index: int, config: AbfccaConfig,
                      sampling_rate_hz: float) -> np.ndarray:
    """EEG from t0 to t = t0 + step_index * t_step; shape (n_channels, n_samples)."""
    n_samples = int(round(window_length_s(step_index, config) * sampling_rate_hz))
    return eeg_from_t0[:, :n_samples]


# --- Step 2: normalised features ---------------------------------------------


def softmax(values: np.ndarray) -> np.ndarray:
    shifted = np.exp(values - values.max())
    return shifted / shifted.sum()


def normalized_features(detector: SsvepDetector, window: np.ndarray) -> np.ndarray:
    """Softmax of the detector's score for every stimulus frequency (paper eq. 6)."""
    scores = detector.score_frequencies(window)
    return softmax(np.array([scores[f] for f in detector.frequencies_hz]))


# --- Steps 3 and 4: window limits --------------------------------------------


def reached_maximum_window(length_s: float, config: AbfccaConfig) -> bool:
    return length_s >= config.max_window_s - 1e-9


def reached_minimum_window(length_s: float, config: AbfccaConfig) -> bool:
    return length_s >= config.min_window_s - 1e-9


# --- Steps 5 and 6: ANCOVA and slope comparisons -----------------------------


def _long_format(times_s: np.ndarray, features: np.ndarray):
    """Stacked features (n_times, n_groups) -> response, time and group per row."""
    n_times, n_groups = features.shape
    return (features.ravel(),
            np.repeat(times_s, n_groups),
            np.tile(np.arange(n_groups), n_times))


def _separate_lines_model(times_s: np.ndarray, features: np.ndarray):
    """OLS with its own intercept and slope per group; slope of group g is param n_groups + g."""
    response, time, group = _long_format(times_s, features)
    indicators = np.eye(features.shape[1])[group]
    design = np.hstack([indicators, indicators * time[:, None]])
    return sm.OLS(response, design).fit()


def _parallel_lines_model(times_s: np.ndarray, features: np.ndarray):
    """OLS with its own intercept per group and one common slope."""
    response, time, group = _long_format(times_s, features)
    design = np.hstack([np.eye(features.shape[1])[group], time[:, None]])
    return sm.OLS(response, design).fit()


def ancova_interaction_p_value(times_s: np.ndarray, features: np.ndarray) -> float:
    """p-value of the frequency x time interaction, i.e. of 'the slopes differ'."""
    separate = _separate_lines_model(times_s, features)
    parallel = _parallel_lines_model(times_s, features)
    _, p_value, _ = separate.compare_f_test(parallel)
    return float(p_value)


def pairwise_slope_p_values(times_s: np.ndarray,
                            features: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Slope per frequency and Tukey-Kramer p-values for every pair of slopes.

    Returns (slopes (n_groups,), p_values (n_groups, n_groups), diagonal = 1).
    """
    n_groups = features.shape[1]
    model = _separate_lines_model(times_s, features)
    slopes = model.params[n_groups:]
    covariance = model.cov_params()[n_groups:, n_groups:]
    p_values = np.ones((n_groups, n_groups))
    for i, j in combinations(range(n_groups), 2):
        standard_error = np.sqrt(covariance[i, i] + covariance[j, j] - 2 * covariance[i, j])
        q = abs(slopes[i] - slopes[j]) / standard_error * np.sqrt(2)
        p_values[i, j] = p_values[j, i] = studentized_range.sf(q, n_groups, model.df_resid)
    return slopes, p_values


# --- Steps 7 and 8: decision -------------------------------------------------


def steepest_slope_is_significant(slopes: np.ndarray, p_values: np.ndarray,
                                  alpha: float) -> bool:
    """True if the steepest slope differs significantly from every other slope."""
    steepest = int(np.argmax(slopes))
    others = [g for g in range(len(slopes)) if g != steepest]
    return all(p_values[steepest, g] <= alpha for g in others)


def classify(latest_features: np.ndarray, frequencies_hz: Sequence[float]) -> float:
    return frequencies_hz[int(np.argmax(latest_features))]


def decide(times_s: np.ndarray, features: np.ndarray, length_s: float,
           frequencies_hz: Sequence[float], config: AbfccaConfig) -> Optional[AdaptiveDecision]:
    """Steps 3-8 for the current time step; None means 'collect more data'."""
    latest = features[-1]
    if reached_maximum_window(length_s, config):
        return AdaptiveDecision(classify(latest, frequencies_hz), length_s, "maximum window",
                                tuple(latest))
    if not reached_minimum_window(length_s, config):
        return None
    if ancova_interaction_p_value(times_s, features) >= config.alpha:
        return None
    slopes, p_values = pairwise_slope_p_values(times_s, features)
    if not steepest_slope_is_significant(slopes, p_values, config.alpha):
        return None
    return AdaptiveDecision(classify(latest, frequencies_hz), length_s, "slope test",
                            tuple(latest))


# --- The loop over time steps ------------------------------------------------


class AbfccaClassifier:
    """Runs Algorithm 1 on the EEG of one trial, as it arrives.

    Call `update(trial_number, eeg_from_t0)` whenever more EEG of the trial is
    available (eeg_from_t0 always starts at t0). It processes every newly
    completed time step and returns the decision once made, else None. A new
    trial_number starts a new trial; after a decision the trial is ignored.
    `classify_trial` does the same for a complete recorded trial.
    """

    def __init__(self, detector: SsvepDetector, config: AbfccaConfig = AbfccaConfig()):
        self.detector = detector
        self.config = config
        self._trial_number = None
        self._next_step = 0
        self._window_lengths: List[float] = []
        self._feature_history: List[np.ndarray] = []
        self._decided = False

    def classify_trial(self, eeg_from_t0: np.ndarray) -> Optional[AdaptiveDecision]:
        """Decision for a complete trial; None only if it is shorter than t_max and undecided."""
        self._start_trial(trial_number=None)
        return self.update(None, eeg_from_t0)

    def update(self, trial_number, eeg_from_t0: np.ndarray) -> Optional[AdaptiveDecision]:
        if trial_number != self._trial_number:
            self._start_trial(trial_number)
        if self._decided:
            return None
        while self._step_is_available(eeg_from_t0.shape[1]):
            decision = self._process_step(eeg_from_t0)
            if decision is not None:
                self._decided = True
                return decision
        return None

    # --- Internals ----------------------------------------------------------

    def _start_trial(self, trial_number) -> None:
        self._trial_number = trial_number
        self._next_step = self._first_feature_step()
        self._window_lengths.clear()
        self._feature_history.clear()
        self._decided = False

    def _first_feature_step(self) -> int:
        return int(np.ceil(self.config.first_feature_window_s / self.config.step_s - 1e-9))

    def _step_is_available(self, n_available_samples: int) -> bool:
        needed_s = window_length_s(self._next_step, self.config)
        return needed_s * self.detector.sampling_rate_hz <= n_available_samples + 1e-9

    def _process_step(self, eeg_from_t0: np.ndarray) -> Optional[AdaptiveDecision]:
        step = self._next_step
        self._next_step += 1
        length_s = window_length_s(step, self.config)
        window = window_until_step(eeg_from_t0, step, self.config, self.detector.sampling_rate_hz)
        self._window_lengths.append(length_s)
        self._feature_history.append(normalized_features(self.detector, window))
        return decide(np.array(self._window_lengths), np.vstack(self._feature_history),
                      length_s, self.detector.frequencies_hz, self.config)
