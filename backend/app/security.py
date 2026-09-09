"""
Shared-secret packet signing + replay protection for the telemetry ingest
link (udp:127.0.0.1:14550).

Why this exists instead of real MAVLink v2 binary signing: MAVLink v2's
built-in signing scheme (a 48-bit timestamp + link_id + HMAC-SHA256 trailer
appended to the binary frame) operates on actual encoded MAVLink messages
via pymavlink. This project's UDP transport currently carries JSON envelopes,
not binary MAVLink frames — swapping that wire format is a separate, larger
piece of work (needs a custom dialect for CHT/RPM/oil-pressure fields).

This module gives the SAME security property in the meantime:
  - Authenticity: only someone holding MAVLINK_SHARED_SECRET can produce a
    signature that verifies, so spoofed frames from an unauthorized sender
    are rejected.
  - Integrity: any tampering with the payload changes the signature.
  - Freshness / anti-replay: a timestamp window plus a short-lived seen-set
    of signatures rejects captured-and-resent packets.

TODO (upgrade path): once the ingestion wire format moves to real encoded
MAVLink v2 messages, switch to pymavlink's native mav.signing (set_key,
sign_outgoing) instead of this module — that also gets you link_id-based
multi-sender bookkeeping for free.
"""

import hashlib
import hmac
import time


def _derive_key(shared_secret: str) -> bytes:
    # MAVLink v2's own signing spec also derives its 32-byte key via
    # SHA256 of a passphrase — mirroring that here for consistency.
    return hashlib.sha256(shared_secret.encode("utf-8")).digest()


def sign_payload(canonical_payload: bytes, timestamp: float, shared_secret: str) -> str:
    """Return a hex HMAC-SHA256 signature over (timestamp || payload)."""
    key = _derive_key(shared_secret)
    message = f"{timestamp:.6f}".encode("utf-8") + b"|" + canonical_payload
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def verify_signature(
    canonical_payload: bytes,
    timestamp: float,
    signature_hex: str,
    shared_secret: str,
    max_age_seconds: float = 5.0,
) -> tuple[bool, str]:
    """Check freshness then signature. Returns (ok, reason)."""
    if not shared_secret:
        return False, "no shared secret configured"
    now = time.time()
    if abs(now - timestamp) > max_age_seconds:
        return False, "timestamp outside freshness window (stale or replayed)"
    expected = sign_payload(canonical_payload, timestamp, shared_secret)
    # Constant-time compare — a naive == here would leak timing info an
    # attacker could use to forge a valid signature byte-by-byte.
    if not hmac.compare_digest(expected, signature_hex):
        return False, "signature mismatch (spoofed or tampered packet)"
    return True, "ok"


class ReplayGuard:
    """Tracks recently-seen signatures so a captured valid packet can't be
    resent within the freshness window and accepted twice.
    """

    def __init__(self, window_seconds: float = 5.0) -> None:
        self._seen: dict[str, float] = {}
        self._window = window_seconds

    def check_and_record(self, signature_hex: str) -> bool:
        now = time.time()
        for sig, seen_at in list(self._seen.items()):
            if now - seen_at > self._window:
                del self._seen[sig]
        if signature_hex in self._seen:
            return False
        self._seen[signature_hex] = now
        return True
