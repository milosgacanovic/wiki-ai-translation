from __future__ import annotations

import argparse
import json
import logging
import time
import re
import hashlib

from .config import load_config
from .db import (
    get_conn,
    fetch_termbase,
    fetch_segment_checksums,
    fetch_cached_translation,
    upsert_segment,
    upsert_translation,
)
from .engines.google_v3 import GoogleTranslateV3
from .logging import configure_logging
from .mediawiki import MediaWikiClient, MediaWikiError
from .placeholders import protect_wikitext, restore_wikitext
from .segmenter import split_translate_units, Segment
from .transliteration import sr_cyrillic_to_latin


def _resolve_project_id(cfg_project_id: str | None, credentials_path: str | None) -> str | None:
    if cfg_project_id:
        return cfg_project_id
    if not credentials_path:
        return None
    try:
        with open(credentials_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("project_id")
    except Exception:
        return None


def _unit_title(page_title: str, unit_key: str, lang: str) -> str:
    return f"Translations:{page_title}/{unit_key}/{lang}"


LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
FILE_LINK_RE = re.compile(r"\[\[(?:File|Image):[^\]]+\]\]", re.IGNORECASE)
EMPTY_P_RE = re.compile(r"<p>\s*(?:<br\s*/?>\s*)+</p>", re.IGNORECASE)
REDIRECT_RE = re.compile(r"^\s*#redirect\b", re.IGNORECASE)
UNRESOLVED_PLACEHOLDER_RE = re.compile(r"__PH\d+__|__LINK\d+__")
BROKEN_LINK_RE = re.compile(r"\[\[(?:__PH\d+__|__LINK\d+__)\|([^\]]+)\]\]")
DISPLAYTITLE_RE = re.compile(r"\{\{\s*DISPLAYTITLE\s*:[^}]+\}\}", re.IGNORECASE)
DISCLAIMER_TABLE_RE = re.compile(
    r"\{\|\s*class=\"translation-disclaimer\".*?\|\}", re.DOTALL
)


def _is_safe_internal_link(target: str) -> bool:
    return ":" not in target


def _tokenize_links(
    text: str, lang: str
) -> tuple[str, dict[str, str], list[tuple[str, str]], set[str]]:
    placeholders: dict[str, str] = {}
    link_meta: list[tuple[str, str]] = []
    source_targets: set[str] = set()

    def _replace(match: re.Match) -> str:
        target = match.group(1)
        display = match.group(2)
        if not _is_safe_internal_link(target):
            return match.group(0)

        page, anchor = (target.split("#", 1) + [""])[:2]
        source_targets.add(page)
        if page.endswith(f"/{lang}"):
            new_target = page
        else:
            new_target = f"{page}/{lang}"
        if anchor:
            new_target = f"{new_target}#{anchor}"

        token = f"__LINK{len(placeholders)}__"
        placeholders[token] = new_target

        if display is None:
            display = target
            # Implicit display: do not translate to avoid changing names
        else:
            link_meta.append((new_target, display))
        return f"[[{token}|{display}]]"

    return LINK_RE.sub(_replace, text), placeholders, link_meta, source_targets




DISCALIMER_TEXT_BY_LANG = {
    "sr": (
        "Ova stranica je automatski prevedena. "
        "Ovaj prevod može sadržati greške ili netačnosti. "
        "<br />Možete pomoći da se poboljša tako što ćete {link}."
    ),
    "it": (
        "Questa pagina è stata tradotta automaticamente. "
        "Questa traduzione può contenere errori o imprecisioni. "
        "<br />Puoi aiutare a migliorarla {link}."
    ),
    "de": (
        "Diese Seite wurde automatisch übersetzt. "
        "Diese Übersetzung kann Fehler oder Ungenauigkeiten enthalten. "
        "<br />Sie können helfen, sie zu verbessern, indem Sie {link}."
    ),
    "es": (
        "Esta página fue traducida automáticamente. "
        "Esta traducción puede contener errores o inexactitudes. "
        "<br />Puedes ayudar a mejorarla {link}."
    ),
    "fr": (
        "Cette page a été traduite automatiquement. "
        "Cette traduction peut contenir des erreurs ou des imprécisions. "
        "<br />Vous pouvez aider à l'améliorer en {link}."
    ),
    "nl": (
        "Deze pagina is automatisch vertaald. "
        "Deze vertaling kan fouten of onnauwkeurigheden bevatten. "
        "<br />Je kunt helpen om het te verbeteren door {link}."
    ),
    "he": (
        "דף זה תורגם אוטומטית. "
        "תרגום זה עשוי להכיל שגיאות או אי־דיוקים. "
        "<br />אפשר לעזור לשפר אותו על ידי {link}."
    ),
    "da": (
        "Denne side blev oversat automatisk. "
        "Denne oversættelse kan indeholde fejl eller unøjagtigheder. "
        "<br />Du kan hjælpe med at forbedre den ved at {link}."
    ),
    "pt": (
        "Esta página foi traduzida automaticamente. "
        "Esta tradução pode conter erros ou imprecisões. "
        "<br />Você pode ajudar a melhorá-la {link}."
    ),
    "pl": (
        "Ta strona została przetłumaczona automatycznie. "
        "To tłumaczenie może zawierać błędy lub nieścisłości. "
        "<br />Możesz pomóc ją poprawić, {link}."
    ),
    "el": (
        "Αυτή η σελίδα μεταφράστηκε αυτόματα. "
        "Αυτή η μετάφραση μπορεί να περιέχει λάθη ή ανακρίβειες. "
        "<br />Μπορείτε να βοηθήσετε να βελτιωθεί {link}."
    ),
    "hu": (
        "Ezt az oldalt automatikusan lefordítottuk. "
        "Ez a fordítás hibákat vagy pontatlanságokat tartalmazhat. "
        "<br />Segíthet javítani rajta, ha {link}."
    ),
    "sv": (
        "Den här sidan översattes automatiskt. "
        "Den här översättningen kan innehålla fel eller felaktigheter. "
        "<br />Du kan hjälpa till att förbättra den genom att {link}."
    ),
    "fi": (
        "Tämä sivu on käännetty automaattisesti. "
        "Tämä käännös voi sisältää virheitä tai epätarkkuuksia. "
        "<br />Voit auttaa parantamaan sitä {link}."
    ),
    "sk": (
        "Táto stránka bola automaticky preložená. "
        "Tento preklad môže obsahovať chyby alebo nepresnosti. "
        "<br />Môžete pomôcť zlepšiť ho {link}."
    ),
    "hr": (
        "Ova stranica je automatski prevedena. "
        "Ovaj prijevod može sadržavati pogreške ili netočnosti. "
        "<br />Možete pomoći da se poboljša {link}."
    ),
    "id": (
        "Halaman ini diterjemahkan secara otomatis. "
        "Terjemahan ini mungkin mengandung kesalahan atau ketidakakuratan. "
        "<br />Anda dapat membantu memperbaikinya dengan {link}."
    ),
    "ar": (
        "تمت ترجمة هذه الصفحة تلقائياً. "
        "قد تحتوي هذه الترجمة على أخطاء أو عدم دقة. "
        "<br />يمكنك المساعدة في تحسينها عبر {link}."
    ),
    "hi": (
        "यह पृष्ठ स्वचालित रूप से अनुवादित किया गया है। "
        "इस अनुवाद में त्रुटियाँ या अशुद्धियाँ हो सकती हैं। "
        "<br />आप इसे बेहतर बनाने में मदद कर सकते हैं, {link}."
    ),
    "no": (
        "Denne siden ble automatisk oversatt. "
        "Denne oversettelsen kan inneholde feil eller unøyaktigheter. "
        "<br />Du kan hjelpe til med å forbedre den ved å {link}."
    ),
    "cs": (
        "Tato stránka byla automaticky přeložena. "
        "Tento překlad může obsahovat chyby nebo nepřesnosti. "
        "<br />Můžete pomoci ji zlepšit {link}."
    ),
    "ko": (
        "이 페이지는 자동 번역되었습니다. "
        "이 번역에는 오류나 부정확한 내용이 있을 수 있습니다. "
        "<br />{link}을 통해 개선하는 데 도움을 줄 수 있습니다."
    ),
    "ja": (
        "このページは自動翻訳されました。"
        "この翻訳には誤りや不正確さが含まれる場合があります。"
        "<br />{link}ことで改善に協力できます。"
    ),
    "ka": (
        "ეს გვერდი ავტომატურად იქნა თარგმნილი. "
        "ამ თარგმანს შეიძლება ჰქონდეს შეცდომები ან უზუსტობები. "
        "<br />შეგიძლიათ დაგვეხმაროთ გაუმჯობესებაში {link}."
    ),
    "ro": (
        "Această pagină a fost tradusă automat. "
        "Această traducere poate conține erori sau inexactități. "
        "<br />Poți ajuta la îmbunătățire {link}."
    ),
    "sl": (
        "Ta stran je bila samodejno prevedena. "
        "Ta prevod lahko vsebuje napake ali netočnosti. "
        "<br />Pomagate lahko pri izboljšavi z {link}."
    ),
    "lb": (
        "Dës Säit gouf automatesch iwwersat. "
        "Dës Iwwersetzung kann Feeler oder Ongenauegkeeten enthalen. "
        "<br />Dir kënnt hëllefen se ze verbesseren andeems Dir {link}."
    ),
    "th": (
        "หน้านี้ถูกแปลโดยอัตโนมัติ "
        "การแปลนี้อาจมีข้อผิดพลาดหรือความไม่ถูกต้อง "
        "<br />คุณสามารถช่วยปรับปรุงได้โดย {link}."
    ),
    "is": (
        "Þessi síða var sjálfvirkt þýdd. "
        "Þessi þýðing kann innihaldið villur eða ónákvæmni. "
        "<br />Þú getur hjálpað til við að bæta hana með því að {link}."
    ),
    "vi": (
        "Trang này được dịch tự động. "
        "Bản dịch này có thể chứa lỗi hoặc thiếu chính xác. "
        "<br />Bạn có thể giúp cải thiện bằng cách {link}."
    ),
    "zu": (
        "Leli khasi lihunyushwe ngokuzenzakalelayo. "
        "Lolu hlelo lokuhumusha lungase luqukathe amaphutha noma ukungaqondile. "
        "<br />Ungasiza ukuluthuthukisa ngokuthi {link}."
    ),
    "zh": (
        "此页面为自动翻译。"
        "该翻译可能包含错误或不准确之处。"
        "<br />你可以通过{link}来帮助改进。"
    ),
    "ru": (
        "Эта страница была автоматически переведена. "
        "Этот перевод может содержать ошибки или неточности. "
        "<br />Вы можете помочь улучшить её, {link}."
    ),
    "uk": (
        "Цю сторінку перекладено автоматично. "
        "Цей переклад може містити помилки або неточності. "
        "<br />Ви можете допомогти покращити її, {link}."
    ),
    "fa": (
        "این صفحه به صورت خودکار ترجمه شده است. "
        "این ترجمه ممکن است حاوی خطاها یا نادقیق‌ها باشد. "
        "<br />می‌توانید با {link} به بهبود آن کمک کنید."
    ),
    "gu": (
        "આ પાનું આપમેળે અનુવાદિત થયું છે. "
        "આ અનુવાદમાં ભૂલો અથવા અચોક્કસતાઓ હોઈ શકે છે. "
        "<br />તમે {link} દ્વારા તેને સુધારવામાં મદદ કરી શકો છો."
    ),
    "ta": (
        "இந்தப் பக்கம் தானாக மொழிபெயர்க்கப்பட்டுள்ளது. "
        "இந்த மொழிபெயர்ப்பில் பிழைகள் அல்லது துல்லியமின்மை இருக்கலாம். "
        "<br />நீங்கள் {link} மூலம் மேம்படுத்த உதவலாம்."
    ),
    "te": (
        "ఈ పేజీ ఆటోమేటిక్‌గా అనువదించబడింది. "
        "ఈ అనువాదంలో తప్పులు లేదా అస్పష్టతలు ఉండవచ్చు. "
        "<br />మీరు {link} ద్వారా మెరుగుపరచడంలో సహాయం చేయవచ్చు."
    ),
    "mr": (
        "हा पृष्ठ स्वयंचलितपणे अनुवादित केला आहे. "
        "या अनुवादात चुका किंवा अचूकतेचा अभाव असू शकतो. "
        "<br />तुम्ही {link} करून सुधारण्यात मदत करू शकता."
    ),
    "tr": (
        "Bu sayfa otomatik olarak çevrildi. "
        "Bu çeviri hatalar veya yanlışlıklar içerebilir. "
        "<br />{link} yaparak iyileştirmeye yardımcı olabilirsiniz."
    ),
    "ur": (
        "یہ صفحہ خودکار طور پر ترجمہ کیا گیا ہے۔ "
        "اس ترجمے میں غلطیاں یا عدم درستگی ہو سکتی ہے۔ "
        "<br />آپ {link} کے ذریعے اسے بہتر بنانے میں مدد کر سکتے ہیں۔"
    ),
    "bn": (
        "এই পৃষ্ঠাটি স্বয়ংক্রিয়ভাবে অনুবাদ করা হয়েছে। "
        "এই অনুবাদে ভুল বা অযথার্থতা থাকতে পারে। "
        "<br />আপনি {link} এর মাধ্যমে এটি উন্নত করতে সাহায্য করতে পারেন।"
    ),
    "jv": (
        "Kaca iki diterjemahake kanthi otomatis. "
        "Terjemahan iki bisa uga ngemot kesalahan utawa ketidakakuratan. "
        "<br />Sampeyan bisa mbantu ngapikake kanthi {link}."
    ),
    "en": (
        "This page was automatically translated. "
        "This translation may contain errors or inaccuracies. "
        "<br />You can help improve it by {link}."
    ),
}


def _translate_page_link(norm_title: str, lang: str, link_text: str) -> str:
    group = f"page-{norm_title.replace(' ', '+')}"
    href = (
        "https://wiki.danceresource.org/index.php?"
        f"title=Special:Translate&group={group}&action=page&filter=&language={lang}"
    )
    return f"[{href} {link_text}]"


def _build_disclaimer(norm_title: str, lang: str) -> str:
    text = DISCALIMER_TEXT_BY_LANG.get(lang, DISCALIMER_TEXT_BY_LANG["en"])
    link_text = {
        "sr": "urediti stranicu",
        "it": "modificando la pagina",
        "de": "die Seite bearbeiten",
        "es": "editando la página",
        "fr": "modifiant la page",
        "nl": "de pagina te bewerken",
        "he": "עריכת הדף",
        "da": "redigere siden",
        "pt": "editando a página",
        "pl": "edytując stronę",
        "el": "επεξεργαζόμενοι τη σελίδα",
        "hu": "szerkeszted az oldalt",
        "sv": "redigera sidan",
        "fi": "muokkaamalla sivua",
        "sk": "upravovaním stránky",
        "hr": "uređivanjem stranice",
        "id": "mengedit halaman",
        "ar": "تحرير الصفحة",
        "hi": "पृष्ठ संपादित करके",
        "no": "redigere siden",
        "cs": "úpravou stránky",
        "ko": "페이지를 편집",
        "ja": "ページを編集する",
        "ka": "გვერდის რედაქტირებით",
        "ro": "editând pagina",
        "sl": "urejanjem strani",
        "lb": "d'Säit ännert",
        "th": "แก้ไขหน้า",
        "is": "breyta síðunni",
        "vi": "chỉnh sửa trang",
        "zu": "uhlele ikhasi",
        "zh": "编辑页面",
        "ru": "редактируя страницу",
        "uk": "редагуючи сторінку",
        "fa": "ویرایش صفحه",
        "gu": "પાનું સંપાદિત કરીને",
        "ta": "பக்கத்தைத் திருத்துவது",
        "te": "పేజీని సవరించడం",
        "mr": "पृष्ठ संपादित",
        "tr": "sayfayı düzenleyerek",
        "ur": "صفحہ میں ترمیم",
        "bn": "পৃষ্ঠা সম্পাদনা করে",
        "jv": "nyunting kaca",
        "en": "editing the page",
    }.get(lang, "editing the page")
    link = _translate_page_link(norm_title, lang, link_text)
    body = text.format(link=link)
    return (
        "{| class=\"translation-disclaimer\"\n"
        "|-\n"
        f"| {body}\n"
        "|}"
    )


def _strip_empty_paragraphs(text: str) -> str:
    cleaned = EMPTY_P_RE.sub("", text)
    return cleaned.strip()

def _collapse_blank_lines(text: str) -> str:
    # Collapse 3+ newlines to 2 and trim leading blank lines.
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.lstrip("\n")


def _strip_unresolved_placeholders(text: str) -> str:
    return UNRESOLVED_PLACEHOLDER_RE.sub("", text)


def _dedupe_displaytitle(text: str) -> str:
    matches = list(DISPLAYTITLE_RE.finditer(text))
    if len(matches) <= 1:
        return text
    first = matches[0].group(0)
    # remove all displaytitles, then prepend the first one
    cleaned = DISPLAYTITLE_RE.sub("", text).strip()
    return f"{first}\n{cleaned}"


def _extract_displaytitle(text: str) -> str | None:
    match = DISPLAYTITLE_RE.search(text)
    if not match:
        return None
    raw = match.group(0)
    # {{DISPLAYTITLE:...}}
    inner = raw.split(":", 1)[-1].rstrip("}").rstrip("}")
    return inner.strip()


def _source_title_for_displaytitle(
    norm_title: str, wikitext: str, segments: list[Segment]
) -> str:
    # Prefer source DISPLAYTITLE from unit 1, then full source wikitext.
    for seg in segments:
        if seg.key == "1":
            value = _extract_displaytitle(seg.text)
            if value:
                return value
            break
    value = _extract_displaytitle(wikitext)
    if value:
        return value
    # Fallback: use the leaf title, not full path.
    return norm_title.rsplit("/", 1)[-1].strip()


def _restore_file_links(source: str, translated: str) -> str:
    source_links = FILE_LINK_RE.findall(source)
    if not source_links:
        return translated
    translated_links = FILE_LINK_RE.findall(translated)
    if not translated_links:
        prefix = "\n".join(source_links)
        return f"{prefix}\n{translated}" if translated else prefix
    out = translated
    for src, tr in zip(source_links, translated_links):
        out = out.replace(tr, src, 1)
    if len(source_links) > len(translated_links):
        extra = "\n".join(source_links[len(translated_links):])
        out = f"{extra}\n{out}"
    return out


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fix_broken_links(text: str, lang: str) -> str:
    def _repl(match: re.Match) -> str:
        display = match.group(1)
        return f"[[{display}/{lang}|{display}]]"
    return BROKEN_LINK_RE.sub(_repl, text)


def _rewrite_internal_links_to_lang_with_source(
    text: str, lang: str, source_targets: set[str]
) -> str:
    def _repl(match: re.Match) -> str:
        target = match.group(1)
        display = match.group(2) or target
        if not _is_safe_internal_link(target):
            return match.group(0)
        page, anchor = (target.split("#", 1) + [""])[:2]
        if page.endswith(f"/{lang}") or page not in source_targets:
            new_target = page
        else:
            new_target = f"{page}/{lang}"
        if anchor:
            new_target = f"{new_target}#{anchor}"
        return f"[[{new_target}|{display}]]"
    return LINK_RE.sub(_repl, text)


def _build_no_translate_terms(
    entries: list[dict[str, str | bool | None]]
) -> list[tuple[str, str]]:
    terms: list[tuple[str, str]] = []
    for entry in entries:
        if not entry.get("forbidden"):
            continue
        term = (entry.get("term") or "").strip()
        preferred = (entry.get("preferred") or "").strip()
        if term and preferred:
            terms.append((term, preferred))
    return terms


def _protect_terms(text: str, terms: list[tuple[str, str]]) -> tuple[str, dict[str, str]]:
    if not terms:
        return text, {}
    placeholders: dict[str, str] = {}
    for term, preferred in sorted(terms, key=lambda t: len(t[0]), reverse=True):
        pattern = re.compile(rf"(?<!\\w){re.escape(term)}(?!\\w)", re.IGNORECASE)

        def _repl(match: re.Match) -> str:
            token = f"__NT{len(placeholders)}__"
            placeholders[token] = preferred
            return token

        text = pattern.sub(_repl, text)
    return text, placeholders


def _should_translate_display(display: str, terms: list[tuple[str, str]]) -> bool:
    if not terms:
        return True
    display_norm = display.strip().lower()
    for term, _ in terms:
        if display_norm == term.strip().lower():
            return False
    return True


def _apply_termbase(text: str, entries: list[dict[str, str | bool | None]]) -> str:
    updated = text
    for entry in entries:
        term = entry.get("term") or ""
        preferred = entry.get("preferred") or ""
        if not term or not preferred:
            continue
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        updated = pattern.sub(preferred, updated)
    return updated


def _protect_link_targets(text: str) -> tuple[str, dict[str, str]]:
    placeholders: dict[str, str] = {}

    def _repl(match: re.Match) -> str:
        target = match.group(1)
        display = match.group(2)
        if not _is_safe_internal_link(target):
            return match.group(0)
        token = f"__LT{len(placeholders)}__"
        placeholders[token] = target
        if display is None:
            return f"[[{token}]]"
        return f"[[{token}|{display}]]"

    return LINK_RE.sub(_repl, text), placeholders


def _apply_termbase_safe(text: str, entries: list[dict[str, str | bool | None]]) -> str:
    if not entries:
        return text
    # Keep disclaimer block URLs intact (e.g. Special:Translate group path).
    disclaimer_placeholders: dict[str, str] = {}

    def _mask_disclaimer(match: re.Match) -> str:
        token = f"__DISC{len(disclaimer_placeholders)}__"
        disclaimer_placeholders[token] = match.group(0)
        return token

    text = DISCLAIMER_TABLE_RE.sub(_mask_disclaimer, text)
    protected, placeholders = _protect_link_targets(text)
    updated = _apply_termbase(protected, entries)
    restored = restore_wikitext(updated, placeholders)
    for token, block in disclaimer_placeholders.items():
        restored = restored.replace(token, block)
    return restored


def _normalize_leading_directives(text: str) -> str:
    pattern = re.compile(
        r"(\{\{DISPLAYTITLE:[^}]+\}\})\s*\n+\s*(__NOTOC__)?\s*\n+\s*(\[\[File:[^\]]+\]\])",
        re.IGNORECASE,
    )

    def _repl(match: re.Match) -> str:
        display = match.group(1)
        notoc = match.group(2) or ""
        filetag = match.group(3)
        return f"{display}{notoc}{filetag}"

    return pattern.sub(_repl, text, count=1)


def _normalize_leading_div(text: str) -> str:
    # Avoid leading blank line/paragraph before a top-level div.
    text = re.sub(r"(__NOTOC__)\s*\n+\s*(<div\b)", r"\1\n\2", text, count=1)
    text = re.sub(r"(\{\{DISPLAYTITLE:[^}]+\}\})\s*\n+\s*(__NOTOC__)\s*\n+\s*(<div\b)", r"\1__NOTOC__\3", text, count=1)
    return text


def _normalize_heading_lines(text: str) -> str:
    def _repl(match: re.Match) -> str:
        eq = match.group(1)
        title = match.group(2).strip()
        return f"\n{eq} {title} {eq}\n"

    return re.sub(r"[ \t]*(={2,6})[ \t]*([^\n]*?)[ \t]*\1[ \t]*", _repl, text)


def _strip_heading_list_prefix(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if re.match(r"^\s*[*#:;]\s*={2,6}", line):
            line = re.sub(r"^\s*[*#:;]\s*", "", line)
        lines.append(line)
    return "\n".join(lines)


def _align_list_markers(source: str, translated: str) -> str:
    source_lines = source.splitlines()
    translated_lines = translated.splitlines()
    markers = ("*", "#", ";", ":")
    fixed = list(translated_lines)
    t_idx = 0
    for src_line in source_lines:
        src_strip = src_line.lstrip()
        if src_strip == "":
            continue
        while t_idx < len(fixed) and fixed[t_idx].strip() == "":
            t_idx += 1
        if t_idx >= len(fixed):
            break
        tr_strip = fixed[t_idx].lstrip()
        if src_strip.startswith("="):
            while t_idx < len(fixed) and not fixed[t_idx].lstrip().startswith("="):
                t_idx += 1
                while t_idx < len(fixed) and fixed[t_idx].strip() == "":
                    t_idx += 1
            if t_idx >= len(fixed):
                break
            t_idx += 1
            continue
        if src_strip.startswith(markers):
            if not tr_strip.startswith(markers):
                marker = src_strip[0]
                fixed[t_idx] = f"{marker} {tr_strip}".rstrip()
            t_idx += 1
            continue
        if tr_strip.startswith(markers):
            fixed[t_idx] = tr_strip.lstrip("*#;:").lstrip()
        t_idx += 1
    return "\n".join(fixed)


def _is_redirect_wikitext(text: str) -> bool:
    return bool(REDIRECT_RE.search(text.lstrip("\ufeff")))


def _insert_disclaimer(
    text: str,
    disclaimer: str,
    marker: str | None,
    norm_title: str,
    lang: str,
    anchors: dict[str, dict[str, str]] | None,
) -> str:
    # Remove any existing disclaimer to prevent duplication.
    text = DISCLAIMER_TABLE_RE.sub("", text).strip()
    if marker and marker in text:
        return text.replace(marker, f"\n\n{disclaimer}\n\n", 1)
    if anchors and norm_title in anchors and lang in anchors[norm_title]:
        anchor = anchors[norm_title][lang]
        idx = text.find(anchor)
        if idx != -1:
            insert_at = idx + len(anchor)
            return text[:insert_at] + "\n\n" + disclaimer + "\n\n" + text[insert_at:]
    return f"{disclaimer}\n\n{text}"


def _fetch_unit_sources(
    client: MediaWikiClient, norm_title: str, keys: list[str]
) -> list[Segment]:
    segments: list[Segment] = []
    for key in keys:
        unit_title = f"Translations:{norm_title}/{key}/en"
        try:
            text, _, _ = client.get_page_wikitext(unit_title)
        except MediaWikiError as exc:
            logging.getLogger("translate").warning(
                "missing translation unit %s: %s", unit_title, exc
            )
            return []
        segments.append(Segment(key=key, text=text.strip()))
    return segments


def _fetch_messagecollection_segments(
    client: MediaWikiClient, norm_title: str, source_lang: str
) -> list[Segment]:
    group_id = f"page-{norm_title}"
    items = client.get_message_collection(group_id, source_lang)
    segments: list[Segment] = []
    for item in items:
        key = item.get("key") or ""
        unit_key = key.split("/")[-1]
        if not unit_key.isdigit():
            continue
        text = (item.get("definition") or "").strip()
        segments.append(Segment(key=unit_key, text=text))
    return segments


def assemble_translated_page(wikitext: str, translations: dict[str, str]) -> str:
    output = []
    matches = list(re.finditer(r"<!--T:(\\d+)-->", wikitext))
    if not matches:
        return wikitext

    cursor = 0
    for idx, match in enumerate(matches):
        output.append(wikitext[cursor:match.start()])
        key = match.group(1)
        translated = translations.get(key, "")
        output.append(translated)
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(wikitext)
        cursor = end

    output.append(wikitext[cursor:])
    combined = "".join(output)
    combined = re.sub(r"</?translate>", "", combined)
    return combined.strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--lang", default="sr")
    parser.add_argument("--engine-lang", default=None)
    parser.add_argument("--disclaimer", default="")
    parser.add_argument("--fuzzy", action="store_true", default=False)
    parser.add_argument("--no-fuzzy", action="store_false", dest="fuzzy")
    parser.add_argument("--start-key", type=int, default=None)
    parser.add_argument("--max-keys", type=int, default=None)
    parser.add_argument("--sleep-ms", type=int, default=200)
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument("--approve-only", action="store_true", help="only approve assembled page")
    parser.add_argument("--retry-approve", action="store_true", help="retry approve if assembled page missing")
    parser.add_argument("--rebuild-only", action="store_true", help="use cached translations only; no MT calls")
    parser.add_argument("--no-cache", action="store_true", help="ignore cached translations and retranslate")
    parser.add_argument("--auto-review", action="store_true", default=False)
    parser.add_argument("--no-auto-review", action="store_false", dest="auto_review")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()

    session = __import__("requests").Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    if args.rebuild_only and args.no_cache:
        raise SystemExit("--rebuild-only cannot be used with --no-cache")

    if args.approve_only:
        _, norm_title = client.get_page_revision_id(args.title)
        assembled_title = f"{norm_title}/{args.lang}"
        backoff = [1, 2, 4, 8] if args.retry_approve else []
        attempts = len(backoff) + 1
        for idx in range(attempts):
            try:
                _, assembled_rev, _ = client.get_page_wikitext(assembled_title)
                client.approve_revision(assembled_rev)
                logging.getLogger("translate").info(
                    "approved assembled page %s", assembled_title
                )
                return {"approve_status": "approved"}
            except MediaWikiError as exc:
                if "no revisions" in str(exc).lower():
                    if idx < len(backoff):
                        wait = backoff[idx]
                        logging.getLogger("translate").warning(
                            "approve retry: %s (waiting %ss)", exc, wait
                        )
                        time.sleep(wait)
                        continue
                    logging.getLogger("translate").warning(
                        "skip approve: %s", exc
                    )
                    return {"approve_status": "no_revisions"}
                raise

    wikitext, rev_id, norm_title = client.get_page_wikitext(args.title)
    if _is_redirect_wikitext(wikitext):
        logging.getLogger("translate").info("skip redirect page: %s", norm_title)
        return
    segments = _fetch_messagecollection_segments(client, norm_title, cfg.source_lang)
    if not segments:
        unit_keys = client.list_translation_unit_keys(norm_title, cfg.source_lang)
        if unit_keys:
            unit_keys = sorted(set(unit_keys), key=lambda k: int(k))
            segments = _fetch_unit_sources(client, norm_title, unit_keys)
            if not segments:
                segments = split_translate_units(wikitext)
        else:
            segments = split_translate_units(wikitext)
    if not segments:
        raise SystemExit("no segments found; is the page marked for translation?")

    deduped: list[Segment] = []
    seen_keys: set[str] = set()
    for seg in segments:
        if seg.key in seen_keys:
            continue
        seen_keys.add(seg.key)
        deduped.append(seg)
    segments = deduped

    logging.getLogger("translate").info(
        "page=%s rev_id=%s segments=%s", args.title, rev_id, len(segments)
    )

    termbase_entries: list[dict[str, str | bool | None]] = []
    if cfg.pg_dsn:
        try:
            with get_conn(cfg.pg_dsn) as conn:
                termbase_entries = fetch_termbase(conn, args.lang)
        except Exception:
            termbase_entries = []

    logging.getLogger("translate").info("termbase entries=%s", len(termbase_entries))

    no_translate_terms = _build_no_translate_terms(termbase_entries)

    segments = sorted(segments, key=lambda s: int(s.key))
    if args.start_key is not None:
        segments = [s for s in segments if int(s.key) >= args.start_key]
    if args.max_keys is not None and args.max_keys > 0:
        segments = segments[: args.max_keys]

    segment_checksums: dict[str, str] = {}
    cached_by_key: dict[str, str] = {}
    cached_source_by_key: dict[str, str] = {}
    existing_checksums: dict[str, str] = {}
    disable_cache = False
    if cfg.pg_dsn and not args.no_cache:
        try:
            with get_conn(cfg.pg_dsn) as conn:
                existing_checksums = fetch_segment_checksums(conn, norm_title)
        except Exception:
            existing_checksums = {}
    if existing_checksums:
        current_keys = {seg.key for seg in segments}
        if set(existing_checksums.keys()) != current_keys:
            disable_cache = True
            logging.getLogger("translate").warning(
                "segment keys changed for %s; bypassing cache for this run",
                norm_title,
            )

    for seg in segments:
        checksum = _checksum(seg.text)
        segment_checksums[seg.key] = checksum
        if (
            not args.no_cache
            and not disable_cache
            and existing_checksums.get(seg.key) == checksum
            and cfg.pg_dsn
        ):
            try:
                with get_conn(cfg.pg_dsn) as conn:
                    cached = fetch_cached_translation(conn, f"{norm_title}::{seg.key}", args.lang)
                if cached:
                    cached_by_key[seg.key] = cached
                    cached_source_by_key[seg.key] = "db"
            except Exception:
                pass
        if args.rebuild_only and seg.key not in cached_by_key:
            unit_title = f"Translations:{norm_title}/{seg.key}/{args.lang}"
            try:
                unit_text, _, _ = client.get_page_wikitext(unit_title)
                if unit_text.strip():
                    cached_by_key[seg.key] = unit_text
                    cached_source_by_key[seg.key] = "wiki"
            except MediaWikiError:
                pass

    to_translate = [seg for seg in segments if seg.key not in cached_by_key]
    if args.rebuild_only and to_translate:
        missing = ", ".join(seg.key for seg in to_translate)
        raise SystemExit(f"rebuild-only: missing cached translations for keys {missing}")

    engine_lang = args.engine_lang or args.lang
    engine = None
    glossary_id = None
    if to_translate:
        project_id = _resolve_project_id(cfg.gcp_project_id, cfg.gcp_credentials_path)
        if not project_id:
            raise SystemExit("GCP project id is required (set GCP_PROJECT_ID or ensure in credentials)")
        engine = GoogleTranslateV3(
            project_id=project_id,
            location=cfg.gcp_location,
            credentials_path=cfg.gcp_credentials_path,
        )
        if cfg.gcp_glossaries:
            glossary_id = cfg.gcp_glossaries.get(args.lang)

    # Translate page title for DISPLAYTITLE (only if MT is enabled)
    source_display_title = _source_title_for_displaytitle(norm_title, wikitext, segments)
    title_translation = None
    for term, preferred in no_translate_terms:
        if source_display_title.strip().lower() == term.strip().lower():
            title_translation = preferred
            break
    if title_translation is None:
        if engine is not None:
            title_translation = engine.translate(
                [source_display_title], cfg.source_lang, engine_lang, glossary_id=glossary_id
            )[0].text
        else:
            title_translation = source_display_title
    if engine_lang == "sr-Latn":
        title_translation = sr_cyrillic_to_latin(title_translation)
    if termbase_entries:
        title_translation = _apply_termbase(title_translation, termbase_entries)

    protected = []
    link_display_requests: dict[str, str] = {}
    source_by_key: dict[str, str] = {}
    marker_key: str | None = None
    source_targets: set[str] = set()
    for seg in segments:
        if cfg.disclaimer_marker and cfg.disclaimer_marker in seg.text and marker_key is None:
            marker_key = seg.key
        link_text, link_placeholders, link_meta, seg_targets = _tokenize_links(seg.text, args.lang)
        source_targets.update(seg_targets)
        source_by_key[seg.key] = seg.text
        if seg.key in cached_by_key:
            continue
        link_text, no_translate_placeholders = _protect_terms(link_text, no_translate_terms)
        result = protect_wikitext(link_text, protect_links=False)
        result.placeholders.update(link_placeholders)
        result.placeholders.update(no_translate_placeholders)
        for target, display in link_meta:
            if _should_translate_display(display, no_translate_terms):
                link_display_requests[target] = display
        protected.append((seg, result))

    translated = []
    if protected and engine is not None:
        translated = engine.translate(
            [p.text for _, p in protected], cfg.source_lang, engine_lang, glossary_id=glossary_id
        )
    protected_map: dict[str, tuple[object, object]] = {}
    for (seg, ph), tr in zip(protected, translated):
        protected_map[seg.key] = (ph, tr)

    # Translate link display texts to ensure localized anchors
    link_display_translated: dict[str, str] = {}
    if link_display_requests and engine is not None:
        displays = list(link_display_requests.values())
        translated_displays = engine.translate(
            displays, cfg.source_lang, engine_lang, glossary_id=glossary_id
        )
        for (target, _), tr in zip(link_display_requests.items(), translated_displays):
            link_display_translated[target] = tr.text

    translated_by_key: dict[str, str] = {}
    ordered_keys: list[str] = []
    for seg in segments:
        if seg.key in cached_by_key:
            restored = cached_by_key[seg.key]
            source_text = source_by_key.get(seg.key, "")
            restored = _restore_file_links(source_text, restored)
            if termbase_entries:
                restored = _apply_termbase_safe(restored, termbase_entries)
            restored = _strip_heading_list_prefix(restored)
            restored = _normalize_heading_lines(restored)
            restored = _align_list_markers(source_text, restored)
            restored = _strip_empty_paragraphs(restored)
            restored = _strip_unresolved_placeholders(restored)
            translated_by_key[seg.key] = restored
            ordered_keys.append(seg.key)
            continue

        ph, tr = protected_map[seg.key]
        restored = restore_wikitext(tr.text, ph.placeholders)
        # Safety: restore any leftover placeholders in case MT preserved tokens
        for token, value in ph.placeholders.items():
            if token in restored:
                restored = restored.replace(token, value)
        restored = _restore_file_links(seg.text, restored)
        restored = _strip_heading_list_prefix(restored)
        restored = _normalize_heading_lines(restored)
        restored = _align_list_markers(seg.text, restored)
        if engine_lang == "sr-Latn":
            restored = sr_cyrillic_to_latin(restored)
        if link_display_translated:
            def _rewrite_display(match: re.Match) -> str:
                target = match.group(1)
                display = match.group(2) or target
                if target in link_display_translated:
                    new_display = link_display_translated[target]
                    if engine_lang == "sr-Latn":
                        new_display = sr_cyrillic_to_latin(new_display)
                    return f"[[{target}|{new_display}]]"
                return f"[[{target}|{display}]]"

            restored = LINK_RE.sub(_rewrite_display, restored)
        restored = _fix_broken_links(restored, args.lang)
        restored = _rewrite_internal_links_to_lang_with_source(
            restored, args.lang, source_targets
        )
        if termbase_entries:
            restored = _apply_termbase_safe(restored, termbase_entries)
        restored = _strip_empty_paragraphs(restored)
        # Mark as fuzzy to indicate machine translation if enabled
        if args.fuzzy:
            restored = f"!!FUZZY!!\n{restored}"
        translated_by_key[seg.key] = restored
        ordered_keys.append(seg.key)

    disclaimer = args.disclaimer or _build_disclaimer(norm_title, args.lang)
    inserted = False
    allow_disclaimer = False
    if marker_key and marker_key in ordered_keys:
        allow_disclaimer = True
    # Segment-only reruns (e.g. --max-keys 1) can rewrite key 1 and drop an
    # existing disclaimer unless we reinsert it.
    if "1" in ordered_keys:
        allow_disclaimer = True
    if not cfg.disclaimer_marker and "1" in ordered_keys:
        allow_disclaimer = True
    if allow_disclaimer:
        if cfg.disclaimer_marker:
            for key in ordered_keys:
                text = translated_by_key[key]
                if cfg.disclaimer_marker in text:
                    translated_by_key[key] = _insert_disclaimer(
                        text, disclaimer, cfg.disclaimer_marker, norm_title, args.lang, cfg.disclaimer_anchors
                    )
                    inserted = True
                    break

        if not inserted and marker_key and marker_key in translated_by_key:
            translated_by_key[marker_key] = _insert_disclaimer(
                translated_by_key[marker_key],
                disclaimer,
                cfg.disclaimer_marker,
                norm_title,
                args.lang,
                cfg.disclaimer_anchors,
            )
            inserted = True

        if not inserted and ordered_keys:
            first_key = ordered_keys[0]
            translated_by_key[first_key] = _insert_disclaimer(
                translated_by_key[first_key],
                disclaimer,
                cfg.disclaimer_marker,
                norm_title,
                args.lang,
                cfg.disclaimer_anchors,
            )

        if cfg.disclaimer_marker:
            for key in ordered_keys:
                translated_by_key[key] = translated_by_key[key].replace(cfg.disclaimer_marker, "")

    # Remove any displaytitles from translated segments and add a single one.
    if ordered_keys and "1" in ordered_keys:
        displaytitle_value = None
        try:
            items = client.get_message_collection(f"page-{norm_title}", args.lang)
            for item in items:
                if str(item.get("key", "")) == f"{norm_title.replace(' ', '_')}/Page_display_title":
                    if item.get("translation"):
                        displaytitle_value = str(item.get("translation")).strip()
                    break
        except Exception:
            displaytitle_value = None
        if displaytitle_value is not None or not args.rebuild_only:
            for key in ordered_keys:
                translated_by_key[key] = DISPLAYTITLE_RE.sub("", translated_by_key[key]).strip()
        if displaytitle_value is None and not args.rebuild_only:
            displaytitle_value = title_translation
        if displaytitle_value:
            displaytitle = f"{{{{DISPLAYTITLE:{displaytitle_value}}}}}"
            translated_by_key["1"] = f"{displaytitle}\n{translated_by_key['1']}"
        translated_by_key["1"] = _strip_empty_paragraphs(translated_by_key["1"])
        translated_by_key["1"] = _normalize_leading_directives(
            translated_by_key["1"]
        )
        translated_by_key["1"] = _normalize_leading_div(
            translated_by_key["1"]
        )
        translated_by_key["1"] = _collapse_blank_lines(
            translated_by_key["1"]
        )

    for key in ordered_keys:
        translated_by_key[key] = _strip_empty_paragraphs(translated_by_key[key])
        if termbase_entries:
            translated_by_key[key] = _apply_termbase_safe(
                translated_by_key[key], termbase_entries
            )
        translated_by_key[key] = _align_list_markers(
            source_by_key.get(key, ""), translated_by_key[key]
        )
        translated_by_key[key] = _strip_unresolved_placeholders(translated_by_key[key])

    # Final pass after disclaimer/displaytitle insertion
    for key in ordered_keys:
        translated_by_key[key] = _strip_unresolved_placeholders(translated_by_key[key])

    for key in ordered_keys:
        restored = translated_by_key[key]
        source_text = source_by_key.get(key, "")
        restored = _restore_file_links(source_text, restored)
        unit_title = _unit_title(norm_title, key, args.lang)
        summary = "Machine translation by bot (draft, needs review)"

        if args.dry_run:
            logging.getLogger("translate").info("DRY RUN edit %s", unit_title)
            continue

        newrev = client.edit(unit_title, restored, summary, bot=True)
        logging.getLogger("translate").info("edited %s", unit_title)
        if args.auto_review and newrev:
            client.translation_review(newrev)
            logging.getLogger("translate").info("reviewed %s", unit_title)
        if cfg.pg_dsn:
            try:
                with get_conn(cfg.pg_dsn) as conn:
                    upsert_segment(
                        conn,
                        norm_title,
                        key,
                        source_text,
                        segment_checksums.get(key, _checksum(source_text)),
                    )
                    segment_key = f"{norm_title}::{key}"
                    engine_used = cached_source_by_key.get(key, cfg.mt_primary)
                    upsert_translation(conn, segment_key, args.lang, restored, engine_used)
            except Exception:
                pass
        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

    if args.auto_approve:
        assembled_title = f"{norm_title}/{args.lang}"
        try:
            _, assembled_rev, _ = client.get_page_wikitext(assembled_title)
        except MediaWikiError as exc:
            logging.getLogger("translate").warning(
                "skip approve: %s", exc
            )
            return
        client.approve_revision(assembled_rev)
        logging.getLogger("translate").info(
            "approved assembled page %s", assembled_title
        )


if __name__ == "__main__":
    main()
