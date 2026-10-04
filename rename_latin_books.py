#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
✏️ Переименование книг с латинскими/цифровыми именами в НАСТОЯЩИЕ названия (кириллица).

ПОЧЕМУ ЭТО БЕЗОПАСНО (главное отличие от простого «латиница → кириллица»):
  1. Книги, у которых имя уже кириллическое, НЕ ТРАГАЮТСЯ вообще.
  2. PDF переименовывается ТОЛЬКО когда название, извлечённое из САМОЙ КНИГИ
     (первые страницы), совпадает с транслитерацией текущего имени файла
     («проверка туда-обратно»). Имя файла — это транслит названия; мы просто
     подтверждаем, что нашли именно его. Английские учебники («English - 11»),
     иностранные книги («The Tipping Point», латышские, немецкие) такой
     проверки не проходят → не переименовываются.
  3. fb2/epub: название берётся из встроенных метаданных файла (это надёжно),
     и только если оно кириллическое.
  4. Книги с чисто цифровыми именами (12102.pdf): заголовок ищется на титульной
     странице (крупные ЗАГЛАВНЫЕ строки), такие переименования всегда
     попадают в отчёт для проверки.
  5. Обложка (covers/<путь>.jpg) переименовывается вместе с книгой.
  6. Коллизия имён → суффикс (2), (3) — ничего не перезаписывается.
  7. Сканированные книги без текстового слоя НЕ переименовываются — они
     попадают в отчёт; для них названия можно задать вручную в
     rename_overrides.json и запустить скрипт снова.
  8. Идемпотентно: повторный запуск ничего не меняет.

ЗАПУСК:
  python3 rename_latin_books.py            # план + отчёт (ничего не меняет)
  python3 rename_latin_books.py --apply    # применить переименования

После --apply в CI дальше запускаются build.py, generate_covers_manifest.py,
generate_search_index.py — они пересобирают manifest.json, books.json,
обложки и поисковый индекс.

В GITHUB ACTIONS:
  workflow «✏️ Rename latin books» (.github/workflows/rename-books.yml).
  mode=plan  — только отчёт (rename_report.md коммитится в репо);
  mode=apply — переименовать и закоммитить, дальше build.yml всё пересоберёт.
"""

import json
import re
import subprocess
import sys
import difflib
import filecmp
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOOKS_DIR = ROOT / "books"
COVERS_DIR = ROOT / "covers"
OVERRIDES_FILE = ROOT / "rename_overrides.json"
REPORT_MD = ROOT / "rename_report.md"
PLAN_JSON = ROOT / "rename_plan.json"

BOOK_EXTS = {".pdf", ".epub", ".fb2", ".doc"}   # .docx — сгенерированная копия, не трогаем
MATCH_THRESHOLD = 0.72          # минимальное сходство «название ↔ имя файла»
PDF_PAGES_TO_SCAN = 6           # титул обычно на 1–3 странице

# ── Старая таджикская кодировка шрифтов («ЉУМЊУРИИ» → «ҶУМҲУРИИ») ──────────
LEGACY = str.maketrans("ЉљЊњЌќЃѓЇїЎў", "ҶҷҲҳҚқҒғӢӣӮӯ")

# ── Кириллица → латиница (для сверки с именем файла; ъ/ь исчезают) ─────────
_CYR2LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ғ": "gh", "д": "d", "е": "e",
    "ё": "jo", "ж": "zh", "з": "z", "и": "i", "ӣ": "i", "й": "y", "к": "k",
    "қ": "q", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ӯ": "u", "ф": "f", "х": "kh", "ҳ": "h",
    "ц": "ts", "ч": "ch", "ҷ": "j", "ш": "sh", "щ": "shch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "ju", "я": "ja",
}
CYR_LETTER = re.compile(r"[А-ЯЁа-яёҒғӢӣҚқӮӯҲҳҶҷ]")
LAT_LETTER = re.compile(r"[A-Za-z]")
CONNECTORS = {"ва", "и", "в", "с", "бо", "дар", "аз", "ё", "на", "по", "к", "у", "о", "ба"}
# строки, которые точно не являются названием (для цифровых имён)
NOT_TITLE_WORDS = re.compile(
    r"Ҷумҳурии|Вазорати|Муассисаи|Президенти|[Аа]кадеми|[Ии]нститут|Донишгоҳ|ДОНИШГОҲ|"
    r"Маориф|МАОРИФ|Российская|[Нн]аук|Душанбе|ДУШАНБЕ|УДК|ISBN|ББК|тавсия|мушовара|"
    r"Донишҷӯён|донишҷӯёни|мактабҳои|ҳамчун китоби|Электрон|каталог|библиотек",
    re.I,
)
AUTHOR_LIKE = re.compile(r"^[А-ЯЁҒҚҲҶӮӢA-Z]\.\s?[А-ЯЁҒҚҲҶӮӢA-Z]\.(\s?[А-ЯЁҒҚҲҶӮӢA-Z]\.)?")


def stem_kind(stem: str) -> str:
    if CYR_LETTER.search(stem):
        return "cyr"            # уже правильное имя — не трогаем
    if re.fullmatch(r"[0-9 _\-().±†°]*", stem):
        return "digits"         # только цифры («12102», «1__1»)
    if LAT_LETTER.search(stem):
        return "latin"          # транслит или иностранное название
    return "other"


def norm_lat(s: str) -> str:
    """Кириллическое название → нормализованная латиница (для сравнения)."""
    s = s.lower().translate(str.maketrans(_CYR2LAT))
    return re.sub(r"[^a-z0-9]", "", s)


def roundtrip_score(title: str, stem: str) -> float:
    a = norm_lat(title)
    b = re.sub(r"[^a-z0-9]", "", stem.lower())
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def title_case(s: str) -> str:
    """«ДИН ВА ИФРОТ» → «Дин ва ифрот» (структурные слова — строчными)."""
    words = s.split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if i > 0 and lw.strip("«»()\"'.,:;") in CONNECTORS:
            out.append(lw)
        elif w.isupper() or w.islower():
            out.append(lw.capitalize())
        else:
            out.append(w)
    return " ".join(out)


def clean_title(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" .:-–—")
    return s


# ── PDF: текст первых страниц ──────────────────────────────────────────────
def pdf_pages_text(path: Path) -> str:
    try:
        out = subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(PDF_PAGES_TO_SCAN), "-layout", str(path), "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=180,
        )
        return out.stdout.decode("utf-8", "ignore").translate(LEGACY)
    except Exception:
        return ""


def _line_ok(l: str) -> bool:
    letters = CYR_LETTER.findall(l)
    if len(letters) < 4 or len(l) > 130:
        return False
    if len(letters) / max(1, len(letters) + len(LAT_LETTER.findall(l))) < 0.75:
        return False
    if re.search(r"УДК|ISBN|ББК|^20\d\d|©|^\(c\)", l, re.I):
        return False
    if re.fullmatch(r"[\d\s.\-–/()]+", l):
        return False
    return True


def candidate_lines(text: str) -> list[str]:
    """Похожие на название строки (кириллица, разумная длина, без мусора).
    Плюс куски библиографических записей: «Н-10. Азизи Азиз. Афсонаи пеш аз хоб.
    Душанбе, Маориф, 2019.» → кандидат «Афсонаи пеш аз хоб» (проверка
    «туда-обратно» отсеет авторов и города)."""
    keep = []
    for raw in text.splitlines():
        l = re.sub(r"\s{2,}\d{1,3}$", "", raw.strip())   # номер страницы в конце строки
        if not l:
            continue
        if l.lower() in CONNECTORS:   # «ва» — для склейки многострочных названий
            keep.append(l)
            continue
        if l.count(". ") >= 2:
            # библиографическая запись → куски между «. »
            # («Н-10. Азизи Азиз. Афсонаи пеш аз хоб. Душанбе...» → «Афсонаи пеш аз хоб»);
            # для настоящих названий с точками склейка соседних кусков восстановит их
            for seg in l.split(". "):
                seg = seg.strip(" .,;")
                if len(seg) > 4 and _line_ok(seg):
                    keep.append(seg)
            continue
        if _line_ok(l):
            keep.append(l)
    return keep


def best_latin_title(stem: str, cands: list[str]) -> tuple[str | None, float]:
    """Лучшее название среди кандидатов и их склеек (до 4 строк подряд).
    Побеждает строго наибольший балл «туда-обратно» — мусор не добавляется."""
    best, best_s = None, 0.0
    for i in range(len(cands)):
        combo = ""
        for j in range(i, min(i + 6, len(cands))):
            combo = (combo + " " + cands[j]).strip()
            if len(combo) > 130:
                break
            s = roundtrip_score(combo, stem)
            if s > best_s + 0.002:
                best, best_s = combo, s
    return best, best_s


def digits_title(text: str) -> str | None:
    """Название для файла с цифровым именем: самый длинный «блок заглавных
    строк» титульной страницы (учреждения/авторы/города отфильтрованы)."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    runs, cur = [], []
    for l in lines:
        letters = CYR_LETTER.findall(l)
        if len(letters) < 4 or len(l) > 120:
            if cur:
                runs.append(cur)
                cur = []
            continue
        upper = CYR_LETTER.findall("".join(ch for ch in l if ch.isupper()))
        is_caps = len(upper) / max(1, len(letters)) >= 0.6
        bad = bool(NOT_TITLE_WORDS.search(l)) or bool(AUTHOR_LIKE.match(l)) or l.lower() in {"тоҷикистон", "тоҷикистон."}
        if is_caps and not bad:
            cur.append(l)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    if not runs:
        return None
    # самый длинный блок (по буквам), при равенстве — верхний
    runs.sort(key=lambda r: -sum(len(CYR_LETTER.findall(x)) for x in r))
    best_run = runs[0]
    title = clean_title(" ".join(best_run))
    if not (4 <= len(title) <= 120):
        return None
    letters = len(CYR_LETTER.findall(title))
    if letters / max(1, len(title)) < 0.55:
        return None
    return title


# ── fb2 / epub: встроенные метаданные ──────────────────────────────────────
def fb2_epub_title(path: Path) -> str | None:
    try:
        import build  # helpers уже есть в репо
        title, _ = build.book_meta(path)
        return title
    except Exception:
        return None


def translit_confirm(title: str, stem: str) -> bool:
    return roundtrip_score(title, stem) >= MATCH_THRESHOLD


# ── основная логика ────────────────────────────────────────────────────────
def sanitize(title: str, ext: str) -> str | None:
    try:
        import build
        return build.sanitize_filename(title, ext)
    except Exception:
        name = re.sub(r"[\\/:*?\"<>|\r\n\t]", " ", title).replace("_", " ")
        name = re.sub(r"\s+", " ", name).strip(" .")[:100]
        return (name + ext) if name else None


def unique_target(path: Path, new_base: str) -> Path:
    target = path.with_name(new_base)
    if target == path:
        return target
    stem, ext = new_base[: -len(path.suffix)], path.suffix
    n = 2
    while target.exists():
        target = path.with_name(f"{stem} ({n}){ext}")
        n += 1
    return target


def same_content(a: Path, b: Path) -> bool:
    """Байт-в-байт одинаковое содержимое (сначала быстрый size-чек)."""
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def find_duplicate(path: Path, title: str) -> Path | None:
    """Если файл с целевым именем УЖЕ есть и содержимое байт-в-байт совпадает —
    это дубль (типичный случай: restore-missing-files вернул старую латинскую
    копию, хотя кириллическая уже есть). Латинский файл тогда УДАЛЯЕТСЯ,
    а не переименовывается в «Название (2).pdf»."""
    nb = sanitize(title, path.suffix.lower())
    if not nb:
        return None
    twin = path.with_name(nb)
    if twin == path or not twin.exists():
        return None
    return twin if same_content(path, twin) else None


def decide(path: Path) -> dict:
    """Возвращает {action: rename|skip|manual, new_base?, reason}."""
    stem, ext = path.stem, path.suffix.lower()
    kind = stem_kind(stem)
    if kind == "cyr":
        return {"action": "skip", "reason": "имя уже кириллическое"}
    if ext == ".doc":
        return {"action": "manual", "reason": ".doc без метаданных — только вручную"}

    if ext in (".epub", ".fb2"):
        title = fb2_epub_title(path)
        if not title:
            return {"action": "manual", "reason": "fb2/epub без названия в метаданных"}
        if not CYR_LETTER.search(title):
            return {"action": "skip", "reason": f"метаданные на латинице (иностранная): «{title[:40]}»"}
        title = clean_title(title)
        if kind == "digits" or translit_confirm(title, stem):
            return {"action": "rename", "title": title, "checked": kind != "digits"}
        return {"action": "skip", "reason": f"название из метаданных не совпадает с именем файла: «{title[:40]}»"}

    # PDF
    text = pdf_pages_text(path)
    if not text.strip():
        return {"action": "manual", "reason": "скан без текстового слоя (нужно OCR или вручную)"}
    cands = candidate_lines(text)
    if kind == "latin":
        title, s = best_latin_title(stem, cands)
        if title and s >= MATCH_THRESHOLD:
            return {"action": "rename", "title": clean_title(title), "checked": True, "score": round(s, 2)}
        return {"action": "skip",
                "reason": "название из книги не совпало с транслитом имени (иностранная/не найдено)"}
    # digits
    title = digits_title(text)
    if title:
        return {"action": "rename", "title": title, "checked": False}
    return {"action": "manual", "reason": "титул не распознан (скан или необычная вёрстка)"}


def main() -> int:
    apply = "--apply" in sys.argv
    if not BOOKS_DIR.exists():
        print("Папка books/ не найдена — запускайте из корня репозитория")
        return 1

    # 1) ручные переопределения (сканы и сложные случаи)
    overrides = {}
    if OVERRIDES_FILE.exists():
        try:
            overrides = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"⚠ rename_overrides.json не читается: {e}")

    targets = [p for p in sorted(BOOKS_DIR.rglob("*"))
               if p.is_file() and p.suffix.lower() in BOOK_EXTS]
    print(f"Всего файлов книг: {len(targets)}")

    plan, to_rename, manual, skipped = [], [], [], 0
    skipped_reasons, to_delete = [], []
    for path in targets:
        rel = path.relative_to(ROOT).as_posix()
        if rel in overrides:
            title = clean_title(str(overrides[rel]))
            if title:
                twin = find_duplicate(path, title)
                if twin:
                    to_delete.append((path, twin))
                    plan.append({"file": rel, "duplicate_of": twin.name, "source": "duplicate"})
                else:
                    to_rename.append((path, title, "override"))
                    plan.append({"file": rel, "new": title, "source": "override"})
            continue
        d = decide(path)
        if d["action"] == "skip":
            skipped += 1
            if stem_kind(path.stem) in ("latin", "digits"):
                skipped_reasons.append((rel, d["reason"]))
        elif d["action"] == "manual":
            manual.append((rel, d["reason"]))
        else:
            title = d["title"]
            if title == title.upper():
                title = title_case(title)   # «ДИН ВА ИФРОТ» → «Дин ва ифрот»
            twin = find_duplicate(path, title)
            if twin:
                to_delete.append((path, twin))
                plan.append({"file": rel, "duplicate_of": twin.name, "source": "duplicate"})
                continue
            to_rename.append((path, title, "checked" if d.get("checked") else "digits"))
            plan.append({"file": rel, "new": title, "source": d.get("checked") and "verified" or "digits",
                         "score": d.get("score")})

    # отчёт
    lines = ["# Отчёт: латинские/цифровые имена книг", ""]
    lines.append(f"* Подтверждено «туда-обратно» (безопасно): **{sum(1 for _,_,s in to_rename if s=='checked')}**")
    lines.append(f"* По титульной странице (цифровые имена): **{sum(1 for _,_,s in to_rename if s=='digits')}**")
    lines.append(f"* Вручную (переопределение): **{sum(1 for _,_,s in to_rename if s=='override')}**")
    lines.append(f"* НЕ тронем (уже кириллица / иностранные / не совпало): **{skipped}**")
    lines.append(f"* Требуют ручного решения: **{len(manual)}**")
    lines.append(f"* 🗑 Дубликаты (точные копии — лишний файл удалится): **{len(to_delete)}**")
    lines.append("")
    lines.append("## Переименования")
    lines.append("")
    lines.append("| Файл | → Новое имя | источник |")
    lines.append("|---|---|---|")
    for path, title, src in to_rename:
        nb = sanitize(title, path.suffix.lower())
        lines.append(f"| `{path.relative_to(ROOT).as_posix()}` | `{nb}` | {src} |")
    if to_delete:
        lines.append("")
        lines.append("## 🗑 Дубликаты (удаление лишней копии)")
        lines.append("")
        lines.append("Целевой файл уже существует, и содержимое байт-в-байт одинаковое")
        lines.append("(обычно так restore-missing-files вернул старую латинскую копию).")
        lines.append("Латинская копия удалится, кириллическая останется как есть.")
        lines.append("")
        for path, twin in to_delete:
            lines.append(f"- `{path.relative_to(ROOT).as_posix()}` — точная копия `{twin.name}`")
    if skipped_reasons:
        lines.append("")
        lines.append("## НЕ тронем (безопасность: иностранные / не подтвердилось)")
        lines.append("")
        for rel, reason in skipped_reasons[:120]:
            lines.append(f"- `{rel}` — {reason}")
        if len(skipped_reasons) > 120:
            lines.append(f"- … и ещё {len(skipped_reasons) - 120}")
    if manual:
        lines.append("")
        lines.append("## Не переименовано (нужно посмотреть глазами)")
        lines.append("")
        lines.append("Для этих книг можно указать название вручную в `rename_overrides.json`")
        lines.append('(формат: {"books/Папка/файл.pdf": "Настоящее название"}) и запустить скрипт снова.')
        lines.append("")
        for rel, reason in manual:
            lines.append(f"- `{rel}` — {reason}")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    PLAN_JSON.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"  ✅ к переименованию: {len(to_rename)}")
    print(f"  ⏸ не трогаем:        {skipped}")
    print(f"  👁 вручную (отчёт):  {len(manual)}")
    if to_delete:
        print(f"  🗑 дубликаты:        {len(to_delete)}")
    print(f"Отчёт: {REPORT_MD.name}  (план: {PLAN_JSON.name})")

    if not apply:
        print("\nЭто был ПЛАН (ничего не изменено). Для применения: python3 rename_latin_books.py --apply")
        return 0

    # применение
    import build
    done, removed_dupes = 0, 0
    for path, twin in to_delete:
        # точный дубль: латинская копия удаляется, обложка при необходимости переезжает
        old_cover = build.cover_path_for_book(path)
        new_cover = build.cover_path_for_book(twin)
        if old_cover.exists():
            if new_cover.exists():
                old_cover.unlink()
            else:
                new_cover.parent.mkdir(parents=True, exist_ok=True)
                old_cover.rename(new_cover)
        path.unlink()
        removed_dupes += 1
        print(f"🗑 дубль удалён: {path.name} (копия {twin.name})")
    for path, title, src in to_rename:
        new_base = sanitize(title, path.suffix.lower())
        if not new_base:
            continue
        target = unique_target(path, new_base)
        if target == path:
            continue
        # обложка следует за книгой (как в build.py)
        old_cover = build.cover_path_for_book(path)
        new_cover = build.cover_path_for_book(target)
        if old_cover.exists():
            if new_cover.exists():
                old_cover.unlink()
            else:
                new_cover.parent.mkdir(parents=True, exist_ok=True)
                old_cover.rename(new_cover)
        path.rename(target)
        done += 1
        print(f"✏️ {path.relative_to(ROOT).as_posix()} → {target.name}")
    print(f"\nПереименовано: {done}")
    if removed_dupes:
        print(f"Удалено дублей: {removed_dupes}")
    print("Дальше CI пересоберёт manifest.json, books.json, обложки и индекс поиска.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
