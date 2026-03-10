import pytest

SESSION_PAYLOAD = {"name": "Test Session", "avatar_ids": [], "avatar_modes": {}}

TRANSCRIPT_PAYLOAD = {
    "session_id": None,  # filled in per test
    "speaker": "Aldric",
    "speaker_type": "avatar",
    "text": "I draw my sword and advance on the goblin.",
    "utterance_type": "speech",
}


@pytest.mark.asyncio
async def test_create_and_retrieve_transcript(client):
    session = (await client.post("/api/sessions/", json=SESSION_PAYLOAD)).json()

    payload = {**TRANSCRIPT_PAYLOAD, "session_id": session["id"]}
    r = await client.post("/api/transcripts/", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["text"] == TRANSCRIPT_PAYLOAD["text"]

    r2 = await client.get(f"/api/transcripts/session/{session['id']}")
    assert r2.status_code == 200
    assert len(r2.json()) == 1
    assert r2.json()[0]["speaker"] == "Aldric"


@pytest.mark.asyncio
async def test_transcript_pagination(client):
    session = (await client.post("/api/sessions/", json=SESSION_PAYLOAD)).json()
    for i in range(5):
        await client.post("/api/transcripts/", json={
            **TRANSCRIPT_PAYLOAD, "session_id": session["id"],
            "text": f"Line {i}",
        })

    r = await client.get(f"/api/transcripts/session/{session['id']}?limit=3&offset=0")
    assert len(r.json()) == 3

    r2 = await client.get(f"/api/transcripts/session/{session['id']}?limit=3&offset=3")
    assert len(r2.json()) == 2
