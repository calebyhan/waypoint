import hashlib
import hmac

from routers.webhooks import _verify_signature

SECRET = "shh-its-a-secret"


def sign(payload: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def test_valid_signature_is_accepted():
    payload = b'{"action": "opened"}'
    assert _verify_signature(payload, sign(payload), SECRET) is True


def test_signature_with_wrong_secret_is_rejected():
    payload = b'{"action": "opened"}'
    assert _verify_signature(payload, sign(payload, secret="wrong-secret"), SECRET) is False


def test_tampered_payload_is_rejected():
    payload = b'{"action": "opened"}'
    signature = sign(payload)
    tampered_payload = b'{"action": "closed"}'
    assert _verify_signature(tampered_payload, signature, SECRET) is False


def test_missing_signature_is_rejected():
    assert _verify_signature(b"{}", None, SECRET) is False
