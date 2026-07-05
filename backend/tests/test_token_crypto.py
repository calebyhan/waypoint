from core.crypto import decrypt, encrypt
from services.github import get_github_token


def test_encrypt_decrypt_round_trip():
    token = "gho_abc123"
    ciphertext = encrypt(token)
    assert ciphertext != token
    assert decrypt(ciphertext) == token


def test_decrypt_rejects_plaintext_legacy_value():
    assert decrypt("gho_plaintext_legacy_token") is None


def test_get_github_token_returns_none_for_legacy_plaintext(fake_db):
    fake_db.table("profiles").insert({
        "id": "11111111-1111-1111-1111-111111111111",
        "github_username": "octocat",
        "github_token": "gho_plaintext_legacy_token",
    }).execute()
    assert get_github_token(fake_db, "11111111-1111-1111-1111-111111111111") is None


def test_get_github_token_decrypts_stored_token(fake_db):
    token = "gho_abc123"
    fake_db.table("profiles").insert({
        "id": "22222222-2222-2222-2222-222222222222",
        "github_username": "octocat",
        "github_token": encrypt(token),
    }).execute()
    assert get_github_token(fake_db, "22222222-2222-2222-2222-222222222222") == token
