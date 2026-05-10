from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import (
    generate_id, now_str, today_str, require_auth, paginate,
    day_of_week, generate_roll_no,
)

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "ROLL_INBOUND"


def _compute_order_inbound_totals(all_inbound: list) -> dict[str, int]:
    """order_id별 누적 입고 수량 반환."""
    totals: dict[str, int] = {}
    for row in all_inbound:
        qty = int(row.get("inbound_qty", 0) or 0)
        for oid in [o.strip() for o in str(row.get("order_ids", "")).split(",") if o.strip()]:
            totals[oid] = totals.get(oid, 0) + qty
    return totals


def _resolve_order_status(order_qty: int, total_inbound: int) -> str:
    if total_inbound <= 0:
        return "주문완료"
    if total_inbound >= order_qty:
        return "입고완료"
    return "입고진행중"


@router.get("/inbound", response_class=HTMLResponse)
async def inbound_list(request: Request, q: str = "", page: int = 1):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["vendor", "roll_no", "order_ids"]) if q else svc.get_all(SHEET)
    data = sorted(data, key=lambda x: x.get("inbound_date", ""), reverse=True)

    # 주문별 누적 수량 계산 (목록 표시용)
    all_orders = {o["order_id"]: o for o in svc.get_all("ORDER")}
    all_inbound = svc.get_all(SHEET)
    order_totals = _compute_order_inbound_totals(all_inbound)

    paged = paginate(data, page)
    return templates.TemplateResponse("inbound/index.html", {
        "request": request, "user": user, "q": q,
        "all_orders": all_orders, "order_totals": order_totals,
        **paged,
    })


@router.get("/inbound/new", response_class=HTMLResponse)
async def inbound_new(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()

    all_inbound = svc.get_all(SHEET)
    order_totals = _compute_order_inbound_totals(all_inbound)

    today = today_str()
    new_roll_no = generate_roll_no(all_inbound, today)

    orders_raw = svc.get_all("ORDER")
    # 주문완료 + 입고진행중 모두 표시 (발주완료 포함)
    active_statuses = {"주문완료", "발주완료", "입고진행중"}
    orders = [o for o in orders_raw if o.get("status") in active_statuses]

    # 각 주문에 누적 입고 수량, 잔여 수량 추가
    for o in orders:
        oid = o["order_id"]
        o_qty = int(o.get("qty", 0) or 0)
        total = order_totals.get(oid, 0)
        o["_total_inbound"] = total
        o["_remaining"] = max(0, o_qty - total)

    return templates.TemplateResponse("inbound/form.html", {
        "request": request, "user": user, "item": None,
        "orders": orders, "today": today, "action": "create",
        "new_roll_no": new_roll_no,
        "auto_manager": user["username"],
        "today_weekday": day_of_week(today),
    })


@router.post("/inbound/new")
async def inbound_create(
    request: Request,
    inbound_date: str = Form(...),
    vendor: str = Form(...),
    roll_no: str = Form(...),
    order_ids: str = Form(""),
    inbound_qty: int = Form(...),
    manager: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()

    # 롤번호 중복 검사
    existing = svc.get_all(SHEET)
    if any(r.get("roll_no") == roll_no for r in existing):
        all_inbound = existing
        order_totals = _compute_order_inbound_totals(all_inbound)
        orders_raw = svc.get_all("ORDER")
        orders = [o for o in orders_raw if o.get("status") in {"주문완료", "발주완료", "입고진행중"}]
        for o in orders:
            oid = o["order_id"]
            o_qty = int(o.get("qty", 0) or 0)
            total = order_totals.get(oid, 0)
            o["_total_inbound"] = total
            o["_remaining"] = max(0, o_qty - total)
        return templates.TemplateResponse("inbound/form.html", {
            "request": request, "user": user, "item": None,
            "orders": orders, "today": today_str(), "action": "create",
            "new_roll_no": roll_no, "auto_manager": manager,
            "today_weekday": day_of_week(inbound_date),
            "error": f"롤번호 '{roll_no}' 는 이미 사용 중입니다. 다른 번호를 사용해주세요.",
        }, status_code=400)

    # 연결된 주문 총 주문 수량 계산
    order_id_list = [o.strip() for o in order_ids.split(",") if o.strip()]
    all_orders = {o["order_id"]: o for o in svc.get_all("ORDER")}
    order_qty_total = sum(int(all_orders[oid].get("qty", 0) or 0) for oid in order_id_list if oid in all_orders)

    # 이번 입고 후 누적 수량 계산 및 상태 결정
    order_totals = _compute_order_inbound_totals(existing)
    inbound_id = generate_id("RIB")
    dow = day_of_week(inbound_date)

    # 전체 입고 수량 대비 상태 (연결 주문 기준)
    if order_id_list and order_qty_total > 0:
        new_totals = dict(order_totals)
        for oid in order_id_list:
            new_totals[oid] = new_totals.get(oid, 0) + inbound_qty
        fully_done = all(new_totals.get(oid, 0) >= int(all_orders[oid].get("qty", 0) or 0) for oid in order_id_list if oid in all_orders)
        status = "입고완료" if fully_done else "입고진행중"
    else:
        status = "입고완료"

    svc.append_row(SHEET, {
        "inbound_id": inbound_id,
        "inbound_date": inbound_date,
        "day_of_week": dow,
        "vendor": vendor,
        "roll_no": roll_no,
        "order_ids": order_ids,
        "order_qty": order_qty_total,
        "inbound_qty": inbound_qty,
        "manager": manager,
        "memo": memo,
        "status": status,
        "created_at": now_str(),
    })

    # 각 연결 주문 상태 업데이트
    all_inbound_after = svc.get_all(SHEET)
    new_order_totals = _compute_order_inbound_totals(all_inbound_after)
    for oid in order_id_list:
        if oid not in all_orders:
            continue
        o_qty = int(all_orders[oid].get("qty", 0) or 0)
        new_status = _resolve_order_status(o_qty, new_order_totals.get(oid, 0))
        svc.update_row("ORDER", "order_id", oid, {"status": new_status})

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

    order_totals = _compute_order_inbound_totals(items)
    all_orders_raw = svc.get_all("ORDER")
    all_orders = {o["order_id"]: o for o in all_orders_raw}

    # 수정 폼에서는 모든 주문 표시 (완료 포함)
    orders = list(all_orders_raw)
    for o in orders:
        oid = o["order_id"]
        o_qty = int(o.get("qty", 0) or 0)
        total = order_totals.get(oid, 0)
        o["_total_inbound"] = total
        o["_remaining"] = max(0, o_qty - total)

    return templates.TemplateResponse("inbound/form.html", {
        "request": request, "user": user, "item": item,
        "orders": orders, "today": today_str(), "action": "edit",
        "new_roll_no": item.get("roll_no", ""),
        "auto_manager": item.get("manager", user["username"]),
        "today_weekday": day_of_week(item.get("inbound_date", today_str())),
    })


@router.post("/inbound/{inbound_id}/edit")
async def inbound_update(
    request: Request,
    inbound_id: str,
    inbound_date: str = Form(...),
    vendor: str = Form(...),
    roll_no: str = Form(...),
    order_ids: str = Form(""),
    inbound_qty: int = Form(...),
    manager: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    dow = day_of_week(inbound_date)

    # 롤번호 중복 검사 (자신 제외)
    all_rows = svc.get_all(SHEET)
    if any(r.get("roll_no") == roll_no and r.get("inbound_id") != inbound_id for r in all_rows):
        item = next((r for r in all_rows if r["inbound_id"] == inbound_id), None)
        return templates.TemplateResponse("inbound/form.html", {
            "request": request, "user": user, "item": item,
            "orders": svc.get_all("ORDER"), "today": today_str(), "action": "edit",
            "new_roll_no": roll_no, "auto_manager": manager,
            "today_weekday": dow,
            "error": f"롤번호 '{roll_no}' 는 이미 사용 중입니다.",
        }, status_code=400)

    order_id_list = [o.strip() for o in order_ids.split(",") if o.strip()]
    all_orders = {o["order_id"]: o for o in svc.get_all("ORDER")}
    order_qty_total = sum(int(all_orders[oid].get("qty", 0) or 0) for oid in order_id_list if oid in all_orders)

    svc.update_row(SHEET, "inbound_id", inbound_id, {
        "inbound_date": inbound_date, "day_of_week": dow, "vendor": vendor,
        "roll_no": roll_no, "order_ids": order_ids,
        "order_qty": order_qty_total, "inbound_qty": inbound_qty,
        "manager": manager, "memo": memo,
    })

    # 수정 후 주문 상태 재계산
    all_inbound_after = svc.get_all(SHEET)
    new_order_totals = _compute_order_inbound_totals(all_inbound_after)
    for oid in order_id_list:
        if oid not in all_orders:
            continue
        o_qty = int(all_orders[oid].get("qty", 0) or 0)
        new_status = _resolve_order_status(o_qty, new_order_totals.get(oid, 0))
        svc.update_row("ORDER", "order_id", oid, {"status": new_status})

    return RedirectResponse(url="/inbound", status_code=303)


@router.post("/inbound/{inbound_id}/delete")
async def inbound_delete(request: Request, inbound_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()

    # 삭제 전 연결 주문 목록 저장
    all_rows = svc.get_all(SHEET)
    target = next((r for r in all_rows if r["inbound_id"] == inbound_id), None)
    linked_order_ids = []
    if target:
        linked_order_ids = [o.strip() for o in str(target.get("order_ids", "")).split(",") if o.strip()]

    svc.delete_row(SHEET, "inbound_id", inbound_id)

    # 삭제 후 주문 상태 재계산
    if linked_order_ids:
        all_inbound_after = svc.get_all(SHEET)
        new_order_totals = _compute_order_inbound_totals(all_inbound_after)
        all_orders = {o["order_id"]: o for o in svc.get_all("ORDER")}
        for oid in linked_order_ids:
            if oid not in all_orders:
                continue
            o_qty = int(all_orders[oid].get("qty", 0) or 0)
            new_status = _resolve_order_status(o_qty, new_order_totals.get(oid, 0))
            svc.update_row("ORDER", "order_id", oid, {"status": new_status})

    return RedirectResponse(url="/inbound", status_code=303)


@router.get("/api/inbound/roll_no_preview")
async def api_roll_no_preview(date: str = ""):
    """입고 날짜 기준 다음 롤번호 미리보기 (프론트엔드 AJAX 용)."""
    svc = get_sheets_service()
    target_date = date or today_str()
    all_inbound = svc.get_all(SHEET)
    return JSONResponse({"roll_no": generate_roll_no(all_inbound, target_date), "day_of_week": day_of_week(target_date)})


@router.get("/api/inbound")
async def api_inbound_list(q: str = ""):
    svc = get_sheets_service()
    return svc.search(SHEET, q, ["vendor", "roll_no"]) if q else svc.get_all(SHEET)
