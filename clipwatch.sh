# clipwatch.sh — телефон: раз в полсекунды сохраняет буфер обмена в ~/clip.txt.
# Нужен потому, что Android отдаёт буфер только пока Termux на экране, а кнопки в шторке — уже «фон».
while true; do c=$(termux-clipboard-get 2>/dev/null); [ -n "$c" ] && printf "%s" "$c" > ~/clip.txt; sleep 0.5; done
