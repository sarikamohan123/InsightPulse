"""
Integration tests: full auth flow — register → login → refresh → me.

Each test makes real HTTP calls through the FastAPI app against a test
Postgres database that is rolled back after every test.
"""

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_REGISTER = {
    "email": "alice@example.com",
    "password": "securepass123",
    "organization_name": "Acme Corp",
}
_LOGIN = {"email": _REGISTER["email"], "password": _REGISTER["password"]}


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

async def test_register_returns_201_with_user_and_org(client):
    resp = await client.post("/api/v1/auth/register", json=_REGISTER)

    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == _REGISTER["email"]
    assert data["role"] == "admin"
    assert data["organization"]["name"] == "Acme Corp"
    assert data["organization"]["slug"] == "acme-corp"
    assert data["organization"]["plan"] == "free"


async def test_register_duplicate_email_returns_409(client):
    await client.post("/api/v1/auth/register", json=_REGISTER)

    resp = await client.post("/api/v1/auth/register", json=_REGISTER)

    assert resp.status_code == 409


async def test_register_short_password_returns_422(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={**_REGISTER, "password": "short"},
    )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

async def test_login_returns_access_and_refresh_tokens(client):
    await client.post("/api/v1/auth/register", json=_REGISTER)

    resp = await client.post("/api/v1/auth/login", json=_LOGIN)

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password_returns_401(client):
    await client.post("/api/v1/auth/register", json=_REGISTER)

    resp = await client.post(
        "/api/v1/auth/login",
        json={**_LOGIN, "password": "wrongpassword"},
    )

    assert resp.status_code == 401


async def test_login_unknown_email_returns_401(client):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever123"},
    )

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

async def test_refresh_returns_new_tokens(client):
    await client.post("/api/v1/auth/register", json=_REGISTER)
    login_resp = await client.post("/api/v1/auth/login", json=_LOGIN)
    old_refresh = login_resp.json()["refresh_token"]

    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
    )

    assert resp.status_code == 200
    assert "access_token" in resp.json()
    assert resp.json()["refresh_token"] != old_refresh


async def test_refresh_rotated_token_cannot_be_reused(client):
    await client.post("/api/v1/auth/register", json=_REGISTER)
    login_resp = await client.post("/api/v1/auth/login", json=_LOGIN)
    old_refresh = login_resp.json()["refresh_token"]
    await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})

    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
    )

    assert resp.status_code == 401


async def test_refresh_invalid_token_returns_401(client):
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": "not.a.real.token"}
    )

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------

async def test_me_returns_current_user(client, auth_headers):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == _REGISTER["email"]
    assert data["is_active"] is True
    assert "organization_id" in data


async def test_me_without_token_returns_401(client):
    resp = await client.get("/api/v1/auth/me")

    assert resp.status_code == 401
