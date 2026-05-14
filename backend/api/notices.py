from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, require_auth, paginate

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "NOTICE"

ADMIN_ROLES = ("SUPER_ADMIN", "ADMIN")


def _is_admin(user: dict) -> bool:
    return bool(user) and user.get("role") in ADMIN_ROLES


def _require_login(request: Request):
    user = require_auth(request)
    if not user:
        return None, RedirectResponse(url="/login", status_code=303)
    return user, None


def _require_admin(request: Request):
    user, redirect = _require_login(request)
    if redirect:
        return None, redirect
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="공지사항 관리 권한이 없습니다.")
    return user, None


def _sort_notices(items: list[dict]) -> list[dict]:
    """고정(is_pinned=Y) 우선, 그 다음 최신순."""
    return sorted(
        items,
        key=lambda n: (
            0 if str(n.get("is_pinned", "")).upper() == "Y" else 1,
            -1 * len(n.get("created_at", "")),
            n.get("created_at", ""),
        ),
        reverse=False,
    )


@router.get("/notices", response_class=HTMLResponse)
async def notices_list(request: Request, q: str = "", page: int = 1):
    user, redirect = _require_login(request)
    if redirect:
        return redirect
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["title", "content", "author"]) if q else svc.get_all(SHEET)
    pinned = [n for n in data if str(n.get("is_pinned", "")).upper() == "Y"]
    others = [n for n in data if str(n.get("is_pinned", "")).upper() != "Y"]
    pinned.sort(key=lambda n: n.get("created_at", ""), reverse=True)
    others.sort(key=lambda n: n.get("created_at", ""), reverse=True)
    ordered = pinned + others
    paged = paginate(ordered, page)
    return templates.TemplateResponse(request, "notices/index.html", {
        "user": user, "q": q, "is_admin": _is_admin(user),
        **paged,
    })


@router.get("/notices/new", response_class=HTMLResponse)
async def notices_new(request: Request):
    user, redirect = _require_admin(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "notices/form.html", {
        "user": user, "item": None, "action": "create",
    })


@router.post("/notices/new")
async def notices_create(
    request: Request,
    title: str = Form(...),
    content: str = Form(""),
    is_pinned: str = Form("N"),
):
    user, redirect = _require_admin(request)
    if redirect:
        return redirect
    svc = get_sheets_service()
    title = title.strip()
    if not title:
        return templates.TemplateResponse(request, "notices/form.html", {
            "user": user, "item": {"title": title, "content": content, "is_pinned": is_pinned},
            "action": "create", "error": "제목을 입력하세요.",
        }, status_code=400)
    ts = now_str()
    svc.append_row(SHEET, {
        "notice_id": generate_id("NTC"),
        "title": title,
        "content": content,
        "author": user.get("username", ""),
        "is_pinned": "Y" if str(is_pinned).upper() == "Y" else "N",
        "created_at": ts,
        "updated_at": ts,
    })
    return RedirectResponse(url="/notices", status_code=303)


@router.get("/notices/{notice_id}", response_class=HTMLResponse)
async def notices_detail(request: Request, notice_id: str):
    user, redirect = _require_login(request)
    if redirect:
        return redirect
    svc = get_sheets_service()
    items = svc.get_all(SHEET)
    item = next((n for n in items if n.get("notice_id") == notice_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")
    return templates.TemplateResponse(request, "notices/detail.html", {
        "user": user, "item": item, "is_admin": _is_admin(user),
    })


@router.get("/notices/{notice_id}/edit", response_class=HTMLResponse)
async def notices_edit(request: Request, notice_id: str):
    user, redirect = _require_admin(request)
    if redirect:
        return redirect
    svc = get_sheets_service()
    items = svc.get_all(SHEET)
    item = next((n for n in items if n.get("notice_id") == notice_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")
    return templates.TemplateResponse(request, "notices/form.html", {
        "user": user, "item": item, "action": "edit",
    })


@router.post("/notices/{notice_id}/edit")
async def notices_update(
    request: Request,
    notice_id: str,
    title: str = Form(...),
    content: str = Form(""),
    is_pinned: str = Form("N"),
):
    user, redirect = _require_admin(request)
    if redirect:
        return redirect
    svc = get_sheets_service()
    items = svc.get_all(SHEET)
    item = next((n for n in items if n.get("notice_id") == notice_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")
    title = title.strip()
    if not title:
        merged = dict(item)
        merged.update({"title": title, "content": content, "is_pinned": is_pinned})
        return templates.TemplateResponse(request, "notices/form.html", {
            "user": user, "item": merged, "action": "edit", "error": "제목을 입력하세요.",
        }, status_code=400)
    svc.update_row(SHEET, "notice_id", notice_id, {
        "notice_id": item.get("notice_id"),
        "title": title,
        "content": content,
        "author": item.get("author", user.get("username", "")),
        "is_pinned": "Y" if str(is_pinned).upper() == "Y" else "N",
        "created_at": item.get("created_at", ""),
    })
    return RedirectResponse(url=f"/notices/{notice_id}", status_code=303)


@router.post("/notices/{notice_id}/delete")
async def notices_delete(request: Request, notice_id: str):
    user, redirect = _require_admin(request)
    if redirect:
        return redirect
    svc = get_sheets_service()
    svc.delete_row(SHEET, "notice_id", notice_id)
    return RedirectResponse(url="/notices", status_code=303)
