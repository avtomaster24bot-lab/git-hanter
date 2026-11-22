#!/usr/bin/env python3
"""Автопубликация видео подборки: YouTube Shorts, Instagram Reels, TikTok.

Запуск: python scripts/publish_social.py youtube|instagram|tiktok
Каждая платформа работает только если заданы её секреты (см. docs/AUTOPUBLISH.md).
Уже опубликованное записывается в data/published.json и повторно не загружается.
Токены никогда не выводятся в лог.
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "topics.json").read_text(encoding="utf-8"))
AP = CFG.get("autopublish", {})
SITE = CFG["site_url"].rstrip("/") + "/"
REG = ROOT / "data/published.json"


def env(name):
    return os.environ.get(name, "").strip()


def log(*a):
    print(*a, flush=True)


def summary(text):
    if env("GITHUB_STEP_SUMMARY"):
        with open(env("GITHUB_STEP_SUMMARY"), "a", encoding="utf-8") as f:
            f.write(text + "\n")


def load_day():
    index = json.loads((ROOT / "data/index.json").read_text(encoding="utf-8"))
    date = env("PUBLISH_DATE") or index["days"][0]["date"]
    return date, json.loads((ROOT / f"data/{date}.json").read_text(encoding="utf-8"))


def registry():
    try:
        return json.loads(REG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_registry(reg):
    REG.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")


def local_video(p):
    path = ROOT / p["video"]
    if path.exists():
        return path
    url = p.get("video_release_url")
    if not url:
        return None
    path.parent.mkdir(exist_ok=True)
    r = requests.get(url, timeout=300)
    if r.ok:
        path.write_bytes(r.content)
        return path
    return None


# ------------------------------------------------------------------ YouTube
def youtube(p, path):
    tok = requests.post("https://oauth2.googleapis.com/token", timeout=60, data={
        "client_id": env("YOUTUBE_CLIENT_ID"), "client_secret": env("YOUTUBE_CLIENT_SECRET"),
        "refresh_token": env("YOUTUBE_REFRESH_TOKEN"), "grant_type": "refresh_token"})
    if not tok.ok:
        raise RuntimeError(f"YouTube OAuth: {tok.status_code} {tok.json().get('error')}")
    access = tok.json()["access_token"]
    post = p["post"]
    meta = {"snippet": {"title": post["youtube_title"], "description": post["youtube_description"],
                        "tags": [t.lstrip("#") for t in post["hashtags"]] + ["shorts"],
                        "categoryId": "28", "defaultLanguage": "ru", "defaultAudioLanguage": "ru"},
            "status": {"privacyStatus": env("YOUTUBE_PRIVACY") or AP.get("youtube_privacy", "public"),
                       "selfDeclaredMadeForKids": False}}
    size = path.stat().st_size
    init = requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                         json=meta, timeout=60, headers={"Authorization": f"Bearer {access}",
                                                         "X-Upload-Content-Type": "video/mp4",
                                                         "X-Upload-Content-Length": str(size)})
    if not init.ok:
        raise RuntimeError(f"YouTube init: {init.status_code} {init.text[:300]}")
    with open(path, "rb") as f:
        up = requests.put(init.headers["Location"], data=f, timeout=600,
                          headers={"Authorization": f"Bearer {access}", "Content-Type": "video/mp4"})
    if not up.ok:
        raise RuntimeError(f"YouTube upload: {up.status_code} {up.text[:300]}")
    vid = up.json()["id"]
    return vid, f"https://youtube.com/shorts/{vid}"


# ------------------------------------------------------------------ Instagram
def instagram(p, path):
    v = env("INSTAGRAM_GRAPH_VERSION") or AP.get("instagram_graph_version", "v23.0")
    host = "graph.instagram.com" if env("INSTAGRAM_LOGIN_API") == "1" else "graph.facebook.com"
    base = f"https://{host}/{v}"
    uid, token = env("INSTAGRAM_USER_ID"), env("INSTAGRAM_ACCESS_TOKEN")
    video_url = SITE + p["video"]  # видео лежит на GitHub Pages (публичный URL)
    head = requests.head(video_url, timeout=30, allow_redirects=True)
    if not head.ok:
        video_url = p.get("video_release_url") or video_url
    c = requests.post(f"{base}/{uid}/media", timeout=60, data={
        "media_type": "REELS", "video_url": video_url, "caption": p["post"]["caption"],
        "share_to_feed": "true", "access_token": token})
    if not c.ok:
        raise RuntimeError(f"Instagram container: {c.status_code} {c.text[:300]}")
    cid = c.json()["id"]
    for _ in range(60):  # до 10 минут на обработку
        time.sleep(10)
        st = requests.get(f"{base}/{cid}", timeout=30, params={"fields": "status_code,status", "access_token": token}).json()
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram processing: {st}")
    else:
        raise RuntimeError("Instagram: видео не обработалось за 10 минут")
    pub = requests.post(f"{base}/{uid}/media_publish", timeout=60, data={"creation_id": cid, "access_token": token})
    if not pub.ok:
        raise RuntimeError(f"Instagram publish: {pub.status_code} {pub.text[:300]}")
    mid = pub.json()["id"]
    link = requests.get(f"{base}/{mid}", timeout=30, params={"fields": "permalink", "access_token": token}).json()
    return mid, link.get("permalink", "")


# ------------------------------------------------------------------ TikTok
_tt = {}


def tiktok_token():
    if "access" in _tt:
        return _tt["access"]
    r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=60, data={
        "client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"),
        "grant_type": "refresh_token", "refresh_token": env("TIKTOK_REFRESH_TOKEN")},
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    j = r.json()
    if "access_token" not in j:
        raise RuntimeError(f"TikTok OAuth: {j.get('error')} {j.get('error_description')}")
    if j.get("refresh_token") and j["refresh_token"] != env("TIKTOK_REFRESH_TOKEN"):
        summary("⚠️ TikTok выдал новый refresh token. Старый продолжит работать до истечения срока; "
                "при ошибке авторизации получите токен заново (docs/AUTOPUBLISH.md).")
    _tt["access"] = j["access_token"]
    return _tt["access"]


def tiktok(p, path):
    access = tiktok_token()
    H = {"Authorization": f"Bearer {access}", "Content-Type": "application/json; charset=UTF-8"}
    info = requests.post("https://open.tiktokapis.com/v2/post/publish/creator_info/query/", headers=H, timeout=60).json()
    opts = info.get("data", {}).get("privacy_level_options") or ["SELF_ONLY"]
    want = env("TIKTOK_PRIVACY") or AP.get("tiktok_privacy", "SELF_ONLY")
    privacy = want if want in opts else ("SELF_ONLY" if "SELF_ONLY" in opts else opts[0])
    size = path.stat().st_size
    init = requests.post("https://open.tiktokapis.com/v2/post/publish/video/init/", headers=H, timeout=60, json={
        "post_info": {"title": p["post"]["caption"][:2200], "privacy_level": privacy,
                      "disable_comment": False, "disable_duet": False, "disable_stitch": False},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}}).json()
    if init.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok init: {init['error']}")
    data = init["data"]
    with open(path, "rb") as f:
        up = requests.put(data["upload_url"], data=f, timeout=600, headers={
            "Content-Type": "video/mp4", "Content-Length": str(size), "Content-Range": f"bytes 0-{size - 1}/{size}"})
    if up.status_code not in (200, 201):
        raise RuntimeError(f"TikTok upload: {up.status_code} {up.text[:300]}")
    status = ""
    for _ in range(30):
        time.sleep(10)
        st = requests.post("https://open.tiktokapis.com/v2/post/publish/status/fetch/", headers=H, timeout=60,
                           json={"publish_id": data["publish_id"]}).json()
        status = st.get("data", {}).get("status", "")
        if status in ("PUBLISH_COMPLETE", "FAILED"):
            break
    if status == "FAILED":
        raise RuntimeError(f"TikTok: публикация не удалась {st.get('data')}")
    return data["publish_id"], f"(TikTok, приватность {privacy}, статус {status or 'в обработке'})"


PLATFORMS = {
    "youtube": (youtube, ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"], "youtube_max_per_day", 5),
    "instagram": (instagram, ["INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID"], "instagram_max_per_day", 9),
    "tiktok": (tiktok, ["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN"], "tiktok_max_per_day", 5),
}


def main():
    name = sys.argv[1]
    fn, secrets, limit_key, default_limit = PLATFORMS[name]
    if not all(env(s) for s in secrets):
        log(f"{name}: секреты не заданы — пропускаю")
        return
    date, day = load_day()
    reg = registry()
    done = reg.setdefault(name, {})
    limit = int(AP.get(limit_key, default_limit))
    count, errors = 0, 0
    for p in day["projects"]:
        key = f"{date}/{p['full_name']}"
        if key in done or not p.get("video") or not p.get("post"):
            continue
        if count >= limit:
            log(f"{name}: дневной лимит {limit} исчерпан")
            break
        path = local_video(p)
        if not path:
            log(f"{name}: нет файла видео для {p['full_name']}")
            continue
        try:
            pid, link = fn(p, path)
            done[key] = {"id": pid, "url": link, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            save_registry(reg)
            count += 1
            log(f"{name}: ✅ {p['full_name']} → {link}")
            summary(f"- {name}: [{p['full_name']}]({link or '#'})")
            time.sleep(5)
        except Exception as e:  # noqa
            errors += 1
            log(f"{name}: ❌ {p['full_name']}: {e}")
            summary(f"- {name}: ошибка для {p['full_name']}: {str(e)[:200]}")
            if errors >= 3:
                break
    log(f"{name}: опубликовано {count}, ошибок {errors}")


if __name__ == "__main__":
    main()
