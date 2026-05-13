from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import (
    generate_id, now_str, today_str, require_auth, paginate,
    day_of_week, generate_roll_no,
)
from backend.utils.audit_log import log_create, log_update, log_delete

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


def _get_locked_inbound_ids(svc) -> set[str]:
    """재단(CUTTING_PROCESS)에서 참조 중인 inbound_id 집합. 잠금 대상 식별용."""
    cuttings = svc.get_all("CUTTING_PROCESS")
    return {c.get("inbound_id") for c in cuttings if c.get("inbound_id")}


def _validate_inbound_overflow(
    svc,
    order_id_list: list[str],
    inbound_qty: int,
    exclude_inbound_id: str = "",
) -> str | None:
    """주문수량 초과 입고 금지 검증.

    각 연결 주문별로 (이번 입고건 제외한 누적입고 + 이번 inbound_qty) ≤ 주문수량 이어야 한다.
    위반 시 사용자에게 보여줄 한국어 오류 메시지 문자열을 반환, 정상이면 None.
    """
    if not order_id_list or inbound_qty <= 0:
        return None
    all_orders = {o["order_id"]: o for o in svc.get_all("ORDER")}
    # 이번 입고건을 제외한 기존 입고들로 누적 계산
    existing = [r for r in svc.get_all(SHEET)
                if r.get("inbound_id") != exclude_inbound_id]
    totals = _compute_order_inbound_totals(existing)
    over: list[str] = []
    for oid in order_id_list:
        order = all_orders.get(oid)
        if not order:
            continue
        o_qty = int(order.get("qty", 0) or 0)
        already = totals.get(oid, 0)
        if already + inbound_qty > o_qty:
            remaining = max(o_qty - already, 0)
            label = f"{order.get('club_name','')} {order.get('player_name','')}#{order.get('player_number','')}".strip()
            over.append(
                f"[{label or oid}] 주문 {o_qty}장 / 기존 입고 {already}장 / 잔여 {remaining}장"
            )
    if over:
        head = f"입고수량 {inbound_qty}장이 주문 잔여수량을 초과합니다."
        return head + "\n" + "\n".join(over)
    return None


def _create_shortage_reorder(
    svc,
    inbound_id: str,
    parent_order_id: str,
    shortage_qty: int,
) -> None:
    """입고 시점에 주문수량 대비 부족분이 확정되면 동일 선수로 새 주문을 등록한다.

    호출 시점은 “해당 주문에 대한 입고가 사용자에 의해 마감된 시점”이 아니므로
    자동 생성 대신, 동일 inbound_id 기준 중복 방지 태그(`[RIB:{inbound_id}]`)만 사용.
    여기서는 호출하지 않는다 — 미입고 잔량은 ‘동일 order_id 에 추가 입고’ 방식으로 충당.
    함수는 향후 확장 포인트로 남겨둔다."""
    if shortage_qty <= 0 or not parent_order_id:
        return
    orders = svc.get_all("ORDER")
    tag = f"[RIB:{inbound_id}]"
    if any(tag in (o.get("memo") or "") for o in orders):
        return
    original = next((o for o in orders if o.get("order_id") == parent_order_id), None)
    if not original:
        return
    svc.append_row("ORDER", {
        "order_id": generate_id("ORD"),
        "order_date": today_str(),
        "club_name": original.get("club_name", ""),
        "collab_name": original.get("collab_name", ""),
        "player_name": original.get("player_name", ""),
        "player_number": original.get("player_number", ""),
        "qty": shortage_qty,
        "status": "주문완료",
        "memo": f"{tag} 미입고 재발주 (원본 {parent_order_id})",
        "created_at": now_str(),
        "parent_order_id": parent_order_id,
    })


@router.get("/inbound", response_class=HTMLResponse)
async def inbound_list(request: Request, q: str = "", page: int = 1, error: str = ""):
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
    locked_inbound_ids = _get_locked_inbound_ids(svc)

    error_message = ""
    if error == "delete_locked":
        error_message = "재단에 사용된 입고는 삭제할 수 없습니다. 먼저 관련 재단 기록을 삭제하세요."

    paged = paginate(data, page)
    return templates.TemplateResponse(request, "inbound/index.html", {
        "user": user, "q": q,
        "all_orders": all_orders, "order_totals": order_totals,
        "locked_inbound_ids": locked_inbound_ids,
        "error_message": error_message,
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

    printers = [p for p in svc.get_all("PRINTER_MASTER") if p.get("status", "활성") == "활성"]

    return templates.TemplateResponse(request, "inbound/form.html", {
        "user": user, "item": None,
        "orders": orders, "today": today, "action": "create",
        "new_roll_no": new_roll_no,
        "auto_manager": user["username"],
        "today_weekday": day_of_week(today),
        "printers": printers,
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

    # 입고 번호 중복 검사
    existing = svc.get_all(SHEET)

    def _render_error(msg: str, status_code: int = 400):
        all_inbound = existing
        order_totals = _compute_order_inbound_totals(all_inbound)
        orders_raw = svc.get_all("ORDER")
        active_orders = [o for o in orders_raw if o.get("status") in {"주문완료", "발주완료", "입고진행중"}]
        for o in active_orders:
            oid = o["order_id"]
            o_qty = int(o.get("qty", 0) or 0)
            total = order_totals.get(oid, 0)
            o["_total_inbound"] = total
            o["_remaining"] = max(0, o_qty - total)
        printers = [p for p in svc.get_all("PRINTER_MASTER") if p.get("status", "활성") == "활성"]
        return templates.TemplateResponse(request, "inbound/form.html", {
            "user": user, "item": None,
            "orders": active_orders, "today": today_str(), "action": "create",
            "new_roll_no": roll_no, "auto_manager": manager,
            "today_weekday": day_of_week(inbound_date),
            "error": msg,
            "printers": printers,
        }, status_code=status_code)

    if any(r.get("roll_no") == roll_no for r in existing):
        return _render_error(f"입고 번호 '{roll_no}' 는 이미 사용 중입니다. 다른 번호를 사용해주세요.")

    # 연결된 주문 총 주문 수량 계산
    order_id_list = [o.strip() for o in order_ids.split(",") if o.strip()]
    all_orders = {o["order_id"]: o for o in svc.get_all("ORDER")}
    order_qty_total = sum(int(all_orders[oid].get("qty", 0) or 0) for oid in order_id_list if oid in all_orders)

    # 주문수량 초과 입고 금지 검증
    overflow_msg = _validate_inbound_overflow(svc, order_id_list, inbound_qty)
    if overflow_msg:
        return _render_error(overflow_msg)

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

    # audit 로그
    log_create(
        svc, entity="ROLL_INBOUND", entity_id=inbound_id,
        data={"inbound_qty": inbound_qty},
        user=user.get("username", ""),
        related_order_id=",".join(order_id_list),
        memo=f"roll_no={roll_no}",
    )

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

    printers = svc.get_all("PRINTER_MASTER")

    return templates.TemplateResponse(request, "inbound/form.html", {
        "user": user, "item": item,
        "orders": orders, "today": today_str(), "action": "edit",
        "new_roll_no": item.get("roll_no", ""),
        "auto_manager": item.get("manager", user["username"]),
        "today_weekday": day_of_week(item.get("inbound_date", today_str())),
        "is_locked": inbound_id in _get_locked_inbound_ids(svc),
        "printers": printers,
    })


@router.post("/inbound/{inbound_id}/edit")
async def inbound_update(
    request: Request,
    inbound_id: str,
    inbound_date: str = Form(""),
    vendor: str = Form(""),
    roll_no: str = Form(""),
    order_ids: str = Form(""),
    inbound_qty: int = Form(0),
    manager: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()

    # 변경 전 원본 (audit 비교용)
    before_item = next((r for r in svc.get_all(SHEET) if r.get("inbound_id") == inbound_id), None)
    if not before_item:
        raise HTTPException(status_code=404, detail="입고 내역을 찾을 수 없습니다.")
    before_qty = int(before_item.get("inbound_qty", 0) or 0)

    # 재단에 사용된 입고는 핵심 필드 변경 차단 (메모/담당자만 허용)
    is_locked = inbound_id in _get_locked_inbound_ids(svc)
    if is_locked:
        inbound_date = before_item.get("inbound_date", "")
        vendor = before_item.get("vendor", "")
        roll_no = before_item.get("roll_no", "")
        order_ids = before_item.get("order_ids", "")
        inbound_qty = before_qty

    dow = day_of_week(inbound_date)

    def _render_error(msg: str, status_code: int = 400):
        return templates.TemplateResponse(request, "inbound/form.html", {
            "user": user, "item": before_item,
            "orders": svc.get_all("ORDER"), "today": today_str(), "action": "edit",
            "new_roll_no": roll_no, "auto_manager": manager,
            "today_weekday": dow,
            "error": msg,
            "is_locked": is_locked,
            "printers": svc.get_all("PRINTER_MASTER"),
        }, status_code=status_code)

    # 입고 번호 중복 검사 (자신 제외) — 잠금 상태에서는 변경 없으므로 스킵
    all_rows = svc.get_all(SHEET)
    if not is_locked and any(r.get("roll_no") == roll_no and r.get("inbound_id") != inbound_id for r in all_rows):
        return _render_error(f"입고 번호 '{roll_no}' 는 이미 사용 중입니다.")

    order_id_list = [o.strip() for o in order_ids.split(",") if o.strip()]
    all_orders = {o["order_id"]: o for o in svc.get_all("ORDER")}
    order_qty_total = sum(int(all_orders[oid].get("qty", 0) or 0) for oid in order_id_list if oid in all_orders)

    # 주문수량 초과 입고 금지 검증 (잠금 상태 제외)
    if not is_locked:
        overflow_msg = _validate_inbound_overflow(
            svc, order_id_list, inbound_qty, exclude_inbound_id=inbound_id,
        )
        if overflow_msg:
            return _render_error(overflow_msg)

    update_data = {"manager": manager, "memo": memo}
    if not is_locked:
        update_data.update({
            "inbound_date": inbound_date, "day_of_week": dow, "vendor": vendor,
            "roll_no": roll_no, "order_ids": order_ids,
            "order_qty": order_qty_total, "inbound_qty": inbound_qty,
        })
    svc.update_row(SHEET, "inbound_id", inbound_id, update_data)

    # audit 로그 (잠금 상태에서는 수량 변경 없음)
    if not is_locked:
        log_update(
            svc, entity="ROLL_INBOUND", entity_id=inbound_id,
            before_data={"inbound_qty": before_qty},
            after_data={"inbound_qty": inbound_qty},
            user=user.get("username", ""),
            related_order_id=",".join(order_id_list),
            memo=f"roll_no={roll_no}",
        )

    # 수정 후 주문 상태 재계산 (잠금 상태에서는 연결 주문이 변하지 않으므로 스킵)
    if not is_locked:
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

    # 재단에 사용된 입고는 삭제 차단
    if inbound_id in _get_locked_inbound_ids(svc):
        return RedirectResponse(url="/inbound?error=delete_locked", status_code=303)

    # 삭제 전 연결 주문 목록 저장
    all_rows = svc.get_all(SHEET)
    target = next((r for r in all_rows if r["inbound_id"] == inbound_id), None)
    linked_order_ids = []
    before_qty = 0
    if target:
        linked_order_ids = [o.strip() for o in str(target.get("order_ids", "")).split(",") if o.strip()]
        before_qty = int(target.get("inbound_qty", 0) or 0)

    svc.delete_row(SHEET, "inbound_id", inbound_id)

    # audit 로그
    if target:
        log_delete(
            svc, entity="ROLL_INBOUND", entity_id=inbound_id,
            before_data={"inbound_qty": before_qty},
            user=user.get("username", ""),
            related_order_id=",".join(linked_order_ids),
            memo=f"roll_no={target.get('roll_no','')}",
        )

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
    """입고 날짜 기준 다음 입고 번호 미리보기 (프론트엔드 AJAX 용)."""
    svc = get_sheets_service()
    target_date = date or today_str()
    all_inbound = svc.get_all(SHEET)
    return JSONResponse({"roll_no": generate_roll_no(all_inbound, target_date), "day_of_week": day_of_week(target_date)})


@router.get("/api/inbound")
async def api_inbound_list(q: str = ""):
    svc = get_sheets_service()
    return svc.search(SHEET, q, ["vendor", "roll_no"]) if q else svc.get_all(SHEET)
