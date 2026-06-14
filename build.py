#!/usr/bin/env python3
"""
build.py — авто-сборка manifest.json, books.json и обложек.

v3:
- Учитывает display_names.json (имена для отображения, GitHub-имя остаётся как есть)
- Идемпотентный
- Генерит обложки через pdftoppm + PIL (WebP если доступен)
- Папки начинающиеся на '_' или '.' пропускаются
- Файлы названия которых начинаются с '_' или '.' пропускаются
"""
import os
import re
import json
import sys
import subprocess
import shutil
from pathlib import Path
from datetime import date

ROOT = Path(__file__).parent.resolve()
BOOKS_DIR = ROOT / 'books'
COVERS_DIR = ROOT / 'covers'
BOOKS_JSON = ROOT / 'books.json'
DISPLAY_NAMES_FILE = ROOT / 'display_names.json'

# ── DEFAULT display_names (если нет файла display_names.json) ─
DEFAULT_DISPLAY = {
    'Пешвои миллат':        {'name': 'Китобҳои Асосгузори сулҳу ваҳдати миллӣ – Пешвои миллат',
                              'emoji': '👑', 'c1': '#b45309', 'c2': '#f59e0b', 'priority': True, 'sort_order': 1},

    'Kitobhoi_darsi':       {'name': 'Китобҳои дарсӣ', 'emoji': '🎓', 'c1': '#2563eb', 'c2': '#3b82f6', 'sort_order': 10},

    'Sinfi_1':  {'name': 'Синфи 1',  'emoji': '1️⃣', 'sort_order': 10},
    'Sinfi_2':  {'name': 'Синфи 2',  'emoji': '2️⃣', 'sort_order': 20},
    'Sinfi_3':  {'name': 'Синфи 3',  'emoji': '3️⃣', 'sort_order': 30},
    'Sinfi_4':  {'name': 'Синфи 4',  'emoji': '4️⃣', 'sort_order': 40},
    'Sinfi_5':  {'name': 'Синфи 5',  'emoji': '5️⃣', 'sort_order': 50},
    'Sinfi_6':  {'name': 'Синфи 6',  'emoji': '6️⃣', 'sort_order': 60},
    'Sinfi_7':  {'name': 'Синфи 7',  'emoji': '7️⃣', 'sort_order': 70},
    'Sinfi_8':  {'name': 'Синфи 8',  'emoji': '8️⃣', 'sort_order': 80},
    'Sinfi_9':  {'name': 'Синфи 9',  'emoji': '9️⃣', 'sort_order': 90},
    'Sinfi_10': {'name': 'Синфи 10', 'emoji': '🔟', 'sort_order': 100},
    'Sinfi_11': {'name': 'Синфи 11', 'emoji': '🎓', 'sort_order': 110},

    'Адабиёти муосир':      {'emoji': '✍️', 'c1': '#7c3aed', 'c2': '#a78bfa', 'sort_order': 30},
    'Адабиёти классикӣ':    {'emoji': '📜', 'c1': '#9333ea', 'c2': '#c084fc', 'sort_order': 31},
    'Адабиёти ҷаҳон':       {'emoji': '🌍', 'c1': '#0891b2', 'c2': '#22d3ee', 'sort_order': 32},
    'Адабиёти бачагона':    {'emoji': '🎈', 'c1': '#f59e0b', 'c2': '#fbbf24', 'sort_order': 33},
    'Шеър':                 {'emoji': '🌹', 'c1': '#db2777', 'c2': '#f472b6', 'sort_order': 34},
    'Назм':                 {'emoji': '📝', 'c1': '#c026d3', 'c2': '#e879f9', 'sort_order': 35},
    'Роман':                {'emoji': '📕', 'c1': '#dc2626', 'c2': '#ef4444', 'sort_order': 36},
    'Қисса':                {'emoji': '📖', 'c1': '#ea580c', 'c2': '#fb923c', 'sort_order': 37},
    'Повест':               {'emoji': '📗', 'c1': '#16a34a', 'c2': '#4ade80', 'sort_order': 38},
    'Достон':               {'emoji': '⚔️', 'c1': '#7c2d12', 'c2': '#c2410c', 'sort_order': 39},
    'Чистон':               {'emoji': '🧩', 'c1': '#0d9488', 'c2': '#5eead4', 'sort_order': 40},
    'Драма':                {'emoji': '🎭', 'c1': '#9f1239', 'c2': '#e11d48', 'sort_order': 41},

    'Таърих':               {'emoji': '🏛', 'c1': '#a16207', 'c2': '#eab308', 'sort_order': 50},
    'Фарҳанг':              {'emoji': '🎨', 'c1': '#d97706', 'c2': '#fbbf24', 'sort_order': 51},
    'Зиндагинома':          {'emoji': '👤', 'c1': '#854d0e', 'c2': '#facc15', 'sort_order': 52},
    'Журналистика':         {'emoji': '📰', 'c1': '#525252', 'c2': '#a3a3a3', 'sort_order': 53},
    'Ёддошт':               {'emoji': '📔', 'c1': '#a16207', 'c2': '#ca8a04', 'sort_order': 54},

    'Илмӣ':                 {'emoji': '🔬', 'c1': '#06b6d4', 'c2': '#22d3ee', 'sort_order': 60},
    'Исломӣ':               {'emoji': '🕌', 'c1': '#15803d', 'c2': '#22c55e', 'sort_order': 61},
    'Тиб':                  {'emoji': '⚕️', 'c1': '#dc2626', 'c2': '#f87171', 'sort_order': 62},
    'Иқтисод':              {'emoji': '💼', 'c1': '#0e7490', 'c2': '#06b6d4', 'sort_order': 63},
    'Фанноварии иттилоотӣ': {'emoji': '💻', 'c1': '#1e40af', 'c2': '#3b82f6', 'sort_order': 64},

    'Дигар':                {'emoji': '📂', 'c1': '#64748b', 'c2': '#94a3b8', 'sort_order': 999},
    'Гуногун':              {'emoji': '📦', 'c1': '#64748b', 'c2': '#94a3b8', 'sort_order': 999},
}

AUTO_PALETTE = [
    ('#3b82f6', '#60a5fa'), ('#8b5cf6', '#a78bfa'), ('#ec4899', '#f472b6'),
    ('#10b981', '#34d399'), ('#f59e0b', '#fbbf24'), ('#ef4444', '#f87171'),
    ('#06b6d4', '#22d3ee'), ('#84cc16', '#a3e635'), ('#f97316', '#fb923c'),
    ('#6366f1', '#818cf8'),
]
AUTO_EMOJIS = ['📚', '📖', '📕', '📗', '📘', '📙', '📔', '📒', '📓', '🗂']


def load_display_names():
    """Загружает display_names из файла, мерджит с DEFAULT."""
    merged = dict(DEFAULT_DISPLAY)
    if DISPLAY_NAMES_FILE.exists():
        try:
            with open(DISPLAY_NAMES_FILE, 'r', encoding='utf-8') as f:
                external = json.load(f)
                for folder, meta in external.items():
                    if folder in merged:
                        merged[folder].update(meta)
                    else:
                        merged[folder] = meta
            print(f"  📝 Loaded {len(external)} display_names overrides")
        except Exception as e:
            print(f"  ⚠ display_names.json load error: {e}")
    return merged


def slugify(text):
    text = text.strip().lower()
    repl = {
        'ӣ':'i','ӯ':'u','ҳ':'h','ҷ':'j','ғ':'gh','қ':'q',
        'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo',
        'ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m',
        'н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u',
        'ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sh','ы':'y',
        'э':'e','ю':'yu','я':'ya','ъ':'','ь':'',
    }
    out = ''
    for ch in text:
        if ch in repl: out += repl[ch]
        elif ch.isalnum(): out += ch
        else: out += '_'
    out = re.sub(r'_+', '_', out).strip('_')
    return out or 'cat'


def get_meta(folder_name, display_map, used_palette_idx=0):
    """Метаданные для папки: name (отображаемое), emoji, c1, c2, priority, sort."""
    if folder_name in display_map:
        m = display_map[folder_name]
        return {
            'folder': folder_name,
            'name': m.get('name', folder_name),
            'emoji': m.get('emoji', '📚'),
            'c1': m.get('c1', '#3b82f6'),
            'c2': m.get('c2', '#60a5fa'),
            'priority': m.get('priority', False),
            'sort_order': m.get('sort_order', 100),
        }
    c1, c2 = AUTO_PALETTE[used_palette_idx % len(AUTO_PALETTE)]
    em = AUTO_EMOJIS[used_palette_idx % len(AUTO_EMOJIS)]
    return {
        'folder': folder_name,
        'name': folder_name,  # raw name as fallback
        'emoji': em,
        'c1': c1,
        'c2': c2,
        'priority': False,
        'sort_order': 500,
    }


def list_pdfs(folder):
    if not folder.exists() or not folder.is_dir(): return []
    return sorted([p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() == '.pdf' and not p.name.startswith('_')])


def list_subfolders(folder):
    if not folder.exists() or not folder.is_dir(): return []
    return sorted([p for p in folder.iterdir()
                   if p.is_dir() and not p.name.startswith('.') and not p.name.startswith('_')])


def make_manifest(folder):
    """Создаёт manifest.json в папке. Возвращает True если файл изменён."""
    pdfs = list_pdfs(folder)
    if not pdfs: return False
    rel_folder = folder.relative_to(ROOT).as_posix()
    books = []
    for pdf in pdfs:
        try: size = pdf.stat().st_size
        except OSError: size = 0
        books.append({'name': pdf.stem, 'file': pdf.name, 'size': size})
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
            old_check = {k: v for k, v in old.items() if k != 'updatedAt'}
            new_check = {k: v for k, v in new_data.items() if k != 'updatedAt'}
            if old_check == new_check: return False
        except: pass
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)
    return True


def make_cover(pdf, cover_path):
    """Создаёт обложку из 1-й страницы PDF."""
    if cover_path.exists() and cover_path.stat().st_mtime >= pdf.stat().st_mtime:
        return False
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp_prefix = cover_path.parent / ('_tmp_' + cover_path.stem)
        subprocess.run([
            'pdftoppm', '-jpeg', '-jpegopt', 'quality=72',
            '-r', '70',
            '-f', '1', '-l', '1',
            '-singlefile',
            str(pdf), str(tmp_prefix)
        ], check=True, capture_output=True, timeout=30)
        tmp_jpg = tmp_prefix.parent / (tmp_prefix.name + '.jpg')
        if tmp_jpg.exists():
            try:
                from PIL import Image
                img = Image.open(tmp_jpg).convert('RGB')
                if img.width > 400:
                    h = int(img.height * (400 / img.width))
                    img = img.resize((400, h), Image.LANCZOS)
                img.save(cover_path, 'JPEG', quality=75, optimize=True, progressive=True)
                tmp_jpg.unlink()
            except ImportError:
                shutil.move(str(tmp_jpg), str(cover_path))
            return True
    except Exception as e:
        print(f"  ⚠ Cover failed for {pdf.name}: {e}")
        return False
    return False


def main():
    if not BOOKS_DIR.exists():
        print(f"❌ {BOOKS_DIR} not found")
        sys.exit(1)

    print(f"📂 Scanning {BOOKS_DIR}\n")

    print("📋 Loading display_names...")
    DISPLAY_MAP = load_display_names()
    print()

    cat_folders = list_subfolders(BOOKS_DIR)
    if not cat_folders:
        print("⚠ No categories found")
        return

    # ── Шаг 1: manifests
    print("📋 STEP 1 — manifests")
    manifest_changes = 0
    folders_to_scan = []
    for cat in cat_folders:
        if list_pdfs(cat): folders_to_scan.append(cat)
        for sub in list_subfolders(cat):
            if list_pdfs(sub): folders_to_scan.append(sub)
    for folder in folders_to_scan:
        if make_manifest(folder):
            manifest_changes += 1
            print(f"  ✅ {folder.relative_to(ROOT)}/manifest.json")
    if manifest_changes == 0:
        print("  ✓ All manifests up-to-date")
    print()

    # ── Шаг 2: covers
    print("🖼  STEP 2 — covers")
    pdftoppm_ok = shutil.which('pdftoppm') is not None
    cover_changes = 0
    if not pdftoppm_ok:
        print("  ⚠ pdftoppm not installed — skipping covers")
    else:
        for folder in folders_to_scan:
            rel_folder = folder.relative_to(BOOKS_DIR)
            covers_target = COVERS_DIR / rel_folder
            for pdf in list_pdfs(folder):
                cover_file = covers_target / (pdf.stem + '.jpg')
                if make_cover(pdf, cover_file):
                    cover_changes += 1
                    print(f"  ✅ {cover_file.relative_to(ROOT)}")
        if cover_changes == 0:
            print("  ✓ All covers up-to-date")
    print()

    # ── Шаг 3: books.json
    print("📁 STEP 3 — books.json")
    repo_name = os.environ.get('GITHUB_REPOSITORY', 'sharipovip/books')
    branch = os.environ.get('GITHUB_REF_NAME', 'main')

    used_palette_idx = 0
    categories = []
    for cat_folder in cat_folders:
        cat_name_raw = cat_folder.name  # raw имя в GitHub
        meta = get_meta(cat_name_raw, DISPLAY_MAP, used_palette_idx)
        if cat_name_raw not in DISPLAY_MAP:
            used_palette_idx += 1

        subs = []
        subfolders = list_subfolders(cat_folder)
        if subfolders:
            for sub in subfolders:
                if not list_pdfs(sub): continue
                sub_meta = get_meta(sub.name, DISPLAY_MAP, 0)
                subs.append({
                    'id': slugify(sub.name)[:30],
                    'name': sub_meta['name'],
                    'folder_raw': sub.name,
                    'folder': f"books/{cat_folder.name}/{sub.name}",
                    'emoji': sub_meta['emoji'],
                })
        if list_pdfs(cat_folder):
            subs.insert(0, {
                'id': slugify(cat_name_raw)[:30],
                'name': meta['name'],
                'folder_raw': cat_folder.name,
                'folder': f"books/{cat_folder.name}",
                'emoji': meta['emoji'],
            })
        if not subs: continue

        cat_obj = {
            'id': slugify(cat_name_raw)[:30],
            'name': meta['name'],
            'folder_raw': cat_folder.name,  # для админки
            'emoji': meta['emoji'],
            'color1': meta['c1'],
            'color2': meta['c2'],
            'sort_order': meta['sort_order'],
            'subs': subs,
        }
        if meta.get('priority'):
            cat_obj['priority'] = True
        categories.append(cat_obj)

    # Сортировка: priority=true сначала, потом по sort_order, потом по имени
    categories.sort(key=lambda c: (not c.get('priority', False), c.get('sort_order', 500), c['name']))

    new_books_json = {
        'version': 3,
        'updatedAt': str(date.today()),
        'repo': repo_name,
        'branch': branch,
        'categories': categories,
    }

    changed = True
    if BOOKS_JSON.exists():
        try:
            with open(BOOKS_JSON, 'r', encoding='utf-8') as f:
                old = json.load(f)
            old_check = {k: v for k, v in old.items() if k != 'updatedAt'}
            new_check = {k: v for k, v in new_books_json.items() if k != 'updatedAt'}
            if old_check == new_check: changed = False
        except: pass

    if changed:
        with open(BOOKS_JSON, 'w', encoding='utf-8') as f:
            json.dump(new_books_json, f, ensure_ascii=False, indent=2)
        print(f"  ✅ books.json updated ({len(categories)} categories)")
    else:
        print("  ✓ books.json up-to-date")

    print(f"\n{'━'*50}")
    print("📊 SUMMARY")
    print(f"  Categories: {len(categories)}")
    print(f"  Subs:       {sum(len(c['subs']) for c in categories)}")
    print(f"  Manifests:  {manifest_changes} changed")
    if pdftoppm_ok: print(f"  Covers:     {cover_changes} changed")
    print('━'*50, "\n✅ DONE")


if __name__ == '__main__':
    main()
