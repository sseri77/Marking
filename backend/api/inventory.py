from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, require_auth, paginate

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "INVENTORY_STATUS"


@router.get("/inventory", response_class=HTMLResponse)
async def inventory_list(request: Request, q: str = "", page: int = 1):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["item_name", "category", "spec"]) if q else svc.get_all(SHEET)
    low_stock = [i for i in data if int(i.get("current_qty", 0)) <= int(i.get("safe_qty", 0))]
    paged = paginate(data, page)
    return templates.TemplateResponse("inventory/index.html", {"request": request, "user": user, "q": q, "low_stock_count": len(low_stock), **paged})


@router.get("/inventory/new", response_class=HTMLResponse)
async def inventory_new(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("inventory/form.html", {"request": request, "user": user, "item": None, "action": "create"})


@router.post("/inventory/new")
async def inventory_create(
    request: Request,
    category: str = Form(...),
    item_name: str = Form(...),
    spec: str = Form(""),
    current_qty: int = Form(...),
    safe_qty: int = Form(0),
    unit: str = Form("개"),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.append_row(SHEET, {"inventory_id": generate_id("INV"), "category": category, "item_name": item_name, "spec": spec, "current_qty": current_qty, "safe_qty": safe_qty, "unit": unit, "updated_at": now_str()})
    return RedirectResponse(url="/inventory", status_code=303)


@router.get("/inventory/{inventory_id}/edit", response_class=HTMLResponse)
async def inventory_edit(request: Request, inventory_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    items = svc.get_all(SHEET)
    item = next((i for i in items if i["inventory_id"] == inventory_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="재고 항목을 찾을 수 없습니다.")
    return templates.TemplateResponse("inventory/form.html", {"request": request, "user": user, "item": item, "action": "edit"})


@router.post("/inventory/{inventory_id}/edit")
async def inventory_update(
    request: Request,
    inventory_id: str,
    category: str = Form(...),
    item_name: str = Form(...),
    spec: str = Form(""),
    current_qty: int = Form(...),
    safe_qty: int = Form(0),
    unit: str = Form("개"),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.update_row(SHEET, "inventory_id", inventory_id, {"category": category, "item_name": item_name, "spec": spec, "current_qty": current_qty, "safe_qty": safe_qty, "unit": unit, "updated_at": now_str()})
    return RedirectResponse(url="/inventory", status_code=303)


@router.post("/inventory/{inventory_id}/delete")
async def inventory_delete(request: Request, inventory_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.delete_row(SHEET, "inventory_id", inventory_id)
    return RedirectResponse(url="/inventory", status_code=303)


@router.get("/api/inventory")
async def api_inventory_list(q: str = "", low_stock_only: bool = False):
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["item_name", "category"]) if q else svc.get_all(SHEET)
    if low_stock_only:
        data = [i for i in data if int(i.get("current_qty", 0)) <= int(i.get("safe_qty", 0))]
    return data
