# BuildVision

**BuildVision** (бывший «СтройКонтроль») — AI-контроль стройплощадки:
 снимок + зона + дата → обнаруженная строительная техника → сопоставление
с этапом графика (Plan vs Fact по количеству) → объяснимое предупреждение
с доказательствами. Поверх этого сквозного сценария построены 6 модулей:
**Dashboard**, **AI Camera** (анализ снимков), **Календарный план и Карта**,
**AI Learning** (обучение на коррекциях инженера), **Прогноз сроков** и
**Мобильное приложение** — плюс сквозная **авторизация с двумя ролями**
(Администратор/Участник проекта).

Сделано для хакатона Департамента градостроительной политики города
Москвы. Полная методика, обоснование решений и ограничения — в плане
проекта и в `docs/`.

## Что уже работает

* Обнаружение техники на снимке (YOLO-World v2, zero-shot, CPU).
* **Количественные правила (Plan vs Fact)**: сопоставление обнаруженной техники с
  этапами демонстрационного графика по числу, не только по факту наличия класса
  (например, котлован: экскаватор ×1, самосвал ×3).
* **PostgreSQL + Django admin**: все справочники (словарь классов, правила,
  график, зоны, камеры, погодные пороги, пользователи и роли) хранятся в Postgres
  и редактируются через веб-админку Django без перезапуска сервиса. Результаты каждого
  анализа (Observation/Detection/StageEvaluationRecord) тоже сохраняются в БД и видны в админке.
* **Авторизация и роли**: вход через сессию Django (та же БД, что и admin), две
  роли — **Администратор** и **Участник проекта**. Общедоступных паролей нет.
  При первом создании аккаунтов используются `DJANGO_SUPERUSER_PASSWORD` и
  `SK_PARTICIPANT_PASSWORD` из защищённого окружения. Без заданного пароля новый
  участник не может войти. Повторный запуск не сбрасывает существующие пароли.
* **AI Learning**: лёгкий классификатор-корректор (CLIP-эмбеддинги + логистическая
  регрессия), обучаемый на коррекциях инженера по неоднозначным/низкоуверенным
  детекциям. В датасете нет размеченного held-out набора, поэтому метрики качества
  честно измеряются train/test-разбиением внутри самих накопленных коррекций, а не
  выдумываются; кандидат становится рабочей версией только вручную через Центр
  обучения AI.
* **Прогноз сроков**: расчётный движок на реальных данных (темп по истории наблюдений,
  погода на реальном горизонте Open-Meteo ~72ч), без ML-предсказания.
* Три статуса проверки: «Отклонений не выявлено», «Возможное отклонение»,
  «Недостаточно данных» — с объяснением на русском и честной обработкой
  известных ограничений классификации.
* Погодные риски на 72 часа (Open-Meteo), пересечённые с этапами графика.
* **Веб-интерфейс** (тёмная тема, React + TypeScript): Главная, Камеры, Камера —
  AI-анализ, Карта, Календарный план, Прогноз, Центр обучения AI, Аналитика,
  Уведомления, Настройки (ролевая).
* **Проекты**: после входа открывается список доступных проектов (`/projects`) вместо единственной
  площадки; администратор видит все проекты и может создавать новые (`/projects/new`) с назначением
  участников, участник — только свои назначенные. Все разделы внутри проекта строго ограничены
  `/api/projects/{project_id}/...` (веб и Android). Старый установленный APK продолжает работать через
  совместимые legacy `/api/...` маршруты, закреплённые за одним проектом через `ConstructionSite.is_legacy`
  (устанавливается однократно миграцией `core/migrations/0005_projects_and_membership.py`). Новый экран
  проектов требует новой сборки APK. Карточка проекта показывает фото с камеры площадки (или мини-карту,
  если камеры ещё нет), прогресс текущего этапа и краткую статистику (снимки, открытые отклонения).
* **ИИ-ассистент проекта**: плавающий чат внутри экрана проекта, отвечающий только на вопросы по
  данным этого проекта (этап, техника, сроки, отклонения) — системный промпт жёстко ограничивает
  модель предоставленным срезом фактов и отказывает на посторонние темы или попытки переопределить
  правила через сообщение пользователя.

Если Postgres временно недоступен, backend автоматически откатывается на
резервную файловую конфигурацию в `data/config/` (обнаружение снимков продолжает
работать, но без сохранения истории и без правок, внесённых через админку после
последнего успешного сида). Модули, у которых нет файлового отката (Dashboard,
Камеры, Аналитика, Уведомления, AI Learning, Прогноз) честно показывают пустые/нулевые
значения (флаг `available: false`), а не выдуманные данные.

Известные ограничения качества детектора задокументированы в
[`docs/detector_quality_report.md`](docs/detector_quality_report.md) —
рекомендуем прочитать перед демонстрацией.

## Структура репозитория

```
backend/          FastAPI-приложение, ядро сопоставления, детектор
  app/            ...и чтение/запись в Postgres через Django ORM (django_bridge.py, persistence.py)
  tests/
admin_panel/      Настройки Django-проекта (settings.py, urls.py)
core/             Django-модели + admin.py + management-команда seed_demo_data
manage.py         Точка входа Django (migrate/createsuperuser/seed_demo_data/runserver)
frontend/         React + TypeScript + Vite интерфейс (8 экранов, сессионная авторизация)
mobile/           Capacitor-обёртка веб-кода для RuStore (см. mobile/README.md)
data/
  config/         Исходные YAML/JSON/GeoJSON — теперь только для сида БД и файлового отката
  raw/images/     Исходные снимки (не в git, см. .gitignore)
  uploads/        Загруженные снимки и обрезки коррекций (не в git)
  runs/           Результаты baseline-прогонов и визуализации (не в git)
scripts/          Инвентаризация, baseline-детекция, разбор Excel, seed_demo_history.py, train_correction_classifier.py
docs/             Отчёт о качестве детектора, документация, презентация
models/           Веса YOLO-World (.pt) + артефакты классификатора-корректора (не в git — см. ниже)
weights/clip/     Веса CLIP-энкодера (не в git — см. ниже)
Dockerfile        Основной образ (FastAPI + модель + фронтенд)
Dockerfile.admin  Лёгкий образ для Django admin (без ML-зависимостей)
docker-compose.yml  db (Postgres) + app (FastAPI, :8000) + admin (Django, :8001)
```

## Быстрый старт (Windows, локально)

Требуется Python 3.13, Node.js 22+, Docker (только для PostgreSQL).

### 1. PostgreSQL

```powershell
docker compose up -d db
```

Использует официальный образ `postgres:16-alpine`, никакой сборки не требуется.

### 2. Django admin (справочники + история анализа)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r admin_panel\requirements.txt
$env:DATABASE_URL = "postgres://stroykontrol:stroykontrol@localhost:5432/stroykontrol"
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py seed_demo_data   # заполняет БД из data/config/*
.venv\Scripts\python manage.py createsuperuser
.venv\Scripts\python manage.py runserver 8001
```

Админка: `http://localhost:8001/admin/`.

> **Известное ограничение среды:** на машине разработки прямое подключение
> с Windows к Postgres/HTTP через проброшенные порты Docker Desktop (127.0.0.1) было
> нестабильным (TCP-соединение устанавливается, но данные приложения повреждаются).
> Внутри контейнеров (`docker compose exec ...`) всё работает корректно —
> это подтверждено (`scripts/verify_db_persistence.py`). Если команды выше не
> подключаются и у вас та же проблема, перезапустите Docker Desktop/WSL2 либо
> работайте через `docker compose up` целиком (см. ниже, раздел Docker).

### 3. Backend (FastAPI)

```powershell
cd backend
python -m venv ..\.venv
..\.venv\Scripts\pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu
..\.venv\Scripts\pip install -r requirements.txt
cd ..
$env:DATABASE_URL = "postgres://stroykontrol:stroykontrol@localhost:5432/stroykontrol"
.\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --port 8000
```

Пакет `clip` (текстовый энкодер для YOLO-World) ставится из git-репозитория
`ultralytics/CLIP` — указан в `backend/requirements.txt`, для установки нужен
доступный `git`. При первом запуске `ultralytics` скачает веса YOLO-World v2
small (~25 МБ) в `models/`, а сам CLIP — веса ViT-B/32 (~340 МБ) в
`%USERPROFILE%\.cache\clip\` (если не положены заранее в `weights/clip/`).
Если Postgres недоступен (см. ограничение выше), backend автоматически
откатывается на `data/config/*`.

Проверка: `http://localhost:8000/api/health`.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Откройте `http://localhost:5173`. По умолчанию клиент использует `/api` и `/admin/`
своего origin: Vite перенаправляет их на локальные порты 8000/8001, а production
nginx — на контейнеры. При необходимости адреса задаются `VITE_API_BASE_URL` и
`VITE_ADMIN_URL` (см. `frontend/.env.example`); секреты в VITE-переменные не помещать.

### Тесты и линтеры

```powershell
.\.venv\Scripts\python -m pytest backend\tests -v
.\.venv\Scripts\python -m ruff check backend scripts core admin_panel manage.py

cd frontend
npx tsc -b
npm run lint
npm run build

cd ..\mobile
npx tsc -b
npm run lint
npm run build
```

Тесты не требуют живого Postgres — при недоступной БД автоматически
используется файловый откат. `backend\tests\test_auth_integration.py` и
`backend\tests\test_project_isolation_integration.py` запускают реальный Django ORM/сессии
в изолированном subprocess (`manage.py test --settings=admin_panel.test_settings`, SQLite
в памяти) — никогда не касаются production Postgres. Второй покрывает изоляцию проектов:
два проекта, участников одного/чужого проекта, чужие зоны/наблюдения, права создания,
пустой новый проект без demo-данных и legacy-совместимость. Файлы `backend\tests\test_end_to_end.py` и
`backend\tests\test_learning.py` требуют отдельной осторожности: они переопределяют авторизацию
глобально и могут обратиться к реальной БД/файлам, если `DJANGO_SETTINGS_MODULE`/`DATABASE_URL` в окружении
указывают на неё; запускайте их только без живого Postgres (тогда срабатывает честный файловый откат),
либо не запускайте вовсе вместе с остальными тестами.

## Docker (db + app + admin)

Скопируйте `.env.example` в `.env` и заполните значения (пароли, `DJANGO_SECRET_KEY`,
домены) перед первым запуском — `docker compose` автоматически подхватывает `.env`
из корневой директории.

```bash
docker compose up --build
```

* `http://localhost:8000` — FastAPI (API + собранный фронтенд).
* `http://localhost:8001/admin/` — Django admin. При старте применяются миграции,
  создаются только недостающие аккаунты и собирается статика. Настройки входа —
  `DJANGO_SUPERUSER_USERNAME`/`DJANGO_SUPERUSER_PASSWORD` и `SK_PARTICIPANT_PASSWORD`;
  пароля по умолчанию нет. Существующие пароли и рабочие справочники не перезаписываются.

На чистой БД демонстрационные справочники заполняются отдельно:
`docker compose exec admin python manage.py seed_demo_data`.
На рабочей БД эту команду без `--users-only` не следует выполнять при каждом обновлении.
Смена существующего пароля выполняется через Django admin или `manage.py changepassword`;
изменение bootstrap-переменной само по себе пароль не сбрасывает.

Изменяющие запросы `/api/*` требуют заголовок `X-BuildVision-Request: 1`.
Веб и мобильный клиент добавляют его автоматически; HTTP-клиенты и интеграционные
скрипты должны отправлять явно. Сервер отклоняет недоверенный Origin, а сессия
проверяется по штатному Django auth hash и отзывается после смены пароля.

`app` и `admin` собираются из разных Dockerfile: `admin` — лёгкий образ без
ML-зависимостей (`Dockerfile.admin`), `app` — полный образ с torch/ultralytics/фронтендом
(`Dockerfile`). Оба копируют одини те же `admin_panel/`+`core/` — общая схема БД.

Образ `app` также копирует локально подготовленные веса модели (`models/`) и
CLIP-энкодера (`weights/clip/ViT-B-32.pt`), чтобы не тянуть их из сети при
первом запуске контейнера — см. `docs/PROJECT_DOCUMENTATION.md`, раздел
«Происхождение весов».

**Проверено:** оба образа (`app` и `admin`) успешно собираются и запускаются —
подтверждено на продакшн VPS (`docker compose up -d`): миграции, сид,
сохранение и чтение анализа снимков через API и Django admin работают
сквозным образом. На машине разработки (Windows) полная сборка `app`
(≈1–2 ГБ с torch/ultralytics) не проверялась из-за нехватки места на
системном диске — используйте раздел «Продакшн-развёртывание (VPS)» ниже как
референс по сборке на Linux.

## Разработческие скрипты

* `scripts/inventory.py` — инвентаризация снимков, разбиение на dev/val/holdout.
* `scripts/parse_works_catalog.py` — разбор справочника видов работ из Excel.
* `scripts/baseline_detect.py` — прогон детектора с визуализацией и метриками.
* `scripts/date_stamp_contact_sheet.py` — контрольный лист для аудита штампов даты.
* `scripts/seed_demo_history.py` — заполняет историю наблюдений реальными детекциями с синтетически распределённой
  во времени меткой (запускается внутри контейнера после деплоя).
* `scripts/train_correction_classifier.py` — обучает классификатор-корректор на CLIP-эмбеддингах накопленных
  коррекций (запускается автоматически через «Центр обучения AI» — Кнопка «Запустить обучение»).
* `scripts/generate_presentation.py` — генерация `docs/presentation.pptx` (требует `python-pptx`).

## Данные, помеченные как демонстрационные

Координаты площадки (`data/config/demo_site.geojson`) и график работ
(`data/config/demo_schedule.json`) — придуманы для демонстрации: реальные
координаты объекта и календарь с датами в материалах ТЗ не найдены.
Справочник видов работ (`data/config/works_catalog.csv`) взят из исходного
Excel без изменений, включая явно помеченные испорченные Excel-коды.

## Продакшн-развёртывание (VPS)

Целевая схема: Ubuntu 24.04, Docker Engine + Compose plugin, nginx как обратный
прокси на 80/443, ufw (22/80/443), сертификаты через certbot (после появления
DNS-записей на ваш домен). Проект разворачивается в `/opt/buildvision`, секреты —
в `/opt/buildvision/.env` (chmod 600, не в git; см. `.env.example` в корне).

Краткая последовательность разворачивания на чистом сервере:

```bash
# один раз: docker, docker compose plugin, nginx, certbot, ufw — через apt
# перенос кода/весов — scp/rsync (без node_modules/.venv/data/raw/data/runs)
cd /opt/buildvision
docker compose build
docker compose up -d   # миграции, инициализация аккаунтов без сброса, статика admin
```

Настройка nginx (см. `deploy/nginx.conf.example`, замените `your-domain.example`
на свой домен) — реверс-прокси `your-domain.example`(+`www`) → `127.0.0.1:8000`,
путь `/admin/` → `127.0.0.1:8001`, `/static/` → собранная статика admin. Порты
`db`/`app`/`admin` в `docker-compose.yml` привязаны только к `127.0.0.1` —
наружу торчат только 80/443 через nginx.

**Особенности сборки на Linux-сервере, обнаруженные при первом деплое**
(уже исправлено в `Dockerfile`/`backend/requirements.txt`, но стоит помнить
при повторной сборке с нуля):

* `opencv-python` (зависимость `ultralytics`) требует системные библиотеки,
  отсутствующие в `python:3.13-slim` по умолчанию: `libgl1`, `libglib2.0-0`,
  `libxcb1`, `libxext6`, `libxrender1`, `libsm6`, `libgomp1` — без них падает
  с `ImportError: libxcb.so.1: cannot open shared object file`.
* Пакет `clip` (текстовый энкодер YOLO-World) не публикуется на PyPI — ставится
  из git (`ultralytics/CLIP`), поэтому в образе нужен установленный `git`.
* На некоторых VPS без выделенного IPv6-адреса Docker/BuildKit всё равно
  пытался резолвить `registry-1.docker.io`/`auth.docker.io` по IPv6 и падал с
  `network is unreachable`/`cannot assign requested address`. Частичные фиксы
  (`daemon.json` с `"ipv6": false`, `sysctl net.ipv6.conf.all.disable_ipv6=1`)
  работали нестабильно для контейнерных network namespace. Надёжно помогло
  только полное отключение IPv6 на уровне ядра: добавить `ipv6.disable=1` в
  `GRUB_CMDLINE_LINUX_DEFAULT` (`/etc/default/grub`), выполнить `update-grub`
  и перезагрузить сервер.

**Особенности, обнаруженные при передеплое на BuildVision** (исправлены в репозитории):

* `.dockerignore` исключал `data/raw/` целиком, что ломало `COPY data/raw/images/` в `Dockerfile`
  (нужно `scripts/seed_demo_history.py`) — исправлено на `data/raw/*` + `!data/raw/images`.
* Миграция, переводящая `StageRule.required` из простого M2M в M2M с `through=`,
  не может быть одним `AlterField` (Django это явно запрещает) — нужны отдельные
  `RemoveField`+`AddField`.
* Мобильное приложение грузится с другого origin (`https://localhost` у Capacitor Android) —
  добавлен в `SK_CORS_ORIGINS` по умолчанию; cookie сессии теперь ставится с
  `SameSite=None` вместо `Lax`, когда `SK_SESSION_COOKIE_SECURE=true` — иначе браузер/WebView
  не отправил бы cookie на кросс-сайт fetch-запросах (см. `backend/app/auth.py`).
* `docker-compose.yml`: добавлено монтирование `./models:/app/models` для `app` — без него
  артефакты классификатора-корректора (модуль AI Learning), появляющиеся во время работы
  контейнера, терялись бы при каждом перезапуске/пересборке.

**Сквозная проверка после редеплоя** подтвердила работу на развёрнутом домене: вход,
сводку с реальными зонами/камерами, анализ снимка с количественной проверкой Plan vs Fact,
прогноз сроков и полный цикл AI Learning (коррекция → обрезок сохранён на диск → счётчики
обновились).

## Лицензии и происхождение сторонних материалов

См. подробности в [`docs/PROJECT_DOCUMENTATION.md`](docs/PROJECT_DOCUMENTATION.md).
Кратко: Ultralytics YOLO-World распространяется по **AGPL-3.0** — при
публичном сетевом использовании необходимо предоставлять исходный код
сервиса (этот репозиторий открыт, что удовлетворяет условию).
