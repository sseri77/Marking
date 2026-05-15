"""초기 재고 일괄 등록.

시스템 도입 시점에 이미 보유 중인 재고(미재단 원단 + 재단 완료 완성품)를
한 화면에서 일괄 등록하기 위한 페이지.

내부적으로 기존 흐름(ORDER → ROLL_INBOUND → CUTTING_PROCESS)에 행을 추가해
재고 집계 로직(`backend/api/inventory.py`)을 그대로 활용한다. 따라서:

- 미재단 수량 → ROLL_INBOUND 잔량(stock_waiting_cut)에 잡힘
- 재단 완료 수량 → CUTTING_PROCESS.success_qty (on_hand)에 잡힘
- 각 행은 메모 `[초기재고]` 태그로 추적 가능
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import (
    generate_id, now_str, today_str, require_auth, day_of_week, generate_roll_no,
)
from backend.utils.audit_log import log_create

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")

INITIAL_TAG = "[초기재고]"
INITIAL_VENDOR = "초기재고"


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _next_init_roll_no(existing_rolls: list[dict], seq_offset: int, date_str: str) -> str:
    """초기재고용 입고 번호: INIT-YYYYMMDD-NNN. 동일 일자 기준 순번."""
    compact = date_str.replace("-", "")
    prefix = f"INIT-{compact}-"
    max_seq = 0
    for r in existing_rolls:
        rno = str(r.get("roll_no", ""))
        if rno.startswith(prefix):
            try:
                seq = int(rno[len(prefix):])
                if seq > max_seq:
                    max_seq = seq
            except ValueError:
                pass
    return f"{prefix}{max_seq + seq_offset:03d}"


@router.get("/inventory/initial", response_class=HTMLResponse)
async def initial_inventory_form(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    clubs = svc.get_all("CLUB_MASTER")
    collabs = svc.get_all("COLLAB_MASTER")
    return templates.TemplateResponse(request, "inventory/initial.html", {
        "user": user,
        "clubs": clubs,
        "collabs": collabs,
        "today": today_str(),
        "auto_manager": user["username"],
    })


@router.post("/inventory/initial")
async def initial_inventory_submit(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    svc = get_sheets_service()

    today = today_str()
    dow = day_of_week(today)
    manager = (form.get("manager") or user["username"]).strip()
    common_memo = (form.get("memo") or "").strip()

    # 폼은 행 단위로 입력된다. 같은 인덱스의 필드를 묶어서 처리.
    indices: set[int] = set()
    for key in form.keys():
        if "[" in key and key.endswith("]"):
            try:
                idx = int(key.split("[")[1].rstrip("]"))
                indices.add(idx)
            except ValueError:
                continue

    errors: list[str] = []
    rows_to_create: list[dict] = []
    for idx in sorted(indices):
        def _g(field: str) -> str:
            return str(form.get(f"{field}[{idx}]", "")).strip()

        club_collab = _g("club_collab")
        player_name = _g("player_name")
        player_number = _g("player_number")
        uncut_qty = _safe_int(_g("uncut_qty"))
        cut_qty = _safe_int(_g("cut_qty"))
        row_memo = _g("row_memo")

        # 모든 핵심 필드가 비어있고 수량이 0이면 빈 행으로 간주하고 스킵
        if not (club_collab or player_name) and uncut_qty == 0 and cut_qty == 0:
            continue

        if uncut_qty < 0 or cut_qty < 0:
            errors.append(f"{idx + 1}번 행: 수량은 0 이상이어야 합니다.")
            continue
        if uncut_qty == 0 and cut_qty == 0:
            errors.append(f"{idx + 1}번 행: 미재단 또는 재단완료 수량 중 하나는 1 이상이어야 합니다.")
            continue
        if not club_collab:
            errors.append(f"{idx + 1}번 행: 구단/콜라보를 선택해주세요.")
            continue
        if not player_name:
            errors.append(f"{idx + 1}번 행: 선수명(또는 항목명)을 입력해주세요.")
            continue

        club_name, _, collab_name = club_collab.partition("|")
        rows_to_create.append({
            "club_name": club_name,
            "collab_name": collab_name,
            "player_name": player_name,
            "player_number": player_number,
            "uncut_qty": uncut_qty,
            "cut_qty": cut_qty,
            "row_memo": row_memo,
        })

    if errors:
        clubs = svc.get_all("CLUB_MASTER")
        collabs = svc.get_all("COLLAB_MASTER")
        return templates.TemplateResponse(request, "inventory/initial.html", {
            "user": user,
            "clubs": clubs,
            "collabs": collabs,
            "today": today,
            "auto_manager": manager,
            "error": " / ".join(errors),
            "submitted_rows": rows_to_create,
            "common_memo": common_memo,
        }, status_code=400)

    if not rows_to_create:
        return RedirectResponse(url="/inventory/initial?empty=1", status_code=303)

    existing_inbound = svc.get_all("ROLL_INBOUND")
    created_count = 0
    for i, r in enumerate(rows_to_create):
        total_qty = r["uncut_qty"] + r["cut_qty"]
        memo_parts = [INITIAL_TAG]
        if common_memo:
            memo_parts.append(common_memo)
        if r["row_memo"]:
            memo_parts.append(r["row_memo"])
        memo = " ".join(memo_parts)

        order_id = generate_id("ORD")
        if r["cut_qty"] > 0 and r["uncut_qty"] == 0:
            order_status = "재단완료"
        elif r["cut_qty"] > 0:
            order_status = "재단완료"
        else:
            order_status = "입고완료"

        svc.append_row("ORDER", {
            "order_id": order_id,
            "order_date": today,
            "club_name": r["club_name"],
            "collab_name": r["collab_name"],
            "order_type": "선수마킹",
            "player_name": r["player_name"],
            "player_number": r["player_number"],
            "qty": total_qty,
            "status": order_status,
            "memo": memo,
            "created_at": now_str(),
            "parent_order_id": "",
        })
        log_create(
            svc, entity="ORDER", entity_id=order_id,
            data={"qty": total_qty},
            user=user.get("username", ""),
            related_order_id=order_id,
            memo=f"{INITIAL_TAG} {r['club_name']}/{r['player_name']}#{r['player_number']}",
        )

        inbound_id = generate_id("RIB")
        roll_no = _next_init_roll_no(existing_inbound, i + 1, today)
        svc.append_row("ROLL_INBOUND", {
            "inbound_id": inbound_id,
            "inbound_date": today,
            "day_of_week": dow,
            "vendor": INITIAL_VENDOR,
            "roll_no": roll_no,
            "order_ids": order_id,
            "order_qty": total_qty,
            "inbound_qty": total_qty,
            "surplus_reason": "",
            "manager": manager,
            "memo": memo,
            "status": "입고완료",
            "created_at": now_str(),
        })
        log_create(
            svc, entity="ROLL_INBOUND", entity_id=inbound_id,
            data={"inbound_qty": total_qty},
            user=user.get("username", ""),
            related_order_id=order_id,
            memo=f"{INITIAL_TAG} roll_no={roll_no}",
        )

        if r["cut_qty"] > 0:
            cutting_id = generate_id("CUT")
            svc.append_row("CUTTING_PROCESS", {
                "cutting_id": cutting_id,
                "inbound_id": inbound_id,
                "order_id": order_id,
                "club_name": r["club_name"],
                "collab_name": r["collab_name"],
                "player_name": r["player_name"],
                "player_number": r["player_number"],
                "input_qty": r["cut_qty"],
                "success_qty": r["cut_qty"],
                "defect_qty": 0,
                "loss_qty": 0,
                "status": "완료",
                "manager": manager,
                "memo": memo,
                "created_at": now_str(),
            })
            log_create(
                svc, entity="CUTTING_PROCESS", entity_id=cutting_id,
                data={"input_qty": r["cut_qty"], "success_qty": r["cut_qty"],
                      "defect_qty": 0, "loss_qty": 0},
                user=user.get("username", ""),
                related_order_id=order_id,
                memo=f"{INITIAL_TAG} inbound_id={inbound_id}",
            )

        created_count += 1

    return RedirectResponse(url=f"/inventory?stock_filter=stock_total", status_code=303)
