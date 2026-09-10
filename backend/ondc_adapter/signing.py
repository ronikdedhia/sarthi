"""Ed25519 request signing/verification, per the real Beckn/ONDC signing spec:
https://github.com/ONDC-Official/developer-docs/blob/main/registry/signing-verification.md

Real algorithm, not a stub: BLAKE2b-512 digest of the request body, Ed25519-sign that
digest, and build an Authorization header in the exact `Signature keyId="...",
algorithm="ed25519",created="...",expires="...",headers="(created) (expires) digest",
signature="..."` shape the real network uses. ARCHITECTURE.md calls this "the part most
likely to silently break integrations" — get_req_id/nuvama_auto_login.py in the sibling
tick-trade project is a cautionary tale of shipping unverified automation straight to
production, so this ships with real unit tests exercising sign -> verify round trips
(including tamper detection) rather than trusting it unattended.

keyId format: "{subscriber_id}|{unique_key_id}|ed25519".
"""
import base64
import hashlib
from datetime import datetime, timedelta, timezone

import nacl.exceptions
import nacl.signing

SIGNATURE_VALID_SECONDS = 300


class SignatureVerificationError(Exception):
    """Raised when a received request's Authorization header doesn't verify —
    tampered payload, wrong key, or a malformed header, never silently ignored."""


def generate_signing_keypair():
    """Returns (private_key_base64, public_key_base64) — a fresh Ed25519 keypair.
    In production these are generated once and the public key is registered with the
    ONDC registry; for the mock-server setup here, both sides just share the same
    keypair out of Django settings."""
    signing_key = nacl.signing.SigningKey.generate()
    private_b64 = base64.b64encode(bytes(signing_key)).decode()
    public_b64 = base64.b64encode(bytes(signing_key.verify_key)).decode()
    return private_b64, public_b64


def _digest_b64(body_bytes):
    return base64.b64encode(hashlib.blake2b(body_bytes, digest_size=64).digest()).decode()


def _signing_string(digest_b64, created, expires):
    return f"(created): {created}\n(expires): {expires}\ndigest: BLAKE-512={digest_b64}"


def build_authorization_header(body_bytes, private_key_b64, subscriber_id, unique_key_id, now=None):
    """Returns the Authorization header value for a request carrying `body_bytes`."""
    now = now or datetime.now(timezone.utc)
    created = int(now.timestamp())
    expires = int((now + timedelta(seconds=SIGNATURE_VALID_SECONDS)).timestamp())

    digest_b64 = _digest_b64(body_bytes)
    signing_string = _signing_string(digest_b64, created, expires)

    signing_key = nacl.signing.SigningKey(base64.b64decode(private_key_b64))
    signature = signing_key.sign(signing_string.encode()).signature
    signature_b64 = base64.b64encode(signature).decode()

    key_id = f"{subscriber_id}|{unique_key_id}|ed25519"
    return (
        f'Signature keyId="{key_id}",algorithm="ed25519",created="{created}",'
        f'expires="{expires}",headers="(created) (expires) digest",signature="{signature_b64}"'
    )


def _parse_authorization_header(header_value):
    if not header_value.startswith("Signature "):
        raise SignatureVerificationError(f"not a Signature auth header: {header_value!r}")
    fields = {}
    for part in header_value[len("Signature "):].split(","):
        key, _, value = part.partition("=")
        fields[key.strip()] = value.strip().strip('"')
    for required in ("keyId", "created", "expires", "signature"):
        if required not in fields:
            raise SignatureVerificationError(f"Authorization header missing {required!r}: {header_value!r}")
    return fields


def verify_authorization_header(body_bytes, header_value, public_key_b64, now=None):
    """Raises SignatureVerificationError on any failure (expired window, bad signature,
    malformed header) — never returns a silent False, since a caller that forgets to
    check a boolean is exactly how an unverified request gets treated as trusted."""
    now = now or datetime.now(timezone.utc)
    fields = _parse_authorization_header(header_value)

    created, expires = int(fields["created"]), int(fields["expires"])
    if not (created <= int(now.timestamp()) <= expires):
        raise SignatureVerificationError(
            f"signature window expired or not yet valid: created={created}, expires={expires}, now={int(now.timestamp())}"
        )

    digest_b64 = _digest_b64(body_bytes)
    signing_string = _signing_string(digest_b64, created, expires)

    verify_key = nacl.signing.VerifyKey(base64.b64decode(public_key_b64))
    try:
        verify_key.verify(signing_string.encode(), base64.b64decode(fields["signature"]))
    except nacl.exceptions.BadSignatureError as e:
        raise SignatureVerificationError("signature does not match body — tampered or wrong key") from e
