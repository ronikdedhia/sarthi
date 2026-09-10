from datetime import datetime, timedelta, timezone

import pytest

from ondc_adapter.signing import (
    SignatureVerificationError,
    build_authorization_header,
    generate_signing_keypair,
    verify_authorization_header,
)


def test_a_correctly_signed_request_verifies():
    private_key, public_key = generate_signing_keypair()
    body = b'{"context": {"action": "search"}}'

    header = build_authorization_header(body, private_key, "sarthi.example", "key1")

    verify_authorization_header(body, header, public_key)  # must not raise


def test_a_tampered_body_fails_verification():
    private_key, public_key = generate_signing_keypair()
    body = b'{"context": {"action": "search"}}'
    header = build_authorization_header(body, private_key, "sarthi.example", "key1")

    tampered_body = b'{"context": {"action": "confirm"}}'

    with pytest.raises(SignatureVerificationError):
        verify_authorization_header(tampered_body, header, public_key)


def test_a_signature_from_the_wrong_keypair_fails_verification():
    private_key, _ = generate_signing_keypair()
    _, someone_elses_public_key = generate_signing_keypair()
    body = b'{"context": {"action": "search"}}'
    header = build_authorization_header(body, private_key, "sarthi.example", "key1")

    with pytest.raises(SignatureVerificationError):
        verify_authorization_header(body, header, someone_elses_public_key)


def test_an_expired_signature_window_fails_verification():
    private_key, public_key = generate_signing_keypair()
    body = b'{"context": {}}'
    long_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    header = build_authorization_header(body, private_key, "sarthi.example", "key1", now=long_ago)

    with pytest.raises(SignatureVerificationError):
        verify_authorization_header(body, header, public_key)


def test_key_id_is_built_from_subscriber_and_key_id():
    private_key, _ = generate_signing_keypair()
    body = b"{}"

    header = build_authorization_header(body, private_key, "sarthi.example", "abc123")

    assert 'keyId="sarthi.example|abc123|ed25519"' in header


def test_malformed_authorization_header_raises_rather_than_crashing():
    _, public_key = generate_signing_keypair()

    with pytest.raises(SignatureVerificationError):
        verify_authorization_header(b"{}", "not a real header", public_key)
