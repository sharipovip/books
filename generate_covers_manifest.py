#!/usr/bin/env python3
"""
generate_covers_manifest.py
───────────────────────────
Обходит папку covers/ и создаёт covers_manifest.json с МНОЖЕСТВОМ
ключей для каждого файла, чтобы приложение могло найти обложку
независимо от формата book_id (с путём, без пути, на кириллице/латинице).

Ключи для covers/a/b/c.jpg:
  - "a/b/c"             (основной: относительный путь от covers/)
  - "b/c"               (без корневой папки)
  - "c"                 (только имя файла, крайний fallback)
  - "books/a/b/c"       (с префиксом books/)
  - "books/b/c"
  - "books/c"
  - "книги/a/b/c"       (кириллический префикс для совместимости)

Запуск:
  python3 generate_covers_manifest.py          # только генерирует файл
  python3 generate_covers_manifest.py --push   # + коммит + пуш
"""

import os
import sys
import json
import urllib.parse
import subprocess
from pathlib import Path

REPO   = "sharipovip/books"
BRANCH = "main"
COVERS_DIR = Path("covers")
OUTPUT     = Path("covers_manifest.json")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def build_manifest() -> dict:
    """Обходит covers/ и возвращает {key: url, ...} с множеством ключей."""
    manifest: dict[str, str] = {}

    if not COVERS_DIR.is_dir():
        print(f"⚠ Папка {COVERS_DIR} не найдена.")
        return manifest

    count_files = 0

    for img_path in sorted(COVERS_DIR.rglob("*")):
        if not img_path.is_file():
            continue
        if img_path.suffix.lower() not in IMAGE_EXTS:
            continue

        # Путь от covers/ без расширения: "Kitobhoi darsi/sinfi_1/Алифбо 1"
        rel = img_path.relative_to(COVERS_DIR)
        base_key = str(rel.with_suffix(""))
        encoded_base = urllib.parse.quote(base_key, safe="")
        encoded_file = urllib.parse.quote(img_path.name)
        url = (
            f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
            f"/covers/{encoded_base}/{encoded_file}"
        )

        # Разбираем путь на части
        parts = base_key.split("/")
        file_only = parts[-1]                        # "Алифбо 1"
        subpath   = "/".join(parts[1:]) if len(parts) > 1 else ""   # "sinfi_1/Алифбо 1"
        root      = parts[0] if parts else ""         # "Kitobhoi darsi"

        # Формируем все возможные ключи (от более конкретных к общим)
        keys: list[str] = []

        # Основной вариант: полный путь от covers/
        keys.append(base_key)

        # Без корневой папки: "sinfi_1/Алифбо 1"
        if subpath:
            keys.append(subpath)

        # Только имя файла: "Алифбо 1" (для случая когда book_id = bare filename)
        keys.append(file_only)

        # С префиксом books/ (если приложение добавляет его)
        keys.append("books/" + base_key)
        if subpath:
            keys.append("books/" + subpath)
        keys.append("books/" + file_only)

        # Записываем ВСЕ ключи → один и тот же URL
        for k in keys:
            if k and k not in manifest:
                manifest[k] = url

        count_files += 1

    print(f"📦 Найдено обложек: {count_files}, записей в manifest: {len(manifest)}")
    return manifest


def write_manifest(manifest: dict) -> bool:
    """Записывает covers_manifest.json, возвращает True если изменился."""
    new_content = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    old_content = None
    if OUTPUT.exists():
        old_content = OUTPUT.read_text(encoding="utf-8")
    if old_content == new_content:
        print("✓ covers_manifest.json не изменился.")
        return False
    OUTPUT.write_text(new_content, encoding="utf-8")
    print(f"✅ covers_manifest.json записан ({len(manifest)} записей).")
    return True


def git_commit_and_push(manifest: dict) -> bool:
    """Коммит и пуш covers_manifest.json."""
    try:
        subprocess.run(["git", "rev-parse", "--git-dir"], check=True, capture_output=True)
        subprocess.run(["git", "add", str(OUTPUT)], capture_output=True, text=True)
        r = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
        if r.returncode == 0:
            print("✓ Нет изменений для коммита.")
            return False
        subprocess.run(["git", "config", "user.name",  "github-actions[bot]"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True, capture_output=True)
        msg = f"🤖 auto: update covers_manifest.json ({len(manifest)} entries)"
        r = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"⚠ git commit ошибка: {r.stderr}")
            return False
        print(f"✅ Коммит: {msg}")
        r = subprocess.run(["git", "push"], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"⚠ git push ошибка: {r.stderr}")
            return False
        print("✅ Push выполнен.")
        return True
    except FileNotFoundError:
        print("⚠ git не найден.")
        return False
    except subprocess.CalledProcessError as e:
        print(f"⚠ Git error: {e}")
        return False


def main() -> None:
    do_push = "--push" in sys.argv
    manifest = build_manifest()
    changed = write_manifest(manifest)
    if changed and do_push:
        git_commit_and_push(manifest)
    if changed:
        print(f"\n📄 covers_manifest.json готов ({len(manifest)} записей).")
        if not do_push:
            print("   Добавьте --push для коммита и пуша.")
    else:
        print("\n✓ Изменений нет.")


if __name__ == "__main__":
    main()
