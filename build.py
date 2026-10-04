#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Китобхона — auto builder for sharipovip/books

What it does:
1) Scans books/** for book files (pdf, epub, fb2, doc, docx, mp4, m4v, webm, txt, zip).
2) Writes manifest.json into every folder that contains them.
3) Writes root books.json from the real folder structure.
4) Generates covers/<same folder>/<book name>.jpg from a PDF page, embedded cover, or consistent fallback artwork.

Idempotent: repeated runs do not duplicate anything and commit only real changes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = ImageDraw = ImageFont = None

ROOT = Path(__file__).resolve().parent
BOOKS_DIR = ROOT / "books"
COVERS_DIR = ROOT / "covers"
BOOKS_JSON = ROOT / "books.json"
COVER_SOURCE_HASHES = ROOT / "cover_source_hashes.json"
DISPLAY_NAMES = ROOT / "display_names.json"
RENAMED_BOOK_PATHS: dict[str, str] = {}
# False = для PDF название берётся из ИМЕНИ ФАЙЛА (как раньше), а не из метаданных PDF.
USE_PDF_METADATA_TITLE = False
REPO = os.environ.get("KITOB_REPO", "sharipovip/books")
BRANCH = os.environ.get("KITOB_BRANCH", "main")
TODAY = date.today().isoformat()

PDF_EXT = ".pdf"
# v94: бисёрформат — ғайр аз PDF ин форматҳо низ ба manifest.json ва books.json дохил мешаванд
# (барнома онҳоро мекушояд: epub/fb2/docx дар дохил, .doc тавассути барномаи берунӣ, mp4/текст)
BOOK_EXTS = {".pdf", ".epub", ".fb2", ".doc", ".docx", ".mp4", ".m4v", ".webm", ".txt", ".zip"}
COVER_W = int(os.environ.get("COVER_W", "400"))
COVER_H = int(os.environ.get("COVER_H", "600"))
COVER_QUALITY = int(os.environ.get("COVER_QUALITY", "78"))

CATEGORY_ORDER = {
    "Пешвои миллат": 1,
    "Kitobhoi_darsi": 10,
    "Китобҳои дарсӣ": 10,
    "Адабиёти классикӣ": 20,
    "Адабиёти ҷаҳон": 30,
    "Адабиёти муосир": 31,
    "Чистон": 40,
    "Фарҳанг": 50,
    "Зиндагинома": 51,
    "Журналистика": 52,
    "Иқтисод": 60,
    "Тиб": 61,
    "Дигар": 999,
}

CATEGORY_META = {
    "Пешвои миллат": ("Китобҳои Асосгузори сулҳу ваҳдати миллӣ – Пешвои миллат", "👑", "#b45309", "#f59e0b"),
    "Kitobhoi_darsi": ("Китобҳои дарсӣ", "🎓", "#2563eb", "#3b82f6"),
    "Адабиёти классикӣ": ("Адабиёти классикӣ", "📜", "#7c2d12", "#f97316"),
    "Адабиёти ҷаҳон": ("Адабиёти ҷаҳон", "🌍", "#0891b2", "#22d3ee"),
    "Адабиёти муосир": ("Адабиёти муосир", "✍️", "#7c3aed", "#a78bfa"),
    "Чистон": ("Чистон", "🧩", "#0d9488", "#5eead4"),
    "Фарҳанг": ("Фарҳанг", "🎨", "#d97706", "#fbbf24"),
    "Зиндагинома": ("Зиндагинома", "👤", "#854d0e", "#facc15"),
    "Журналистика": ("Журналистика", "📰", "#525252", "#a3a3a3"),
    "Иқтисод": ("Иқтисод", "💼", "#0e7490", "#06b6d4"),
    "Тиб": ("Тиб", "⚕️", "#dc2626", "#f87171"),
    "Дигар": ("Дигар", "📂", "#64748b", "#94a3b8"),
}

NAME_MAP = {
    "Sinfi_1": "Синфи 1", "Sinfi_2": "Синфи 2", "Sinfi_3": "Синфи 3", "Sinfi_4": "Синфи 4",
    "Sinfi_5": "Синфи 5", "Sinfi_6": "Синфи 6", "Sinfi_7": "Синфи 7", "Sinfi_8": "Синфи 8",
    "Sinfi_9": "Синфи 9", "Sinfi_10": "Синфи 10", "Sinfi_11": "Синфи 11",
    "Kitobhoi_darsi": "Китобҳои дарсӣ",
}

EMOJI_BY_WORD = [
    ("синфи 1", "1️⃣"), ("синфи 2", "2️⃣"), ("синфи 3", "3️⃣"), ("синфи 4", "4️⃣"),
    ("синфи 5", "5️⃣"), ("синфи 6", "6️⃣"), ("синфи 7", "7️⃣"), ("синфи 8", "8️⃣"),
    ("синфи 9", "9️⃣"), ("синфи 10", "🔟"), ("синфи 11", "🎓"),
    ("пешвои", "👑"), ("шеър", "🌹"), ("назм", "📝"), ("наср", "📚"),
    ("роман", "📕"), ("қисса", "📖"), ("таърих", "🏛"), ("дин", "🕌"),
    ("илм", "🔬"), ("фалсафа", "🤔"), ("луғат", "📘"), ("ёддошт", "📔"),
    ("зиндагинома", "👤"), ("журналист", "📰"), ("тиб", "⚕️"),
    ("иқтисод", "💼"), ("молия", "💰"), ("маркетинг", "📈"),
    ("бухгалтер", "🧾"), ("чистон", "🧩"), ("фарҳанг", "🎨"),
]

PALETTES = [
    ("#2563eb", "#60a5fa"), ("#7c3aed", "#a78bfa"), ("#0d9488", "#5eead4"),
    ("#d97706", "#fbbf24"), ("#dc2626", "#f87171"), ("#0891b2", "#22d3ee"),
    ("#16a34a", "#86efac"), ("#be185d", "#f472b6"), ("#64748b", "#94a3b8"),
]


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠ Could not read {path}: {e}")
        return default


def write_json_if_changed(path: Path, data: Any) -> bool:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def rel_posix(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def slug(text: str) -> str:
    # Latin slugs for IDs; deterministic and safe.
    tr = str.maketrans({
        "А":"a","Б":"b","В":"v","Г":"g","Д":"d","Е":"e","Ё":"yo","Ж":"zh","З":"z","И":"i","Й":"y","К":"k","Л":"l","М":"m","Н":"n","О":"o","П":"p","Р":"r","С":"s","Т":"t","У":"u","Ф":"f","Х":"h","Ц":"ts","Ч":"ch","Ш":"sh","Щ":"sh","Ъ":"","Ы":"y","Ь":"","Э":"e","Ю":"yu","Я":"ya",
        "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"yo","ж":"zh","з":"z","и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"ts","ч":"ch","ш":"sh","щ":"sh","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya",
        "Қ":"q","қ":"q","Ғ":"gh","ғ":"gh","Ҳ":"h","ҳ":"h","Ҷ":"j","ҷ":"j","Ӣ":"i","ӣ":"i","Ӯ":"u","ӯ":"u",
    })
    s = text.translate(tr).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "item"


def display_name(raw: str, overrides: dict[str, Any]) -> str:
    item = overrides.get(raw)
    if isinstance(item, str):
        return item
    if isinstance(item, dict) and item.get("name"):
        return str(item["name"])
    return NAME_MAP.get(raw, raw.replace("_", " "))


def display_emoji(name: str, raw: str, overrides: dict[str, Any]) -> str:
    item = overrides.get(raw)
    if isinstance(item, dict) and item.get("emoji"):
        return str(item["emoji"])
    low = name.lower()
    for key, em in EMOJI_BY_WORD:
        if key in low:
            return em
    return "📚"


def category_meta(raw: str, overrides: dict[str, Any], idx: int) -> tuple[str, str, str, str, int, bool]:
    # returns name, emoji, c1, c2, sort_order, priority
    item = overrides.get(raw)
    priority = raw == "Пешвои миллат"
    sort_order = CATEGORY_ORDER.get(raw, 100 + idx)
    if isinstance(item, dict):
        name = str(item.get("name") or CATEGORY_META.get(raw, (display_name(raw, overrides),))[0])
        emoji = str(item.get("emoji") or CATEGORY_META.get(raw, (None, "📚"))[1])
        c1 = str(item.get("color1") or CATEGORY_META.get(raw, (None, None, PALETTES[idx % len(PALETTES)][0]))[2])
        c2 = str(item.get("color2") or CATEGORY_META.get(raw, (None, None, None, PALETTES[idx % len(PALETTES)][1]))[3])
        sort_order = int(item.get("sort_order") or sort_order)
        priority = bool(item.get("priority", priority))
        return name, emoji, c1, c2, sort_order, priority
    if raw in CATEGORY_META:
        name, emoji, c1, c2 = CATEGORY_META[raw]
        return name, emoji, c1, c2, sort_order, priority
    c1, c2 = PALETTES[idx % len(PALETTES)]
    return display_name(raw, overrides), display_emoji(display_name(raw, overrides), raw, overrides), c1, c2, sort_order, priority


def collect_pdf_dirs() -> dict[Path, list[Path]]:
    result: dict[Path, list[Path]] = {}
    if not BOOKS_DIR.exists():
        print("⚠ books/ directory does not exist")
        return result
    for item in BOOKS_DIR.rglob("*"):
        if item.is_file() and item.suffix.lower() in BOOK_EXTS:
            # v99: .docx/.txt, лежащие РЯДОМ с .doc — это служебные копии для
            # показа внутри приложения (doc→docx конвертация). Их НЕ показываем
            # в каталоге отдельными книгами.
            if item.suffix.lower() in (".docx", ".txt") and item.with_suffix(".doc").exists():
                continue
            result.setdefault(item.parent, []).append(item)
    for k in result:
        result[k].sort(key=lambda p: p.name.casefold())
    return dict(sorted(result.items(), key=lambda kv: kv[0].as_posix().casefold()))


# ---------- Метаданные epub/fb2: настоящее название книги + обложка ----------
# Файлы в репо часто названы транслитом («1_Armaghieddon_otkladyvaietsia.epub»),
# а ВНУТРИ файла лежит настоящее название («Армагеддон откладывается») и обложка.
# Мы не переименовываем файлы (ссылки стабильны) — только берём имя и обложку
# из самого файла для manifest.json и covers/.

def _clean_title(t: str | None) -> str | None:
    if not t:
        return None
    t = re.sub(r"\s+", " ", str(t)).strip()
    return t[:120] if t else None


def _epub_opf_path(zf: zipfile.ZipFile) -> str | None:
    try:
        container = zf.read("META-INF/container.xml")
        root = ET.fromstring(container)
        for rf in root.iter():
            if rf.tag.endswith("rootfile"):
                p = rf.get("full-path")
                if p and p in zf.namelist():
                    return p
    except Exception:
        pass
    return None


def _epub_cover_href(opf_dir: str, manifest_items: list, spine_ids: list) -> tuple[str, str] | None:
    # 1) <item properties="cover-image">
    for it in manifest_items:
        props = (it.get("properties") or "").split()
        if "cover-image" in props and (it.get("media-type") or "").startswith("image/"):
            return it.get("href"), it.get("media-type")
    # 2) id похожий на cover
    for it in manifest_items:
        if re.search(r"(^|_)cover($|_)|(cover[-_]?image)", (it.get("id") or ""), re.I) and (it.get("media-type") or "").startswith("image/"):
            return it.get("href"), it.get("media-type")
    # 3) первый spine-файл типа cover.xhtml -> <img> внутри
    for sid in spine_ids[:3]:
        for it in manifest_items:
            if it.get("id") == sid and "html" in (it.get("media-type") or ""):
                href, mt = it.get("href"), it.get("media-type")
                return href + "::__HTML__", mt  # маркер: это страница, не картинка
    return None


def extract_epub_meta(path: Path) -> tuple[str | None, bytes | None]:
    """Возвращает (название, bytes обложки) из EPUB."""
    try:
        with zipfile.ZipFile(path) as zf:
            opf_path = _epub_opf_path(zf)
            if not opf_path:
                return None, None
            opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
            root = ET.fromstring(zf.read(opf_path))
            # название: dc:title
            title = None
            for el in root.iter():
                if el.tag.endswith("}title") and (el.text or "").strip():
                    title = _clean_title(el.text)
                    break
            # обложка
            manifest_items = [el for el in root.iter() if el.tag.endswith("}item")]
            spine_ids = [el.get("idref") for el in root.iter() if el.tag.endswith("}itemref")]
            cover = _epub_cover_href(opf_dir, manifest_items, spine_ids)
            cover_bytes = None
            if cover:
                href, _mt = cover
                if href.endswith("::__HTML__"):
                    # страница cover.xhtml — ищем <img src> внутри
                    try:
                        page_path = href[:-len("::__HTML__")]
                        full = opf_dir + page_path
                        if full not in zf.namelist():
                            full = page_path
                        page = ET.fromstring(zf.read(full))
                        img_src = None
                        for el in page.iter():
                            if el.tag.endswith("}img") and el.get("src"):
                                img_src = el.get("src")
                                break
                        if img_src:
                            img_path = img_src.split("?")[0]
                            full_img = (opf_dir + img_path) if not img_src.startswith("/") else img_path[1:]
                            for cand in {full_img, opf_dir + img_path, img_path}:
                                if cand in zf.namelist():
                                    cover_bytes = zf.read(cand)
                                    break
                    except Exception:
                        pass
                else:
                    img_path = href.split("?")[0]
                    for cand in {opf_dir + img_path, img_path}:
                        if cand in zf.namelist():
                            cover_bytes = zf.read(cand)
                            break
            return title, cover_bytes
    except Exception:
        return None, None


def extract_fb2_meta(path: Path) -> tuple[str | None, bytes | None]:
    """Возвращает (название, bytes обложки) из FB2 (utf-8 и windows-1251)."""
    try:
        root = ET.parse(str(path)).getroot()
        title = None
        for ti in root.iter():
            if ti.tag.endswith("}title-info"):
                for bt in ti.iter():
                    if bt.tag.endswith("}book-title") and (bt.text or "").strip():
                        title = _clean_title(bt.text)
                        break
                # обложка: coverpage/image xlink:href="#id"
                href = None
                for cp in ti.iter():
                    if cp.tag.endswith("}coverpage"):
                        for im in cp.iter():
                            if im.tag.endswith("}image"):
                                for v in (im.get("{http://www.w3.org/1999/xlink}href"), im.get("href"), im.get("l:href")):
                                    if v:
                                        href = v.lstrip("#")
                                        break
                if href:
                    for b in root.iter():
                        if b.tag.endswith("}binary") and b.get("id") == href:
                            data = (b.text or "").replace("\n", "").replace("\r", "").replace(" ", "")
                            return title, base64.b64decode(data)
                break
        return title, None
    except Exception:
        return None, None


def book_meta(path: Path) -> tuple[str | None, bytes | None]:
    ext = path.suffix.lower()
    if ext == ".epub":
        return extract_epub_meta(path)
    if ext == ".fb2":
        return extract_fb2_meta(path)
    return None, None


def sanitize_filename(title: str, ext: str) -> str | None:
    """Название книги → безопасное имя файла (любые алфавиты, вкл. таджикский)."""
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]", " ", title)
    name = name.replace("_", " ")  # «с всяки _» → обычные пробелы
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        return None
    name = name[:100].strip()
    return name + ext


def pretty_book_name(s: str) -> str | None:
    """«1_Kitobi_darsi_2» → «Kitobi darsi 2»: убирает числовой префикс с разделителем
    (1_, 2., 5-) и подчёркивания. Целиком числовые названия («1984», «12065») не трогает."""
    name = str(s or "").strip()
    stripped = re.sub(r"^\d+[_\-.]\s*", "", name)
    if stripped and len(stripped) >= 2:
        name = stripped
    name = name.replace("_", " ")
    name = re.sub(r"\s+", " ", name).strip(" .-")
    return name or None


def pdf_title(path: Path) -> str | None:
    """Заголовок из метаданных PDF (pdfinfo из poppler-utils, есть в GitHub Actions)."""
    if shutil.which("pdfinfo") is None:
        return None
    try:
        out = subprocess.run(
            ["pdfinfo", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        text = out.stdout.decode("utf-8", "ignore")
    except Exception:
        return None
    m = re.search(r"^Title:\s*(.+)$", text, re.M)
    if not m:
        return None
    t = _clean_title(m.group(1))
    if not t:
        return None
    t = re.sub(r"^microsoft word -\s*", "", t, flags=re.I).strip() or None
    if not t:
        return None
    low = t.casefold()
    if low in ("untitled", "untitled document", "document", "powerpoint presentation", "layout"):
        return None
    if low == path.stem.strip().casefold():
        return None
    return t


def rename_books_to_titles() -> int:
    """Переименует файлы epub/fb2/doc в НАСТОЯЩИЕ названия.

    Файлы в репо названы транслитом («1_Armaghieddon_otkladyvaietsia.epub»), а внутри
    каждого файла записано настоящее название («Армагеддон откладывается», «Шоҳнома»...).
    После переименования имя файла, имя в manifest.json и имя обложки
    (covers/<папка>/<название>.jpg) СОВПАДАЮТ. Обложка переименовывается вместе с книгой.
    v99: .doc тоже переименовывается (метаданных нет → просто чистое имя: «1_estetika» →
    «estetika»), а рядом робот кладёт .docx-копию для показа внутри приложения.
    PDF не переименовываются (заголовок из PDF надёжно извлечь нельзя) — их имена и так
    нормальные. Идемпотентно: повторный запуск ничего не меняет.
    """
    global RENAMED_BOOK_PATHS
    RENAMED_BOOK_PATHS = {}
    renamed = 0
    if not BOOKS_DIR.exists():
        return 0
    for path in sorted(BOOKS_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".epub", ".fb2", ".doc"):
            continue
        try:
            title, _cover = book_meta(path)
        except Exception:
            title = None
        if title:
            if path.stem.strip().casefold() == title.strip().casefold():
                continue  # уже называется как книга
            new_base = sanitize_filename(title, path.suffix)
        else:
            # метаданных нет (китобҳои лотинӣ бо «_») — барои ординарӣ: 1_Kitobi_darsi → Kitobi darsi
            pretty = pretty_book_name(path.stem)
            if not pretty or pretty.casefold() == path.stem.strip().casefold():
                continue  # ном аллакай тоза аст
            new_base = sanitize_filename(pretty, path.suffix)
        if not new_base:
            continue
        target = path.with_name(new_base)
        if target.exists() and target != path:
            # коллизия: одинаковое название у двух книг → суффикс (2), (3)...
            stem, ext = new_base[:-len(path.suffix)], path.suffix
            n = 2
            while target.exists() and target != path:
                target = path.with_name(f"{stem} ({n}){ext}")
                n += 1
        if target == path:
            continue
        # обложка следует за книгой (старое имя → новое имя)
        old_cover = cover_path_for_book(path)
        new_cover = cover_path_for_book(target)
        if old_cover.exists():
            if new_cover.exists():
                old_cover.unlink()          # новая уже есть — старую убираем
            else:
                new_cover.parent.mkdir(parents=True, exist_ok=True)
                old_cover.rename(new_cover)
        RENAMED_BOOK_PATHS[rel_posix(path)] = rel_posix(target)
        path.rename(target)
        renamed += 1
        print(f"✏️ renamed: {rel_posix(path)} → {rel_posix(target).split('/')[-1]}")
    return renamed


def convert_docs() -> int:
    """v99: DOC (Word 97-2003) → DOCX-копия рядом с файлом — чтобы приложение
    ПОКАЗЫВАЛО книгу внутри ридера (mammoth читает .docx, но не .doc).

    Порядок качества: LibreOffice (soffice) → полноценный .docx с форматированием;
    antiword → .txt (только текст). В CI build.yml ставит antiword всегда, а
    libreoffice-writer — только если есть .doc без .docx-копии.
    Идемпотентно: если копия уже есть — ничего не делает.
    """
    if not BOOKS_DIR.exists():
        return 0
    docs = [p for p in sorted(BOOKS_DIR.rglob("*.doc")) if p.is_file()]
    if not docs:
        return 0
    have_soffice = shutil.which("soffice") is not None
    have_antiword = shutil.which("antiword") is not None
    if not have_soffice and not have_antiword:
        print("⚠ Найдены .doc, но нет конвертера (soffice/antiword) — копии не созданы")
        return 0
    converted = 0
    for path in docs:
        docx = path.with_suffix(".docx")
        txt = path.with_suffix(".txt")
        if docx.exists() or txt.exists():
            continue  # копия уже есть
        if have_soffice:
            try:
                subprocess.run(
                    ["soffice", "--headless", "--convert-to", "docx", "--outdir", str(path.parent), str(path)],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300,
                )
                if docx.exists() and docx.stat().st_size > 0:
                    print(f"📄 doc→docx: {rel_posix(docx)}")
                    converted += 1
                    continue
            except Exception as e:
                print(f"⚠ doc→docx не удалось ({path.name}): {e}")
        if have_antiword:
            try:
                out = subprocess.run(
                    ["antiword", "-w", "0", str(path)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90,
                )
                if out.returncode == 0:
                    text = out.stdout.decode("utf-8", "replace").strip()
                    if text:
                        txt.write_text(text + "\n", encoding="utf-8")
                        print(f"📄 doc→txt: {rel_posix(txt)}")
                        converted += 1
                        continue
            except Exception as e:
                print(f"⚠ doc→txt не удалось ({path.name}): {e}")
        print(f"⚠ {path.name}: копия для показа не создана")
    return converted


def pdf_info(pdf: Path) -> dict[str, Any]:
    st = pdf.stat()
    name = pdf.stem
    if pdf.suffix.lower() in (".epub", ".fb2"):
        # настоящее название книги из самого файла (вместо транслита имени файла)
        try:
            title, _cover = book_meta(pdf)
            if title:
                name = title
        except Exception:
            pass
    elif pdf.suffix.lower() == ".pdf" and USE_PDF_METADATA_TITLE:
        # PDF: заголовок из метаданных. ВЫКЛЮЧЕНО по умолчанию: в метаданных многих учебников
        # мусор («Author: ikbol», «68.cdr», «Sanat va Mehnat s4.in») и он портил названия.
        try:
            t = pdf_title(pdf)
            if t:
                name = t
        except Exception:
            pass
    # чистим отображаемое имя: «1_Kitobi_darsi» → «Kitobi darsi» (файлы PDF не переименовываются!)
    pretty = pretty_book_name(name)
    if pretty and pretty.casefold() != name.strip().casefold():
        name = pretty
    return {
        "name": name,
        "file": pdf.name,
        "size": st.st_size,
        "mtime": int(st.st_mtime),
    }


def build_manifests(pdf_dirs: dict[Path, list[Path]]) -> int:
    changed = 0
    for folder, pdfs in pdf_dirs.items():
        manifest = {
            "version": 1,
            "updatedAt": TODAY,
            "folder": rel_posix(folder),
            "books": [pdf_info(p) for p in pdfs],
        }
        if write_json_if_changed(folder / "manifest.json", manifest):
            changed += 1
            print(f"📝 manifest: {rel_posix(folder)}/manifest.json ({len(pdfs)} files)")
    return changed


def is_leaf_or_pdf_dir(path: Path, pdf_dirs: dict[Path, list[Path]]) -> bool:
    return path in pdf_dirs and bool(pdf_dirs[path])


def build_books_json(pdf_dirs: dict[Path, list[Path]], overrides: dict[str, Any]) -> bool:
    top_to_subs: dict[str, list[Path]] = {}
    for folder in pdf_dirs:
        try:
            rel = folder.relative_to(BOOKS_DIR)
        except ValueError:
            continue
        parts = rel.parts
        if not parts:
            continue
        top = parts[0]
        top_to_subs.setdefault(top, []).append(folder)

    categories = []
    for idx, top in enumerate(sorted(top_to_subs.keys(), key=lambda x: (CATEGORY_ORDER.get(x, 1000), x.casefold()))):
        top_path = BOOKS_DIR / top
        cat_name, cat_emoji, c1, c2, sort_order, priority = category_meta(top, overrides, idx)
        sub_dirs = sorted(top_to_subs[top], key=lambda p: p.as_posix().casefold())
        subs = []
        for subdir in sub_dirs:
            rel_under_books = subdir.relative_to(BOOKS_DIR)
            parts = rel_under_books.parts
            # If PDFs are directly inside top folder, the sub is the category itself.
            raw_sub = top if len(parts) == 1 else parts[-1]
            sub_name = cat_name if len(parts) == 1 and priority else display_name(raw_sub, overrides)
            sub_emoji = display_emoji(sub_name, raw_sub, overrides)
            subs.append({
                "id": slug("_".join(parts)),
                "name": sub_name,
                "folder_raw": raw_sub,
                "folder": rel_posix(subdir),
                "emoji": sub_emoji,
            })
        cat = {
            "id": slug(top),
            "name": cat_name,
            "folder_raw": top,
            "emoji": cat_emoji,
            "color1": c1,
            "color2": c2,
            "sort_order": sort_order,
            "subs": subs,
        }
        if priority:
            cat["priority"] = True
        categories.append(cat)

    categories.sort(key=lambda c: (0 if c.get("priority") else 1, c.get("sort_order", 999), c["name"]))
    data = {
        "version": 3,
        "updatedAt": TODAY,
        "repo": REPO,
        "branch": BRANCH,
        "categories": categories,
    }
    changed = write_json_if_changed(BOOKS_JSON, data)
    if changed:
        print(f"📚 books.json: {len(categories)} categories")
    return changed


def cover_path_for_book(pdf: Path) -> Path:
    rel = pdf.relative_to(BOOKS_DIR)
    return COVERS_DIR / rel.with_suffix(".jpg")


def file_sha1(path: Path, max_bytes: int = 1024 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            b = f.read(max_bytes)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cover_is_usable(cover: Path) -> bool:
    return cover.exists() and cover.stat().st_size >= 500


def generate_cover(pdf: Path, cover: Path) -> bool:
    """Render the first PDF page. Return True when the result was verified/saved."""
    if shutil.which("pdftoppm") is None:
        print("⚠ pdftoppm not found, skipping covers")
        return False
    if Image is None:
        print("⚠ Pillow not found, skipping covers")
        return False
    cover.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        prefix = str(Path(td) / "page")
        cmd = ["pdftoppm", "-f", "1", "-singlefile", "-jpeg", "-r", "120", str(pdf), prefix]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        except subprocess.CalledProcessError as e:
            print(f"⚠ cover failed for {rel_posix(pdf)}: {e.stderr.decode('utf-8', 'ignore')[:200]}")
            return False
        except subprocess.TimeoutExpired:
            print(f"⚠ cover timeout: {rel_posix(pdf)}")
            return False
        img_path = Path(prefix + ".jpg")
        if not img_path.exists():
            print(f"⚠ cover not produced: {rel_posix(pdf)}")
            return False
        try:
            im = Image.open(img_path).convert("RGB")
            im.thumbnail((COVER_W, COVER_H), Image.LANCZOS)
            canvas = Image.new("RGB", (COVER_W, COVER_H), (245, 240, 228))
            x = (COVER_W - im.width) // 2
            y = (COVER_H - im.height) // 2
            canvas.paste(im, (x, y))
            tmp = cover.with_suffix(".tmp.jpg")
            canvas.save(tmp, "JPEG", quality=COVER_QUALITY, optimize=True, progressive=True)
            if cover.exists() and file_sha1(tmp) == file_sha1(cover):
                tmp.unlink(missing_ok=True)
                return True
            tmp.replace(cover)
            print(f"🖼 cover: {rel_posix(cover)}")
            return True
        except Exception as e:
            print(f"⚠ cover save failed for {rel_posix(pdf)}: {e}")
            return False

def save_cover_bytes(data: bytes, cover: Path) -> bool:
    """Обложка из bytes (epub/fb2) — тот же вид, что у PDF-обложек: 400x600, белый фон."""
    if Image is None:
        return False
    try:
        import io
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((COVER_W, COVER_H), Image.LANCZOS)
        canvas = Image.new("RGB", (COVER_W, COVER_H), (245, 240, 228))
        canvas.paste(im, ((COVER_W - im.width) // 2, (COVER_H - im.height) // 2))
        cover.parent.mkdir(parents=True, exist_ok=True)
        tmp = cover.with_suffix(".tmp.jpg")
        canvas.save(tmp, "JPEG", quality=COVER_QUALITY, optimize=True, progressive=True)
        if cover.exists() and file_sha1(tmp) == file_sha1(cover):
            tmp.unlink(missing_ok=True)
            return True
        tmp.replace(cover)
        return True
    except Exception as e:
        print(f"⚠ cover from meta failed for {cover.name}: {e}")
        return False


def generate_cover_from_meta(book: Path, cover: Path) -> bool:
    try:
        _title, data = book_meta(book)
    except Exception:
        data = None
    if not data:
        return False
    return save_cover_bytes(data, cover)


def _cover_font(size: int, bold: bool = False):
    if ImageFont is None:
        return None
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size=size)
            except Exception:
                pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _cover_title(book: Path) -> str:
    if book.suffix.lower() in (".epub", ".fb2"):
        try:
            title, _cover = book_meta(book)
            if title:
                return title
        except Exception:
            pass
    elif book.suffix.lower() == ".pdf":
        try:
            title = pdf_title(book)
            if title:
                return title
        except Exception:
            pass
    return pretty_book_name(book.stem) or book.stem


def _wrap_cover_title(text: str, font, draw, max_width: int) -> list[str]:
    words = str(text or "Китоб").split()
    if not words:
        return ["Китоб"]
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = (line + " " + word).strip()
        try:
            width = draw.textbbox((0, 0), candidate, font=font)[2]
        except Exception:
            width = len(candidate) * 12
        if line and width > max_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    if len(lines) > 5:
        lines = lines[:5]
        lines[-1] = lines[-1].rstrip(" .…") + "…"
    return lines


def generate_generic_cover(book: Path, cover: Path) -> bool:
    """Create consistent artwork for supported formats without an extractable cover."""
    if Image is None or ImageDraw is None:
        print("⚠ Pillow not found, skipping generic cover")
        return False
    try:
        seed = hashlib.sha1(rel_posix(book).encode("utf-8")).digest()
        color_a, color_b = PALETTES[seed[0] % len(PALETTES)]
        start, end = _hex_rgb(color_a), _hex_rgb(color_b)
        canvas = Image.new("RGB", (COVER_W, COVER_H), start)
        draw = ImageDraw.Draw(canvas)
        for y in range(COVER_H):
            t = y / max(1, COVER_H - 1)
            color = tuple(int(start[i] * (1 - t) + end[i] * t) for i in range(3))
            draw.line((0, y, COVER_W, y), fill=color)
        margin = 28
        outline = tuple(min(255, c + 48) for c in start)
        draw.rounded_rectangle((margin, margin, COVER_W - margin, COVER_H - margin), radius=20, outline=outline, width=3)
        # Simple open-book pictogram, drawn with primitives so no external asset is needed.
        top, bottom = 76, 225
        left, mid, right = 105, COVER_W // 2, COVER_W - 105
        draw.line((left, top + 18, mid, top + 35, right, top + 18), fill=(255, 248, 224), width=6, joint="curve")
        draw.line((left, top + 18, left, bottom - 10, mid, bottom - 28, mid, top + 35), fill=(255, 248, 224), width=6, joint="curve")
        draw.line((right, top + 18, right, bottom - 10, mid, bottom - 28), fill=(255, 248, 224), width=6, joint="curve")
        draw.line((mid, top + 35, mid, bottom - 28), fill=(255, 248, 224), width=4)

        extension = book.suffix.lower().lstrip(".").upper() or "BOOK"
        small_font = _cover_font(17, bold=True)
        title_font = _cover_font(30, bold=True)
        if small_font is None or title_font is None:
            return False
        label = f"KITOBHONA  ·  {extension}"
        try:
            label_width = draw.textbbox((0, 0), label, font=small_font)[2]
            draw.text(((COVER_W - label_width) / 2, 248), label, font=small_font, fill=(255, 248, 224))
        except UnicodeEncodeError:
            draw.text((COVER_W * 0.2, 248), extension, font=small_font, fill=(255, 248, 224))
        title = _cover_title(book)
        lines = _wrap_cover_title(title, title_font, draw, COVER_W - 84)
        y = 310
        for line in lines:
            try:
                box = draw.textbbox((0, 0), line, font=title_font)
                width = box[2] - box[0]
                height = box[3] - box[1]
                draw.text(((COVER_W - width) / 2, y), line, font=title_font, fill=(255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0))
                y += max(38, height + 10)
            except UnicodeEncodeError:
                safe = line.encode("ascii", "replace").decode("ascii")
                draw.text((40, y), safe, font=title_font, fill=(255, 255, 255))
                y += 42
        cover.parent.mkdir(parents=True, exist_ok=True)
        tmp = cover.with_suffix(".tmp.jpg")
        canvas.save(tmp, "JPEG", quality=COVER_QUALITY, optimize=True, progressive=True)
        if cover.exists() and file_sha1(tmp) == file_sha1(cover):
            tmp.unlink(missing_ok=True)
            return True
        tmp.replace(cover)
        print(f"🖼 fallback cover: {rel_posix(cover)}")
        return True
    except Exception as e:
        print(f"⚠ generic cover failed for {rel_posix(book)}: {e}")
        return False


def changed_book_paths_from_event() -> set[str]:
    """Find book files added/modified in the current push so legacy covers refresh once."""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return set()
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        before = str(event.get("before") or "")
        after = str(event.get("after") or "HEAD")
        changed: set[str] = set()
        for commit in event.get("commits") or []:
            if not isinstance(commit, dict):
                continue
            for field in ("added", "modified"):
                for path in commit.get(field) or []:
                    normalized = str(path).strip().replace("\\", "/")
                    if normalized.startswith("books/"):
                        changed.add(normalized)
        if changed:
            return changed
    except Exception:
        return set()
    if not before or not after or set(before) <= {"0"}:
        return set()
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false", "diff", "--name-only", "--diff-filter=ACMRT", before, after, "--", "books/"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60,
        )
        if result.returncode != 0:
            return set()
        return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip().startswith("books/")}
    except Exception:
        return set()


def build_covers(book_dirs: dict[Path, list[Path]], force_paths: set[str] | None = None) -> int:
    """Refresh changed covers and create fallbacks for every supported book format."""
    previous = read_json(COVER_SOURCE_HASHES, {})
    if not isinstance(previous, dict):
        previous = {}
    forced = set(force_paths or ())
    updated: dict[str, str] = {}
    changed = 0
    for files in book_dirs.values():
        for book in files:
            key = rel_posix(book)
            cover = cover_path_for_book(book)
            valid_cover = cover_is_usable(cover)
            force = key in forced
            try:
                source_hash = file_sha256(book)
            except Exception as e:
                print(f"⚠ could not hash {key}: {e}")
                if key in previous:
                    updated[key] = str(previous[key] or "")
                continue
            old_hash = previous.get(key)

            # On the first run, keep valid legacy covers as-is, except files in the
            # triggering push; checkout mtimes are not reliable for detecting updates.
            if valid_cover and not force and key not in previous:
                updated[key] = source_hash
                continue
            if valid_cover and not force and old_hash == source_hash:
                updated[key] = source_hash
                continue

            before_cover = file_sha1(cover) if valid_cover else None
            ext = book.suffix.lower()
            ok = False
            if ext == PDF_EXT:
                ok = generate_cover(book, cover)
            elif ext in (".epub", ".fb2"):
                ok = generate_cover_from_meta(book, cover)
                if not ok:
                    ok = generate_generic_cover(book, cover)
                elif ok:
                    print(f"🖼 cover (from file meta): {rel_posix(cover)}")
            else:
                ok = generate_generic_cover(book, cover)

            if ok and cover_is_usable(cover):
                updated[key] = source_hash
                after_cover = file_sha1(cover)
                if before_cover != after_cover:
                    changed += 1
            else:
                # Keep a mismatch marker so a transient rendering failure retries later.
                updated[key] = str(old_hash or "")

    write_json_if_changed(COVER_SOURCE_HASHES, updated)
    return changed

def main() -> int:
    os.chdir(ROOT)
    changed_books = changed_book_paths_from_event()
    overrides = read_json(DISPLAY_NAMES, {})
    if not isinstance(overrides, dict):
        print("⚠ display_names.json must be an object; ignoring")
        overrides = {}

    r = rename_books_to_titles()
    for old_path, new_path in RENAMED_BOOK_PATHS.items():
        if old_path in changed_books:
            changed_books.add(new_path)
    if r:
        print(f"✏️ Renamed {r} books to their real titles")

    d = convert_docs()
    if d:
        print(f"📄 Created {d} viewable copies of .doc books")

    book_dirs = collect_pdf_dirs()
    book_count = sum(len(v) for v in book_dirs.values())
    print(f"🔎 Found {book_count} supported books in {len(book_dirs)} folders")

    if not book_dirs:
        print("⚠ No supported books found. Nothing to build.")
        return 0

    m = build_manifests(book_dirs)
    b = build_books_json(book_dirs, overrides)
    c = build_covers(book_dirs, changed_books)

    print(f"✅ Done: manifests changed={m}, books.json changed={int(b)}, covers changed={c}, cover source hashes updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
