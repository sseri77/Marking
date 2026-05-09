from datetime import datetime
from fastapi import Request, HTTPException
from backend.auth.jwt_handler import decode_token


def generate_id(prefix: str) -> str:
    ts = datetime.now().strftime("%y%m%d%H%M%S%f")[:16]
    return f"{prefix}{ts}"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="인증이 만료되었습니다.")
    return {"username": payload.get("sub"), "role": payload.get("role")}


def require_auth(request: Request) -> dict:
    try:
        return get_current_user(request)
    except HTTPException:
        return None


def paginate(items: list, page: int = 1, per_page: int = 20) -> dict:
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "items": items[start:end],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }
