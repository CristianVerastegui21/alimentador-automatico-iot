import os
import unittest
from unittest.mock import patch
from app import create_app

class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test-secret", "SESSION_COOKIE_SECURE": False})
        self.client = self.app.test_client()

    def test_health(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_login_and_csrf(self):
        with patch.dict(os.environ, {"ADMIN_EMAIL": "admin@test.local", "ADMIN_PASSWORD": "test-password"}):
            response = self.client.post("/login", data={"email": "admin@test.local", "password": "test-password"})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.client.get("/").status_code, 200)
            self.assertEqual(self.client.post("/api/feed", json={}).status_code, 403)
            with self.client.session_transaction() as s:
                csrf = s["csrf"]
            self.assertEqual(self.client.post("/logout", data={"csrf": csrf}).status_code, 302)
            self.assertEqual(self.client.get("/api/status").status_code, 401)

    def test_device_rejects_bad_token(self):
        with patch.dict(os.environ, {"DEVICE_TOKEN": "a" * 48}):
            self.assertEqual(self.client.get("/api/device/config").status_code, 401)

if __name__ == "__main__":
    unittest.main()
