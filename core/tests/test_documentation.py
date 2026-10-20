import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from core.models import UserProfile
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from fastapi.testclient import TestClient
from app.main import app
from app import documentation_router

class DocumentationTests(TransactionTestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch=patch.object(documentation_router,'STORE_DIR',Path(self.temp.name))
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.client=TestClient(app,base_url='https://testserver',headers={'X-BuildVision-Request':'1'})
        self.addCleanup(self.client.close)
    def login(self,role='admin'):
        user=User.objects.create_user('docs-'+role,password='test-password-only-123',is_staff=role=='admin')
        UserProfile.objects.create(user=user,role=role)
        response=self.client.post('/api/auth/login',data={'username':user.username,'password':'test-password-only-123'})
        self.assertEqual(response.status_code,200,response.text)
    def post(self,name='slides.pdf',content=b'%PDF-1.4\nexample'):
        return self.client.post('/api/documentation/presentation',files={'file':(name,content,'application/pdf')})
    def test_public_empty_and_upload_requires_login(self):
        self.assertEqual(self.client.get('/api/documentation/presentation').json(),{'available':False})
        self.assertEqual(self.client.get('/api/documentation/presentation/file').status_code,404)
        self.assertEqual(self.post().status_code,401)
    def test_non_admin_cannot_publish(self):
        self.login('participant')
        self.assertEqual(self.post().status_code,403)
    def test_admin_publish_replace_and_public_read(self):
        self.login()
        first=self.post(); self.assertEqual(first.status_code,200,first.text)
        self.assertTrue(first.json()['available'])
        second=self.post(content=b'%PDF-1.7\nreplacement')
        self.assertEqual(second.status_code,200,second.text)
        self.assertNotEqual(first.json()['url'],second.json()['url'])
        with TestClient(app,base_url='https://testserver') as public:
            response=public.get(second.json()['url'])
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.content,b'%PDF-1.7\nreplacement')
            self.assertIn('inline',response.headers['content-disposition'])
        self.assertEqual(len(list(Path(self.temp.name).iterdir())),1)
    def test_invalid_upload_does_not_replace_existing(self):
        self.login(); self.assertEqual(self.post().status_code,200)
        self.assertEqual(self.post('slides.exe').status_code,400)
        self.assertEqual(self.post(content=b'not a PDF').status_code,400)
        with patch.object(documentation_router,'MAX_BYTES',8):
            self.assertEqual(self.post(content=b'%PDF-123456789').status_code,413)
        self.assertEqual((Path(self.temp.name)/'presentation.pdf').read_bytes(),b'%PDF-1.4\nexample')
