from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, require_auth, paginate

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "COLLAB_MASTER"


@router.get("/collabs", response_class=HTMLResponse)
async def collabs_list(request: Request, q: str = "", page: int = 1):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    clubs = svc.get_all("CLUB_MASTER")
    data = svc.search(SHEET, q, ["collab_name", "club_id"]) if q else svc.get_all(SHEET)
    paged = paginate(data, page)
    return templates.TemplateResponse("collabs/index.html", {"request": request, "user": user, "q": q, "clubs": clubs, **paged})


@router.get("/collabs/new", response_class=HTMLResponse)
async def collabs_new(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    clubs = svc.get_all("CLUB_MASTER")
    return templates.TemplateResponse("collabs/form.html", {"request": request, "user": user, "collab": None, "clubs": clubs, "action": "create"})


@router.post("/collabs/new")
async def collabs_create(request: Request, club_id: str = Form(...), collab_name: str = Form(...), status: str = Form("활성")):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    ts = now_str()
    svc.append_row(SHEET, {"collab_id": generate_id("COL"), "club_id": club_id, "collab_name": collab_name, "status": status, "created_at": ts, "updated_at": ts})
    return RedirectResponse(url="/collabs", status_code=303)


@router.get("/collabs/{collab_id}/edit", response_class=HTMLResponse)
async def collabs_edit(request: Request, collab_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    clubs = svc.get_all("CLUB_MASTER")
    collabs = svc.get_all(SHEET)
    collab = next((c for c in collabs if c["collab_id"] == collab_id), None)
    if not collab:
        raise HTTPException(status_code=404, detail="콜라보를 찾을 수 없습니다.")
    return templates.TemplateResponse("collabs/form.html", {"request": request, "user": user, "collab": collab, "clubs": clubs, "action": "edit"})


@router.post("/collabs/{collab_id}/edit")
async def collabs_update(request: Request, collab_id: str, club_id: str = Form(...), collab_name: str = Form(...), status: str = Form("활성")):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.update_row(SHEET, "collab_id", collab_id, {"club_id": club_id, "collab_name": collab_name, "status": status, "updated_at": now_str()})
    return RedirectResponse(url="/collabs", status_code=303)


@router.post("/collabs/{collab_id}/delete")
async def collabs_delete(request: Request, collab_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.delete_row(SHEET, "collab_id", collab_id)
    return RedirectResponse(url="/collabs", status_code=303)


@router.get("/api/collabs")
async def api_collabs_list(q: str = "", club_id: str = ""):
    svc = get_sheets_service()
    data = svc.get_all(SHEET)
    if club_id:
        data = [c for c in data if c.get("club_id") == club_id]
    if q:
        data = [c for c in data if q.lower() in c.get("collab_name", "").lower()]
    return data
