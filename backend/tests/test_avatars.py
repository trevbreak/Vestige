import pytest

AVATAR_PAYLOAD = {
    "name": "Aelindra",
    "player_name": "Sarah",
    "race": "Elf",
    "char_class": "Ranger",
    "level": 5,
    "alignment": "Chaotic Good",
    "strength": 12, "dexterity": 18, "constitution": 14,
    "intelligence": 12, "wisdom": 15, "charisma": 10,
    "hit_points_max": 42, "hit_points_current": 42,
    "armor_class": 15, "speed": 35, "proficiency_bonus": 3,
    "backstory": "Grew up in the Misty Forest.",
    "sentence_style": "short, precise",
    "mode": "active",
}


@pytest.mark.asyncio
async def test_create_avatar(client):
    r = await client.post("/api/avatars/", json=AVATAR_PAYLOAD)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Aelindra"
    assert data["id"] is not None
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_list_avatars(client):
    await client.post("/api/avatars/", json=AVATAR_PAYLOAD)
    r = await client.get("/api/avatars/")
    assert r.status_code == 200
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_get_avatar(client):
    created = (await client.post("/api/avatars/", json=AVATAR_PAYLOAD)).json()
    r = await client.get(f"/api/avatars/{created['id']}")
    assert r.status_code == 200
    assert r.json()["name"] == "Aelindra"


@pytest.mark.asyncio
async def test_get_avatar_not_found(client):
    r = await client.get("/api/avatars/9999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_avatar(client):
    created = (await client.post("/api/avatars/", json=AVATAR_PAYLOAD)).json()
    r = await client.patch(f"/api/avatars/{created['id']}", json={"level": 6, "hit_points_max": 50})
    assert r.status_code == 200
    data = r.json()
    assert data["level"] == 6
    assert data["hit_points_max"] == 50


@pytest.mark.asyncio
async def test_delete_avatar_archives(client):
    created = (await client.post("/api/avatars/", json=AVATAR_PAYLOAD)).json()
    r = await client.delete(f"/api/avatars/{created['id']}")
    assert r.status_code == 204
    # Should not appear in default list
    r2 = await client.get("/api/avatars/")
    ids = [a["id"] for a in r2.json()]
    assert created["id"] not in ids
    # But appears with include_inactive
    r3 = await client.get("/api/avatars/?include_inactive=true")
    ids3 = [a["id"] for a in r3.json()]
    assert created["id"] in ids3


@pytest.mark.asyncio
async def test_set_avatar_mode(client):
    created = (await client.post("/api/avatars/", json=AVATAR_PAYLOAD)).json()
    r = await client.patch(f"/api/avatars/{created['id']}/mode?mode=passive")
    assert r.status_code == 200
    assert r.json()["mode"] == "passive"


@pytest.mark.asyncio
async def test_set_avatar_mode_invalid(client):
    created = (await client.post("/api/avatars/", json=AVATAR_PAYLOAD)).json()
    r = await client.patch(f"/api/avatars/{created['id']}/mode?mode=banished")
    assert r.status_code == 400
