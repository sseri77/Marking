from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, require_auth, paginate

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "CLUB_MASTER"


@router.get("/clubs", response_class=HTMLResponse)
async def clubs_list(request: Request, q: str = "", page: int = 1):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["club_name"]) if q else svc.get_all(SHEET)
    paged = paginate(data, page)
    return templates.TemplateResponse(request, "clubs/index.html", {"user": user, "q": q, **paged})


@router.get("/clubs/new", response_class=HTMLResponse)
async def clubs_new(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "clubs/form.html", {"user": user, "club": None, "action": "create"})


@router.post("/clubs/new")
async def clubs_create(request: Request, club_name: str = Form(...), status: str = Form("활성")):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    ts = now_str()
    svc.append_row(SHEET, {"club_id": generate_id("CLB"), "club_name": club_name, "status": status, "created_at": ts, "updated_at": ts})
    return RedirectResponse(url="/clubs", status_code=303)


@router.get("/clubs/{club_id}/edit", response_class=HTMLResponse)
async def clubs_edit(request: Request, club_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    clubs = svc.get_all(SHEET)
    club = next((c for c in clubs if c["club_id"] == club_id), None)
    if not club:
        raise HTTPException(status_code=404, detail="구단을 찾을 수 없습니다.")
    return templates.TemplateResponse(request, "clubs/form.html", {"user": user, "club": club, "action": "edit"})


@router.post("/clubs/{club_id}/edit")
async def clubs_update(request: Request, club_id: str, club_name: str = Form(...), status: str = Form("활성")):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.update_row(SHEET, "club_id", club_id, {"club_name": club_name, "status": status, "updated_at": now_str()})
    return RedirectResponse(url="/clubs", status_code=303)


@router.post("/clubs/{club_id}/delete")
async def clubs_delete(request: Request, club_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.delete_row(SHEET, "club_id", club_id)
    return RedirectResponse(url="/clubs", status_code=303)


@router.get("/api/clubs")
async def api_clubs_list(q: str = ""):
    svc = get_sheets_service()
    return svc.search(SHEET, q, ["club_name"]) if q else svc.get_all(SHEET)
