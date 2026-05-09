import os
import json
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
    "PLAYER_MASTER": ["player_id", "club_name", "collab_name", "player_name", "player_number", "status", "created_at", "updated_at"],
    # 주문 (= 인쇄업체 발주 데이터)
    "ORDER": ["order_id", "order_date", "club_name", "collab_name", "player_name", "player_number", "qty", "status", "memo", "created_at"],
    # 롤 원단 입고
    "ROLL_INBOUND": ["inbound_id", "inbound_date", "vendor", "roll_no", "order_ids", "manager", "memo", "status", "created_at"],
    # 선수별 재단
    "CUTTING_PROCESS": ["cutting_id", "inbound_id", "order_id", "club_name", "collab_name", "player_name", "player_number", "input_qty", "success_qty", "defect_qty", "loss_qty", "status", "worker", "memo", "created_at"],
    # 출고
    "STORE_OUTBOUND": ["outbound_id", "cutting_id", "store_name", "club_name", "collab_name", "player_name", "player_number", "qty", "invoice_no", "shipping_date", "manager", "memo", "created_at"],
}


class SheetsService:
    def __init__(self):
        self._client: Optional[gspread.Client] = None
        self._spreadsheet: Optional[gspread.Spreadsheet] = None
        self._demo_mode = False

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
            return self._spreadsheet.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(SHEET_HEADERS.get(sheet_name, [])) + 2)
            headers = SHEET_HEADERS.get(sheet_name, [])
            if headers:
                ws.append_row(headers)
            return ws

    def get_all(self, sheet_name: str) -> list[dict]:
        sheet = self._get_sheet(sheet_name)
        if not sheet:
            return self._get_demo_data(sheet_name)
        records = sheet.get_all_records()
        return records

    def append_row(self, sheet_name: str, data: dict) -> dict:
        sheet = self._get_sheet(sheet_name)
        if not sheet:
            return data
        headers = SHEET_HEADERS.get(sheet_name, list(data.keys()))
        row = [str(data.get(h, "")) for h in headers]
        sheet.append_row(row)
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
            "PLAYER_MASTER": [
                {"player_id": "PLY001", "club_name": "FC서울", "collab_name": "2024 홈킷", "player_name": "황의조", "player_number": "9", "status": "활성", "created_at": "2024-01-01", "updated_at": "2024-01-01"},
                {"player_id": "PLY002", "club_name": "FC서울", "collab_name": "2024 홈킷", "player_name": "기성용", "player_number": "6", "status": "활성", "created_at": "2024-01-01", "updated_at": "2024-01-01"},
                {"player_id": "PLY003", "club_name": "전북현대", "collab_name": "2024 어웨이킷", "player_name": "이동국", "player_number": "20", "status": "비활성", "created_at": "2024-01-01", "updated_at": "2024-01-01"},
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
                {"process_id": "CUT001", "work_order_no": "WO-240501", "club_name": "FC서울", "collab_name": "2024 홈킷", "player_name": "황의조", "player_number": "9", "input_qty": "100", "success_qty": "95", "defect_qty": "3", "loss_qty": "2", "status": "완료", "worker": "박작업", "memo": "", "created_at": "2024-05-01"},
                {"process_id": "CUT002", "work_order_no": "WO-240503", "club_name": "전북현대", "collab_name": "2024 어웨이킷", "player_name": "이동국", "player_number": "20", "input_qty": "80", "success_qty": "78", "defect_qty": "1", "loss_qty": "1", "status": "진행중", "worker": "최작업", "memo": "", "created_at": "2024-05-03"},
            ],
            "STORE_OUTBOUND": [
                {"outbound_id": "OUT001", "store_name": "강남점", "club_name": "FC서울", "collab_name": "2024 홈킷", "player_name": "황의조", "player_number": "9", "qty": "30", "invoice_no": "INV-240502", "shipping_date": "2024-05-02", "manager": "김물류", "memo": "", "created_at": "2024-05-02"},
                {"outbound_id": "OUT002", "store_name": "홍대점", "club_name": "FC서울", "collab_name": "2024 홈킷", "player_name": "기성용", "player_number": "6", "qty": "20", "invoice_no": "INV-240504", "shipping_date": "2024-05-04", "manager": "박물류", "memo": "", "created_at": "2024-05-04"},
            ],
            "INVENTORY_STATUS": [
                {"inventory_id": "INV001", "category": "원재료", "item_name": "폴리에스터", "spec": "150cm/white", "current_qty": "450", "safe_qty": "100", "unit": "m", "updated_at": "2024-05-01"},
                {"inventory_id": "INV002", "category": "원재료", "item_name": "나일론", "spec": "140cm/black", "current_qty": "300", "safe_qty": "50", "unit": "m", "updated_at": "2024-05-03"},
                {"inventory_id": "INV003", "category": "가공품", "item_name": "FC서울 홈킷-황의조#9", "spec": "완제품", "current_qty": "65", "safe_qty": "20", "unit": "개", "updated_at": "2024-05-02"},
            ],
        }
        return demo.get(sheet_name, [])


_sheets_service: Optional[SheetsService] = None


def get_sheets_service() -> SheetsService:
    global _sheets_service
    if _sheets_service is None:
        _sheets_service = SheetsService()
    return _sheets_service
