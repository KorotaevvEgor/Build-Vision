"""Защита cookie API от межсайтовых запросов без отдельной системы токенов.

Каждая запись требует нестандартного заголовка от нашего клиента. Чужая
HTML-форма его добавить не может, а cross-origin fetch требует разрешённого
CORS preflight. Origin дополнительно проверяется до выполнения обработчика.
CLI-клиенты без Origin также должны явно отправить этот заголовок.
"""

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class ApiRequestGuard:
    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = {origin.strip() for origin in allowed_origins if origin.strip()}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["path"].startswith("/api/")
            and scope["method"] not in {"GET", "HEAD", "OPTIONS"}
        ):
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            if (
                headers.get("x-buildvision-request") != "1"
                or (origin is not None and origin not in self.allowed_origins)
            ):
                response = JSONResponse(
                    {"detail": "Запрос отклонён защитой от межсайтовых запросов"},
                    status_code=403,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
