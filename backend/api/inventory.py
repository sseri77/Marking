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


def _build_inventory_rows(svc):
    """주문/입고/재단/출고 데이터를 집계해 선수별 재고 현황을 만든다."""
    orders = svc.get_all("ORDER")
    inbounds = svc.get_all("ROLL_INBOUND")
    cuttings = svc.get_all("CUTTING_PROCESS")
    outbounds = svc.get_all("STORE_OUTBOUND")

    inbound_by_order = defaultdict(int)
    for ib in inbounds:
        oid_field = str(ib.get("order_ids", "")).strip()
        if not oid_field:
            continue
        ids = [s.strip() for s in oid_field.split(",") if s.strip()]
        qty = _safe_int(ib.get("inbound_qty"))
        if not ids:
            continue
        share = qty // len(ids) if qty else 0
        for oid in ids:
            inbound_by_order[oid] += share

    cutting_by_order = defaultdict(lambda: {"input": 0, "success": 0, "defect": 0, "loss": 0})
    for c in cuttings:
        oid = c.get("order_id", "")
        cutting_by_order[oid]["input"] += _safe_int(c.get("input_qty"))
        cutting_by_order[oid]["success"] += _safe_int(c.get("success_qty"))
        cutting_by_order[oid]["defect"] += _safe_int(c.get("defect_qty"))
        cutting_by_order[oid]["loss"] += _safe_int(c.get("loss_qty"))

    cutting_to_order = {c.get("cutting_id"): c.get("order_id") for c in cuttings}
    outbound_by_order = defaultdict(int)
    for ob in outbounds:
        oid = cutting_to_order.get(ob.get("cutting_id"), "")
        if oid:
            outbound_by_order[oid] += _safe_int(ob.get("qty"))

    rows = []
    for o in orders:
        oid = o.get("order_id", "")
        ordered = _safe_int(o.get("qty"))
        inbound_qty = inbound_by_order.get(oid, 0)
        cut = cutting_by_order.get(oid, {"input": 0, "success": 0, "defect": 0, "loss": 0})
        out_qty = outbound_by_order.get(oid, 0)
        remaining = max(ordered - out_qty, 0)
        on_hand = max(cut["success"] - out_qty, 0)
        rows.append({
            "order_id": oid,
            "order_date": o.get("order_date", ""),
            "club_name": o.get("club_name", ""),
            "collab_name": o.get("collab_name", ""),
            "player_name": o.get("player_name", ""),
            "player_number": o.get("player_number", ""),
            "status": o.get("status", ""),
            "ordered": ordered,
            "inbound": inbound_qty,
            "cut_input": cut["input"],
            "cut_success": cut["success"],
            "cut_defect": cut["defect"],
            "cut_loss": cut["loss"],
            "outbound": out_qty,
            "on_hand": on_hand,
            "remaining": remaining,
        })
    return rows


def _filter_rows(all_rows, q: str, club: str, status: str, stock_filter: str):
    rows = all_rows
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["club_name"].lower()
                or ql in r["collab_name"].lower()
                or ql in r["player_name"].lower()
                or ql in str(r["player_number"]).lower()]
    if club:
        rows = [r for r in rows if r["club_name"] == club]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if stock_filter == "on_hand":
        rows = [r for r in rows if r["on_hand"] > 0]
    elif stock_filter == "shortage":
        rows = [r for r in rows if r["cut_success"] < r["ordered"]]
    elif stock_filter == "completed":
        rows = [r for r in rows if r["remaining"] == 0 and r["ordered"] > 0]
    rows.sort(key=lambda r: r["order_date"], reverse=True)
    return rows


@router.get("/inventory", response_class=HTMLResponse)
async def inventory_status(
    request: Request,
    q: str = "",
    club: str = "",
    status: str = "",
    stock_filter: str = "",
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    all_rows = _build_inventory_rows(svc)
    rows = _filter_rows(all_rows, q, club, status, stock_filter)

    summary = {
        "total_ordered": sum(r["ordered"] for r in rows),
        "total_inbound": sum(r["inbound"] for r in rows),
        "total_cut_success": sum(r["cut_success"] for r in rows),
        "total_outbound": sum(r["outbound"] for r in rows),
        "total_on_hand": sum(r["on_hand"] for r in rows),
        "total_remaining": sum(r["remaining"] for r in rows),
    }

    club_totals = defaultdict(lambda: {"ordered": 0, "cut_success": 0, "outbound": 0, "on_hand": 0, "remaining": 0})
    for r in rows:
        ct = club_totals[r["club_name"] or "(미지정)"]
        ct["ordered"] += r["ordered"]
        ct["cut_success"] += r["cut_success"]
        ct["outbound"] += r["outbound"]
        ct["on_hand"] += r["on_hand"]
        ct["remaining"] += r["remaining"]
    club_summary = sorted(club_totals.items(), key=lambda kv: kv[1]["remaining"], reverse=True)

    all_clubs = sorted({r["club_name"] for r in all_rows if r["club_name"]})
    all_statuses = sorted({r["status"] for r in all_rows if r["status"]})

    return templates.TemplateResponse(request, "inventory/index.html", {
        "user": user,
        "rows": rows,
        "summary": summary,
        "club_summary": club_summary,
        "all_clubs": all_clubs,
        "all_statuses": all_statuses,
        "q": q,
        "club": club,
        "status": status,
        "stock_filter": stock_filter,
    })


@router.get("/inventory/print", response_class=HTMLResponse)
async def inventory_print(
    request: Request,
    q: str = "",
    club: str = "",
    status: str = "",
    stock_filter: str = "",
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    all_rows = _build_inventory_rows(svc)
    rows = _filter_rows(all_rows, q, club, status, stock_filter)

    summary = {
        "total_ordered": sum(r["ordered"] for r in rows),
        "total_inbound": sum(r["inbound"] for r in rows),
        "total_cut_success": sum(r["cut_success"] for r in rows),
        "total_outbound": sum(r["outbound"] for r in rows),
        "total_on_hand": sum(r["on_hand"] for r in rows),
        "total_remaining": sum(r["remaining"] for r in rows),
    }

    club_totals = defaultdict(lambda: {"ordered": 0, "cut_success": 0, "outbound": 0, "on_hand": 0, "remaining": 0})
    for r in rows:
        ct = club_totals[r["club_name"] or "(미지정)"]
        ct["ordered"] += r["ordered"]
        ct["cut_success"] += r["cut_success"]
        ct["outbound"] += r["outbound"]
        ct["on_hand"] += r["on_hand"]
        ct["remaining"] += r["remaining"]
    club_summary = sorted(club_totals.items(), key=lambda kv: kv[1]["remaining"], reverse=True)

    stock_filter_labels = {
        "on_hand": "보유 재고 있음",
        "shortage": "재단 미완료",
        "completed": "출고 완료",
    }
    filters = {
        "검색어": q,
        "구단": club,
        "상태": status,
        "재고 필터": stock_filter_labels.get(stock_filter, ""),
    }
    active_filters = {k: v for k, v in filters.items() if v}

    return templates.TemplateResponse(request, "inventory/print.html", {
        "user": user,
        "rows": rows,
        "summary": summary,
        "club_summary": club_summary,
        "active_filters": active_filters,
        "printed_at": now_str(),
    })


@router.get("/api/inventory")
async def api_inventory(q: str = "", stock_filter: str = ""):
    svc = get_sheets_service()
    rows = _build_inventory_rows(svc)
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["club_name"].lower()
                or ql in r["player_name"].lower()
                or ql in str(r["player_number"]).lower()]
    if stock_filter == "on_hand":
        rows = [r for r in rows if r["on_hand"] > 0]
    elif stock_filter == "remaining":
        rows = [r for r in rows if r["remaining"] > 0]
    return rows
