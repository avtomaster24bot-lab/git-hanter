#!/usr/bin/env python3
"""Отправка сегодняшней подборки в Telegram (если заданы TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID)."""
import html
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHATS = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
CFG = json.loads((ROOT / "topics.json").read_text(encoding="utf-8"))
SITE = CFG["site_url"].rstrip("/") + "/"

if not TOKEN or not CHATS:
    print("Telegram не настроен — пропускаю")
    sys.exit(0)

API = f"https://api.telegram.org/bot{TOKEN}"
index = json.loads((ROOT / "data/index.json").read_text(encoding="utf-8"))
date = index["days"][0]["date"]
day = json.loads((ROOT / f"data/{date}.json").read_text(encoding="utf-8"))


def call(method, **kw):
    for _ in range(3):
        r = requests.post(f"{API}/{method}", timeout=60, **kw)
        if r.status_code == 429:
            time.sleep(r.json().get("parameters", {}).get("retry_after", 5) + 1)
            continue
        if not r.ok:
            print(method, r.status_code, r.text[:300])
        return r
    return None


e = html.escape


def send(CHAT):
    call("sendMessage", data={"chat_id": CHAT, "parse_mode": "HTML", "disable_web_page_preview": "true",
                              "text": f"🔎 <b>Git Hunter — подборка за {date}</b>\n{len(day['projects'])} интересных проектов GitHub.\n"
                                      f"Сайт с архивом и поиском: {SITE}#/day/{date}"})
    for p in day["projects"]:
        s = p["summary"]
        feats = "\n".join(f"• {e(str(f))}" for f in (s.get("features") or [])[:4])
        cap = (f"{e(p.get('category_emoji',''))} <b>{e(p['full_name'])}</b>  ⭐{p['stars']}"
               f"{'  · ' + e(p['language']) if p.get('language') else ''}\n<i>{e(s.get('tagline',''))}</i>\n\n"
               f"<b>Что это:</b> {e(s.get('what',''))}\n<b>Зачем:</b> {e(s.get('why',''))}\n{feats}\n\n"
               f"<a href=\"{p['url']}\">GitHub</a> · <a href=\"{SITE}#/p/{p['full_name']}\">Подробнее</a>")
        if len(cap) > 1024:
            cap = (f"{e(p.get('category_emoji',''))} <b>{e(p['full_name'])}</b>  ⭐{p['stars']}\n<i>{e(s.get('tagline',''))}</i>\n\n"
                   f"{e(s.get('what',''))[:600]}\n\n<a href=\"{p['url']}\">GitHub</a> · <a href=\"{SITE}#/p/{p['full_name']}\">Подробнее</a>")[:1024]
        r = call("sendPhoto", data={"chat_id": CHAT, "photo": p["image"], "caption": cap, "parse_mode": "HTML"})
        if r is None or not r.ok:
            call("sendMessage", data={"chat_id": CHAT, "text": cap, "parse_mode": "HTML"})
        if p.get("audio") and (ROOT / p["audio"]).exists():
            with open(ROOT / p["audio"], "rb") as f:
                call("sendAudio", data={"chat_id": CHAT, "title": p["name"], "performer": "Git Hunter"},
                     files={"audio": (Path(p["audio"]).name, f, "audio/mpeg")})
        time.sleep(1.5)


for c in CHATS:
    send(c)
    print("Отправлено в Telegram:", c)
