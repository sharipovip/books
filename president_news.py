#!/usr/bin/env python3
"""Архив новостей сомонаи Президенти ҶТ (prezident.tj) — робот v101.

Каждый запуск (GitHub Actions, cron каждый час):
  1. Берёт 12 последних новостей каждой из 8 категорий с открытого API
     controlpanel.president.tj (тот же API, что использует сам сайт).
  2. Каждую новость сохраняет ОТДЕЛЬНЫМ файлом: president/<категория>/<id>.json
     (заголовок, дата, полный текст, ссылки на фото flickr) — полный архив.
  3. Собирает president/index.json — компактный список для приложения
     (резерв, если API недоступен: заголовки + дата + превью-фото).

Новые новости докачиваются (полный текст + фото), старые не трогаются —
архив только растёт. Если изменений нет — коммит не создаётся.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "president"
API = "https://controlpanel.president.tj"
LANG_ID = 1  # тоҷикӣ
PER_CAT = 12
TIMEOUT = 25
PAUSE = 0.12  # пауза между запросами, чтобы не нагружать сомона

CATS = [
    ("news", "Хабарҳо"),
    ("meetings", "Вохӯриҳо"),
    ("speeches", "Суханрониҳо"),
    ("trips", "Сафарҳо"),
    ("documents", "Санадҳо"),
    ("missives", "Паём"),
    ("telegrams", "Барқияҳо"),
    ("calls", "Суҳбатҳои телефонӣ"),
]


def api_get(path: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        API + path + "?" + qs,
        headers={"User-Agent": "KitobkhonaApp/1.0 (news archive robot)", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_cat(cat: str) -> list[dict]:
    d = api_get("/api/home-event", {"event_type": cat, "lang_id": LANG_ID})
    if not d.get("success") or not isinstance(d.get("data"), list):
        return []
    out = []
    for it in d["data"]:
        if it.get("id") and it.get("title"):
            out.append({
                "id": it["id"],
                "title": it["title"],
                "publish": it.get("publish_date") or it.get("news_date") or "",
                "has_photos": bool(it.get("news_flickr_image_relation")),
                "site_path": it.get("remote_url") or "",
            })
    return out[:PER_CAT]


def fetch_article(news_id: int) -> dict | None:
    try:
        d = api_get("/api/event/show", {"id": news_id, "lang_id": LANG_ID})
        if d.get("success") and d.get("data"):
            a = d["data"]
            return {
                "title": a.get("title") or "",
                "publish": a.get("publish_date") or "",
                "teaser": a.get("teaser") or "",
                "text": a.get("text") or a.get("teaser") or "",
                "site_path": a.get("remote_url") or "",
            }
    except Exception as e:
        print(f"⚠ show {news_id}: {e}")
    return None


def fetch_photos(news_id: int) -> dict:
    try:
        d = api_get("/api/event-flickr-images", {"id": news_id, "lang_id": LANG_ID})
        data = d.get("data") if d.get("success") else []
        small, big = [], []
        for p in data or []:
            if not p.get("src"):
                continue
            if p.get("type") == "small":
                small.append(p["src"])
            elif p.get("type") == "original":
                big.append(p["src"])
        return {"thumbs": small, "big": big}
    except Exception as e:
        print(f"⚠ flickr {news_id}: {e}")
        return {"thumbs": [], "big": []}


def write_if_changed(path: Path, data) -> bool:
    payload = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return True


def main() -> int:
    os.chdir(ROOT)
    if not OUT_DIR.exists():
        OUT_DIR.mkdir(parents=True)

    index_cats: dict[str, list[dict]] = {}
    new_files = 0

    for cat, label in CATS:
        items = fetch_cat(cat)
        print(f"• {cat} ({label}): {len(items)} хабар")
        index_list = []
        for it in items:
            nid = it["id"]
            file_path = OUT_DIR / cat / f"{nid}.json"
            record = None
            if file_path.exists():
                try:
                    record = json.loads(file_path.read_text(encoding="utf-8"))
                except Exception:
                    record = None
            if record is None:
                # новая новость — скачиваем полный текст и фото (АРХИВ)
                art = fetch_article(nid)
                photos = fetch_photos(nid) if it["has_photos"] else {"thumbs": [], "big": []}
                time.sleep(PAUSE)
                if art is None:
                    art = {"title": it["title"], "publish": it["publish"], "teaser": "", "text": "", "site_path": it["site_path"]}
                record = {
                    "id": nid,
                    "cat": cat,
                    "cat_label": label,
                    "title": it["title"],
                    "publish": it["publish"],
                    "site_path": it.get("site_path") or art.get("site_path") or "",
                    "teaser": art.get("teaser") or "",
                    "text": art.get("text") or "",
                    "photos": photos,
                    "archived_at": date.today().isoformat(),
                }
                if write_if_changed(file_path, record):
                    new_files += 1
                    print(f"  + архив: president/{cat}/{nid}.json")
            index_list.append({
                "id": nid,
                "title": record.get("title") or it["title"],
                "publish": record.get("publish") or it["publish"],
                "thumb": (record.get("photos", {}).get("thumbs") or [""])[0] or "",
                "photos_count": max(len(record.get("photos", {}).get("thumbs") or []), len(record.get("photos", {}).get("big") or [])),
                "site_path": record.get("site_path") or "",
            })
        index_cats[cat] = index_list

    index = {
        "version": 1,
        "updatedAt": date.today().isoformat(),
        "source": "prezident.tj",
        "cats": index_cats,
    }
    changed = write_if_changed(OUT_DIR / "index.json", index)
    print(f"✅ Архив: {new_files} новых новостей, index.json {'обновлён' if changed else 'без изменений'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
