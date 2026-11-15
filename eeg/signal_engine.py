"""
    signal_engine.py – SignalEngine (akwizycja LSL + przetwarzanie EEG)
    ====================================================================
    Wydzielona klasa z cgx_bci_smr_logic_display.py.
    Hardware:  Unicorn Hybrid Black (LSL: UnicornRecorderLSLStream, 250 Hz),
               ustawienia kanalow/FS w config.py.

    Uzycie:
        from signal_engine import SignalEngine
        engine = SignalEngine()          # lub SignalEngine(stream_name="...")
        engine.connect()
        engine.start_background()
"""

import os
import time
import threading

import numpy as np
from scipy.signal import butter, filtfilt, lfilter, lfilter_zi
from pylsl import StreamInlet, resolve_streams
import mne

from config import Config


class SignalEngine:

    # Domyslna nazwa strumienia LSL wysylanego przez Unicorn Recorder
    DEFAULT_STREAM_NAME = "UnicornRecorderLSLStream"

    def __init__(self, stream_name=None, channel_idx=None):
        # Zrodlo danych LSL (Unicorn Hybrid Black przez Unicorn Recorder).
        # Mozna nadpisac w Config (LSL_STREAM_NAME, LSL_CHANNEL_IDX) lub argumentami.
        self.stream_name = (stream_name
                            or getattr(Config, "LSL_STREAM_NAME", None)
                            or self.DEFAULT_STREAM_NAME)
        self.channel_idx = list(channel_idx if channel_idx is not None
                                else Config.LSL_CHANNEL_IDX)
        self.lsl_info = None          # StreamInfo po polaczeniu
        self.n_received = 0           # licznik wszystkich odebranych probek
        self.n_dropped = 0            # probki odrzucone przez blad konwersji
        self.last_error = None

        self.mu_band  = Config.MU_BAND_DEFAULT[:]
        self.smr_band = Config.SMR_BAND_DEFAULT[:]
        self._rebuild_filters()

        self.data_buffer  = np.zeros((Config.N_CHANNELS, Config.BUFFER_SIZE))

        # 4 osobne baseliny: mu i beta per kanal (Blad 1: inicjalizowane po IAF)
        # Uwaga: dopiero po update_iaf_from_predictor() sa uzywane poprawne pasma.
        # Przed tym uzywane sa Config.MU_BAND_DEFAULT i Config.SMR_BAND_DEFAULT.
        self.baseline_c3_mu   = 8e+12
        self.baseline_c3_beta = 8e+12
        self.baseline_c4_mu   = 8e+12
        self.baseline_c4_beta = 8e+12
        # Zachowane dla kompatybilnosci
        self.baseline_mu  = 8e+12
        self.baseline_smr = 8e+12
        # Skroty dla collect_rest_sample / commit (wskazuja na powyzsze)
        self.baseline_c3  = 8e+12   # = srednia c3_mu i c3_beta (do wyswietlania)
        self.baseline_c4  = 8e+12

        # IAF/IBF per kanal
        self.iaf    = 10.0
        self.ibf    = 20.0
        self.iaf_c3 = 10.0
        self.ibf_c3 = 20.0
        self.iaf_c4 = 10.0
        self.ibf_c4 = 20.0

        # Pasma per kanal
        self.mu_band_c3   = Config.MU_BAND_DEFAULT[:]    # [IAF_c3-2, IAF_c3+2]
        self.mu_band_c4   = Config.MU_BAND_DEFAULT[:]
        self.beta_band_c3 = Config.SMR_BAND_DEFAULT[:]   # [IBF_c3-2, IBF_c3+2]
        self.beta_band_c4 = Config.SMR_BAND_DEFAULT[:]

        # Wagi mu vs beta z predyktora Blankertza (elevation per pasmo per kanal)
        # uzywane gdy Config.WEIGHTED_ERD=True
        self.elev_c3_mu   = 1.0
        self.elev_c3_beta = 1.0
        self.elev_c4_mu   = 1.0
        self.elev_c4_beta = 1.0

        self.lock     = threading.Lock()
        self.eeg_data = []
        self.eeg_ts   = []
        self.markers  = []

        self.inlet    = None
        self._running = False

        # Bufor probek REST do rolling baseline (commit na koniec bloku REST)
        self._rest_samples_c3_mu   = []
        self._rest_samples_c3_beta = []
        self._rest_samples_c4_mu   = []
        self._rest_samples_c4_beta = []

        # Stan EMA wygładzania ERD per-kanal – aktualizowany TYLKO w get_erd_c3/c4
        # get_erd() czyta _ema_c3/c4 bezposrednio (bez ponownego wywolania get_erd_c3/c4)
        self._ema_c3_mu = self._ema_c3_beta = 0.0
        self._ema_c4_mu = self._ema_c4_beta = 0.0
        self._erd_c3 = self._erd_c4 = 0.0  # połączone, odczytywane przez get_erd()
        self._ema_global = 0.0

        # Stan kauzalnego LPF 0.35 Hz (Kodama) – OSOBNY per pasmo (Opcja A):
        # C3/C4 x mu/beta = 4 niezalezne filtry. Uzywany gdy SMOOTHING_MODE='lpf'.
        # Inicjalizacja zerowa (lfilter_zi * 0) – start od 0% ERD.
        self._lpf_zi = {k: lfilter_zi(self.b_lpf, self.a_lpf) * 0.0
                        for k in ('c3_mu', 'c3_beta', 'c4_mu', 'c4_beta')}

    # --- Filtry ---

    def _rebuild_filters(self):
        """Buduje filtry Butterwortha 4. rzedu dla pasm Mu i SMR oraz
        dolnoprzepustowy LPF wygladzajacy przebieg ERD (Kodama 2023)."""
        nyq = 0.5 * Config.FS
        self.b_mu,  self.a_mu  = butter(4,
            [self.mu_band[0]  / nyq, self.mu_band[1]  / nyq], btype='band')
        self.b_smr, self.a_smr = butter(4,
            [self.smr_band[0] / nyq, self.smr_band[1] / nyq], btype='band')

        # LPF 0.35 Hz na STRUMIENIU ERD (Kodama 2023). Projektowany wzgledem
        # czestotliwosci strumienia ERD (10 Hz = 1 probka co 100 ms), NIE fs EEG.
        # nyq_erd = 5 Hz. Gdyby uzyc nyq=250 Hz, odciecie spadloby do ~0.007 Hz
        # (~23 s opoznienia). Uzywany tylko gdy Config.SMOOTHING_MODE == 'lpf'.
        nyq_erd = 10.0 / 2.0
        self.b_lpf, self.a_lpf = butter(3, 0.25 / nyq_erd, btype='low')

    # --- LSL ---

    def connect(self, timeout=10.0):
        """Laczy sie ze strumieniem LSL po nazwie (domyslnie
        UnicornRecorderLSLStream z Unicorn Recorder)."""
        print(f"[LSL] Szukam strumienia '{self.stream_name}' (max {timeout:.0f}s)...")
        # resolve_byprop konczy po PIERWSZYM znalezionym strumieniu (minimum=1),
        # wiec mogl pominac zywy strumien, gdy obok istnieje martwy o tej samej
        # nazwie. resolve_streams zbiera WSZYSTKIE odpowiedzi z calego okna.
        streams = []
        deadline = time.time() + timeout
        while not streams and time.time() < deadline:
            streams = [s for s in resolve_streams(wait_time=2.0)
                       if s.name() == self.stream_name]
        print(f"[LSL] Znaleziono {len(streams)} strumien(i) o tej nazwie.")
        if not streams:
            available = [f"{s.name()} ({s.channel_count()} ch, {s.nominal_srate():.0f} Hz)"
                         for s in resolve_streams(wait_time=1.0)]
            raise RuntimeError(
                f"Nie znaleziono strumienia LSL '{self.stream_name}'.\n"
                f"Dostepne strumienie: {available if available else 'brak'}\n"
                f"Sprawdz: Unicorn Recorder -> wlaczony 'Send data via LSL' "
                f"i uruchomiona akwizycja.")

        # Moga istniec "martwe" strumienie o tej samej nazwie (np. po restarcie
        # Unicorn Recorder). Sprawdzamy kazdy kandydat i bierzemy ten, z ktorego
        # faktycznie plyna probki.
        info, inlet = None, None
        for cand in streams:
            cand_inlet = StreamInlet(cand, max_buflen=60)
            probe, _ = cand_inlet.pull_chunk(timeout=1.5, max_samples=16)
            if probe:
                info, inlet = cand, cand_inlet
                break
            print(f"[LSL] Strumien source_id={cand.source_id()!r} nie wysyla danych "
                  f"– pomijam.")
            cand_inlet.close_stream()
        if info is None:
            raise RuntimeError(
                f"Znaleziono {len(streams)} strumien(i) '{self.stream_name}', ale zaden "
                f"nie wysyla danych. W Unicorn Recorder wcisnij Start (akwizycja) "
                f"i wlacz LSL; w razie potrzeby zrestartuj Recorder.")

        n_ch = info.channel_count()
        srate = info.nominal_srate()

        if max(self.channel_idx) >= n_ch:
            raise RuntimeError(
                f"Strumien ma {n_ch} kanalow, a LSL_CHANNEL_IDX={self.channel_idx} "
                f"wskazuje poza zakres. Unicorn: EEG = indeksy 0-7.")
        if abs(srate - Config.FS) > 1e-6:
            print(f"[LSL] UWAGA: fs strumienia = {srate:.0f} Hz, a Config.FS = "
                  f"{Config.FS}. Ustaw Config.FS = {srate:.0f} (Unicorn = 250 Hz), "
                  f"inaczej filtry i okna mocy beda zle.")

        self.lsl_info = info
        self.inlet = inlet
        print(f"[LSL] Polaczono: {info.name()}  ({n_ch} ch, {srate:.0f} Hz)")
        print(f"[LSL] Kanaly:    {Config.CHANNEL_NAMES}")
        print(f"[LSL] Indeksy:   {self.channel_idx}")

    def start_background(self):
        self._running = True
        target = self._replay_loop if hasattr(self, '_replay_data') else self._pull_loop
        t = threading.Thread(target=target, daemon=True)
        t.start()

    def _pull_loop(self):
        """Watek tla: pobiera paczki probek z LSL i zapisuje do bufora."""
        buf_len = self.data_buffer.shape[1]
        while self._running:
            try:
                samples, stamps = self.inlet.pull_chunk(timeout=0.05, max_samples=128)
            except Exception as e:
                print(f"[LSL] BLAD pull_chunk: {e!r}")
                self.last_error = repr(e)
                time.sleep(0.5)
                continue
            if not samples:
                continue
            try:
                # (n, n_kanalow_strumienia) -> (n_wybranych, n)
                chunk = np.asarray(samples, dtype=float)[:, self.channel_idx].T
            except (ValueError, TypeError, IndexError) as e:
                # Nie gub bledu po cichu – licz i pokaz pierwszy
                self.n_dropped += len(samples)
                if self.last_error is None:
                    self.last_error = repr(e)
                    print(f"[LSL] BLAD konwersji paczki ({len(samples)} probek): "
                          f"{e!r}; przykladowa probka: {samples[0]}")
                continue
            n = chunk.shape[1]
            with self.lock:
                if n >= buf_len:
                    self.data_buffer[:] = chunk[:, -buf_len:]
                else:
                    self.data_buffer = np.roll(self.data_buffer, -n, axis=1)
                    self.data_buffer[:, -n:] = chunk
                self.eeg_data.extend(chunk.T.tolist())
                self.eeg_ts.extend(stamps)
                self.n_received += n

    # --- REPLAY z pliku .fif ---

    def connect_from_file(self, fif_path):
        """Wczytuje sygnal z .fif oraz odpowiadajacy mu _events.npy.
        Zastepuje connect() + _pull_loop() w trybie replay."""
        print(f"[REPLAY] Wczytuje {fif_path}")
        raw = mne.io.read_raw_fif(fif_path, preload=True, verbose='ERROR')

        # Ustaw kanaly w tej samej kolejnosci co CHANNEL_NAMES
        try:
            raw.pick(Config.CHANNEL_NAMES)
        except Exception as e:
            raise RuntimeError(
                f"Plik .fif nie zawiera oczekiwanych kanalow {Config.CHANNEL_NAMES}.\n"
                f"Dostepne: {raw.ch_names}\nBlad: {e}")

        # MNE trzyma w V — wracamy do jednostek CGX (z save(): data * 1e-6)
        self._replay_data = raw.get_data() * 1e6   #ping (n_channels, n_samples)
        self._replay_idx  = 0
        self._replay_fs   = raw.info['sfreq']
        print(f"[REPLAY] {self._replay_data.shape[1]} probek, "
              f"{self._replay_data.shape[1]/self._replay_fs:.1f}s, "
              f"fs={self._replay_fs:.0f}Hz")

        # Wczytaj _events.npy obok pliku .fif
        events_path = fif_path.replace("_raw.fif", "_events.npy")
        if os.path.exists(events_path):
            ev = np.load(events_path, allow_pickle=True)
            self._replay_events = ev
            print(f"[REPLAY] Wczytano events: {events_path}  "
                  f"({ev.shape[0]} markerow)")
        else:
            self._replay_events = np.zeros((0, 3), dtype=int)
            print(f"[REPLAY] UWAGA: brak pliku {events_path} – "
                  f"synchronizacja z MI niemozliwa.")

    def _replay_loop(self):
        """Watek tla: podaje probki z pliku w tempie real-time.
        Obsluguje skoki indeksu (seek) ustawiane przez main()."""
        speed = getattr(self, '_replay_speed', 1.0)
        dt = 1.0 / (Config.FS * speed)
        next_t = time.time()
        n_total = self._replay_data.shape[1]

        while self._running:
            if self._replay_idx >= n_total:
                # Po wyczerpaniu pliku — zapetlaj od poczatku
                self._replay_idx = 0
                next_t = time.time()
                print("[REPLAY] Koniec pliku – zapetlam od poczatku.")

            arr = self._replay_data[:, self._replay_idx]
            with self.lock:
                self.data_buffer = np.roll(self.data_buffer, -1, axis=1)
                self.data_buffer[:, -1] = arr
                self.eeg_data.append(arr.tolist())
                self.eeg_ts.append(self._replay_idx / self._replay_fs)
            self._replay_idx += 1

            next_t += dt
            sleep = next_t - time.time()
            if sleep > 0:
                time.sleep(sleep)
            elif sleep < -0.1:
                # Jesli mocno odstajemy (np. po seek), zresetuj zegar
                next_t = time.time()

    def seek_replay(self, sample_idx):
        """Przewija odtwarzanie do zadanej probki w pliku .fif.
        Uzywane do synchronizacji okna MI z prawdziwymi cue'ami."""
        with self.lock:
            self._replay_idx = max(0, int(sample_idx))

    def stop(self):
        self._running = False

    def add_marker(self, code):
        """Zapisuje marker jako (indeks_probki, kod). Uzywa len(eeg_data)
        zamiast timestamp LSL – eliminuje problem roznych zegarow.
        [CLASSIFIER ONLINE] Zwraca indeks probki potrzebny do klasyfikacji."""
        with self.lock:
            idx = len(self.eeg_data)
        self.markers.append((idx, code))
        return idx  # [CLASSIFIER ONLINE]

    # [CLASSIFIER ONLINE] Zwraca caly nagrany sygnal (n_ch, n_samples)
    def get_eeg_array(self):
        with self.lock:
            data = np.array(self.eeg_data).T
        return data

    # --- Laplasjan przestrzenny ---

    @staticmethod
    def _apply_laplacian(buf, lap_cfg):
        """Laplasjan przestrzenny dla jednego kanalu, z dowolna liczba sasiadow.
        lap_cfg: slownik {'center': idx, 'neighbors': [idx1, idx2, ...]}.
        Zwraca sygnal (n_samples,) po odjęciu sredniej sasiadow:
            center - mean(neighbors)
        Dziala zarowno dla 4 sasiadow (pelny duzy laplasjan) jak i dla
        mniejszej liczby (np. 3, gdy montaz nie posiada wszystkich elektrod)."""
        center = buf[lap_cfg['center']]
        neighbors = lap_cfg['neighbors']
        neighbor_mean = np.mean([buf[idx] for idx in neighbors], axis=0)
        return center - neighbor_mean

    # --- Moc w pasmach ---
    def _band_power(self, b, a):
        """Moc RMS z ostatnich POWER_WINDOW_S sekund na kanalach SMR.

        Jesli Config.USE_LAPLACIAN=True, przed filtrowaniem stosuje duzy
        laplasjan na C3 i C4 (zamiast surowych kanalow SMR_CHANNELS).
        Filtr kauzalny lfilter zamiast filtfilt – brak artefaktow brzegowych
        w trybie online.
        """
        with self.lock:
            buf = self.data_buffer.copy()

        win = int(Config.FS * Config.POWER_WINDOW_S)

        if Config.USE_LAPLACIAN:
            signals = [
                self._apply_laplacian(buf, Config.LAPLACIAN_C3),
                self._apply_laplacian(buf, Config.LAPLACIAN_C4),
            ]
        else:
            signals = [buf[ch] for ch in Config.SMR_CHANNELS]

        powers = []
        for sig in signals:
            try:
                filt = lfilter(b, a, sig)
                powers.append(float(np.mean(filt[-win:] ** 2)))
            except Exception:
                powers.append(1.0)
        return float(np.mean(powers))

    def _band_power_single(self, sig, b, a):
        """Moc RMS jednego sygnalu (1D array) w pasmie filtra (b, a).
        Uzywane przez get_power_c3/c4."""
        win = int(Config.FS * Config.POWER_WINDOW_S)
        try:
            filt = filtfilt(b, a, sig)
            return float(np.mean(filt[-win:] ** 2))
        except Exception:
            return 1.0

    ''' 0.25
    def _band_power_single(self, sig, b, a):
    """Moc w pasmie (b,a): filtfilt na buforze, okno cofnięte o guard
    od krawędzi 'teraz', by ominąć artefakt brzegowy filtfilt."""
    win   = int(Config.FS * Config.POWER_WINDOW_S)   # 500 = 1 s
    guard = int(Config.FS * 0.25)                     # 0.25 s marginesu
    try:
        filt = filtfilt(b, a, sig)
        seg  = filt[-(win + guard):-guard] if guard else filt[-win:]
        return float(np.mean(seg ** 2))
    except Exception:
        return 1.0
    '''
    def _get_signal_c3(self, buf):
        if Config.USE_LAPLACIAN:
            return self._apply_laplacian(buf, Config.LAPLACIAN_C3)
        return buf[Config.SMR_CHANNELS[0]]

    def _get_signal_c4(self, buf):
        if Config.USE_LAPLACIAN:
            return self._apply_laplacian(buf, Config.LAPLACIAN_C4)
        return buf[Config.SMR_CHANNELS[1]]

    def _band_power_for_band(self, sig, band):
        """Moc RMS sygnalu w zadanym pasmie [lo, hi] Hz."""
        nyq = 0.5 * Config.FS
        lo  = max(band[0] / nyq, 1e-4)
        hi  = min(band[1] / nyq, 0.9999)
        b, a = butter(4, [lo, hi], btype='band')
        return self._band_power_single(sig, b, a)

    def get_power_c3_mu(self):
        with self.lock:
            buf = self.data_buffer.copy()
        return self._band_power_for_band(self._get_signal_c3(buf), self.mu_band_c3)

    def get_power_c3_beta(self):
        with self.lock:
            buf = self.data_buffer.copy()
        return self._band_power_for_band(self._get_signal_c3(buf), self.beta_band_c3)

    def get_power_c4_mu(self):
        with self.lock:
            buf = self.data_buffer.copy()
        return self._band_power_for_band(self._get_signal_c4(buf), self.mu_band_c4)

    def get_power_c4_beta(self):
        with self.lock:
            buf = self.data_buffer.copy()
        return self._band_power_for_band(self._get_signal_c4(buf), self.beta_band_c4)

    # Skroty dla wstecznej kompatybilnosci (uzywane w calibrate_baseline)
    def get_power_c3(self):
        return self.get_power_c3_mu()

    def get_power_c4(self):
        return self.get_power_c4_mu()

    def get_mu_power(self):
        return self._band_power(self.b_mu, self.a_mu)

    def get_smr_power(self):
        return self._band_power(self.b_smr, self.a_smr)

    # --- Kalibracja ---

    def calibrate_baseline_from_data(self, cal_data):
        """Wyznacza 4 baseliny (C3_mu, C3_beta, C4_mu, C4_beta) z macierzy
        surowego sygnalu EEG (n_ch, n_samples) z okna kalibracji.

        Algorytm:
          - Filtruje CALY sygnal cal_data (filtfilt – brak artefaktow przejsciowych)
          - Dzieli na okna 1s i liczy moc RMS per okno
          - Robust median po wszystkich oknach -> baseline
        """
        win = int(Config.FS * Config.POWER_WINDOW_S)   # 500 probek = 1s

        def _power_windows(sig, band):
            """Filtruje caly sygnal, potem liczy moc per okno 1s."""
            nyq = 0.5 * Config.FS
            lo  = max(band[0] / nyq, 1e-4)
            hi  = min(band[1] / nyq, 0.9999)
            b, a = butter(4, [lo, hi], btype='band')
            try:
                filt = filtfilt(b, a, sig)   # filtfilt na calym sygnale – brak artefaktow
            except Exception:
                return []
            n_windows = len(filt) // win
            return [float(np.mean(filt[i*win:(i+1)*win] ** 2))
                    for i in range(n_windows)]

        def robust_median(samples):
            samples = [s for s in samples if s is not None and s > 1e-12]
            if not samples:
                return 8e+12
            med = float(np.median(samples))
            clean = [s for s in samples if s < med * 1.5]
            return float(np.median(clean)) if clean else med

        sig_c3 = (self._apply_laplacian(cal_data, Config.LAPLACIAN_C3)
                  if Config.USE_LAPLACIAN else cal_data[Config.SMR_CHANNELS[0]])
        sig_c4 = (self._apply_laplacian(cal_data, Config.LAPLACIAN_C4)
                  if Config.USE_LAPLACIAN else cal_data[Config.SMR_CHANNELS[1]])

        w_c3_mu   = _power_windows(sig_c3, self.mu_band_c3)
        w_c3_beta = _power_windows(sig_c3, self.beta_band_c3)
        w_c4_mu   = _power_windows(sig_c4, self.mu_band_c4)
        w_c4_beta = _power_windows(sig_c4, self.beta_band_c4)

        self.baseline_c3_mu   = robust_median(w_c3_mu)
        self.baseline_c3_beta = robust_median(w_c3_beta)
        self.baseline_c4_mu   = robust_median(w_c4_mu)
        self.baseline_c4_beta = robust_median(w_c4_beta)
        self.baseline_c3  = (self.baseline_c3_mu + self.baseline_c3_beta) / 2
        self.baseline_c4  = (self.baseline_c4_mu + self.baseline_c4_beta) / 2
        self.baseline_mu  = (self.baseline_c3 + self.baseline_c4) / 2
        self.baseline_smr = self.baseline_mu

        n = len(w_c3_mu)
        print(f"[KALIBRACJA] {n} okien x 1s  "
              f"pasma: mu_c3={self.mu_band_c3} beta_c3={self.beta_band_c3}")
        print(f"[KALIBRACJA] C3: mu={self.baseline_c3_mu:.4e}  "
              f"beta={self.baseline_c3_beta:.4e}")
        print(f"[KALIBRACJA] C4: mu={self.baseline_c4_mu:.4e}  "
              f"beta={self.baseline_c4_beta:.4e}")

    def calibrate_baseline(self, samples_mu, samples_smr):
        """Zachowane dla wstecznej kompatybilnosci.
        Nie uzywane gdy predictor jest dostepny – wtedy uzywa calibrate_baseline_from_data."""
        if not samples_mu:
            return
        def robust_median(s):
            med = float(np.median(s))
            clean = [x for x in s if x < med * 1.5]
            return float(np.median(clean)) if clean else med
        self.baseline_mu  = robust_median(samples_mu)
        self.baseline_smr = robust_median(samples_smr) if samples_smr else self.baseline_mu
        self.baseline_c3_mu = self.baseline_c3_beta = self.baseline_mu
        self.baseline_c4_mu = self.baseline_c4_beta = self.baseline_mu
        self.baseline_c3 = self.baseline_c4 = self.baseline_mu

    # --- Rolling baseline – naprawa Bledu 2 + 4 baseliny ---

    def collect_rest_sample(self):
        """Zbiera probki mocy do 4 buforow REST.
        NIE modyfikuje baseline – commit nastapi na koncu REST jesli
        Config.ROLLING_BASELINE=True."""
        self._rest_samples_c3_mu.append(self.get_power_c3_mu())
        self._rest_samples_c3_beta.append(self.get_power_c3_beta())
        self._rest_samples_c4_mu.append(self.get_power_c4_mu())
        self._rest_samples_c4_beta.append(self.get_power_c4_beta())

    def commit_rolling_baseline(self):
        """NAPRAWA BLEDU 2: wywolywana TYLKO gdy Config.ROLLING_BASELINE=True.
        Sprawdzenie flagi jest tutaj (nie tylko w callerze) jako dodatkowe
        zabezpieczenie przed przypadkowym wywolaniem."""
        if not Config.ROLLING_BASELINE:
            self._rest_samples_c3_mu.clear()
            self._rest_samples_c3_beta.clear()
            self._rest_samples_c4_mu.clear()
            self._rest_samples_c4_beta.clear()
            return

        def robust_median(samples):
            samples = [s for s in samples if s is not None]
            if not samples:
                return None
            med = float(np.median(samples))
            clean = [s for s in samples if s < med * 1.5]
            return float(np.median(clean)) if clean else med

        a = Config.BASELINE_ALPHA

        def _update(current, samples):
            ref = robust_median(samples)
            if ref is not None and ref > 1e-12:
                return (1 - a) * current + a * ref
            return current

        self.baseline_c3_mu   = _update(self.baseline_c3_mu,   self._rest_samples_c3_mu)
        self.baseline_c3_beta = _update(self.baseline_c3_beta, self._rest_samples_c3_beta)
        self.baseline_c4_mu   = _update(self.baseline_c4_mu,   self._rest_samples_c4_mu)
        self.baseline_c4_beta = _update(self.baseline_c4_beta, self._rest_samples_c4_beta)
        self.baseline_c3 = (self.baseline_c3_mu + self.baseline_c3_beta) / 2
        self.baseline_c4 = (self.baseline_c4_mu + self.baseline_c4_beta) / 2
        self.baseline_mu = (self.baseline_c3 + self.baseline_c4) / 2

        n = len(self._rest_samples_c3_mu)
        print(f"[BASELINE-ROLL] C3 mu={self.baseline_c3_mu:.3e} "
              f"beta={self.baseline_c3_beta:.3e}  "
              f"C4 mu={self.baseline_c4_mu:.3e} "
              f"beta={self.baseline_c4_beta:.3e}  ({n} probek)")

        self._rest_samples_c3_mu.clear()
        self._rest_samples_c3_beta.clear()
        self._rest_samples_c4_mu.clear()
        self._rest_samples_c4_beta.clear()

    # --- Aktualizacja IAF/IBF z predyktora Blankertza ---
    def update_iaf_from_predictor(self, fits, bands=None):
        """Aktualizuje IAF/IBF, pasma i wagi.

        fits  : wynik fit_channel per kanal – ZAWSZE dostarcza wagi mu/beta
                (mu_elev, elevation), uzywane przy --weighted-erd.
        bands : opcjonalny dict {'iaf': float|None, 'ibf': float|None} ze
                WSPOLNYM, odpornym IAF/IBF (predictor.robust_bands). Gdy klucz
                jest None -> odpowiednie pasmo NIE jest zmieniane (brak wyraznego
                piku -> zostaje dotychczasowe). Gdy bands=None -> tryb zgodny
                wstecznie: czestotliwosci brane per-kanal z fits.

        Kluczowa zmiana: IAF/IBF sa WSPOLNE dla C3 i C4 (jedno pasmo mu, jedno
        beta), bo rozjazd czestotliwosci miedzy poblizymi elektrodami jest
        niefizjologiczny. Moc baseline pozostaje liczona OSOBNO per kanal."""

        def _weights(ch):
            f = fits.get(ch, {})
            elev_mu_  = float(max(f.get('mu_elev', 1.0), 0.1))
            peak_freq = float(f.get('peak_freq', 10.0))
            if peak_freq > 16.0:
                elev_beta_ = float(max(f.get('elevation', 1.0), 0.1))
            else:
                elev_beta_ = elev_mu_
            return elev_mu_, elev_beta_

        def _legacy_freqs(ch):
            f    = fits.get(ch, {})
            iaf_ = float(np.clip(f.get('iaf', 10.0), 7.0, 14.0))
            pf   = float(f.get('peak_freq', 20.0))
            ibf_ = float(np.clip(pf if pf > 16.0 else iaf_ + 10.0, 16.0, 30.0))
            return iaf_, ibf_

        # --- Ustal czestotliwosci mu/beta (wspolne) i flagi czy zmieniac pasma ---
        if bands is None:
            iaf_c3, ibf_c3 = _legacy_freqs('C3')
            iaf_c4, ibf_c4 = _legacy_freqs('C4')
            set_mu = set_beta = True
        else:
            shared_iaf = bands.get('iaf')
            shared_ibf = bands.get('ibf')
            if shared_iaf is not None:
                iaf_c3 = iaf_c4 = float(np.clip(shared_iaf, 7.0, 14.0))
                set_mu = True
            else:
                iaf_c3, iaf_c4 = self.iaf_c3, self.iaf_c4
                set_mu = False
                print("[IAF] Brak wyraznego piku mu – pozostawiam dotychczasowe pasmo mu.")
            if shared_ibf is not None:
                ibf_c3 = ibf_c4 = float(np.clip(shared_ibf, 16.0, 30.0))
                set_beta = True
            else:
                ibf_c3, ibf_c4 = self.ibf_c3, self.ibf_c4
                set_beta = False
                print("[IAF] Brak wyraznego piku beta – pozostawiam dotychczasowe pasmo beta.")

        # --- Zapis per kanal: IAF/IBF i wagi zawsze; pasma tylko gdy set_* ---
        if 'C3' in fits:
            self.iaf_c3, self.ibf_c3 = iaf_c3, ibf_c3
            if set_mu:
                self.mu_band_c3   = [round(iaf_c3 - 2.0, 1), round(iaf_c3 + 2.0, 1)]
            if set_beta:
                self.beta_band_c3 = [round(ibf_c3 - 2.0, 1), round(ibf_c3 + 2.0, 1)]
            self.elev_c3_mu, self.elev_c3_beta = _weights('C3')
        if 'C4' in fits:
            self.iaf_c4, self.ibf_c4 = iaf_c4, ibf_c4
            if set_mu:
                self.mu_band_c4   = [round(iaf_c4 - 2.0, 1), round(iaf_c4 + 2.0, 1)]
            if set_beta:
                self.beta_band_c4 = [round(ibf_c4 - 2.0, 1), round(ibf_c4 + 2.0, 1)]
            self.elev_c4_mu, self.elev_c4_beta = _weights('C4')

        self.iaf     = float(np.mean([self.iaf_c3, self.iaf_c4]))
        self.ibf     = float(np.mean([self.ibf_c3, self.ibf_c4]))
        self.mu_band = [round((self.mu_band_c3[0]+self.mu_band_c4[0])/2, 1),
                        round((self.mu_band_c3[1]+self.mu_band_c4[1])/2, 1)]

        print(f"[IAF] C3: IAF={self.iaf_c3:.1f}Hz mu={self.mu_band_c3} "
              f"IBF={self.ibf_c3:.1f}Hz beta={self.beta_band_c3} "
              f"wagi=({self.elev_c3_mu:.1f}/{self.elev_c3_beta:.1f})")
        print(f"[IAF] C4: IAF={self.iaf_c4:.1f}Hz mu={self.mu_band_c4} "
              f"IBF={self.ibf_c4:.1f}Hz beta={self.beta_band_c4} "
              f"wagi=({self.elev_c4_mu:.1f}/{self.elev_c4_beta:.1f})")

    # --- Rolling baseline ---

    # --- Metryka ERD/ERS ---

    def _erd_raw(self, power, baseline):
        """ERD [%] -> tanh. Wspolna logika dla wszystkich kanalow."""
        erd = float(np.clip(
            (power - baseline) / baseline * 100.0, -100, 100))
        return float(np.tanh(erd / Config.TANH_SCALE) * 100.0)

    def _combine_mu_beta(self, erd_mu, erd_beta, elev_mu, elev_beta):
        """Laczy ERD z pasma mu i beta.
        Config.WEIGHTED_ERD=False: srednia arytmetyczna
        Config.WEIGHTED_ERD=True:  srednia wazona elevation z predyktora"""
        mode = getattr(Config, 'BAND_MODE', 'both')
        if mode == 'mu':
            return erd_mu
        if mode == 'beta':
            return erd_beta
        # mode == 'both'
        if getattr(Config, 'WEIGHTED_ERD', False):
            total = elev_mu + elev_beta
            if total < 1e-6:
                return (erd_mu + erd_beta) / 2.0
            return (erd_mu * elev_mu + erd_beta * elev_beta) / total
        return (erd_mu + erd_beta) / 2.0

    def _smooth(self, band_key, raw, prev):
        """Wygladza jedna sciezke pasma (Opcja A – osobno per pasmo per kanal).
        Config.SMOOTHING_MODE:
          'ema' -> EMA 1. rzedu (Config.SMOOTHING) – domyslne
          'lpf' -> kauzalny Butterworth 0.35 Hz (Kodama 2023), stan w
                   self._lpf_zi[band_key], gladszy przebieg kosztem
                   nieco wiekszego opoznienia grupowego.
        band_key: 'c3_mu'|'c3_beta'|'c4_mu'|'c4_beta'. prev: poprzednia
        wartosc wygladzona (uzywana tylko w trybie EMA)."""
        if getattr(Config, 'SMOOTHING_MODE', 'ema') == 'lpf':
            out, self._lpf_zi[band_key] = lfilter(
                self.b_lpf, self.a_lpf, [raw], zi=self._lpf_zi[band_key])
            return float(out[0])
        a = Config.SMOOTHING
        return (1 - a) * prev + a * raw

    '''
    def get_erd_c3(self):
        """ERD na C3: srednia (lub wazona) z pasma mu i beta,
        wygladzana EMA (Config.SMOOTHING).
        Aktualizuje self._ema_c3 – nie wywolywac get_erd_c3() ponownie
        w get_erd(), zeby uniknac podwojnego EMA."""
        p_mu   = self.get_power_c3_mu()
        p_beta = self.get_power_c3_beta()
        if p_mu is None or p_beta is None:
            return self._ema_c3   # zwroc ostatnia znana wartosc
        erd_mu   = self._erd_raw(p_mu,   self.baseline_c3_mu)
        erd_beta = self._erd_raw(p_beta, self.baseline_c3_beta)
        raw = self._combine_mu_beta(erd_mu, erd_beta,
                                    self.elev_c3_mu, self.elev_c3_beta)
        a = Config.SMOOTHING
        self._ema_c3 = (1 - a) * self._ema_c3 + a * raw
        return self._ema_c3
    '''
    # nowe
    def get_erd_c3(self):
        erd_mu   = self._erd_raw(self.get_power_c3_mu(),   self.baseline_c3_mu)
        erd_beta = self._erd_raw(self.get_power_c3_beta(), self.baseline_c3_beta)
        self._ema_c3_mu   = self._smooth('c3_mu',   erd_mu,   self._ema_c3_mu)
        self._ema_c3_beta = self._smooth('c3_beta', erd_beta, self._ema_c3_beta)
        self._erd_c3 = self._combine_mu_beta(
            self._ema_c3_mu, self._ema_c3_beta, self.elev_c3_mu, self.elev_c3_beta)
        return self._erd_c3
    '''
    def get_erd_c4(self):
        """ERD na C4: srednia (lub wazona) z pasma mu i beta,
        wygladzana EMA (Config.SMOOTHING)."""
        p_mu   = self.get_power_c4_mu()
        p_beta = self.get_power_c4_beta()
        if p_mu is None or p_beta is None:
            return self._ema_c4
        erd_mu   = self._erd_raw(p_mu,   self.baseline_c4_mu)
        erd_beta = self._erd_raw(p_beta, self.baseline_c4_beta)
        raw = self._combine_mu_beta(erd_mu, erd_beta,
                                    self.elev_c4_mu, self.elev_c4_beta)
        a = Config.SMOOTHING
        self._ema_c4 = (1 - a) * self._ema_c4 + a * raw
        return self._ema_c4
    '''
    # nowe
    def get_erd_c4(self):
        erd_mu   = self._erd_raw(self.get_power_c4_mu(),   self.baseline_c4_mu)
        erd_beta = self._erd_raw(self.get_power_c4_beta(), self.baseline_c4_beta)
        self._ema_c4_mu   = self._smooth('c4_mu',   erd_mu,   self._ema_c4_mu)
        self._ema_c4_beta = self._smooth('c4_beta', erd_beta, self._ema_c4_beta)
        self._erd_c4 = self._combine_mu_beta(
            self._ema_c4_mu, self._ema_c4_beta, self.elev_c4_mu, self.elev_c4_beta)
        return self._erd_c4
    '''
    def get_erd(self, update_baseline=False):
        """Srednia ERD z C3+C4.
        NAPRAWA BLEDU EMA: czyta _ema_c3/_ema_c4 bezposrednio –
        NIE wywoluje get_erd_c3/c4 ponownie, zeby uniknac podwojnego EMA.
        W petli zawsze wywoluj najpierw get_erd_c3(), get_erd_c4(),
        potem get_erd() – kolejnosc ma znaczenie."""
        vals = [v for v in [self._ema_c3, self._ema_c4]
                if v is not None]
        if not vals:
            return None
        self._ema_global = float(np.mean(vals))
        return self._ema_global
    '''
    #new
    def get_erd(self, update_baseline=False):
        self._ema_global = float(np.mean([self._erd_c3, self._erd_c4]))
        return self._ema_global

    # ------------------------------------------------------------------
    # JEDEN PASEK DWUKIERUNKOWY – wartosc w zakresie [-1, +1]
    #   < 0  -> lewo,  > 0  -> prawo,  0 -> srodek
    # ------------------------------------------------------------------
    def get_bar_value(self, trial):
        """Wartosc paska sterowanego roznicami mocy (ERD) nad C3 i C4,
        w zaleznosci od wyobrazanej strony.

        Zaklada kontralateralna desynchronizacje:
          LEFT  MI (769) -> ERD nad C4 (prawa polkula) -> pasek w LEWO  (< 0)
          RIGHT MI (770) -> ERD nad C3 (lewa  polkula) -> pasek w PRAWO (> 0)

        Pasek jest DWUKIERUNKOWY: jesli zamiast ERD wystapi ERS (albo
        desynchronizacja pojawi sie po niewlasciwej stronie), wartosc zmienia
        znak i pasek/czastki ida w przeciwna strone.

        Mapowanie ERD -> wychylenie jest TAKIE SAME jak w starszej wersji UI
        (erd_to_drift w cgx_bci_smr_display): -ERD/50, przyciete do [-1, +1].
        -50 % ERD = pelne wychylenie. Brak dodatkowego skalowania.

        Tryb (Config.BAR_LAT_MODE, domyslnie 'contra'):
          'contra' – DOMYSLNY. Tylko kanal kontralateralny do wyobrazanej reki:
                     kierunek = strona cue, wielkosc = sila desynchronizacji.
          'diff'   – indeks lateralizacji: (ERD_C4 - ERD_C3)/50.
        """
        erd_c3 = float(self._erd_c3)   # ostatnia wygladzona wartosc (get_erd_c3)
        erd_c4 = float(self._erd_c4)
        mode   = getattr(Config, 'BAR_LAT_MODE', 'contra')

        # Ta sama stala co erd_to_drift w display – bez osobnego skalowania.
        FULL = 50.0

        if mode == 'diff':
            value = (erd_c4 - erd_c3) / FULL
        else:   # 'contra' – domyslne
            erd_contra = erd_c4 if trial == Config.LEFT else erd_c3
            direction  = -1.0   if trial == Config.LEFT else 1.0
            # -erd_contra > 0 gdy jest desynchronizacja (ERD ujemne)
            value      = direction * (-erd_contra / FULL)

        return float(np.clip(value, -1.0, 1.0))

    # --- Zapis ---
    def save(self):
        if len(self.eeg_data) < 2:
            print("[ZAPIS] Za malo danych – pomijam.")
            return

        data = np.array(self.eeg_data).T   # (n_ch, n_samples)

        info = mne.create_info(
            ch_names=Config.CHANNEL_NAMES,
            sfreq=Config.FS,
            ch_types='eeg'
        )
        raw = mne.io.RawArray(data, info)
        raw.set_montage('standard_1020')

        events_arr = np.array(
            [[int(np.clip(idx, 0, data.shape[1]-1)), 0, code]
             for idx, code in self.markers]
        ) if self.markers else np.zeros((0, 3), dtype=int)

        # Folder MyDataCGX/SUBJECT_ID/ – tworzony jesli nie istnieje
        # przy --tune: folder = subject bez sufiksu _tune, plik ma sufiks _tune
        folder = Config._SAVE_DIR if Config._SAVE_DIR else Config.SUBJECT_ID
        save_dir = os.path.join("../../MyDataCGX", folder)
        os.makedirs(save_dir, exist_ok=True)

        # Automatyczne numerowanie sesji
        sess_num  = 1
        fname_fif = os.path.join(save_dir, f"{Config.SUBJECT_ID}_raw.fif")
        while os.path.exists(fname_fif):
            sess_num += 1
            fname_fif = os.path.join(save_dir,
                                     f"{Config.SUBJECT_ID}_s{sess_num}_raw.fif")
        fname_events = fname_fif.replace("_raw.fif", "_events.npy")

        raw.save(fname_fif, overwrite=False)
        np.save(fname_events, events_arr)
        print(f"[ZAPIS] Sesja {sess_num}: {fname_fif}")
        print(f"[ZAPIS] Eventy:   {fname_events}")
        print(f"[ZAPIS] Katalog:  {os.path.abspath(fname_fif)}")
