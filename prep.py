# prep.py — подготовка текста к озвучке.
# Одна функция: prepare(текст) -> строка на кириллице.
# В результате остаются только буквы, цифры словами, знаки . , ! ? ; :
# и метка ʘ — на её месте озвучка вставляет паузу.

import re
from num2words import num2words
import pymorphy3
import cmudict

# ---------- свои исключения: слово → как читать ----------
TRANSLIT = True   # False — оставлять английские слова латиницей (для голоса, который сам читает английский)

# Ручные ударения для Vosk: плюс перед ударной гласной. Перекрывают RuAccent и словарь Vosk.
STRESS = {
    # 'деплоить': 'депл+оить',
}

# Читать по буквам, хотя в них есть гласные (слова без гласных — http, ssh — читаются по буквам и так)
SPELL_WORDS = {'url', 'uri', 'api', 'cpu', 'gpu', 'usb', 'ui', 'ux', 'id', 'io', 'ip', 'os', 'vm', 'utf',
               'html', 'xml', 'sql', 'pdf', 'ide', 'ai', 'llm', 'tts', 'ssd', 'hdd', 'abi', 'sdk',
               'cli', 'oop', 'tcp', 'udp', 'vpn', 'dns', 'ssl', 'tls', 'jwt', 'uuid'}

CUSTOM = {
    'close': 'клоуз',
    'handoff': 'хэндоф',
    'ok': 'окей', 'okay': 'окей',
    'from': 'фром', 'of': 'ов', 'because': 'бикоз',     # у британцев «о», словарь даёт американское «а»
    'python': 'пайтон', 'pythons': 'пайтонс',
    'window': 'виндоу', 'windows': 'виндоус',
    'ssh': 'эс эс аш',
    'ubuntu': 'убунту',                               # в словаре ошибка: без «н»
    'ctrl': 'контрол', 'alt': 'альт', 'esc': 'эскэйп',
}

# аббревиатуры, которые говорят словом, а не по буквам
ACRONYMS_ANY = {'json': 'джейсон', 'yaml': 'ямл', 'cuda': 'кюда', 'ascii': 'аски',
                'jpeg': 'джейпег', 'jpg': 'джейпег', 'gif': 'гиф', 'wifi': 'вайфай', 'ajax': 'аякс'}
ACRONYMS_UPPER = {'REST': 'рест', 'RAM': 'рам', 'ROM': 'ром', 'SIM': 'сим', 'NATO': 'нато',
                  'GUI': 'гуи', 'CRUD': 'крад', 'TOML': 'томл', 'NASA': 'наса', 'ASAP': 'эйсап'}

# ---------- числа и падежи ----------
morph = pymorphy3.MorphAnalyzer()
PREP = {
    'к': 'datv', 'ко': 'datv',
    'от': 'gent', 'до': 'gent', 'из': 'gent', 'без': 'gent', 'для': 'gent',
    'около': 'gent', 'против': 'gent', 'у': 'gent', 'после': 'gent', 'кроме': 'gent',
    'более': 'gent', 'менее': 'gent', 'больше': 'gent', 'меньше': 'gent', 'свыше': 'gent',
    'вместо': 'gent', 'вокруг': 'gent', 'среди': 'gent', 'возле': 'gent', 'вроде': 'gent',
    'порядка': 'gent', 'течение': 'gent', 'раньше': 'gent', 'позже': 'gent', 'дольше': 'gent',
    'над': 'ablt', 'под': 'ablt', 'перед': 'ablt', 'между': 'ablt',
    'о': 'loct', 'об': 'loct', 'при': 'loct',
}

def ru_case(before, after):
    pm = re.search(r'([а-яёА-ЯЁ]+)\s*$', before)
    if not pm:
        return None
    p = pm.group(1).lower()
    if p in ('с', 'со'):
        return 'gent' if re.match(r'\s*\S*\s*до\b', after.lower()) else 'ablt'
    if p in ('в', 'во', 'на'):
        nm = re.match(r'\s*([а-яёА-ЯЁ]+)', after)
        if nm and 'loct' in morph.parse(nm.group(1).lower())[0].tag:
            return 'loct'
        return None
    return PREP.get(p)

# Глаголы, после которых число — подлежащее: «прошла одна секунда», «осталась одна минута»
NOM_VERBS = {'пройти', 'проходить', 'остаться', 'оставаться', 'уйти', 'уходить', 'понадобиться',
             'потребоваться', 'требоваться', 'быть', 'истечь', 'истекать', 'миновать', 'пролететь'}

def acc_context(before):
    # Число стоит в винительном: «за 1 с», «через 1 мин», «ждал 1 с» (длительность после глагола)
    pm = re.search(r'([а-яёА-ЯЁ]+)\s*$', before)
    if not pm:
        return False
    w = pm.group(1).lower()
    if w in ('за', 'через', 'на', 'в', 'во', 'про', 'спустя', 'сквозь'):
        return True
    p = morph.parse(w)[0]
    return bool({'VERB', 'INFN', 'GRND'} & set(p.tag.grammemes)) and p.normal_form not in NOM_VERBS

def inflect_ru(words, case):
    out = []
    for w in words.split():
        f = morph.parse(w)[0].inflect({case})
        out.append(f.word if f else w)
    return ' '.join(out)

def num_to_words(m):
    def conv(x):
        s = num2words(int(x), lang='ru')
        s = re.sub(r'^одна тысяча', 'тысяча', s)
        return s.replace('-', ' ').replace(',', '')
    def w(x):
        z = len(x) - len(x.lstrip('0'))
        if z and len(x) > 1:
            rest = x[z:]
            return ' '.join(['ноль'] * z + ([conv(rest)] if rest else []))
        return conv(x)
    out = w(m.group(1))
    if m.group(2):
        frac = m.group(2)
        out += ' точка '
        out += ' '.join(w(d) for d in frac) if frac.startswith('0') else w(frac)
    else:
        case = ru_case(m.string[:m.start()], m.string[m.end():])
        if case:
            out = inflect_ru(out, case)
    return f' {out} '

# ---------- английский → русские буквы ----------
CMU = cmudict.dict()

ARPA = {'AA':'а','AE':'э','AH':'а','AO':'о','AW':'ау','AY':'ай','B':'б','CH':'ч',
        'D':'д','DH':'з','EH':'э','ER':'эр','EY':'эй','F':'ф','G':'г','HH':'х',
        'IH':'и','IY':'и','JH':'дж','K':'к','L':'л','M':'м','N':'н','NG':'нг',
        'OW':'оу','OY':'ой','P':'п','R':'р','S':'с','SH':'ш','T':'т','TH':'с',
        'UH':'у','UW':'у','V':'в','W':'в','Y':'й','Z':'з','ZH':'ж'}
YV = {'UW':'ю','UH':'ю','AA':'я','AE':'я','AH':'я','EH':'е','IY':'и','IH':'и','OW':'ё','AO':'ё','ER':'ер'}
LETTERS = {'A':'эй','B':'би','C':'си','D':'ди','E':'и','F':'эф','G':'джи','H':'эйч',
           'I':'ай','J':'джей','K':'кей','L':'эл','M':'эм','N':'эн','O':'оу','P':'пи',
           'Q':'кью','R':'ар','S':'эс','T':'ти','U':'ю','V':'ви','W':'дабл ю','X':'экс',
           'Y':'вай','Z':'зэт'}
FALLBACK = [('sh','ш'),('ch','ч'),('th','т'),('ph','ф'),('ck','к'),('qu','кв'),
            ('oo','у'),('ee','и'),('ea','и'),('ou','ау'),('ai','эй'),('ay','эй'),
            ('oa','оу'),('x','кс'),('a','а'),('b','б'),('c','к'),('d','д'),('e','э'),
            ('f','ф'),('g','г'),('h','х'),('i','и'),('j','дж'),('k','к'),('l','л'),
            ('m','м'),('n','н'),('o','о'),('p','п'),('q','к'),('r','р'),('s','с'),
            ('t','т'),('u','у'),('v','в'),('w','в'),('y','и'),('z','з')]
REDUCED = {'AH0', 'IH0', 'EH0', 'UH0', 'AA0', 'AE0', 'AO0'}
SPELL = {'a': 'а', 'e': 'э', 'i': 'и', 'o': 'о', 'u': 'у', 'y': 'и'}
YSPELL = {'a': 'я', 'e': 'е', 'i': 'и', 'o': 'ё', 'u': 'ю'}

def arpa_to_ru(phones, word):
    groups = re.findall(r'[aeiouy]+', word)
    gi, out, i = 0, '', 0
    while i < len(phones):
        p = phones[i]
        base = re.sub(r'\d', '', p)
        if base == 'Y' and i + 1 < len(phones) and re.sub(r'\d', '', phones[i + 1]) in YV:
            g = groups[gi] if gi < len(groups) else ''
            if out[-1:] and out[-1] in 'бвгджзклмнпрстфхцчшщ':   # после согласного — «ь»: вэлью, компьютэр
                out += 'ь'
            if phones[i + 1] in REDUCED and g[:1] in YSPELL:   # безударный — по букве: documents → докюмэнтс
                out += 'ю' if 'u' in g else 'ё' if 'o' in g else YSPELL[g[0]]
            else:
                out += YV[re.sub(r'\d', '', phones[i + 1])]
            gi += 1; i += 2
            continue
        if p[-1].isdigit():
            g = groups[gi] if gi < len(groups) else ''
            gi += 1
            if p in ('OW0', 'OW2'):
                # слово на -ow/-ows — «оу»: window → виндоу, follow → фолоу; иначе «о»: photo, video
                rest = [re.sub(r'\d', '', x) for x in phones[i + 1:]]
                v = 'оу' if rest in ([], ['Z'], ['S']) and re.search(r'ows?$', word.lower()) else 'о'
            elif base == 'AW' and i + 1 < len(phones) and phones[i + 1][-1].isdigit():
                v = 'ав'                                   # power → павэр, а не пауэр
            elif p in REDUCED and g:
                v = SPELL.get(g[0], ARPA.get(base, ''))
            elif base == 'AA' and 'o' in g:
                v = 'о'
            elif base in ('AA', 'AH') and 'a' in g and i and re.sub(r'\d', '', phones[i - 1]) == 'W':
                v = 'о'                                    # what → вот, want → вонт, swap → своп
            elif p == 'ER1':
                v = 'ор' if i and re.sub(r'\d', '', phones[i - 1]) == 'W' else 'ёр'
            elif base == 'UW' and g[:1] == 'e' and i and re.sub(r'\d', '', phones[i - 1]) in ('N', 'T', 'D', 'S', 'Z'):
                v = 'ью'                                   # new → нью, news → ньюз, stew → стью (по-британски)
            else:
                v = ARPA.get(base, '')
            out += v
            i += 1
            continue
        out += ARPA.get(base, ''); i += 1
    return out

def split_cmu(w):
    best = {len(w): []}
    for i in range(len(w) - 3, -1, -1):
        for j in range(len(w), i + 2, -1):
            if j in best and w[i:j] in CMU and (i not in best or len(best[j]) + 1 < len(best[i])):
                best[i] = [w[i:j]] + best[j]
    return best.get(0)

def en_word(w):
    w = w.replace('zqx', "'")                          # апостроф внутри слова: I'll, don't
    if "'" in w:
        lw = w.lower()
        if lw in CMU:
            return arpa_to_ru(CMU[lw][0], lw.replace("'", ''))
        w = w.replace("'", '')
    lw = w.lower()
    if lw in CUSTOM:
        return CUSTOM[lw]
    if lw in ACRONYMS_ANY:
        return ACRONYMS_ANY[lw]
    if w in ACRONYMS_UPPER:
        return ACRONYMS_UPPER[w]
    if len(w) == 1:                                    # одиночная буква — по названию
        return LETTERS[w.upper()]
    if re.fullmatch(r'h+m+', lw):                     # hm, hmm, hmmm — «хм»
        return 'хм'
    if re.fullmatch(r'[b-df-hj-np-tv-z]th', lw):        # nth, kth, mth — «энс», «кейс», «эмс»
        return LETTERS[lw[0].upper()] + 'с'
    # аббревиатуры по буквам: без гласных (http, ssh, npm, pwd) или из списка SPELL_WORDS (api, url, cpu)
    if lw in SPELL_WORDS or (len(w) <= 6 and not re.search(r'[aeiouy]', lw)):
        return ' '.join(LETTERS[c] for c in w.upper())
    if w.isupper() and len(w) <= 5:
        return ' '.join(LETTERS[c] for c in w)
    if lw in CMU:
        return arpa_to_ru(CMU[lw][0], lw)
    parts = split_cmu(lw)
    if parts and len(parts) <= 3:
        return ''.join(arpa_to_ru(CMU[p][0], p) for p in parts)
    lw = re.sub(r'^u', 'ю', lw)                        # u в начале — «ю»: usd → юсд, ubuntu → юбунту
    lw = re.sub(r'c(?=[eiy])', 'с', lw)               # c перед e, i, y — «с»: cipher, accent → аксэнт
    for a, b in FALLBACK:
        lw = lw.replace(a, b)
    return lw


# ---------- числа особых видов ----------
ABBR_NUM = {'тыс': 'тысяча', 'млн': 'миллион', 'млрд': 'миллиард', 'руб': 'рубль'}

def abbr_with_number(m):
    # «37 тыс.» → «37 тысяч», «2 тыс.» → «2 тысячи»
    rest = m.string[m.end():].lstrip()
    dot = '.' if m.group(0).endswith('.') and (not rest or rest[0].isupper()) else ''
    return _abbr_with_number(m) + dot

def _abbr_with_number(m):
    n = int(m.group(1))
    word = morph.parse(ABBR_NUM[m.group(2)])[0].make_agree_with_number(n).word
    if m.group(2) != 'тыс':
        return f'{m.group(1)} {word}'
    words = num2words(n, lang='ru', gender='f')            # две тысячи, одна тысяча
    case = ru_case(m.string[:m.start()], m.string[m.end():])
    if case:
        words = inflect_ru(words + ' ' + word, case)
        return f' {words} '
    return f' {words} {word} '

def noun_parse(noun):
    ps = morph.parse(noun)
    return next((x for x in ps if 'nomn' in x.tag and 'sing' in x.tag), ps[0])

def unit_words(num, noun, m):
    # «5» + «процент» → «5 процентов»; падеж — по предлогу перед числом
    if noun == 'евро':
        return f'{num} евро'
    p = noun_parse(noun)
    if re.search(r'[.,]', num):
        f = p.inflect({'sing', 'gent'})
        return f'{num} {f.word if f else noun}'
    n = int(num)
    case = ru_case(m.string[:m.start()], m.string[m.end():])
    if case:
        f = p.inflect({'sing' if n % 10 == 1 and n % 100 != 11 else 'plur', case})
    else:
        f = p.make_agree_with_number(n)
    acc_one = (not case and 'femn' in p.tag and n % 10 == 1 and n % 100 != 11
               and acc_context(m.string[:m.start()]))
    if acc_one:                                        # за одну секунду, ждал одну минуту
        f = p.inflect({'sing', 'accs'})
    word = f.word if f else noun
    if 'femn' in p.tag:                                # одна минута, две секунды
        words = num2words(n, lang='ru', gender='f')
        if case:
            words = inflect_ru(words, case)
        if acc_one:
            words = re.sub(r'одна$', 'одну', words)
        return f' {words} {word} '
    return f'{num} {word}'

CUR = {'$': 'доллар', '€': 'евро', '¥': 'юань', '₽': 'рубль'}

def percent(m):
    return unit_words(m.group(1), 'процент', m)

def degrees(m):
    return unit_words(m.group(1), 'градус', m) + (' Цельсия' if m.group(2) else '')

def cur_before(m):
    return unit_words(m.group(2), CUR[m.group(1)], m)

def cur_after(m):
    return unit_words(m.group(1), CUR[m.group(2)], m)

# ---------- даты ----------
MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля',
          'августа', 'сентября', 'октября', 'ноября', 'декабря']

def ord_words(n, tags):
    w = num2words(n, lang='ru', to='ordinal').split()
    f = morph.parse(w[-1])[0].inflect(tags)
    w[-1] = f.word if f else w[-1]
    return ' '.join(w)

def date_words(m, d, mo, y=None):
    # «10-09» → «десятое сентября», «2026-10-09» → «девятое октября две тысячи двадцать шестого года»
    if not (1 <= d <= 31 and 1 <= mo <= 12):
        return m.group(0)
    case = ru_case(m.string[:m.start()], m.string[m.end():])
    if case == 'ablt':
        case = 'gent'                                  # «с 10.09» — с десятого
    s = f'{ord_words(d, {"neut", case or "nomn"})} {MONTHS[mo - 1]}'
    if y is not None:
        if y < 100:
            y += 2000
        s += ' ' + ord_words(y, {'masc', 'gent'}) + ' года'
    return f' {s} '

def plain_num(x):
    # число как написано, без склонения: «09» → «ноль девять»
    z = len(x) - len(x.lstrip('0'))
    rest = x[z:]
    words = ['ноль'] * (z if rest else max(z, 1))
    if rest:
        words.append(re.sub(r'^одна тысяча', 'тысяча', num2words(int(rest), lang='ru')))
    return ' '.join(words)

def short_date(m):
    # «10-09», «28-10» — точно дата (по убыванию диапазон не пишут)
    # «15-20» — точно не дата, оставляем диапазоном «от … до …»
    # «09-10», «5-10» — непонятно: читаем как написано, «ноль девять тире десять»
    a, b = m.group(1), m.group(2)
    da, db = int(a), int(b)
    if not (1 <= da <= 31 and 1 <= db <= 12):
        return m.group(0)
    if da > db:
        return date_words(m, da, db)
    return f' {plain_num(a)} тире {plain_num(b)} '

def time_to_words(m):
    # «08:50» → «восемь пятьдесят», «08:05» → «восемь ноль пять»
    h, mm = int(m.group(1)), m.group(2)
    if h > 23 or int(mm) > 59:
        return m.group(0)
    hw = num2words(h, lang='ru')
    if mm == '00':
        mw = ''                                        # 09:00 → «девять»
    elif mm.startswith('0'):
        mw = 'ноль ' + num2words(int(mm), lang='ru')
    else:
        mw = num2words(int(mm), lang='ru')
    out = f'{hw} {mw}'.strip()
    case = ru_case(m.string[:m.start()], m.string[m.end():])
    if case == 'ablt':
        case = 'gent'                                      # «с 08:50» — с восьми пятидесяти
    if case:
        out = inflect_ru(out, case)
    return f' {out} '

ABBR = [(r'\bт\.\s?е\.', 'то есть'), (r'\bт\.\s?к\.', 'так как'), (r'\bт\.\s?д\.', 'так далее'),
        (r'\bт\.\s?п\.', 'тому подобное'), (r'\bнапр\.', 'например'), (r'\bсм\.', 'смотри'),
        (r'\bдр\.', 'другие'), (r'\bтыс\.', 'тысяч'), (r'\bмлн\.?', 'миллионов'),
        (r'\bмлрд\.?', 'миллиардов'), (r'\bруб\.', 'рублей'),
        (r'\be\.\s?g\.', 'например'), (r'\bi\.\s?e\.', 'то есть'), (r'\betc\.', 'и так далее'),
        (r'\bvs\b\.?', 'против')]

DIGITS = ['ноль', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять']

def mixed_word(m):
    # «nr2701» → «эн ар два семь ноль один»: цифры по одной, короткие латинские буквы по названию
    out = []
    for part in re.findall(r'\d+|[A-Za-z]+|[^\dA-Za-z]+', m.group(0)):
        if part.isdigit():
            out += [DIGITS[int(d)] for d in part]
        elif re.fullmatch(r'[A-Za-z]{1,3}', part):
            out += [LETTERS[c.upper()] for c in part]
        else:
            out.append(part)
    return ' '.join(out)

# ---------- порядковые, годы, единицы ----------
ORD_SUFFIX = r'(й|я|е|го|му|м|ым|ой|ую|х|ми|ые)'

def sci_number(m):
    # «1e-5» → «1 на десять в минус пятой», «2.5e3» → «2.5 на десять в третьей»
    mant, exp = m.group(1), int(m.group(2))
    sign = 'минус ' if exp < 0 else ''
    return f' {mant} на десять в {sign}{ord_words(abs(exp), {"femn", "loct"})} '

def ordinal_suffix(m):
    # «2-й» → «второй», «1020-м шаге» → «тысяча двадцатом шаге», «22-го» → «двадцать второго»
    n, suf = int(m.group(1)), m.group(2)
    w = num2words(n, lang='ru', to='ordinal').split()
    forms = [f for f in morph.parse(w[-1])[0].lexeme if f.word.endswith(suf)]
    if not forms:
        return m.group(0)
    case = ru_case(m.string[:m.start()], m.string[m.end():])
    prev = re.search(r'([а-яё]+)\s*$', m.string[:m.start()].lower())
    if not case and prev and prev.group(1) in ('в', 'во', 'на', 'о', 'об', 'при'):
        case = 'loct'
    order = ([case] if case else []) + ['loct', 'nomn', 'gent', 'datv', 'accs', 'ablt']
    want_plur = suf in ('х', 'ми', 'ые')
    def rank(f):
        c = f.tag.case or ''
        return (order.index(c) if c in order else 99, (f.tag.number == 'plur') != want_plur)
    w[-1] = min(forms, key=rank).word
    return ' ' + ' '.join(w) + ' '

def year_ordinal(m):
    # «к 2026 году» → «к две тысячи двадцать шестому году», «в 2026 году» → «…шестом году»
    n, yw = int(m.group(1)), m.group(2)
    parses = morph.parse(yw.lower())
    cases = {x.tag.case for x in parses}
    prev = re.search(r'([а-яё]+)\s*$', m.string[:m.start()].lower())
    prev = prev.group(1) if prev else ''
    if prev in ('в', 'во', 'о', 'об', 'при') and cases & {'loct', 'loc2'}:
        case = 'loct'
    elif PREP.get(prev) in cases:
        case = PREP[prev]
    else:
        case = parses[0].tag.case or 'nomn'
        case = 'loct' if case == 'loc2' else case
    number = 'plur' if parses[0].tag.number == 'plur' else 'sing'
    tags = {'plur', case} if number == 'plur' else {'masc', case}
    return f' {ord_words(n, tags)} {yw}'

UNITS = {'мс': 'миллисекунда', 'ms': 'миллисекунда', 'мкс': 'микросекунда', 'us': 'микросекунда',
         'µs': 'микросекунда', 'нс': 'наносекунда', 'ns': 'наносекунда', 'сек': 'секунда',
         'мин': 'минута', 'min': 'минута', 'ч': 'час',
         'кб': 'килобайт', 'kb': 'килобайт', 'мб': 'мегабайт', 'mb': 'мегабайт',
         'гб': 'гигабайт', 'gb': 'гигабайт', 'тб': 'терабайт', 'tb': 'терабайт',
         'км': 'километр', 'km': 'километр', 'кг': 'килограмм', 'kg': 'килограмм',
         'гц': 'герц', 'hz': 'герц', 'кгц': 'килогерц', 'khz': 'килогерц',
         'мгц': 'мегагерц', 'mhz': 'мегагерц', 'ггц': 'гигагерц', 'ghz': 'гигагерц'}
UNIT_RE = '|'.join(sorted(map(re.escape, UNITS), key=len, reverse=True))

def unit_num(m):
    return unit_words(m.group(1), UNITS[m.group(2).lower()], m)

def sec_unit(m):
    nxt = (m.group(2) or '').strip().lower()
    if nxt:
        if re.match(r'(половин|лишн|небольш|хвост|утра|вечера|ночи|дня)', nxt):
            return m.group(0)
        if any(x.tag.case in ('ablt', 'gent') and x.score > 0.2 for x in morph.parse(nxt)
               if 'NOUN' in x.tag or 'NPRO' in x.tag or 'ADJF' in x.tag):
            return m.group(0)          # «с ошибкой», «с собой» — предлог
    return unit_words(m.group(1), 'секунда', m)

# ---------- главная функция ----------
def prepare(t):
    t = t.replace('\r\n', '\n').replace('\r', '\n')                       # переводы строк Windows
    t = re.sub(r'([=\-_~*#─━═—–])\1{3,}', ' ', t)                       # ==== / ---- разделители — молча
    t = re.sub(r'(?<![.!?,;:\n])[ \t]*\n(?=[ \t]*[-*•●▪◦·][ \t]+)', '.\n', t)   # пункт списка — с новой фразы
    t = re.sub(r'(?m)^[ \t]*[-*•●▪◦·][ \t]+', '', t)                    # маркеры списка
    t = re.sub(r'(?m)^[ \t]*#{1,6}[ \t]+(.+?)[ \t]*$',
               lambda m: m.group(1) + ('' if m.group(1)[-1] in '.!?:' else '.'), t)  # ## Заголовок
    t = re.sub(r'[ \t]*·[ \t]*', '. ', t)                                 # · → точка
    t = re.sub(r'\n[ \t]*\n\s*', ' ǁ ', t)                           # пустая строка → абзац
    t = re.sub(r"(?<=[A-Za-z])['’](?=[A-Za-z])", 'zqx', t)         # I'll → одно слово
    t = re.sub(r'(?<=\d)[ \u00a0\u202f](?=\d{3}\b)', '', t)             # 8 000 → 8000
    t = re.sub(r'\b(\d+(?:\.\d+)?)[eE]([+-]?\d+)\b', sci_number, t)            # 1e-5
    t = re.sub(r'(\d+)[kK]\b', r'\1 тыс', t)                                  # 50k → 50 тыс
    t = re.sub(r'(\d+)\s*(тыс|млн|млрд|руб)\b\.?', abbr_with_number, t)  # 37 тыс. → 37 тысяч
    # 60 с → секунды; но не «2 с половиной», «5 с утра», «3 с ошибкой» (там «с» — предлог)
    t = re.sub(r'(\d+(?:[.,]\d+)?)\s*с(?![\w-])(?=(\s+[а-яё]+)?)', sec_unit, t)
    t = re.sub(r'(\d+(?:[.,]\d+)?)\s*(' + UNIT_RE + r')(?![\w])\.?', unit_num, t, flags=re.I)  # 5 мс, 2 GB
    t = re.sub(r'(\d+)-' + ORD_SUFFIX + r'\b', ordinal_suffix, t)               # 2-й, 1020-м
    t = re.sub(r'\b(\d{4})\s+(год[а-я]*)\b', year_ordinal, t, flags=re.I)        # к 2026 году
    t = re.sub(r'(\d+(?:[.,]\d+)?)\s*%', percent, t)                        # 5% → 5 процентов
    t = t.replace('%', ' процент ')
    t = re.sub(r'(\d+(?:[.,]\d+)?)\s*°\s*([CС]\b)?', degrees, t)         # 5° → 5 градусов
    t = t.replace('°', ' градус ')
    t = re.sub(r'([$€¥₽])\s?(\d+(?:[.,]\d+)?)', cur_before, t)          # $5 → 5 долларов
    t = re.sub(r'(\d+(?:[.,]\d+)?)\s?([$€¥₽])', cur_after, t)           # 100¥ → 100 юаней
    t = t.replace('$', ' доллар ').replace('€', ' евро ').replace('¥', ' юань ').replace('₽', ' рубль ')
    for a, b in ABBR:
        # если после сокращения начинается новое предложение — точку сохраняем
        t = re.sub(a, lambda m, b=b: b + ('.' if (lambda r: not r or r[0].isupper())(m.string[m.end():].lstrip()) else ''),
                   t, flags=re.I)
    t = re.sub(r'(?<![\d:])(\d{1,2}:\d{2})\s*[–—-]\s*(\d{1,2}:\d{2})(?![\d:])', r'\1 тире \2', t)  # 09:00–10:15
    t = re.sub(r'(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])', time_to_words, t)  # 08:50 → восемь пятьдесят
    t = re.sub(r'\b(\d{4})-(\d{2})-(\d{2})\b',
               lambda m: date_words(m, int(m.group(3)), int(m.group(2)), int(m.group(1))), t)  # 2026-10-09
    t = re.sub(r'\b(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?\b(?!\.\d)',
               lambda m: m.group(0) if re.fullmatch(r'\d{1,2}\.\d{1,2}\.(\d{4}|\d{2})', m.group(0))
               else ' ' + ' точка '.join(plain_num(x) for x in m.groups() if x) + ' ', t)  # версия 1.2.3
    t = re.sub(r'\b(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})\b',
               lambda m: date_words(m, int(m.group(1)), int(m.group(2)), int(m.group(3))), t)  # 09.10.2026
    t = re.sub(r'(?<![\w-])(\d{1,2})-(\d{1,2})(?![\w-])', short_date, t)              # 10-09, 09-10
    t = re.sub(r'(?<=[A-Za-z])[ \t]+(?=[А-Яа-яЁё])', ', ', t)          # латиница → кириллица: пауза
    t = re.sub(r'\b(?=[^\W_]*[^\W\d_])(?=[^\W_]*\d)[^\W_]+\b', mixed_word, t)  # nr2701, md5, v2
    t = t.replace('±', ' плюс минус ').replace('+', ' плюс ')
    t = t.replace('§', ' параграф ')
    # перевод строки: если строка кончилась знаком препинания — длинная пауза, как после точки
    t = re.sub(r'[ \t]*[;:][ \t]*\n\s*', '. ǀ ', t)                    # ; и : в конце строки — конец фразы
    t = re.sub(r',[ \t]*\n\s*', ', ', t)                                # запятая — терминал мог перенести строку
    t = re.sub(r'([.!?…])[ \t]*\n\s*', r'\1 ǀ ', t)
    t = re.sub(r'([)\]»"\'])[ \t]*\n\s*', r'\1. ǀ ', t)
    t = re.sub(r'[ \t]*\n\s*', ' ', t)                                  # без знака — без паузы
    t = t.replace('://', ' двоеточие слэш слэш ')
    t = re.sub(r'(?<=[^\W\d])\.(?=\w)|(?<=\w)\.(?=[^\W\d])', ' точка ', t)
    t = re.sub(r'(?<=[^\W\d]):(?=\w)|(?<=\w):(?=[^\W\d])', ' двоеточие ', t)
    t = re.sub(r'(?<=\d):(?=\d)', ' ', t)                                # 10:30
    t = t.replace('−', ' минус ')
    t = t.replace('-=', ' минус равно ')
    t = re.sub(r'(?<![\w-])(\d+)-(\d+)(?![\w-])',
               lambda m: f'от {int(m.group(1))} до {int(m.group(2))}', t)    # 5-10, 09-10
    t = re.sub(r'(?<![\w-])-(?=\d)', ' минус ', t)                      # -5
    t = re.sub(r'(?<=[\d)\]])\s*-\s*(?=[\d(\[])', ' минус ', t)          # 5-3, (..) - (..)
    t = re.sub(r'(?<=\b[A-Za-z])-(?=[A-Za-z]\b)', ' минус ', t)          # a-b
    t = re.sub(r'(?<=[A-Za-z\d_])\s+-\s+(?=[A-Za-z_])|(?<=[A-Za-z_])\s+-\s+(?=[A-Za-z\d_])',
               ' минус ', t)                                             # amount - remaining
    t = re.sub(r'\s*[—–]\s*|\s-\s', ', ', t)                            # тире
    t = re.sub(r'\s*(→|⇒|->|=>)\s*', ', ', t)                           # стрелки
    t = t.replace('≈', ' примерно ')
    t = re.sub(r'~\s*(?=\d)', ' примерно ', t)
    t = t.replace('~', ' тильда ')
    t = t.replace('≤', ' меньше или равно ').replace('≥', ' больше или равно ').replace('≠', ' не равно ')
    t = t.replace('<=', ' меньше или равно ').replace('>=', ' больше или равно ')
    t = t.replace('<', ' меньше ').replace('>', ' больше ')
    t = t.replace('×', ' умножить на ').replace('÷', ' разделить на ')
    t = re.sub(r'\*+', ' звёздочка ', t)
    t = t.replace('^', ' в степени ')
    t = t.replace('&', ' амперсанд ').replace('@', ' собака ').replace('#', ' решётка ')
    t = t.replace('№', ' номер ').replace('∞', ' бесконечность ').replace('√', ' корень из ')
    t = t.replace('\\', ' бэкслэш ')
    t = t.replace('!=', ' не равно ').replace('=', ' равно ')
    t = re.sub(r'\s*[(\[]\s*', ', ', t)                                 # открывающие скобки
    t = re.sub(r'\s*[)\]]\s*', ', ', t)                                 # закрывающие скобки → пауза
    t = re.sub(r'\s*»\s*', ', ', t)                                     # »
    t = re.sub(r'[,;](?=\s|$)', ', ʘ', t)                               # запятая и ; → пауза
    t = re.sub(r':(?=\s|$)', ': ʘ', t)                                  # двоеточие → пауза
    t = re.sub(r'(?<=[A-Za-z])/(?=[A-Za-z])', ' slash ', t)
    t = t.replace('/', ' слэш ')
    t = re.sub(r'[^\w\s.,!?;:]|_', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()

    t = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', t)                          # camelCase
    # английские куски переводим в русские буквы и обрамляем меткой ǂ,
    # чтобы озвучка могла прочитать их отдельно (медленнее и с паузой)
    t = re.sub(r'[A-Za-z]+(?:(?: +(?:точка|двоеточие|слэш|минус|плюс|равно|не))* +[A-Za-z]+)*',
               lambda m: 'ǂ' + re.sub(r'[A-Za-z]+', lambda w: en_word(w.group()) if TRANSLIT else w.group(), m.group()) + 'ǂ', t)
    t = re.sub(r'(\d+)(?:[.,](\d+))?', num_to_words, t)
    t = re.sub(r'\s+', ' ', t).strip()
    t = re.sub(r'\s+([.,!?;:])', r'\1', t)                              # пробел перед знаком
    t = re.sub(r',(?:\s*ʘ)?(?:\s*,)+', ',', t)                         # «,,» → «,»
    t = re.sub(r'ʘ(?:[\s,]*ʘ)+', 'ʘ', t)                               # две паузы подряд → одна
    t = re.sub(r'[,;:]+\s*(?:ʘ\s*)?(?=[.!?])', '', t)                  # запятая перед точкой
    t = re.sub(r'([.!?])(?:\s*[,;:]+)?(?:\s*ʘ)?(?=\s|$)', r'\1', t)   # «., ʘ» после точки → просто точка
    # заглавная буква после точки и в начале абзаца — иначе Piper не видит конец предложения
    t = re.sub(r'([.!?]\s+(?:ǀ\s*)?ǂ?|ǁ\s*ǂ?)([а-яё])', lambda m: m.group(1) + m.group(2).upper(), t)
    t = re.sub(r'^(ǂ?)([а-яё])', lambda m: m.group(1) + m.group(2).upper(), t)
    return t
