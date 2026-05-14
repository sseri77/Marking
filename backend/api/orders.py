from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, today_str, require_auth, paginate
from backend.utils.audit_log import log_create, log_update, log_delete

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "ORDER"


@router.get("/orders", response_class=HTMLResponse)
async def order_list(request: Request, q: str = "", page: int = 1):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["club_name", "player_name", "player_number", "collab_name"]) if q else svc.get_all(SHEET)
    data = sorted(data, key=lambda x: x.get("order_date", ""), reverse=True)

    inbound_order_ids: set[str] = set()
    for ib in svc.get_all("ROLL_INBOUND"):
        for oid in str(ib.get("order_ids", "")).split(","):
            oid = oid.strip()
            if oid:
                inbound_order_ids.add(oid)
    for item in data:
        item["awaiting_inbound"] = bool(item.get("parent_order_id")) and item.get("order_id") not in inbound_order_ids

    paged = paginate(data, page)
    return templates.TemplateResponse(request, "orders/index.html", {"user": user, "q": q, **paged})


@router.get("/orders/new", response_class=HTMLResponse)
async def order_new(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    clubs = svc.get_all("CLUB_MASTER")
    collabs = svc.get_all("COLLAB_MASTER")
    players = svc.get_all("PLAYER_MASTER")
    return templates.TemplateResponse(request, "orders/form.html", {
        "user": user, "item": None,
        "clubs": clubs, "collabs": collabs, "players": players,
        "today": today_str(), "action": "create"
    })


@router.post("/orders/new")
async def order_create(
    request: Request,
    order_date: str = Form(...),
    club_collab: str = Form(...),
    player_name: str = Form(...),
    player_number: str = Form(...),
    qty: int = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    club_name, _, collab_name = club_collab.partition("|")
    svc = get_sheets_service()
    new_order_id = generate_id("ORD")
    svc.append_row(SHEET, {
        "order_id": new_order_id,
        "order_date": order_date,
        "club_name": club_name,
        "collab_name": collab_name,
        "player_name": player_name,
        "player_number": player_number,
        "qty": qty,
        "status": "주문완료",
        "memo": memo,
        "created_at": now_str(),
    })
    log_create(
        svc, entity="ORDER", entity_id=new_order_id,
        data={"qty": qty}, user=user.get("username", ""),
        related_order_id=new_order_id,
        memo=f"{club_name}/{player_name}#{player_number}",
    )
    return RedirectResponse(url="/orders", status_code=303)


@router.get("/orders/{order_id}/edit", response_class=HTMLResponse)
async def order_edit(request: Request, order_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    items = svc.get_all(SHEET)
    item = next((i for i in items if i["order_id"] == order_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
    clubs = svc.get_all("CLUB_MASTER")
    collabs = svc.get_all("COLLAB_MASTER")
    players = svc.get_all("PLAYER_MASTER")
    return templates.TemplateResponse(request, "orders/form.html", {
        "user": user, "item": item,
        "clubs": clubs, "collabs": collabs, "players": players,
        "today": today_str(), "action": "edit"
    })


@router.post("/orders/{order_id}/edit")
async def order_update(
    request: Request,
    order_id: str,
    order_date: str = Form(...),
    club_collab: str = Form(...),
    player_name: str = Form(...),
    player_number: str = Form(...),
    qty: int = Form(...),
    status: str = Form("주문완료"),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    club_name, _, collab_name = club_collab.partition("|")
    svc = get_sheets_service()
    before = next((o for o in svc.get_all(SHEET) if o.get("order_id") == order_id), None)
    before_qty = int((before or {}).get("qty", 0) or 0)
    svc.update_row(SHEET, "order_id", order_id, {
        "order_date": order_date, "club_name": club_name, "collab_name": collab_name,
        "player_name": player_name, "player_number": player_number,
        "qty": qty, "status": status, "memo": memo,
    })
    log_update(
        svc, entity="ORDER", entity_id=order_id,
        before_data={"qty": before_qty}, after_data={"qty": qty},
        user=user.get("username", ""), related_order_id=order_id,
        memo=f"{club_name}/{player_name}#{player_number}",
    )
    return RedirectResponse(url="/orders", status_code=303)


@router.post("/orders/{order_id}/delete")
async def order_delete(request: Request, order_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    before = next((o for o in svc.get_all(SHEET) if o.get("order_id") == order_id), None)
    before_qty = int((before or {}).get("qty", 0) or 0)
    svc.delete_row(SHEET, "order_id", order_id)
    if before:
        log_delete(
            svc, entity="ORDER", entity_id=order_id,
            before_data={"qty": before_qty},
            user=user.get("username", ""), related_order_id=order_id,
            memo=f"{before.get('club_name','')}/{before.get('player_name','')}#{before.get('player_number','')}",
        )
    return RedirectResponse(url="/orders", status_code=303)


@router.get("/api/orders")
async def api_order_list(q: str = "", club_name: str = "", status: str = ""):
    svc = get_sheets_service()
    data = svc.get_all(SHEET)
    if q:
        data = svc.search(SHEET, q, ["club_name", "player_name", "player_number"])
    if club_name:
        data = [d for d in data if d.get("club_name") == club_name]
    if status:
        data = [d for d in data if d.get("status") == status]
    return data
