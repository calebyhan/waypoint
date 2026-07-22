"""Tests for /auth profile endpoints: Gemini key encryption-at-rest and masking."""

from core.crypto import decrypt, encrypt
from tests.conftest import USER_ID


def _seed_profile(fake_db, user_id=USER_ID, **overrides):
    row = {
        "id": user_id,
        "github_username": "alice",
        "avatar_url": None,
        "gemini_api_key": None,
        "github_token": None,
    }
    row.update(overrides)
    fake_db.seed("profiles", [row])
    return row


def _stored_key(fake_db, user_id=USER_ID):
    return fake_db.table("profiles").select("*").eq("id", user_id).single().execute().data["gemini_api_key"]


def test_update_me_encrypts_gemini_key_at_rest(client, fake_db):
    _seed_profile(fake_db)

    res = client.patch("/auth/me", json={"gemini_api_key": "AIzaSySecretKey1234"})

    assert res.status_code == 200
    stored = _stored_key(fake_db)
    assert stored != "AIzaSySecretKey1234"  # not plaintext
    assert decrypt(stored) == "AIzaSySecretKey1234"  # round-trips
    # The response never exposes the raw key.
    assert "AIzaSySecretKey1234" not in res.text
    assert res.json()["has_gemini_key"] is True
    assert res.json()["gemini_api_key"].endswith("1234")


def test_get_me_masks_gemini_key(client, fake_db):
    _seed_profile(fake_db, gemini_api_key=encrypt("AIzaSySecretKey1234"))

    res = client.get("/auth/me")

    assert res.status_code == 200
    body = res.json()
    assert body["has_gemini_key"] is True
    assert body["gemini_api_key"] == "••••1234"
    assert "AIzaSySecretKey1234" not in res.text
    assert "github_token" not in body


def test_get_me_handles_legacy_plaintext_key(client, fake_db):
    # Rows written before encryption shipped hold plaintext; they must still
    # register as configured and be masked, not break or leak.
    _seed_profile(fake_db, gemini_api_key="legacy-plaintext-abcd")

    res = client.get("/auth/me")

    assert res.status_code == 200
    body = res.json()
    assert body["has_gemini_key"] is True
    assert body["gemini_api_key"] == "••••abcd"
    assert "legacy-plaintext-abcd" not in res.text


def test_get_me_without_key(client, fake_db):
    _seed_profile(fake_db)

    res = client.get("/auth/me")

    assert res.status_code == 200
    assert res.json()["has_gemini_key"] is False
    assert res.json()["gemini_api_key"] is None


def test_update_me_ignores_masked_resubmission(client, fake_db):
    original = encrypt("AIzaSySecretKey1234")
    _seed_profile(fake_db, gemini_api_key=original)

    # Frontend echoes the masked value back on save — must not overwrite the key.
    res = client.patch("/auth/me", json={"gemini_api_key": "••••1234"})

    assert res.status_code == 200
    assert _stored_key(fake_db) == original
    assert res.json()["has_gemini_key"] is True


def test_update_me_clears_key_with_empty_string(client, fake_db):
    _seed_profile(fake_db, gemini_api_key=encrypt("AIzaSySecretKey1234"))

    res = client.patch("/auth/me", json={"gemini_api_key": ""})

    assert res.status_code == 200
    assert _stored_key(fake_db) is None
    assert res.json()["has_gemini_key"] is False
