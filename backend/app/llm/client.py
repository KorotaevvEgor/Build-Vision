"""Клиент к OpenAI-совместимому API (AITunnel) с кэшем и честной деградацией.

Ключевое поведение: клиент НИКОГДА не бросает исключение наружу и никогда
не возвращает выдуманный текст. При любой проблеме — недоступной сети,
исчерпанных ретраях, неверном ответе — возвращается результат с
``available=False`` и заполненным ``error``. Вызывающий код обязан показать
пользователю штатное объяснение и пометку, что заключение не сформировано.
Это прямое следствие принципа проекта: честное «нет данных» лучше
уверенного вымысла.

Кэш на диске нужен не для экономии, а для демонстрации: ответы по уже
разобранным снимкам отдаются мгновенно и переживают отсутствие интернета
в момент показа жюри.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from .. import config

logger = logging.getLogger(__name__)

CACHE_DIR = config.DATA_DIR / "llm_cache"

_DEFAULT_BASE_URL = "https://api.aitunnel.ru/v1"
_REQUEST_TIMEOUT_SECONDS = 120
_MAX_ATTEMPTS_PER_HOST = 2
_RETRY_BACKOFF_SECONDS = 2.0

# Версия входит в ключ кэша: при правке промпта старые ответы не подхватываются
# молча, иначе можно часами отлаживать промпт и смотреть на закэшированный ответ.
PROMPT_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class LLMResult:
    """Результат обращения к модели.

    ``available=False`` означает, что содержательного ответа нет: ни текста,
    ни данных. Поле ``text`` в этом случае пустое, а причина — в ``error``.
    """

    available: bool
    text: str = ""
    model: str = ""
    cached: bool = False
    error: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


def _api_key() -> str:
    return os.environ.get("AITUNNEL_API_KEY", "").strip()


def llm_is_configured() -> bool:
    """Есть ли вообще ключ. Позволяет интерфейсу не обещать того, чего нет."""
    return bool(_api_key())


def text_model() -> str:
    return os.environ.get("AITUNNEL_TEXT_MODEL", "claude-sonnet-4.6").strip()


def vision_model() -> str:
    return os.environ.get("AITUNNEL_VISION_MODEL", text_model()).strip()


def _base_urls() -> list[str]:
    """Основной адрес и резервное зеркало — пробуются по очереди."""
    primary = os.environ.get("AITUNNEL_BASE_URL", _DEFAULT_BASE_URL).strip().rstrip("/")
    fallback = os.environ.get("AITUNNEL_FALLBACK_BASE_URL", "").strip().rstrip("/")
    urls = [primary]
    if fallback and fallback != primary:
        urls.append(fallback)
    return urls


def _cache_path(cache_key: str) -> Path:
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def _read_cache(cache_key: str) -> LLMResult | None:
    path = _cache_path(cache_key)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Повреждённый файл кэша LLM, игнорируется: %s", path)
        return None
    return LLMResult(
        available=True,
        text=payload.get("text", ""),
        model=payload.get("model", ""),
        cached=True,
        usage=payload.get("usage", {}),
    )


def _write_cache(cache_key: str, result: LLMResult) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"text": result.text, "model": result.model, "usage": result.usage}
    try:
        _cache_path(cache_key).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        logger.warning("Не удалось записать кэш LLM — продолжаем без кэширования")


def image_data_url(image_path: Path) -> str:
    """Кодирует изображение в data URL, как того требует OpenAI-совместимый формат."""
    mime = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _extract_text(payload: dict) -> str:
    """Достаёт текст ответа. Часть провайдеров отдаёт content списком блоков."""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def chat(
    messages: list[dict],
    *,
    cache_key: str,
    model: str | None = None,
    max_tokens: int = 1200,
    temperature: float = 0.2,
    use_cache: bool = True,
) -> LLMResult:
    """Один запрос к модели с кэшем, ретраями и переключением на зеркало."""
    chosen_model = model or text_model()
    full_cache_key = f"{PROMPT_SCHEMA_VERSION}|{chosen_model}|{cache_key}"

    if use_cache:
        cached = _read_cache(full_cache_key)
        if cached is not None:
            return cached

    if not llm_is_configured():
        return LLMResult(
            available=False,
            error="Ключ AITUNNEL_API_KEY не задан — заключение не формируется",
        )

    body = {
        "model": chosen_model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }

    last_error = "неизвестная ошибка"
    for base_url in _base_urls():
        for attempt in range(1, _MAX_ATTEMPTS_PER_HOST + 1):
            try:
                response = requests.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=body,
                    timeout=_REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                last_error = f"сеть недоступна: {type(exc).__name__}"
                logger.warning("LLM %s попытка %s: %s", base_url, attempt, last_error)
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
                continue

            if response.status_code == 200:
                payload = response.json()
                text = _extract_text(payload).strip()
                if not text:
                    last_error = "модель вернула пустой ответ"
                    break
                result = LLMResult(
                    available=True,
                    text=text,
                    model=chosen_model,
                    usage=payload.get("usage", {}) or {},
                )
                if use_cache:
                    _write_cache(full_cache_key, result)
                return result

            # 4xx повторять бессмысленно — это наша ошибка в запросе или в ключе.
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            if response.status_code < 500:
                break
            time.sleep(_RETRY_BACKOFF_SECONDS * attempt)

    logger.warning("LLM недоступна: %s", last_error)
    return LLMResult(available=False, error=last_error)


def parse_json_response(text: str) -> dict | None:
    """Разбирает JSON из ответа модели, снимая обрамление ```json ... ```.

    Возвращает None, если разобрать не удалось: вызывающий код должен
    трактовать это как недоступность структурированного результата, а не
    пытаться угадать содержимое.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        cleaned = cleaned.removeprefix("json").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[: -len("```")].strip()
    # Модель иногда добавляет пояснение до или после объекта — берём срез по скобкам.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
