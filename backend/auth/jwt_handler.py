import hmac
import hashlib
import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from backend.config import get_settings

settings = get_settings()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _hash_pw(password: str) -> str:
    salt = base64.b64encode(hmac.new(settings.SECRET_KEY.encode(), password.encode(), hashlib.sha256).digest()).decode()
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return f"{salt}:{base64.b64encode(h).decode()}"


def _check_pw(password: str, stored: str) -> bool:
    try:
        salt, stored_hash = stored.split(":", 1)
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
        return base64.b64encode(h).decode() == stored_hash
    except Exception:
        return False


DEMO_USERS = {
    "admin": {"username": "admin", "full_name": "관리자", "role": "SUPER_ADMIN", "disabled": False, "password": "admin1234"},
    "manager": {"username": "manager", "full_name": "매니저", "role": "MANAGER", "disabled": False, "password": "manager1234"},
    "staff": {"username": "staff", "full_name": "직원", "role": "STAFF", "disabled": False, "password": "staff1234"},
}


def get_user(username: str) -> Optional[dict]:
    return DEMO_USERS.get(username)


def _find_sheet_user(username: str) -> Optional[dict]:
    """USER_MASTER 시트에서 username 으로 사용자 조회 (지연 import 로 순환 의존 회피)."""
    try:
        from backend.services.sheets_service import get_sheets_service
        svc = get_sheets_service()
        users = svc.get_all("USER_MASTER")
    except Exception:
        return None
    for u in users:
        if str(u.get("username", "")).strip() == username:
            return u
    return None


def authenticate_user(username: str, password: str) -> Optional[dict]:
    sheet_user = _find_sheet_user(username)
    if sheet_user:
        if sheet_user.get("status", "활성") == "비활성":
            return None
        if not _check_pw(password, sheet_user.get("password_hash", "")):
            return None
        try:
            from backend.services.sheets_service import get_sheets_service
            from datetime import datetime as _dt
            get_sheets_service().update_row(
                "USER_MASTER", "user_id", sheet_user.get("user_id", ""),
                {"last_login_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S")},
            )
        except Exception:
            pass
        return {
            "username": sheet_user.get("username", ""),
            "full_name": sheet_user.get("full_name", ""),
            "role": sheet_user.get("role", "STAFF"),
        }

    user = get_user(username)
    if not user or user.get("disabled"):
        return None
    if user.get("password") != password:
        return None
    return {k: v for k, v in user.items() if k != "password"}


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload["exp"] = int(expire.timestamp())
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps(payload).encode())
    sig_input = f"{header}.{body}".encode()
    sig = _b64url_encode(hmac.new(settings.SECRET_KEY.encode(), sig_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def decode_token(token: str) -> Optional[dict]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, body, sig = parts
        sig_input = f"{header}.{body}".encode()
        expected = _b64url_encode(hmac.new(settings.SECRET_KEY.encode(), sig_input, hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64url_decode(body))
        if payload.get("exp", 0) < datetime.now(timezone.utc).timestamp():
            return None
        return payload
    except Exception:
        return None
