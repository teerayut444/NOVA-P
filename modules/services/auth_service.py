"""
File-based User Authentication Service
======================================
Loads credentials from a UTF-8 `.txt` file (`users.txt` at project root by default),
supports both plain-text and PBKDF2-SHA256 / SHA256 hashed secrets, and provides
session/client lockout helpers against brute-force login attempts.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from pathlib import Path
from typing import Any

import user_logger

_ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_USERS_FILE = _ROOT_DIR / "users.txt"

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 30
_PBKDF2_DEFAULT_ITERATIONS = 260_000


def hash_password(password: str, iterations: int = _PBKDF2_DEFAULT_ITERATIONS) -> str:
    """Hash a plain-text password using PBKDF2-HMAC-SHA256 for storage in users.txt."""
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a non-empty string.")
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(plain_password: str, stored_secret: str) -> bool:
    """Verify a password against plain-text or hashed secret using constant-time comparison."""
    if not isinstance(plain_password, str) or not isinstance(stored_secret, str):
        return False
    if not plain_password or not stored_secret:
        return False

    if stored_secret.startswith("pbkdf2_sha256$"):
        parts = stored_secret.split("$")
        if len(parts) != 4:
            return False
        _, iter_str, salt_hex, expected_hex = parts
        try:
            iterations = int(iter_str)
            if iterations <= 0:
                return False
            salt = bytes.fromhex(salt_hex)
            expected_bytes = bytes.fromhex(expected_hex)
        except ValueError:
            return False
        derived = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(derived, expected_bytes)

    if stored_secret.startswith("sha256$"):
        parts = stored_secret.split("$")
        if len(parts) == 2:
            digest = hashlib.sha256(plain_password.encode("utf-8")).hexdigest()
            return hmac.compare_digest(digest, parts[1].strip().lower())
        if len(parts) == 3:
            _, salt, expected_hex = parts
            digest = hashlib.sha256(f"{salt}{plain_password}".encode("utf-8")).hexdigest()
            return hmac.compare_digest(digest, expected_hex.strip().lower())
        return False

    return hmac.compare_digest(plain_password.encode("utf-8"), stored_secret.encode("utf-8"))


def format_logger_user_name(username: str, display_name: str = "") -> str:
    """Format logged identity as 'display_name (username)' or 'username'."""
    clean_u = user_logger._sanitize_username(username)
    clean_d = user_logger._sanitize_username(display_name)
    if clean_d and clean_d.lower() != clean_u.lower():
        return user_logger._sanitize_username(f"{clean_d} ({clean_u})")
    return clean_u


def load_users(users_file: str | os.PathLike[str] | None = None) -> tuple[dict[str, dict[str, str]], str | None]:
    """
    Parse users from a `.txt` file (`username:password` or `username:password:display_name`).
    Returns `(users_by_lower_username, error_code)`.
    """
    path = Path(users_file) if users_file is not None else DEFAULT_USERS_FILE
    if not path.exists() or not path.is_file():
        return {}, "missing_file"

    users: dict[str, dict[str, str]] = {}
    try:
        raw_text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}, "read_error"

    for raw_line in raw_text.splitlines():
        line = raw_line.rstrip("\r\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = line.split(":", 2)
        if len(parts) < 2:
            continue
        username = parts[0].strip()
        password_secret = parts[1].rstrip("\r\n")
        display_name = parts[2].strip() if len(parts) >= 3 else ""
        if not username or not password_secret:
            continue
        users[username.lower()] = {
            "username": username,
            "password": password_secret,
            "display_name": display_name,
        }

    if not users:
        return {}, "empty_users"
    return users, None


def authenticate_user(
    username: str,
    password: str,
    users_file: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Authenticate a username/password pair against the configured `.txt` user file."""
    clean_input_user = (username or "").strip()
    if not clean_input_user or not password:
        return {
            "ok": False,
            "reason": "empty_input",
            "username": user_logger._sanitize_username(clean_input_user),
            "display_name": "",
            "logger_user_name": "",
        }

    users, err_code = load_users(users_file=users_file)
    if err_code:
        return {
            "ok": False,
            "reason": err_code,
            "username": user_logger._sanitize_username(clean_input_user),
            "display_name": "",
            "logger_user_name": "",
        }

    record = users.get(clean_input_user.lower())
    if not record:
        # Constant-time dummy comparison to avoid trivial timing differences on unknown usernames
        hmac.compare_digest(password.encode("utf-8"), b"__nova_dummy_secret__")
        return {
            "ok": False,
            "reason": "invalid_credentials",
            "username": user_logger._sanitize_username(clean_input_user),
            "display_name": "",
            "logger_user_name": "",
        }

    if not verify_password(password, record["password"]):
        return {
            "ok": False,
            "reason": "invalid_credentials",
            "username": user_logger._sanitize_username(record["username"]),
            "display_name": user_logger._sanitize_username(record["display_name"]),
            "logger_user_name": format_logger_user_name(record["username"], record["display_name"]),
        }

    canonical_user = user_logger._sanitize_username(record["username"])
    display_name = user_logger._sanitize_username(record["display_name"])
    return {
        "ok": True,
        "reason": "ok",
        "username": canonical_user,
        "display_name": display_name,
        "logger_user_name": format_logger_user_name(canonical_user, display_name),
    }


def check_lockout(attempt_state: dict[str, Any] | None, now: float | None = None) -> int:
    """Return remaining lockout seconds (0 if login attempts are allowed)."""
    if not attempt_state:
        return 0
    cur_now = time.time() if now is None else float(now)
    locked_until = float(attempt_state.get("locked_until", 0.0) or 0.0)
    if locked_until > cur_now:
        return max(1, int(locked_until - cur_now + 0.999))
    return 0


def record_failed_attempt(
    attempt_state: dict[str, Any] | None,
    now: float | None = None,
    max_attempts: int = MAX_FAILED_ATTEMPTS,
    lockout_seconds: int = LOCKOUT_SECONDS,
) -> tuple[dict[str, Any], int]:
    """Increment failed login counter and apply temporary lockout when threshold is reached."""
    cur_now = time.time() if now is None else float(now)
    state = dict(attempt_state or {})
    if float(state.get("locked_until", 0.0) or 0.0) <= cur_now and state.get("locked_until"):
        state["locked_until"] = 0.0
        state["count"] = 0

    count = int(state.get("count", 0) or 0) + 1
    if count >= max_attempts:
        state["count"] = 0
        state["locked_until"] = cur_now + lockout_seconds
        return state, lockout_seconds

    state["count"] = count
    state["locked_until"] = 0.0
    return state, 0


def reset_attempts() -> dict[str, Any]:
    """Return a clean login attempt tracking state."""
    return {"count": 0, "locked_until": 0.0}
