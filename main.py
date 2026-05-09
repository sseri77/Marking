import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from backend.config import get_settings
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import require_auth
from backend.api import auth, clubs, collabs, players, inbound, cutting, outbound, inventory, search

settings = get_settings()

app = FastAPI(title=settings.APP_NAME, version="1.0.0")

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

templates = Jinja2Templates(directory="frontend/templates")

for router_module in [auth, clubs, collabs, players, inbound, cutting, outbound, inventory, search]:
    app.include_router(router_module.router)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    inbound_data = svc.get_all("MATERIAL_INBOUND")
    cutting_data = svc.get_all("CUTTING_PROCESS")
    outbound_data = svc.get_all("STORE_OUTBOUND")
    inventory_data = svc.get_all("INVENTORY_STATUS")
    clubs_data = svc.get_all("CLUB_MASTER")
    players_data = svc.get_all("PLAYER_MASTER")

    today = __import__("datetime").date.today().isoformat()

    stats = {
        "today_inbound": sum(int(i.get("qty", 0)) for i in inbound_data if i.get("date", "") == today),
        "today_cutting_success": sum(int(i.get("success_qty", 0)) for i in cutting_data if i.get("created_at", "").startswith(today)),
        "today_outbound": sum(int(i.get("qty", 0)) for i in outbound_data if i.get("shipping_date", "") == today),
        "low_stock_count": len([i for i in inventory_data if int(i.get("current_qty", 0)) <= int(i.get("safe_qty", 0))]),
        "total_clubs": len(clubs_data),
        "total_players": len(players_data),
        "in_progress_cutting": len([c for c in cutting_data if c.get("status") == "진행중"]),
        "total_inbound_qty": sum(int(i.get("qty", 0)) for i in inbound_data),
        "total_outbound_qty": sum(int(i.get("qty", 0)) for i in outbound_data),
    }

    store_summary = {}
    for o in outbound_data:
        store = o.get("store_name", "")
        store_summary[store] = store_summary.get(store, 0) + int(o.get("qty", 0))

    low_stock_items = [i for i in inventory_data if int(i.get("current_qty", 0)) <= int(i.get("safe_qty", 0))]
    recent_inbound = sorted(inbound_data, key=lambda x: x.get("date", ""), reverse=True)[:5]
    recent_outbound = sorted(outbound_data, key=lambda x: x.get("shipping_date", ""), reverse=True)[:5]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "stats": stats,
        "store_summary": store_summary,
        "low_stock_items": low_stock_items,
        "recent_inbound": recent_inbound,
        "recent_outbound": recent_outbound,
    })


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=settings.DEBUG)
