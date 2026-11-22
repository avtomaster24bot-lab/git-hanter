/* Git Hunter — клиент без сборки */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => (n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(".0", "") + "k" : String(n ?? 0));
  const ruDate = (d) => new Date(d + "T00:00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric", weekday: "long" });
  const plural = (n, a, b, c) => { const m = n % 10, h = n % 100; return m === 1 && h !== 11 ? a : m >= 2 && m <= 4 && (h < 10 || h >= 20) ? b : c; };
  const QUICK = ["telegram бот", "AI агенты", "генерация видео", "self-hosted", "автоматизация", "парсер", "голосовой ассистент", "CRM"];

  const state = { index: null, projects: [], trend: null, cat: "", lang: "", view: "", list: [], playlist: [], plIdx: -1 };
  const favs = new Map(JSON.parse(localStorage.getItem("gh_favs") || "[]").map((p) => [p.full_name, p]));
  const saveFavs = () => { localStorage.setItem("gh_favs", JSON.stringify([...favs.values()])); $("#favCount").textContent = favs.size || ""; };

  const toast = (t) => { const el = $("#toast"); el.textContent = t; el.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove("show"), 2200); };
  const getJSON = async (u) => { const r = await fetch(u, { cache: "no-cache" }); if (!r.ok) throw new Error(r.status); return r.json(); };

  async function load() {
    try {
      state.index = await getJSON("data/index.json");
      state.projects = await getJSON("data/projects.json").catch(() => []);
    } catch (e) {
      state.index = { days: [] };
    }
    state.trend = await getJSON("data/trend.json").catch(() => null);
    const langs = [...new Set(state.projects.map((p) => p.language).filter(Boolean))].sort();
    $("#langSel").innerHTML += langs.map((l) => `<option>${esc(l)}</option>`).join("");
    if (state.index.updated) $("#updated").textContent = "Последнее обновление: " + new Date(state.index.updated).toLocaleString("ru-RU") + ` · всего проектов в базе: ${state.index.total || state.projects.length}`;
    $("#quick").innerHTML = QUICK.map((q) => `<button type="button" data-q="${esc(q)}">${esc(q)}</button>`).join("");
    saveFavs();
    route();
  }

  /* ---------- видео ---------- */
  function videoSrc(p) {
    if (!p.video) return "";
    const recent = (state.index.days || []).slice(0, 7).some((d) => d.date === p.date);
    return recent || !p.video_release_url ? p.video : p.video_release_url;
  }
  function posterSrc(p) {
    if (!p.video) return p.image;
    const recent = (state.index.days || []).slice(0, 7).some((d) => d.date === p.date);
    return recent ? p.video.replace(/\.mp4$/, ".jpg") : (p.video_poster_release_url || p.image);
  }
  function videoBlock(p, open) {
    if (!p.video) return "";
    const src = videoSrc(p);
    const player = `<video class="vplayer" controls playsinline preload="none" poster="${esc(posterSrc(p))}" src="${esc(src)}"></video>`;
    const btns = `<div class="vbtns">
        <a class="btn" href="${esc(src)}" download="${esc(p.name)}-git-hunter.mp4">⬇ Скачать видео</a>
        ${p.post ? `<button class="btn ghost" data-copy="youtube" data-name="${esc(p.full_name)}">📋 Текст для YouTube</button>
        <button class="btn ghost" data-copy="instagram" data-name="${esc(p.full_name)}">📋 Для Instagram</button>
        <button class="btn ghost" data-copy="tiktok" data-name="${esc(p.full_name)}">📋 Для TikTok</button>` : ""}
      </div><small class="vnote">Вертикальное видео 1080×1920${p.video_duration ? ` · ${Math.round(p.video_duration)} с` : ""}${p.video_mb ? ` · ${p.video_mb} МБ` : ""} — готово для Shorts, Reels и TikTok</small>`;
    if (open) return `<div class="vwrap">${player}${btns}</div>`;
    return `<details class="more video"><summary>🎬 Видео для Shorts / Reels / TikTok</summary><div class="vwrap">${player}${btns}</div></details>`;
  }
  function postText(p, kind) {
    const t = p.post || {};
    if (kind === "youtube") return `${t.youtube_title}\n\n${t.youtube_description}`;
    return t.caption || "";
  }
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); }
    catch (e) { const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); }
  }

  /* ---------- карточки ---------- */
  function section(title, text) { return text ? `<div class="s"><b>${title}</b><p>${esc(text)}</p></div>` : ""; }
  function howTo(t) { return t ? `<div class="s"><b>Как начать</b><p>${esc(t).replace(/`([^`]+)`/g, "<code>$1</code>")}</p></div>` : ""; }

  function card(p, i) {
    const s = p.summary || {};
    const img = p.image || `https://opengraph.githubassets.com/1/${p.full_name}`;
    const fav = favs.has(p.full_name);
    const feats = (s.features || []).length ? `<div class="s"><b>Что умеет</b><ul>${s.features.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>` : "";
    const rich = !!p.summary;
    return `<article class="card" data-name="${esc(p.full_name)}">
      <a class="img" href="#/p/${esc(p.full_name)}"><img loading="lazy" src="${esc(img)}" alt="${esc(p.full_name)}" onerror="this.src='https://opengraph.githubassets.com/1/${esc(p.full_name)}'">
        ${p.category_name ? `<span class="badge">${esc(p.category_emoji || "")} ${esc(p.category_name)}</span>` : ""}
        ${i != null ? `<span class="rank">#${i + 1}</span>` : ""}</a>
      <div class="body">
        <div class="title"><img src="https://github.com/${esc(p.owner || p.full_name.split("/")[0])}.png?size=56" alt="" loading="lazy" onerror="this.remove()"><div><h3><a href="#/p/${esc(p.full_name)}">${esc(p.name || p.full_name)}</a></h3><small>${esc(p.owner || p.full_name.split("/")[0])}</small></div></div>
        ${s.tagline ? `<p class="tag">${esc(s.tagline)}</p>` : p.description ? `<p class="tag">${esc(p.description)}</p>` : ""}
        <div class="meta"><span>⭐ ${fmt(p.stars)}</span>${p.language ? `<span>● ${esc(p.language)}</span>` : ""}${p.stars_per_day ? `<span class="hot">🔥 +${fmt(p.stars_per_day)}/день</span>` : ""}${p.license ? `<span>${esc(p.license)}</span>` : ""}${s.difficulty ? `<span class="diff">${esc(s.difficulty)}</span>` : ""}</div>
        ${rich ? section("Что это", s.what) + section("Зачем", s.why) + `<details class="more"><summary>Что умеет, кому пригодится, как начать</summary>${feats}${section("Кому пригодится", s.who)}${howTo(s.how_to_start)}</details>` : ""}
        ${videoBlock(p)}
        ${s.fallback ? `<span class="fallback">Краткое описание по данным GitHub (ИИ-разбор недоступен)</span>` : ""}
        <div class="actions">
          ${p.audio ? `<button class="btn" data-play="${esc(p.full_name)}">▶ Слушать</button>` : ""}
          <a class="btn ghost" href="${esc(p.url || "https://github.com/" + p.full_name)}" target="_blank" rel="noopener">GitHub ↗</a>
          ${p.homepage ? `<a class="btn ghost" href="${esc(p.homepage)}" target="_blank" rel="noopener">Сайт ↗</a>` : ""}
          <button class="btn ghost ${fav ? "on" : ""}" data-fav="${esc(p.full_name)}">${fav ? "★ В избранном" : "☆ В избранное"}</button>
          <button class="btn ghost" data-share="${esc(p.full_name)}" title="Поделиться">↗ Поделиться</button>
        </div>
      </div></article>`;
  }

  function filtered(list) {
    return list.filter((p) => (!state.cat || p.category === state.cat) && (!state.lang || p.language === state.lang));
  }

  function renderChips(list) {
    const present = new Set(list.map((p) => p.category).filter(Boolean));
    const cats = (state.index.categories || []).filter((c) => present.has(c.id));
    $("#toolbar").style.display = list.length && list.some((p) => p.category || p.language) ? "" : "none";
    $("#catChips").innerHTML = `<button class="chip ${state.cat ? "" : "active"}" data-cat="">Все</button>` +
      cats.map((c) => `<button class="chip ${state.cat === c.id ? "active" : ""}" data-cat="${esc(c.id)}">${esc(c.emoji)} ${esc(c.name)}</button>`).join("");
  }

  function grid(list, ranked) {
    state.list = list;
    const f = filtered(list);
    renderChips(list);
    if (!f.length) return `<div class="empty">Ничего не найдено. Попробуйте сбросить фильтры.</div>`;
    return `<div class="grid">${f.map((p) => card(p, ranked ? list.indexOf(p) : null)).join("")}</div>`;
  }

  /* ---------- экраны ---------- */
  const V = $("#view");
  const setNav = (n) => document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === n));

  function viewDay(date) {
    const days = state.index.days || [];
    if (!days.length) { renderChips([]); V.innerHTML = `<div class="empty">Первая подборка ещё готовится. Загляните чуть позже — она появляется каждый день в 08:00 (Алматы).</div>`; return; }
    const d = date || days[0].date;
    const list = state.projects.filter((p) => p.date === d);
    const i = days.findIndex((x) => x.date === d);
    const prev = days[i + 1], next = days[i - 1];
    const withAudio = list.filter((p) => p.audio).length;
    V.innerHTML = `<div class="sec-head"><div><h2>${date ? "Подборка" : "Подборка дня"} · ${esc(ruDate(d))}</h2>
      <p>${list.length} ${plural(list.length, "проект", "проекта", "проектов")} · свежие и быстрорастущие репозитории</p></div>
      <div class="actions">${withAudio ? `<button class="btn" data-playall="1">▶ Слушать всю подборку</button>` : ""}
      ${prev ? `<a class="btn ghost" href="#/day/${prev.date}">← ${prev.date}</a>` : ""}${next ? `<a class="btn ghost" href="#/day/${next.date}">${next.date} →</a>` : ""}</div></div>` + grid(list, true) + studioBanner();
  }

  function viewArchive() {
    renderChips([]);
    const days = state.index.days || [];
    V.innerHTML = `<div class="sec-head"><div><h2>Архив подборок</h2><p>${days.length} ${plural(days.length, "день", "дня", "дней")} · ${state.projects.length} проектов</p></div></div>` +
      (days.length ? `<div class="archive">${days.map((d) => `<a class="day" href="#/day/${d.date}"><h3>${esc(ruDate(d.date))}</h3><p>${d.count} ${plural(d.count, "проект", "проекта", "проектов")}: ${esc((d.names || []).slice(0, 4).map((n) => n.split("/")[1]).join(", "))}${(d.names || []).length > 4 ? "…" : ""}</p></a>`).join("")}</div>` : `<div class="empty">Архив пока пуст</div>`);
  }

  function viewTrend() {
    renderChips([]);
    const t = state.trend?.items || [];
    const top = [...state.projects].filter((p) => (Date.now() - new Date(p.date)) < 8 * 864e5).sort((a, b) => b.stars_per_day - a.stars_per_day).slice(0, 6);
    V.innerHTML = `<div class="sec-head"><div><h2>🔥 Тренд недели</h2><p>Репозитории, созданные за последние 7 дней и быстрее всех собирающие звёзды</p></div></div>` +
      (t.length ? `<div class="trend">${t.map((r, i) => `<div class="trow"><div class="n">${i + 1}</div><img loading="lazy" src="${esc(r.image)}" alt=""><div><h4><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.full_name)}</a></h4><p>${esc(r.description || "Без описания")}</p><p>⭐ ${fmt(r.stars)} · 🔥 +${fmt(r.stars_per_day)}/день${r.language ? " · " + esc(r.language) : ""}${r.featured ? ` · <a href="#/p/${esc(r.full_name)}">есть разбор</a>` : ""}</p></div>
        <button class="btn ghost" data-favraw='${esc(JSON.stringify({ full_name: r.full_name, name: r.full_name.split("/")[1], url: r.url, description: r.description, stars: r.stars, language: r.language, image: r.image }))}'>☆</button></div>`).join("")}</div>` : `<div class="empty">Данные тренда появятся после первой подборки</div>`) +
      (top.length ? `<div class="sec-head" style="margin-top:34px"><div><h2>Лучшее из подборок за неделю</h2><p>С понятным разбором и аудио</p></div></div><div class="grid">${top.map((p) => card(p)).join("")}</div>` : "");
  }

  function viewFav() {
    const list = [...favs.values()];
    V.innerHTML = `<div class="sec-head"><div><h2>★ Избранное</h2><p>Хранится в этом браузере</p></div>${list.length ? `<button class="btn ghost" data-clearfav="1">Очистить</button>` : ""}</div>` +
      (list.length ? grid(list) : (renderChips([]), `<div class="empty">Нажмите «☆ В избранное» на любой карточке, чтобы сохранить проект</div>`));
  }

  function viewProject(name) {
    renderChips([]);
    const p = state.projects.find((x) => x.full_name === name) || favs.get(name);
    if (!p) { V.innerHTML = `<div class="empty">Проект не найден в подборках. <a href="https://github.com/${esc(name)}" target="_blank">Открыть на GitHub</a></div>`; return; }
    const s = p.summary || {};
    V.innerHTML = `<div class="sec-head"><div><h2>${esc(p.full_name)}</h2><p>${p.date ? `Из подборки за <a href="#/day/${p.date}">${p.date}</a>` : ""}</p></div></div>
      <div class="detail"><div>${p.video ? videoBlock(p, true) : ""}<img class="hero-img" src="${esc(p.readme_image || p.image)}" onerror="this.src='${esc(p.image)}'" alt="">
      ${p.readme_image ? `<img class="hero-img" style="margin-top:12px" src="${esc(p.image)}" alt="">` : ""}</div>
      <div class="card"><div class="body">
        ${s.tagline ? `<p class="tag">${esc(s.tagline)}</p>` : ""}
        <div class="meta"><span>⭐ ${fmt(p.stars)}</span>${p.forks != null ? `<span>🍴 ${fmt(p.forks)}</span>` : ""}${p.language ? `<span>● ${esc(p.language)}</span>` : ""}${p.stars_per_day ? `<span class="hot">🔥 +${fmt(p.stars_per_day)}/день</span>` : ""}${p.license ? `<span>${esc(p.license)}</span>` : ""}</div>
        ${p.audio ? `<audio controls preload="none" src="${esc(p.audio)}" style="width:100%"></audio>` : ""}
        ${section("Что это", s.what)}${section("Зачем", s.why)}
        ${(s.features || []).length ? `<div class="s"><b>Что умеет</b><ul>${s.features.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>` : ""}
        ${section("Кому пригодится", s.who)}${howTo(s.how_to_start)}
        ${(p.topics || []).length ? `<div class="meta">${p.topics.map((t) => `<span>#${esc(t)}</span>`).join("")}</div>` : ""}
        <div class="actions"><a class="btn" href="${esc(p.url)}" target="_blank" rel="noopener">Открыть на GitHub ↗</a>
        <button class="btn ghost ${favs.has(p.full_name) ? "on" : ""}" data-fav="${esc(p.full_name)}">${favs.has(p.full_name) ? "★ В избранном" : "☆ В избранное"}</button></div>
      </div></div></div>`;
  }

  function viewLocalSearch(q) {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const hay = (p) => [p.full_name, p.description, p.language, p.category_name, (p.topics || []).join(" "), JSON.stringify(p.summary || {})].join(" ").toLowerCase();
    const list = state.projects.map((p) => ({ p, h: hay(p) })).map(({ p, h }) => ({ p, sc: words.reduce((a, w) => a + (h.includes(w) ? 1 : 0), 0) }))
      .filter((x) => x.sc > 0).sort((a, b) => b.sc - a.sc || b.p.stars - a.p.stars).map((x) => x.p);
    V.innerHTML = `<div class="sec-head"><div><h2>Поиск в подборках: «${esc(q)}»</h2><p>Найдено: ${list.length}</p></div><button class="btn" data-gh="${esc(q)}">Искать по всему GitHub →</button></div>` +
      (list.length ? grid(list) : (renderChips([]), `<div class="empty">В подборках пока нет совпадений. Попробуйте поиск по всему GitHub.</div>`));
  }

  async function viewGithubSearch(q, sort) {
    renderChips([]);
    sort = sort || "stars";
    V.innerHTML = `<div class="loading">Ищу на GitHub «${esc(q)}»…</div>`;
    const fresh = sort === "fresh";
    const query = q + (fresh ? ` created:>${new Date(Date.now() - 90 * 864e5).toISOString().slice(0, 10)}` : "");
    try {
      const r = await fetch(`https://api.github.com/search/repositories?q=${encodeURIComponent(query)}&sort=stars&order=desc&per_page=24`, { headers: { Accept: "application/vnd.github+json" } });
      if (r.status === 403 || r.status === 429) throw new Error("Лимит GitHub для поиска без входа — 10 запросов в минуту. Подождите минуту и попробуйте снова.");
      if (!r.ok) throw new Error("GitHub ответил ошибкой " + r.status);
      const j = await r.json();
      const list = (j.items || []).map((it) => {
        const ex = state.projects.find((p) => p.full_name === it.full_name);
        if (ex) return ex;
        const age = Math.max((Date.now() - new Date(it.created_at)) / 864e5, 1);
        return { full_name: it.full_name, name: it.name, owner: it.owner.login, avatar: it.owner.avatar_url, url: it.html_url, homepage: it.homepage || "", description: it.description || "", stars: it.stargazers_count, language: it.language || "", license: it.license?.spdx_id && it.license.spdx_id !== "NOASSERTION" ? it.license.spdx_id : "", stars_per_day: +(it.stargazers_count / age).toFixed(1), image: `https://opengraph.githubassets.com/1/${it.full_name}`, topics: it.topics || [] };
      });
      V.innerHTML = `<div class="sec-head"><div><h2>GitHub: «${esc(q)}»</h2><p>Найдено ${fmt(j.total_count)} · показаны топ-${list.length} по звёздам${fresh ? " среди созданных за 90 дней" : ""}. Проекты с разбором отмечены разделами «Что это / Зачем».</p></div>
        <div class="actions"><a class="btn ${fresh ? "ghost" : ""}" href="#/search/github/${encodeURIComponent(q)}">Популярные</a><a class="btn ${fresh ? "" : "ghost"}" href="#/search/fresh/${encodeURIComponent(q)}">Свежие (90 дней)</a></div></div>` +
        (list.length ? `<div class="grid">${list.map((p) => card(p)).join("")}</div>` : `<div class="empty">Ничего не найдено. Попробуйте английские слова: например «telegram bot», «video ai».</div>`);
      state.list = list;
    } catch (e) {
      V.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  /* ---------- Услуги Git Hunter Studio (данные и медиа — с сайта Studio) ---------- */
  const STUDIO = "https://avtomaster24bot-lab.github.io/git-hunter-studio/";
  const CONSULT = "https://t.me/Git_Hunter_bot?start=consult";
  let studioCards = null;
  function studioBanner() {
    return `<div class="studio-banner"><span>🤖 Хотите такого же ИИ-помощника для своего бизнеса?</span>
      <a class="btn" href="#/services">Заказать ИИ-ассистента или сайт</a></div>`;
  }
  function studioCard(c) {
    const abs = (u) => (u && !/^https?:/.test(u) ? STUDIO + u : u);
    const sec = (t, x) => (x ? `<div class="s"><b>${t}</b><p>${esc(x)}</p></div>` : "");
    const tail = c.price ? sec("Цена", c.price) : sec("Дальше", c.next);
    const vid = c.video ? `<div class="vwrap"><video class="vplayer" controls playsinline preload="none" poster="${esc(abs(c.poster))}" src="${esc(abs(c.video))}"></video>
      <div class="vbtns"><a class="btn" href="${esc(c.video_release_url || abs(c.video))}" download>⬇ Скачать видео</a>
      <button class="btn ghost" data-scopy="youtube" data-sid="${esc(c.id)}">📋 Текст для YouTube</button>
      <button class="btn ghost" data-scopy="instagram" data-sid="${esc(c.id)}">📋 Для Instagram</button>
      <button class="btn ghost" data-scopy="tiktok" data-sid="${esc(c.id)}">📋 Для TikTok</button></div>
      <small class="vnote">Вертикальное видео 1080×1920${c.video_duration ? ` · ${Math.round(c.video_duration)} с` : ""}</small></div>` : "";
    return `<article class="card">
      <a class="img" href="${STUDIO}#b${c.num}" target="_blank" rel="noopener"><img loading="lazy" src="${esc(abs(c.image))}" alt="${esc(c.title)}">
        <span class="badge">${esc(c.emoji)} ${esc(c.badge)}</span><span class="rank">#${c.num}</span></a>
      <div class="body">
        <div class="title"><div><h3>${esc(c.title)}</h3><small>Git Hunter Studio</small></div></div>
        <p class="tag">${esc(c.tagline)}</p>
        <audio controls preload="none" src="${esc(abs(c.audio))}" style="width:100%"></audio>
        ${sec("Что это", c.what)}${sec("Зачем вам", c.why)}
        <div class="s"><b>Что умеет</b><ul>${(c.features || []).map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>
        ${sec("Для кого", c.who)}${tail}
        ${vid}
        <details class="more"><summary>Текст аудио</summary><p>${esc(c.text)}</p></details>
        <div class="actions"><a class="btn" href="${CONSULT}" target="_blank" rel="noopener">💬 Бесплатная консультация</a>
          <a class="btn ghost" href="${STUDIO}#b${c.num}" target="_blank" rel="noopener">Сайт Studio ↗</a></div>
      </div></article>`;
  }
  async function viewServices() {
    renderChips([]);
    V.innerHTML = `<div class="loading">Загружаю услуги…</div>`;
    try {
      if (!studioCards) studioCards = await getJSON(STUDIO + "data/cards.json");
      V.innerHTML = `<div class="sec-head"><div><h2>🤖 Услуги Git Hunter Studio</h2><p>Внедряем лучшие ИИ-инструменты для вашего бизнеса: личный ИИ-ассистент, сайты с ИИ-консультантом, боты и контент-завод.</p></div>
        <div class="actions"><a class="btn" href="${CONSULT}" target="_blank" rel="noopener">💬 Бесплатная консультация</a><a class="btn ghost" href="${STUDIO}" target="_blank" rel="noopener">Сайт Studio ↗</a></div></div>
        <div class="grid">${studioCards.map(studioCard).join("")}</div>`;
    } catch (e) {
      V.innerHTML = `<div class="empty">Не удалось загрузить услуги. <a href="${STUDIO}" target="_blank" rel="noopener">Открыть сайт Git Hunter Studio</a></div>`;
    }
  }
  document.addEventListener("click", async (e) => {
    const t = e.target.closest("[data-scopy]"); if (!t || !studioCards) return;
    const c = studioCards.find((x) => x.id === t.dataset.sid); if (!c) return;
    const p = c.post || {}, k = t.dataset.scopy;
    await copyText(k === "youtube" ? `${p.youtube_title}\n\n${p.youtube_description}` : p[k] || "");
    toast("Текст скопирован");
  });

  function route() {
    const h = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
    const [a, ...rest] = h.split("/");
    state.view = a || "today";
    setNav({ "": "today", trend: "trend", archive: "archive", fav: "fav", services: "services" }[a || ""] || "");
    if (!a) viewDay();
    else if (a === "day") viewDay(rest[0]);
    else if (a === "archive") viewArchive();
    else if (a === "trend") viewTrend();
    else if (a === "fav") viewFav();
    else if (a === "services") viewServices();
    else if (a === "p") viewProject(rest.join("/"));
    else if (a === "search") {
      const mode = rest[0], q = rest.slice(1).join("/");
      $("#q").value = q;
      const radio = document.querySelector(`input[name=mode][value=${mode === "local" ? "local" : "github"}]`); if (radio) radio.checked = true;
      if (mode === "local") viewLocalSearch(q); else viewGithubSearch(q, mode === "fresh" ? "fresh" : "stars");
    } else viewDay();
    if (a && a !== "search") window.scrollTo({ top: $("main").offsetTop - 70, behavior: "smooth" });
  }

  /* ---------- плеер ---------- */
  const audio = $("#plAudio");
  function play(list, idx) {
    state.playlist = list; state.plIdx = idx;
    const p = list[idx]; if (!p) return;
    $("#player").classList.remove("hidden");
    $("#plTitle").textContent = p.name; $("#plSub").textContent = (p.summary?.tagline || p.description || "");
    audio.src = p.audio; audio.play().catch(() => {});
  }
  audio.addEventListener("ended", () => { if (state.plIdx + 1 < state.playlist.length) play(state.playlist, state.plIdx + 1); });
  $("#plNext").onclick = () => play(state.playlist, Math.min(state.plIdx + 1, state.playlist.length - 1));
  $("#plPrev").onclick = () => play(state.playlist, Math.max(state.plIdx - 1, 0));
  $("#plClose").onclick = () => { audio.pause(); $("#player").classList.add("hidden"); };

  /* ---------- события ---------- */
  document.addEventListener("click", async (e) => {
    const t = e.target.closest("button,[data-q]"); if (!t) return;
    const d = t.dataset;
    if (d.cat !== undefined) { state.cat = d.cat; route(); }
    else if (d.play) { const list = filtered(state.list).filter((p) => p.audio); play(list, list.findIndex((p) => p.full_name === d.play)); }
    else if (d.playall) { const list = filtered(state.list).filter((p) => p.audio); play(list, 0); }
    else if (d.fav) {
      const p = state.list.find((x) => x.full_name === d.fav) || state.projects.find((x) => x.full_name === d.fav) || favs.get(d.fav);
      if (favs.has(d.fav)) { favs.delete(d.fav); toast("Убрано из избранного"); } else if (p) { favs.set(d.fav, p); toast("Добавлено в избранное ★"); }
      saveFavs(); const y = scrollY; route(); scrollTo(0, y);
    } else if (d.favraw) { const p = JSON.parse(d.favraw); favs.set(p.full_name, p); saveFavs(); toast("Добавлено в избранное ★"); }
    else if (d.clearfav) { if (confirm("Очистить избранное?")) { favs.clear(); saveFavs(); route(); } }
    else if (d.copy) {
      const p = state.list.find((x) => x.full_name === d.name) || state.projects.find((x) => x.full_name === d.name);
      if (p) { await copyText(postText(p, d.copy)); toast({ youtube: "Название и описание для YouTube скопированы", instagram: "Подпись для Instagram скопирована", tiktok: "Подпись для TikTok скопирована" }[d.copy]); }
    } else if (d.share) {
      const url = location.origin + location.pathname + "#/p/" + d.share;
      if (navigator.share) navigator.share({ title: d.share, url }).catch(() => {}); else { await navigator.clipboard?.writeText(url); toast("Ссылка скопирована"); }
    } else if (d.gh) location.hash = "#/search/github/" + encodeURIComponent(d.gh);
    else if (d.q) { $("#q").value = d.q; $("#searchForm").requestSubmit(); }
  });
  $("#langSel").onchange = (e) => { state.lang = e.target.value; route(); };
  $("#searchForm").onsubmit = (e) => {
    e.preventDefault();
    const q = $("#q").value.trim(); if (!q) return;
    const mode = document.querySelector("input[name=mode]:checked").value;
    location.hash = `#/search/${mode}/${encodeURIComponent(q)}`;
  };
  window.addEventListener("hashchange", route);
  load();
})();
