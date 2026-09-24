# Развёртывание — Блок 4 плана доработки

Файлы в этой папке закрывают все 5 пунктов Блока 4: Caddy, автозапуск
через nssm, закрепление адреса сервера, бэкап, `.env`. Ничего в самом
приложении (backend/frontend) эти файлы не меняют — это чисто
инфраструктура вокруг уже готового кода.

**Зависимость:** делайте это после Блока 1 (авторизация) — иначе
получите сервер, доступный всей локальной сети без логина, как и
написано в исходном плане.

## 0. Разметка папок (пример — поправьте под себя)

Все скрипты в этой папке по умолчанию считают, что на сервере так:

```
C:\lesovod\
  backend\          ← код backend (эта репа/архив, папка backend\)
    venv\           ← создаётся один раз (см. п.1)
  frontend\dist\    ← результат `npm run build` (см. п.1)
  deploy\           ← эта папка целиком (Caddyfile, .bat, .env)
  caddy\caddy.exe
  nssm\nssm.exe
  data\             ← LESOVOD_APP_DIR / LESOVOD_STORAGE_DIR (см. .env)
  logs\             ← создаётся install_service.bat сам
  backups\          ← создаётся backup_lesovod.bat сам
  backups-secrets\  ← создаётся backup_lesovod.bat сам, права — только админу
```

Если раскладка другая — путей всего четыре места, где их надо
поправить: `Caddyfile` (root), `run_server.bat` (`BACKEND_DIR`),
`install_service.bat` (`NSSM`), `backup_lesovod.bat` (`BACKUP_DIR`,
`SECRETS_BACKUP_DIR`). Остальное (пути к БД/шаблонам/storage) — только
в `.env`, один раз.

## 1. Первичная установка (руками, один раз)

```bat
cd C:\lesovod\backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt

cd C:\lesovod\frontend
npm install
npm run build
REM результат — frontend\dist\, именно на него смотрит Caddyfile
```

Скопируйте `.env.example` → `.env` в этой папке (`deploy\.env`) и
заполните пути под реальный сервер — см. комментарии в самом файле.
`deploy\.env` (заполненный) — не кладите в git/архив, который
расшариваете; `.env.example` — можно.

## 2. Backend как служба Windows (nssm)

1. Скачайте nssm: https://nssm.cc/download, распакуйте в `C:\lesovod\nssm\`.
2. От администратора: `deploy\install_service.bat`.
3. `net start LesovodBackend`, проверить: `curl http://localhost:8000/api/health`
   должен ответить `{"status":"ok"}`.
4. Логи — `C:\lesovod\logs\backend.out.log` / `backend.err.log`.

## 3. Caddy (раздача фронтенда + прокси /api)

1. Скачайте Caddy: https://caddyserver.com/download (Windows amd64,
   один exe-файл), положите в `C:\lesovod\caddy\caddy.exe`.
2. Проверка вручную: `C:\lesovod\caddy\caddy.exe run --config C:\lesovod\deploy\Caddyfile`,
   открыть `http://localhost` — должен открыться фронтенд, а не 404/пустая
   страница.
3. Постоянный запуск — тем же nssm, вторая служба:
   ```bat
   C:\lesovod\nssm\nssm.exe install LesovodCaddy C:\lesovod\caddy\caddy.exe "run --config C:\lesovod\deploy\Caddyfile"
   C:\lesovod\nssm\nssm.exe set LesovodCaddy AppDirectory C:\lesovod\caddy
   C:\lesovod\nssm\nssm.exe set LesovodCaddy Start SERVICE_AUTO_START
   C:\lesovod\nssm\nssm.exe set LesovodCaddy AppExit Default Restart
   net start LesovodCaddy
   ```
4. Порт 80 занят чем-то другим (частая причина — IIS/Skype/другой
   веб-сервер)? Либо освободите его, либо смените адрес в `Caddyfile`
   на `lesovod.local:8080` и учтите порт при обращении с клиентов.

## 4. Локальный адрес сервера (IP или `lesovod.local`)

Два независимых варианта, можно оба сразу (mDNS — как удобный алиас
поверх зафиксированного IP, а не вместо него):

**А. Закрепить IP в роутере (надёжный вариант, работает всегда).**
В веб-интерфейсе роутера — DHCP reservation / статическая аренда по
MAC-адресу сервера. После этого сервер всегда получает один и тот же
IP при перезагрузке роутера. Раздайте пользователям этот IP
(`http://192.168.X.Y`) — самый простой рабочий вариант, если не нужно
красивое имя.

**Б. `lesovod.local` через mDNS (удобнее, но менее предсказуемо).**
На сервере нужен mDNS-responder, объявляющий имя `lesovod.local` в
сеть — в Windows он не встроен по умолчанию. Практический вариант:
установить **Bonjour Print Services** (бесплатный маленький установщик
от Apple, ищется на support.apple.com — не Bonjour из iTunes целиком,
именно "Print Services", он же ставит службу `Bonjour Service`,
которая и отвечает на mDNS-запросы).

Важная оговорка: клиентские Windows-машины разрешают `.local`-имена
через mDNS не всегда одинаково надёжно (зависит от версии Windows и
того, стоит ли на них тоже Bonjour/iTunes). Если после установки
Bonjour на сервере `http://lesovod.local` не открывается с какого-то
конкретного компьютера — рабочий обход: на этом компьютере в
`C:\Windows\System32\drivers\etc\hosts` добавить строку
`192.168.X.Y  lesovod.local` (тот же IP, что закреплён в пункте А).
То есть вариант А — обязательная основа, вариант Б — надстройка,
которая может не завестись на части клиентов без ручного вмешательства.

## 5. Ежедневный бэкап

```bat
schtasks /create /tn "LesovodBackup" /tr "C:\lesovod\deploy\backup_lesovod.bat" /sc daily /st 23:30 /ru SYSTEM
```

Что делает `backup_lesovod.bat` — см. комментарии в самом файле:
консистентный снимок SQLite (через `sqlite3.Connection.backup()`, не
голое копирование файла — важно из-за WAL-режима), копия
`storage\` (документы/абрисы) в `C:\lesovod\backups\<дата>\`,
`secrets.json` — **отдельно**, в `C:\lesovod\backups-secrets\`
(ограничьте NTFS-права на эту папку только администратору — там ключи
API/токен бота открытым текстом). Хранится 14 дней, старое чистится
автоматически.

Проверьте один раз руками, что бэкап реально восстанавливается —
скрипт, который ни разу не пробовали разворачивать обратно, не бэкап,
а иллюзия бэкапа.

## 6. Чек-лист перед тем, как пускать реальных пользователей

- [ ] Блок 1 (авторизация) закрыт, пароль `admin` сменён (форма в
      `Settings.jsx`, см. основной план, Блок 1 п.6) — иначе весь
      остальной Блок 4 бессмысленен, сервер будет открыт всем.
- [ ] `LESOVOD_DB_PATH` в `.env` указывает на настоящую заполненную
      базу, если она есть, а не на пустышку, которую backend создаст
      сам при первом запуске.
- [ ] `frontend\dist` собран с актуальным кодом (`npm run build`) —
      Caddy отдаёт именно эту папку, а не dev-сервер.
- [ ] `LesovodBackend` и `LesovodCaddy` в списке служб Windows
      (`services.msc`) — обе `Running`, обе `Automatic`.
- [ ] Тестовый бэкап (п.5) сделан и открыт вручную — файл базы не 0 байт.
- [ ] `CORSMiddleware(allow_origins=["*"])` в `backend/app/main.py` —
      комментарий в самом файле уже предупреждает сузить список
      источников перед продакшеном. Раз Caddy теперь отдаёт фронтенд и
      проксирует API с одного и того же адреса (см. `Caddyfile`) —
      запросы идут same-origin, и `*` здесь уже не даёт постороннему
      сайту ничего лишнего исключительно за счёт этого. Сознательно не
      трогали в рамках Блока 4 — это Блок 5 или отдельное решение,
      сюда просто фиксируем факт, что оставили как есть.

## 7. Токены телеграм-бота (Этап 4, Блок 3/часть 2)

Два отдельных значения в `.env` — не перепутайте, назначение разное:

| Переменная | Для чего | Откуда взять |
|---|---|---|
| `LESOVOD_TELEGRAM_BOT_TOKEN` | бот говорит с Telegram | `@BotFather` в Telegram, команда `/newbot` (или `/token` для уже созданного бота) |
| `LESOVOD_BOT_SERVICE_TOKEN` | бот говорит с ЭТИМ backend'ом (`Authorization: Bearer ...`, роль `bot`) | генерируете сами один раз: `python -c "import secrets; print(secrets.token_hex(32))"` |

Если `LESOVOD_BOT_SERVICE_TOKEN` не задан — все будущие эндпоинты
`/api/bot/...` (Блок 3/часть 3) остаются недоступны в принципе, для
любого токена, а не "открыты по умолчанию" — это осознанное
fail-safe-поведение (см. `config.get_bot_service_token()`), не баг.

Сам процесс бота (`telegram_bot.py`) на данном этапе (часть 2 из 4)
ещё НЕ читает `LESOVOD_BOT_SERVICE_TOKEN` и не шлёт его backend'у —
это часть 3 плана (замена прямых импортов на HTTP-вызовы). Пока что
эта переменная только даёт backend'у *способность* узнать бота по
токену; сам бот пока обращается к базе напрямую, как и раньше.

`backup_lesovod.bat` теперь бэкапит `.env` в ту же защищённую папку
`backups-secrets\`, что и `secrets.json` (см. раздел 5) — оба значения
из этого раздела попадут туда же.

## 8. Проверка обновлений мобильного приложения (Android, сайдлоуд)

Мобильное приложение при запуске тихо запрашивает `GET /app/version.json`
и сравнивает `version_code` со своим `BuildConfig.VERSION_CODE`. Это
обычная статика — Caddy отдаёт её тем же `file_server`, что и весь
остальной фронтенд (см. `handle {}` в `Caddyfile`), отдельный
backend-эндпоинт под это не заводили. Источник файла в репозитории —
`frontend/public/app/version.json`, `npm run build` копирует его в
`frontend/dist/app/version.json`, как и остальные файлы `public/`
(см. `frontend/public/vendor/`, `abris_tool.html` — та же схема).

При каждом релизе мобильного приложения (после того как в
`LesovodMobile/app/build.gradle.kts` подняли `versionCode`):

1. Соберите подписанный релизный APK (не debug-сборку из CI).
2. Положите его на сервер как
   `C:\lesovod\frontend\dist\app\lesovod-latest.apk` — рядом с
   `version.json`, имя файла должно совпадать с `apk_url` внутри него.
   Сам APK **не кладите в git** — большой бинарник, меняется каждый
   релиз; копируете вручную на сервер, как и весь `frontend\dist`.
3. Поднимите `version_code` в `frontend/public/app/version.json` до
   значения нового `versionCode` и либо пересоберите фронтенд
   (`npm run build`), либо, раз это всего один файл, просто перезапишите
   его прямо в `C:\lesovod\frontend\dist\app\version.json` — рестарт
   служб не нужен, Caddy отдаёт изменения сразу. Если правили на
   сервере напрямую — перенесите то же значение и в
   `frontend/public/app/version.json` в репозитории, чтобы следующая
   пересборка фронтенда не откатила `version_code` назад.

Формат файла:
```json
{
  "version_code": 2,
  "apk_url": "https://lesovodapipom.store/app/lesovod-latest.apk"
}
```

Если сервер недоступен или отдал не-200/битый JSON — мобильное
приложение должно тихо считать, что обновления нет, и не мешать
работе (это уже требование к клиенту, не к серверу — здесь просто
фиксируем, что сервер не гарантирует и не обязан ничего, кроме отдачи
статического файла).
