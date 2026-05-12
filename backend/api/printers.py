from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, require_auth, paginate

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "PRINTER_MASTER"


@router.get("/printers", response_class=HTMLResponse)
async def printers_list(request: Request, q: str = "", page: int = 1):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["printer_name", "contact", "phone"]) if q else svc.get_all(SHEET)
    paged = paginate(data, page)
    return templates.TemplateResponse(request, "printers/index.html", {
        "user": user, "q": q, **paged,
    })


@router.get("/printers/new", response_class=HTMLResponse)
async def printers_new(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "printers/form.html", {
        "user": user, "item": None, "action": "create",
    })


@router.post("/printers/new")
async def printers_create(
    request: Request,
    printer_name: str = Form(...),
    contact: str = Form(""),
    phone: str = Form(""),
    memo: str = Form(""),
    status: str = Form("활성"),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()

    # 인쇄업체명 중복 검사
    existing = svc.get_all(SHEET)
    if any(p.get("printer_name", "").strip() == printer_name.strip() for p in existing):
        return templates.TemplateResponse(request, "printers/form.html", {
            "user": user, "item": None, "action": "create",
            "error": f"인쇄업체 '{printer_name}' 는 이미 등록되어 있습니다.",
        }, status_code=400)

    ts = now_str()
    svc.append_row(SHEET, {
        "printer_id": generate_id("PRT"),
        "printer_name": printer_name,
        "contact": contact,
        "phone": phone,
        "memo": memo,
        "status": status,
        "created_at": ts,
        "updated_at": ts,
    })
    return RedirectResponse(url="/printers", status_code=303)


@router.get("/printers/{printer_id}/edit", response_class=HTMLResponse)
async def printers_edit(request: Request, printer_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    items = svc.get_all(SHEET)
    item = next((p for p in items if p["printer_id"] == printer_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="인쇄업체를 찾을 수 없습니다.")
    return templates.TemplateResponse(request, "printers/form.html", {
        "user": user, "item": item, "action": "edit",
    })


@router.post("/printers/{printer_id}/edit")
async def printers_update(
    request: Request,
    printer_id: str,
    printer_name: str = Form(...),
    contact: str = Form(""),
    phone: str = Form(""),
    memo: str = Form(""),
    status: str = Form("활성"),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()

    existing = svc.get_all(SHEET)
    if any(p.get("printer_name", "").strip() == printer_name.strip() and p.get("printer_id") != printer_id for p in existing):
        item = next((p for p in existing if p["printer_id"] == printer_id), None)
        return templates.TemplateResponse(request, "printers/form.html", {
            "user": user, "item": item, "action": "edit",
            "error": f"인쇄업체 '{printer_name}' 는 이미 등록되어 있습니다.",
        }, status_code=400)

    svc.update_row(SHEET, "printer_id", printer_id, {
        "printer_name": printer_name,
        "contact": contact,
        "phone": phone,
        "memo": memo,
        "status": status,
        "updated_at": now_str(),
    })
    return RedirectResponse(url="/printers", status_code=303)


@router.post("/printers/{printer_id}/delete")
async def printers_delete(request: Request, printer_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.delete_row(SHEET, "printer_id", printer_id)
    return RedirectResponse(url="/printers", status_code=303)


@router.get("/api/printers")
async def api_printers_list(q: str = "", active_only: bool = False):
    """인쇄업체 조회 API (입고 등록 폼 자동완성 등에 사용)."""
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["printer_name", "contact", "phone"]) if q else svc.get_all(SHEET)
    if active_only:
        data = [p for p in data if p.get("status", "활성") == "활성"]
    return data
