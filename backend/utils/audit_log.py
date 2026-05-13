"""수량 변경 audit 로그 헬퍼.

QTY_AUDIT 시트에 주문/입고/재단의 수량 필드 변경 이력을 기록한다.
before/after 가 동일하면 기록하지 않는다(불필요한 로그 방지).
"""
from backend.utils.helpers import generate_id, now_str

AUDIT_SHEET = "QTY_AUDIT"

# audit 대상 수량 필드 정의 (entity 별)
QTY_FIELDS = {
    "ORDER": ["qty"],
    "ROLL_INBOUND": ["inbound_qty"],
    "CUTTING_PROCESS": ["input_qty", "success_qty", "defect_qty", "loss_qty"],
}


def _to_int(value, default: int = 0) -> int:
    try:
        s = str(value).strip()
        if s == "" or s.lower() == "none":
            return default
        return int(float(s))
    except (TypeError, ValueError):
        return default


def log_change(
    svc,
    *,
    entity: str,
    entity_id: str,
    action: str,
    field: str,
    before,
    after,
    user: str = "",
    related_order_id: str = "",
    memo: str = "",
) -> None:
    """수량 변경 한 건을 기록한다. UPDATE 인데 값이 동일하면 스킵."""
    b = _to_int(before)
    a = _to_int(after)
    if action == "UPDATE" and b == a:
        return
    try:
        svc.append_row(AUDIT_SHEET, {
            "audit_id": generate_id("AUD"),
            "audit_at": now_str(),
            "entity": entity,
            "entity_id": entity_id,
            "action": action,
            "field": field,
            "before": b,
            "after": a,
            "delta": a - b,
            "user": user,
            "related_order_id": related_order_id,
            "memo": memo,
        })
    except Exception as e:
        # 감사 로그 실패가 본 트랜잭션을 막지 않도록 방어적으로 처리
        print(f"[QTY_AUDIT] log_change 실패: {e}")


def log_create(svc, *, entity: str, entity_id: str, data: dict,
               user: str = "", related_order_id: str = "", memo: str = "") -> None:
    """엔티티 생성 시 모든 수량 필드를 0 → 신규값으로 기록한다."""
    for f in QTY_FIELDS.get(entity, []):
        log_change(
            svc, entity=entity, entity_id=entity_id, action="CREATE",
            field=f, before=0, after=data.get(f, 0),
            user=user, related_order_id=related_order_id, memo=memo,
        )


def log_update(svc, *, entity: str, entity_id: str, before_data: dict, after_data: dict,
               user: str = "", related_order_id: str = "", memo: str = "") -> None:
    """엔티티 수정 시 각 수량 필드별 before/after 를 기록한다."""
    for f in QTY_FIELDS.get(entity, []):
        if f not in after_data:
            continue
        log_change(
            svc, entity=entity, entity_id=entity_id, action="UPDATE",
            field=f, before=before_data.get(f, 0), after=after_data.get(f, 0),
            user=user, related_order_id=related_order_id, memo=memo,
        )


def log_delete(svc, *, entity: str, entity_id: str, before_data: dict,
               user: str = "", related_order_id: str = "", memo: str = "") -> None:
    """엔티티 삭제 시 모든 수량 필드를 기존값 → 0 으로 기록한다."""
    for f in QTY_FIELDS.get(entity, []):
        log_change(
            svc, entity=entity, entity_id=entity_id, action="DELETE",
            field=f, before=before_data.get(f, 0), after=0,
            user=user, related_order_id=related_order_id, memo=memo,
        )
