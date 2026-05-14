from collections import defaultdict
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import require_auth, now_str

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _within_range(date_str: str, start: str, end: str) -> bool:
    if not date_str:
        return not (start or end)
    if start and date_str < start:
        return False
    if end and date_str > end:
        return False
    return True


def _build_history(
    svc,
    q: str = "",
    club: str = "",
    collab: str = "",
    status: str = "",
    start: str = "",
    end: str = "",
    order_id: str = "",
):
    """선수 단위 주문→입고→재단→출고 타임라인을 구성한다."""
    orders = svc.get_all("ORDER")
    inbounds = svc.get_all("ROLL_INBOUND")
    cuttings = svc.get_all("CUTTING_PROCESS")
    outbounds = svc.get_all("STORE_OUTBOUND")

    if order_id:
        orders = [o for o in orders if o.get("order_id") == order_id]

    if q:
        ql = q.lower()
        orders = [o for o in orders if ql in str(o.get("club_name", "")).lower()
                  or ql in str(o.get("collab_name", "")).lower()
                  or ql in str(o.get("player_name", "")).lower()
                  or ql in str(o.get("player_number", "")).lower()]
    if club:
        orders = [o for o in orders if o.get("club_name") == club]
    if collab:
        orders = [o for o in orders if o.get("collab_name") == collab]
    if status:
        orders = [o for o in orders if o.get("status") == status]
    if start or end:
        orders = [o for o in orders if _within_range(o.get("order_date", ""), start, end)]

    inbound_by_order = defaultdict(list)
    for ib in inbounds:
        oid_field = str(ib.get("order_ids", "")).strip()
        if not oid_field:
            continue
        for oid in [s.strip() for s in oid_field.split(",") if s.strip()]:
            inbound_by_order[oid].append(ib)

    cuttings_by_order = defaultdict(list)
    for c in cuttings:
        cuttings_by_order[c.get("order_id", "")].append(c)

    cutting_to_order = {c.get("cutting_id"): c.get("order_id") for c in cuttings}
    outbound_by_order = defaultdict(list)
    for ob in outbounds:
        oid = cutting_to_order.get(ob.get("cutting_id"), "")
        if oid:
            outbound_by_order[oid].append(ob)

    histories = []
    for o in orders:
        oid = o.get("order_id", "")
        ord_inbound = inbound_by_order.get(oid, [])
        ord_cuts = cuttings_by_order.get(oid, [])
        ord_outs = outbound_by_order.get(oid, [])

        ordered = _safe_int(o.get("qty"))
        cut_success = sum(_safe_int(c.get("success_qty")) for c in ord_cuts)
        outbound_qty = sum(_safe_int(ob.get("qty")) for ob in ord_outs)

        events = []
        events.append({
            "stage": "order",
            "label": "주문 등록",
            "date": o.get("order_date", ""),
            "qty": ordered,
            "memo": o.get("memo", ""),
            "ref": oid,
            "extra": {},
        })
        for ib in sorted(ord_inbound, key=lambda x: x.get("inbound_date", "")):
            events.append({
                "stage": "inbound",
                "label": "원단 입고",
                "date": ib.get("inbound_date", ""),
                "qty": _safe_int(ib.get("inbound_qty")),
                "memo": ib.get("memo", ""),
                "ref": ib.get("roll_no", ib.get("inbound_id", "")),
                "extra": {"업체": ib.get("vendor", ""), "담당": ib.get("manager", "")},
            })
        for c in sorted(ord_cuts, key=lambda x: x.get("created_at", "")):
            events.append({
                "stage": "cutting",
                "label": "재단",
                "date": (c.get("created_at") or "")[:10],
                "qty": _safe_int(c.get("success_qty")),
                "memo": c.get("memo", ""),
                "ref": c.get("cutting_id", ""),
                "extra": {
                    "투입": _safe_int(c.get("input_qty")),
                    "성공": _safe_int(c.get("success_qty")),
                    "불량": _safe_int(c.get("defect_qty")),
                    "로스": _safe_int(c.get("loss_qty")),
                    "담당": c.get("manager", ""),
                },
            })
        for ob in sorted(ord_outs, key=lambda x: x.get("shipping_date", "")):
            events.append({
                "stage": "outbound",
                "label": "매장 출고",
                "date": ob.get("shipping_date", ""),
                "qty": _safe_int(ob.get("qty")),
                "memo": ob.get("memo", ""),
                "ref": ob.get("invoice_no") or ob.get("outbound_id", ""),
                "extra": {
                    "매장": ob.get("store_name", ""),
                    "배송": ob.get("delivery_method", ""),
                    "담당": ob.get("manager", ""),
                },
            })

        events.sort(key=lambda e: (e["date"] or "", {"order": 0, "inbound": 1, "cutting": 2, "outbound": 3}.get(e["stage"], 9)))

        histories.append({
            "order": o,
            "events": events,
            "summary": {
                "ordered": ordered,
                "inbound": sum(_safe_int(ib.get("inbound_qty")) for ib in ord_inbound),
                "cut_success": cut_success,
                "outbound": outbound_qty,
                "remaining": max(ordered - outbound_qty, 0),
            },
        })

    histories.sort(key=lambda h: h["order"].get("order_date", ""), reverse=True)
    return histories


@router.get("/history", response_class=HTMLResponse)
async def history_page(
    request: Request,
    q: str = "",
    club: str = "",
    collab: str = "",
    status: str = "",
    start: str = "",
    end: str = "",
    order_id: str = "",
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    histories = _build_history(svc, q, club, collab, status, start, end, order_id)

    # 필터 옵션 (모든 주문 기준)
    all_orders = svc.get_all("ORDER")
    all_clubs = sorted({o.get("club_name", "") for o in all_orders if o.get("club_name")})
    all_collabs = sorted({o.get("collab_name", "") for o in all_orders if o.get("collab_name")})
    all_statuses = sorted({o.get("status", "") for o in all_orders if o.get("status")})

    totals = {
        "orders": len(histories),
        "ordered": sum(h["summary"]["ordered"] for h in histories),
        "inbound": sum(h["summary"]["inbound"] for h in histories),
        "cut_success": sum(h["summary"]["cut_success"] for h in histories),
        "outbound": sum(h["summary"]["outbound"] for h in histories),
        "remaining": sum(h["summary"]["remaining"] for h in histories),
    }

    return templates.TemplateResponse(request, "history/index.html", {
        "user": user,
        "histories": histories,
        "totals": totals,
        "all_clubs": all_clubs,
        "all_collabs": all_collabs,
        "all_statuses": all_statuses,
        "q": q,
        "club": club,
        "collab": collab,
        "status": status,
        "start": start,
        "end": end,
        "order_id": order_id,
    })


@router.get("/history/print", response_class=HTMLResponse)
async def history_print(
    request: Request,
    q: str = "",
    club: str = "",
    collab: str = "",
    status: str = "",
    start: str = "",
    end: str = "",
    order_id: str = "",
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    histories = _build_history(svc, q, club, collab, status, start, end, order_id)

    totals = {
        "orders": len(histories),
        "ordered": sum(h["summary"]["ordered"] for h in histories),
        "inbound": sum(h["summary"]["inbound"] for h in histories),
        "cut_success": sum(h["summary"]["cut_success"] for h in histories),
        "outbound": sum(h["summary"]["outbound"] for h in histories),
        "remaining": sum(h["summary"]["remaining"] for h in histories),
    }

    filters = {
        "검색어": q,
        "구단": club,
        "콜라보": collab,
        "상태": status,
        "기간 시작": start,
        "기간 종료": end,
        "주문 ID": order_id,
    }
    active_filters = {k: v for k, v in filters.items() if v}

    return templates.TemplateResponse(request, "history/print.html", {
        "user": user,
        "histories": histories,
        "totals": totals,
        "active_filters": active_filters,
        "printed_at": now_str(),
    })


@router.get("/api/history")
async def api_history(
    q: str = "",
    club: str = "",
    collab: str = "",
    status: str = "",
    start: str = "",
    end: str = "",
    order_id: str = "",
):
    svc = get_sheets_service()
    return _build_history(svc, q, club, collab, status, start, end, order_id)
