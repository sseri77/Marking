"""월별(=1개월 일자별) 재단·출고 보고서.

- 일별 추이(line/bar): 재단(투입/성공/불량/로스), 출고(수량)
- 분해 축: 구단별 / 콜라보(원단)별 / 매장별(출고 한정)
- 차트는 Chart.js 로 렌더, 데이터는 템플릿에 JSON 으로 직렬화해 주입.
"""
from collections import defaultdict
from datetime import date, timedelta
from calendar import monthrange
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import require_auth, now_str

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_year_month(year: str, month: str) -> tuple[int, int]:
    today = date.today()
    try:
        y = int(year) if year else today.year
    except ValueError:
        y = today.year
    try:
        m = int(month) if month else today.month
    except ValueError:
        m = today.month
    if not (1 <= m <= 12):
        m = today.month
    return y, m


def _month_bounds(y: int, m: int) -> tuple[date, date]:
    start = date(y, m, 1)
    end = date(y, m, monthrange(y, m)[1])
    return start, end


def _prev_next_month(y: int, m: int) -> tuple[tuple[int, int], tuple[int, int]]:
    prev_m = m - 1 or 12
    prev_y = y - 1 if m == 1 else y
    next_m = m + 1 if m < 12 else 1
    next_y = y + 1 if m == 12 else y
    return (prev_y, prev_m), (next_y, next_m)


def _date_key_cutting(c: dict) -> str:
    """재단 일자 키. created_at 의 YYYY-MM-DD 부분."""
    return (str(c.get("created_at") or "")[:10])


def _date_key_outbound(o: dict) -> str:
    """출고 일자 키. shipping_date 우선."""
    return str(o.get("shipping_date") or "")[:10]


def _in_range(d: str, start: date, end: date) -> bool:
    if not d or len(d) < 10:
        return False
    return start.isoformat() <= d <= end.isoformat()


def _build_report(
    svc,
    y: int,
    m: int,
    club: str = "",
    collab: str = "",
    store: str = "",
) -> dict:
    cuttings = svc.get_all("CUTTING_PROCESS")
    outbounds = svc.get_all("STORE_OUTBOUND")

    start, end = _month_bounds(y, m)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    day_keys = [d.isoformat() for d in days]
    day_labels = [f"{d.day}일" for d in days]

    def _cut_ok(c: dict) -> bool:
        if club and c.get("club_name") != club:
            return False
        if collab and c.get("collab_name") != collab:
            return False
        return _in_range(_date_key_cutting(c), start, end)

    def _out_ok(o: dict) -> bool:
        if club and o.get("club_name") != club:
            return False
        if collab and o.get("collab_name") != collab:
            return False
        if store and o.get("store_name") != store:
            return False
        return _in_range(_date_key_outbound(o), start, end)

    period_cuts = [c for c in cuttings if _cut_ok(c)]
    period_outs = [o for o in outbounds if _out_ok(o)]

    # 일별 시리즈
    daily_cut = {k: {"input": 0, "success": 0, "defect": 0, "loss": 0} for k in day_keys}
    daily_out = {k: 0 for k in day_keys}
    for c in period_cuts:
        k = _date_key_cutting(c)
        if k in daily_cut:
            daily_cut[k]["input"] += _safe_int(c.get("input_qty"))
            daily_cut[k]["success"] += _safe_int(c.get("success_qty"))
            daily_cut[k]["defect"] += _safe_int(c.get("defect_qty"))
            daily_cut[k]["loss"] += _safe_int(c.get("loss_qty"))
    for o in period_outs:
        k = _date_key_outbound(o)
        if k in daily_out:
            daily_out[k] += _safe_int(o.get("qty"))

    # 총합
    totals = {
        "cut_input": sum(d["input"] for d in daily_cut.values()),
        "cut_success": sum(d["success"] for d in daily_cut.values()),
        "cut_defect": sum(d["defect"] for d in daily_cut.values()),
        "cut_loss": sum(d["loss"] for d in daily_cut.values()),
        "outbound": sum(daily_out.values()),
        "cut_records": len(period_cuts),
        "out_records": len(period_outs),
    }

    # 분해 — 구단별 / 콜라보별 / 매장별
    by_club: dict = defaultdict(lambda: {"cut_success": 0, "cut_defect": 0, "outbound": 0})
    by_collab: dict = defaultdict(lambda: {"cut_success": 0, "cut_defect": 0, "outbound": 0})
    by_store: dict = defaultdict(int)

    for c in period_cuts:
        cn = c.get("club_name") or "(미지정)"
        co = c.get("collab_name") or "(미지정)"
        by_club[cn]["cut_success"] += _safe_int(c.get("success_qty"))
        by_club[cn]["cut_defect"] += _safe_int(c.get("defect_qty"))
        by_collab[co]["cut_success"] += _safe_int(c.get("success_qty"))
        by_collab[co]["cut_defect"] += _safe_int(c.get("defect_qty"))

    for o in period_outs:
        cn = o.get("club_name") or "(미지정)"
        co = o.get("collab_name") or "(미지정)"
        st = o.get("store_name") or "(미지정)"
        q = _safe_int(o.get("qty"))
        by_club[cn]["outbound"] += q
        by_collab[co]["outbound"] += q
        by_store[st] += q

    def _sorted(d: dict, key_fn):
        return sorted(d.items(), key=key_fn, reverse=True)

    club_rows = _sorted(by_club, lambda kv: kv[1]["cut_success"] + kv[1]["outbound"])
    collab_rows = _sorted(by_collab, lambda kv: kv[1]["cut_success"] + kv[1]["outbound"])
    store_rows = sorted(by_store.items(), key=lambda kv: kv[1], reverse=True)

    return {
        "year": y,
        "month": m,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "day_keys": day_keys,
        "day_labels": day_labels,
        "daily_cut": [daily_cut[k] for k in day_keys],
        "daily_out": [daily_out[k] for k in day_keys],
        "totals": totals,
        "club_rows": club_rows,
        "collab_rows": collab_rows,
        "store_rows": store_rows,
    }


def _all_filter_options(svc) -> dict:
    """필터 드롭다운에 노출할 구단/콜라보/매장 목록."""
    clubs = sorted({c.get("club_name", "") for c in svc.get_all("CLUB_MASTER") if c.get("club_name")})
    collabs = sorted({c.get("collab_name", "") for c in svc.get_all("COLLAB_MASTER") if c.get("collab_name")})
    stores = sorted({s.get("store_name", "") for s in svc.get_all("STORE_MASTER") if s.get("store_name")})
    return {"clubs": clubs, "collabs": collabs, "stores": stores}


@router.get("/reports/monthly", response_class=HTMLResponse)
async def reports_monthly(
    request: Request,
    year: str = "",
    month: str = "",
    club: str = "",
    collab: str = "",
    store: str = "",
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    y, m = _parse_year_month(year, month)
    report = _build_report(svc, y, m, club=club, collab=collab, store=store)
    (prev_y, prev_m), (next_y, next_m) = _prev_next_month(y, m)

    return templates.TemplateResponse(request, "reports/monthly.html", {
        "user": user,
        "report": report,
        "filters": {"club": club, "collab": collab, "store": store},
        "options": _all_filter_options(svc),
        "prev_y": prev_y, "prev_m": prev_m,
        "next_y": next_y, "next_m": next_m,
    })


@router.get("/reports/monthly/print", response_class=HTMLResponse)
async def reports_monthly_print(
    request: Request,
    year: str = "",
    month: str = "",
    club: str = "",
    collab: str = "",
    store: str = "",
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    y, m = _parse_year_month(year, month)
    report = _build_report(svc, y, m, club=club, collab=collab, store=store)
    active_filters = {k: v for k, v in {"구단": club, "콜라보": collab, "매장": store}.items() if v}
    return templates.TemplateResponse(request, "reports/print.html", {
        "user": user,
        "report": report,
        "active_filters": active_filters,
        "printed_at": now_str(),
    })
