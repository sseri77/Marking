from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, today_str, require_auth, paginate

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "ROLL_INBOUND"


@router.get("/inbound", response_class=HTMLResponse)
async def inbound_list(request: Request, q: str = "", page: int = 1):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["vendor", "roll_no", "order_ids"]) if q else svc.get_all(SHEET)
    data = sorted(data, key=lambda x: x.get("inbound_date", ""), reverse=True)
    paged = paginate(data, page)
    return templates.TemplateResponse("inbound/index.html", {"request": request, "user": user, "q": q, **paged})


@router.get("/inbound/new", response_class=HTMLResponse)
async def inbound_new(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    orders = [o for o in svc.get_all("ORDER") if o.get("status") in ("주문완료", "발주완료")]
    return templates.TemplateResponse("inbound/form.html", {
        "request": request, "user": user, "item": None,
        "orders": orders, "today": today_str(), "action": "create"
    })


@router.post("/inbound/new")
async def inbound_create(
    request: Request,
    inbound_date: str = Form(...),
    vendor: str = Form(...),
    roll_no: str = Form(...),
    order_ids: str = Form(""),
    manager: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    inbound_id = generate_id("RIB")
    svc.append_row(SHEET, {
        "inbound_id": inbound_id,
        "inbound_date": inbound_date,
        "vendor": vendor,
        "roll_no": roll_no,
        "order_ids": order_ids,
        "manager": manager,
        "memo": memo,
        "status": "입고완료",
        "created_at": now_str(),
    })
    # 연결된 주문 상태 → 입고완료로 업데이트
    for oid in [o.strip() for o in order_ids.split(",") if o.strip()]:
        svc.update_row("ORDER", "order_id", oid, {"status": "입고완료"})
    return RedirectResponse(url="/inbound", status_code=303)


@router.get("/inbound/{inbound_id}/edit", response_class=HTMLResponse)
async def inbound_edit(request: Request, inbound_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    items = svc.get_all(SHEET)
    item = next((i for i in items if i["inbound_id"] == inbound_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="입고 내역을 찾을 수 없습니다.")
    orders = svc.get_all("ORDER")
    return templates.TemplateResponse("inbound/form.html", {
        "request": request, "user": user, "item": item,
        "orders": orders, "today": today_str(), "action": "edit"
    })


@router.post("/inbound/{inbound_id}/edit")
async def inbound_update(
    request: Request,
    inbound_id: str,
    inbound_date: str = Form(...),
    vendor: str = Form(...),
    roll_no: str = Form(...),
    order_ids: str = Form(""),
    manager: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.update_row(SHEET, "inbound_id", inbound_id, {
        "inbound_date": inbound_date, "vendor": vendor, "roll_no": roll_no,
        "order_ids": order_ids, "manager": manager, "memo": memo,
    })
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
    return svc.search(SHEET, q, ["vendor", "roll_no"]) if q else svc.get_all(SHEET)
