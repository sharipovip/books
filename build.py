#!/usr/bin/env python3
"""
build.py — авто-сборка manifest.json, books.json и обложек для репо книг.

Запускается GitHub Actions при каждом push изменений в books/.
Идемпотентный: повторный запуск не дублирует, обновляет только то что изменилось.

Что делает:
1. Сканит books/**/ рекурсивно
2. В каждой папке с PDF — создаёт/обновляет manifest.json
3. В корне репо — создаёт/обновляет books.json (категории + подкатегории)
4. В covers/ — генерирует JPG обложки (1-я страница PDF) если pdftoppm доступен
5. Папка `books/Пешвои миллат` автоматически становится первой категорией с priority=true
"""
import os
import re
import json
import sys
import subprocess
import shutil
import hashlib
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
BOOKS_DIR = ROOT / 'books'
COVERS_DIR = ROOT / 'covers'
BOOKS_JSON = ROOT / 'books.json'

# ── СЛОВАРЬ ИЗВЕСТНЫХ КАТЕГОРИЙ (эмодзи + цвета) ─────────────
CATEGORY_META = {
    # Особая категория Пешвои миллат — будет первой
    'Пешвои миллат':        {'emoji': '👑', 'c1': '#b45309', 'c2': '#f59e0b', 'priority': True},

    # Учебники
    'Kitobhoi_darsi':       {'emoji': '🎓', 'c1': '#2563eb', 'c2': '#3b82f6'},

    # Художественная литература
    'Адабиёти муосир':      {'emoji': '✍️', 'c1': '#7c3aed', 'c2': '#a78bfa'},
    'Адабиёти классикӣ':    {'emoji': '📜', 'c1': '#9333ea', 'c2': '#c084fc'},
    'Адабиёти ҷаҳон':       {'emoji': '🌍', 'c1': '#0891b2', 'c2': '#22d3ee'},
    'Адабиёти бачагона':    {'emoji': '🎈', 'c1': '#f59e0b', 'c2': '#fbbf24'},
    'Шеър':                 {'emoji': '🌹', 'c1': '#db2777', 'c2': '#f472b6'},
    'Назм':                 {'emoji': '📝', 'c1': '#c026d3', 'c2': '#e879f9'},
    'Роман':                {'emoji': '📕', 'c1': '#dc2626', 'c2': '#ef4444'},
    'Қисса':                {'emoji': '📖', 'c1': '#ea580c', 'c2': '#fb923c'},
    'Повест':               {'emoji': '📗', 'c1': '#16a34a', 'c2': '#4ade80'},
    'Достон':               {'emoji': '⚔️', 'c1': '#7c2d12', 'c2': '#c2410c'},
    'Чистон':               {'emoji': '🧩', 'c1': '#0d9488', 'c2': '#5eead4'},
    'Драма':                {'emoji': '🎭', 'c1': '#9f1239', 'c2': '#e11d48'},

    # Таърих ва Фарҳанг
    'Таърих':               {'emoji': '🏛', 'c1': '#a16207', 'c2': '#eab308'},
    'Фарҳанг':              {'emoji': '🎨', 'c1': '#d97706', 'c2': '#fbbf24'},
    'Зиндагинома':          {'emoji': '👤', 'c1': '#854d0e', 'c2': '#facc15'},
    'Журналистика':         {'emoji': '📰', 'c1': '#525252', 'c2': '#a3a3a3'},
    'Ёддошт':               {'emoji': '📔', 'c1': '#a16207', 'c2': '#ca8a04'},

    # Илм ва Дин
    'Илмӣ':                 {'emoji': '🔬', 'c1': '#06b6d4', 'c2': '#22d3ee'},
    'Исломӣ':               {'emoji': '🕌', 'c1': '#15803d', 'c2': '#22c55e'},
    'Тиб':                  {'emoji': '⚕️', 'c1': '#dc2626', 'c2': '#f87171'},
    'Иқтисод':              {'emoji': '💼', 'c1': '#0e7490', 'c2': '#06b6d4'},
    'Фанноварии иттилоотӣ': {'emoji': '💻', 'c1': '#1e40af', 'c2': '#3b82f6'},

    # Дигар
    'Дигар':                {'emoji': '📂', 'c1': '#64748b', 'c2': '#94a3b8'},
    'Гуногун':              {'emoji': '📦', 'c1': '#64748b', 'c2': '#94a3b8'},
}

# Палитра для авто-цветов незнакомых категорий
AUTO_PALETTE = [
    ('#3b82f6', '#60a5fa'), ('#8b5cf6', '#a78bfa'), ('#ec4899', '#f472b6'),
    ('#10b981', '#34d399'), ('#f59e0b', '#fbbf24'), ('#ef4444', '#f87171'),
    ('#06b6d4', '#22d3ee'), ('#84cc16', '#a3e635'), ('#f97316', '#fb923c'),
    ('#6366f1', '#818cf8'),
]
AUTO_EMOJIS = ['📚', '📖', '📕', '📗', '📘', '📙', '📔', '📒', '📓', '🗂']


def slugify(text: str) -> str:
    """Создаёт безопасный ID из таджикского текста."""
    text = text.strip().lower()
    # Транслитерация основных букв
    repl = {
        'ӣ':'i','ӯ':'u','ҳ':'h','ҷ':'j','ғ':'gh','қ':'q',
        'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo',
        'ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m',
        'н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u',
        'ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sh','ы':'y',
        'э':'e','ю':'yu','я':'ya','ъ':'','ь':'','ё':'yo',
    }
    out = ''
    for ch in text:
        if ch in repl:
            out += repl[ch]
        elif ch.isalnum():
            out += ch
        else:
            out += '_'
    out = re.sub(r'_+', '_', out).strip('_')
    return out or 'cat'


def get_meta(folder_name: str, used_palette_idx: int = 0):
    """Возвращает emoji, c1, c2, priority для категории."""
    if folder_name in CATEGORY_META:
        m = CATEGORY_META[folder_name]
        return {
            'emoji': m['emoji'],
            'c1': m['c1'],
            'c2': m['c2'],
            'priority': m.get('priority', False),
        }
    # Авто
    c1, c2 = AUTO_PALETTE[used_palette_idx % len(AUTO_PALETTE)]
    em = AUTO_EMOJIS[used_palette_idx % len(AUTO_EMOJIS)]
    return {'emoji': em, 'c1': c1, 'c2': c2, 'priority': False}


def list_pdfs(folder: Path):
    """Возвращает отсортированный список PDF-файлов в папке (не рекурсивно)."""
    if not folder.exists() or not folder.is_dir():
        return []
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == '.pdf'])


def list_subfolders(folder: Path):
    """Возвращает отсортированный список подпапок."""
    if not folder.exists() or not folder.is_dir():
        return []
    return sorted([p for p in folder.iterdir() if p.is_dir() and not p.name.startswith('.')])


def make_manifest(folder: Path) -> bool:
    """
    Создаёт/обновляет manifest.json в папке.
    Возвращает True если файл был изменён.
    """
    pdfs = list_pdfs(folder)
    if not pdfs:
        return False

    rel_folder = folder.relative_to(ROOT).as_posix()
    books = []
    for pdf in pdfs:
        try:
            size = pdf.stat().st_size
        except OSError:
            size = 0
        books.append({
            'name': pdf.stem,
            'file': pdf.name,
            'size': size,
        })

    from datetime import date
    new_data = {
        'version': 1,
        'updatedAt': str(date.today()),
        'folder': rel_folder,
        'books': books,
    }

    manifest_path = folder / 'manifest.json'
    if manifest_path.exists():
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                old = json.load(f)
            # Сравниваем без updatedAt
            old_check = {k: v for k, v in old.items() if k != 'updatedAt'}
            new_check = {k: v for k, v in new_data.items() if k != 'updatedAt'}
            if old_check == new_check:
                return False
        except (json.JSONDecodeError, OSError):
            pass

    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)
    return True


def make_cover(pdf: Path, cover_path: Path) -> bool:
    """
    Создаёт обложку из 1-й страницы PDF.
    Возвращает True если файл был создан/обновлён.
    """
    # Пропускаем если обложка существует и свежее PDF
    if cover_path.exists():
        if cover_path.stat().st_mtime >= pdf.stat().st_mtime:
            return False

    cover_path.parent.mkdir(parents=True, exist_ok=True)

    # pdftoppm: вытащить 1-ю страницу в JPEG ~400×600
    try:
        # Через временный файл
        tmp_prefix = cover_path.parent / ('_tmp_' + cover_path.stem)
        subprocess.run([
            'pdftoppm', '-jpeg', '-jpegopt', 'quality=70',
            '-r', '60',  # ~600px высоты
            '-f', '1', '-l', '1',
            '-singlefile',
            str(pdf), str(tmp_prefix)
        ], check=True, capture_output=True, timeout=30)

        tmp_jpg = tmp_prefix.parent / (tmp_prefix.name + '.jpg')
        if tmp_jpg.exists():
            # Уменьшаем через Pillow если есть
            try:
                from PIL import Image
                img = Image.open(tmp_jpg).convert('RGB')
                # Ширина не больше 400
                if img.width > 400:
                    h = int(img.height * (400 / img.width))
                    img = img.resize((400, h), Image.LANCZOS)
                img.save(cover_path, 'JPEG', quality=72, optimize=True, progressive=True)
                tmp_jpg.unlink()
            except ImportError:
                shutil.move(str(tmp_jpg), str(cover_path))
            return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  ⚠ Cover failed for {pdf.name}: {e}")
        return False

    return False


def main():
    if not BOOKS_DIR.exists():
        print(f"❌ {BOOKS_DIR} not found")
        sys.exit(1)

    print(f"📂 Scanning {BOOKS_DIR}")
    print()

    # Список категорий (папки 1-го уровня в books/)
    cat_folders = list_subfolders(BOOKS_DIR)
    if not cat_folders:
        print("⚠ No categories found")
        return

    # ── Шаг 1: обходим все папки рекурсивно, создаём manifest.json
    print("📋 STEP 1 — manifests")
    manifest_changes = 0
    folders_to_scan = []  # все папки которые содержат PDF
    for cat in cat_folders:
        # Сама категория
        if list_pdfs(cat):
            folders_to_scan.append(cat)
        # Подкатегории (один уровень глубже)
        for sub in list_subfolders(cat):
            if list_pdfs(sub):
                folders_to_scan.append(sub)
            # Глубже не идём (структура: books/Категория/Подкатегория/файлы.pdf)

    for folder in folders_to_scan:
        if make_manifest(folder):
            manifest_changes += 1
            rel = folder.relative_to(ROOT)
            print(f"  ✅ {rel}/manifest.json")

    if manifest_changes == 0:
        print("  ✓ All manifests up-to-date")
    print()

    # ── Шаг 2: обложки
    print("🖼  STEP 2 — covers")
    pdftoppm_ok = shutil.which('pdftoppm') is not None
    if not pdftoppm_ok:
        print("  ⚠ pdftoppm not installed — skipping covers")
    else:
        cover_changes = 0
        for folder in folders_to_scan:
            rel_folder = folder.relative_to(BOOKS_DIR)  # относительно books/
            covers_target = COVERS_DIR / rel_folder
            for pdf in list_pdfs(folder):
                cover_file = covers_target / (pdf.stem + '.jpg')
                if make_cover(pdf, cover_file):
                    cover_changes += 1
                    rel = cover_file.relative_to(ROOT)
                    print(f"  ✅ {rel}")
        if cover_changes == 0:
            print("  ✓ All covers up-to-date")
    print()

    # ── Шаг 3: books.json
    print("📁 STEP 3 — books.json")
    from datetime import date
    repo_name = os.environ.get('GITHUB_REPOSITORY', 'sharipovip/books')
    branch = os.environ.get('GITHUB_REF_NAME', 'main')

    used_palette_idx = 0
    categories = []
    for cat_folder in cat_folders:
        cat_name = cat_folder.name
        meta = get_meta(cat_name, used_palette_idx)
        if cat_name not in CATEGORY_META:
            used_palette_idx += 1

        # Подкатегории
        subs = []
        subfolders = list_subfolders(cat_folder)
        if subfolders:
            for sub in subfolders:
                if not list_pdfs(sub):
                    continue
                sub_meta = get_meta(sub.name, 0)
                subs.append({
                    'id': slugify(sub.name)[:30],
                    'name': sub.name,
                    'folder': f"books/{cat_folder.name}/{sub.name}",
                    'emoji': sub_meta['emoji'],
                })

        # Если в самой папке категории есть PDF (без подкатегорий) — она сама подкатегория
        if list_pdfs(cat_folder):
            subs.insert(0, {
                'id': slugify(cat_name)[:30],
                'name': cat_name,
                'folder': f"books/{cat_folder.name}",
                'emoji': meta['emoji'],
            })

        if not subs:
            continue  # пропускаем пустые категории

        cat_obj = {
            'id': slugify(cat_name)[:30],
            'name': cat_name,
            'emoji': meta['emoji'],
            'color1': meta['c1'],
            'color2': meta['c2'],
            'subs': subs,
        }
        if meta.get('priority'):
            cat_obj['priority'] = True

        categories.append(cat_obj)

    # Сортируем: priority=true сверху
    categories.sort(key=lambda c: (not c.get('priority', False), c['name']))

    new_books_json = {
        'version': 3,
        'updatedAt': str(date.today()),
        'repo': repo_name,
        'branch': branch,
        'categories': categories,
    }

    # Сравниваем со старым
    changed = True
    if BOOKS_JSON.exists():
        try:
            with open(BOOKS_JSON, 'r', encoding='utf-8') as f:
                old = json.load(f)
            old_check = {k: v for k, v in old.items() if k != 'updatedAt'}
            new_check = {k: v for k, v in new_books_json.items() if k != 'updatedAt'}
            if old_check == new_check:
                changed = False
        except (json.JSONDecodeError, OSError):
            pass

    if changed:
        with open(BOOKS_JSON, 'w', encoding='utf-8') as f:
            json.dump(new_books_json, f, ensure_ascii=False, indent=2)
        print(f"  ✅ books.json updated ({len(categories)} categories)")
    else:
        print("  ✓ books.json up-to-date")

    print()
    print("━" * 50)
    print("📊 SUMMARY")
    print(f"  Categories:    {len(categories)}")
    print(f"  Total subs:    {sum(len(c['subs']) for c in categories)}")
    print(f"  Manifests changed: {manifest_changes}")
    if pdftoppm_ok:
        print(f"  Covers changed:    {cover_changes}")
    print("━" * 50)
    print("✅ DONE")


if __name__ == '__main__':
    main()
