from datetime import datetime
from fastapi import Request, HTTPException
from backend.auth.jwt_handler import decode_token

KO_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def generate_id(prefix: str) -> str:
    ts = datetime.now().strftime("%y%m%d%H%M%S%f")[:16]
    return f"{prefix}{ts}"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def day_of_week(date_str: str) -> str:
    """'YYYY-MM-DD' 문자열을 받아 한국어 요일 반환 (예: '일요일')"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return KO_WEEKDAYS[dt.weekday()] + "요일"
    except Exception:
        return ""


def generate_roll_no(existing_rolls: list, date_str: str) -> str:
    """당일 기준 순번 롤번호 자동 생성: R-YYYYMMDD-NNN"""
    compact = date_str.replace("-", "")
    prefix = f"R-{compact}-"
    max_seq = 0
    for r in existing_rolls:
        rno = str(r.get("roll_no", ""))
        if rno.startswith(prefix):
            try:
                seq = int(rno[len(prefix):])
                if seq > max_seq:
                    max_seq = seq
            except ValueError:
                pass
    return f"{prefix}{max_seq + 1:03d}"


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
