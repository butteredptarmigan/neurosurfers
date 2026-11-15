# config.py
# ============================================================================
# 1. KONFIGURACJA
# ============================================================================

class Config:
    # --- UNICORN HYBRID BLACK / LSL ---
    #Unicorn
    FS = 250   # Unicorn Hybrid Black: 250 Hz
    LSL_STREAM_NAME = "UnicornRecorderLSLStream"   # domyslna nazwa z Unicorn Recorder
    #CGX
    #FS = 500   # CGX Quick-20r wysyla 500 Hz
    #Biosemi
    #FS = 1024
    # Indeksy kanalow w strumieniu LSL i odpowiadajace im nazwy

    # Unicorn: strumien LSL = 17 kanalow: 0-7 EEG, 8-10 akcelerometr, 11-13 zyroskop,
    # 14 bateria, 15 licznik, 16 validation indicator. Do przetwarzania tylko EEG.
    LSL_CHANNEL_IDX = list(range(8))
    # nagranka (CGX)
    #LSL_CHANNEL_IDX = [1, 2, 4, 5, 6, 7, 8, 11, 12, 14, 17]
    # terazniejszy
    #LSL_CHANNEL_IDX = [1, 2, 4, 5, 6, 7, 8, 11, 12, 13, 14, 17, 18]

    # Unicorn Hybrid Black (stale pozycje elektrod, kolejnosc = kanaly 1-8)
    CHANNEL_NAMES = ['Fz', 'C3', 'Cz', 'C4', 'Pz', 'PO7', 'Oz', 'PO8']
    #nagranka (CGX)
    #CHANNEL_NAMES = ['Fp1', 'Fp2', 'F3', 'Fz', 'F4', 'C3', 'Cz', 'Pz', 'P4', 'P3', 'C4']
    #biosemi
    #CHANNEL_NAMES = ['Fp1', 'Fp2', 'F3', 'F1', 'Fz', 'F2', 'F4', 'FC5', 'FC3', 'FC1', 'FCz', 'FC2', 'FC4', 'FC6', 'T7', 'C5', 'C3', 'C1', 'Cz', 'C2', 'C4', 'C6', 'T8', 'CP5', 'CP3', 'CP1', 'CPz', 'CP2', 'CP4', 'CP6', 'P3', 'P1', 'Pz', 'P2', 'P4', 'EXG7', 'EXG8']
    #terazniejszy
    #CHANNEL_NAMES = ['Fp1', 'Fp2', 'F3', 'Fz', 'F4', 'C3', 'Cz', 'Pz', 'P4', 'T3', 'P3', 'C4', 'T4']

    #Unicorn / CGX
    N_CHANNELS      = len(LSL_CHANNEL_IDX)   # 8
    #Biosemi
    #N_CHANNELS       = len(CHANNEL_NAMES)

    # Indeksy w CHANNEL_NAMES (Unicorn):
    # Fz=0, C3=1, Cz=2, C4=3, Pz=4, PO7=5, Oz=6, PO8=7

    # Unicorn
    SMR_CHANNELS   = [1, 3]   # C3, C4
    #nagranka (CGX)
    #SMR_CHANNELS   = [5, 10]   # C3, C4
    #biosemi
    #SMR_CHANNELS = [16, 20]  # C3, C4
    #terazniejszy
    #SMR_CHANNELS = [5, 11]


    # Unicorn nie ma Fp1/Fp2 – najblizej oczu jest Fz (slabszy detektor mrugniec)
    BLINK_CHANNELS = [0]     # Fz
    #BLINK_CHANNELS = [0, 1]  # Fp1, Fp2 (CGX)

    # --- LAPLASJAN PRZESTRZENNY ---
    # Duzy laplasjan (large Laplacian) dla C3 i C4.
    # Wzor: center - 0.25*(top + bottom + left + right)

    # Unicorn: brak F3/F4/P3/P4 – jedynym sensownym sasiadem C3 i C4 jest Cz
    # (roznica C3-Cz / C4-Cz). Domyslnie USE_LAPLACIAN=False (surowe C3/C4).
    LAPLACIAN_C3 = {'center': 1, 'neighbors': [2]}   # Cz
    LAPLACIAN_C4 = {'center': 3, 'neighbors': [2]}   # Cz
    # nagranka (CGX)
    #LAPLACIAN_C3 = {'center': 5,  'neighbors': [2, 9, 6]}   # F3, P3, Cz
    #LAPLACIAN_C4 = {'center': 10, 'neighbors': [4, 8, 6]}   # F4, P4, Cz

    #biosemi
    #LAPLACIAN_C3 = {'center': 16,  'neighbors': [2, 30, 18, 14]}   # F3, P3, Cz T7
    #LAPLACIAN_C4 = {'center': 20, 'neighbors': [6, 34, 18, 22]}   # F4, P4, Cz T8

    #terazniejszy
    #LAPLACIAN_C3 = {'center': 5,  'neighbors': [2, 10, 6, 9]}   # F3, P3, Cz, T3
    #LAPLACIAN_C4 = {'center': 11, 'neighbors': [4, 8, 6, 12]}   # F4, P4, Cz, T4

    # Przelacznik – nadpisywany przez argparse (--laplacian)
    USE_LAPLACIAN = False
    WEIGHTED_ERD  = False   # --weighted-erd: wazona srednia ERD mu/beta
    BAND_MODE = 'both'  # nadpisywane przez --mu-only / --beta-only

    # [CLASSIFIER ONLINE] Kanaly do klasyfikacji FBCSP (bez EOG Fp1/Fp2)
    # Unicorn: kanaly sensomotoryczne (PO7/Oz/PO8 pomijamy – dominuje alfa wzrokowa)
    CLF_CHANNELS = ['Fz', 'C3', 'Cz', 'C4', 'Pz']
    #CLF_CHANNELS = ['F3', 'Fz', 'F4', 'C3', 'Cz', 'C4', 'P3', 'Pz', 'P4']  # CGX

    # --- PRZETWARZANIE SYGNALU ---
    MU_BAND_DEFAULT  = [8.0, 15.0] #ping teraz do badania tego nie uzywamy - ale przyda sie pozniej do analiz
    SMR_BAND_DEFAULT = [15.0, 22.0] # nie uzywane

    #Unicorn
    BUFFER_SIZE    = 1250   # 5s bufora przy 250 Hz
    #CGX
    #BUFFER_SIZE    = 2500   # 5s bufora przy 500 Hz
    #Biosemi
    #BUFFER_SIZE     = 5120
    POWER_WINDOW_S = 2      # okno obliczania mocy RMS (s)
    SMOOTHING      = 0.06   # EMA feedback (nie uzywane aktywnie – patrz get_erd)

    # --- BASELINE ---
    BASELINE_SECONDS = 60.0   # dlugosc bloku kalibracyjnego (tryb 2a)
    BASELINE_ALPHA   = 0.08   # ping bylo 0.08 wspolczynnik rolling baseline (EMA)
    CALIBRATION_START_S = 10.0  # od ktorej sekundy bloku zbierac probki
    CALIBRATION_DURATION_S = 40.0  # przez ile sekund zbierac probki do baseline'u

    # --- METRYKA ERD/ERS ---
    DEAD_ZONE_THRESHOLD = 4.0    # ignoruj |metryka| < prog (%)
    TANH_SCALE          = 120.0   # ping bylo 20 skala mapowania tanh

    # --- PARADYGMAT ---
    N_TRIALS   = 30
    REST_TIME  = 2.0
    CUE_TIME   = 1.25
    MI_TIME    = 4.0
    BREAK_TIME = 1.5

    # --- MARKERY IV BCI 2b ---
    LEFT        = 769
    RIGHT       = 770
    TRIAL_START = 768
    STOP        = 999

    # --- PROGI FEEDBACKU (%) ---
    TH_EXCELLENT = -25.0
    TH_GOOD      = -14.0
    TH_WEAK      = -7.0

    # --- OKNO ---
    #WIDTH, HEIGHT = 800, 600
    WIDTH, HEIGHT = 1920, 1080

    # --- ZAPIS ---
    SUBJECT_ID = "subject01"

    # --- TRYBY (nadpisywane przez argparse) ---
    BASELINE_PER_TRIAL = False
    ROLLING_BASELINE = False
    TUNE_MODE = False   # --tune: 60 prob, brak modelu, brak feedbacku, sufiks _tune
    _SAVE_DIR = None  # folder zapisu (None = uzyj SUBJECT_ID)

    # [CLASSIFIER ONLINE] okno epoki do klasyfikacji
    # Marker zapisywany w momencie CUE (strzalka), MI zaczyna sie po CUE_TIME=1.25s
    # Okno odpowiada EPOCH_TMIN + CUE_TIME i EPOCH_TMAX + CUE_TIME z cgx_transfer_gs
    #CLF_EPOCH_TMIN = 1.25  # 0.5 + 1.25s (CUE_TIME)
    #CLF_EPOCH_TMAX = 4.75  # 4.0 + 1.25s (CUE_TIME)

    # [CLASSIFIER ONLINE] okno epoki do klasyfikacji
    CLF_EPOCH_TMIN = 1.5 # s po cue
    CLF_EPOCH_TMAX = 5  # s po cue

    # ========================================================================
    # [CSP-LDA] Klasyfikator CSP+LDA + pasek online (proof of concept)
    # ========================================================================
    # Pasmo najlepsze wg eksperymentow uzytkownika (dlugie okno 0.75-4.25s)
    CLF_BAND         = [8.0, 15.0]
    CLF_N_COMPONENTS = 6            # liczba filtrow CSP (parzysta)
    CLF_TRAIN_N_TRIALS = 60         # domyslna liczba pierwszych trialow do nauki

    # Okna augmentacji [s po markerze] - kazde 1 s = okno online.
    # 6 przesuniec pokrywa faze MI, ucza klasyfikator niezaleznosci od czasu.
    CLF_TRAIN_WINDOWS = [
        (1.0, 2.0), (1.5, 2.5), (2.0, 3.0),
        (2.5, 3.5), (3.0, 4.0), (3.5, 4.5),
    ]

    # --- Pasek online sterowany decyzja klasyfikatora ---
    CLF_WINDOW_S     = 1.0          # dlugosc okna klasyfikacji online (s)
    CLF_STEP_S       = 1.0 / 16.0   # co ile sekund nowa decyzja (1/16 s)
    CLF_BAR_MAX_STEPS = 32          # zakres paska w krokach od centrum
    CLF_BAR_CONF_GATE = 0.0         # min. pewnosc (0-1) by ruszyc pasek (0=zawsze)



### zajebane z diag
MU_BAND = (8.0, 15.0)
# Unicorn (brak F3/F4/P3/P4)
LAPLACIAN_NEIGHBORS = {
    'C3': ['Cz'],
    'Cz': ['Fz', 'C3', 'C4', 'Pz'],
    'C4': ['Cz'],
}
#nagrania (CGX)
'''
LAPLACIAN_NEIGHBORS = {
    'C3': ['F3', 'Cz', 'P3'],
    'Cz': ['Fz', 'C3', 'C4', 'Pz'],
    'C4': ['F4', 'Cz', 'P4'],
}
'''

#biosemi T7 i T8 do weryfikacji
'''
LAPLACIAN_NEIGHBORS = {
    'C3': ['F3', 'Cz', 'P3', 'T7'],
    'Cz': ['Fz', 'C3', 'C4', 'Pz'],
    'C4': ['F4', 'Cz', 'P4', 'T8'],
}
'''
'''
#
#terazniejszy
LAPLACIAN_NEIGHBORS = {
    'C3': ['F3', 'Cz', 'P3', 'T3'],
    'Cz': ['Fz', 'C3', 'C4', 'Pz'],
    'C4': ['F4', 'Cz', 'P4', 'T4'],
}
'''
SMR_PRED_STRONG = 6.0
SMR_PRED_MODERATE = 3.0