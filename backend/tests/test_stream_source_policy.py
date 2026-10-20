import socket
from unittest.mock import patch
import pytest
from app.streams.source_policy import validate_source,SourcePolicy,fetch_resource,SourceError
from app.streams.secrets import seal_source,open_source,mask_source

PUBLIC=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]

def test_policy_rejects_unsafe_sources():
 for u in ['file:///etc/passwd','http://127.0.0.1/','http://169.254.169.254/','http://[::1]/','http://host/\nfoo','https://rutube.ru/video/abc']:
  with pytest.raises(SourceError):validate_source(u,policy=SourcePolicy())
 with patch('socket.getaddrinfo',return_value=PUBLIC):
  assert validate_source('https://camera.example/live.m3u8',policy=SourcePolicy()).host=='camera.example'

def test_dns_and_redirect_targets_rechecked():
 with patch('socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',80))]):
  with pytest.raises(SourceError):validate_source('http://camera.example/live')

def test_mask_and_encryption(monkeypatch):
 from cryptography.fernet import Fernet
 monkeypatch.setenv('SK_STREAM_SECRET_KEY',Fernet.generate_key().decode())
 u='rtsp://user:secret@camera.example/live?token=private'
 assert open_source(seal_source(u))==u
 assert 'secret' not in mask_source(u) and 'private' not in mask_source(u) and 'user' not in mask_source(u)
