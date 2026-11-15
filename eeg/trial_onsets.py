"""Where adaptive-window trials start in a live SignalEngine stream.

An onset source tells the adaptive classifier (abfcca_classifier.py) which EEG
belongs to the current trial: everything from t0 = onset + visual latency on.

    SelfRestartingOnsets  asynchronous use, no stimulus markers needed: the first
                          trial starts when streaming starts, every next one
                          right where the previous decision was made
    LslMarkerOnsets       a trial starts at each `trial_start` marker of the
                          stimulus program (integration test v1/sync_test_stimuli.py
                          publishes them on the SSVEPStimulusMarkers LSL stream)

Both expose:
    trial_eeg(engine)            call while holding engine.lock; the current trial's
                                 EEG from t0 (all channels), or None between trials
    finish_trial(window_length_s) call after a decision
"""

import bisect
import json
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import numpy as np
from pylsl import StreamInlet, proc_clocksync, resolve_byprop

# Keep in sync with integration test v1/stimulus_lsl.py.
MARKER_STREAM_NAME = "SSVEPStimulusMarkers"
TRIAL_START_EVENT = "trial_start"
MARKER_WAIT_S = 60.0


@dataclass(frozen=True)
class TrialEeg:
    number: int
    eeg_from_t0: np.ndarray   # (n_channels, n_samples since t0); may have 0 samples


def eeg_since(engine, first_sample: int) -> np.ndarray:
    """Samples from absolute sample index `first_sample` up to now (engine.lock held)."""
    n_since = max(0, engine.n_received - first_sample)
    buffer_length = engine.data_buffer.shape[1]
    if n_since > buffer_length:
        raise RuntimeError(
            f"The trial started {n_since} samples ago, more than the {buffer_length}-sample "
            f"EEG buffer holds; poll the classifier more often.")
    return engine.data_buffer[:, buffer_length - n_since:].copy()


class SelfRestartingOnsets:
    def __init__(self, sampling_rate_hz: float, visual_latency_s: float):
        self._sampling_rate_hz = sampling_rate_hz
        self._latency_samples = int(round(visual_latency_s * sampling_rate_hz))
        self._onset_sample: Optional[int] = None
        self._trial_number = 0

    def trial_eeg(self, engine) -> TrialEeg:
        if self._onset_sample is None:
            self._onset_sample = engine.n_received
        t0_sample = self._onset_sample + self._latency_samples
        return TrialEeg(self._trial_number, eeg_since(engine, t0_sample))

    def finish_trial(self, window_length_s: float) -> None:
        decision_samples = int(round(window_length_s * self._sampling_rate_hz))
        self._onset_sample += self._latency_samples + decision_samples
        self._trial_number += 1


class LslMarkerOnsets:
    def __init__(self, sampling_rate_hz: float, visual_latency_s: float,
                 stream_name: str = MARKER_STREAM_NAME):
        self._latency_samples = int(round(visual_latency_s * sampling_rate_hz))
        self._inlet = self._open_marker_stream(stream_name)
        self._onset_sample: Optional[int] = None
        self._trial_number = 0

    def trial_eeg(self, engine) -> Optional[TrialEeg]:
        self._read_trial_starts(engine)
        if self._onset_sample is None:
            return None
        return TrialEeg(self._trial_number, eeg_since(engine, self._onset_sample + self._latency_samples))

    def finish_trial(self, window_length_s: float) -> None:
        self._onset_sample = None

    # --- Internals ----------------------------------------------------------

    @staticmethod
    def _open_marker_stream(stream_name: str) -> StreamInlet:
        print(f"[ONSET] Waiting up to {MARKER_WAIT_S:.0f} s for LSL stream '{stream_name}'...")
        found = resolve_byprop("name", stream_name, minimum=1, timeout=MARKER_WAIT_S)
        if not found:
            raise RuntimeError(f"LSL marker stream '{stream_name}' not found - start the stimulus.")
        return StreamInlet(found[0], processing_flags=proc_clocksync)

    def _read_trial_starts(self, engine) -> None:
        markers, timestamps = self._inlet.pull_chunk(timeout=0.0)
        for (payload,), timestamp in zip(markers, timestamps):
            if json.loads(payload).get("event") == TRIAL_START_EVENT:
                # Same machine: EEG and marker timestamps share LSL's local clock.
                self._onset_sample = bisect.bisect_left(engine.eeg_ts, timestamp)
                self._trial_number += 1


OnsetFactory = Callable[[float, float], object]
ONSET_SOURCES: Dict[str, OnsetFactory] = {
    "self-restart": SelfRestartingOnsets,
    "markers": LslMarkerOnsets,
}
DEFAULT_ONSET_SOURCE = "self-restart"


def create_onset_source(name: str, sampling_rate_hz: float, visual_latency_s: float):
    if name not in ONSET_SOURCES:
        raise ValueError(f"Unknown onset source '{name}'. Choose one of {sorted(ONSET_SOURCES)}.")
    return ONSET_SOURCES[name](sampling_rate_hz, visual_latency_s)
