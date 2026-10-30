#Requires AutoHotkey v2.0
; Озвучка: Ctrl+Alt+S — прочитать выделенное (буфер обмена), Ctrl+Alt+X — пауза/продолжить,
; Ctrl+Alt+, и Ctrl+Alt+. — фраза назад/вперёд, Ctrl+Alt+[ и Ctrl+Alt+] — на 5 секунд назад/вперёд,
; Ctrl+Alt+; и Ctrl+Alt+' — на 10% медленнее/быстрее.
; Клавиши заданы кодами (vk…), чтобы работали и в русской раскладке.

; say.py ищется рядом с этим файлом, pythonw.exe — в PATH (галочка «Add to PATH» при установке Python)
PY := 'pythonw.exe "' A_ScriptDir '\say.py"'
Say(cmd := "") => Run(PY (cmd ? " " cmd : ""),, "Hide")

^!vk53::Say()            ; S
^!vk58::Say("toggle")    ; X
^!vkBC::Say("prev")      ; , (Б)
^!vkBE::Say("next")      ; . (Ю)
^!vkDB::Say("back")      ; [ (Х)
^!vkDD::Say("fwd")       ; ] (Ъ)
^!vkBA::Say("slower")    ; ; (Ж)
^!vkDE::Say("faster")    ; ' (Э)
