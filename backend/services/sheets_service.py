import os
import json
import time
import importlib
from typing import Any, Optional
from datetime import datetime
from backend.config import get_settings

_GSPREAD_AVAILABLE = None

settings = get_settings()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_HEADERS = {
    "CLUB_MASTER": ["club_id", "club_name", "status", "created_at", "updated_at"],
    "COLLAB_MASTER": ["collab_id", "club_id", "collab_name", "status", "created_at", "updated_at"],
    # 인쇄업체 (원단 입고처)
    "PRINTER_MASTER": ["printer_id", "printer_name", "contact", "phone", "memo", "status", "created_at", "updated_at"],
    # 매장 (출고 대상)
    "STORE_MASTER": ["store_id", "store_name", "contact", "phone", "address", "memo", "status", "created_at", "updated_at"],
    # 주문 (= 인쇄업체 발주 데이터). order_type: 선수마킹 / 로고 / 기타 (구버전 데이터는 빈 값 → 선수마킹으로 간주)
    "ORDER": ["order_id", "order_date", "club_name", "collab_name", "order_type", "player_name", "player_number", "qty", "status", "memo", "created_at", "parent_order_id"],
    # 롤 원단 입고
    "ROLL_INBOUND": ["inbound_id", "inbound_date", "day_of_week", "vendor", "roll_no", "order_ids", "order_qty", "inbound_qty", "surplus_reason", "manager", "memo", "status", "created_at"],
    # 선수별 재단
    "CUTTING_PROCESS": ["cutting_id", "inbound_id", "order_id", "club_name", "collab_name", "player_name", "player_number", "input_qty", "success_qty", "defect_qty", "loss_qty", "status", "manager", "memo", "created_at"],
    # 출고
    "STORE_OUTBOUND": ["outbound_id", "cutting_id", "store_name", "club_name", "collab_name", "player_name", "player_number", "qty", "delivery_method", "invoice_no", "shipping_date", "manager", "memo", "created_at"],
    # 수량 변경 이력 로그 (주문/입고/재단의 수량 필드 변경 audit)
    "QTY_AUDIT": ["audit_id", "audit_at", "entity", "entity_id", "action", "field", "before", "after", "delta", "user", "related_order_id", "memo"],
    # 사용자 계정 (관리자 계정 정보 + 권한)
    # permissions: 페이지별 접근 권한을 JSON 문자열로 저장 (예: {"clubs": {"view":true,"write":true,"delete":false}, ...})
    "USER_MASTER": ["user_id", "username", "full_name", "role", "password_hash", "status", "permissions", "memo", "last_login_at", "created_at", "updated_at"],
    # 관리자 공지사항 게시판
    "NOTICE": ["notice_id", "title", "content", "author", "is_pinned", "created_at", "updated_at"],
}

# 시트 스키마가 변경된 후 기존 시트의 헤더/데이터를 신규 스키마로 변환하기 위한 필드명 매핑.
# 키: 신규 시트명, 값: {옛 필드명: 신규 필드명}. 신규 필드명이 None 이면 해당 컬럼은 제거.
SHEET_FIELD_MIGRATIONS = {
    "CUTTING_PROCESS": {
        "process_id": "cutting_id",
        "work_order_no": None,
        "worker": "manager",
    },
}


CACHE_TTL_SECONDS = 30


# USER_MASTER 시트 최초 생성 시 자동으로 시드할 기본 관리자 계정.
# 비밀번호는 SECRET_KEY 기반 해시로 저장되므로 매 실행마다 동일 결과.
DEFAULT_USER_SEED = [
    ("USR_ADMIN_DEFAULT", "admin", "관리자", "SUPER_ADMIN", "admin1234"),
    ("USR_MANAGER_DEFAULT", "manager", "매니저", "MANAGER", "manager1234"),
    ("USR_STAFF_DEFAULT", "staff", "직원", "STAFF", "staff1234"),
]


def _build_default_user_rows() -> list[dict]:
    """기본 시드 사용자 행(dict 리스트) 생성. 비밀번호 해시는 런타임에 계산."""
    from backend.auth.jwt_handler import _hash_pw
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return [
        {
            "user_id": uid,
            "username": uname,
            "full_name": fname,
            "role": role,
            "password_hash": _hash_pw(pw),
            "status": "활성",
            "permissions": "",
            "memo": "초기 시드 계정",
            "last_login_at": "",
            "created_at": ts,
            "updated_at": ts,
        }
        for uid, uname, fname, role, pw in DEFAULT_USER_SEED
    ]


class SheetsService:
    def __init__(self):
        self._client: Optional[gspread.Client] = None
        self._spreadsheet: Optional[gspread.Spreadsheet] = None
        self._demo_mode = False
        self._schema_checked: set[str] = set()
        self._cache: dict[str, tuple[float, list[dict]]] = {}

    def _invalidate_cache(self, sheet_name: str) -> None:
        self._cache.pop(sheet_name, None)

    def _try_import_gspread(self):
        global _GSPREAD_AVAILABLE
        if _GSPREAD_AVAILABLE is not None:
            return _GSPREAD_AVAILABLE
        try:
            globals()["gspread"] = importlib.import_module("gspread")
            crypt_mod = importlib.import_module("google.oauth2.service_account")
            globals()["Credentials"] = crypt_mod.Credentials
            _GSPREAD_AVAILABLE = True
        except BaseException:
            _GSPREAD_AVAILABLE = False
        return _GSPREAD_AVAILABLE

    def _connect(self):
        if self._client:
            return
        if not self._try_import_gspread():
            self._demo_mode = True
            return
        sheet_id = settings.GOOGLE_SHEET_ID
        print(f"[Sheets] GOOGLE_SHEET_ID set: {bool(sheet_id)}")
        if not sheet_id:
            self._demo_mode = True
            return
        try:
            sa_info = None
            if settings.GOOGLE_SERVICE_ACCOUNT_JSON:
                sa_info = json.loads(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
                print("[Sheets] Using GOOGLE_SERVICE_ACCOUNT_JSON env var")
            elif os.environ.get("client_email"):
                # pydantic 파싱 오류 방지를 위해 os.environ에서 직접 읽기
                raw_key = os.environ.get("private_key", "")
                if "\\n" in raw_key:
                    raw_key = raw_key.replace("\\n", "\n")
                if "-----BEGIN" not in raw_key:
                    raw_key = "-----BEGIN RSA PRIVATE KEY-----\n" + raw_key + "\n-----END RSA PRIVATE KEY-----\n"
                sa_info = {
                    "type": str(os.environ.get("type", "service_account")),
                    "project_id": str(os.environ.get("project_id", "")),
                    "private_key_id": str(os.environ.get("private_key_id", "")),
                    "private_key": raw_key,
                    "client_email": str(os.environ.get("client_email", "")),
                    "client_id": str(os.environ.get("client_id", "")),
                    "auth_uri": str(os.environ.get("auth_uri", "https://accounts.google.com/o/oauth2/auth")),
                    "token_uri": str(os.environ.get("token_uri", "https://oauth2.googleapis.com/token")),
                    "auth_provider_x509_cert_url": str(os.environ.get("auth_provider_x509_cert_url", "https://www.googleapis.com/oauth2/v1/certs")),
                    "client_x509_cert_url": str(os.environ.get("client_x509_cert_url", "")),
                    "universe_domain": str(os.environ.get("universe_domain", "googleapis.com")),
                }
                print(f"[Sheets] Using individual env vars, client_email: {os.environ.get('client_email')}")
                print(f"[Sheets] private_key starts with: {raw_key[:40]}")
            else:
                cred_file = settings.GOOGLE_SERVICE_ACCOUNT_FILE
                if not os.path.exists(cred_file):
                    print("[Sheets] No credentials found (JSON env var, individual env vars, or file)")
                    self._demo_mode = True
                    return
                creds = globals()["Credentials"].from_service_account_file(cred_file, scopes=SCOPES)
                print("[Sheets] Using credentials file")
                sa_info = None

            if sa_info:
                creds = globals()["Credentials"].from_service_account_info(sa_info, scopes=SCOPES)
            self._client = globals()["gspread"].authorize(creds)
            self._spreadsheet = self._client.open_by_key(sheet_id)
            print("[Sheets] Connected successfully")
        except Exception as e:
            print(f"[Sheets] Connection failed: {e}")
            self._demo_mode = True

    def _get_sheet(self, sheet_name: str) -> Optional[Any]:
        self._connect()
        if self._demo_mode or not self._spreadsheet:
            return None
        try:
            ws = self._spreadsheet.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(SHEET_HEADERS.get(sheet_name, [])) + 2)
            headers = SHEET_HEADERS.get(sheet_name, [])
            if headers:
                ws.append_row(headers)
            if sheet_name == "USER_MASTER":
                try:
                    rows = [[str(r.get(h, "")) for h in headers] for r in _build_default_user_rows()]
                    ws.append_rows(rows)
                    print(f"[Sheets] USER_MASTER 기본 계정 {len(rows)}개 시드 완료")
                except Exception as e:
                    print(f"[Sheets] USER_MASTER 시드 실패: {e}")
            self._schema_checked.add(sheet_name)
            return ws
        if sheet_name not in self._schema_checked:
            self._ensure_sheet_schema(sheet_name, ws)
            if sheet_name == "USER_MASTER":
                self._seed_user_master_if_empty(ws)
            self._schema_checked.add(sheet_name)
        return ws

    def _seed_user_master_if_empty(self, ws) -> None:
        """USER_MASTER 시트에 데이터 행이 하나도 없으면 기본 계정을 시드한다."""
        try:
            records = ws.get_all_records()
            if records:
                return
            headers = SHEET_HEADERS["USER_MASTER"]
            rows = [[str(r.get(h, "")) for h in headers] for r in _build_default_user_rows()]
            ws.append_rows(rows)
            print(f"[Sheets] USER_MASTER 비어있어 기본 계정 {len(rows)}개 시드 완료")
        except Exception as e:
            print(f"[Sheets] USER_MASTER 자동 시드 실패: {e}")

    def _ensure_sheet_schema(self, sheet_name: str, sheet) -> None:
        """시트의 헤더가 현재 SHEET_HEADERS와 일치하는지 확인하고, 다르면 자동 마이그레이션한다."""
        expected = SHEET_HEADERS.get(sheet_name)
        if not expected:
            return
        try:
            current = sheet.row_values(1)
        except Exception as e:
            print(f"[Sheets] {sheet_name} 헤더 읽기 실패: {e}")
            return
        # 헤더가 이미 정상이면 종료
        if current == expected:
            return
        # 시트가 비어 있으면 헤더만 기록
        if not current or all(not (c or "").strip() for c in current):
            sheet.update("A1", [expected])
            print(f"[Sheets] {sheet_name} 헤더 초기화 완료")
            return
        # 헤더가 다른 경우: 기존 데이터를 옛 헤더 기준으로 읽고 새 스키마로 변환
        print(f"[Sheets] {sheet_name} 스키마 마이그레이션 시작: {current} -> {expected}")
        try:
            records = sheet.get_all_records()
        except Exception as e:
            print(f"[Sheets] {sheet_name} 마이그레이션용 데이터 읽기 실패: {e}")
            return
        field_map = SHEET_FIELD_MIGRATIONS.get(sheet_name, {})
        new_rows = []
        for r in records:
            new_r = {}
            for old_key, val in r.items():
                if old_key in field_map:
                    new_key = field_map[old_key]
                    if new_key is None:
                        continue
                else:
                    new_key = old_key
                new_r[new_key] = val
            new_rows.append([str(new_r.get(h, "")) for h in expected])
        try:
            sheet.clear()
            sheet.update("A1", [expected] + new_rows)
            print(f"[Sheets] {sheet_name} 마이그레이션 완료 ({len(new_rows)}행)")
        except Exception as e:
            print(f"[Sheets] {sheet_name} 마이그레이션 쓰기 실패: {e}")

    def get_all(self, sheet_name: str) -> list[dict]:
        now = time.time()
        cached = self._cache.get(sheet_name)
        if cached and (now - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]
        sheet = self._get_sheet(sheet_name)
        if not sheet:
            return self._get_demo_data(sheet_name)
        records = sheet.get_all_records()
        self._cache[sheet_name] = (now, records)
        return records

    def append_row(self, sheet_name: str, data: dict) -> dict:
        sheet = self._get_sheet(sheet_name)
        if not sheet:
            return data
        headers = SHEET_HEADERS.get(sheet_name, list(data.keys()))
        row = [str(data.get(h, "")) for h in headers]
        sheet.append_row(row)
        self._invalidate_cache(sheet_name)
        return data

    def update_row(self, sheet_name: str, id_field: str, id_value: str, data: dict) -> bool:
        sheet = self._get_sheet(sheet_name)
        if not sheet:
            return True
        records = sheet.get_all_records()
        headers = SHEET_HEADERS.get(sheet_name, [])
        for i, record in enumerate(records):
            if str(record.get(id_field)) == str(id_value):
                row_num = i + 2
                data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                row = [str(data.get(h, record.get(h, ""))) for h in headers]
                sheet.update(f"A{row_num}", [row])
                self._invalidate_cache(sheet_name)
                return True
        return False

    def delete_row(self, sheet_name: str, id_field: str, id_value: str) -> bool:
        sheet = self._get_sheet(sheet_name)
        if not sheet:
            return True
        records = sheet.get_all_records()
        for i, record in enumerate(records):
            if str(record.get(id_field)) == str(id_value):
                sheet.delete_rows(i + 2)
                self._invalidate_cache(sheet_name)
                return True
        return False

    def search(self, sheet_name: str, query: str, fields: list[str]) -> list[dict]:
        records = self.get_all(sheet_name)
        if not query:
            return records
        q = query.lower()
        return [r for r in records if any(q in str(r.get(f, "")).lower() for f in fields)]

    def _get_demo_data(self, sheet_name: str) -> list[dict]:
        demo = {
            "CLUB_MASTER": [
                {"club_id": "CLB001", "club_name": "FC서울", "status": "활성", "created_at": "2024-01-01", "updated_at": "2024-01-01"},
                {"club_id": "CLB002", "club_name": "전북현대", "status": "활성", "created_at": "2024-01-01", "updated_at": "2024-01-01"},
                {"club_id": "CLB003", "club_name": "울산HD", "status": "활성", "created_at": "2024-01-01", "updated_at": "2024-01-01"},
            ],
            "COLLAB_MASTER": [
                {"collab_id": "COL001", "club_id": "CLB001", "collab_name": "2024 홈킷", "status": "활성", "created_at": "2024-01-01", "updated_at": "2024-01-01"},
                {"collab_id": "COL002", "club_id": "CLB002", "collab_name": "2024 어웨이킷", "status": "활성", "created_at": "2024-01-01", "updated_at": "2024-01-01"},
            ],
            "PRINTER_MASTER": [
                {"printer_id": "PRT001", "printer_name": "한울인쇄", "contact": "김대리", "phone": "02-1234-5678", "memo": "주거래 인쇄업체", "status": "활성", "created_at": "2024-01-01", "updated_at": "2024-01-01"},
                {"printer_id": "PRT002", "printer_name": "서울프린팅", "contact": "이과장", "phone": "02-9876-5432", "memo": "", "status": "활성", "created_at": "2024-01-01", "updated_at": "2024-01-01"},
            ],
            "STORE_MASTER": [
                {"store_id": "STR001", "store_name": "강남점", "contact": "박매니저", "phone": "02-555-1111", "address": "서울 강남구", "memo": "", "status": "활성", "created_at": "2024-01-01", "updated_at": "2024-01-01"},
                {"store_id": "STR002", "store_name": "홍대점", "contact": "최매니저", "phone": "02-555-2222", "address": "서울 마포구", "memo": "", "status": "활성", "created_at": "2024-01-01", "updated_at": "2024-01-01"},
            ],
            "VENDOR_MASTER": [
                {"vendor_id": "VND001", "vendor_name": "한국원단", "contact": "김대리", "phone": "02-1234-5678", "email": "korea@fabric.com", "status": "활성", "created_at": "2024-01-01", "updated_at": "2024-01-01"},
                {"vendor_id": "VND002", "vendor_name": "서울텍스", "contact": "이과장", "phone": "02-9876-5432", "email": "seoul@tex.com", "status": "활성", "created_at": "2024-01-01", "updated_at": "2024-01-01"},
            ],
            "MATERIAL_INBOUND": [
                {"inbound_id": "INB001", "date": "2024-05-01", "vendor": "한국원단", "material_name": "폴리에스터", "spec": "150cm/white", "lot_no": "LOT-240501", "qty": "500", "unit": "m", "manager": "김철수", "memo": "", "created_at": "2024-05-01"},
                {"inbound_id": "INB002", "date": "2024-05-03", "vendor": "서울텍스", "material_name": "나일론", "spec": "140cm/black", "lot_no": "LOT-240503", "qty": "300", "unit": "m", "manager": "이영희", "memo": "긴급발주", "created_at": "2024-05-03"},
            ],
            "CUTTING_PROCESS": [
                {"cutting_id": "CUT001", "inbound_id": "", "order_id": "", "club_name": "FC서울", "collab_name": "2024 홈킷", "player_name": "황의조", "player_number": "9", "input_qty": "100", "success_qty": "95", "defect_qty": "3", "loss_qty": "2", "status": "완료", "manager": "박작업", "memo": "", "created_at": "2024-05-01"},
                {"cutting_id": "CUT002", "inbound_id": "", "order_id": "", "club_name": "전북현대", "collab_name": "2024 어웨이킷", "player_name": "이동국", "player_number": "20", "input_qty": "80", "success_qty": "78", "defect_qty": "1", "loss_qty": "1", "status": "진행중", "manager": "최작업", "memo": "", "created_at": "2024-05-03"},
            ],
            "STORE_OUTBOUND": [
                {"outbound_id": "OUT001", "cutting_id": "CUT001", "store_name": "강남점", "club_name": "FC서울", "collab_name": "2024 홈킷", "player_name": "황의조", "player_number": "9", "qty": "30", "delivery_method": "택배", "invoice_no": "INV-240502", "shipping_date": "2024-05-02", "manager": "김물류", "memo": "", "created_at": "2024-05-02"},
                {"outbound_id": "OUT002", "cutting_id": "", "store_name": "홍대점", "club_name": "FC서울", "collab_name": "2024 홈킷", "player_name": "기성용", "player_number": "6", "qty": "20", "delivery_method": "퀵", "invoice_no": "", "shipping_date": "2024-05-04", "manager": "박물류", "memo": "퀵 발송", "created_at": "2024-05-04"},
            ],
            "USER_MASTER": [],
            "NOTICE": [
                {"notice_id": "NTC001", "title": "시스템 사용 안내", "content": "마킹키트 관리시스템에 오신 것을 환영합니다. 사용 중 문의사항은 관리자에게 연락 바랍니다.", "author": "admin", "is_pinned": "Y", "created_at": "2024-05-01 09:00:00", "updated_at": "2024-05-01 09:00:00"},
                {"notice_id": "NTC002", "title": "주간 정기 점검 안내", "content": "매주 일요일 02:00~04:00 정기 점검이 진행됩니다. 해당 시간에는 시스템 이용이 제한될 수 있습니다.", "author": "admin", "is_pinned": "N", "created_at": "2024-05-05 10:00:00", "updated_at": "2024-05-05 10:00:00"},
            ],
            "INVENTORY_STATUS": [
                {"inventory_id": "INV001", "category": "원재료", "item_name": "폴리에스터", "spec": "150cm/white", "current_qty": "450", "safe_qty": "100", "unit": "m", "updated_at": "2024-05-01"},
                {"inventory_id": "INV002", "category": "원재료", "item_name": "나일론", "spec": "140cm/black", "current_qty": "300", "safe_qty": "50", "unit": "m", "updated_at": "2024-05-03"},
                {"inventory_id": "INV003", "category": "가공품", "item_name": "FC서울 홈킷-황의조#9", "spec": "완제품", "current_qty": "65", "safe_qty": "20", "unit": "개", "updated_at": "2024-05-02"},
            ],
        }
        if sheet_name == "USER_MASTER":
            return _build_default_user_rows()
        return demo.get(sheet_name, [])


_sheets_service: Optional[SheetsService] = None


def get_sheets_service() -> SheetsService:
    global _sheets_service
    if _sheets_service is None:
        _sheets_service = SheetsService()
    return _sheets_service
