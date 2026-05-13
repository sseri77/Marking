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


def _used_input_by_inbound(svc, exclude_cutting_id: str = "") -> dict:
    used: dict = {}
    for c in svc.get_all("CUTTING_PROCESS"):
        if c.get("cutting_id") == exclude_cutting_id:
            continue
        used[c.get("inbound_id", "")] = used.get(c.get("inbound_id", ""), 0) + _safe_int(c.get("input_qty"))
    return used


def _available_input_qty(svc, inbound_id: str, exclude_cutting_id: str = "") -> int:
    """해당 입고에서 아직 재단에 투입되지 않은 잔여 수량."""
    if not inbound_id:
        return 0
    inbound = next((r for r in svc.get_all("ROLL_INBOUND") if r.get("inbound_id") == inbound_id), None)
    if not inbound:
        return 0
    return _safe_int(inbound.get("inbound_qty")) - _used_input_by_inbound(svc, exclude_cutting_id).get(inbound_id, 0)


def _annotate_inbounds_available(svc, exclude_cutting_id: str = "") -> list:
    """입고 목록에 available_qty 필드를 붙인 새 리스트를 반환한다(원본 캐시 보호)."""
    used = _used_input_by_inbound(svc, exclude_cutting_id)
    annotated = []
    for ib in svc.get_all("ROLL_INBOUND"):
        total = _safe_int(ib.get("inbound_qty"))
        annotated.append({**ib, "available_qty": max(total - used.get(ib.get("inbound_id", ""), 0), 0)})
    return annotated


def _orders_for_cutting_form(svc, current_order_id: str = "") -> list:
    """재단 폼 ‘연결 주문’ 드롭다운용 목록.
    - 취소된 주문은 제외
    - 수정 모드에서는 현재 주문은 상태와 무관하게 항상 포함
    """
    excluded = {"취소"}
    return [
        o for o in svc.get_all("ORDER")
        if o.get("status") not in excluded or o.get("order_id") == current_order_id
    ]


def _validate_cutting_qty(
    svc,
    inbound_id: str,
    input_qty: int,
    success_qty: int,
    defect_qty: int,
    loss_qty: int,
    exclude_cutting_id: str = "",
) -> str | None:
    """재단 수량 정합성 검증.

    - input_qty == success_qty + defect_qty + loss_qty
    - input_qty 는 해당 입고의 잔여 가용 수량을 초과할 수 없다
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
    available = _available_input_qty(svc, inbound_id, exclude_cutting_id=exclude_cutting_id)
    if input_qty > available:
        return f"투입수량({input_qty}장)이 입고 잔여 수량({available}장)을 초과합니다."
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
    inbounds = _annotate_inbounds_available(svc)
    orders = _orders_for_cutting_form(svc)
    players = svc.get_all("PLAYER_MASTER")
    return templates.TemplateResponse(request, "cutting/form.html", {
        "user": user, "item": None,
        "inbounds": inbounds, "orders": orders, "players": players,
        "action": "create", "auto_manager": user["username"],
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
    manager: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    submitted = {
        "inbound_id": inbound_id, "order_id": order_id,
        "club_name": club_name, "collab_name": collab_name,
        "player_name": player_name, "player_number": player_number,
        "input_qty": input_qty, "success_qty": success_qty,
        "defect_qty": defect_qty, "loss_qty": loss_qty,
        "status": status, "manager": manager, "memo": memo,
    }
    error_message = _validate_cutting_qty(svc, inbound_id, input_qty, success_qty, defect_qty, loss_qty)
    if error_message:
        return templates.TemplateResponse(request, "cutting/form.html", {
            "user": user, "item": submitted,
            "inbounds": _annotate_inbounds_available(svc),
            "orders": _orders_for_cutting_form(svc, order_id),
            "players": svc.get_all("PLAYER_MASTER"), "action": "create",
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
    inbounds = _annotate_inbounds_available(svc, exclude_cutting_id=cutting_id)
    orders = _orders_for_cutting_form(svc, item.get("order_id", ""))
    players = svc.get_all("PLAYER_MASTER")
    return templates.TemplateResponse(request, "cutting/form.html", {
        "user": user, "item": item,
        "inbounds": inbounds, "orders": orders, "players": players,
        "action": "edit", "auto_manager": item.get("manager", user["username"]),
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
    manager: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    submitted = {
        "cutting_id": cutting_id,
        "inbound_id": inbound_id, "order_id": order_id,
        "club_name": club_name, "collab_name": collab_name,
        "player_name": player_name, "player_number": player_number,
        "input_qty": input_qty, "success_qty": success_qty,
        "defect_qty": defect_qty, "loss_qty": loss_qty,
        "status": status, "manager": manager, "memo": memo,
    }
    error_message = _validate_cutting_qty(
        svc, inbound_id, input_qty, success_qty, defect_qty, loss_qty,
        exclude_cutting_id=cutting_id,
    )
    if error_message:
        return templates.TemplateResponse(request, "cutting/form.html", {
            "user": user, "item": submitted,
            "inbounds": _annotate_inbounds_available(svc, exclude_cutting_id=cutting_id),
            "orders": _orders_for_cutting_form(svc, order_id),
            "players": svc.get_all("PLAYER_MASTER"), "action": "edit",
            "auto_manager": manager,
            "error": error_message,
        })

    # 변경 전 원본 (audit 비교용)
    before_item = next((r for r in svc.get_all(SHEET) if r.get("cutting_id") == cutting_id), {})
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
