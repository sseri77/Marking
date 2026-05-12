from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, require_auth, paginate

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "PLAYER_MASTER"


@router.get("/players", response_class=HTMLResponse)
async def players_list(request: Request, q: str = "", page: int = 1):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["player_name", "player_number", "club_name", "collab_name"]) if q else svc.get_all(SHEET)
    paged = paginate(data, page)
    return templates.TemplateResponse(request, "players/index.html", {"user": user, "q": q, **paged})


@router.get("/players/new", response_class=HTMLResponse)
async def players_new(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    clubs = svc.get_all("CLUB_MASTER")
    collabs = svc.get_all("COLLAB_MASTER")
    return templates.TemplateResponse(request, "players/form.html", {"user": user, "player": None, "clubs": clubs, "collabs": collabs, "action": "create"})


@router.post("/players/new")
async def players_create(
    request: Request,
    club_name: str = Form(...),
    collab_name: str = Form(...),
    player_name: str = Form(...),
    player_number: str = Form(...),
    status: str = Form("활성"),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    existing = svc.get_all(SHEET)
    duplicate = next((p for p in existing if p.get("club_name") == club_name and p.get("collab_name") == collab_name and str(p.get("player_number")) == str(player_number)), None)
    if duplicate:
        clubs = svc.get_all("CLUB_MASTER")
        collabs = svc.get_all("COLLAB_MASTER")
        return templates.TemplateResponse(request, "players/form.html", {"user": user, "player": None, "clubs": clubs, "collabs": collabs, "action": "create", "error": f"선수번호 {player_number}번은 해당 구단/콜라보에 이미 등록되어 있습니다."})
    ts = now_str()
    svc.append_row(SHEET, {"player_id": generate_id("PLY"), "club_name": club_name, "collab_name": collab_name, "player_name": player_name, "player_number": player_number, "status": status, "created_at": ts, "updated_at": ts})
    return RedirectResponse(url="/players", status_code=303)


@router.get("/players/{player_id}/edit", response_class=HTMLResponse)
async def players_edit(request: Request, player_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    clubs = svc.get_all("CLUB_MASTER")
    collabs = svc.get_all("COLLAB_MASTER")
    players = svc.get_all(SHEET)
    player = next((p for p in players if p["player_id"] == player_id), None)
    if not player:
        raise HTTPException(status_code=404, detail="선수를 찾을 수 없습니다.")
    return templates.TemplateResponse(request, "players/form.html", {"user": user, "player": player, "clubs": clubs, "collabs": collabs, "action": "edit"})


@router.post("/players/{player_id}/edit")
async def players_update(
    request: Request,
    player_id: str,
    club_name: str = Form(...),
    collab_name: str = Form(...),
    player_name: str = Form(...),
    player_number: str = Form(...),
    status: str = Form("활성"),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.update_row(SHEET, "player_id", player_id, {"club_name": club_name, "collab_name": collab_name, "player_name": player_name, "player_number": player_number, "status": status, "updated_at": now_str()})
    return RedirectResponse(url="/players", status_code=303)


@router.post("/players/{player_id}/delete")
async def players_delete(request: Request, player_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.delete_row(SHEET, "player_id", player_id)
    return RedirectResponse(url="/players", status_code=303)


@router.get("/api/players")
async def api_players_list(q: str = "", club_name: str = "", collab_name: str = ""):
    svc = get_sheets_service()
    data = svc.get_all(SHEET)
    if club_name:
        data = [p for p in data if p.get("club_name") == club_name]
    if collab_name:
        data = [p for p in data if p.get("collab_name") == collab_name]
    if q:
        data = [p for p in data if q.lower() in p.get("player_name", "").lower() or q in str(p.get("player_number", ""))]
    return data
