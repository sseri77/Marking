from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.auth.jwt_handler import _hash_pw
from backend.utils.helpers import generate_id, now_str, require_auth, paginate
from backend.schemas.user import ROLE_CHOICES, STATUS_CHOICES

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "USER_MASTER"

ROLE_LABELS = dict(ROLE_CHOICES)


def _require_admin(request: Request):
    user = require_auth(request)
    if not user:
        return None, RedirectResponse(url="/login", status_code=303)
    if user.get("role") not in ("SUPER_ADMIN", "ADMIN"):
        raise HTTPException(status_code=403, detail="계정 관리 권한이 없습니다.")
    return user, None


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_list(request: Request, q: str = "", page: int = 1):
    user, redirect = _require_admin(request)
    if redirect:
        return redirect
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["username", "full_name", "role"]) if q else svc.get_all(SHEET)
    data = sorted(data, key=lambda u: u.get("created_at", ""), reverse=True)
    paged = paginate(data, page)
    return templates.TemplateResponse(request, "accounts/index.html", {
        "user": user, "q": q,
        "role_labels": ROLE_LABELS,
        **paged,
    })


@router.get("/accounts/new", response_class=HTMLResponse)
async def accounts_new(request: Request):
    user, redirect = _require_admin(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "accounts/form.html", {
        "user": user, "item": None, "action": "create",
        "role_choices": ROLE_CHOICES, "status_choices": STATUS_CHOICES,
    })


@router.post("/accounts/new")
async def accounts_create(
    request: Request,
    username: str = Form(...),
    full_name: str = Form(""),
    role: str = Form("STAFF"),
    password: str = Form(...),
    password_confirm: str = Form(...),
    status: str = Form("활성"),
    memo: str = Form(""),
):
    user, redirect = _require_admin(request)
    if redirect:
        return redirect
    svc = get_sheets_service()

    username = username.strip()
    error = None
    if not username:
        error = "아이디를 입력하세요."
    elif len(password) < 4:
        error = "비밀번호는 4자 이상이어야 합니다."
    elif password != password_confirm:
        error = "비밀번호가 일치하지 않습니다."
    elif role not in dict(ROLE_CHOICES):
        error = "유효하지 않은 권한 등급입니다."
    else:
        existing = svc.get_all(SHEET)
        if any(str(u.get("username", "")).strip() == username for u in existing):
            error = f"아이디 '{username}' 는 이미 사용 중입니다."

    if error:
        return templates.TemplateResponse(request, "accounts/form.html", {
            "user": user, "item": {
                "username": username, "full_name": full_name, "role": role,
                "status": status, "memo": memo,
            },
            "action": "create",
            "role_choices": ROLE_CHOICES, "status_choices": STATUS_CHOICES,
            "error": error,
        }, status_code=400)

    ts = now_str()
    svc.append_row(SHEET, {
        "user_id": generate_id("USR"),
        "username": username,
        "full_name": full_name,
        "role": role,
        "password_hash": _hash_pw(password),
        "status": status,
        "permissions": "",
        "memo": memo,
        "last_login_at": "",
        "created_at": ts,
        "updated_at": ts,
    })
    return RedirectResponse(url="/accounts", status_code=303)


@router.get("/accounts/{user_id}/edit", response_class=HTMLResponse)
async def accounts_edit(request: Request, user_id: str):
    user, redirect = _require_admin(request)
    if redirect:
        return redirect
    svc = get_sheets_service()
    items = svc.get_all(SHEET)
    item = next((u for u in items if u.get("user_id") == user_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    return templates.TemplateResponse(request, "accounts/form.html", {
        "user": user, "item": item, "action": "edit",
        "role_choices": ROLE_CHOICES, "status_choices": STATUS_CHOICES,
    })


@router.post("/accounts/{user_id}/edit")
async def accounts_update(
    request: Request,
    user_id: str,
    full_name: str = Form(""),
    role: str = Form("STAFF"),
    status: str = Form("활성"),
    memo: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
):
    user, redirect = _require_admin(request)
    if redirect:
        return redirect
    svc = get_sheets_service()

    items = svc.get_all(SHEET)
    item = next((u for u in items if u.get("user_id") == user_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    error = None
    if role not in dict(ROLE_CHOICES):
        error = "유효하지 않은 권한 등급입니다."
    elif password or password_confirm:
        if len(password) < 4:
            error = "비밀번호는 4자 이상이어야 합니다."
        elif password != password_confirm:
            error = "비밀번호가 일치하지 않습니다."

    if error:
        merged = dict(item)
        merged.update({"full_name": full_name, "role": role, "status": status, "memo": memo})
        return templates.TemplateResponse(request, "accounts/form.html", {
            "user": user, "item": merged, "action": "edit",
            "role_choices": ROLE_CHOICES, "status_choices": STATUS_CHOICES,
            "error": error,
        }, status_code=400)

    update = {
        "user_id": item.get("user_id"),
        "username": item.get("username"),
        "full_name": full_name,
        "role": role,
        "password_hash": _hash_pw(password) if password else item.get("password_hash", ""),
        "status": status,
        "permissions": item.get("permissions", ""),
        "memo": memo,
        "last_login_at": item.get("last_login_at", ""),
        "created_at": item.get("created_at", ""),
    }
    svc.update_row(SHEET, "user_id", user_id, update)
    return RedirectResponse(url="/accounts", status_code=303)


@router.post("/accounts/{user_id}/delete")
async def accounts_delete(request: Request, user_id: str):
    user, redirect = _require_admin(request)
    if redirect:
        return redirect
    svc = get_sheets_service()
    items = svc.get_all(SHEET)
    target = next((u for u in items if u.get("user_id") == user_id), None)
    if target and target.get("username") == user.get("username"):
        raise HTTPException(status_code=400, detail="현재 로그인 중인 계정은 삭제할 수 없습니다.")
    svc.delete_row(SHEET, "user_id", user_id)
    return RedirectResponse(url="/accounts", status_code=303)
