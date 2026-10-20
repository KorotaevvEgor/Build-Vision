import hashlib,os,re,shutil,subprocess,tempfile,time,threading
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime,UTC
from pathlib import Path
from urllib.parse import urljoin,urlsplit,urlunsplit
from PIL import Image
from .source_policy import validate_source,fetch_resource,open_resource,SourceError,ValidatedSource

class CaptureError(Exception):
    def __init__(self,code='capture_failed',message='Не удалось получить кадр. Проверьте адрес и доступность камеры.'):
        self.code=code;self.public_message=message;super().__init__(message)
@dataclass
class CapturedFrame:
    path:Path
    sha256:str
    width:int
    height:int
    bytes:int
    received_at:datetime

def read_prefix(response,deadline):
    prefix=b''
    while len(prefix)<512:
        if len(prefix.lstrip(b'\xef\xbb\xbf \r\n\t'))>=7:break
        if time.monotonic()>deadline:raise SourceError('Превышено время получения кадра')
        chunk=response.read1(512-len(prefix))
        if not chunk:break
        prefix+=chunk
    return prefix

def materialize_hls(url:str,directory:Path,*,deadline=None)->Path:
    deadline=deadline or time.monotonic()+20;cache={};total=0
    def fetch(u,depth=0):
        nonlocal total
        if depth>5 or len(cache)>40:raise SourceError('Слишком сложный плейлист потока')
        if u in cache:return cache[u]
        data,actual=fetch_resource(u,max_bytes=16*1024*1024,deadline=deadline)
        total+=len(data)
        if total>64*1024*1024:raise SourceError('Поток превышает лимит данных')
        playlist=data.lstrip(b'\xef\xbb\xbf \r\n\t').startswith(b'#EXTM3U')
        path=directory/f'resource-{len(cache)}{ ".m3u8" if playlist else ".bin"}'
        cache[u]=path
        if playlist:
            lines=[]
            for line in data.decode('utf-8-sig').splitlines():
                if line and not line.startswith('#'):line=fetch(urljoin(actual,line.strip()),depth+1).name
                elif 'URI=' in line:
                    def uri(m):return 'URI="'+fetch(urljoin(actual,m.group(1)),depth+1).name+'"'
                    line,n=re.subn(r'URI="([^"]+)"',uri,line)
                    if not n:raise SourceError('Неподдерживаемый адрес в плейлисте')
                # Untrusted extensions can introduce URL substitution; only standard static HLS.
                if line.startswith(('#EXT-X-DEFINE','#EXT-X-CONTENT-STEERING')):raise SourceError('Неподдерживаемое расширение HLS')
                lines.append(line)
            path.write_text('\n'.join(lines)+'\n',encoding='utf8')
        else:
            if data.lstrip().startswith((b'<?xml',b'<MPD',b'ffconcat')):raise SourceError('Неподдерживаемый вложенный формат')
            path.write_bytes(data)
        return path
    return fetch(url)

def capture_frame(source:ValidatedSource,*,destination:Path,timeout_seconds:int=20)->CapturedFrame:
    deadline=time.monotonic()+timeout_seconds
    exe=shutil.which('ffmpeg')
    if not exe:raise CaptureError('ffmpeg_unavailable','Обработчик видео пока не настроен на сервере')
    destination.parent.mkdir(parents=True,exist_ok=True)
    try:
        # Revalidate immediately before connecting; use the new pinned result, never a hostname lookup by FFmpeg.
        source=validate_source(source.url)
        with ExitStack() as stack:
            temp=stack.enter_context(tempfile.TemporaryDirectory(prefix='stream-'))
            folder=Path(temp);env=os.environ.copy();options=[]
            if source.scheme in ('rtsp','rtsps'):
                guard=Path(os.getenv('SK_STREAM_NETWORK_GUARD','/app/stream-network-guard.so'))
                if os.name!='posix' or not guard.is_file():raise CaptureError('network_guard_unavailable','Защищённый RTSP-захват не настроен на сервере')
                # RTSPS requires hostname-aware TLS verification, unavailable in this pinned RTSP adapter.
                if source.scheme=='rtsps':raise CaptureError('rtsps_unavailable','Для защищённого источника используйте HTTPS/HLS или согласованный RTSP-шлюз')
                u=urlsplit(source.url);ip=source.ips[0];auth=u.netloc.rsplit('@',1)[0]+'@' if '@' in u.netloc else ''
                netloc=auth+(f'[{ip}]' if ':' in ip else ip)+f':{source.port}'
                address=urlunsplit((u.scheme,netloc,u.path,u.query,''))
                env.update(LD_PRELOAD=str(guard),SK_STREAM_PIN_IP=ip,SK_STREAM_PIN_PORT=str(source.port))
                options=['-rtsp_transport','tcp','-rw_timeout','8000000','-protocol_whitelist','rtsp,tcp,rtp']
            else:
                response,actual=stack.enter_context(open_resource(source.url,deadline=deadline))
                prefix=read_prefix(response,deadline)
                if prefix.lstrip(b'\xef\xbb\xbf \r\n\t').startswith(b'#EXTM3U'):
                    address=str(materialize_hls(actual,folder,deadline=deadline))
                    options=['-protocol_whitelist','file,crypto,data','-format_whitelist','hls,mpegts,mov,aac,mp3','-f','hls','-allowed_extensions','ALL']
                else:
                    address='pipe:0'
                    options=['-protocol_whitelist','pipe','-format_whitelist','mpegts,mov,mpjpeg,mjpeg,matroska,webm,flv,aac,mp3,image2pipe']
            output=folder/'frame.jpg'
            args=[exe,'-hide_banner','-loglevel','error','-nostdin','-y','-threads','1','-filter_threads','1','-max_alloc','67108864',*options,'-i',address,'-frames:v','1','-vf',"scale=w='min(4096,iw)':h='min(2160,ih)':force_original_aspect_ratio=decrease",'-q:v','3',str(output)]
            remaining=deadline-time.monotonic()
            if remaining<=0:raise CaptureError('timeout','Источник не передал кадр за 20 секунд')
            with (folder/'decoder.log').open('wb') as err:
                proc=subprocess.Popen(args,stdin=subprocess.PIPE if address=='pipe:0' else subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=err,env=env,start_new_session=os.name=='posix')
                if address=='pipe:0':
                    def feed():
                        size=0;chunk=prefix
                        try:
                            while chunk and time.monotonic()<deadline and proc.poll() is None:
                                size+=len(chunk)
                                if size>64*1024*1024:break
                                proc.stdin.write(chunk);proc.stdin.flush();chunk=response.read1(65536)
                        except (OSError,ValueError):pass
                        finally:
                            try:proc.stdin.close()
                            except OSError:pass
                    threading.Thread(target=feed,daemon=True).start()
                try:proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    if os.name=='posix':
                        import signal
                        os.killpg(proc.pid,signal.SIGKILL)
                    else:proc.kill()
                    proc.wait();raise CaptureError('timeout','Источник не передал кадр за 20 секунд') from None
            if proc.returncode or not output.is_file():raise CaptureError()
            size=output.stat().st_size
            if not 0<size<=10*1024*1024:raise CaptureError('image_size','Полученный кадр превышает допустимый размер')
            with Image.open(output) as im:
                im.load();w,h=im.size
                if im.format!='JPEG' or w*h>12000000 or w>4096 or h>2160:raise CaptureError('invalid_image','Источник передал неподдерживаемый кадр')
            data=output.read_bytes();tmp=destination.with_suffix('.tmp');tmp.write_bytes(data);os.replace(tmp,destination)
            return CapturedFrame(destination,hashlib.sha256(data).hexdigest(),w,h,size,datetime.now(UTC))
    except CaptureError:raise
    except SourceError as e:raise CaptureError('source_rejected',str(e)) from None
    except Exception:raise CaptureError() from None
