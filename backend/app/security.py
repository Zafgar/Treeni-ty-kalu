"""Kevyt pääsynhallinta profiililukkoa varten — pelkkää Python-standardikirjastoa.

Idea (kavereille jaettava yhteinen instanssi, ei pankkitason turva):
  - PT (admin) asettaa admin-PINin -> lukko menee päälle.
  - Kukin profiili voi saada oman PINin.
  - Admin näkee kaikki profiilit; tavallinen käyttäjä pääsee vain omaansa.
  - Ensisijainen tarkoitus: kukaan ei vahingossa kirjaa väärälle profiilille.

Tokenit ovat HMAC-allekirjoitettuja (ei salattuja) — riittää estämään
väärentäminen ilman ulkoisia riippuvuuksia. PINit tallennetaan pbkdf2-tiivisteinä.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

_PBKDF2_ROUNDS = 120_000
_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 vrk


def hash_pin(pin: str) -> str:
    """Tiivistä PIN pbkdf2:lla satunnaisella suolalla. Palauttaa
    'pbkdf2$<kierrokset>$<suola_b64>$<tiiviste_b64>'."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, _PBKDF2_ROUNDS)
    return "pbkdf2${}${}${}".format(
        _PBKDF2_ROUNDS,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_pin(pin: str, stored: str | None) -> bool:
    """Tarkista PIN tallennettua tiivistettä vastaan (vakioaikainen vertailu)."""
    if not stored:
        return False
    try:
        scheme, rounds_s, salt_b64, hash_b64 = stored.split("$")
        if scheme != "pbkdf2":
            return False
        rounds = int(rounds_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, rounds)
    return hmac.compare_digest(dk, expected)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_token(secret: str, *, role: str, profile_id: int | None) -> str:
    """Luo allekirjoitettu token. role='admin' näkee kaiken; role='profile' on
    sidottu yhteen profiiliin. Muoto '<payload_b64>.<sig_b64>'."""
    payload = {
        "role": role,
        "pid": profile_id,
        "exp": int(time.time()) + _TOKEN_TTL_SECONDS,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    return "{}.{}".format(_b64url(raw), _b64url(sig))


def read_token(secret: str, token: str | None) -> dict | None:
    """Vahvista allekirjoitus + vanhentuminen. Palauttaa payloadin tai None."""
    if not token or "." not in token:
        return None
    try:
        raw_b64, sig_b64 = token.split(".", 1)
        raw = _b64url_decode(raw_b64)
        sig = _b64url_decode(sig_b64)
    except (ValueError, TypeError):
        return None
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if payload.get("exp", 0) < int(time.time()):
        return None
    return payload


def new_secret() -> str:
    """Satunnainen token-allekirjoitusavain (luodaan kerran, tallennetaan kantaan)."""
    return secrets.token_hex(32)
