import pytest

from app.core import auth


@pytest.fixture
def locked_client(client, settings):
    settings.app_password = "dad-secret-pw"
    auth._failures.clear()
    yield client
    auth._failures.clear()


def test_open_when_no_password_configured(client):
    assert client.get("/api/auth/status").json() == {"auth_required": False, "logged_in": True}
    assert client.get("/api/scans/status").status_code == 200


def test_data_requires_login(locked_client):
    r = locked_client.get("/api/scans/status")
    assert r.status_code == 401 and r.json()["error"]["code"] == "login_required"
    assert locked_client.get("/api/stocks/RELIANCE/history").status_code == 401
    assert locked_client.get("/api/health").status_code == 200  # monitoring stays open
    assert locked_client.get("/api/auth/status").json() == {"auth_required": True, "logged_in": False}


def test_login_sets_cookie_and_unlocks(locked_client):
    r = locked_client.post("/api/auth/login", json={"password": "dad-secret-pw"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "max-age=2592000" in cookie
    assert locked_client.get("/api/scans/status").status_code == 200
    locked_client.post("/api/auth/logout")
    assert locked_client.get("/api/scans/status").status_code == 401


def test_wrong_password_and_lockout(locked_client):
    for _ in range(auth.MAX_FAILURES):
        r = locked_client.post("/api/auth/login", json={"password": "nope"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "wrong_password"
    r = locked_client.post("/api/auth/login", json={"password": "dad-secret-pw"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_attempts"


def test_tokens_expire_and_are_tied_to_the_password():
    t = auth.make_token("pw1", ttl_seconds=60, now=1000)
    assert auth.token_is_valid(t, "pw1", now=1030)
    assert not auth.token_is_valid(t, "pw1", now=1061)  # expired
    assert not auth.token_is_valid(t, "pw2", now=1030)  # password changed -> logged out
    assert not auth.token_is_valid(t[:-1] + ("0" if t[-1] != "0" else "1"), "pw1", now=1030)  # tampered
    assert not auth.token_is_valid("garbage", "pw1")


def test_production_refuses_to_start_without_password(monkeypatch):
    from app.core.config import Settings
    from app import main

    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None, app_env="production", app_password=""))
    with pytest.raises(RuntimeError, match="APP_PASSWORD"):
        main.create_app()
