from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, today_str, require_auth, paginate

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")
SHEET = "STORE_OUTBOUND"


def _build_cutting_options(svc, *, completed_only: bool = False, keep_cutting_id: str = "") -> list[dict]:
    """출고 폼에서 선택 가능한 재단 목록. 잔여 수량(success_qty - 누적 출고)을 함께 계산.

    completed_only=True 인 경우 '완료' 상태이면서 잔여 수량 > 0 인 재단만 반환.
    keep_cutting_id 로 지정된 재단은 필터를 통과하지 못해도 포함 (수정 시 기존 선택값 유지용).
    """
    cuttings = svc.get_all("CUTTING_PROCESS")
    outbounds = svc.get_all(SHEET)
    outbound_totals: dict[str, int] = {}
    for o in outbounds:
        cid = (o.get("cutting_id") or "").strip()
        if not cid:
            continue
        try:
            outbound_totals[cid] = outbound_totals.get(cid, 0) + int(o.get("qty", 0) or 0)
        except (TypeError, ValueError):
            pass
    options = []
    for c in cuttings:
        cid = c.get("cutting_id")
        if not cid:
            continue
        try:
            success = int(c.get("success_qty", 0) or 0)
        except (TypeError, ValueError):
            success = 0
        used = outbound_totals.get(cid, 0)
        remaining = max(0, success - used)
        status = c.get("status", "")
        if completed_only and cid != keep_cutting_id:
            if status != "완료" or remaining <= 0:
                continue
        options.append({
            "cutting_id": cid,
            "club_name": c.get("club_name", ""),
            "collab_name": c.get("collab_name", ""),
            "player_name": c.get("player_name", ""),
            "player_number": c.get("player_number", ""),
            "success_qty": success,
            "outbound_qty": used,
            "remaining": remaining,
            "status": status,
            "created_at": c.get("created_at", ""),
        })
    options.sort(key=lambda x: x["created_at"], reverse=True)
    return options


@router.get("/outbound", response_class=HTMLResponse)
async def outbound_list(request: Request, q: str = "", page: int = 1):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    data = svc.search(SHEET, q, ["store_name", "club_name", "player_name", "invoice_no", "delivery_method"]) if q else svc.get_all(SHEET)
    data = sorted(data, key=lambda x: x.get("shipping_date", ""), reverse=True)
    paged = paginate(data, page)
    return templates.TemplateResponse(request, "outbound/index.html", {"user": user, "q": q, **paged})


@router.get("/outbound/new", response_class=HTMLResponse)
async def outbound_new(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    cuttings = _build_cutting_options(svc, completed_only=True)
    stores = [s for s in svc.get_all("STORE_MASTER") if s.get("status", "활성") == "활성"]
    return templates.TemplateResponse(request, "outbound/form.html", {
        "user": user, "item": None,
        "cuttings": cuttings, "stores": stores,
        "today": today_str(), "action": "create",
        "auto_manager": user["username"],
    })


DELIVERY_METHODS = {"택배", "퀵", "기타"}


@router.post("/outbound/new")
async def outbound_create(request: Request):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    cutting_ids = [c for c in form.getlist("cutting_ids") if c]
    qtys_raw = form.getlist("qtys")
    store_name = (form.get("store_name") or "").strip()
    delivery_method = form.get("delivery_method") or "택배"
    invoice_no = form.get("invoice_no") or ""
    shipping_date = (form.get("shipping_date") or "").strip()
    manager = (form.get("manager") or "").strip()
    memo = form.get("memo") or ""

    svc = get_sheets_service()

    def render_error(msg: str, status: int = 400):
        cuttings = _build_cutting_options(svc, completed_only=True)
        stores = [s for s in svc.get_all("STORE_MASTER") if s.get("status", "활성") == "활성"]
        return templates.TemplateResponse(request, "outbound/form.html", {
            "user": user, "item": None,
            "cuttings": cuttings, "stores": stores,
            "today": today_str(), "action": "create",
            "auto_manager": manager or user["username"],
            "error": msg,
        }, status_code=status)

    if not store_name or not shipping_date or not manager:
        return render_error("매장명·출고일·담당자를 모두 입력해주세요.")
    if not cutting_ids:
        return render_error("재단을 1개 이상 선택해주세요.")
    if len(cutting_ids) != len(qtys_raw):
        return render_error("선택한 재단과 수량 정보가 일치하지 않습니다. 다시 시도해주세요.")
    if delivery_method not in DELIVERY_METHODS:
        delivery_method = "택배"

    cuttings_by_id = {c.get("cutting_id"): c for c in svc.get_all("CUTTING_PROCESS")}
    options_by_id = {o["cutting_id"]: o for o in _build_cutting_options(svc, completed_only=True)}

    rows_to_add = []
    for cid, qraw in zip(cutting_ids, qtys_raw):
        try:
            qv = int(qraw)
        except (TypeError, ValueError):
            return render_error("수량은 숫자로 입력해주세요.")
        if qv <= 0:
            return render_error("수량은 1 이상이어야 합니다.")
        cutting = cuttings_by_id.get(cid)
        if not cutting or cutting.get("status") != "완료":
            return render_error("선택한 재단 중 완료 상태가 아닌 항목이 있습니다.")
        opt = options_by_id.get(cid)
        if opt and qv > opt["remaining"]:
            return render_error(
                f"'{cutting.get('player_name', '')} #{cutting.get('player_number', '')}' 재단의 출고 수량이 잔여 {opt['remaining']}장을 초과합니다."
            )
        rows_to_add.append({
            "cutting_id": cid,
            "qty": qv,
            "cutting": cutting,
        })

    created_at = now_str()
    for r in rows_to_add:
        cutting = r["cutting"]
        svc.append_row(SHEET, {
            "outbound_id": generate_id("OUT"),
            "cutting_id": r["cutting_id"],
            "store_name": store_name,
            "club_name": cutting.get("club_name", ""),
            "collab_name": cutting.get("collab_name", ""),
            "player_name": cutting.get("player_name", ""),
            "player_number": cutting.get("player_number", ""),
            "qty": r["qty"],
            "delivery_method": delivery_method,
            "invoice_no": invoice_no,
            "shipping_date": shipping_date,
            "manager": manager,
            "memo": memo,
            "created_at": created_at,
        })
    return RedirectResponse(url="/outbound", status_code=303)


@router.get("/outbound/{outbound_id}/edit", response_class=HTMLResponse)
async def outbound_edit(request: Request, outbound_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    items = svc.get_all(SHEET)
    item = next((i for i in items if i["outbound_id"] == outbound_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="출고 내역을 찾을 수 없습니다.")
    cuttings = _build_cutting_options(svc, completed_only=True, keep_cutting_id=item.get("cutting_id", ""))
    stores = svc.get_all("STORE_MASTER")
    return templates.TemplateResponse(request, "outbound/form.html", {
        "user": user, "item": item,
        "cuttings": cuttings, "stores": stores,
        "today": today_str(), "action": "edit",
        "auto_manager": item.get("manager", user["username"]),
    })


@router.post("/outbound/{outbound_id}/edit")
async def outbound_update(
    request: Request,
    outbound_id: str,
    cutting_id: str = Form(""),
    store_name: str = Form(...),
    qty: int = Form(...),
    delivery_method: str = Form("택배"),
    invoice_no: str = Form(""),
    shipping_date: str = Form(...),
    manager: str = Form(...),
    memo: str = Form(""),
):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    if delivery_method not in DELIVERY_METHODS:
        delivery_method = "택배"
    update_data = {
        "store_name": store_name, "qty": qty,
        "delivery_method": delivery_method,
        "invoice_no": invoice_no, "shipping_date": shipping_date,
        "manager": manager, "memo": memo,
    }
    if cutting_id:
        cutting = next((c for c in svc.get_all("CUTTING_PROCESS") if c.get("cutting_id") == cutting_id), None)
        if cutting:
            update_data.update({
                "cutting_id": cutting_id,
                "club_name": cutting.get("club_name", ""),
                "collab_name": cutting.get("collab_name", ""),
                "player_name": cutting.get("player_name", ""),
                "player_number": cutting.get("player_number", ""),
            })
    svc.update_row(SHEET, "outbound_id", outbound_id, update_data)
    return RedirectResponse(url="/outbound", status_code=303)


@router.post("/outbound/{outbound_id}/delete")
async def outbound_delete(request: Request, outbound_id: str):
    user = require_auth(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    svc = get_sheets_service()
    svc.delete_row(SHEET, "outbound_id", outbound_id)
    return RedirectResponse(url="/outbound", status_code=303)


@router.get("/api/outbound")
async def api_outbound_list(q: str = ""):
    svc = get_sheets_service()
    return svc.search(SHEET, q, ["store_name", "club_name", "player_name", "invoice_no", "delivery_method"]) if q else svc.get_all(SHEET)
