from django.test import TransactionTestCase
from django.contrib.auth.models import User
from django.core.cache import cache
from fastapi.testclient import TestClient
from backend.app.main import app

class RegistrationTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.api=TestClient(app,base_url="https://testserver",headers={"X-BuildVision-Request":"1"})
        self.addCleanup(self.api.close)
        self.data={"full_name":"Иван Петров", "email":"ivan@example.com", "password":"Strong!Secret582", "password_confirm":"Strong!Secret582"}

    def test_request_is_persisted_without_creating_active_account(self):
        response=self.api.post("/api/auth/register",data=self.data)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["status"],"sent")
        from core.models import RegistrationRequest
        item=RegistrationRequest.objects.get(email="ivan@example.com")
        self.assertNotEqual(item.password_hash,self.data["password"])
        from django.contrib.auth.hashers import check_password
        self.assertTrue(check_password(self.data["password"],item.password_hash))
        self.assertFalse(User.objects.exists())

    def test_duplicate_email_is_case_insensitive_and_does_not_replace_request(self):
        self.assertEqual(self.api.post("/api/auth/register",data=self.data).status_code,200)
        response=self.api.post("/api/auth/register",data={**self.data,"email":" IVAN@EXAMPLE.COM ","full_name":"Пётр Иванов"})
        self.assertEqual(response.json()["status"],"already_sent")
        from core.models import RegistrationRequest
        self.assertEqual(RegistrationRequest.objects.count(),1)
        self.assertEqual(RegistrationRequest.objects.get().full_name,"Иван Петров")

    def test_invalid_fields_do_not_create_request(self):
        for field,value in [("email","not-email"),("full_name","Иван 123"),("password","12345678"),("password_confirm","wrong")]:
            with self.subTest(field=field):
                response=self.api.post("/api/auth/register",data={**self.data,field:value})
                self.assertEqual(response.status_code,422)
                self.assertIn(field,response.json()["detail"]["fields"])

    def test_existing_email_is_not_registered_again(self):
        User.objects.create_user("existing",email="IVAN@example.com")
        response=self.api.post("/api/auth/register",data=self.data)
        self.assertEqual(response.status_code,409)

    def test_request_guard_is_required(self):
        response=TestClient(app,base_url="https://testserver").post("/api/auth/register",data=self.data)
        self.assertEqual(response.status_code,403)

    def test_requests_are_throttled(self):
        for _ in range(60):
            self.api.post("/api/auth/register",data={**self.data,"email":"invalid"})
        self.assertEqual(self.api.post("/api/auth/register",data=self.data).status_code,429)
