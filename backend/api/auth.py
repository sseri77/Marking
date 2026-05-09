from fastapi import APIRouter, Request, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.auth.jwt_handler import authenticate_user, create_access_token

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(response: Response, username: str = Form(...), password: str = Form(...)):
    user = authenticate_user(username, password)
    if not user:
        return RedirectResponse(url="/login?error=1", status_code=303)
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(key="access_token", value=token, httponly=True, max_age=28800)
    return resp


@router.post("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie("access_token")
    return resp


@router.get("/logout")
async def logout_get():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie("access_token")
    return resp


@router.post("/api/auth/login")
async def api_login(username: str = Form(...), password: str = Form(...)):
    from fastapi import HTTPException
    user = authenticate_user(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    return {"access_token": token, "token_type": "bearer", "user": {"username": user["username"], "full_name": user["full_name"], "role": user["role"]}}
