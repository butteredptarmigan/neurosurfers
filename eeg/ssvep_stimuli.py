"""SSVEP stimuli: flickering squares with configurable frequencies (PsychoPy).

Each square's luminance follows a sine wave sampled once per screen frame, so
any frequency below half the refresh rate is rendered accurately, even when
the refresh rate is not an integer multiple of it (e.g. 14 Hz on a 60 Hz screen).

Every session is logged to --log-dir for later comparison with recorded EEG:
    ssvep_<start>.csv   one row per frame: frame index, stimulus time, wall-clock
                        time (Unix epoch, seconds) captured right after the flip,
                        and the luminance of each stimulus in that frame
    ssvep_<start>.json  session start/end (epoch + ISO), frequencies, refresh
                        rate, layout

Usage:
    python ssvep_stimuli.py                          # 12, 14, 16 Hz
    python ssvep_stimuli.py --freqs 12 14 16 18      # four stimuli
    python ssvep_stimuli.py --size 0.35 --gap 0.25 --duration 30
    python ssvep_stimuli.py --windowed               # instead of fullscreen

Press Escape to quit.
"""

import argparse
import csv
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Sequence

from psychopy import event, visual

DEFAULT_FREQUENCIES_HZ = (12.0, 14.0, 16.0)
DEFAULT_LOG_DIR = Path("ssvep_logs")
QUIT_KEY = "escape"


@dataclass(frozen=True)
class StimulusLayout:
    """Geometry of the stimuli in PsychoPy 'height' units (1.0 = screen height)."""

    size: float = 0.3
    gap: float = 0.2


@dataclass(frozen=True)
class SessionConfig:
    frequencies_hz: Sequence[float]
    layout: StimulusLayout
    fullscreen: bool
    duration_s: float  # 0 means run until QUIT_KEY is pressed
    log_dir: Path


# --- Pure computations (no screen needed) ---------------------------------


def horizontal_positions(count: int, layout: StimulusLayout) -> List[float]:
    """Centre x positions of `count` stimuli, evenly spaced around the screen centre."""
    pitch = layout.size + layout.gap
    return [(index - (count - 1) / 2) * pitch for index in range(count)]


def luminance(frequency_hz: float, time_s: float) -> float:
    """Sinusoidal luminance in PsychoPy's -1 (black) .. +1 (white) range."""
    return math.sin(2 * math.pi * frequency_hz * time_s)


def luminance_levels(frequencies_hz: Sequence[float], time_s: float) -> List[float]:
    return [luminance(frequency_hz, time_s) for frequency_hz in frequencies_hz]


def validate_frequencies(frequencies_hz: Sequence[float], refresh_rate_hz: float) -> None:
    nyquist_hz = refresh_rate_hz / 2
    too_fast = [f for f in frequencies_hz if f >= nyquist_hz]
    if too_fast:
        raise ValueError(
            f"Frequencies {too_fast} Hz cannot be shown at a {refresh_rate_hz:.1f} Hz "
            f"refresh rate (must be below {nyquist_hz:.1f} Hz)."
        )


# --- Session log -----------------------------------------------------------


def iso_local(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s).astimezone().isoformat(timespec="milliseconds")


class SessionLog:
    """Writes the per-frame CSV and the session metadata JSON."""

    def __init__(self, log_dir: Path, config: SessionConfig, refresh_rate_hz: float):
        log_dir.mkdir(parents=True, exist_ok=True)
        stem = f"ssvep_{datetime.now():%Y%m%d_%H%M%S}"
        self.csv_path = log_dir / f"{stem}.csv"
        self.json_path = log_dir / f"{stem}.json"
        self._metadata = {
            "start_epoch_s": time.time(),
            "start_iso": iso_local(time.time()),
            "frequencies_hz": list(config.frequencies_hz),
            "refresh_rate_hz": refresh_rate_hz,
            "layout": asdict(config.layout),
            "fullscreen": config.fullscreen,
            "csv_file": self.csv_path.name,
        }
        self._write_metadata()
        self._csv_file = open(self.csv_path, "w", newline="")
        self._writer = csv.writer(self._csv_file)
        self._writer.writerow(
            ["frame", "stimulus_time_s", "flip_epoch_s"]
            + [f"lum_{f:g}hz" for f in config.frequencies_hz]
        )

    def record_frame(self, frame_index: int, stimulus_time_s: float,
                     flip_epoch_s: float, levels: Sequence[float]) -> None:
        self._writer.writerow(
            [frame_index, f"{stimulus_time_s:.6f}", f"{flip_epoch_s:.6f}"]
            + [f"{level:.5f}" for level in levels]
        )

    def close(self, frame_count: int) -> None:
        self._csv_file.close()
        end_epoch_s = time.time()
        self._metadata.update(
            end_epoch_s=end_epoch_s, end_iso=iso_local(end_epoch_s), frame_count=frame_count
        )
        self._write_metadata()

    def _write_metadata(self) -> None:
        self.json_path.write_text(json.dumps(self._metadata, indent=2))


# --- PsychoPy rendering ----------------------------------------------------


def create_window(fullscreen: bool) -> visual.Window:
    return visual.Window(
        fullscr=fullscreen,
        size=(1280, 720),
        color=(-1, -1, -1),
        units="height",
        allowGUI=False,
    )


def square_vertices(size: float) -> List[tuple]:
    half = size / 2
    return [(-half, -half), (-half, half), (half, half), (half, -half)]


def create_stimuli(window: visual.Window, count: int,
                   layout: StimulusLayout) -> List[visual.ShapeStim]:
    # ShapeStim instead of Rect: Rect breaks with the numpy version in this env.
    return [
        visual.ShapeStim(window, vertices=square_vertices(layout.size), pos=(x, 0), lineWidth=0)
        for x in horizontal_positions(count, layout)
    ]


def draw_frame(stimuli: Sequence[visual.ShapeStim], levels: Sequence[float]) -> None:
    for stimulus, level in zip(stimuli, levels):
        stimulus.fillColor = (level, level, level)
        stimulus.draw()


def should_stop(time_s: float, duration_s: float) -> bool:
    if QUIT_KEY in event.getKeys():
        return True
    return duration_s > 0 and time_s >= duration_s


def present(window: visual.Window, config: SessionConfig) -> None:
    refresh_rate_hz = window.getActualFrameRate() or 60.0
    validate_frequencies(config.frequencies_hz, refresh_rate_hz)
    stimuli = create_stimuli(window, len(config.frequencies_hz), config.layout)
    session_log = SessionLog(config.log_dir, config, refresh_rate_hz)
    print(f"Logging to {session_log.csv_path}", flush=True)

    frame_index = 0
    time_s = 0.0
    try:
        while not should_stop(time_s, config.duration_s):
            # Frame-count based time keeps the phase independent of timing jitter.
            time_s = frame_index / refresh_rate_hz
            levels = luminance_levels(config.frequencies_hz, time_s)
            draw_frame(stimuli, levels)
            window.flip()
            session_log.record_frame(frame_index, time_s, time.time(), levels)
            frame_index += 1
    finally:
        session_log.close(frame_index)
    print(f"Done: {frame_index} frames ({time_s:.1f} s). Metadata: {session_log.json_path}",
          flush=True)


# --- Entry point -----------------------------------------------------------


def parse_config(argv: Sequence[str] = None) -> SessionConfig:
    parser = argparse.ArgumentParser(description="Show flickering SSVEP stimuli.")
    parser.add_argument("--freqs", type=float, nargs="+", default=DEFAULT_FREQUENCIES_HZ,
                        help="flicker frequencies in Hz, one stimulus each")
    parser.add_argument("--size", type=float, default=StimulusLayout.size,
                        help="stimulus side length (screen heights)")
    parser.add_argument("--gap", type=float, default=StimulusLayout.gap,
                        help="space between neighbouring stimuli (screen heights)")
    parser.add_argument("--duration", type=float, default=0.0,
                        help="seconds to run; 0 = until Escape")
    parser.add_argument("--windowed", action="store_true", help="do not use fullscreen")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR,
                        help="where to write the timestamped session log")
    args = parser.parse_args(argv)
    return SessionConfig(
        frequencies_hz=tuple(args.freqs),
        layout=StimulusLayout(size=args.size, gap=args.gap),
        fullscreen=not args.windowed,
        duration_s=args.duration,
        log_dir=args.log_dir,
    )


def main(argv: Sequence[str] = None) -> None:
    config = parse_config(argv)
    window = create_window(config.fullscreen)
    try:
        present(window, config)
    finally:
        window.close()


if __name__ == "__main__":
    main()
