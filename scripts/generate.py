#!/usr/bin/env python3
"""Git Hanter: ежедневная подборка интересных проектов GitHub.

Ищет свежие и быстрорастущие репозитории, пишет понятный разбор на русском
(через GitHub Models, с запасным шаблоном), делает аудио (edge-tts / gTTS)
и сохраняет всё в data/, audio/ и feed.xml.
"""
import asyncio
import base64
import datetime as dt
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
AUDIO = ROOT / "audio"
CFG = json.loads((ROOT / "topics.json").read_text(encoding="utf-8"))
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
TZ = ZoneInfo("Asia/Almaty")
TODAY = os.environ.get("DIGEST_DATE") or dt.datetime.now(TZ).date().isoformat()
FORCE = os.environ.get("FORCE") == "1"

S = requests.Session()
S.headers.update({"Accept": "application/vnd.github+json", "User-Agent": "git-hanter",
                  "X-GitHub-Api-Version": "2022-11-28"})
if TOKEN:
    S.headers["Authorization"] = f"Bearer {TOKEN}"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- GitHub search
def search(q, sort="stars", per_page=30):
    for attempt in range(3):
        r = S.get("https://api.github.com/search/repositories",
                  params={"q": q, "sort": sort, "order": "desc", "per_page": per_page}, timeout=30)
        if r.status_code == 200:
            return r.json().get("items", [])
        if r.status_code in (403, 429):
            wait = int(r.headers.get("Retry-After", "20"))
            log(f"rate limit on '{q}', sleep {wait}s")
            time.sleep(min(wait, 60))
            continue
        log(f"search failed {r.status_code} for '{q}': {r.text[:200]}")
        return []
    return []


def days_ago(n):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=n)).date().isoformat()


def age_days(created):
    c = dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
    return max((dt.datetime.now(dt.timezone.utc) - c).total_seconds() / 86400, 1.0)


def score(repo):
    # звёзды в день с поправкой на свежесть и наличие описания
    s = repo["stargazers_count"] / age_days(repo["created_at"])
    if repo.get("description"):
        s *= 1.15
    if repo.get("homepage"):
        s *= 1.05
    if repo.get("fork") or repo.get("archived"):
        s = 0
    return s


def collect_candidates(featured):
    fresh = days_ago(CFG.get("fresh_days", 45))
    min_stars = CFG.get("min_stars", 40)
    groups = []
    for c in CFG["categories"]:
        groups.append((c["id"], c["name"], c.get("emoji", ""), c["queries"]))
    for i, u in enumerate(CFG.get("user_topics", [])):
        groups.append((f"user{i}", u["name"], u.get("emoji", "⭐"), [u["query"]]))

    cands = {}
    for cid, cname, emoji, queries in groups:
        for q in queries:
            full_q = f"{q} created:>{fresh} stars:>{min_stars} archived:false"
            items = search(full_q)
            log(f"[{cid}] {q}: {len(items)}")
            for it in items:
                fn = it["full_name"].lower()
                if fn in featured:
                    continue
                sc = score(it)
                if sc <= 0:
                    continue
                if fn not in cands or cands[fn]["_score"] < sc:
                    it["_score"] = sc
                    it["_cat"] = (cid, cname, emoji)
                    cands[fn] = it
            time.sleep(2.2)  # лимит поиска 30 запросов/мин
    return list(cands.values())


SPAM_WORDS = ("cheat", "crack", "keygen", "hack", "loader", "executor", "spoofer", "unlocker", "aimbot",
              "injector", "free download", "mod menu", "mod-menu", "trainer", "bypass", "activator",
              "license key", "free premium", "premium free", "generator free", "robux", "v-bucks", "nulled",
              "warez", "console-bridge", "dll", "unlock all", "fps boost", "wallhack", "esp ")
_users = {}


def vet(repo):
    """Отсекаем спам и репозитории с накрученными звёздами."""
    text = f"{repo['full_name']} {repo.get('description') or ''}".lower()
    if any(w in text for w in SPAM_WORDS):
        return "spam-words"
    stars, forks = repo["stargazers_count"], repo.get("forks_count", 0)
    if forks < 3:
        return "few-forks"
    if stars > 1000 and forks / stars > 0.6:
        return "fork-farm"
    if not repo.get("description"):
        return "no-description"
    login = repo["owner"]["login"]
    if login not in _users:
        r = S.get(f"https://api.github.com/users/{login}", timeout=30)
        _users[login] = r.json() if r.status_code == 200 else {}
    u = _users[login]
    if not u:
        return "no-owner"
    owner_age = age_days(u.get("created_at", dt.datetime.now(dt.timezone.utc).isoformat()))
    if owner_age < CFG.get("min_owner_age_days", 120):
        return "young-owner"
    if u.get("type") == "User" and (u.get("followers", 0) < 5 or u.get("public_repos", 0) < 2):
        return "weak-owner"
    return ""


def pick(cands):
    per_day = CFG.get("per_day", 9)
    max_cat = CFG.get("max_per_category", 2)
    cands.sort(key=lambda r: r["_score"], reverse=True)
    chosen, per_cat, owners = [], {}, set()
    checked = 0
    for r in cands:
        cid = r["_cat"][0]
        owner = r["owner"]["login"].lower()
        if per_cat.get(cid, 0) >= max_cat or owner in owners:
            continue
        if checked > 120:
            break
        checked += 1
        why = vet(r)
        r["_vet"] = why
        if why:
            log(f"  пропуск {r['full_name']}: {why}")
            continue
        chosen.append(r)
        per_cat[cid] = per_cat.get(cid, 0) + 1
        owners.add(owner)
        if len(chosen) >= per_day:
            break
    if len(chosen) < per_day:  # добираем без ограничений по категориям
        for r in cands:
            if r in chosen or r.get("_vet"):
                continue
            if "_vet" not in r:
                r["_vet"] = vet(r)
                if r["_vet"]:
                    continue
            chosen.append(r)
            if len(chosen) >= per_day:
                break
    return chosen


# ---------------------------------------------------------------- README
def fetch_readme(full_name):
    r = S.get(f"https://api.github.com/repos/{full_name}/readme", timeout=30)
    if r.status_code != 200:
        return "", ""
    j = r.json()
    try:
        text = base64.b64decode(j.get("content", "")).decode("utf-8", "ignore")
    except Exception:
        text = ""
    return text, j.get("download_url") or ""


IMG_RE = re.compile(r'!\[[^\]]*\]\(\s*<?([^)\s>]+)>?[^)]*\)|<img[^>]+src=["\']([^"\']+)["\']', re.I)
BAD_IMG = ("shields.io", "badge", "badgen", "img.shields", "travis-ci", "codecov", "github.com/actions",
           "/workflows/", "star-history", "contrib.rocks", "buymeacoffee", "ko-fi", "discord", "twitter",
           "sponsor", "visitor", "hits.", "komarev", "deepwiki", "trendshift", "producthunt", "logo")


def first_image(readme, full_name, branch):
    for m in IMG_RE.finditer(readme):
        url = (m.group(1) or m.group(2) or "").strip()
        low = url.lower()
        if not url or any(b in low for b in BAD_IMG) or low.endswith(".svg"):
            continue
        if url.startswith("//"):
            url = "https:" + url
        elif not url.startswith("http"):
            url = f"https://raw.githubusercontent.com/{full_name}/{branch}/{url.lstrip('./')}"
        elif "github.com" in url and "/blob/" in url:
            url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        return url
    return ""


def clean_readme(text, limit=6000):
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:limit]


# ---------------------------------------------------------------- AI summary
PROMPT = """Ты — автор популярного русскоязычного канала про интересные проекты на GitHub.
Объясняй просто, как другу, без жаргона (если термин нужен — поясни его в скобках).
Проект: {name}
Описание: {desc}
Язык: {lang}. Звёзд: {stars}. Темы: {topics}. Сайт: {homepage}
README (фрагмент):
\"\"\"
{readme}
\"\"\"

Верни СТРОГО JSON-объект с полями (все тексты на русском):
{{
 "tagline": "суть проекта одной фразой до 90 символов",
 "what": "Что это за проект — 2-3 предложения",
 "why": "Зачем он нужен, какую проблему решает — 2-3 предложения",
 "features": ["что умеет — 3-5 коротких пунктов"],
 "who": "Кому пригодится — 1-2 предложения",
 "how_to_start": "Как начать — 1-3 предложения или команда установки из README",
 "difficulty": "легко | средне | для профи",
 "narration": "Текст для озвучки на 30-50 секунд (70-110 слов): живой, понятный рассказ — что это, зачем и чем полезно. Без ссылок, кода, эмодзи и markdown. Название проекта латиницей допустимо."
}}"""


def llm_providers():
    """Сначала свой OpenAI-совместимый API (секреты), затем бесплатный Pollinations без ключа."""
    out = []
    url, key = os.environ.get("LLM_API_URL", "").strip(), os.environ.get("LLM_API_KEY", "").strip()
    if url and key:
        out.append(("custom", url.rstrip("/") + ("" if url.rstrip("/").endswith("/chat/completions") else "/chat/completions"),
                    {"Authorization": f"Bearer {key}"}, os.environ.get("LLM_MODEL") or CFG.get("model", "gpt-4o-mini")))
    if CFG.get("use_free_ai", True):
        out.append(("pollinations", "https://text.pollinations.ai/openai", {}, CFG.get("free_model", "openai")))
    return out


def ai_summary(repo, readme):
    prompt = PROMPT.format(
        name=repo["full_name"], desc=repo.get("description") or "—",
        lang=repo.get("language") or "—", stars=repo["stargazers_count"],
        topics=", ".join(repo.get("topics", [])[:10]) or "—",
        homepage=repo.get("homepage") or "—", readme=clean_readme(readme))
    for name, url, headers, model in llm_providers():
        body = {"model": model, "temperature": 0.5, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": "Отвечай только валидным JSON на русском языке."},
                             {"role": "user", "content": prompt}]}
        for attempt in range(4):
            try:
                r = requests.post(url, json=body, timeout=120,
                                  headers={"Content-Type": "application/json", "Accept": "application/json", **headers})
                if r.status_code == 402 and "FREE_LIMIT" in r.text:
                    m = re.search(r"Retry after (\d+)s", r.text)
                    wait = int(m.group(1)) if m else 45
                    log(f"{name} free limit, wait {wait}s")
                    time.sleep(wait + 2)
                    continue
                if r.status_code == 429:
                    wait = int(r.headers.get("Retry-After", "20") or 20)
                    log(f"{name} 429, wait {wait}s")
                    if wait > 120:
                        break
                    time.sleep(wait + 1)
                    continue
                if r.status_code != 200:
                    log(f"{name} error {r.status_code}: {r.text[:200]}")
                    time.sleep(5)
                    continue
                content = r.json()["choices"][0]["message"]["content"] or ""
                m = re.search(r"\{.*\}", content, re.S)
                data = json.loads(m.group(0) if m else content)
                if not data.get("what") or not data.get("narration"):
                    raise ValueError("incomplete json")
                if isinstance(data.get("features"), str):
                    data["features"] = [data["features"]]
                data["ai"] = name
                return data
            except Exception as e:  # noqa
                log(f"{name} exception: {e}")
                time.sleep(5)
    return None


LANG_RU = {"Python": "Python", "TypeScript": "TypeScript", "JavaScript": "JavaScript"}


def fallback_summary(repo):
    name = repo["name"]
    desc = (repo.get("description") or "Описание автор пока не добавил.").strip()
    lang = repo.get("language") or "нескольких языках"
    topics = ", ".join(repo.get("topics", [])[:5])
    cat = repo["_cat"][1]
    return {
        "tagline": desc[:90],
        "what": f"{name} — открытый проект из категории «{cat}». Описание автора: «{desc}»",
        "why": f"Проект быстро набирает популярность: {repo['stargazers_count']} звёзд за "
               f"{int(age_days(repo['created_at']))} дн. Значит, он решает задачу, которая нужна многим.",
        "features": [f"Написан на {lang}"] + ([f"Темы: {topics}"] if topics else []) +
                    ["Открытый исходный код — можно изучить и доработать"],
        "who": "Разработчикам и всем, кто интересуется темой «%s»." % cat,
        "how_to_start": "Откройте репозиторий на GitHub и следуйте инструкции в README.",
        "difficulty": "средне",
        "narration": f"Сегодня в подборке проект {name}. {desc} Он написан на {lang} и уже собрал "
                     f"{repo['stargazers_count']} звёзд. Загляните на страницу проекта, там есть инструкция по запуску.",
        "fallback": True,
    }


# ---------------------------------------------------------------- audio
async def _edge(text, path, voice):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate="+5%").save(str(path))


def make_audio(text, path):
    voice = CFG.get("voice", "ru-RU-SvetlanaNeural")
    for attempt in range(3):
        try:
            asyncio.run(_edge(text, path, voice))
            if path.exists() and path.stat().st_size > 5000:
                return "edge-tts"
        except Exception as e:  # noqa
            log(f"edge-tts failed: {e}")
            time.sleep(4 * (attempt + 1))
    try:
        from gtts import gTTS
        gTTS(text, lang="ru").save(str(path))
        if path.exists() and path.stat().st_size > 5000:
            return "gtts"
    except Exception as e:  # noqa
        log(f"gTTS failed: {e}")
    return None


# ---------------------------------------------------------------- trend
def weekly_trend(featured_all):
    items = search(f"created:>{days_ago(7)} stars:>30", per_page=40)
    items.sort(key=lambda r: r["stargazers_count"] / age_days(r["created_at"]), reverse=True)
    out = []
    for it in items:
        if it.get("fork") or vet(it):
            continue
        out.append({
            "full_name": it["full_name"], "url": it["html_url"], "description": it.get("description") or "",
            "stars": it["stargazers_count"], "language": it.get("language"),
            "stars_per_day": round(it["stargazers_count"] / age_days(it["created_at"]), 1),
            "image": f"https://opengraph.githubassets.com/1/{it['full_name']}",
            "featured": it["full_name"].lower() in featured_all,
        })
        if len(out) >= 12:
            break
    return out


# ---------------------------------------------------------------- feed
def build_feed(index, projects):
    site = CFG["site_url"].rstrip("/") + "/"
    by_date = {}
    for p in projects:
        by_date.setdefault(p["date"], []).append(p)
    items = []
    for d in index["days"][:30]:
        ps = by_date.get(d["date"], [])
        desc = "".join(
            f"<h3>{html.escape(p['full_name'])} ⭐{p['stars']}</h3><p><img src=\"{html.escape(p['image'])}\" width=\"600\"/></p>"
            f"<p><b>{html.escape(p['summary'].get('tagline',''))}</b></p><p>{html.escape(p['summary'].get('what',''))}</p>"
            f"<p>{html.escape(p['summary'].get('why',''))}</p><p><a href=\"{p['url']}\">Открыть на GitHub</a></p>"
            for p in ps)
        pub = dt.datetime.fromisoformat(d["date"]).replace(hour=8, tzinfo=TZ)
        items.append(
            f"<item><title>Git Hanter — подборка за {d['date']}</title><link>{site}#/day/{d['date']}</link>"
            f"<guid isPermaLink=\"false\">git-hanter-{d['date']}</guid>"
            f"<pubDate>{pub.strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>"
            f"<description><![CDATA[{desc}]]></description></item>")
    xml = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<rss version=\"2.0\"><channel>"
           f"<title>Git Hanter — интересные проекты GitHub</title><link>{site}</link>"
           "<description>Каждый день — свежие проекты GitHub с понятным разбором на русском</description>"
           "<language>ru</language>" + "".join(items) + "</channel></rss>\n")
    (ROOT / "feed.xml").write_text(xml, encoding="utf-8")


# ---------------------------------------------------------------- main
def main():
    DATA.mkdir(exist_ok=True)
    AUDIO.mkdir(exist_ok=True)
    index = load_json(DATA / "index.json", {"days": []})
    projects = load_json(DATA / "projects.json", [])
    if any(d["date"] == TODAY for d in index["days"]) and not FORCE:
        log(f"Подборка за {TODAY} уже есть. FORCE=1 чтобы пересобрать.")
        return
    if FORCE:
        projects = [p for p in projects if p["date"] != TODAY]
        index["days"] = [d for d in index["days"] if d["date"] != TODAY]
    featured = {p["full_name"].lower() for p in projects}

    cands = collect_candidates(featured)
    log(f"кандидатов: {len(cands)}")
    chosen = pick(cands)
    log("выбрано: " + ", ".join(r["full_name"] for r in chosen))

    day = []
    stats = {"ai": 0, "fallback": 0, "audio": 0}
    for i, repo in enumerate(chosen, 1):
        fn = repo["full_name"]
        log(f"[{i}/{len(chosen)}] {fn}")
        readme, _ = fetch_readme(fn)
        summary = ai_summary(repo, readme)
        if summary and summary.get("ai") == "pollinations":
            time.sleep(CFG.get("free_ai_pause_sec", 46))  # бесплатный лимит: 1 ответ / 45 с
        if summary:
            stats["ai"] += 1
        else:
            summary = fallback_summary(repo)
            stats["fallback"] += 1
        slug = re.sub(r"[^a-z0-9]+", "-", fn.lower()).strip("-")
        audio_rel = f"audio/{TODAY}-{slug}.mp3"
        engine = make_audio(f"{repo['name']}. {summary['narration']}", ROOT / audio_rel)
        if engine:
            stats["audio"] += 1
        cid, cname, emoji = repo["_cat"]
        day.append({
            "date": TODAY,
            "full_name": fn,
            "name": repo["name"],
            "owner": repo["owner"]["login"],
            "avatar": repo["owner"].get("avatar_url"),
            "url": repo["html_url"],
            "homepage": repo.get("homepage") or "",
            "description": repo.get("description") or "",
            "stars": repo["stargazers_count"],
            "forks": repo.get("forks_count", 0),
            "language": repo.get("language") or "",
            "topics": repo.get("topics", [])[:8],
            "license": (repo.get("license") or {}).get("spdx_id") or "",
            "created_at": repo["created_at"],
            "stars_per_day": round(repo["stargazers_count"] / age_days(repo["created_at"]), 1),
            "category": cid, "category_name": cname, "category_emoji": emoji,
            "image": f"https://opengraph.githubassets.com/1/{fn}",
            "readme_image": first_image(readme, fn, repo.get("default_branch", "main")),
            "audio": audio_rel if engine else "",
            "audio_engine": engine or "",
            "summary": summary,
        })

    # второй шанс для карточек, где ИИ не ответил
    for item in day:
        if not item["summary"].get("fallback"):
            continue
        repo = next(r for r in chosen if r["full_name"] == item["full_name"])
        log(f"повтор ИИ для {item['full_name']}")
        time.sleep(CFG.get("free_ai_pause_sec", 46))
        summary = ai_summary(repo, fetch_readme(item["full_name"])[0])
        if summary:
            item["summary"] = summary
            stats["ai"] += 1
            stats["fallback"] -= 1
            rel = f"audio/{TODAY}-" + re.sub(r"[^a-z0-9]+", "-", item["full_name"].lower()).strip("-") + ".mp3"
            engine = make_audio(f"{repo['name']}. {summary['narration']}", ROOT / rel)
            if engine:
                item["audio_engine"], item["audio"] = engine, rel

    if not day:
        log("Не найдено ни одного проекта")
        sys.exit(1)

    save_json(DATA / f"{TODAY}.json", {"date": TODAY, "projects": day})
    projects = day + projects
    save_json(DATA / "projects.json", projects)
    index["days"].insert(0, {"date": TODAY, "count": len(day),
                             "names": [p["full_name"] for p in day]})
    index["days"].sort(key=lambda d: d["date"], reverse=True)
    index["updated"] = dt.datetime.now(TZ).isoformat(timespec="minutes")
    index["total"] = len(projects)
    index["categories"] = [{"id": c["id"], "name": c["name"], "emoji": c.get("emoji", "")} for c in CFG["categories"]] + \
        [{"id": f"user{i}", "name": u["name"], "emoji": u.get("emoji", "⭐")} for i, u in enumerate(CFG.get("user_topics", []))]
    index["last_stats"] = stats
    save_json(DATA / "index.json", index)
    save_json(DATA / "trend.json", {"updated": index["updated"],
                                     "items": weekly_trend({p["full_name"].lower() for p in projects})})
    build_feed(index, projects)
    log(f"Готово: {len(day)} проектов, AI {stats['ai']}, шаблон {stats['fallback']}, аудио {stats['audio']}")
    gh_out = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"## Git Hanter {TODAY}\n\nПроектов: {len(day)}, AI-разборов: {stats['ai']}, "
                    f"шаблонов: {stats['fallback']}, аудио: {stats['audio']}\n\n" +
                    "\n".join(f"- [{p['full_name']}]({p['url']}) ⭐{p['stars']} — {p['summary'].get('tagline','')}" for p in day))


if __name__ == "__main__":
    main()
