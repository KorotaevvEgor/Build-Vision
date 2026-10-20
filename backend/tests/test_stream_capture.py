import pytest
from pathlib import Path
from app.streams.capture import materialize_hls,CaptureError

def test_hls_rewrites_all_resources_and_refuses_unknown_uri(tmp_path,monkeypatch):
    urls=[]
    def fetch(url,**kw):
        urls.append(url)
        if url.endswith('.m3u8'):return b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\n#EXTINF:2,\npart.ts\n#EXT-X-ENDLIST\n',url
        return b'bytes',url
    monkeypatch.setattr('app.streams.capture.fetch_resource',fetch)
    path=materialize_hls('https://camera.example/live.m3u8',tmp_path)
    text=path.read_text()
    assert 'https:' not in text and 'URI="' in text
    assert len(urls)==3

def test_capture_failure_does_not_expose_source(tmp_path):
    from app.streams.capture import capture_frame
    from app.streams.source_policy import ValidatedSource
    with pytest.raises(CaptureError):capture_frame(ValidatedSource('rtsp://secret@host/live','rtsp','host',554,('93.184.216.34',)),destination=tmp_path/'x.jpg')

def test_fragmented_hls_header():
    from app.streams.capture import read_prefix
    import time
    class Fragments:
        def __init__(self):self.parts=iter([b'#EXT',b'M3U\n#EXT-X-TARGETDURATION:2\n'])
        def read1(self,n):return next(self.parts,b'')
    assert read_prefix(Fragments(),time.monotonic()+1).startswith(b'#EXTM3U')
