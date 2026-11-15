"""
Test polaczenia SignalEngine <-> Unicorn Hybrid Black (LSL).

Wymagania:
  1. Unicorn Recorder uruchomiony, wlaczone "Send data via LSL",
     akwizycja wystartowana (domyslna nazwa: UnicornRecorderLSLStream).
  2. W config.py (dla Unicorna):
        FS               = 250
        N_CHANNELS       = 8
        LSL_CHANNEL_IDX  = list(range(8))      # EEG = kanaly 0-7 w strumieniu
        CHANNEL_NAMES    = ['Fz','C3','Cz','C4','Pz','PO7','Oz','PO8']

Uruchomienie:
  python test_unicorn_lsl.py
  python test_unicorn_lsl.py --stream-name MojaNazwa --seconds 30
  python test_unicorn_lsl.py --rate 10        # 10 linii/s zamiast 2
  python test_unicorn_lsl.py --method toolbox-fbcca   # metoda detekcji SSVEP (ssvep_methods.py)
  python test_unicorn_lsl.py --method abfcca --rate 20              # okno adaptacyjne, start triali:
  python test_unicorn_lsl.py --method abfcca --rate 20 --onset markers   # ... z markerow bodzca
  Ctrl+C konczy test.
"""

import argparse
import time

import numpy as np

from config import Config
from signal_engine import SignalEngine
from ssvep_methods import (ALL_METHODS, DEFAULT_METHOD, create_adaptive_classifier,
                           create_detector, is_adaptive)
from trial_onsets import DEFAULT_ONSET_SOURCE, ONSET_SOURCES, create_onset_source

WINDOW_SECONDS = 1.0
OCCIPITAL_CHANNELS = ("PO7", "Oz", "PO8")
DEFAULT_STIMULUS_FREQUENCIES_HZ = (12.0, 14.0, 16.0)  # keep in sync with ssvep_stimuli.py


def occipital_indices(channel_names):
    missing = [name for name in OCCIPITAL_CHANNELS if name not in channel_names]
    if missing:
        raise ValueError(f"Occipital channels {missing} not found in {list(channel_names)}.")
    return [channel_names.index(name) for name in OCCIPITAL_CHANNELS]


def format_detection(result):
    scores = "  ".join(f"{f:g} Hz: {s:.3f}" for f, s in result.scores.items())
    return f"SSVEP -> {result.best_frequency_hz:g} Hz   ({scores})"


def format_adaptive_decision(decision, frequencies_hz):
    features = "  ".join(f"{f:g} Hz: {s:.3f}" for f, s in zip(frequencies_hz, decision.features))
    return (f"SSVEP -> {decision.frequency_hz:g} Hz after {decision.window_length_s:.2f} s "
            f"[{decision.reason}]   ({features})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stream-name", default=None,
                    help="nazwa strumienia LSL (domyslnie UnicornRecorderLSLStream)")
    ap.add_argument("--seconds", type=float, default=0,
                    help="czas testu w sekundach (0 = do Ctrl+C)")
    ap.add_argument("--rate", type=float, default=2.0,
                    help="ile razy na sekunde wypisywac wiersz (domyslnie 2)")
    ap.add_argument("--freqs", type=float, nargs="+", default=DEFAULT_STIMULUS_FREQUENCIES_HZ,
                    help="czestotliwosci bodzcow SSVEP w Hz (jak w ssvep_stimuli.py)")
    ap.add_argument("--method", choices=ALL_METHODS, default=DEFAULT_METHOD,
                    help="metoda detekcji SSVEP")
    ap.add_argument("--onset", choices=sorted(ONSET_SOURCES), default=DEFAULT_ONSET_SOURCE,
                    help="poczatek triala dla metod adaptacyjnych (abfcca, abcca)")
    args = ap.parse_args()

    engine = SignalEngine(stream_name=args.stream_name)
    engine.connect()
    engine.start_background()

    n_ch = len(engine.channel_idx)
    names = (list(Config.CHANNEL_NAMES)
             if len(Config.CHANNEL_NAMES) == n_ch
             else [f"Ch{i+1}" for i in range(n_ch)])

    window_samples = int(round(Config.FS * WINDOW_SECONDS))
    occipital = occipital_indices(names)
    detector, adaptive, onsets = None, None, None
    if is_adaptive(args.method):
        adaptive = create_adaptive_classifier(args.method, args.freqs, Config.FS)
        onsets = create_onset_source(args.onset, Config.FS, adaptive.config.visual_latency_s)
    else:
        detector = create_detector(args.method, args.freqs, Config.FS)
    n_analyzed = 0

    print_header = False
    if print_header is True:
        header = f"{'t[s]':>6} {'probek':>8} {'fs[Hz]':>7} | " + " ".join(f"{n:>9}" for n in names)
        print("\nOstatnia probka (uV na kanal):")
        print(header)
        print("-" * len(header))

    t_start = time.time()
    t_prev, n_prev = t_start, 0
    period = 1.0 / args.rate # changes here! window length

    try:
        while True:
            time.sleep(period)
            now = time.time()

            with engine.lock:
                last = engine.data_buffer[:, -1].copy()
                n_total = engine.n_received

                window = None
                if detector is not None and n_total - n_analyzed >= window_samples:
                    window = engine.data_buffer[:, -window_samples:].copy()
                    n_analyzed = n_total

                trial = onsets.trial_eeg(engine) if onsets is not None else None

            if window is not None:
                print(format_detection(detector.detect(window[occipital])))

            if trial is not None:
                decision = adaptive.update(trial.number, trial.eeg_from_t0[occipital])
                if decision is not None:
                    print(format_adaptive_decision(decision, args.freqs))
                    onsets.finish_trial(decision.window_length_s)

            fs_est = (n_total - n_prev) / (now - t_prev)
            t_prev, n_prev = now, n_total

            print_values = False
            if print_values is True:
                vals = " ".join(f"{v:>9.1f}" for v in last)
                print(f"{now - t_start:>6.1f} {n_total:>8d} {fs_est:>7.1f} | {vals}")

            if n_total == 0 and now - t_start > 5:
                print(f"[!] Brak danych od 5 s (odrzucone: {engine.n_dropped}, "
                      f"blad: {engine.last_error}). Czy w Unicorn Recorder jest "
                      f"wcisniety START (akwizycja) i wlaczone LSL?")

            if args.seconds and now - t_start >= args.seconds:
                break
    except KeyboardInterrupt:
        print("\n[STOP] Przerwano.")
    finally:
        engine.stop()

    # Podsumowanie
    with engine.lock:
        buf = engine.data_buffer.copy()
        n_total = engine.n_received
    elapsed = time.time() - t_start
    print(f"\nOdebrano {n_total} probek w {elapsed:.1f} s "
          f"(srednio {n_total / elapsed:.1f} Hz, oczekiwane {Config.FS} Hz)")
    print("Std sygnalu w buforze [uV]:")
    for n, s in zip(names, buf.std(axis=1)):
        print(f"  {n:>5}: {s:8.2f}")


if __name__ == "__main__":
    main()
