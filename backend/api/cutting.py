from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, require_auth, paginate

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "CUTTING_PROCESS"


@router.get("/cutting", response_class=HTMLResponse)
async def cutting_list(request: Request, q: str = "", page: int = 1):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["club_name", "player_name", "player_number", "inbound_id"]) if q else svc.get_all(SHEET)
    data = sorted(data, key=lambda x: x.get("created_at", ""), reverse=True)
    paged = paginate(data, page)
    return templates.TemplateResponse("cutting/index.html", {"request": request, "user": user, "q": q, **paged})


@router.get("/cutting/new", response_class=HTMLResponse)
async def cutting_new(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    inbounds = svc.get_all("ROLL_INBOUND")
    orders = svc.get_all("ORDER")
    players = svc.get_all("PLAYER_MASTER")
    return templates.TemplateResponse("cutting/form.html", {
        "request": request, "user": user, "item": None,
        "inbounds": inbounds, "orders": orders, "players": players, "action": "create"
    })


@router.post("/cutting/new")
async def cutting_create(
    request: Request,
    inbound_id: str = Form(...),
    order_id: str = Form(...),
    club_name: str = Form(...),
    collab_name: str = Form(...),
    player_name: str = Form(...),
    player_number: str = Form(...),
    input_qty: int = Form(...),
    success_qty: int = Form(...),
    defect_qty: int = Form(0),
    loss_qty: int = Form(0),
    status: str = Form("진행중"),
    worker: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if success_qty > input_qty:
        svc = get_sheets_service()
        return templates.TemplateResponse("cutting/form.html", {
            "request": request, "user": user, "item": None,
            "inbounds": svc.get_all("ROLL_INBOUND"), "orders": svc.get_all("ORDER"),
            "players": svc.get_all("PLAYER_MASTER"), "action": "create",
            "error": "성공수량은 투입수량을 초과할 수 없습니다."
        })
    svc = get_sheets_service()
    svc.append_row(SHEET, {
        "cutting_id": generate_id("CUT"),
        "inbound_id": inbound_id,
        "order_id": order_id,
        "club_name": club_name,
        "collab_name": collab_name,
        "player_name": player_name,
        "player_number": player_number,
        "input_qty": input_qty,
        "success_qty": success_qty,
        "defect_qty": defect_qty,
        "loss_qty": loss_qty,
        "status": status,
        "worker": worker,
        "memo": memo,
        "created_at": now_str(),
    })
    if status == "완료":
        svc.update_row("ORDER", "order_id", order_id, {"status": "재단완료"})
    return RedirectResponse(url="/cutting", status_code=303)


@router.get("/cutting/{cutting_id}/edit", response_class=HTMLResponse)
async def cutting_edit(request: Request, cutting_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    items = svc.get_all(SHEET)
    item = next((i for i in items if i["cutting_id"] == cutting_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="재단 작업을 찾을 수 없습니다.")
    inbounds = svc.get_all("ROLL_INBOUND")
    orders = svc.get_all("ORDER")
    players = svc.get_all("PLAYER_MASTER")
    return templates.TemplateResponse("cutting/form.html", {
        "request": request, "user": user, "item": item,
        "inbounds": inbounds, "orders": orders, "players": players, "action": "edit"
    })


@router.post("/cutting/{cutting_id}/edit")
async def cutting_update(
    request: Request,
    cutting_id: str,
    inbound_id: str = Form(...),
    order_id: str = Form(...),
    club_name: str = Form(...),
    collab_name: str = Form(...),
    player_name: str = Form(...),
    player_number: str = Form(...),
    input_qty: int = Form(...),
    success_qty: int = Form(...),
    defect_qty: int = Form(0),
    loss_qty: int = Form(0),
    status: str = Form("진행중"),
    worker: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.update_row(SHEET, "cutting_id", cutting_id, {
        "inbound_id": inbound_id, "order_id": order_id,
        "club_name": club_name, "collab_name": collab_name,
        "player_name": player_name, "player_number": player_number,
        "input_qty": input_qty, "success_qty": success_qty,
        "defect_qty": defect_qty, "loss_qty": loss_qty,
        "status": status, "worker": worker, "memo": memo,
    })
    if status == "완료":
        svc.update_row("ORDER", "order_id", order_id, {"status": "재단완료"})
    return RedirectResponse(url="/cutting", status_code=303)


@router.post("/cutting/{cutting_id}/delete")
async def cutting_delete(request: Request, cutting_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.delete_row(SHEET, "cutting_id", cutting_id)
    return RedirectResponse(url="/cutting", status_code=303)


@router.get("/api/cutting")
async def api_cutting_list(q: str = ""):
    svc = get_sheets_service()
    return svc.search(SHEET, q, ["club_name", "player_name", "inbound_id"]) if q else svc.get_all(SHEET)
