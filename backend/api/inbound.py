from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, today_str, require_auth, paginate

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "MATERIAL_INBOUND"


@router.get("/inbound", response_class=HTMLResponse)
async def inbound_list(request: Request, q: str = "", page: int = 1):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["vendor", "material_name", "lot_no"]) if q else svc.get_all(SHEET)
    data = sorted(data, key=lambda x: x.get("date", ""), reverse=True)
    paged = paginate(data, page)
    return templates.TemplateResponse("inbound/index.html", {"request": request, "user": user, "q": q, **paged})


@router.get("/inbound/new", response_class=HTMLResponse)
async def inbound_new(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    vendors = svc.get_all("VENDOR_MASTER")
    return templates.TemplateResponse("inbound/form.html", {"request": request, "user": user, "item": None, "vendors": vendors, "today": today_str(), "action": "create"})


@router.post("/inbound/new")
async def inbound_create(
    request: Request,
    date: str = Form(...),
    vendor: str = Form(...),
    material_name: str = Form(...),
    spec: str = Form(""),
    lot_no: str = Form(...),
    qty: int = Form(...),
    unit: str = Form("m"),
    manager: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    existing = svc.get_all(SHEET)
    if any(r.get("lot_no") == lot_no for r in existing):
        vendors = svc.get_all("VENDOR_MASTER")
        return templates.TemplateResponse("inbound/form.html", {"request": request, "user": user, "item": None, "vendors": vendors, "today": today_str(), "action": "create", "error": f"LOT번호 {lot_no}는 이미 등록되어 있습니다."})
    svc.append_row(SHEET, {"inbound_id": generate_id("INB"), "date": date, "vendor": vendor, "material_name": material_name, "spec": spec, "lot_no": lot_no, "qty": qty, "unit": unit, "manager": manager, "memo": memo, "created_at": now_str()})
    return RedirectResponse(url="/inbound", status_code=303)


@router.get("/inbound/{inbound_id}/edit", response_class=HTMLResponse)
async def inbound_edit(request: Request, inbound_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    vendors = svc.get_all("VENDOR_MASTER")
    items = svc.get_all(SHEET)
    item = next((i for i in items if i["inbound_id"] == inbound_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="입고 내역을 찾을 수 없습니다.")
    return templates.TemplateResponse("inbound/form.html", {"request": request, "user": user, "item": item, "vendors": vendors, "today": today_str(), "action": "edit"})


@router.post("/inbound/{inbound_id}/edit")
async def inbound_update(
    request: Request,
    inbound_id: str,
    date: str = Form(...),
    vendor: str = Form(...),
    material_name: str = Form(...),
    spec: str = Form(""),
    lot_no: str = Form(...),
    qty: int = Form(...),
    unit: str = Form("m"),
    manager: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.update_row(SHEET, "inbound_id", inbound_id, {"date": date, "vendor": vendor, "material_name": material_name, "spec": spec, "lot_no": lot_no, "qty": qty, "unit": unit, "manager": manager, "memo": memo})
    return RedirectResponse(url="/inbound", status_code=303)


@router.post("/inbound/{inbound_id}/delete")
async def inbound_delete(request: Request, inbound_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.delete_row(SHEET, "inbound_id", inbound_id)
    return RedirectResponse(url="/inbound", status_code=303)


@router.get("/api/inbound")
async def api_inbound_list(q: str = ""):
    svc = get_sheets_service()
    return svc.search(SHEET, q, ["vendor", "material_name", "lot_no"]) if q else svc.get_all(SHEET)
