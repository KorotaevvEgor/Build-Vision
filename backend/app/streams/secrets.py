import os
from urllib.parse import urlsplit
from cryptography.fernet import Fernet,InvalidToken

def cipher():
    try:return Fernet(os.environ['SK_STREAM_SECRET_KEY'].encode())
    except (KeyError,ValueError):raise ValueError('На сервере не настроен ключ видеопотоков') from None

def seal_source(url:str)->str:return cipher().encrypt(url.encode()).decode()
def open_source(value:str)->str:
    try:return cipher().decrypt(value.encode()).decode()
    except InvalidToken:raise ValueError('Введите адрес потока заново: сохранённый адрес не удалось расшифровать') from None
def mask_source(url:str)->str:
    u=urlsplit(url)
    return f'{u.scheme}://{u.hostname}' + (f':{u.port}' if u.port else '') + '/…'
