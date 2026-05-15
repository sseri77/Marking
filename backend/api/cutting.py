from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, today_str, require_auth, paginate
from backend.utils.audit_log import log_create, log_update, log_delete

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "CUTTING_PROCESS"


def _get_locked_cutting_ids(svc) -> set[str]:
    """출고(STORE_OUTBOUND)의 cutting_id 로 참조 중인 재단 cutting_id 집합."""
    outbounds = svc.get_all("STORE_OUTBOUND")
    return {(o.get("cutting_id") or "").strip() for o in outbounds if (o.get("cutting_id") or "").strip()}


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _used_input_by_inbound_order(svc, exclude_cutting_id: str = "") -> dict:
    """(inbound_id, order_id) 별 누적 투입 수량.

    1장에 여러 선수가 인쇄되는 경우, 입고 1장은 묶인 각 선수에 대해 1회씩
    독립적으로 재단될 수 있으므로 잔여는 (입고, 선수) 단위로 추적해야 한다.
    """
    used: dict = {}
    for c in svc.get_all("CUTTING_PROCESS"):
        if c.get("cutting_id") == exclude_cutting_id:
            continue
        key = (c.get("inbound_id", ""), c.get("order_id", ""))
        used[key] = used.get(key, 0) + _safe_int(c.get("input_qty"))
    return used


def _available_input_qty(svc, inbound_id: str, order_id: str, exclude_cutting_id: str = "") -> int:
    """해당 입고-선수 조합에서 아직 재단에 투입되지 않은 잔여 수량."""
    if not inbound_id:
        return 0
    inbound = next((r for r in svc.get_all("ROLL_INBOUND") if r.get("inbound_id") == inbound_id), None)
    if not inbound:
        return 0
    used = _used_input_by_inbound_order(svc, exclude_cutting_id).get((inbound_id, order_id), 0)
    return _safe_int(inbound.get("inbound_qty")) - used


def _inbound_order_pairs(
    svc,
    exclude_cutting_id: str = "",
    current_inbound_id: str = "",
    current_order_id: str = "",
) -> list:
    """재단 폼 통합 셀렉트용 (입고 × 주문) 페어 목록.

    잔여가 있는 (입고, 주문) 조합만 반환한다. 수정 모드의 현재 선택은 잔여/취소 여부와
    무관하게 항상 포함된다. 한 입고에 여러 선수가 묶여 있으면 각 선수마다 별도 페어가
    만들어진다.
    """
    used = _used_input_by_inbound_order(svc, exclude_cutting_id)
    orders_by_id = {o.get("order_id"): o for o in svc.get_all("ORDER")}
    pairs = []
    for ib in svc.get_all("ROLL_INBOUND"):
        inb_id = ib.get("inbound_id", "")
        total = _safe_int(ib.get("inbound_qty"))
        order_ids = [o.strip() for o in str(ib.get("order_ids", "")).split(",") if o.strip()]
        for oid in order_ids:
            order = orders_by_id.get(oid)
            if not order:
                continue
            is_current = (inb_id == current_inbound_id and oid == current_order_id)
            if order.get("status") == "취소" and not is_current:
                continue
            remaining = max(total - used.get((inb_id, oid), 0), 0)
            if remaining <= 0 and not is_current:
                continue
            pairs.append({
                "inbound_id": inb_id,
                "order_id": oid,
                "inbound_date": ib.get("inbound_date", ""),
                "day_of_week": ib.get("day_of_week", ""),
                "vendor": ib.get("vendor", ""),
                "roll_no": ib.get("roll_no", ""),
                "club_name": order.get("club_name", ""),
                "collab_name": order.get("collab_name", ""),
                "player_name": order.get("player_name", ""),
                "player_number": order.get("player_number", ""),
                "order_type": order.get("order_type", "") or "선수마킹",
                "order_qty": _safe_int(order.get("qty")),
                "remaining": remaining,
                "is_current": is_current,
            })
    pairs.sort(key=lambda p: (p["inbound_date"], p["club_name"], p["player_name"]), reverse=True)
    return pairs


def _validate_cutting_qty(
    svc,
    inbound_id: str,
    order_id: str,
    input_qty: int,
    success_qty: int,
    defect_qty: int,
    loss_qty: int,
    exclude_cutting_id: str = "",
) -> str | None:
    """재단 수량 정합성 검증.

    - input_qty == success_qty + defect_qty + loss_qty
    - input_qty 는 해당 입고-선수 조합의 잔여 가용 수량을 초과할 수 없다
      (1장에 여러 선수가 인쇄되므로 잔여는 선수별로 독립 추적)
    - 각 수량은 음수일 수 없다

    위반 시 한국어 오류 메시지 문자열을 반환, 정상이면 None.
    """
    if input_qty < 0 or success_qty < 0 or defect_qty < 0 or loss_qty < 0:
        return "수량은 0 이상이어야 합니다."
    total = success_qty + defect_qty + loss_qty
    if input_qty != total:
        return (
            f"투입수량({input_qty}장)이 성공({success_qty}) + 불량({defect_qty}) + 로스({loss_qty}) "
            f"= {total}장과 일치해야 합니다."
        )
    available = _available_input_qty(svc, inbound_id, order_id, exclude_cutting_id=exclude_cutting_id)
    if input_qty > available:
        return f"투입수량({input_qty}장)이 해당 선수의 입고 잔여 수량({available}장)을 초과합니다."
    return None


def _create_defect_reorder(svc, cutting_id: str, original_order_id: str, defect_qty: int) -> None:
    """재단완료 시점에 불량 수량만큼 동일 선수로 새 주문을 등록한다.
    동일 cutting_id 기준으로 이미 생성된 재발주가 있으면 중복 생성하지 않는다."""
    if defect_qty <= 0 or not original_order_id:
        return
    orders = svc.get_all("ORDER")
    tag = f"[{cutting_id}]"
    if any(tag in (o.get("memo") or "") for o in orders):
        return
    original = next((o for o in orders if o.get("order_id") == original_order_id), None)
    if not original:
        return
    svc.append_row("ORDER", {
        "order_id": generate_id("ORD"),
        "order_date": today_str(),
        "club_name": original.get("club_name", ""),
        "collab_name": original.get("collab_name", ""),
        "order_type": original.get("order_type", "") or "선수마킹",
        "player_name": original.get("player_name", ""),
        "player_number": original.get("player_number", ""),
        "qty": defect_qty,
        "status": "주문완료",
        "memo": f"{tag} 불량 재발주 (원본 {original_order_id})",
        "created_at": now_str(),
        "parent_order_id": original_order_id,
    })


@router.get("/cutting", response_class=HTMLResponse)
async def cutting_list(request: Request, q: str = "", page: int = 1, error: str = ""):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["club_name", "player_name", "player_number", "inbound_id"]) if q else svc.get_all(SHEET)
    data = sorted(data, key=lambda x: x.get("created_at", ""), reverse=True)
    locked_cutting_ids = _get_locked_cutting_ids(svc)
    error_message = ""
    if error == "delete_locked":
        error_message = "출고에 사용된 재단 기록은 삭제할 수 없습니다. 먼저 관련 출고 기록을 삭제하세요."
    paged = paginate(data, page)
    return templates.TemplateResponse(request, "cutting/index.html", {
        "user": user, "q": q,
        "locked_cutting_ids": locked_cutting_ids,
        "error_message": error_message,
        **paged,
    })


@router.get("/cutting/new", response_class=HTMLResponse)
async def cutting_new(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    pairs = _inbound_order_pairs(svc)
    return templates.TemplateResponse(request, "cutting/form.html", {
        "user": user, "item": None,
        "pairs": pairs,
        "action": "create", "auto_manager": user["username"],
    })


def _order_info(svc, order_id: str) -> dict:
    if not order_id:
        return {}
    return next((o for o in svc.get_all("ORDER") if o.get("order_id") == order_id), {}) or {}


@router.post("/cutting/new")
async def cutting_create(
    request: Request,
    inbound_id: str = Form(...),
    order_id: str = Form(...),
    input_qty: int = Form(...),
    success_qty: int = Form(...),
    defect_qty: int = Form(0),
    loss_qty: int = Form(0),
    mark_done: str = Form(""),
    manager: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    status = "완료" if mark_done else "진행중"
    order = _order_info(svc, order_id)
    club_name = order.get("club_name", "")
    collab_name = order.get("collab_name", "")
    player_name = order.get("player_name", "")
    player_number = order.get("player_number", "")
    submitted = {
        "inbound_id": inbound_id, "order_id": order_id,
        "input_qty": input_qty, "success_qty": success_qty,
        "defect_qty": defect_qty, "loss_qty": loss_qty,
        "status": status, "manager": manager, "memo": memo,
    }
    error_message = _validate_cutting_qty(svc, inbound_id, order_id, input_qty, success_qty, defect_qty, loss_qty)
    if error_message:
        return templates.TemplateResponse(request, "cutting/form.html", {
            "user": user, "item": submitted,
            "pairs": _inbound_order_pairs(svc, current_inbound_id=inbound_id, current_order_id=order_id),
            "action": "create",
            "auto_manager": manager,
            "error": error_message,
        })
    cutting_id = generate_id("CUT")
    svc.append_row(SHEET, {
        "cutting_id": cutting_id,
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
        "manager": manager,
        "memo": memo,
        "created_at": now_str(),
    })
    log_create(
        svc, entity="CUTTING_PROCESS", entity_id=cutting_id,
        data={"input_qty": input_qty, "success_qty": success_qty,
              "defect_qty": defect_qty, "loss_qty": loss_qty},
        user=user.get("username", ""), related_order_id=order_id,
        memo=f"inbound_id={inbound_id}",
    )
    if status == "완료":
        svc.update_row("ORDER", "order_id", order_id, {"status": "재단완료"})
        _create_defect_reorder(svc, cutting_id, order_id, defect_qty)
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
    # 기존 데이터에 worker 필드가 있으면 manager로 마이그레이션
    if not item.get("manager") and item.get("worker"):
        item["manager"] = item["worker"]
    pairs = _inbound_order_pairs(
        svc,
        exclude_cutting_id=cutting_id,
        current_inbound_id=item.get("inbound_id", ""),
        current_order_id=item.get("order_id", ""),
    )
    return templates.TemplateResponse(request, "cutting/form.html", {
        "user": user, "item": item,
        "pairs": pairs,
        "action": "edit", "auto_manager": item.get("manager", user["username"]),
    })


@router.post("/cutting/{cutting_id}/edit")
async def cutting_update(
    request: Request,
    cutting_id: str,
    inbound_id: str = Form(...),
    order_id: str = Form(...),
    input_qty: int = Form(...),
    success_qty: int = Form(...),
    defect_qty: int = Form(0),
    loss_qty: int = Form(0),
    status: str = Form("진행중"),
    manager: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    order = _order_info(svc, order_id)
    before_item = next((r for r in svc.get_all(SHEET) if r.get("cutting_id") == cutting_id), {})
    club_name = order.get("club_name") or before_item.get("club_name", "")
    collab_name = order.get("collab_name") or before_item.get("collab_name", "")
    player_name = order.get("player_name") or before_item.get("player_name", "")
    player_number = order.get("player_number") or before_item.get("player_number", "")
    submitted = {
        "cutting_id": cutting_id,
        "inbound_id": inbound_id, "order_id": order_id,
        "input_qty": input_qty, "success_qty": success_qty,
        "defect_qty": defect_qty, "loss_qty": loss_qty,
        "status": status, "manager": manager, "memo": memo,
    }
    error_message = _validate_cutting_qty(
        svc, inbound_id, order_id, input_qty, success_qty, defect_qty, loss_qty,
        exclude_cutting_id=cutting_id,
    )
    if error_message:
        return templates.TemplateResponse(request, "cutting/form.html", {
            "user": user, "item": submitted,
            "pairs": _inbound_order_pairs(
                svc,
                exclude_cutting_id=cutting_id,
                current_inbound_id=inbound_id,
                current_order_id=order_id,
            ),
            "action": "edit",
            "auto_manager": manager,
            "error": error_message,
        })

    before_qty = {
        "input_qty": _safe_int(before_item.get("input_qty")),
        "success_qty": _safe_int(before_item.get("success_qty")),
        "defect_qty": _safe_int(before_item.get("defect_qty")),
        "loss_qty": _safe_int(before_item.get("loss_qty")),
    }

    svc.update_row(SHEET, "cutting_id", cutting_id, {
        "inbound_id": inbound_id, "order_id": order_id,
        "club_name": club_name, "collab_name": collab_name,
        "player_name": player_name, "player_number": player_number,
        "input_qty": input_qty, "success_qty": success_qty,
        "defect_qty": defect_qty, "loss_qty": loss_qty,
        "status": status, "manager": manager, "memo": memo,
    })
    log_update(
        svc, entity="CUTTING_PROCESS", entity_id=cutting_id,
        before_data=before_qty,
        after_data={"input_qty": input_qty, "success_qty": success_qty,
                    "defect_qty": defect_qty, "loss_qty": loss_qty},
        user=user.get("username", ""), related_order_id=order_id,
        memo=f"inbound_id={inbound_id}",
    )
    if status == "완료":
        svc.update_row("ORDER", "order_id", order_id, {"status": "재단완료"})
        _create_defect_reorder(svc, cutting_id, order_id, defect_qty)
    return RedirectResponse(url="/cutting", status_code=303)


@router.post("/cutting/{cutting_id}/delete")
async def cutting_delete(request: Request, cutting_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    # 출고에 사용된 재단은 삭제 차단
    if cutting_id in _get_locked_cutting_ids(svc):
        return RedirectResponse(url="/cutting?error=delete_locked", status_code=303)
    before_item = next((r for r in svc.get_all(SHEET) if r.get("cutting_id") == cutting_id), None)
    svc.delete_row(SHEET, "cutting_id", cutting_id)
    if before_item:
        log_delete(
            svc, entity="CUTTING_PROCESS", entity_id=cutting_id,
            before_data={
                "input_qty": _safe_int(before_item.get("input_qty")),
                "success_qty": _safe_int(before_item.get("success_qty")),
                "defect_qty": _safe_int(before_item.get("defect_qty")),
                "loss_qty": _safe_int(before_item.get("loss_qty")),
            },
            user=user.get("username", ""),
            related_order_id=before_item.get("order_id", ""),
            memo=f"inbound_id={before_item.get('inbound_id','')}",
        )
    return RedirectResponse(url="/cutting", status_code=303)


@router.get("/api/cutting")
async def api_cutting_list(q: str = ""):
    svc = get_sheets_service()
    return svc.search(SHEET, q, ["club_name", "player_name", "inbound_id"]) if q else svc.get_all(SHEET)
