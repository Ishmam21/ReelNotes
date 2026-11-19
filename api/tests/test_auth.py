from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import auth, main


@pytest.mark.parametrize(("method", "path"), [
    ("GET", "/playlists"),
    ("GET", "/playlists/{id}"),
    ("GET", "/playlists/{id}/manifest"),
    ("GET", "/playlists/{id}/guides"),
    ("GET", "/guides/{id}/download"),
    ("GET", "/guides/{id}/evidence"),
    ("GET", "/videos/{id}/thumbnail"),
    ("GET", "/videos/{id}/transcript"),
    ("POST", "/videos/{id}/retry"),
])
def test_private_resources_require_a_session(method, path):
    response = TestClient(main.app).request(method, path.format(id=uuid4()))
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/auth/register", "/auth/login"])
def test_validation_does_not_echo_password(path, monkeypatch):
    def unexpected_connection():
        pytest.fail("Invalid account input must not access the database")

    monkeypatch.setattr(auth, "get_engine", unexpected_connection)
    password = "secret that must not be echoed"
    response = TestClient(main.app).post(path, json={"email": "invalid", "password": password})
    assert response.status_code == 422
    assert password not in response.text
    assert '"input"' not in response.text


@pytest.mark.parametrize("password", ["Ab1!c", "abc1!d", "ABC1!D", "Abcd!e", "Abc123", "Ab1 cd"])
def test_registration_rejects_passwords_that_miss_requirements(password):
    response = TestClient(main.app).post(
        "/auth/register", json={"email": "owner@example.com", "password": password}
    )
    assert response.status_code == 422
    assert password not in response.text


def test_registration_accepts_six_character_password():
    registration = auth.Registration(email="owner@example.com", password="Ab1!cd")
    assert registration.password.get_secret_value() == "Ab1!cd"


def test_login_accepts_credentials_under_the_old_policy():
    login = auth.LoginCredentials(email="owner@example.com", password="a long lowercase passphrase")
    assert login.password.get_secret_value() == "a long lowercase passphrase"


def test_untrusted_origin_cannot_change_session():
    response = TestClient(main.app).post("/auth/logout", headers={"Origin": "https://other.example"})
    assert response.status_code == 403
    assert "set-cookie" not in response.headers
