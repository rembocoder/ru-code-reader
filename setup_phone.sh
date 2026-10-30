#!/data/data/com.termux/files/usr/bin/bash
# setup_phone.sh — ставит озвучку (Руслан + prep.py, пауза и переходы по фразам) в Termux.
# Запуск: bash setup_phone.sh   (из папки, где лежат prep.py, xtts_server.py, say.py, clipwatch.sh)
# Piper и голос Руслана должны уже стоять внутри proot-Ubuntu — см. README.md.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/tts ~/.shortcuts
for f in prep.py xtts_server.py say.py; do
    [ -f "$SRC/$f" ] || { echo "Нет $SRC/$f"; exit 1; }
    cp "$SRC/$f" ~/tts/
done
cp "$SRC/clipwatch.sh" ~/clipwatch.sh
echo "Файлы скопированы в ~/tts"

pip install -q num2words pymorphy3 cmudict
echo "Библиотеки для prep.py установлены"

pkill -f tts/xtts_server.py 2>/dev/null || true

# уведомление-плеер: ⏮ прошлая фраза, ▶ читать буфер с начала, ⏸ новый текст — читать, тот же — пауза/продолжить, ⏭ следующая
PY=/data/data/com.termux/files/usr/bin/python3
SAY=/data/data/com.termux/files/home/tts/say.py
LINE="termux-notification --id say --ongoing --type media --title \"Озвучка\" --media-previous \"$PY $SAY prev\" --media-play \"$PY $SAY say\" --media-pause \"$PY $SAY play\" --media-next \"$PY $SAY next\""
CLIP='pgrep -f clipwatch.sh >/dev/null || (nohup bash ~/clipwatch.sh >/dev/null 2>&1 &)'
touch ~/.bashrc
cp ~/.bashrc ~/.bashrc.bak
grep -v 'termux-notification --id say' ~/.bashrc.bak | grep -v 'clipwatch' > ~/.bashrc || true
echo "$CLIP" >> ~/.bashrc
echo "$LINE" >> ~/.bashrc
eval "$CLIP"
termux-notification-remove say 2>/dev/null || true
eval "$LINE"
echo "Уведомление и clipwatch настроены (старый .bashrc — в ~/.bashrc.bak)"

printf '#!/data/data/com.termux/files/usr/bin/bash\n%s %s play\n' "$PY" "$SAY" > ~/.shortcuts/say
chmod +x ~/.shortcuts/say
echo "Готово. Скопируй текст в Termux, подожди секунду и нажми кнопку в уведомлении."
