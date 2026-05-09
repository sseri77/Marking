from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import require_auth

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = "", type: str = "all"):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    results = {}
    if q:
        if type in ("all", "club"):
            results["clubs"] = svc.search("CLUB_MASTER", q, ["club_name"])
        if type in ("all", "collab"):
            results["collabs"] = svc.search("COLLAB_MASTER", q, ["collab_name"])
        if type in ("all", "player"):
            results["players"] = svc.search("PLAYER_MASTER", q, ["player_name", "player_number"])
        if type in ("all", "inbound"):
            results["inbound"] = svc.search("MATERIAL_INBOUND", q, ["vendor", "material_name", "lot_no"])
        if type in ("all", "outbound"):
            results["outbound"] = svc.search("STORE_OUTBOUND", q, ["store_name", "club_name", "player_name", "invoice_no"])
        total = sum(len(v) for v in results.values())
    else:
        total = 0
    return templates.TemplateResponse("search/index.html", {"request": request, "user": user, "q": q, "type": type, "results": results, "total": total})


@router.get("/api/search")
async def api_search(q: str = ""):
    if not q:
        return {"results": {}, "total": 0}
    svc = get_sheets_service()
    results = {
        "clubs": svc.search("CLUB_MASTER", q, ["club_name"]),
        "collabs": svc.search("COLLAB_MASTER", q, ["collab_name"]),
        "players": svc.search("PLAYER_MASTER", q, ["player_name", "player_number"]),
        "inbound": svc.search("MATERIAL_INBOUND", q, ["vendor", "material_name", "lot_no"]),
        "outbound": svc.search("STORE_OUTBOUND", q, ["store_name", "club_name", "player_name"]),
    }
    total = sum(len(v) for v in results.values())
    return {"results": results, "total": total, "query": q}
