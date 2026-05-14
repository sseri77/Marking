"""LG / 먼작귀(서울 Ver) 콜라보 및 주문 일괄 등록 스크립트.

실행 방법 (프로젝트 루트에서):
    python -m scripts.seed_lg_munjakgwi

동작 순서:
1. CLUB_MASTER 에서 'LG' 구단을 찾는다. 없으면 종료한다.
2. COLLAB_MASTER 에 '먼작귀(서울 Ver)' 콜라보가 LG 구단으로 이미 등록돼 있는지 확인.
   - 없으면 새로 등록한다.
3. ORDER 시트에 아래 선수별 주문 38건을 일괄 append 한다.
   - 동일 (club_name, collab_name, player_number) 의 주문이 이미 존재하면 스킵한다(중복 방지).

수량/이름/번호는 사용자 요청 그대로 사용한다.
"""
from __future__ import annotations

from backend.services.sheets_service import get_sheets_service
from backend.utils.helpers import generate_id, now_str, today_str

CLUB_NAME = "LG"
COLLAB_NAME = "먼작귀(서울 Ver)"

# (번호, 이름, 수량)
ORDERS: list[tuple[str, str, int]] = [
    ("1", "임찬규", 100),
    ("2", "문보경", 150),
    ("3", "최원영", 5),
    ("4", "신민재", 15),
    ("6", "구본혁", 50),
    ("7", "이영빈", 5),
    ("8", "문성주", 15),
    ("10", "오지환", 30),
    ("11", "함덕주", 5),
    ("13", "송승기", 30),
    ("16", "최지명", 5),
    ("17", "박해민", 200),
    ("18", "정우영", 5),
    ("20", "우강훈", 30),
    ("23", "오스틴", 50),
    ("26", "이민호", 5),
    ("27", "박동원", 30),
    ("29", "손주영", 15),
    ("30", "톨허스트", 5),
    ("31", "이정용", 5),
    ("32", "이지강", 5),
    ("37", "김강률", 5),
    ("42", "김진성", 5),
    ("45", "김진수", 5),
    ("46", "치리노스", 5),
    ("47", "김윤식", 15),
    ("50", "장현식", 5),
    ("51", "홍창기", 150),
    ("52", "이재원", 150),
    ("53", "천성호", 15),
    ("54", "유영찬", 15),
    ("55", "송찬의", 150),
    ("56", "문정빈", 5),
    ("61", "백승현", 5),
    ("63", "이주헌", 30),
    ("67", "김영우", 15),
    ("68", "웰스", 5),
    ("85", "염경엽", 5),
]


def ensure_collab(svc) -> str:
    """LG 구단의 먼작귀(서울 Ver) 콜라보를 보장하고 collab_id 를 반환."""
    clubs = svc.get_all("CLUB_MASTER")
    lg = next((c for c in clubs if c.get("club_name") == CLUB_NAME), None)
    if not lg:
        raise SystemExit(
            f"[ERR] CLUB_MASTER 에 '{CLUB_NAME}' 구단이 없습니다. 먼저 구단을 등록하세요."
        )
    club_id = lg.get("club_id", "")

    collabs = svc.get_all("COLLAB_MASTER")
    existing = next(
        (
            c
            for c in collabs
            if c.get("club_id") == club_id and c.get("collab_name") == COLLAB_NAME
        ),
        None,
    )
    if existing:
        print(f"[OK] 콜라보 이미 존재: {existing.get('collab_id')} / {COLLAB_NAME}")
        return existing.get("collab_id", "")

    ts = now_str()
    new_id = generate_id("COL")
    svc.append_row(
        "COLLAB_MASTER",
        {
            "collab_id": new_id,
            "club_id": club_id,
            "collab_name": COLLAB_NAME,
            "status": "활성",
            "created_at": ts,
            "updated_at": ts,
        },
    )
    print(f"[NEW] 콜라보 등록 완료: {new_id} / {CLUB_NAME} / {COLLAB_NAME}")
    return new_id


def seed_orders(svc) -> None:
    order_date = today_str()
    existing_orders = svc.get_all("ORDER")
    existing_keys = {
        (
            str(o.get("club_name", "")),
            str(o.get("collab_name", "")),
            str(o.get("player_number", "")),
        )
        for o in existing_orders
    }

    created, skipped = 0, 0
    for number, name, qty in ORDERS:
        key = (CLUB_NAME, COLLAB_NAME, number)
        if key in existing_keys:
            print(f"[SKIP] 동일 주문 존재: #{number} {name}")
            skipped += 1
            continue
        svc.append_row(
            "ORDER",
            {
                "order_id": generate_id("ORD"),
                "order_date": order_date,
                "club_name": CLUB_NAME,
                "collab_name": COLLAB_NAME,
                "player_name": name,
                "player_number": number,
                "qty": qty,
                "status": "주문완료",
                "memo": "",
                "created_at": now_str(),
            },
        )
        created += 1
        print(f"[NEW] 주문 등록: #{number} {name} x {qty}")

    print(f"\n주문 등록 완료: 신규 {created}건 / 스킵 {skipped}건 / 합계 {len(ORDERS)}건")


def main() -> None:
    svc = get_sheets_service()
    ensure_collab(svc)
    seed_orders(svc)


if __name__ == "__main__":
    main()
