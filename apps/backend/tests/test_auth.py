import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"

@pytest.mark.asyncio
async def test_admin_login_and_me(client: AsyncClient):
    # 1. Login with seeded admin
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert "access_token" in login_data
    token = login_data["access_token"]
    assert login_data["user"]["email"] == "admin@inventory.local"

    # 2. Query /me
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["full_name"] == "Sarah Jenkins (Super Admin)"
    assert me_data["is_superuser"] is True
