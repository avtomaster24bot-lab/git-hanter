# Автопубликация видео в YouTube, Instagram и TikTok

Каждый день Git Hunter делает для каждого проекта вертикальное видео 1080×1920 (до 60 с) и готовые тексты постов.
Видео можно скачивать с сайта вручную (кнопки «Скачать видео» и «Скопировать текст…»), а можно включить автопубликацию.

**Как это устроено.** В workflow «Ежедневная подборка» есть задача `publish`. Она запускается после деплоя сайта
по расписанию (каждый день в 08:00 по Алматы) или вручную с галочкой «Опубликовать в YouTube / Instagram / TikTok».
Каждая платформа включается **только если заданы её секреты**. Если секретов нет, шаг просто пропускается.
Опубликованное записывается в `data/published.json`, повторно ничего не загружается.

Секреты добавляются здесь: **репозиторий → Settings → Secrets and variables → Actions → New repository secret**.
Необязательные настройки (приватность и т.п.) задаются на соседней вкладке **Variables**.

Дневные лимиты задаются в `topics.json` → `autopublish`.

---

## 1. YouTube Shorts

Нужны 3 секрета: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`.

1. Откройте https://console.cloud.google.com/ и создайте проект (например, `git-hunter`).
2. **APIs & Services → Library**: найдите **YouTube Data API v3** и нажмите **Enable**.
3. **APIs & Services → OAuth consent screen** (Google Auth Platform):
   - тип **External**, название приложения, ваша почта;
   - **Data access / Scopes**: добавьте `https://www.googleapis.com/auth/youtube.upload`;
   - **Audience → Test users**: добавьте свой Google-аккаунт;
   - **Важно:** нажмите **Publish app** (статус *In production*). В режиме *Testing* refresh token
     перестаёт работать через 7 дней. Предупреждение «приложение не проверено» для личного использования не мешает.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - тип **Web application**;
   - в **Authorized redirect URIs** добавьте `https://developers.google.com/oauthplayground`;
   - сохраните **Client ID** и **Client secret**.
5. Откройте https://developers.google.com/oauthplayground:
   - шестерёнка справа вверху → **Use your own OAuth credentials** → вставьте Client ID и Client secret;
   - слева в поле *Input your own scopes* введите `https://www.googleapis.com/auth/youtube.upload` → **Authorize APIs**;
   - войдите в Google-аккаунт **и выберите нужный YouTube-канал**, подтвердите доступ
     (на экране «не проверено» нажмите «Дополнительно → Перейти»);
   - **Step 2 → Exchange authorization code for tokens** → скопируйте **Refresh token**.
6. Добавьте секреты `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`.

Ограничения YouTube, о которых нужно знать:
- **Квота**: 10 000 единиц в сутки, одна загрузка стоит ~1 600, то есть **максимум 6 видео в день**.
  Поэтому по умолчанию `youtube_max_per_day: 5`.
- **Непроверенные проекты.** Видео, загруженные через API из проекта, который не прошёл аудит Google,
  YouTube **автоматически делает приватными**. Чтобы видео выходили публично, подайте заявку
  *YouTube API Services — Audit and Quota Extension Form*: https://support.google.com/youtube/contact/yt_api_form
  До одобрения можно поставить переменную `YOUTUBE_PRIVACY=private` и публиковать вручную в YouTube Studio
  (видео уже загружены, с названием и описанием).
- Видео вертикальное, короче 60 с и с `#shorts` в названии, поэтому YouTube сам относит его к Shorts.

---

## 2. Instagram Reels

Нужны 2 секрета: `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`.

Требования: аккаунт Instagram должен быть **профессиональным** (Business или Creator).
Видео должно лежать по публичной ссылке. Это уже так: видео лежат на GitHub Pages.

### Вариант А (рекомендуется): через Facebook-страницу, вечный токен
1. В Instagram: **Настройки → Тип аккаунта и инструменты → Переключиться на профессиональный аккаунт**.
2. Привяжите Instagram к **Facebook-странице** (создайте страницу, если её нет):
   Facebook → ваша страница → **Настройки → Связанные аккаунты → Instagram**.
3. https://developers.facebook.com/apps → **Create app**: тип/use case **Other → Business**.
   В приложение добавьте продукт **Instagram** (*API setup with Facebook login*).
4. https://business.facebook.com/settings → **Пользователи → Системные пользователи → Добавить**
   (роль *Admin*). Затем **Назначить ресурсы**: ваше приложение, Facebook-страница и Instagram-аккаунт (полный доступ).
5. У системного пользователя нажмите **Сгенерировать токен**: выберите приложение, срок **Никогда**,
   разрешения `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`,
   `business_management`. Это и есть **`INSTAGRAM_ACCESS_TOKEN`**.
6. Узнайте ID Instagram-аккаунта в https://developers.facebook.com/tools/explorer (с этим токеном):
   - `GET me/accounts` → возьмите `id` вашей страницы;
   - `GET <id_страницы>?fields=instagram_business_account` → значение `instagram_business_account.id`
     и есть **`INSTAGRAM_USER_ID`** (число вида `1784…`).
7. Добавьте оба секрета.

Если системного пользователя создать нельзя, токен можно получить в Graph API Explorer
(*Get User Access Token* с теми же разрешениями) и продлить в https://developers.facebook.com/tools/debug/accesstoken
кнопкой **Extend Access Token**. Но такой токен живёт **60 дней**, потом его надо обновлять.

### Вариант Б: Instagram API с входом через Instagram (без Facebook-страницы)
В приложении выберите *API setup with Instagram login*, добавьте свой аккаунт, сгенерируйте токен
с разрешениями `instagram_business_basic` и `instagram_business_content_publish`. ID аккаунта показан там же.
Добавьте переменную `INSTAGRAM_LOGIN_API=1`. Токен живёт 60 дней.

Ограничения: до ~50 публикаций через API за 24 часа. Пока приложение в режиме разработки,
публиковать можно только в аккаунты людей, у которых есть роль в приложении, то есть в ваш. Для своего аккаунта этого достаточно.

---

## 3. TikTok

Нужны 3 секрета: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`.

> ⚠️ Пока приложение **не прошло аудит TikTok**, все видео публикуются как **приватные** (видны только вам).
> Это правило TikTok. После одобрения аудита задайте переменную `TIKTOK_PRIVACY=PUBLIC_TO_EVERYONE`.

1. Зарегистрируйтесь на https://developers.tiktok.com/ → **Manage apps → Connect an app** (или *Create app*).
2. Заполните карточку приложения:
   - иконка, название (например, Git Hunter), категория, описание;
   - **Terms of Service URL**: `https://avtomaster24bot-lab.github.io/git-hanter/terms.html`
   - **Privacy Policy URL**: `https://avtomaster24bot-lab.github.io/git-hanter/privacy.html`
   - платформа **Web**, сайт `https://avtomaster24bot-lab.github.io/git-hanter/`.
3. **Add products**: **Login Kit** и **Content Posting API** (включите *Direct Post*).
   Scopes: `user.info.basic`, `video.publish`, `video.upload`.
4. В Login Kit укажите **Redirect URI**: `https://avtomaster24bot-lab.github.io/git-hanter/tiktok-callback.html`
5. Сохраните **Client key** и **Client secret**. Для теста можно использовать **Sandbox** (добавьте себя как target user)
   либо отправить приложение на **Submit for review**.
6. Получите код авторизации. Откройте в браузере (подставьте свой client key):
   ```
   https://www.tiktok.com/v2/auth/authorize/?client_key=ВАШ_CLIENT_KEY&scope=user.info.basic,video.publish,video.upload&response_type=code&redirect_uri=https%3A%2F%2Favtomaster24bot-lab.github.io%2Fgit-hanter%2Ftiktok-callback.html&state=githunter
   ```
   Войдите в TikTok и разрешите доступ. Страница `tiktok-callback.html` покажет **code**. Его нужно использовать в течение нескольких минут.
7. Обменяйте code на токены (в терминале):
   ```bash
   curl -X POST https://open.tiktokapis.com/v2/oauth/token/ \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "client_key=ВАШ_CLIENT_KEY" -d "client_secret=ВАШ_CLIENT_SECRET" \
     -d "code=КОД_ИЗ_ШАГА_6" -d "grant_type=authorization_code" \
     -d "redirect_uri=https://avtomaster24bot-lab.github.io/git-hanter/tiktok-callback.html"
   ```
   Из ответа возьмите `refresh_token`. Он живёт 365 дней, а access token скрипт обновляет сам.
8. Добавьте секреты `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`.

Ограничения: непроверенные приложения публикуют только приватно, и не больше 5 авторов в сутки.
У самого TikTok есть лимит постов в день на аккаунт, поэтому по умолчанию `tiktok_max_per_day: 5`.

---

## Проверка

Actions → **Ежедневная подборка** → **Run workflow** → отметьте **«Опубликовать в YouTube / Instagram / TikTok»**
(и «Не отправлять в Telegram», если не нужно дублировать). Результат с ссылками будет в Summary запуска,
а журнал в `data/published.json`.

## Ручная публикация (без API)

На сайте у каждого проекта есть блок «🎬 Видео для Shorts / Reels / TikTok»:
**Скачать видео**, **Текст для YouTube** (название + описание), **Для Instagram**, **Для TikTok** (подпись с хэштегами).
