# say.py — отдаёт команды серверу озвучки (Windows и телефон с Termux).
#   say.py          — прочитать буфер обмена
#   say.py file F   — прочитать текст из файла F
#   say.py play     — новый текст в буфере — читать его, тот же — пауза/продолжить
#   say.py toggle   — пауза / продолжить (и после перезапуска сервера)
#   say.py prev     — к прошлой фразе       say.py next   — к следующей
#   say.py back     — на 5 секунд назад     say.py fwd    — на 5 секунд вперёд
#   say.py slower   — на 10% медленнее      say.py faster — на 10% быстрее
# Если сервер не запущен, запускает его сам.

import os, socket, subprocess, sys, time

HOST, PORT = '127.0.0.1', 50555
ANDROID = 'com.termux' in os.environ.get('PREFIX', '')
SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'xtts_server.py')   # лежит рядом
CLIP = os.path.expanduser('~/clip.txt')           # телефон: его обновляет clipwatch.sh
# на Windows сервер запускается через pythonw.exe — без окна
_w = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
PYTHONW = _w if os.name == 'nt' and os.path.exists(_w) else sys.executable

def send(msg):
    with socket.create_connection((HOST, PORT), timeout=1) as s:
        s.sendall(msg.encode('utf-8'))

def clipboard():
    if ANDROID:
        # сначала спрашиваем буфер напрямую; если Android не отдал — берём то, что сохранил clipwatch.sh
        try:
            r = subprocess.run(['termux-clipboard-get'], capture_output=True, timeout=5)
            text = r.stdout.decode('utf-8', 'ignore')
            if text.strip():
                return text
        except Exception:
            pass
        try:
            return open(CLIP, encoding='utf-8', errors='ignore').read()
        except OSError:
            return ''
    import tkinter
    try:
        r = tkinter.Tk(); r.withdraw(); text = r.clipboard_get(); r.destroy()
        return text
    except tkinter.TclError:
        return ''

arg = sys.argv[1].lower() if len(sys.argv) > 1 else 'say'
if arg == 'file' and len(sys.argv) > 2:      # текст из файла (на телефоне — через «Поделиться»)
    try:
        text = open(sys.argv[2], encoding='utf-8', errors='ignore').read()
    except OSError:
        sys.exit()
    if not text.strip():
        sys.exit()
    msg = 'SAY\n' + text
elif arg in ('say', 'play'):
    text = clipboard()
    if arg == 'say' and not text.strip():
        sys.exit()
    msg = arg.upper() + '\n' + text
elif arg in ('toggle', 'stop', 'prev', 'next', 'back', 'fwd', 'slower', 'faster'):
    msg = {'stop': 'TOGGLE'}.get(arg, arg.upper()) + '\n'
else:
    sys.exit()

def start_server():
    if ANDROID:
        subprocess.Popen([PYTHONW, SERVER], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    else:
        subprocess.Popen([PYTHONW, SERVER], creationflags=0x08000000 | 0x00000008)

try:
    send(msg)
except OSError:
    start_server()
    for _ in range(80):            # ждём до 20 секунд, пока сервер откроет порт
        time.sleep(0.25)
        try:
            send(msg)
            break
        except OSError:
            pass
