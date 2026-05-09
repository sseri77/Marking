from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, today_str, require_auth, paginate

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "STORE_OUTBOUND"


@router.get("/outbound", response_class=HTMLResponse)
async def outbound_list(request: Request, q: str = "", page: int = 1):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["store_name", "club_name", "player_name", "invoice_no"]) if q else svc.get_all(SHEET)
    data = sorted(data, key=lambda x: x.get("shipping_date", ""), reverse=True)
    paged = paginate(data, page)
    return templates.TemplateResponse("outbound/index.html", {"request": request, "user": user, "q": q, **paged})


@router.get("/outbound/new", response_class=HTMLResponse)
async def outbound_new(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    clubs = svc.get_all("CLUB_MASTER")
    collabs = svc.get_all("COLLAB_MASTER")
    players = svc.get_all("PLAYER_MASTER")
    return templates.TemplateResponse("outbound/form.html", {"request": request, "user": user, "item": None, "clubs": clubs, "collabs": collabs, "players": players, "today": today_str(), "action": "create"})


@router.post("/outbound/new")
async def outbound_create(
    request: Request,
    store_name: str = Form(...),
    club_name: str = Form(...),
    collab_name: str = Form(...),
    player_name: str = Form(...),
    player_number: str = Form(...),
    qty: int = Form(...),
    invoice_no: str = Form(...),
    shipping_date: str = Form(...),
    manager: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.append_row(SHEET, {"outbound_id": generate_id("OUT"), "store_name": store_name, "club_name": club_name, "collab_name": collab_name, "player_name": player_name, "player_number": player_number, "qty": qty, "invoice_no": invoice_no, "shipping_date": shipping_date, "manager": manager, "memo": memo, "created_at": now_str()})
    return RedirectResponse(url="/outbound", status_code=303)


@router.get("/outbound/{outbound_id}/edit", response_class=HTMLResponse)
async def outbound_edit(request: Request, outbound_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    clubs = svc.get_all("CLUB_MASTER")
    collabs = svc.get_all("COLLAB_MASTER")
    players = svc.get_all("PLAYER_MASTER")
    items = svc.get_all(SHEET)
    item = next((i for i in items if i["outbound_id"] == outbound_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="출고 내역을 찾을 수 없습니다.")
    return templates.TemplateResponse("outbound/form.html", {"request": request, "user": user, "item": item, "clubs": clubs, "collabs": collabs, "players": players, "today": today_str(), "action": "edit"})


@router.post("/outbound/{outbound_id}/edit")
async def outbound_update(
    request: Request,
    outbound_id: str,
    store_name: str = Form(...),
    club_name: str = Form(...),
    collab_name: str = Form(...),
    player_name: str = Form(...),
    player_number: str = Form(...),
    qty: int = Form(...),
    invoice_no: str = Form(...),
    shipping_date: str = Form(...),
    manager: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.update_row(SHEET, "outbound_id", outbound_id, {"store_name": store_name, "club_name": club_name, "collab_name": collab_name, "player_name": player_name, "player_number": player_number, "qty": qty, "invoice_no": invoice_no, "shipping_date": shipping_date, "manager": manager, "memo": memo})
    return RedirectResponse(url="/outbound", status_code=303)


@router.post("/outbound/{outbound_id}/delete")
async def outbound_delete(request: Request, outbound_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.delete_row(SHEET, "outbound_id", outbound_id)
    return RedirectResponse(url="/outbound", status_code=303)


@router.get("/api/outbound")
async def api_outbound_list(q: str = ""):
    svc = get_sheets_service()
    return svc.search(SHEET, q, ["store_name", "club_name", "player_name", "invoice_no"]) if q else svc.get_all(SHEET)
