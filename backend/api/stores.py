from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, require_auth, paginate

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "STORE_MASTER"


@router.get("/stores", response_class=HTMLResponse)
async def stores_list(request: Request, q: str = "", page: int = 1):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["store_name", "contact", "phone", "address"]) if q else svc.get_all(SHEET)
    paged = paginate(data, page)
    return templates.TemplateResponse(request, "stores/index.html", {
        "user": user, "q": q, **paged,
    })


@router.get("/stores/new", response_class=HTMLResponse)
async def stores_new(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "stores/form.html", {
        "user": user, "item": None, "action": "create",
    })


@router.post("/stores/new")
async def stores_create(
    request: Request,
    store_name: str = Form(...),
    contact: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    memo: str = Form(""),
    status: str = Form("활성"),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()

    existing = svc.get_all(SHEET)
    if any(s.get("store_name", "").strip() == store_name.strip() for s in existing):
        return templates.TemplateResponse(request, "stores/form.html", {
            "user": user, "item": None, "action": "create",
            "error": f"매장 '{store_name}' 는 이미 등록되어 있습니다.",
        }, status_code=400)

    ts = now_str()
    svc.append_row(SHEET, {
        "store_id": generate_id("STR"),
        "store_name": store_name,
        "contact": contact,
        "phone": phone,
        "address": address,
        "memo": memo,
        "status": status,
        "created_at": ts,
        "updated_at": ts,
    })
    return RedirectResponse(url="/stores", status_code=303)


@router.get("/stores/{store_id}/edit", response_class=HTMLResponse)
async def stores_edit(request: Request, store_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    items = svc.get_all(SHEET)
    item = next((s for s in items if s["store_id"] == store_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="매장을 찾을 수 없습니다.")
    return templates.TemplateResponse(request, "stores/form.html", {
        "user": user, "item": item, "action": "edit",
    })


@router.post("/stores/{store_id}/edit")
async def stores_update(
    request: Request,
    store_id: str,
    store_name: str = Form(...),
    contact: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    memo: str = Form(""),
    status: str = Form("활성"),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()

    existing = svc.get_all(SHEET)
    if any(s.get("store_name", "").strip() == store_name.strip() and s.get("store_id") != store_id for s in existing):
        item = next((s for s in existing if s["store_id"] == store_id), None)
        return templates.TemplateResponse(request, "stores/form.html", {
            "user": user, "item": item, "action": "edit",
            "error": f"매장 '{store_name}' 는 이미 등록되어 있습니다.",
        }, status_code=400)

    svc.update_row(SHEET, "store_id", store_id, {
        "store_name": store_name,
        "contact": contact,
        "phone": phone,
        "address": address,
        "memo": memo,
        "status": status,
        "updated_at": now_str(),
    })
    return RedirectResponse(url="/stores", status_code=303)


@router.post("/stores/{store_id}/delete")
async def stores_delete(request: Request, store_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.delete_row(SHEET, "store_id", store_id)
    return RedirectResponse(url="/stores", status_code=303)


@router.get("/api/stores")
async def api_stores_list(q: str = "", active_only: bool = False):
    """매장 조회 API."""
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["store_name", "contact", "phone", "address"]) if q else svc.get_all(SHEET)
    if active_only:
        data = [s for s in data if s.get("status", "활성") == "활성"]
    return data
