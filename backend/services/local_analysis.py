"""Conservative offline rules. Scores are heuristics, not probabilities.

This module deliberately does not resolve cross-turn pronouns or infer a task owner
from the person speaking. Keep original evidence; unsupported wording may be missed.
"""
import re
from backend.schemas import ActionItem, TranscriptSegment

LETTER = r"[А-ЯЁӘҒҚҢӨҰҮҺІA-Z][а-яёәғқңөұүһіa-z]+(?:-[А-ЯЁӘҒҚҢӨҰҮҺІA-Z][а-яёәғқңөұүһіa-z]+)?"
PERSON = rf"{LETTER}(?:\s+{LETTER}){{0,2}}"
# Explicit finite vocabulary, not a claim of full Russian/Kazakh understanding.
VERBS = {
    'подготовьте': 'Подготовить', 'подготовить': 'Подготовить',
    'проверьте': 'Проверить', 'проверить': 'Проверить',
    'разработайте': 'Разработать', 'разработать': 'Разработать',
    'согласуйте': 'Согласовать', 'согласовать': 'Согласовать',
    'представьте': 'Представить', 'представить': 'Представить',
    'предоставьте': 'Предоставить', 'предоставить': 'Предоставить',
    'проведите': 'Провести', 'провести': 'Провести',
    'организуйте': 'Организовать', 'организовать': 'Организовать',
    'направьте': 'Направить', 'направить': 'Направить',
    'отправьте': 'Отправить', 'отправить': 'Отправить',
    'найдите': 'Найти', 'найти': 'Найти',
    'обновите': 'Обновить', 'обновить': 'Обновить',
    'свяжитесь': 'Связаться', 'связаться': 'Связаться',
    'разберитесь': 'Разобраться', 'разобраться': 'Разобраться',
    'доложите': 'Доложить', 'доложить': 'Доложить',
    'зафиксируйте': 'Зафиксировать', 'зафиксировать': 'Зафиксировать',
    'соберите': 'Собрать', 'собрать': 'Собрать',
    'пропишите': 'Прописать', 'прописать': 'Прописать',
    'ищите': 'Найти', 'выставляйте': 'Выставить', 'выставить': 'Выставить',
    'привлеките': 'Привлечь', 'привлечь': 'Привлечь',
    'запросите': 'Запросить', 'запросить': 'Запросить',
    'поручаю': 'Поручаю',
    'дайындаңыз': 'Дайындау', 'дайындаңдар': 'Дайындау',
    'дайындау': 'Дайындау', 'тексеріңіз': 'Тексеру', 'тексеру': 'Тексеру',
    'жіберіңіз': 'Жіберу', 'жіберу': 'Жіберу', 'ұсыныңыз': 'Ұсыну',
    'ұсыну': 'Ұсыну', 'өткізіңіз': 'Өткізу', 'өткізу': 'Өткізу',
}
FUTURE_DIRECTIVES = {'подготовит':'Подготовить', 'проверит':'Проверить',
                     'представит':'Представить', 'проведет':'Провести', 'проведёт':'Провести'}
VERBS.update(FUTURE_DIRECTIVES)
VERB = re.compile(r'\b(' + '|'.join(sorted(VERBS, key=len, reverse=True)) + r')\b', re.I)
LET_OWNER = re.compile(rf'^(?i:пусть)\s+(?P<name>{PERSON})\s+')
IMPERATIVES = {v for v in VERBS if v.endswith(('ьте', 'итесь', 'ыңыз', 'іңіз', 'ңдар'))}
IMPERATIVES.update({'соберите', 'найдите', 'проведите', 'пропишите', 'поручаю', 'ищите', 'выставляйте', 'привлеките', 'запросите'})
VOCATIVE = re.compile(rf'^\s*(?:Коллеги[,!]\s*)?(?P<name>{PERSON})\s*,\s*')
OWNER = re.compile(r'(?:ответственн(?:ый|ая|ые|ой)|жауапты)\s*[:—–-]?\s*(?P<name>.+?)(?=\s*[,;]?\s+(?:срок|мерзім)|\s+[—–]\s*(?:срок|мерзім)|$)', re.I)
NON_NAMES = {'коллеги', 'ребята', 'команда', 'пожалуйста', 'хорошо', 'первое', 'второе', 'третье', 'четвёртое', 'четвертое', 'пятая', 'пятое', 'шестое', 'седьмое', 'смотрите', 'значит', 'итак', 'здравствуйте', 'сегодня', 'завтра', 'послезавтра', 'спасибо', 'дальше', 'далее', 'например'}
MONTHS = r'(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)'
DAY = r'(?:понедельник[ау]?|вторник[ау]?|сред[ауые]|четверг[ау]?|пятниц[аыуе]|суббот[аыуе]|воскресень[еяю])'
NUM = r'(?:\d+|один|одну|две|два|три|четыре|пять|шесть|семь|десять)'
RU_TIME = rf'(?:\d{{1,2}}\s+{MONTHS}(?:\s+\d{{4}}(?:\s*года)?)?|\d{{1,2}}[./]\d{{1,2}}(?:[./]\d{{2,4}})?|(?:первому|второму|третьему|пятнадцатому|двадцатому|тридцатому)\s+{MONTHS}|{DAY}|конца\s+(?:этой\s+)?(?:недели|месяца|квартала|года)|(?:следующей|этой|текущей)\s+недел[иею]|{NUM}\s+(?:рабочих\s+)?(?:дня|дней|недели|недель|месяца|месяцев)|недел[ию]|месяц|сегодня|завтра|послезавтра)'
KZ_MONTH = r'(?:қаңтар|ақпан|наурыз|сәуір|мамыр|маусым|шілде|тамыз|қыркүйек|қазан|қараша|желтоқсан)(?:ға|ге|қа|ке)?'
DEADLINE = re.compile(rf'\b(?:(?P<prep>до|к|ко|на|за|через|в течение)\s+(?P<ru>{RU_TIME})|(?P<bare>сегодня|завтра|послезавтра)|(?P<kz>\d{{1,2}}\s+{KZ_MONTH}\s+дейін|(?:келесі|осы)\s+апта(?:да|ға)?|жұмаға\s+дейін|ертең))\b', re.I)
# Asking, proposing, reporting a past instruction, or negation is not a firm task.
UNCERTAIN = re.compile(r'\b(?:если|может\s+быть|может,|предлагаю|предложил[аи]?|предложили|обсуждали|обсудили|попросил[аи]?|попросили|поручил[аи]?|поручили|вчера|раньше|не\s+(?:нужно|надо|следует)|егер)\b', re.I)
LEAD = re.compile(r'^(?:(?:первое|второе|третье|четв[её]ртое|пятое|пятая|шестое|седьмое)\s*[,;:.)—–-]\s*|\d+[.)]\s*|(?:коллеги|хорошо|смотрите|итак|пожалуйста|так|тогда|значит так)\s*[,—:]\s*|(?:нужно|необходимо|надо|следует|прошу|поручаю|давайте)\s+)', re.I)


def sentences(text: str) -> list[str]:
    # Do not split dates such as 15.10.2026 or decimal numbers.
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+(?=[А-ЯЁӘҒҚҢӨҰҮҺІA-Z])|\n+|;\s*', text) if s.strip()]


def _deadline(source: str):
    matches = list(DEADLINE.finditer(source))
    if len(matches) != 1:
        return None, None
    m = matches[0]
    # Preserve relative units and their prepositions. Never attach a guessed year.
    value = m.group(0)
    if m.group('prep') and m.group('prep').lower() in {'до', 'к', 'ко'}:
        value = m.group('ru')
    return value.strip(), m.span()


def _owner_and_body(source: str):
    explicit = OWNER.search(source.rstrip('.!'))
    owner = None
    body = source
    if explicit:
        owner = explicit.group('name').strip(' ,.—–-:') or None
        if owner and re.fullmatch(r'не (?:указан[аыо]?|определ[её]н[аыо]?|назначен[аыо]?)|неизвест(?:ен|на|но)|unknown|белгісіз', owner, re.I):
            owner = None
        body = source[:explicit.start()].rstrip(' ,.—–-:')
    # Strip enumerations / politeness, keeping original evidence untouched.
    while (m := LEAD.match(body)):
        body = body[m.end():]
    let_owner = LET_OWNER.match(body)
    if let_owner and let_owner.group('name').casefold() not in NON_NAMES:
        if not explicit:
            owner = let_owner.group('name')
        body = body[let_owner.end():]
    vocative = VOCATIVE.match(body)
    if vocative and vocative.group('name').casefold() not in NON_NAMES:
        if not explicit:
            owner = vocative.group('name')
        body = body[vocative.end():]
    return owner, body


def _speech_units(segments: list[TranscriptSegment]):
    """Rejoin sentence fragments split by ASR without merging different speakers."""
    pending = ''
    speaker = None
    for segment in segments:
        if pending and (segment.speaker != speaker or re.search(r'[.!?]$', pending)):
            yield speaker, pending
            pending = ''
        pending = (pending + ' ' + segment.text).strip()
        speaker = segment.speaker
    if pending:
        yield speaker, pending


def _instruction_fragments(segments):
    """Attach only explicit adjacent owner/deadline labels, not inferred pronouns."""
    pending = None
    last_speaker = None
    for speaker, unit in _speech_units(segments):
        for fragment in sentences(unit):
            metadata = re.match(r'^(?:ответственн(?:ый|ая|ые|ой)|жауапты|срок|мерзім)\b', fragment, re.I)
            if metadata and pending and speaker == last_speaker and VERB.search(pending):
                pending += ' ' + fragment
            else:
                if pending:
                    yield pending
                pending = fragment
            last_speaker = speaker
    if pending:
        yield pending


def extract_action_items(segments: list[TranscriptSegment]) -> list[ActionItem]:
    items = []
    seen = set()
    # Separate an explicit assignment from a following "а вы ..." clause;
    # its owner/deadline must not leak into the second instruction or vice versa.
    fragments = (part.strip() for source in _instruction_fragments(segments)
                 for part in re.split(r',\s+а\s+(?=вы\b)', source, flags=re.I))
    for source in fragments:
        if '?' in source or UNCERTAIN.search(source):
            continue
        responsible, body = _owner_and_body(source)
        # Reject directly negated verbs in Russian and common Kazakh negatives.
        if re.search(r'\bне\s+(?:' + '|'.join(VERBS) + r')\b|\b\w+(?:маңыз|меңіз|баңыз|беңіз|паңыз|пеңіз)\b', body, re.I):
            continue
        verb = VERB.search(body)
        if not verb:
            continue
        token = verb.group(0).lower()
        if token in FUTURE_DIRECTIVES:
            directive = source
            while (lead := LEAD.match(directive)):
                directive = directive[lead.end():]
            if not LET_OWNER.match(directive):
                continue
        prefix = body[:verb.start()].strip(' ,:—–-')
        is_kazakh = token in {'дайындаңыз','дайындаңдар','дайындау','тексеріңіз','тексеру','жіберіңіз','жіберу','ұсыныңыз','ұсыну','өткізіңіз','өткізу'}
        if prefix and not is_kazakh and not re.fullmatch(r'(?:нужно|необходимо|надо|следует|прошу|пожалуйста|давайте|тогда|вы|до\s+.+|к\s+.+|на\s+.+|за\s+.+)(?:\s+.*)?', prefix, re.I):
            continue
        # Infinitives need an explicit instruction context (not "цель — подготовить").
        if token not in IMPERATIVES and not responsible and not re.match(r'^(?:нужно|необходимо|надо|следует|прошу|поручаю|давайте)\b', source, re.I) and not re.match(r'^\s*(?:первое|второе|третье|четв[её]ртое|пятое|пятая|шестое|седьмое|\d+)\s*[,;:.)—–-]', source, re.I) and not re.match(r'^\s*(?:' + '|'.join(VERBS) + r')\b', source, re.I):
            continue
        deadline, _ = _deadline(source)
        # Keep only the task part; Kazakh objects normally precede the verb.
        task = body if is_kazakh else body[verb.start():]
        task = re.sub(r'\b' + re.escape(verb.group(0)) + r'\b', (VERBS[token].lower() if is_kazakh and verb.start()>0 else VERBS[token]), task, count=1, flags=re.I)
        # Remove metadata and deadline phrases from the task, not from evidence.
        task = re.sub(r'\s*[,—–-]\s*(?:срок|мерзім)\s*[:—–-]?.*$', '', task, flags=re.I)
        if deadline is not None:
            task = DEADLINE.sub('', task)
        task = re.sub(r'\s+([,;])', r'\1', task)
        task = re.sub(r'\s+', ' ', task).strip(' ,.—–-:!')
        if not task or len(task.split()) < 2:
            continue
        task = task[0].upper() + task[1:]
        key = (task.casefold(), responsible, deadline)
        if key in seen:
            continue
        seen.add(key)
        items.append(ActionItem(text=task, responsible=responsible, deadline=deadline,
                                source_fragment=source,
                                confidence=round(0.55 + 0.2 * bool(responsible) + 0.15 * bool(deadline), 2)))
    return items


def summarize_transcript(text: str) -> str:
    """Extract up to three informative source sentences, <= 1200 chars.

    This is an extractive preview, not a semantic summary of the full meeting.
    """
    parts = sentences(text)
    if not parts:
        return 'Речь не обнаружена.'
    greetings = re.compile(r'^(?:коллеги[,!]\s*)?(?:добрый день|здравствуйте|начинаем|спасибо|все свободны)', re.I)
    candidates = [p for p in parts if not greetings.match(p)] or parts
    ranked = sorted(enumerate(candidates), key=lambda p: (-int(bool(VERB.search(p[1]))) - int(bool(re.search(r'проблем|решени|риск|итог|показател',p[1],re.I))), p[0]))
    chosen = sorted(ranked[:3], key=lambda p:p[0])
    result = ' '.join(p for _,p in chosen)
    if len(result)>1200:
        result = result[:1199].rsplit(' ',1)[0] + '…'
    return result
