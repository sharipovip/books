#!/usr/bin/env python3
"""
generate_covers_manifest.py
───────────────────────────
Обходит папку covers/ репозитория и создаёт covers_manifest.json —
отображение «book_id → URL обложки на raw.githubusercontent.com».

Логика:
  covers/<relative_path>.jpg  →  ключ: <relative_path>, значение: raw URL

Где <relative_path> — это путь от covers/ без расширения,
соответствующий пути книги в books/ без расширения:
  books/Илмӣ/Адабиётшиносӣ/kitob.pdf  →  covers_manifest["Илмӣ/Адабиётшиносӣ/kitob"]
  books/Адабиёти классикӣ/Наср/kitob.pdf → covers_manifest["Адабиёти классикӣ/Наср/kitob"]

Запуск:
  python3 generate_covers_manifest.py          # только генерирует файл
  python3 generate_covers_manifest.py --push   # генерирует + коммитит + пушит

CI (GitHub Actions):
  Работает автоматически — смотри .github/workflows/build.yml
"""

import os
import sys
import json
import urllib.parse
import subprocess
from pathlib import Path

# ─── Конфигурация ────────────────────────────────────────────────────────────
REPO   = "sharipovip/books"
BRANCH = "main"
COVERS_DIR = Path("covers")
OUTPUT     = Path("covers_manifest.json")
# ─────────────────────────────────────────────────────────────────────────────


def build_manifest() -> dict:
    """Обходит covers/ и возвращает {key: raw_url, ...}."""
    manifest: dict[str, str] = {}

    if not COVERS_DIR.is_dir():
        print(f"⚠ Папка {COVERS_DIR} не найдена, манифест будет пуст.")
        return manifest

    extensions = {".jpg", ".jpeg", ".png", ".webp"}
    count = 0

    for img_path in sorted(COVERS_DIR.rglob("*")):
        if not img_path.is_file():
            continue
        if img_path.suffix.lower() not in extensions:
            continue

        # Путь от covers/ без расширения: "Илмӣ/Адабиётшиносӣ/kitob"
        rel = img_path.relative_to(COVERS_DIR)
        key = str(rel.with_suffix(""))

        # URL на raw.githubusercontent.com (без кодирования — raw
        # работает с utf-8, но кодируем для безопасности)
        encoded_key = urllib.parse.quote(key, safe="")
        encoded_file = urllib.parse.quote(img_path.name)
        url = (
            f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
            f"/covers/{encoded_key}/{encoded_file}"
        )
        manifest[key] = url
        count += 1

    print(f"📦 Найдено обложек: {count}")
    return manifest


def write_manifest(manifest: dict) -> bool:
    """Записывает covers_manifest.json, возвращает True если файл изменился."""
    new_content = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"

    old_content = None
    if OUTPUT.exists():
        old_content = OUTPUT.read_text(encoding="utf-8")

    if old_content == new_content:
        print("✓ covers_manifest.json не изменился — коммит не нужен.")
        return False

    OUTPUT.write_text(new_content, encoding="utf-8")
    print(f"✅ covers_manifest.json записан ({len(manifest)} записей).")
    return True


def git_commit_and_push() -> bool:
    """Делает git add + commit + push, если есть изменения."""
    try:
        # Проверяем, что это git-репозиторий
        subprocess.run(["git", "rev-parse", "--git-dir"], check=True,
                       capture_output=True)

        # git add
        r = subprocess.run(["git", "add", str(OUTPUT)], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"⚠ git add ошибка: {r.stderr}")
            return False

        # Проверяем, есть ли изменения в индексе
        r = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
        if r.returncode == 0:
            print("✓ Нет изменений для коммита.")
            return False

        # Настраиваем пользователя (для CI)
        subprocess.run(["git", "config", "user.name",  "github-actions[bot]"],
                       check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
                       check=True, capture_output=True)

        # Commit
        msg = f"🤖 auto: update covers_manifest.json ({len(build_manifest())} covers)"
        r = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"⚠ git commit ошибка: {r.stderr}")
            return False
        print(f"✅ Коммит: {msg}")

        # Push
        r = subprocess.run(["git", "push"], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"⚠ git push ошибка: {r.stderr}")
            return False
        print("✅ Push выполнен.")
        return True

    except FileNotFoundError:
        print("⚠ git не найден — пропускаю коммит/пуш.")
        return False
    except subprocess.CalledProcessError as e:
        print(f"⚠ Git error: {e}")
        return False


def main() -> None:
    do_push = "--push" in sys.argv

    manifest = build_manifest()
    changed = write_manifest(manifest)

    if changed and do_push:
        git_commit_and_push()

    if changed:
        print(f"\n📄 covers_manifest.json готов ({len(manifest)} обложек).")
        if not do_push:
            print("   Запустите с --push чтобы закоммитить и запушить.")
    else:
        print("\n✓ Изменений нет.")


if __name__ == "__main__":
    main()
