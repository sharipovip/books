#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the global search index used by Kitobkhona from catalog manifests.

The index stores the exact repository folder, file name, category and subcategory
for every supported book so search results open the correct file in the app.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parent
OUTPUT_NAME = "search-index.json"
SUPPORTED_EXTS = {".pdf", ".epub", ".fb2", ".doc", ".docx", ".mp4", ".m4v", ".webm", ".txt", ".zip"}


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Cannot read valid JSON from {path}: {exc}") from exc


def safe_folder_path(root: Path, folder: str) -> Path:
    rel = PurePosixPath(str(folder).replace("\\", "/"))
    if not rel.parts or rel.parts[0] != "books" or any(part in ("", ".", "..") for part in rel.parts):
        raise ValueError(f"Unsafe or invalid book folder: {folder!r}")
    path = root.joinpath(*rel.parts)
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError(f"Book folder escapes repository root: {folder!r}")
    return path


def build_index(root: Path) -> dict[str, Any]:
    catalog_path = root / "books.json"
    catalog = read_json(catalog_path)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("categories"), list):
        raise RuntimeError("books.json must contain a categories array")

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for category in catalog["categories"]:
        if not isinstance(category, dict):
            continue
        category_id = str(category.get("id") or "")
        category_name = str(category.get("name") or category.get("folder_raw") or "")
        subs = category.get("subs") if isinstance(category.get("subs"), list) else []
        for subcategory in subs:
            if not isinstance(subcategory, dict):
                continue
            folder = str(subcategory.get("folder") or "").strip().rstrip("/")
            if not folder:
                raise RuntimeError(f"Catalog subcategory has no folder: {category_name!r}/{subcategory!r}")
            manifest_path = safe_folder_path(root, folder) / "manifest.json"
            manifest = read_json(manifest_path)
            books = manifest.get("books") if isinstance(manifest, dict) else None
            if not isinstance(books, list):
                raise RuntimeError(f"{manifest_path} must contain a books array")

            subcategory_name = str(subcategory.get("name") or subcategory.get("folder_raw") or folder)
            for book in books:
                if not isinstance(book, dict):
                    continue
                file_name = str(book.get("file") or "").strip()
                if (not file_name or Path(file_name).name != file_name or "/" in file_name or chr(92) in file_name or file_name in {".", ".."}):
                    raise RuntimeError(f"Invalid file name in {manifest_path}: {file_name!r}")
                if Path(file_name).suffix.lower() not in SUPPORTED_EXTS:
                    continue
                item_id = f"{folder}/{file_name}"
                if item_id in seen:
                    continue
                seen.add(item_id)
                name = str(book.get("name") or Path(file_name).stem)
                try:
                    size = int(book.get("size") or 0)
                except (TypeError, ValueError):
                    size = 0
                try:
                    mtime = int(book.get("mtime") or 0)
                except (TypeError, ValueError):
                    mtime = 0
                items.append({
                    "id": item_id,
                    "name": name,
                    "file": file_name,
                    "author": str(book.get("author") or book.get("book_author") or ""),
                    "folder": folder,
                    "category_id": category_id,
                    "category": category_name,
                    "subcategory": subcategory_name,
                    "size": size,
                    "mtime": mtime,
                })

    items.sort(key=lambda item: (
        item["category_id"].casefold(),
        item["subcategory"].casefold(),
        item["name"].casefold(),
        item["file"].casefold(),
    ))
    return {
        "version": 1,
        "updatedAt": str(catalog.get("updatedAt") or ""),
        "repo": str(catalog.get("repo") or os.environ.get("KITOB_REPO", "sharipovip/books")),
        "branch": str(catalog.get("branch") or os.environ.get("KITOB_BRANCH", "main")),
        "count": len(items),
        "items": items,
    }


def write_if_changed(path: Path, value: dict[str, Any]) -> bool:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == text:
        print(f"✓ {path.name} is up to date ({len(value['items'])} books)")
        return False
    path.write_text(text, encoding="utf-8")
    print(f"✅ {path.name} generated with {len(value['items'])} books")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="book repository root (defaults to this script's folder)")
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / "books.json").is_file():
        raise SystemExit(f"books.json not found in {root}")
    index = build_index(root)
    write_if_changed(root / OUTPUT_NAME, index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
