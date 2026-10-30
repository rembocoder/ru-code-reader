# xtts_server.py — фоновый сервер озвучки.
# Текст режется на фразы, каждая фраза синтезируется Vosk в отдельный файл в папке say_cache.
# Там же хранится место, где остановилось чтение, — продолжить можно и после перезапуска.
# Vosk грузится по первой просьбе и выгружается через IDLE_MIN минут простоя.
# Если Vosk не загрузился, фразы синтезирует Piper (Руслан).
# Работает и на Windows (Vosk), и на Android в Termux (Piper в proot-Ubuntu) — платформа определяется сама.
# Команды принимает от say.py на 127.0.0.1:50555:
#   SAY <текст>  — новый текст;  TOGGLE — пауза/продолжить;
#   PLAY <текст> — если текст новый, читать его, иначе пауза/продолжить;
#   PREV / NEXT — фраза назад/вперёд;  BACK / FWD — на SEEK_SEC секунд назад/вперёд;
#   SLOWER / FASTER — скорость на SPEED_STEP медленнее/быстрее.

import os, re, sys, gc, socket, threading, time, subprocess, logging, json, shutil
# Кэш скомпилированных под видеокарту вычислений: по умолчанию он мал (256 МБ),
# и CUDA может заново компилировать всё при каждом запуске.
os.environ.setdefault('CUDA_CACHE_MAXSIZE', '4294967296')

ANDROID = 'com.termux' in os.environ.get('PREFIX', '')
BASE = os.path.dirname(os.path.abspath(__file__))     # всё лежит рядом с этим файлом
os.makedirs(BASE, exist_ok=True)
sys.path.insert(0, BASE)
logging.basicConfig(filename=os.path.join(BASE, 'xtts_server.log'), level=logging.INFO,
                    format='%(asctime)s %(message)s', encoding='utf-8')
class _NoHTTP(logging.Filter):
    # без простыни сетевых запросов в логе, как бы ни назывался сетевой модуль
    def filter(self, r):
        return not r.getMessage().startswith('HTTP Request:')
logging.getLogger().handlers[0].addFilter(_NoHTTP())

# ---------- настройки ----------
HOST, PORT = '127.0.0.1', 50555
USE_VOSK = True           # False — всегда читать Piper
VOSK_MODEL = 'vosk-model-tts-ru-0.9-multi'
VOSK_SPEAKER = 3          # 3 — мужской, 2 — женский
VOSK_RATE = 1.1           # больше — быстрее; 1.0 — обычная
LONG_CHARS = 250          # предложение длиннее — режется на несколько фраз
SHORT_CHARS = 0           # предложение короче — приклеивать к следующему; 0 — не приклеивать
SEEK_SEC = 5              # шаг перемотки, сек
SPEED_STEP = 0.1          # шаг изменения скорости (0.1 = 10%)
SPEED_MIN, SPEED_MAX = 0.5, 3.0
VOSK_GPU = False          # True — на видеокарте, False — на процессоре
USE_RUACCENT = False      # ударения и «ё» расставляет RuAccent (точнее словаря Vosk, понимает омографы)
RUACCENT_MODEL = 'tiny2.1'    # модель для омографов (замок/замок): tiny2.1 — легче, turbo3.1 — точнее
RUACCENT_DICT = False     # True — большой словарь RuAccent: точнее, но больше памяти
BERT_ON_GPU = False       # модель ударений на видеокарте: чуть быстрее, но больше памяти
IDLE_MIN = 15             # через сколько минут простоя выгружать модель; 0 — никогда
SENT_PAUSE = 0.5          # пауза после предложения, сек
PARA_PAUSE = 1.0          # пауза между абзацами (пустая строка), сек
LINE_PAUSE = 0.6          # доп. пауза на переводе строки после знака препинания, сек
AUDIO_BUFFER = '1.0'
MPV = shutil.which('mpv') or next((p for p in (r'C:\Program Files\MPV Player\mpv.exe',
                                    r'C:\Program Files\mpv\mpv.exe') if os.path.exists(p)), 'mpv')
PIPER = os.path.join(BASE, r'piper\piper.exe')
PIPER_RU = os.path.join(BASE, r'voices\ru_RU-ruslan-medium.onnx')
PIPER_SPEED = '0.9'       # скорость Руслана: меньше — быстрее
NW = 0x08000000           # не открывать окна

# ---------- телефон (Termux) ----------
UBUNTU = os.path.join(os.environ.get('PREFIX', ''), 'var/lib/proot-distro/containers/ubuntu/rootfs')
ANDROID_PIPER = '/root/piper/piper'                          # пути внутри Ubuntu
ANDROID_VOICE = '/root/voices/ru_RU-ruslan-medium.onnx'
ANDROID_OUT = '/root/tts_out'                                # сюда Piper складывает фразы
if ANDROID:
    USE_VOSK = False
    MPV = 'mpv'
    PIPER_SPEED = '0.85'
POPEN_KW = {'creationflags': NW} if os.name == 'nt' else {}

# Windows урезает скорость фоновым процессам без окна (EcoQoS) — отключаем это для сервера.
# Типы аргументов указаны явно: без них на 64-битной Windows вызовы молча не срабатывают.
if os.name == 'nt':
  try:
    import ctypes
    from ctypes import wintypes
    class _PPTS(ctypes.Structure):
        _fields_ = [('Version', wintypes.ULONG), ('ControlMask', wintypes.ULONG), ('StateMask', wintypes.ULONG)]
    _k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _k32.GetCurrentProcess.restype = wintypes.HANDLE
    _k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _h = _k32.GetCurrentProcess()
    _st = _PPTS(1, 0x1 | 0x4, 0)      # скорость выполнения и таймеры — без урезания
    _ok1 = _k32.SetProcessInformation(_h, 4, ctypes.byref(_st), ctypes.sizeof(_st))
    _e1 = ctypes.get_last_error()
    _ok2 = _k32.SetPriorityClass(_h, 0x80)   # высокий приоритет
    logging.info('отключение экономии: %s (код %s), приоритет: %s', bool(_ok1), _e1, bool(_ok2))
  except Exception:
    logging.exception('не удалось отключить экономию')

import importlib, prep
_prep_mtime = os.path.getmtime(prep.__file__)

def prepare(text):
    # prep.py подхватывается заново, если файл поменяли, — перезапускать сервер не нужно
    global _prep_mtime
    try:
        mt = os.path.getmtime(prep.__file__)
        if mt != _prep_mtime:
            _prep_mtime = mt
            importlib.reload(prep)
            logging.info('prep.py обновлён')
    except Exception:
        logging.exception('не удалось перечитать prep.py, работаю со старым')
    return prep.prepare(text)

def mem_info():
    # Оперативная память процесса сейчас и пиковая, МБ
    if os.name != 'nt':
        try:
            st = open('/proc/self/status').read()
            cur = int(re.search(r'VmRSS:\s+(\d+)', st).group(1)) // 1024
            peak = int(re.search(r'VmHWM:\s+(\d+)', st).group(1)) // 1024
            return '%d МБ (пик %d МБ)' % (cur, peak)
        except Exception:
            return '?'
    try:
        import ctypes
        from ctypes import wintypes
        class PMC(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                        ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                        ('a', ctypes.c_size_t), ('b', ctypes.c_size_t), ('c', ctypes.c_size_t),
                        ('d', ctypes.c_size_t), ('PagefileUsage', ctypes.c_size_t),
                        ('PeakPagefileUsage', ctypes.c_size_t)]
        c = PMC(); c.cb = ctypes.sizeof(c)
        k32 = ctypes.WinDLL('kernel32')
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return '?'
        return '%d МБ (пик %d МБ)' % (c.WorkingSetSize / 2**20, c.PeakWorkingSetSize / 2**20)
    except Exception:
        return '?'

class Timed:
    # Пишет в лог, сколько длится каждый вызов модели — чтобы найти, где задержка
    def __init__(self, sess, name):
        self.sess, self.name = sess, name
    def run(self, *a, **k):
        t = time.time()
        r = self.sess.run(*a, **k)
        logging.info('  %s: %.2f сек', self.name, time.time() - t)
        return r
    def __getattr__(self, n):
        return getattr(self.sess, n)

model = None
accentizer = None
loading = False
lock = threading.Lock()
last_used = time.time()

# ---------- загрузка и выгрузка Vosk ----------
def load_vosk(t0):
    # То же, что vosk_tts.Model, но по шагам с замерами времени, со словарём из кэша
    # и без долгого перебора алгоритмов cuDNN (он тормозит и загрузку, и первые фразы).
    import json, pickle, onnxruntime
    from pathlib import Path
    from vosk_tts import Model, Synth
    from tokenizers.implementations import BertWordPieceTokenizer
    path = Path.home() / '.cache' / 'vosk' / VOSK_MODEL
    opts = onnxruntime.SessionOptions()
    # kSameAsRequested — не захватывать память видеокарты «про запас»
    prov = [('CUDAExecutionProvider', {'cudnn_conv_algo_search': 'HEURISTIC',
                                       'arena_extend_strategy': 'kSameAsRequested'}),
            'CPUExecutionProvider']
    if not VOSK_GPU:
        prov = ['CPUExecutionProvider']
    m = Model.__new__(Model)
    # В модели 17 тысяч узлов, и onnxruntime минуту-две планирует переиспользование памяти.
    # Без этого планирования модель грузится за секунду (памяти при синтезе уходит больше).
    o = onnxruntime.SessionOptions()
    o.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_DISABLE_ALL
    o.enable_mem_reuse = False
    o.enable_mem_pattern = False
    m.onnx = onnxruntime.InferenceSession(str(path / 'model.onnx'), sess_options=o, providers=prov)
    logging.info('Vosk: основная модель за %.1f сек', time.time() - t0)
    cache = path / 'dictionary.pkl'
    if cache.exists():
        m.dic = pickle.load(open(cache, 'rb'))
    else:
        m.dic, probs = {}, {}
        for line in open(path / 'dictionary', encoding='utf-8'):
            items = line.split(maxsplit=2)
            prob = float(items[1])
            if probs.get(items[0], 0) < prob:
                m.dic[items[0]] = items[2]
                probs[items[0]] = prob
        pickle.dump(m.dic, open(cache, 'wb'), protocol=pickle.HIGHEST_PROTOCOL)
    logging.info('Vosk: словарь за %.1f сек', time.time() - t0)
    m.config = json.load(open(path / 'config.json', encoding='utf-8'))
    if (path / 'bert' / 'vocab.txt').exists():
        m.tokenizer = BertWordPieceTokenizer(vocab=str(path / 'bert' / 'vocab.txt'),
                                             unk_token='[UNK]', lowercase=False)
        m.bert_onnx = onnxruntime.InferenceSession(str(path / 'bert' / 'model.onnx'), sess_options=opts,
                                                   providers=prov if BERT_ON_GPU else ['CPUExecutionProvider'])
    else:
        m.tokenizer = None
    logging.info('Vosk: модель ударений за %.1f сек', time.time() - t0)
    m.onnx = Timed(m.onnx, 'голос')
    if m.tokenizer:
        m.bert_onnx = Timed(m.bert_onnx, 'ударения')
    return Synth(m)

def load_model():
    global model, loading
    with lock:
        if model is not None or loading:
            return
        loading = True
    try:
        t0 = time.time()
        import onnxruntime
        try:
            onnxruntime.preload_dlls()
        except Exception:
            pass
        s = load_vosk(t0)
        s.synth_audio('Проверка.', VOSK_SPEAKER)          # прогрев
        with lock:
            model = s
        # ударения догружаются в фоне; до этого Vosk читает со своими словарными
        threading.Thread(target=load_accentizer, daemon=True).start()
        logging.info('Vosk загружен за %.1f сек, работает на: %s, память %s', time.time() - t0,
                     s.model.onnx.get_providers(), mem_info())
    except Exception:
        logging.exception('не удалось загрузить Vosk')
    finally:
        loading = False

def load_accentizer():
    global accentizer
    if not USE_RUACCENT or accentizer is not None:
        return
    t0 = time.time()
    try:
        from ruaccent import RUAccent
        for size in dict.fromkeys([RUACCENT_MODEL, 'tiny2', 'turbo2']):
            try:
                a = RUAccent()
                a.load(omograph_model_size=size, use_dictionary=RUACCENT_DICT)
                break
            except Exception:
                logging.exception('RuAccent: модель %s не загрузилась', size)
        else:
            return
        fix_ruaccent_sessions(a)
        a.process_all('Проверка.')
        if model is None:                   # Vosk успели выгрузить — ударения тоже не держим
            return
        accentizer = a
        logging.info('RuAccent загружен за %.1f сек, память %s', time.time() - t0, mem_info())
    except Exception:
        logging.exception('RuAccent не загрузился — ударения ставит словарь Vosk')

class _FeedFix:
    # Новые transformers не отдают token_type_ids, а моделям RuAccent они нужны — дописываем нули
    def __init__(self, sess):
        self.sess = sess
        self.need = {i.name for i in sess.get_inputs()}
    def run(self, out, feed, *a, **k):
        if 'token_type_ids' in self.need and 'token_type_ids' not in feed and 'input_ids' in feed:
            import numpy as np
            feed = dict(feed, token_type_ids=np.zeros_like(feed['input_ids']))
        return self.sess.run(out, feed, *a, **k)
    def __getattr__(self, n):
        return getattr(self.sess, n)

def fix_ruaccent_sessions(a):
    for part in vars(a).values():
        s = getattr(part, 'session', None)
        if s is not None and hasattr(s, 'get_inputs') and not isinstance(s, _FeedFix):
            part.session = _FeedFix(s)

def accent(text):
    # «выбрасывать» → «выбр+асывать»; потом поправки из prep.STRESS
    if accentizer is not None:
        try:
            text = accentizer.process_all(text)
        except Exception:
            logging.exception('RuAccent не справился: %s', text[:80])
    fix = getattr(prep, 'STRESS', {})
    if fix:
        text = re.sub(r'[а-яёА-ЯЁ+]+', lambda m: fix.get(m.group().replace('+', '').lower(), m.group()), text)
    return text

def unload_model():
    global model, accentizer
    with lock:
        model = None
        accentizer = None
    gc.collect()
    logging.info('Vosk выгружен по простою')

def idle_watcher():
    while True:
        time.sleep(30)
        busy = R.synth_alive() or R.playing()
        if IDLE_MIN and model is not None and not busy and time.time() - last_used > IDLE_MIN * 60:
            unload_model()

# ---------- нарезка на фразы ----------
def split_long(s, limit=LONG_CHARS):
    # Очень длинное предложение (лог, список без точек) Vosk синтезирует долго и съедает
    # гигабайты памяти — режем его по запятым, а если их нет, по пробелам.
    if len(s) <= limit:
        return [s]
    out, cur = [], ''
    for piece in re.split(r'(?<=,)\s+', s):
        while len(piece) > limit:
            cut = piece.rfind(' ', 0, limit)
            cut = cut if cut > 0 else limit
            if cur:
                out.append(cur); cur = ''
            out.append(piece[:cut]); piece = piece[cut:].strip()
        if cur and len(cur) + len(piece) + 1 > limit:
            out.append(cur); cur = piece
        else:
            cur = (cur + ' ' + piece).strip()
    if cur:
        out.append(cur)
    return out

def make_phrases(text):
    # -> список {'text': фраза, 'pause': пауза перед ней, сек}
    # Фраза — предложение (до . ! ? …) или строка, которая кончается знаком препинания
    # (их prep.py отмечает знаком ǀ); длинные режутся, совсем короткие приклеиваются к следующей.
    t = re.sub(r'\s*ʘ\s*', ' ', text).replace('ǂ', '')
    out = []
    for pi, para in enumerate(t.split('ǁ')):
        for li, line in enumerate(para.split('ǀ')):
            extra = LINE_PAUSE if li else (PARA_PAUSE if pi else 0)
            sents = [s.strip().lstrip(' ,;:.!?') for s in re.split(r'(?<=[.!?…])\s+', line)]
            sents = [part for s in sents if re.search(r'\w', s) for part in split_long(s)]
            merged = []
            for s in sents:
                if merged and len(merged[-1]) < SHORT_CHARS:
                    merged[-1] += ' ' + s
                else:
                    merged.append(s)
            for k, s in enumerate(merged):
                out.append({'text': s, 'pause': (SENT_PAUSE + (extra if k == 0 else 0)) if out else 0.0})
    return out

# ---------- синтез одной фразы ----------
RATE = 22050
def synth_phrase(text):
    # -> сырые 16-битные отсчёты 22050 Гц
    global last_used
    last_used = time.time()
    if USE_VOSK and model is not None:
        t0 = time.time()
        text = accent(text)
        b = model.synth_audio(text, VOSK_SPEAKER, speech_rate=VOSK_RATE).tobytes()
        logging.info('%.1f сек звука за %.1f сек, память %s: %s', len(b) / (2 * RATE),
                     time.time() - t0, mem_info(), text[:80])
        return b
    if ANDROID:
        return proot_piper.synth(text)
    p = subprocess.run([PIPER, '-q', '--output_raw', '-m', PIPER_RU, '--length_scale', PIPER_SPEED],
                       input=text.encode('utf-8'), capture_output=True, **POPEN_KW)
    return p.stdout

class ProotPiper:
    # Телефон: Piper живёт в proot-Ubuntu. Держим один процесс, чтобы не грузить голос на каждую фразу:
    # он получает фразу строкой и кладёт её в отдельный wav в ANDROID_OUT, печатая путь к файлу.
    def __init__(self):
        self.p, self.lock = None, threading.Lock()

    def start(self):
        os.makedirs(UBUNTU + ANDROID_OUT, exist_ok=True)
        self.p = subprocess.Popen(
            # nice — синтез не должен отнимать процессор у телефона (и у чтения буфера)
            ['nice', '-n', '10', 'proot-distro', 'login', 'ubuntu', '--', ANDROID_PIPER, '-q', '-m', ANDROID_VOICE,
             '--length_scale', PIPER_SPEED, '--output_dir', ANDROID_OUT],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        logging.info('Piper запущен в Ubuntu')

    def readline(self, timeout):
        import select
        buf = b''
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.p.stdout], [], [], 0.5)
            if r:
                ch = os.read(self.p.stdout.fileno(), 1)
                if not ch:
                    return None
                if ch == b'\n':
                    return buf.decode('utf-8', 'ignore').strip()
                buf += ch
            elif self.p.poll() is not None:
                return None
        return None

    def synth(self, text):
        import wave
        with self.lock:
            for attempt in (1, 2):
                try:
                    if self.p is None or self.p.poll() is not None:
                        self.start()
                    self.p.stdin.write(text.replace('\n', ' ').encode('utf-8') + b'\n')
                    self.p.stdin.flush()
                    while True:
                        line = self.readline(60)
                        if line is None:
                            raise OSError('Piper не ответил')
                        if line.endswith('.wav'):
                            break
                    path = UBUNTU + line if line.startswith('/') else line
                    with wave.open(path, 'rb') as w:
                        data = w.readframes(w.getnframes())
                    os.remove(path)
                    return data
                except Exception:
                    logging.exception('Piper: попытка %d не удалась', attempt)
                    try:
                        self.p.kill()
                    except Exception:
                        pass
                    self.p = None
        # запасной путь: отдельный запуск на фразу
        r = subprocess.run(['nice', '-n', '10', 'proot-distro', 'login', 'ubuntu', '--', ANDROID_PIPER, '-q', '--output_raw',
                            '-m', ANDROID_VOICE, '--length_scale', PIPER_SPEED],
                           input=text.encode('utf-8'), capture_output=True)
        return r.stdout

proot_piper = ProotPiper()

def ensure_model():
    # Vosk грузится несколько секунд — ждём его
    if not USE_VOSK or model is not None:
        return
    load_model()
    for _ in range(600):
        if model is not None or not loading:
            break
        time.sleep(0.1)

# ---------- связь с mpv: на какой секунде он играет ----------
class MpvIPC:
    def __init__(self, path):
        self.path, self.f, self.rid = path, None, 0
        self.lock = threading.Lock()
    def _open(self):
        if self.f:
            return True
        try:
            if os.name == 'nt':
                self.f = open(self.path, 'r+b', buffering=0)
            else:
                s = socket.socket(socket.AF_UNIX); s.connect(self.path)
                self.f = s.makefile('rwb', buffering=0)
            self.buf = b''
            return True
        except OSError:
            return False
    def _readline(self):
        while b'\n' not in self.buf:
            d = self.f.read(4096)
            if not d:
                raise OSError('mpv закрылся')
            self.buf += d
        line, _, self.buf = self.buf.partition(b'\n')
        return line
    def time_pos(self):
        return self.command('get_property', 'time-pos')
    def command(self, *args):
        with self.lock:
            if not self._open():
                return None
            try:
                self.rid += 1
                self.f.write((json.dumps({'command': list(args), 'request_id': self.rid}) + '\n').encode())
                while True:
                    r = json.loads(self._readline())
                    if r.get('request_id') == self.rid:
                        return r.get('data')
            except (OSError, ValueError):
                return None
    def close(self):
        try:
            self.f and self.f.close()
        except OSError:
            pass

# ---------- чтение: фразы, файлы, место ----------
CACHE = os.path.join(BASE, 'say_cache')
STATE = os.path.join(CACHE, 'state.json')

class Reader:
    def __init__(self):
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)
        self.items, self.durs, self.pos, self.gen = [], [], [0, 0.0], 0
        self.src = ''                # отпечаток исходного текста — чтобы понять, новый ли он
        self.speed = 1.0            # скорость воспроизведения; при запуске сервера и новом тексте — 1.0
        self.synth_th = None
        self.play = None            # {'gen', 'stop', 'proc', 'ipc', 'segs', 'thread'}
        self.saved_at = 0
        try:
            st = json.load(open(STATE, encoding='utf-8'))
            self.items, self.durs, self.pos = st['items'], st['durs'], st['pos']
            self.src = st.get('src', '')
            for i, d in enumerate(self.durs):      # файл мог пропасть
                if d is not None and not os.path.exists(self.file(i)):
                    self.durs[i] = None
            logging.info('восстановлено: %d фраз, место %s', len(self.items), self.pos)
        except Exception:
            pass

    def file(self, i):
        return os.path.join(CACHE, '%04d.raw' % i)

    def save(self):
        with self.lock:
            st = {'items': self.items, 'durs': self.durs, 'pos': self.pos, 'src': self.src}
        try:
            os.makedirs(CACHE, exist_ok=True)
            tmp = STATE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(st, f, ensure_ascii=False)
            os.replace(tmp, STATE)
        except OSError:
            logging.exception('не удалось сохранить место')

    def total(self, i):
        # длительность фразы i вместе с паузой перед ней; None — ещё не синтезирована
        d = self.durs[i]
        return None if d is None else self.items[i]['pause'] + d

    # --- синтез всех фраз в фоне: сначала от текущего места, потом остальные ---
    def synth_alive(self):
        return self.synth_th is not None and self.synth_th.is_alive()

    def start_synth(self):
        if self.synth_alive() or all(d is not None for d in self.durs):
            return
        gen = self.gen
        self.synth_th = threading.Thread(target=self._synth_loop, args=(gen,), daemon=True)
        self.synth_th.start()

    def _synth_loop(self, gen):
        ensure_model()
        while True:
            with self.lock:
                if gen != self.gen:
                    return
                missing = [i for i, d in enumerate(self.durs) if d is None]
                if not missing:
                    return
                cur = self.pos[0]
                i = next((k for k in missing if k >= cur), missing[0])
                text = self.items[i]['text']
            try:
                b = synth_phrase(text)
            except Exception:
                logging.exception('не удалось синтезировать: %s', text[:80])
                b = b''
            with self.lock:
                if gen != self.gen:
                    return
                os.makedirs(CACHE, exist_ok=True)
                with open(self.file(i), 'wb') as f:
                    f.write(b)
                self.durs[i] = len(b) / (2 * RATE)
                self.cond.notify_all()
            self.save()

    # --- воспроизведение ---
    def playing(self):
        p = self.play
        return p is not None and p['thread'].is_alive()

    def live_pos(self):
        # текущее место: у играющего mpv спрашиваем секунду и переводим в (фраза, смещение)
        with self.lock:
            p = self.play
            if p is None or not p['thread'].is_alive():
                return list(self.pos)
        t = p['ipc'].time_pos()
        with self.lock:
            if t is None or not p['segs']:
                return list(self.pos)
            for start, i, off in reversed(p['segs']):
                if t >= start:
                    return [i, off + (t - start)]
            return list(self.pos)

    def stop_play(self):
        p = self.play
        if p is None:
            return
        pos = self.live_pos() if p['thread'].is_alive() else None
        p['stop'].set()
        try:
            p['proc'].kill()
        except Exception:
            pass
        p['thread'].join(timeout=3)
        p['ipc'].close()
        with self.lock:
            if pos is not None:
                self.pos = pos
            self.play = None
        self.save()

    def start_play(self):
        with self.lock:
            if not self.items:
                return
            if self.pos[0] >= len(self.items):        # дослушано до конца — сначала
                self.pos = [0, 0.0]
            self.nplay = getattr(self, 'nplay', 0) + 1      # у каждого запуска mpv свой канал
            name = 'say_mpv_%d_%d' % (os.getpid(), self.nplay)
            import tempfile
            ipc_path = r'\\.\pipe\%s' % name if os.name == 'nt' else os.path.join(tempfile.gettempdir(), name)
            proc = subprocess.Popen(
                [MPV, '--no-video', '--really-quiet', '--idle=no', f'--audio-buffer={AUDIO_BUFFER}',
                 f'--input-ipc-server={ipc_path}', f'--speed={self.speed}',
                 '--demuxer=rawaudio', '--demuxer-rawaudio-format=s16le',
                 f'--demuxer-rawaudio-rate={RATE}', '--demuxer-rawaudio-channels=1', '-'] + MPV_EXTRA,
                stdin=subprocess.PIPE, **POPEN_KW)
            p = {'gen': self.gen, 'stop': threading.Event(), 'proc': proc,
                 'ipc': MpvIPC(ipc_path), 'segs': []}
            p['thread'] = threading.Thread(target=self._play_loop, args=(p,), daemon=True)
            self.play = p
        self.start_synth()
        p['thread'].start()
        threading.Thread(target=self._track, args=(p,), daemon=True).start()

    def _play_loop(self, p):
        global last_used
        stream_t = 0.0
        with self.lock:
            i, off = self.pos
        try:
            while not p['stop'].is_set():
                with self.lock:
                    if i >= len(self.items):
                        break
                    while self.durs[i] is None and not p['stop'].is_set():
                        if not self.synth_alive():
                            self.start_synth()
                        self.cond.wait(0.5)
                    if p['stop'].is_set():
                        break
                    pause = self.items[i]['pause']
                    path = self.file(i)
                try:
                    audio = open(path, 'rb').read()
                except OSError:
                    audio = b''
                data = b'\x00\x00' * int(RATE * pause) + audio
                start = min(int(off * RATE) * 2, len(data))
                with self.lock:
                    p['segs'].append((stream_t, i, off))
                chunk = data[start:]
                p['proc'].stdin.write(chunk)
                p['proc'].stdin.flush()
                stream_t += len(chunk) / (2 * RATE)
                last_used = time.time()
                i, off = i + 1, 0.0
            p['proc'].stdin.close()
        except (OSError, ValueError):
            pass
        if not p['stop'].is_set():
            p['proc'].wait()
            with self.lock:
                if self.play is p and i >= len(self.items):
                    self.pos = [len(self.items), 0.0]       # дослушано до конца
                    self.play = None
            self.save()

    def _track(self, p):
        # раз в полсекунды запоминаем место, раз в секунду пишем на диск
        while p['thread'].is_alive() and not p['stop'].is_set():
            time.sleep(0.5)
            pos = self.live_pos()
            with self.lock:
                if self.play is p and not p['stop'].is_set():
                    self.pos = pos
            if time.time() - self.saved_at > 1:
                self.saved_at = time.time()
                self.save()

    # --- команды ---
    def say(self, text, src=''):
        self.stop_play()
        with self.lock:
            self.src = src
            self.gen += 1
            shutil.rmtree(CACHE, ignore_errors=True)
            self.items = make_phrases(text)
            self.durs = [None] * len(self.items)
            self.pos = [0, 0.0]
            self.speed = 1.0
        self.save()
        logging.info('новый текст: %d фраз', len(self.items))
        self.start_play()

    def toggle(self):
        if self.playing():
            self.stop_play()
            logging.info('пауза на %s', self.pos)
        else:
            self.start_play()

    def move(self, how):
        was = self.playing()
        if was:
            self.stop_play()
        with self.lock:
            n = len(self.items)
            if not n:
                return
            i, off = self.pos
            if how == 'PREV':
                i, off = max(0, min(i, n) - 1), 0.0
            elif how == 'NEXT':
                i, off = min(n, i + 1), 0.0
            elif how == 'BACK':
                if i >= n:
                    i, off = n, 0.0
                off -= SEEK_SEC
                while off < 0 and i > 0:
                    tot = self.total(i - 1)
                    if tot is None:
                        break
                    i -= 1
                    off += tot
                if off < 0:
                    off = 0.0
            elif how == 'FWD':
                off += SEEK_SEC
                while i < n:
                    tot = self.total(i)
                    if tot is None:                 # ещё не синтезирована — ждём
                        self.start_synth()
                        if not self.cond.wait(10):
                            break
                        continue
                    if off < tot:
                        break
                    off -= tot
                    i += 1
                if i >= n:
                    i, off = n, 0.0
            self.pos = [i, off]
        self.save()
        logging.info('%s → %s', how, self.pos)
        if was and self.pos[0] < len(self.items):
            self.start_play()

    def set_speed(self, delta):
        with self.lock:
            self.speed = round(min(SPEED_MAX, max(SPEED_MIN, self.speed + delta)), 2)
            p = self.play
        if p is not None and p['thread'].is_alive():
            p['ipc'].command('set_property', 'speed', self.speed)
        logging.info('скорость %.1f', self.speed)

R = Reader()
MPV_EXTRA = []

# ---------- приём команд ----------
cmd_lock = threading.Lock()

def handle(conn):
    with conn:
        data = b''
        while True:
            b = conn.recv(65536)
            if not b:
                break
            data += b
    cmd, _, body = data.decode('utf-8', 'ignore').partition('\n')
    cmd = cmd.strip()
    with cmd_lock:
        try:
            src = __import__('hashlib').md5(body.strip().encode('utf-8')).hexdigest()
            if cmd == 'PLAY' and (src == R.src or not body.strip()):
                cmd = 'TOGGLE'                      # текст тот же — просто пауза/продолжить
                logging.info('PLAY: текст тот же (%s…) — пауза/продолжить', body.strip()[:30])
            if cmd in ('SAY', 'PLAY'):
                text = prepare(body)
                with open(os.path.join(BASE, 'say_last.txt'), 'w', encoding='utf-8') as f:
                    f.write(text)
                if re.search(r'\w', text):
                    R.say(text, src)
            elif cmd in ('TOGGLE', 'STOP'):
                R.toggle()
            elif cmd in ('PREV', 'NEXT', 'BACK', 'FWD'):
                R.move(cmd)
            elif cmd in ('SLOWER', 'FASTER'):
                R.set_speed(SPEED_STEP if cmd == 'FASTER' else -SPEED_STEP)
        except Exception:
            logging.exception('ошибка команды %s', cmd)

def main():
    srv = socket.socket()
    try:
        srv.bind((HOST, PORT))
    except OSError:
        return                     # сервер уже запущен
    srv.listen()
    logging.info('сервер запущен')
    threading.Thread(target=idle_watcher, daemon=True).start()
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()

if __name__ == '__main__':
    main()
