#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Китобхона — auto builder for sharipovip/books

What it does:
1) Scans books/** for PDF files.
2) Writes manifest.json into every folder that contains PDFs.
3) Writes root books.json from the real folder structure.
4) Generates covers/<same folder>/<pdf name>.jpg from first PDF page.

Idempotent: repeated runs do not duplicate anything and commit only real changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except Exception:
    Image = None

ROOT = Path(__file__).resolve().parent
BOOKS_DIR = ROOT / "books"
COVERS_DIR = ROOT / "covers"
BOOKS_JSON = ROOT / "books.json"
DISPLAY_NAMES = ROOT / "display_names.json"
REPO = os.environ.get("KITOB_REPO", "sharipovip/books")
BRANCH = os.environ.get("KITOB_BRANCH", "main")
TODAY = date.today().isoformat()

PDF_EXT = ".pdf"
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
    for pdf in BOOKS_DIR.rglob("*.pdf"):
        if pdf.is_file():
            result.setdefault(pdf.parent, []).append(pdf)
    for k in result:
        result[k].sort(key=lambda p: p.name.casefold())
    return dict(sorted(result.items(), key=lambda kv: kv[0].as_posix().casefold()))


def pdf_info(pdf: Path) -> dict[str, Any]:
    st = pdf.stat()
    return {
        "name": pdf.stem,
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
            print(f"📝 manifest: {rel_posix(folder)}/manifest.json ({len(pdfs)} PDF)")
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


def cover_path_for_pdf(pdf: Path) -> Path:
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


def cover_is_fresh(pdf: Path, cover: Path) -> bool:
    if not cover.exists() or cover.stat().st_size < 500:
        return False
    # mtime check is enough for GitHub Action after checkout.
    return cover.stat().st_mtime >= pdf.stat().st_mtime


def generate_cover(pdf: Path, cover: Path) -> bool:
    if cover_is_fresh(pdf, cover):
        return False
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
                return False
            tmp.replace(cover)
            print(f"🖼 cover: {rel_posix(cover)}")
            return True
        except Exception as e:
            print(f"⚠ cover save failed for {rel_posix(pdf)}: {e}")
            return False


def build_covers(pdf_dirs: dict[Path, list[Path]]) -> int:
    changed = 0
    for pdfs in pdf_dirs.values():
        for pdf in pdfs:
            if generate_cover(pdf, cover_path_for_pdf(pdf)):
                changed += 1
    return changed


def main() -> int:
    os.chdir(ROOT)
    overrides = read_json(DISPLAY_NAMES, {})
    if not isinstance(overrides, dict):
        print("⚠ display_names.json must be an object; ignoring")
        overrides = {}

    pdf_dirs = collect_pdf_dirs()
    pdf_count = sum(len(v) for v in pdf_dirs.values())
    print(f"🔎 Found {pdf_count} PDF in {len(pdf_dirs)} folders")

    if not pdf_dirs:
        print("⚠ No PDFs found. Nothing to build.")
        return 0

    m = build_manifests(pdf_dirs)
    b = build_books_json(pdf_dirs, overrides)
    c = build_covers(pdf_dirs)

    print(f"✅ Done: manifests changed={m}, books.json changed={int(b)}, covers changed={c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
