"""Pinned network endpoints; nested HLS resources use the same validation."""
import base64,http.client,ipaddress,os,socket,ssl,time
from dataclasses import dataclass,field
from urllib.parse import urlsplit,urlunsplit,urljoin,unquote

class SourceError(ValueError):pass
@dataclass
class SourcePolicy:
    hosts:tuple[str,...]=field(default_factory=lambda:tuple(x.strip().lower() for x in os.getenv('SK_STREAM_ALLOWED_HOSTS','').split(',') if x.strip()))
    cidrs:tuple[str,...]=field(default_factory=lambda:tuple(x.strip() for x in os.getenv('SK_STREAM_ALLOWED_CIDRS','').split(',') if x.strip()))
@dataclass(frozen=True)
class ValidatedSource:
    url:str
    scheme:str
    host:str
    port:int
    ips:tuple[str,...]

def validate_source_format(url:str):
    if not url or len(url)>2000 or any(ord(c)<33 for c in url) or '\\' in url:raise SourceError('Проверьте адрес потока')
    try:
        u=urlsplit(url);host=(u.hostname or '').lower();port=u.port or {'http':80,'https':443,'rtsp':554,'rtsps':322}.get(u.scheme,0)
    except ValueError:raise SourceError('Проверьте адрес и порт') from None
    if u.scheme not in ('http','https','rtsp','rtsps') or not host or u.fragment:raise SourceError('Нужна прямая ссылка HTTP(S) или RTSP(S)')
    if any(host==d or host.endswith('.'+d) for d in ('rutube.ru','youtube.com','youtu.be','vk.com')):raise SourceError('Укажите прямой поток, а не страницу видеоплатформы')
    if port not in (80,443,554,322,8080,8443,8554,1935):raise SourceError('Порт потока не разрешён')
    return u,host,port

def validate_source(url:str,*,policy:SourcePolicy|None=None)->ValidatedSource:
    policy=policy or SourcePolicy()
    u,host,port=validate_source_format(url)
    if policy.hosts and host not in policy.hosts:raise SourceError('Узел не разрешён настройками сервера')
    try:ips=tuple(sorted({i[4][0] for i in socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)}))
    except OSError:raise SourceError('Не удалось определить адрес камеры') from None
    if not ips:raise SourceError('Узел камеры не найден')
    for raw in ips:
        ip=ipaddress.ip_address(raw)
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:raise SourceError('Служебный сетевой адрес запрещён')
        if not ip.is_global and not any(ip in ipaddress.ip_network(n) for n in policy.cidrs):raise SourceError('Для внутренней камеры требуется разрешённая подсеть на сервере')
    return ValidatedSource(url,u.scheme,host,port,ips)

from contextlib import contextmanager

@contextmanager
def open_resource(url:str,*,policy:SourcePolicy|None=None,deadline:float|None=None):
    deadline=deadline or time.monotonic()+20
    for _ in range(5):
        s=validate_source(url,policy=policy)
        if s.scheme not in ('http','https'):raise SourceError('Недопустимый адрес вложенного ресурса')
        left=deadline-time.monotonic()
        if left<=0:raise SourceError('Превышено время получения кадра')
        raw=socket.create_connection((s.ips[0],s.port),timeout=min(8,left))
        conn=http.client.HTTPConnection(s.host,s.port,timeout=min(8,left))
        try:
            conn.sock=ssl.create_default_context().wrap_socket(raw,server_hostname=s.host) if s.scheme=='https' else raw
            u=urlsplit(url);headers={'Host':s.host if s.port in (80,443) else f'{s.host}:{s.port}','User-Agent':'BuildVision-FrameCapture/1'}
            if u.username is not None:headers['Authorization']='Basic '+base64.b64encode((unquote(u.username)+':'+unquote(u.password or '')).encode()).decode()
            conn.request('GET',urlunsplit(('','',u.path or '/',u.query,'')),headers=headers)
            r=conn.getresponse()
            if r.status in (301,302,303,307,308):
                target=r.getheader('Location')
                if not target:raise SourceError('Пустое перенаправление потока')
                url=urljoin(url,target);continue
            if r.status!=200:raise SourceError('Источник недоступен или требует авторизацию')
            yield r,url
            return
        finally:conn.close();raw.close()
    raise SourceError('Слишком много перенаправлений')

def fetch_resource(url:str,*,policy:SourcePolicy|None=None,max_bytes:int=32*1024*1024,deadline:float|None=None)->tuple[bytes,str]:
    deadline=deadline or time.monotonic()+20
    with open_resource(url,policy=policy,deadline=deadline) as (r,actual):
        chunks=[];size=0
        while True:
            if time.monotonic()>deadline:raise SourceError('Превышено время получения кадра')
            chunk=r.read1(min(65536,max_bytes+1-size))
            if not chunk:break
            size+=len(chunk)
            if size>max_bytes:raise SourceError('Ресурс потока превышает допустимый размер')
            chunks.append(chunk)
        return b''.join(chunks),actual
