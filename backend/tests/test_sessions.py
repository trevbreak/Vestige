import pytest

SESSION_PAYLOAD = {
    "name": "The Mines of Phandelver — Session 1",
    "campaign_name": "Lost Mine of Phandelver",
    "avatar_ids": [],
    "avatar_modes": {},
}


@pytest.mark.asyncio
async def test_create_session(client):
    r = await client.post("/api/sessions/", json=SESSION_PAYLOAD)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == SESSION_PAYLOAD["name"]
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_list_sessions(client):
    await client.post("/api/sessions/", json=SESSION_PAYLOAD)
    r = await client.get("/api/sessions/")
    assert r.status_code == 200
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_end_session(client):
    created = (await client.post("/api/sessions/", json=SESSION_PAYLOAD)).json()
    r = await client.post(f"/api/sessions/{created['id']}/end")
    assert r.status_code == 200
    data = r.json()
    assert data["is_active"] is False
    assert data["ended_at"] is not None


@pytest.mark.asyncio
async def test_update_session(client):
    created = (await client.post("/api/sessions/", json=SESSION_PAYLOAD)).json()
    r = await client.patch(f"/api/sessions/{created['id']}", json={"name": "Updated Name"})
    assert r.status_code == 200
    assert r.json()["name"] == "Updated Name"
