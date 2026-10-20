"""Registration request stub. Never sends email or activates an account."""
import hashlib
import re
from fastapi import APIRouter, Form, HTTPException, Request, Response
from . import django_bridge

router = APIRouter()

@router.post("/api/auth/register")
def register(request: Request, response: Response, full_name: str = Form(""), email: str = Form(""), password: str = Form(""), password_confirm: str = Form("")) -> dict:
    if not django_bridge.ensure_django_ready():
        raise HTTPException(503, "Регистрация временно недоступна. Попробуйте позже.")
    from django.contrib.auth.models import User
    from django.contrib.auth.hashers import make_password
    from django.contrib.auth.password_validation import validate_password
    from django.core.cache import cache
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email
    from core.models import RegistrationRequest

    # Public endpoint: throttle the trusted connection address, never a supplied header.
    address = request.client.host if request.client else "unknown"
    key = "registration:" + hashlib.sha256(address.encode()).hexdigest()
    if not cache.add(key, 1, 3600):
        try:
            attempts = cache.incr(key)
        except ValueError:
            cache.set(key, 1, 3600)
            attempts = 1
        if attempts > 60:
            raise HTTPException(429, "Слишком много попыток. Попробуйте позже.")

    name = " ".join(full_name.split())
    normalized_email = email.strip().casefold()
    errors = {}
    if len(name) > 150 or not re.fullmatch(r"[^\W\d_]+(?:[ .’'-]+[^\W\d_]+)+", name):
        errors["full_name"] = "Введите имя и фамилию буквами, без цифр и специальных символов."
    try:
        if len(normalized_email) > 254:
            raise ValidationError("email too long")
        validate_email(normalized_email)
    except ValidationError:
        errors["email"] = "Введите корректный email, например name@company.ru."
    if len(password) > 128:
        errors["password"] = "Пароль должен содержать не более 128 символов."
    else:
        try:
            validate_password(password, User(username=normalized_email, first_name=name.split(" ")[0], email=normalized_email))
        except ValidationError as exc:
            errors["password"] = " ".join(exc.messages)
    if password != password_confirm:
        errors["password_confirm"] = "Пароли не совпадают."
    if errors:
        raise HTTPException(422, {"message":"Проверьте поля формы.", "fields":errors})
    response.headers["Cache-Control"] = "no-store"
    if RegistrationRequest.objects.filter(email=normalized_email).exists():
        return {"status":"already_sent", "email":normalized_email, "mode":"stub"}
    if User.objects.filter(email__iexact=normalized_email).exists():
        raise HTTPException(409, "Этот email уже зарегистрирован. Войдите в аккаунт.")
    _, created = RegistrationRequest.objects.get_or_create(email=normalized_email, defaults={"full_name":name,"password_hash":make_password(password)})
    return {"status":"sent" if created else "already_sent", "email":normalized_email,"mode":"stub"}
