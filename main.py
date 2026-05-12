import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from backend.config import get_settings
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import require_auth
from backend.api import auth, clubs, collabs, players, printers, stores, orders, inbound, cutting, outbound, search

settings = get_settings()


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

app = FastAPI(title=settings.APP_NAME, version="1.0.0")

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

templates = Jinja2Templates(directory="frontend/templates")

for router_module in [auth, clubs, collabs, players, printers, stores, orders, inbound, cutting, outbound, search]:
    app.include_router(router_module.router)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    today = __import__("datetime").date.today().isoformat()

    order_data = svc.get_all("ORDER")
    inbound_data = svc.get_all("ROLL_INBOUND")
    cutting_data = svc.get_all("CUTTING_PROCESS")
    outbound_data = svc.get_all("STORE_OUTBOUND")
    clubs_data = svc.get_all("CLUB_MASTER")
    players_data = svc.get_all("PLAYER_MASTER")

    stats = {
        "total_orders": len(order_data),
        "pending_orders": len([o for o in order_data if o.get("status") == "주문완료"]),
        "today_inbound": len([i for i in inbound_data if i.get("inbound_date", "") == today]),
        "in_progress_cutting": len([c for c in cutting_data if c.get("status") == "진행중"]),
        "today_outbound": sum(_safe_int(o.get("qty")) for o in outbound_data if o.get("shipping_date", "") == today),
        "total_clubs": len(clubs_data),
        "total_players": len(players_data),
        "total_cutting_success": sum(_safe_int(c.get("success_qty")) for c in cutting_data),
        "total_outbound_qty": sum(_safe_int(o.get("qty")) for o in outbound_data),
    }

    # 주문 현황 (상태별)
    order_status = {}
    for o in order_data:
        s = o.get("status", "")
        order_status[s] = order_status.get(s, 0) + 1

    # 매장별 출고 현황
    store_summary = {}
    for o in outbound_data:
        store = o.get("store_name", "")
        store_summary[store] = store_summary.get(store, 0) + _safe_int(o.get("qty"))

    recent_orders = sorted(order_data, key=lambda x: x.get("order_date", ""), reverse=True)[:5]
    recent_outbound = sorted(outbound_data, key=lambda x: x.get("shipping_date", ""), reverse=True)[:5]
    in_progress_cuttings = [c for c in cutting_data if c.get("status") == "진행중"][:5]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "stats": stats,
        "order_status": order_status,
        "store_summary": store_summary,
        "recent_orders": recent_orders,
        "recent_outbound": recent_outbound,
        "in_progress_cuttings": in_progress_cuttings,
    })


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=settings.DEBUG)
