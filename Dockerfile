# syntax=docker/dockerfile:1
#
# Единый образ: FastAPI отдаёт и API, и собранный статический фронтенд
# с одного адреса (см. план, раздел «Технический подход»).
# Веса модели и CLIP-энкодер копируются из локально подготовленных
# каталогов, чтобы контейнер не тянул их из сети при первом запуске
# (план: «подготовить словарь и экспорт локально»).

# ---------- Стадия 1: сборка фронтенда ----------
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- Стадия 2: backend + модель ----------
FROM python:3.13-slim AS backend
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SK_FRONTEND_DIST=/app/frontend/dist \
    SK_YOLO_CONFIG_DIR=/app/.cache/ultralytics \
    SK_TORCH_HOME=/app/.cache/torch \
    DJANGO_SETTINGS_MODULE=admin_panel.settings

# Системные библиотеки, нужные opencv-python (используется ultralytics/YOLO-World)
# для инициализации бэкенда отрисовки, даже в headless-режиме без дисплея.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        git \
        libgl1 \
        libglib2.0-0 \
        libxcb1 \
        libxext6 \
        libxrender1 \
        libsm6 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# CPU-версии torch/torchvision — отдельно, с официального индекса.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir torch==2.8.0 torchvision==0.23.0 \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY manage.py manage.py
COPY admin_panel/ admin_panel/
COPY core/ core/
COPY data/config/ data/config/
COPY data/raw/images/ data/raw/images/
COPY scripts/ scripts/
COPY models/ models/

# CLIP-энкодер (используется YOLO-World для текстового словаря) ищет веса
# по умолчанию в ~/.cache/clip — кладём заранее подготовленный файл туда,
# чтобы избежать загрузки ~340 МБ при первом запуске контейнера.
COPY weights/clip/ /root/.cache/clip/

COPY --from=frontend-build /app/frontend/dist frontend/dist/

RUN mkdir -p data/uploads

EXPOSE 8000

# Один worker: одна копия модели в памяти на процесс (см. план,
# раздел «Размещение на арендованной VPS»).
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
