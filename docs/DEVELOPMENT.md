# Разработка и проверка

## Окружение

Python 3.13, Node.js 22.18 или новее в ветке 22, PostgreSQL 16 и Docker Compose. Создайте `.env` по `.env.example`; реальные значения не добавляйте в Git.

## Локальный сервер

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\Activate.ps1
pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r backend/requirements.txt
docker compose up -d db
python manage.py migrate
python manage.py createsuperuser
python -m uvicorn app.main:app --app-dir backend --port 8000
```

В локальном окружении `DATABASE_URL` должен указывать на доступный PostgreSQL. Django admin запускается отдельной командой `python manage.py runserver 8001`.

## Модели

Детектор загружает YOLO-World лениво при первом анализе. Для автономного Docker-развёртывания Dockerfile ожидает заранее подготовленные файлы в `models/` и `weights/clip/`: веса YOLO-World и `ViT-B-32.pt`. Получайте их из официальных источников соответствующих моделей; проверьте применимые лицензии. Эти каталоги исключены из Git. См. `backend/app/config.py`, `detector.py` и Dockerfile для конкретных путей.

Файлы обученного корректора создаются системой в `models/`. После обучения кандидат проходит проверку и публикуется администратором; наличие файла само по себе не включает модель.

## Веб-клиент

```bash
cd frontend
npm ci
npm run dev
```

Vite перенаправляет `/api` на сервер разработки. В production API и собранный клиент отдаются с одного origin. Адреса окружения описаны в `frontend/.env.example`.

## Проверки без рабочей базы

```bash
pip install -r requirements-ci.txt
PYTHONPATH=backend DJANGO_SETTINGS_MODULE=admin_panel.test_settings python -m pytest backend/tests/test_matching_rules.py backend/tests/test_work_evidence.py -q
python manage.py test core.tests.test_independent_evidence --settings=admin_panel.test_settings
cd frontend
node --experimental-strip-types --test tests/*.test.ts
npm run build
```

В PowerShell задайте переменные перед запуском: `$env:PYTHONPATH="backend"; $env:DJANGO_SETTINGS_MODULE="admin_panel.test_settings"`. Тестовые настройки используют SQLite в памяти и не обращаются к PostgreSQL. Полный набор backend-проверок содержит сценарии загрузки моделей и анализа изображений — для него требуется ML-окружение и отдельные тестовые данные.

## Полезные команды

- `scripts/extract_frames.py` — извлечение кадров из локального видео. Это утилита, а не фоновый сервис подключения камер.
- `scripts/parse_works_catalog.py` — подготовка справочника работ из Excel.
- `scripts/evaluate_detector.py` — оценка детектора по независимым аннотациям.
- `scripts/train_correction_classifier.py` — обучение классификатора-корректора.
- `scripts/train_correction_tasks.py` — обработка задания обучения.
- `scripts/verify_db_persistence.py` — проверка сохранения данных.

Для каждого скрипта сначала просмотрите `--help`. Не запускайте импорт, заполнение демонстрационных данных или обучение на рабочей базе без понимания области действия команды.
