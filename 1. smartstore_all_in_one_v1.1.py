#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
smartstore_all_in_one.py  (consolidated) - v1.1 개선판
- 전역 작업(stores!A1): "등록갯수" | "배송코드" | "배송변경" | "상품삭제" | "혜택설정"
- A열 TRUE 인 계정만 처리(A2~)
- 병렬 실행: .env → PARALLEL_STORES=true / PARALLEL_WORKERS=4
- 상품삭제:
  * '삭제금지상품' 탭의 판매자상품코드로 예외 필터
  * 한 줄 진행표(보드)로 스토어별 진행률 표시 (병렬에서도 라인 안 섞임)
  * 예외처리된 판매자코드 목록을 CLI 리포트로 출력
  * Ctrl+C 로 안전 중단 지원(전체 스레드 즉시 중지 신호 전달)
- delete_exceptions_sync.py 가 있으면 호출하여 '삭제금지상품' 최신화
  (B1의 마지막 주문일자를 기준으로 해당 월만 스캔)

[v1.1 개선사항]
- 열 범위 계산 버그 수정 (26열 초과 지원)
- Thread Safety 개선 (Lock 적용)
- Bare except 제거 (구체적 예외 처리)
- HTTP 세션 재사용 (성능 개선)
- 페이지 번호 통일 (page=1 시작)
- 예외 로깅 개선
"""

from __future__ import annotations

import os
import sys
import time
import json
import base64
import math
import re
import signal
import threading
from typing import Any, Dict, List, Optional, Tuple, Set, Callable

from datetime import datetime, timedelta

import requests
import bcrypt
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

from concurrent.futures import ThreadPoolExecutor, as_completed

# ====== 외부 동기화 모듈(없으면 무시) ======
try:
    from delete_exceptions_sync import sync_delete_exceptions
except ImportError:
    sync_delete_exceptions = None


# ================= 상수/엔드포인트 =================
API_HOST = "https://api.commerce.naver.com"
TOKEN_URL = f"{API_HOST}/external/v1/oauth2/token"
SEARCH_URL = f"{API_HOST}/external/v1/products/search"
ORIGIN_DELETE_URL_V2 = f"{API_HOST}/external/v2/products/origin-products"
BULK_UPDATE_URL = f"{API_HOST}/external/v1/products/origin-products/bulk-update"

# 주소록(배송코드) 최신 엔드포인트
ADDR_PAGED = f"{API_HOST}/external/v1/seller/addressbooks-for-page"
ADDR_LIST = f"{API_HOST}/external/v1/seller/addressbooks"

REQUEST_TIMEOUT = 40
DEFAULT_BATCH_SIZE = 1000

STORES_SHEET = "stores"
RESULTS_SHEET = "results"
PRODUCT_COUNT_SHEET = "등록갯수"
DELIVERY_CODE_SHEET = "배송코드"

GLOBAL_TASK_OPTIONS = ["등록갯수", "배송코드", "배송변경", "상품삭제", "혜택설정", "중복삭제"]

# ================= 설정 상수 =================
class Config:
    BENEFIT_CHUNK_SIZE = 50
    SEARCH_PAGE_SIZE_SMALL = 100
    SEARCH_PAGE_SIZE_LARGE = 200
    MAX_RETRIES = 5
    INITIAL_BACKOFF = 1.0
    MAX_BACKOFF = 8.0


# =================== 전역 캐시 (Thread-Safe) ====================
_cache_lock = threading.Lock()
_sync_lock = threading.Lock()

# 상품삭제 시트 캐시 (중복삭제 G열 기록용)
DELETE_SHEET_CACHE: Dict[str, Any] = {
    "headers": None,
    "values": None,
}

# 삭제금지상품 캐시 (상품삭제/중복삭제 공용)
DELETE_EXCEPTIONS_CACHE: Dict[str, Any] = {
    "loaded": False,
    "codes": set(),
}
DELETE_EXCEPTIONS_SYNCED = False
# =================================================

# ================= HTTP 세션 (연결 재사용) =================
HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({
    "Accept": "application/json",
    "Content-Type": "application/json"
})


# ================= 공용 유틸 =================
def log(msg: str):
    print(msg)
    sys.stdout.flush()


def plog(msg: str):
    log(msg)


def S(v: Any) -> str:
    try:
        return "" if v is None else str(v).strip()
    except (TypeError, ValueError):
        return ""


def N(v: Any) -> Optional[int]:
    s = S(v)
    if s == "":
        return None
    for tok in ("₩", "원", ",", " ", "\u00A0"):
        s = s.replace(tok, "")
    try:
        return int(round(float(s)))
    except (ValueError, TypeError):
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return int(round(float(m.group(0)))) if m else None


def B(v: Any) -> bool:
    return S(v).lower() in ("true", "1", "y", "yes", "t", "on")


def now_kr() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_number_list(text: Any) -> List[int]:
    if not text:
        return []
    parts = [p.strip() for p in str(text).replace("\n", ",").replace("\t", ",").split(",") if p.strip()]
    out: List[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except (ValueError, TypeError):
            pass
    return out


def safe_name(name: str) -> str:
    name = S(name)
    name = re.sub(r"[^\w\-.가-힣 ]+", "_", name)
    return name or "store"


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def save_json(path: str, data: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def col_letter(n: int) -> str:
    """
    1-based 열 번호를 Excel 스타일 열 문자로 변환
    예: 1 -> A, 26 -> Z, 27 -> AA, 28 -> AB, ...
    """
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _extract_created_ts(item: Dict[str, Any]) -> float:
    """상품 아이템에서 등록일시 타임스탬프 추출"""
    try:
        prod = item.get("product") or item
        cps = prod.get("channelProducts") or item.get("channelProducts") or []
        cand = None
        if cps and isinstance(cps[0], dict):
            cand = (
                cps[0].get("regDate") or
                cps[0].get("createdDate") or
                cps[0].get("createDate")
            )
        if not cand:
            cand = (
                prod.get("regDate") or
                prod.get("createdDate") or
                prod.get("createDate")
            )
        if not cand:
            return datetime.max.timestamp()

        s = str(cand).strip().replace(" ", "")
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt.timestamp()
    except (ValueError, TypeError, AttributeError, KeyError):
        return datetime.max.timestamp()


# ================= Ctrl+C 안전 중단 =================
STOP_EVENT = threading.Event()


def sleep_with_stop(total_sec: float, step: float = 0.1) -> bool:
    remain = float(total_sec)
    while remain > 0:
        if STOP_EVENT.is_set():
            return False
        t = step if remain > step else remain
        time.sleep(t)
        remain -= t
    return not STOP_EVENT.is_set()


def _install_sigint_handler():
    def _handler(signum, frame):
        if not STOP_EVENT.is_set():
            plog("\n[CTRL+C] 중단 요청 감지 → 작업 정리 중…")
            STOP_EVENT.set()
    try:
        signal.signal(signal.SIGINT, _handler)
    except (ValueError, OSError):
        pass


# ================= 진행 보드(병렬 시 라인 섞임 방지) =================
class ProgressBoard:
    def __init__(self, refresh_sec: float = None):
        env = os.getenv("PROGRESS_REFRESH_SEC")
        self.refresh_sec = float(env) if env else (refresh_sec if refresh_sec else 0.25)
        self.mode = (os.getenv("PROGRESS_MODE") or "board").lower()  # board|off
        self._lock = threading.Lock()
        self._rows: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []  # 고정 라인 순서
        self._last_render = 0.0
        self._printed_lines = 0
        self._last_snapshot = ""

        self._ansi_ok = sys.stdout.isatty() and (self.mode == "board")

    def update(self, store: str, pct: int, cur: int, total: int, except_cnt: int = 0):
        if self.mode == "off":
            return
        with self._lock:
            if store not in self._rows:
                self._rows[store] = {}
                self._order.append(store)
            self._rows[store].update({"pct": pct, "cur": cur, "total": total, "except": except_cnt})
        self.render(throttled=True)

    def _build_lines(self) -> List[str]:
        lines = ["=== DELETE PROGRESS (parallel) ==="]
        for store in self._order:
            r = self._rows.get(store, {})
            pct = int(r.get("pct") or 0)
            cur = int(r.get("cur") or 0)
            total = int(r.get("total") or 0)
            exc = int(r.get("except") or 0)
            extra = f" | except:{exc}" if exc else ""
            lines.append(f"{store:<12} | {pct:3d}% | {cur}/{total}{extra}")
        return lines

    def render(self, throttled: bool = False):
        if self.mode == "off":
            return
        now = time.time()
        if throttled and (now - self._last_render) < self.refresh_sec:
            return

        with self._lock:
            lines = self._build_lines()
            snapshot = "\n".join(lines)
            if snapshot == self._last_snapshot:
                return
            self._last_snapshot = snapshot
            self._last_render = now

            if self._ansi_ok and self._printed_lines:
                sys.stdout.write(f"\x1b[{self._printed_lines}F")
                sys.stdout.flush()

            sys.stdout.write(snapshot + "\n")
            sys.stdout.flush()
            self._printed_lines = len(lines)


# 진행 보드 전역 인스턴스
PROGRESS = ProgressBoard()


# ================= Google Sheets =================
class Sheets:
    def __init__(self, spreadsheet_key: str, service_json_path: str):
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(service_json_path, scope)
        self.gc = gspread.authorize(creds)
        self.sh = self.gc.open_by_key(spreadsheet_key)

    def get_all_records(self, tab: str) -> List[Dict[str, Any]]:
        ws = self.sh.worksheet(tab)
        values = ws.get_all_values()
        if not values:
            return []
        headers = [h.strip() for h in values[0]]
        rows = []
        for row in values[1:]:
            padded = row + [""] * (len(headers) - len(row))
            rows.append({headers[i]: padded[i] for i in range(len(headers))})
        return rows

    def append_row(self, tab: str, values: List[Any]):
        try:
            ws = self.sh.worksheet(tab)
            ws.append_row(values, value_input_option="RAW")
        except gspread.exceptions.APIError as e:
            plog(f"[WARN] append_row API 오류: {e}")
        except Exception as e:
            plog(f"[WARN] append_row 실패: {e}")

    def ensure_sheet_with_headers(self, tab: str, headers: List[str]):
        try:
            ws = self.sh.worksheet(tab)
            current = ws.row_values(1)
            if current != headers:
                ws.update(range_name="1:1", values=[headers], value_input_option="RAW")
        except gspread.WorksheetNotFound:
            ws = self.sh.add_worksheet(title=tab, rows=200, cols=len(headers))
            ws.update(range_name="1:1", values=[headers], value_input_option="RAW")


def results_append_safe(sheets: Sheets, values: List[Any]):
    """
    - 콘솔에는 항상 [RESULT] 로그 찍고
    - job_name == "상품삭제" 인 경우만 구글시트 기록 생략
    - 그 외 작업(등록갯수/배송코드/배송변경/혜택설정/중복삭제)은 results 시트에 기록
    """
    job_name = S(values[1]) if len(values) > 1 else ""
    plog(f"[RESULT] {' | '.join(S(v) for v in values)}")

    if job_name == "상품삭제":
        return

    try:
        sheets.append_row(RESULTS_SHEET, values)
    except Exception as e:
        plog(f"[WARN] results 기록 실패: {e}")


# ================= 인증/서명 =================
def sign_client_secret(client_id: str, client_secret: str, ts_ms: int) -> str:
    pwd = f"{client_id}_{ts_ms}".encode("utf-8")
    hashed = bcrypt.hashpw(pwd, client_secret.strip().encode("utf-8"))
    return base64.b64encode(hashed).decode("utf-8")


def get_access_token(client_id: str, client_secret: str) -> str:
    ts = int(time.time() * 1000)
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "timestamp": ts,
        "client_secret_sign": sign_client_secret(client_id, client_secret, ts),
        "type": "SELF",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    r = HTTP_SESSION.post(TOKEN_URL, data=data, headers=headers, timeout=REQUEST_TIMEOUT)
    if r.status_code == 403:
        raise RuntimeError("403 Forbidden: 허용 IP/권한/스코프 확인 필요")
    r.raise_for_status()
    return r.json()["access_token"]


def auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json", "Content-Type": "application/json"}


# ================= Search/Count =================
def _fetch_product_counts(access_token: str) -> dict:
    headers = auth_headers(access_token)

    def total_elements(body: dict) -> int:
        base = {"page": 1, "size": 1}
        base.update(body)
        r = HTTP_SESSION.post(SEARCH_URL, headers=headers, json=base, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        js = r.json()
        return int(js.get("totalElements") or js.get("total") or 0)

    def count_by_status(status_code: str) -> int:
        return total_elements({"productStatusTypes": [status_code]})

    total_all = total_elements({})
    on_sale = count_by_status("SALE")
    stop_selling = count_by_status("SUSPENSION")
    approval_wait = count_by_status("WAIT")
    plog(f"[COUNT] api(current): 전체={total_all}, 판매중={on_sale}, 중지={stop_selling}, 승인대기={approval_wait}")
    return {"전체": total_all, "판매중": on_sale, "판매중지": stop_selling, "승인대기": approval_wait}


# ================= 주소록 → 배송코드 =================
def _addr_get(url: str, access_token: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    try:
        r = HTTP_SESSION.get(url, headers=headers, params=params or {}, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        plog(f"[배송코드][WARN] 주소록 요청 실패: {e}")
        return None
    if r.status_code != 200:
        plog(f"[배송코드][WARN] 주소록 요청 status={r.status_code} url={url}")
        return None
    try:
        return r.json()
    except (ValueError, json.JSONDecodeError) as e:
        plog(f"[배송코드][WARN] 주소록 응답 JSON 파싱 실패: {e}")
        return None


def _addr_to_list(js: Any) -> List[Dict[str, Any]]:
    if js is None:
        return []
    if isinstance(js, list):
        return js
    if isinstance(js, dict):
        for k in ("addressBooks", "contents", "items", "list", "data", "addresses", "rows"):
            v = js.get(k)
            if isinstance(v, list):
                return v
        return [js]
    return []


def _norm_addr(a: Dict[str, Any]) -> Dict[str, Any]:
    def g(*keys, default=None):
        for k in keys:
            if k in a and a[k] is not None:
                return a[k]
        return default

    ab_no = g("addressBookNo", "addressbookno", "addressId", "id", "addressNo")
    raw_type = g("type", "addressType", "category")
    a_type = str(raw_type or "").upper().strip()

    if a_type in ("RELEASE", "SHIPPING_RELEASE", "FULFILLMENT", "SHIPFROM"):
        std = "RELEASE"
    elif a_type in ("REFUND_OR_EXCHANGE", "REFUND", "RETURN", "EXCHANGE", "RETURNS"):
        std = "REFUND_OR_EXCHANGE"
    elif a_type in ("GENERAL", "DOMESTIC", "NORMAL", "DEFAULT", "BILLING"):
        std = "GENERAL"
    elif a_type in ("OVERSEAS", "EXPORT", "INTERNATIONAL"):
        std = "OVERSEAS"
    else:
        std = a_type or "UNKNOWN"

    overseas = bool(g("overseasAddress", "overseas", "isOverseas", default=False))
    default = bool(g("defaultAddress", "default", "isDefault", default=False))

    return {
        "addressBookNo": ab_no,
        "type": std,
        "overseas": overseas,
        "default": default,
        "raw": a,
    }


def extract_delivery_codes(addresses: List[Dict[str, Any]]) -> Dict[str, str]:
    norm = [_norm_addr(a) for a in addresses if isinstance(a, dict)]

    def pick(candidates: List[Dict[str, Any]]) -> Optional[int]:
        if not candidates:
            return None
        defaults = [c for c in candidates if c.get("default")]
        target = defaults[0] if defaults else candidates[0]
        try:
            return int(str(target.get("addressBookNo")).strip())
        except (ValueError, TypeError):
            return None

    SHIPPING_TYPES = ("GENERAL", "RELEASE", "OVERSEAS", "UNKNOWN")

    domestic_candidates = [
        x for x in norm
        if not x.get("overseas", False) and x.get("type") in SHIPPING_TYPES
    ]

    overseas_candidates = [
        x for x in norm
        if x.get("overseas", False) and x.get("type") in SHIPPING_TYPES
    ]

    refund_candidates = [
        x for x in norm
        if x.get("type") in ("REFUND_OR_EXCHANGE", "REFUND", "RETURN", "EXCHANGE", "RETURNS")
    ]

    dom_id = pick(domestic_candidates)
    over_id = pick(overseas_candidates)
    ret_id = pick(refund_candidates)

    return {
        "국내출고지": str(dom_id) if dom_id is not None else "",
        "해외출고지": str(over_id) if over_id is not None else "",
        "반품지": str(ret_id) if ret_id is not None else "",
    }


def fetch_address_book(access_token: str) -> List[Dict[str, Any]]:
    """
    스마트스토어 주소록 전체를 리스트로 반환한다.

    - /seller/addressbooks-for-page (신규, 페이징) 먼저 사용
    - 거기서 아무것도 못 가져오면 /seller/addressbooks (구버전) 한 번 더 시도
    """
    all_items: List[Dict[str, Any]] = []

    # 1) paged 엔드포인트 우선 사용
    page = 1
    size = 50  # 주소록 많지 않아서 50이면 충분
    while True:
        if STOP_EVENT.is_set():
            break

        js = _addr_get(ADDR_PAGED, access_token, {"page": page, "size": size})
        if not js:
            break

        items = _addr_to_list(js)
        if not items:
            break

        all_items.extend(items)

        # 마지막 페이지면 탈출
        if len(items) < size:
            break

        page += 1
        # 혹시나 무한 루프 방지
        if page > 200:
            break

    # 2) paged 쪽에서 아무것도 못 가져왔으면 구버전 엔드포인트 fallback
    if not all_items:
        js = _addr_get(ADDR_LIST, access_token)
        all_items = _addr_to_list(js)

    return all_items


# ================= 혜택설정 유틸 =================
def _parse_int_or_none(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip()
    if s == "":
        return None
    if s == "-":
        return 0
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _is_true_flag(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().upper() in ("TRUE", "Y", "YES", "1")


def build_customer_benefit_from_row(row: dict) -> dict:
    """
    혜택설정 시트 한 줄(row) → PURCHASE_BENEFIT dict 생성
    이벤트문구(별도 컬럼)는 여기서 제외 (v2 개별 업데이트용)
    """
    def to_int(x):
        try:
            if x is None:
                return None
            s = str(x).replace(",", "").strip()
            if s == "":
                return None
            return int(float(s))
        except (ValueError, TypeError):
            return None

    benefit: dict = {}

    # 후기 포인트 정책
    review: dict = {}
    t = to_int(row.get("후기포인트"))
    p = to_int(row.get("포토후기포인트"))
    at = to_int(row.get("한달후기포인트"))
    ap = to_int(row.get("한달포토후기포인트"))

    if t is not None:
        review["textReviewPoint"] = t
    if p is not None:
        review["photoVideoReviewPoint"] = p
    if at is not None:
        review["afterUseTextReviewPoint"] = at
    if ap is not None:
        review["afterUsePhotoVideoReviewPoint"] = ap

    if review:
        benefit["reviewPointPolicy"] = review

    # 사은품 문구
    gift_txt = (row.get("사은품") or "").strip()
    if gift_txt:
        benefit["giftPolicy"] = {"presentContent": gift_txt}

    # 복수구매 할인
    qty = to_int(row.get("복수구매"))
    disc = to_int(row.get("복수구매할인"))
    if qty and disc:
        benefit["multiPurchaseDiscountPolicy"] = {
            "orderValue": qty,
            "orderValueUnitType": "COUNT",
            "discountMethod": {
                "value": disc,
                "unitType": "WON",
            },
        }

    return benefit


def _extract_discounted_price_from_search_item(item: dict) -> int:
    """
    검색 결과 한 건에서 할인판매가(discountedPrice)를 우선으로 뽑고,
    없으면 salePrice를 사용. 전부 없으면 0 리턴.
    """
    try:
        prod = item.get("product") or item
        cps = prod.get("channelProducts") or item.get("channelProducts") or []

        prices = []

        for c in cps:
            if not isinstance(c, dict):
                continue
            d = c.get("discountedPrice")
            s = c.get("salePrice")
            if d is not None:
                prices.append(float(d))
            elif s is not None:
                prices.append(float(s))

        if prices:
            return int(prices[0])

        ps = prod.get("productSale") or {}
        if ps.get("discountedPrice") is not None:
            return int(ps["discountedPrice"])
        if ps.get("salePrice") is not None:
            return int(ps["salePrice"])

    except (ValueError, TypeError, KeyError, AttributeError):
        pass

    return 0


def _search_products_base(
    access_token: str,
    filters: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
    price_filter: Optional[Callable[[dict], bool]] = None,
) -> List[int]:
    """
    /products/search 에서 originProductNo 리스트만 뽑는 공용 함수.

    - filters.status_type:
        * "ON_SALE" / "SALE" / "판매중" → productStatusTypes=["SALE"] 로 변환(판매중만)
        * 그 외 값 → 그대로 statusType 에 넣어서 사용(혹시 모를 확장용)
    - created_from / created_to / query / size 지원
    - 검색 결과 중 ProhibitionProduct(판매금지)는 origin 목록에서 제외
      (배송변경/혜택설정에서 400 ProhibitionProduct 터지는 것 방지)
    - price_filter: 가격 필터 함수 (Optional)
    """
    headers = auth_headers(access_token)
    filters = filters or {}
    page = 1  # 네이버 API는 page=1부터 시작
    size = min(Config.SEARCH_PAGE_SIZE_LARGE, max(1, int(filters.get("size") or Config.SEARCH_PAGE_SIZE_LARGE)))
    nos: List[int] = []

    status_raw = S(filters.get("status_type"))
    min_price = filters.get("min_price", 0)

    log_prefix = "[SEARCH][PRICE]" if price_filter else "[SEARCH]"
    log(
        f"{log_prefix} 상품 검색 시작 → size={size}, limit={limit}, "
        f"created_from={filters.get('created_from')}, created_to={filters.get('created_to')}, "
        f"query={filters.get('query')}, status={status_raw}"
        + (f", min_price={min_price}" if price_filter else "")
    )

    while True:
        log(f"{log_prefix} 페이지 {page} 요청 중… (현재까지 {len(nos)}개 수집)")

        body: Dict[str, Any] = {
            "page": page,
            "size": size,
            "sort": "CREATED_DATE",
            "order": "DESC",
        }

        # ===== status_type 처리 =====
        if status_raw:
            st_up = status_raw.upper()
            # 시트에 ON_SALE 이라고 써도 실제 API에는 SALE 로 맞춰서 전달
            if st_up in ("ON_SALE", "SALE") or status_raw == "판매중":
                body["productStatusTypes"] = ["SALE"]
            else:
                # 혹시 다른 상태값을 쓰고 싶을 때를 위해 fallback
                body["statusType"] = status_raw

        # ===== 날짜/검색어 필터 =====
        if filters.get("created_from"):
            body["createdFrom"] = filters["created_from"]
        if filters.get("created_to"):
            body["createdTo"] = filters["created_to"]
        if filters.get("query"):
            body["query"] = filters["query"]

        try:
            r = HTTP_SESSION.post(SEARCH_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as e:
            log(f"{log_prefix}[ERROR] page={page} 검색 실패 → {e}")
            raise

        data = r.json()
        items = data.get("contents") or data.get("items") or []

        if not items:
            log(f"{log_prefix} 페이지 {page} 비어있음 → 검색 종료")
            break

        for it in items:
            prod = it.get("product") or it

            # ProhibitionProduct(판매금지 상품)는 리스트에서 제외
            status_in_item = S(
                prod.get("productStatusType")
                or prod.get("statusType")
                or prod.get("status")
            ).upper()
            if "PROHIBITION" in status_in_item:
                continue

            # 가격 필터 적용
            if price_filter and not price_filter(it):
                continue

            no = (
                prod.get("originProductNo")
                or prod.get("productNo")
                or prod.get("id")
            )
            if no:
                try:
                    nos.append(int(no))
                except (ValueError, TypeError):
                    pass

            if limit and len(nos) >= limit:
                log(f"{log_prefix} limit {limit} 개 도달 → 검색 종료")
                return nos[:limit]

        if len(items) < size:
            log(f"{log_prefix} 페이지 {page} 이후 데이터 없음 → 검색 종료")
            break

        page += 1
        time.sleep(0.05)

    log(f"{log_prefix} 상품 검색 완료 → 총 {len(nos)}개 수집")
    return nos[:limit] if limit else nos


def list_origin_product_nos(
    access_token: str,
    filters: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
) -> List[int]:
    """
    /products/search 에서 originProductNo 리스트만 뽑는 공용 함수.
    """
    return _search_products_base(access_token, filters, limit, price_filter=None)


def list_origin_product_nos_by_discounted_price(
    access_token: str,
    min_price: int,
    filters: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
) -> List[int]:
    """
    혜택설정용:
      - 검색 결과에서 할인판매가(discountedPrice) 기준으로 min_price 이상인 것만 필터링
      - ProhibitionProduct 제외
    """
    filters = filters or {}
    filters["min_price"] = min_price

    def price_filter(it: dict) -> bool:
        discounted = _extract_discounted_price_from_search_item(it)
        return discounted >= min_price

    return _search_products_base(access_token, filters, limit, price_filter=price_filter)


# ================= 혜택설정 핸들러 =================
def bulk_update_benefit_for_store(
    access_token: str,
    customer_benefit: dict,
    origin_product_nos: List[int],
    chunk_size: int = Config.BENEFIT_CHUNK_SIZE,
):
    """
    PURCHASE_BENEFIT bulk 업데이트.
    - chunk 단위로 PUT
    - ProhibitionProduct 로 chunk 전체가 400 날아가면
      → 개별 PUT fallback 으로 금지상품만 제외
    """
    if not customer_benefit:
        return {
            "updated": 0,
            "attempt": 0,
            "fail": 0,
            "skipped": True,
            "reason": "no fields",
        }

    headers = auth_headers(access_token)
    url = BULK_UPDATE_URL

    updated = 0
    attempt = 0
    fail = 0
    total = len(origin_product_nos)

    if total == 0:
        return {
            "updated": 0,
            "attempt": 0,
            "fail": 0,
            "skipped": False,
            "reason": "no targets",
        }

    plog(f"[혜택설정][BULK] 총 대상 상품 {total}개, chunk_size={chunk_size}")

    for i in range(0, total, chunk_size):
        if STOP_EVENT.is_set():
            plog("[혜택설정][BULK] STOP 이벤트 감지 → 중단")
            break

        chunk = origin_product_nos[i: i + chunk_size]
        attempt += len(chunk)

        plog(
            f"[혜택설정][BULK] chunk {i+1}-{i+len(chunk)} / {total} 처리 중..."
        )

        body = {
            "originProductNos": chunk,
            "productBulkUpdateType": "PURCHASE_BENEFIT",
            "purchaseBenefit": customer_benefit,
        }

        try:
            r = HTTP_SESSION.put(url, headers=headers, json=body, timeout=20)
        except requests.RequestException as e:
            fail += len(chunk)
            plog(
                f"[혜택설정][BULK][ERROR] chunk {i+1}-{i+len(chunk)} / {total} "
                f"요청 예외: {e}"
            )
            continue

        if r.status_code == 200:
            updated += len(chunk)
            plog(
                f"[혜택설정][BULK][OK] chunk {i+1}-{i+len(chunk)} / {total} 성공"
            )
            continue

        # 400 + ProhibitionProduct → 개별 fallback
        if r.status_code == 400 and "ProhibitionProduct" in (r.text or ""):
            plog(
                f"[혜택설정][BULK] ProhibitionProduct 감지 → 개별 fallback 시도 "
                f"(chunk {i+1}-{i+len(chunk)})"
            )
            fb_updated, fb_failed = _bulk_update_benefit_chunk_per_item(
                access_token=access_token,
                customer_benefit=customer_benefit,
                origin_product_nos=chunk,
            )
            updated += fb_updated
            fail += fb_failed
            plog(
                f"[혜택설정][BULK][FALLBACK] chunk {i+1}-{i+len(chunk)} "
                f"per-item 결과: updated={fb_updated}, fail={fb_failed}"
            )
            continue

        fail += len(chunk)
        plog(
            f"[혜택설정][BULK][ERROR] chunk {i+1}-{i+len(chunk)} / {total} "
            f"status={r.status_code} resp={r.text[:250]}"
        )

    plog(
        f"[혜택설정][BULK] 완료: updated={updated}, attempt={attempt}, fail={fail}"
    )

    return {
        "updated": updated,
        "attempt": attempt,
        "fail": fail,
        "skipped": False,
    }


def _bulk_update_benefit_chunk_per_item(
    access_token: str,
    customer_benefit: dict,
    origin_product_nos: List[int],
) -> Tuple[int, int]:
    """
    ProhibitionProduct 등으로 chunk 전체가 실패할 때,
    해당 chunk 를 originProductNo 단위로 하나씩 PUT 해서
    금지상품만 실패시키고 나머지는 살리는 fallback.
    - 개별 origin 로그는 남기지 않고, 최종 합계만 상위에서 사용
    """
    headers = auth_headers(access_token)
    url = BULK_UPDATE_URL

    updated = 0
    failed = 0

    for origin in origin_product_nos:
        if STOP_EVENT.is_set():
            break

        body = {
            "originProductNos": [origin],
            "productBulkUpdateType": "PURCHASE_BENEFIT",
            "purchaseBenefit": customer_benefit,
        }

        try:
            r = HTTP_SESSION.put(url, headers=headers, json=body, timeout=20)
        except requests.RequestException:
            failed += 1
            continue

        if r.status_code == 200:
            updated += 1
        else:
            failed += 1

    return updated, failed


def update_benefit_updated_at(sheets: Sheets, store_name: str, ts: str):
    """
    혜택설정 시트(updated_at 컬럼)에 계정별 마지막 혜택 적용 시각 기록
    - 헤더에 updated_at 없으면 마지막 열에 자동 추가
    - store_name 행 찾아서 해당 행의 updated_at 셀만 갱신
    """
    SHEET_NAME = "혜택설정"
    try:
        ws = sheets.sh.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        plog(f"[혜택설정][WARN] '{SHEET_NAME}' 시트를 찾을 수 없음 → updated_at 기록 생략")
        return

    values = ws.get_all_values() or []
    if not values:
        plog(f"[혜택설정][WARN] '{SHEET_NAME}' 시트가 비어 있음 → updated_at 기록 생략")
        return

    headers = [h.strip() for h in values[0]]
    if "store_name" not in headers:
        plog(f"[혜택설정][WARN] '{SHEET_NAME}' 헤더에 store_name 없음 → updated_at 기록 생략")
        return

    if "updated_at" not in headers:
        headers.append("updated_at")
        ws.update("1:1", [headers])
        plog(f"[혜택설정] 헤더에 updated_at 추가")

    store_idx = headers.index("store_name")
    updated_idx = headers.index("updated_at")

    target_row = None
    for i, row in enumerate(values[1:], start=2):
        if len(row) <= store_idx:
            continue
        if row[store_idx].strip() == store_name:
            target_row = i
            break

    if target_row is None:
        plog(f"[혜택설정][WARN] {store_name}: '{SHEET_NAME}' 시트에서 행을 찾지 못해 updated_at 기록 생략")
        return

    try:
        ws.update_cell(target_row, updated_idx + 1, ts)
        plog(f"[혜택설정] {store_name}: updated_at={ts} 기록 완료 (row={target_row})")
    except Exception as e:
        plog(f"[혜택설정][WARN] {store_name}: updated_at 기록 실패 → {e}")


def update_benefit_result_ratio(sheets: Sheets, store_name: str, updated: int, attempt: int):
    """
    혜택설정 시트 L열('결과' 헤더)에 'updated/attempt' 형태로 기록
    - 헤더에 '결과' 없으면 추가
    - store_name 행 찾아서 해당 셀 갱신
    """
    SHEET_NAME = "혜택설정"
    try:
        ws = sheets.sh.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        plog(f"[혜택설정][WARN] '{SHEET_NAME}' 시트를 찾을 수 없음 → 결과 비율 기록 생략")
        return

    values = ws.get_all_values() or []
    if not values:
        plog(f"[혜택설정][WARN] '{SHEET_NAME}' 시트가 비어 있음 → 결과 비율 기록 생략")
        return

    headers = [h.strip() for h in values[0]]
    if "store_name" not in headers:
        plog(f"[혜택설정][WARN] '{SHEET_NAME}' 헤더에 store_name 없음 → 결과 비율 기록 생략")
        return

    if "결과" not in headers:
        headers.append("결과")
        ws.update("1:1", [headers])
        plog(f"[혜택설정] 헤더에 '결과' 추가")

    store_idx = headers.index("store_name")
    result_idx = headers.index("결과")

    target_row = None
    for i, row in enumerate(values[1:], start=2):
        if len(row) <= store_idx:
            continue
        if row[store_idx].strip() == store_name:
            target_row = i
            break

    if target_row is None:
        plog(f"[혜택설정][WARN] {store_name}: '{SHEET_NAME}' 시트에서 행을 찾지 못해 결과 비율 기록 생략")
        return

    ratio_str = f"{updated}/{attempt}"

    try:
        ws.update_cell(target_row, result_idx + 1, ratio_str)
        plog(f"[혜택설정] {store_name}: 결과={ratio_str} 기록 완료 (row={target_row})")
    except Exception as e:
        plog(f"[혜택설정][WARN] {store_name}: 결과 비율 기록 실패 → {e}")


def handler_benefit_update(sheets: Sheets, token: str, store_row: Dict[str, Any], cfg_row: Dict[str, Any]):
    store_name = S(store_row.get("store_name"))

    # 최소 판매가 (discountedPrice 기준)
    min_price = N(cfg_row.get("최소판매가")) or 0
    plog(f"[혜택설정] {store_name}: 최소판매가={min_price}원 이상(discountedPrice 기준)만 혜택 적용")

    # -------------------------
    # updated_at 기준으로 "이후 등록 상품만" 필터
    # -------------------------
    last_updated_raw = S(cfg_row.get("updated_at"))
    created_from = None

    if last_updated_raw:
        try:
            if " " in last_updated_raw:
                dt = datetime.strptime(last_updated_raw, "%Y-%m-%d %H:%M:%S")
            else:
                dt = datetime.strptime(last_updated_raw, "%Y-%m-%d")
            created_from = dt.strftime("%Y-%m-%d")
            plog(
                f"[혜택설정] {store_name}: updated_at={last_updated_raw} 이후 등록 상품만 대상 "
                f"(createdFrom={created_from})"
            )
        except (ValueError, TypeError):
            plog(f"[혜택설정][WARN] updated_at 파싱 실패({last_updated_raw}) → 전체 등록 상품 대상")

    today_str = datetime.now().strftime("%Y-%m-%d")

    filters: Dict[str, Any] = {
        "status_type": "SALE",
        "created_from": created_from,
        "created_to": today_str,
        "query": S(cfg_row.get("query")),
        "size": Config.SEARCH_PAGE_SIZE_LARGE,
    }

    origin_nos = list_origin_product_nos_by_discounted_price(
        access_token=token,
        min_price=min_price,
        filters=filters,
    )

    total_targets = len(origin_nos)
    if total_targets == 0:
        plog(f"[혜택설정] {store_name}: 조건(>= {min_price})에 맞는 SALE 상품 없음")
        ts = now_kr()
        results_append_safe(
            sheets,
            [ts, "혜택설정", store_name, 0, 0, 0, "", f"min_price={min_price}, SALE only, no targets"],
        )
        # 그래도 이 시점에 updated_at 찍어서 "다 했음" 기준 남겨두는게 맞음
        try:
            update_benefit_updated_at(sheets, store_name, ts)
        except Exception as e:
            plog(f"[혜택설정][WARN] {store_name}: updated_at 갱신 중 오류 → {e}")
        # 결과 비율(0/0)도 같이 기록
        try:
            update_benefit_result_ratio(sheets, store_name, 0, 0)
        except Exception as e:
            plog(f"[혜택설정][WARN] {store_name}: 결과 비율(0/0) 기록 중 오류 → {e}")
        return

    plog(f"[혜택설정] {store_name}: discountedPrice>={min_price}, SALE 상품 {total_targets}개")

    customer_benefit = build_customer_benefit_from_row(cfg_row)

    bulk_res = bulk_update_benefit_for_store(
        access_token=token,
        customer_benefit=customer_benefit,
        origin_product_nos=origin_nos,
        chunk_size=Config.BENEFIT_CHUNK_SIZE,
    )

    result_msg = (
        f"discountedPrice>={min_price}, SALE only, "
        f"bulk {bulk_res['updated']}/{bulk_res['attempt']} "
        f"fail={bulk_res['fail']}"
    )

    ts = now_kr()

    results_append_safe(
        sheets,
        [ts, "혜택설정", store_name,
         bulk_res["attempt"], bulk_res["updated"], bulk_res["fail"],
         "", result_msg]
    )

    # 혜택설정 시트 L열 '결과'에 updated/attempt 기록
    try:
        update_benefit_result_ratio(sheets, store_name, bulk_res["updated"], bulk_res["attempt"])
    except Exception as e:
        plog(f"[혜택설정][WARN] {store_name}: 결과 비율 기록 중 오류 → {e}")

    # 혜택설정 시트 M열 updated_at 갱신
    try:
        update_benefit_updated_at(sheets, store_name, ts)
    except Exception as e:
        plog(f"[혜택설정][WARN] {store_name}: updated_at 갱신 중 오류 → {e}")

    plog(f"[혜택설정] {store_name}: {result_msg}")


# ================= 오늘출발/배송변경 =================
def _call_bulk_update(access_token: str, body: dict) -> None:
    headers = auth_headers(access_token)
    for attempt in range(Config.MAX_RETRIES + 1):
        if STOP_EVENT.is_set():
            return
        try:
            r = HTTP_SESSION.put(BULK_UPDATE_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            plog(f"[WARN] bulk update 요청 예외: {e}")
            if attempt >= Config.MAX_RETRIES:
                raise RuntimeError(f"bulk update 요청 실패: {e}")
            sleep = min(2 ** attempt, Config.MAX_BACKOFF)
            if not sleep_with_stop(sleep):
                return
            continue

        if r.status_code == 429 or (500 <= r.status_code < 600):
            sleep = min(2 ** attempt, Config.MAX_BACKOFF)
            plog(f"[WARN] {r.status_code} → retry in {sleep}s (attempt {attempt+1}/{Config.MAX_RETRIES+1})")
            if not sleep_with_stop(sleep):
                return
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code} {r.reason}: type={body.get('productBulkUpdateType')} resp={r.text[:800]}")
        return


def build_delivery_info_from_job(job_row: Dict[str, Any]) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    delivery_type = S(job_row.get("deliveryType")) or "DELIVERY"
    info["deliveryType"] = delivery_type
    delivery_company = S(job_row.get("deliveryCompany"))
    if delivery_type == "DELIVERY" and delivery_company:
        info["deliveryCompany"] = delivery_company
    info["deliveryAttributeType"] = "NORMAL"

    feePayType = S(job_row.get("deliveryFeePayType"))
    baseFee = N(job_row.get("baseDeliveryFee"))
    fee_obj: Dict[str, Any] = {}
    if feePayType:
        fee_obj["deliveryFeePayType"] = feePayType
    if baseFee is not None:
        fee_obj["baseDeliveryFee"] = baseFee

    areaType = S(job_row.get("deliveryAreaType"))
    area2fee = N(job_row.get("area2extraFee"))
    area3fee = N(job_row.get("area3extraFee"))
    diffdesc = S(job_row.get("differentialFeeByArea"))
    area_obj: Dict[str, Any] = {}
    if areaType:
        area_obj["deliveryAreaType"] = areaType
    if area2fee is not None:
        area_obj["area2extraFee"] = area2fee
    if areaType == "AREA_3" and area3fee is not None:
        area_obj["area3extraFee"] = area3fee
    if area_obj:
        info.setdefault("deliveryFee", {})["deliveryFeeByArea"] = area_obj
    if diffdesc:
        info.setdefault("deliveryFee", {})["differentialFeeByArea"] = diffdesc
    if fee_obj:
        info.setdefault("deliveryFee", {}).update(fee_obj)

    claim_obj: Dict[str, Any] = {}
    ship_addr_id = N(job_row.get("shippingAddressId"))
    if ship_addr_id is not None:
        claim_obj["shippingAddressId"] = ship_addr_id
        plog(f"[INFO] 출고지 변경…OK (shippingAddressId={ship_addr_id})")
    return_addr_id = N(job_row.get("returnAddressId"))
    if return_addr_id is not None:
        claim_obj["returnAddressId"] = return_addr_id
        plog(f"[INFO] 반품지 변경…OK (returnAddressId={return_addr_id})")
    rfee = N(job_row.get("returnDeliveryFee"))
    if rfee is not None:
        claim_obj["returnDeliveryFee"] = rfee
    xfee = N(job_row.get("exchangeDeliveryFee"))
    if xfee is not None:
        claim_obj["exchangeDeliveryFee"] = xfee
    if claim_obj:
        info["claimDeliveryInfo"] = claim_obj

    return {k: v for k, v in info.items() if v not in (None, "", {})}


def build_today_attr_from_job(job_row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    courier = S(job_row.get("todayDeliveryCourier"))
    if not courier:
        return None
    plog(f"[INFO] 오늘출발…OK (todayDeliveryCourier={courier})")
    return {"deliveryAttributeType": "TODAY", "todayDeliveryCourier": courier}


def handler_delivery_update(sheets: Sheets, token: str, store_row: Dict[str, Any], cfg_row: Dict[str, Any]):
    store_name = S(store_row.get("store_name"))
    job_name = S(cfg_row.get("job_name")) or "배송변경"
    target_mode = S(cfg_row.get("target_mode")).upper()
    target_limit = N(cfg_row.get("target_limit")) or 0
    batch_size = N(cfg_row.get("batch_size")) or DEFAULT_BATCH_SIZE
    dry_run = B(cfg_row.get("dry_run"))
    update_types_raw = S(cfg_row.get("update_types")).upper()
    limit_types = (set(t.strip() for t in update_types_raw.split(",") if t.strip()) if update_types_raw else None)

    if target_mode == "LIST":
        origin_nos = parse_number_list(cfg_row.get("origin_product_nos"))
    elif target_mode == "FILTER":
        created_from = S(cfg_row.get("created_from"))
        created_to = S(cfg_row.get("created_to"))
        recent_days = N(cfg_row.get("recent_days"))
        if recent_days and not created_from and not created_to:
            today = datetime.now()
            created_to = today.strftime("%Y-%m-%d")
            created_from = (today - timedelta(days=recent_days)).strftime("%Y-%m-%d")
            plog(f"[INFO] [{store_name}] recent_days={recent_days} → {created_from} ~ {created_to}")
        filters = {
            "status_type": S(cfg_row.get("status_type")),
            "created_from": created_from,
            "created_to": created_to,
            "query": S(cfg_row.get("query")),
            "size": Config.SEARCH_PAGE_SIZE_LARGE
        }
        origin_nos = list_origin_product_nos(token, filters, limit=target_limit or 1000)
    else:
        raise ValueError("target_mode 은 LIST 또는 FILTER만 가능")

    if target_limit and len(origin_nos) > target_limit:
        origin_nos = origin_nos[:target_limit]
    if dry_run:
        origin_nos = origin_nos[:min(20, len(origin_nos))]

    total = len(origin_nos)
    if total == 0:
        results_append_safe(sheets, [now_kr(), job_name, store_name, 0, 0, 0, "", "no targets"])
        return

    delivery_info = build_delivery_info_from_job(cfg_row)
    if S(delivery_info.get("deliveryType")) == "DELIVERY" and not S(delivery_info.get("deliveryCompany")):
        raise RuntimeError("DELIVERY 타입에는 deliveryCompany(택배사) 코드 필요")
    attr_info = build_today_attr_from_job(cfg_row)

    if (not limit_types) or ("DELIVERY" in limit_types):
        for i in range(0, total, batch_size):
            if STOP_EVENT.is_set():
                break
            chunk = origin_nos[i:i + batch_size]
            body = {"originProductNos": chunk, "productBulkUpdateType": "DELIVERY", "deliveryInfo": delivery_info}
            _call_bulk_update(token, body)
            plog(f"[OK] {store_name} {job_name}: DELIVERY {i+1}-{i+len(chunk)} / {total}")

    if attr_info and ((not limit_types) or ("ATTR" in limit_types)):
        for i in range(0, total, batch_size):
            if STOP_EVENT.is_set():
                break
            chunk = origin_nos[i:i + batch_size]
            body = {"originProductNos": chunk, "productBulkUpdateType": "DELIVERY_ATTRIBUTE", "deliveryAttribute": attr_info}
            _call_bulk_update(token, body)
            plog(f"[OK] {store_name} {job_name}: ATTR {i+1}-{i+len(chunk)} / {total}")

    applied = []
    claim_info = delivery_info.get("claimDeliveryInfo") or {}
    applied.append("출고지OK" if "shippingAddressId" in claim_info else "출고지SKIP")
    applied.append("반품지OK" if "returnAddressId" in claim_info else "반품지SKIP")
    applied.append("오늘출발OK" if attr_info else "오늘출발SKIP")
    results_append_safe(sheets, [now_kr(), job_name, store_name, total, total, 0, "", ",".join(applied)])


# ================= 상품 삭제(예외 보고 포함) =================
def get_last_order_date_from_exceptions(sheets: Sheets) -> str:
    try:
        ws = sheets.sh.worksheet("삭제금지상품")
        return S(ws.acell("B1").value)
    except (gspread.WorksheetNotFound, gspread.exceptions.APIError):
        return ""


def load_delete_exceptions(sheets: Sheets) -> Set[str]:
    """
    '삭제금지상품' 시트에서 판매자코드 목록을 불러온다.
    - Google Sheets READ 쿼터를 줄이기 위해
      프로세스당 최초 1회만 get_all_values()를 호출하고
      이후에는 전역 캐시에서 재사용한다.
    - Thread-safe 버전
    """
    global DELETE_EXCEPTIONS_CACHE

    with _cache_lock:
        # 이미 로딩된 적 있으면 캐시 사용
        if DELETE_EXCEPTIONS_CACHE["loaded"]:
            return DELETE_EXCEPTIONS_CACHE["codes"]

        try:
            ws = sheets.sh.worksheet("삭제금지상품")
        except gspread.WorksheetNotFound:
            DELETE_EXCEPTIONS_CACHE["loaded"] = True
            DELETE_EXCEPTIONS_CACHE["codes"] = set()
            return set()

        values = ws.get_all_values()
        if not values or len(values) < 2:
            DELETE_EXCEPTIONS_CACHE["loaded"] = True
            DELETE_EXCEPTIONS_CACHE["codes"] = set()
            return set()

        headers = [h.strip() for h in values[0]]
        seller_col_idx = None
        for i, h in enumerate(headers):
            h_low = h.lower()
            if ("판매자" in h and "코드" in h) or ("seller" in h_low and "code" in h_low):
                seller_col_idx = i
                break
        if seller_col_idx is None:
            seller_col_idx = 1 if len(headers) > 1 else 0

        codes: Set[str] = set()
        for row in values[1:]:
            if len(row) <= seller_col_idx:
                continue
            code = S(row[seller_col_idx])
            if code:
                codes.add(code)

        DELETE_EXCEPTIONS_CACHE["loaded"] = True
        DELETE_EXCEPTIONS_CACHE["codes"] = codes

    return codes


def inline_progress_single(store: str, current: int, total: int, except_cnt: int = 0):
    pct = int((current / total) * 100) if total else 100
    if B(os.getenv("PARALLEL_STORES")):
        PROGRESS.update(store, pct, current, total, except_cnt)
    else:
        sys.stdout.write(f"\r[DEL] {store} {pct:3d}% | {current}/{total}" + (f" | except:{except_cnt}" if except_cnt else ""))
        sys.stdout.flush()
        if current >= total:
            sys.stdout.write("\n")
            sys.stdout.flush()


def _collect_delete_candidates(
    token: str,
    store_name: str,
    except_codes: Set[str]
) -> Tuple[List[Tuple[float, int, List[str]]], List[str], int]:
    """
    삭제 후보 상품 수집
    Returns: (candidates, except_hit_codes, total_scanned)
    """
    headers = auth_headers(token)
    page = 1  # 통일: page=1 시작
    size = Config.SEARCH_PAGE_SIZE_SMALL
    candidates: List[Tuple[float, int, List[str]]] = []  # (created_ts, origin_no, seller_codes)
    except_hit_codes: List[str] = []
    total_scanned = 0

    while not STOP_EVENT.is_set():
        body = {
            "page": page,
            "size": size,
            "sort": "CREATED_DATE",
            "order": "ASC",
        }
        try:
            r = HTTP_SESSION.post(SEARCH_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as e:
            plog(f"[상품삭제][ERROR] {store_name}: search page={page} 실패 → {e}")
            break

        data = r.json()
        contents = data.get("contents") or []
        if not contents:
            break

        for item in contents:
            if STOP_EVENT.is_set():
                break

            prod = item.get("product") or item
            origin_no = (
                prod.get("originProductNo")
                or prod.get("productNo")
                or prod.get("id")
            )
            if not origin_no:
                continue

            try:
                origin_no = int(origin_no)
            except (ValueError, TypeError):
                continue

            cps = item.get("channelProducts") or prod.get("channelProducts") or []
            seller_codes: List[str] = []
            for c in cps:
                code = S(c.get("sellerManagementCode"))
                if code:
                    seller_codes.append(code)

            total_scanned += 1

            # 삭제예외(삭제금지상품) 먼저 필터
            if except_codes and any(code in except_codes for code in seller_codes):
                for c in seller_codes:
                    if c in except_codes and c not in except_hit_codes:
                        except_hit_codes.append(c)
                continue

            created_ts = _extract_created_ts(item)
            candidates.append((created_ts, origin_no, seller_codes))

        if len(contents) < size:
            break

        page += 1
        if not sleep_with_stop(0.2):
            break

    return candidates, except_hit_codes, total_scanned


def _execute_deletion(
    token: str,
    store_name: str,
    candidates: List[Tuple[float, int, List[str]]],
    delete_count: int,
    except_cnt: int
) -> Tuple[int, int, int, int]:
    """
    실제 삭제 실행
    Returns: (success, already_deleted, failures, attempted)
    """
    headers = auth_headers(token)
    success = 0
    already_deleted = 0
    failures = 0
    attempted = 0

    inline_progress_single(store_name, success, delete_count, except_cnt)

    for created_ts, origin_no, seller_codes in candidates:
        if STOP_EVENT.is_set():
            plog(f"\n[STOP] {store_name}: 사용자 중단 요청 → 삭제 루프 종료")
            break
        if success >= delete_count:
            break

        url = f"{ORIGIN_DELETE_URL_V2}/{origin_no}"
        attempted += 1

        backoff = Config.INITIAL_BACKOFF
        max_retries = Config.MAX_RETRIES

        for attempt in range(1, max_retries + 1):
            if STOP_EVENT.is_set():
                break
            try:
                r = HTTP_SESSION.delete(url, headers=headers, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as e:
                plog(f"[상품삭제][ERROR] {store_name}: origin={origin_no} 요청 예외({attempt}/{max_retries}) → {e}")
                if attempt >= max_retries:
                    failures += 1
                else:
                    if not sleep_with_stop(backoff):
                        break
                    backoff = min(backoff * 2, Config.MAX_BACKOFF)
                continue

            # 429 / 5xx → 재시도
            if r.status_code == 429 or (500 <= r.status_code < 600):
                plog(
                    f"[상품삭제][WARN] {store_name}: origin={origin_no} "
                    f"status={r.status_code} ({attempt}/{max_retries}) → retry"
                )
                if attempt >= max_retries:
                    failures += 1
                    break
                if not sleep_with_stop(backoff):
                    break
                backoff = min(backoff * 2, Config.MAX_BACKOFF)
                continue

            # 404 → 이미 없는 상품으로 보고 카운트만, 성공으로 치진 않음
            if r.status_code == 404:
                already_deleted += 1
                plog(f"[상품삭제][INFO] {store_name}: origin={origin_no} 이미 삭제된 상품(404)")
                break

            # 400 등 클라이언트 에러
            if r.status_code >= 400:
                failures += 1
                try:
                    payload = r.json()
                except (ValueError, json.JSONDecodeError):
                    payload = {}
                msg = S(payload.get("message")) or r.text[:300]
                plog(
                    f"[상품삭제][ERROR] {store_name}: origin={origin_no} "
                    f"status={r.status_code} msg={msg}"
                )
                break

            # 2xx → 정상 삭제
            success += 1
            break

        inline_progress_single(store_name, success, delete_count, except_cnt)

    return success, already_deleted, failures, attempted


def handler_delete_oldest(sheets: Sheets, token: str, store_row: Dict[str, Any], cfg_row: Dict[str, Any]):
    """
    - delete_count 개수만큼
    - '가장 오래된 상품'부터
    - 삭제예외(삭제금지상품) 제외하고
    - 실제 삭제(2xx 응답) 성공 기준으로 최대한 delete_count 개까지 삭제 시도
    """
    store_name = S(store_row.get("store_name"))
    job_name = S(cfg_row.get("job_name")) or "상품삭제"
    dry_run = B(cfg_row.get("dry_run"))
    delete_count = N(cfg_row.get("delete_count")) or 0

    if STOP_EVENT.is_set():
        plog(f"[STOP] {store_name}: 시작 전 중단 요청 → 종료")
        return

    if delete_count <= 0:
        plog(f"[상품삭제] {store_name}: delete_count <= 0 → 스킵")
        results_append_safe(sheets, [now_kr(), job_name, store_name, 0, 0, 0, "", "delete_count <= 0"])
        return

    # 마지막 주문일자 기준 삭제예외 동기화
    last_order_date = get_last_order_date_from_exceptions(sheets)
    if last_order_date:
        plog(f"[상품삭제] {store_name}: LAST_ORDER_DATE(B1) = {last_order_date}")

    # 삭제금지상품 동기화는 프로세스당 1회만 수행 (쿼터 방어)
    global DELETE_EXCEPTIONS_SYNCED
    with _sync_lock:
        if sync_delete_exceptions is not None and not STOP_EVENT.is_set() and not DELETE_EXCEPTIONS_SYNCED:
            try:
                plog("[RUN] delete_exceptions_sync (상품삭제) 시작")
                sync_delete_exceptions()
                DELETE_EXCEPTIONS_SYNCED = True
            except Exception as e:
                plog(f"[WARN] {store_name}: 삭제금지상품 동기화 실패 → {e}")

    # 삭제금지상품 코드 로드 (캐시 사용)
    except_codes = load_delete_exceptions(sheets)
    plog(f"[상품삭제] {store_name}: 삭제금지상품 코드 수 = {len(except_codes)}")

    # 1단계: 전체 후보 수집
    candidates, except_hit_codes, total_scanned = _collect_delete_candidates(
        token, store_name, except_codes
    )
    except_cnt = len(except_hit_codes)

    if not candidates:
        plog(f"[상품삭제] {store_name}: 삭제 가능한 후보 없음 (scanned={total_scanned}, except={except_cnt})")
        if except_cnt:
            show = ", ".join(except_hit_codes[:50])
            tail = "" if except_cnt <= 50 else f" …(+{except_cnt-50})"
            plog(f"[EXCEPT][{store_name}] 예외코드: {show}{tail}")
        results_append_safe(
            sheets,
            [now_kr(), job_name, store_name, 0, 0, 0, "", f"no candidates, scanned={total_scanned}, except={except_cnt}"],
        )
        return

    # 2단계: 등록일 기준 정렬(오래된 순)
    candidates.sort(key=lambda x: (x[0], x[1]))

    plog(
        f"[상품삭제] {store_name}: 후보(예외 제외) {len(candidates)}개 중 "
        f"최대 {delete_count}개 오래된 순으로 삭제 시도"
        + (" (dry_run)" if dry_run else "")
    )

    if dry_run:
        # dry_run 이면 실제 삭제는 안 하고 후보/예외 정보만 기록
        if except_cnt:
            plog(f"[EXCEPT][{store_name}] 예외로 제외된 코드 수: {except_cnt}")
            show = ", ".join(except_hit_codes[:50])
            tail = "" if except_cnt <= 50 else f" …(+{except_cnt-50})"
            plog(f"[EXCEPT][{store_name}] 예외코드: {show}{tail}")
        preview = [c[1] for c in candidates[:delete_count]]
        plog(f"[상품삭제][DRY_RUN] {store_name}: 실제 삭제 대상이 될 originProductNo 상위 {delete_count}개: {preview}")
        results_append_safe(
            sheets,
            [now_kr(), job_name, store_name, min(len(candidates), delete_count), 0, 0, "", f"dry_run=True, scanned={total_scanned}, except={except_cnt}"],
        )
        return

    # 실제 삭제 실행
    success, already_deleted, failures, attempted = _execute_deletion(
        token, store_name, candidates, delete_count, except_cnt
    )

    # 예외 로그
    if except_cnt:
        plog(f"[EXCEPT][{store_name}] 예외로 제외된 코드 수: {except_cnt}")
        show = ", ".join(except_hit_codes[:50])
        tail = "" if except_cnt <= 50 else f" …(+{except_cnt-50})"
        plog(f"[EXCEPT][{store_name}] 예외코드: {show}{tail}")

    plog(
        f"[상품삭제][DONE] {store_name}: 요청={delete_count}, "
        f"성공={success}, 이미삭제={already_deleted}, 실패={failures}, "
        f"시도건수={attempted}, 후보={len(candidates)}, scanned={total_scanned}, except={except_cnt}"
    )

    results_append_safe(
        sheets,
        [
            now_kr(),
            job_name,
            store_name,
            min(len(candidates), delete_count),
            success,
            already_deleted,
            "",
            f"failures={failures}, attempted={attempted}, scanned={total_scanned}, except={except_cnt}, cand={len(candidates)}",
        ],
    )

    return


# ================= 상품 중복삭제(판매자코드 OR 상품명) =================
def _normalize_name_for_dedup(name: Any) -> str:
    if name is None:
        return ""
    s = str(name)
    # 공백 제거 + 소문자
    return "".join(s.split()).lower()


def _collect_all_products_for_dedup(token: str, store_name: str) -> Dict[int, Dict[str, Any]]:
    """
    /products/search 전체를 돌면서 중복검사용 데이터 수집
    - key: originProductNo(int)
    - value: {
        "created_ts": float,
        "seller_codes": [str, ...],
        "raw_name": str,
      }
    """
    headers = auth_headers(token)
    page = 1  # 통일: page=1 시작
    size = Config.SEARCH_PAGE_SIZE_SMALL
    products: Dict[int, Dict[str, Any]] = {}

    while not STOP_EVENT.is_set():
        body = {
            "page": page,
            "size": size,
            "sort": "CREATED_DATE",
            "order": "ASC",
        }
        try:
            r = HTTP_SESSION.post(
                SEARCH_URL,
                headers=headers,
                json=body,
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            plog(f"[중복삭제][ERROR] {store_name}: 검색 page={page} 실패 → {e}")
            break

        data = r.json()
        contents = data.get("contents") or []
        if not contents:
            break

        for item in contents:
            if STOP_EVENT.is_set():
                break

            prod = item.get("product") or item
            origin_no = (
                prod.get("originProductNo")
                or prod.get("productNo")
                or prod.get("id")
            )
            if not origin_no:
                continue
            try:
                origin_no = int(origin_no)
            except (ValueError, TypeError):
                continue

            cps = item.get("channelProducts") or prod.get("channelProducts") or []
            seller_codes: List[str] = []
            for c in cps:
                code = S(c.get("sellerManagementCode"))
                if code:
                    seller_codes.append(code)

            raw_name = (
                prod.get("name")
                or prod.get("productName")
                or (cps[0].get("name") if cps and isinstance(cps[0], dict) else "")
            )

            products[origin_no] = {
                "created_ts": _extract_created_ts(item),
                "seller_codes": seller_codes,
                "raw_name": S(raw_name),
            }

        if len(contents) < size:
            break

        page += 1
        if not sleep_with_stop(0.2):
            break

    plog(f"[중복삭제] {store_name}: 중복검사용 상품수={len(products)}")
    return products


def _pick_victims_from_groups_with_exceptions(
    groups: Dict[str, List[int]],
    products: Dict[int, Dict[str, Any]],
    except_codes: Set[str],
) -> Set[int]:
    """
    groups: key -> [origin_no, ...]
    products: origin_no -> meta( created_ts, seller_codes, raw_name )
    except_codes: 삭제금지상품의 판매자코드 집합

    규칙:
    - 그룹 안에 '판매된 상품(코드 ∈ except_codes)' 이 하나라도 있으면:
        → 그 상품들은 전부 살리고(삭제 X)
        → 같은 그룹 안의 '판매이력 없는 상품'만 victims 로 삭제
    - 그룹 안에 판매된 상품이 하나도 없으면:
        → created_ts 최신 1개만 살리고, 나머지는 victims 로 삭제
    """
    victims: Set[int] = set()

    for key, ids in groups.items():
        if len(ids) <= 1:
            continue

        has_sale: List[int] = []
        no_sale: List[int] = []

        for oid in ids:
            meta = products.get(oid, {}) or {}
            codes = meta.get("seller_codes") or []
            if any(c in except_codes for c in codes):
                has_sale.append(oid)
            else:
                no_sale.append(oid)

        if has_sale:
            # 판매된 상품이 있는 그룹 → 팔린 건 모두 살리고, 팔리지 않은 것만 삭제
            for oid in no_sale:
                victims.add(oid)
        else:
            # 판매된 상품이 없는 그룹 → 기존 로직 그대로(최신 1개만 살리기)
            sorted_ids = sorted(
                ids,
                key=lambda oid: (
                    products.get(oid, {}).get("created_ts", float("inf")),
                    oid,
                ),
                reverse=True,
            )
            survivor = sorted_ids[0]
            for oid in sorted_ids[1:]:
                victims.add(oid)

    return victims


def _dedup_find_victims(
    products: Dict[int, Dict[str, Any]],
    except_codes: Set[str],
) -> Tuple[Set[int], int, int]:
    """
    - 판매자코드 기준 → victims_code
    - (그걸 제외한 나머지에서) 상품명 기준 → victims_name
    - except_codes(삭제금지상품) 를 반영해서:
        · 판매된 상품은 절대 victims 되지 않도록 처리
        · 같은 이름/코드 그룹 안에 섞여 있으면 '판매X'만 삭제
    """
    # 1) 판매자코드 기준 그룹핑
    seller_groups: Dict[str, List[int]] = {}
    for oid, meta in products.items():
        for code in meta.get("seller_codes") or []:
            if not code:
                continue
            seller_groups.setdefault(code, []).append(oid)

    victims_code = _pick_victims_from_groups_with_exceptions(
        seller_groups,
        products,
        except_codes,
    )

    # 코드 기준 중복 그룹 수(단순 참고용)
    code_group_cnt = sum(1 for _k, ids in seller_groups.items() if len(ids) > 1)

    # 2) 상품명 기준 그룹핑 (코드 기준에서 victims 로 빠진 것 제외)
    survivors_after_code: Dict[int, Dict[str, Any]] = {
        oid: meta for oid, meta in products.items() if oid not in victims_code
    }

    name_groups: Dict[str, List[int]] = {}
    for oid, meta in survivors_after_code.items():
        norm_name = _normalize_name_for_dedup(meta.get("raw_name"))
        if not norm_name:
            continue
        name_groups.setdefault(norm_name, []).append(oid)

    victims_name = _pick_victims_from_groups_with_exceptions(
        name_groups,
        survivors_after_code,
        except_codes,
    )

    name_group_cnt = sum(1 for _k, ids in name_groups.items() if len(ids) > 1)

    victims_all: Set[int] = set()
    victims_all.update(victims_code)
    victims_all.update(victims_name)

    return victims_all, code_group_cnt, name_group_cnt


def _delete_origin_product_for_dedup(
    token: str,
    store_name: str,
    origin_no: int,
) -> Tuple[bool, bool]:
    """
    1개 상품 삭제 (중복삭제용)
    리턴: (deleted_success, already_deleted)
    """
    headers = auth_headers(token)
    url = f"{ORIGIN_DELETE_URL_V2}/{origin_no}"

    backoff = Config.INITIAL_BACKOFF
    max_retries = Config.MAX_RETRIES

    for attempt in range(1, max_retries + 1):
        if STOP_EVENT.is_set():
            break
        try:
            r = HTTP_SESSION.delete(url, headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            plog(
                f"[중복삭제][ERROR] {store_name}: origin={origin_no} "
                f"요청 예외({attempt}/{max_retries}) → {e}"
            )
            if attempt >= max_retries:
                return (False, False)
            if not sleep_with_stop(backoff):
                break
            backoff = min(backoff * 2, Config.MAX_BACKOFF)
            continue

        # 429 / 5xx → 재시도
        if r.status_code == 429 or (500 <= r.status_code < 600):
            plog(
                f"[중복삭제][WARN] {store_name}: origin={origin_no} "
                f"status={r.status_code} ({attempt}/{max_retries}) → retry"
            )
            if attempt >= max_retries:
                return (False, False)
            if not sleep_with_stop(backoff):
                break
            backoff = min(backoff * 2, Config.MAX_BACKOFF)
            continue

        # 404 → 이미 삭제로 간주 (카운트는 already_deleted 로)
        if r.status_code == 404:
            plog(f"[중복삭제][INFO] {store_name}: origin={origin_no} 이미 삭제(404)")
            return (False, True)

        # 그 외 4xx 에러
        if r.status_code >= 400:
            plog(
                f"[중복삭제][ERROR] {store_name}: origin={origin_no} "
                f"status={r.status_code} resp={r.text[:300]}"
            )
            return (False, False)

        # 2xx → 정상 삭제
        return (True, False)

    return (False, False)


def _update_dedup_count_in_delete_sheet(
    sheets: Sheets,
    store_name: str,
    deleted_count: int,
):
    """
    Google Sheets READ 쿼터 초과 방지를 위해:
    - 상품삭제 시트를 최초 1회만 전체 읽기(get_all_values)
    - 이후부터는 캐시된 내용만 사용
    - WRITE는 문제 없음
    - Thread-safe 버전
    """
    SHEET_NAME = "상품삭제"
    global DELETE_SHEET_CACHE

    # 1. 시트를 가져오기
    try:
        ws = sheets.sh.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        plog(f"[중복삭제][WARN] '{SHEET_NAME}' 시트를 찾을 수 없어 기록 생략")
        return

    with _cache_lock:
        # 2. 최초 1회만 전체 읽기
        if DELETE_SHEET_CACHE["headers"] is None:
            values = ws.get_all_values()
            if not values:
                plog(f"[중복삭제][WARN] '{SHEET_NAME}' 시트가 비어 있어 기록 생략")
                return

            headers = [h.strip() for h in values[0]]
            DELETE_SHEET_CACHE["headers"] = headers
            DELETE_SHEET_CACHE["values"] = values
        else:
            headers = DELETE_SHEET_CACHE["headers"]
            values = DELETE_SHEET_CACHE["values"]

        # 3. 헤더 검증 및 '중복삭제', 'updated_at' 헤더가 없으면 추가(1회만 실행)
        headers_changed = False
        if "중복삭제" not in headers:
            headers.append("중복삭제")
            headers_changed = True
            plog(f"[중복삭제] '{SHEET_NAME}' 헤더에 '중복삭제' 추가")

        if "updated_at" not in headers:
            headers.append("updated_at")
            headers_changed = True
            plog(f"[중복삭제] '{SHEET_NAME}' 헤더에 'updated_at' 추가")

        if headers_changed:
            # 헤더 실제 시트 반영 + 캐시 갱신
            ws.update("1:1", [headers])
            DELETE_SHEET_CACHE["headers"] = headers

        if "store_name" not in headers:
            plog(f"[중복삭제][WARN] '{SHEET_NAME}' 헤더에 store_name 없음 → 기록 생략")
            return

        store_idx = headers.index("store_name")
        dup_idx = headers.index("중복삭제")
        updated_idx = headers.index("updated_at") if "updated_at" in headers else None

        # 4. store_name 이 있는 행 찾기
        target_row = None
        for i, row in enumerate(values[1:], start=2):
            if len(row) <= store_idx:
                continue
            if row[store_idx].strip() == store_name:
                target_row = i
                break

    if target_row is None:
        plog(f"[중복삭제][WARN] {store_name}: '{SHEET_NAME}' 에 store_name 행 없음 → 기록 생략")
        return

    # 5. 업데이트 (WRITE는 쿼터 적음 → 문제 없음)
    try:
        # G열: 중복삭제 개수
        ws.update_cell(target_row, dup_idx + 1, str(deleted_count))
        plog(f"[중복삭제] {store_name}: 상품삭제!G{target_row} = {deleted_count} 기록 완료")

        # H열(or 현재 위치): updated_at 시간 기록
        if updated_idx is not None:
            ts = now_kr()
            ws.update_cell(target_row, updated_idx + 1, ts)
            plog(f"[중복삭제] {store_name}: updated_at 갱신 → {ts}")
    except Exception as e:
        plog(f"[중복삭제][WARN] {store_name}: 중복삭제 개수/updated_at 기록 실패 → {e}")


def handler_dedup_delete(sheets: Sheets, token: str, store_row: Dict[str, Any]):
    """
    단일 스토어:
      1) 삭제금지상품(판매이력 있는 상품코드) 최신화 + 로드
      2) 전체 상품 조회
      3) 판매자코드/상품명 기준 중복 그룹 계산
         - 삭제금지상품(판매된 상품)은 절대 삭제 X
         - 같은 그룹 안에 판매된 상품 + 미판매 상품이 섞여 있으면, 미판매 상품만 삭제
      4) 실제 삭제된 originProductNo(삭제코드)를 results 시트에 기록
      5) 삭제 성공 개수를 '상품삭제'!G 열에 기록
    """
    store_name = S(store_row.get("store_name"))
    job_name = "중복삭제"

    if STOP_EVENT.is_set():
        plog(f"[중복삭제] {store_name}: 시작 전 중단 요청 → 스킵")
        return

    # 1) 삭제금지상품 LAST_ORDER_DATE 로깅
    last_order_date = get_last_order_date_from_exceptions(sheets)
    if last_order_date:
        plog(f"[중복삭제] {store_name}: LAST_ORDER_DATE(B1) = {last_order_date}")

    # 2) 삭제금지상품 동기화는 프로세스당 1회만 수행 (상품삭제와 공유)
    global DELETE_EXCEPTIONS_SYNCED
    with _sync_lock:
        if sync_delete_exceptions is not None and not STOP_EVENT.is_set() and not DELETE_EXCEPTIONS_SYNCED:
            try:
                plog("[RUN] delete_exceptions_sync (중복삭제) 시작")
                sync_delete_exceptions()
                DELETE_EXCEPTIONS_SYNCED = True
            except Exception as e:
                plog(f"[WARN] {store_name}: 삭제금지상품 동기화 실패 → {e}")

    # 3) 삭제금지상품 코드 로드 (캐시 사용, 상품삭제와 공유)
    except_codes = load_delete_exceptions(sheets)
    plog(f"[중복삭제] {store_name}: 삭제금지상품 코드 수 = {len(except_codes)}")

    # 4) 전체 상품 수집
    products = _collect_all_products_for_dedup(token, store_name)
    if not products:
        plog(f"[중복삭제] {store_name}: 상품이 없어 스킵")
        results_append_safe(
            sheets,
            [now_kr(), job_name, store_name, 0, 0, 0, "", "no products"],
        )
        _update_dedup_count_in_delete_sheet(sheets, store_name, 0)
        return

    # 5) 중복 그룹에서 victim 추출 (삭제금지상품 고려)
    victims_all, code_group_cnt, name_group_cnt = _dedup_find_victims(
        products,
        except_codes,
    )
    victim_cnt = len(victims_all)

    plog(
        f"[중복삭제] {store_name}: 판매자코드 중복그룹={code_group_cnt}, "
        f"상품명 중복그룹={name_group_cnt}, 삭제대상 상품수={victim_cnt}"
    )

    if victim_cnt == 0:
        results_append_safe(
            sheets,
            [
                now_kr(),
                job_name,
                store_name,
                0,
                0,
                0,
                "",
                f"no duplicates (code_groups={code_group_cnt}, name_groups={name_group_cnt})",
            ],
        )
        _update_dedup_count_in_delete_sheet(sheets, store_name, 0)
        return

    # 6) 실제 삭제 실행
    deleted = 0
    already_deleted = 0
    errors = 0

    deleted_codes: List[int] = []
    already_codes: List[int] = []

    for origin_no in sorted(victims_all):
        if STOP_EVENT.is_set():
            plog(f"[중복삭제] {store_name}: 사용자 중단 요청 → 삭제 중단")
            break

        ok, already = _delete_origin_product_for_dedup(token, store_name, origin_no)
        if ok:
            deleted += 1
            deleted_codes.append(origin_no)
        elif already:
            already_deleted += 1
            already_codes.append(origin_no)
        else:
            errors += 1

    plog(
        f"[중복삭제][DONE] {store_name}: 대상={victim_cnt}, "
        f"삭제성공={deleted}, 이미삭제={already_deleted}, 실패={errors}"
    )

    # 삭제코드 문자열 (실제 삭제 성공한 originProductNo만)
    deleted_codes_str = ",".join(str(x) for x in deleted_codes)

    # 이미 삭제였던 코드들도 메모에 같이 남겨두면 검증할 때 참고 가능
    memo = f"errors={errors}, code_groups={code_group_cnt}, name_groups={name_group_cnt}"
    if already_codes:
        already_str = ",".join(str(x) for x in already_codes)
        memo += f", already={already_str}"

    # results 시트 기록
    # [시간, 작업명, 스토어, 대상수, 삭제성공, 이미삭제, 삭제코드, 메모]
    results_append_safe(
        sheets,
        [
            now_kr(),
            job_name,
            store_name,
            victim_cnt,
            deleted,
            already_deleted,
            deleted_codes_str,
            memo,
        ],
    )

    # 상품삭제 시트 G열 '중복삭제'에 삭제 성공 개수 기록
    _update_dedup_count_in_delete_sheet(sheets, store_name, deleted)


# ================= stores 설정 머지 =================
def _merge_default_row(rows: List[Dict[str, Any]], store_name: str) -> Optional[Dict[str, Any]]:
    default_row = None
    store_row = None
    for r in rows:
        name = S(r.get("store_name"))
        if name.upper() == "DEFAULT":
            default_row = r
        if name == store_name:
            store_row = r
    if not default_row and not store_row:
        return None
    if not default_row:
        return store_row
    if not store_row:
        return default_row
    merged = dict(default_row)
    for k, v in store_row.items():
        if S(v) != "":
            merged[k] = v
    return merged


# ================= 등록갯수 / 배송코드(전역) =================
def run_product_count_job(sheets: Sheets, stores_rows: List[Dict[str, Any]]):
    SHEET = PRODUCT_COUNT_SHEET
    REQUIRED_HEADERS = ["store_name", "전체", "판매중", "판매중지", "승인대기", "updated_at"]

    try:
        ws = sheets.sh.worksheet(SHEET)
        all_vals = ws.get_all_values() or []
    except gspread.WorksheetNotFound:
        ws = sheets.sh.add_worksheet(title=SHEET, rows=200, cols=len(REQUIRED_HEADERS))
        ws.update(range_name="1:1", values=[REQUIRED_HEADERS], value_input_option="RAW")
        all_vals = [REQUIRED_HEADERS]

    if not all_vals:
        all_vals = [REQUIRED_HEADERS]
        ws.update(range_name="1:1", values=[REQUIRED_HEADERS], value_input_option="RAW")

    headers = [h.strip() for h in (all_vals[0] if all_vals else [])]
    if not headers:
        headers = REQUIRED_HEADERS
        ws.update(range_name="1:1", values=[headers], value_input_option="RAW")

    missing = [h for h in REQUIRED_HEADERS if h not in headers]
    if missing:
        headers = headers + missing
        ws.update(range_name="1:1", values=[headers], value_input_option="RAW")
        if all_vals:
            all_vals[0] = headers
        else:
            all_vals = [headers]

    try:
        store_col_idx = headers.index("store_name")
    except ValueError:
        headers.append("store_name")
        ws.update(range_name="1:1", values=[headers], value_input_option="RAW")
        store_col_idx = headers.index("store_name")

    existing_rows = ws.get_all_values() if not all_vals else all_vals
    row_map = {}
    if existing_rows:
        for i, row in enumerate(existing_rows[1:], start=2):
            if len(row) > store_col_idx and row[store_col_idx]:
                row_map[row[store_col_idx]] = i

    total_jobs = len(stores_rows)
    ok_cnt = err_cnt = done = 0

    for store_row in stores_rows:
        if STOP_EVENT.is_set():
            break
        store = S(store_row.get("store_name"))
        client_id = S(store_row.get("client_id"))
        client_secret = S(store_row.get("client_secret"))
        if not store or not client_id or not client_secret:
            done += 1
            err_cnt += 1
            plog(f"[등록갯수][{done}/{total_jobs}] {store} -> client 누락")
            continue
        try:
            token = get_access_token(client_id, client_secret)
            counts = _fetch_product_counts(token)
            row_values_map = {
                "store_name": store,
                "전체": counts.get("전체", 0),
                "판매중": counts.get("판매중", 0),
                "판매중지": counts.get("판매중지", 0),
                "승인대기": counts.get("승인대기", 0),
                "updated_at": now_kr()
            }
            row_to_write = [row_values_map.get(h, "") for h in headers]
            target_row = row_map.get(store)
            if target_row is None:
                ws.append_row(row_to_write, value_input_option="RAW")
                current = ws.get_all_values()
                for i, r in enumerate(current[1:], start=2):
                    if len(r) > store_col_idx and r[store_col_idx] == store:
                        row_map[store] = i
                        break
            else:
                end_col = col_letter(len(headers))
                rng = f"A{target_row}:{end_col}{target_row}"
                ws.update(range_name=rng, values=[row_to_write], value_input_option="RAW")
            ok_cnt += 1
            plog(f"[등록갯수][{done+1}/{total_jobs}] {store} -> OK 전체:{row_values_map['전체']} 판매중:{row_values_map['판매중']} 중지:{row_values_map['판매중지']} 승인대기:{row_values_map['승인대기']}")
        except Exception as e:
            err_cnt += 1
            plog(f"[등록갯수][{done+1}/{total_jobs}] {store} -> ERROR {e}")
        finally:
            done += 1
            if not sleep_with_stop(0.1):
                break

    plog(f"[등록갯수] 완료: OK={ok_cnt}, ERR={err_cnt}, 총={total_jobs}")


def run_delivery_code_job(sheets: Sheets, stores_rows: List[Dict[str, Any]]):
    # E열까지 포함해서 헤더 정의
    headers = ["store_name", "국내출고지", "해외출고지", "반품지", "updated_at"]
    sheets.ensure_sheet_with_headers(DELIVERY_CODE_SHEET, headers)
    ws = sheets.sh.worksheet(DELIVERY_CODE_SHEET)

    total_jobs = len(stores_rows)
    ok_cnt = err_cnt = 0
    plog(f"[배송코드] 대상 계정: {total_jobs}개")
    plog("-------------------------\n| store | 판매중 | 상태 | 비고 |\n=========================")

    # 기존 시트에 이미 써져 있는 store 행 위치 맵
    all_rows_snapshot = ws.get_all_values()
    store_idx_map: Dict[str, int] = {}
    if all_rows_snapshot:
        hdr = all_rows_snapshot[0]
        try:
            sidx = hdr.index("store_name")
        except ValueError:
            sidx = 0
        for i, row in enumerate(all_rows_snapshot[1:], start=2):
            if len(row) > sidx and row[sidx]:
                store_idx_map[row[sidx]] = i

    for store_row in stores_rows:
        if STOP_EVENT.is_set():
            break

        store = S(store_row.get("store_name"))
        client_id = S(store_row.get("client_id"))
        client_secret = S(store_row.get("client_secret"))
        status = "OK"
        note = ""

        if not store or not client_id or not client_secret:
            status = "ERR"
            note = "client 누락"
            err_cnt += 1
            plog(f"| {store:<6} | -   | {status} | {note} |")
            continue

        try:
            # 토큰 발급
            token = get_access_token(client_id, client_secret)

            # 주소록 전체 조회
            addrs = fetch_address_book(token)

            # raw 주소록 debug 저장
            debug_dir = os.getenv("OUTPUT_DIR") or "./addressbooks_debug"
            ensure_dir(debug_dir)
            raw_path = os.path.join(debug_dir, f"{safe_name(store)}_addressbooks_raw.json")
            try:
                save_json(raw_path, addrs)
            except Exception as e:
                plog(f"[배송코드][WARN] raw 저장 실패({store}): {e}")

            # 코드 추출
            codes = extract_delivery_codes(addrs)

            # 이 계정의 업데이트 시각
            ts = now_kr()

            # 시트에 쓸 한 줄 (E열 updated_at 포함)
            row_to_write = [
                store,
                codes.get("국내출고지", ""),
                codes.get("해외출고지", ""),
                codes.get("반품지", ""),
                ts,
            ]

            # 기존 행이 있으면 업데이트, 없으면 append
            target_row = store_idx_map.get(store)
            if target_row is None:
                ws.append_row(row_to_write, value_input_option="RAW")
            else:
                end_col = col_letter(len(headers))
                rng = f"A{target_row}:{end_col}{target_row}"
                ws.update(
                    range_name=rng,
                    values=[row_to_write],
                    value_input_option="RAW",
                )

            ok_cnt += 1

        except Exception as e:
            status = "ERR"
            note = str(e)
            err_cnt += 1

        plog(f"| {store:<6} | -   | {status} | {note[:80]} |")

    plog("-------------------------")
    plog(f"[배송코드] 완료: OK={ok_cnt}, ERR={err_cnt}, 총={total_jobs}")


def run_global_task(sheets: Sheets, stores_rows: List[Dict[str, Any]], global_task: str):
    if global_task == "등록갯수":
        run_product_count_job(sheets, stores_rows)
    elif global_task == "배송코드":
        run_delivery_code_job(sheets, stores_rows)


# ================= 스토어 작업 러너 =================
def _run_store_job(sheets: Sheets, global_task: str, store_row: Dict[str, Any], cfg_row: Dict[str, Any]):
    store_name = S(store_row.get("store_name"))
    client_id = S(store_row.get("client_id"))
    client_secret = S(store_row.get("client_secret"))

    if not store_name or not client_id or not client_secret:
        plog(f"[WARN] {store_name or '(no name)'}: client_id/client_secret 누락 → 스킵")
        results_append_safe(sheets, [now_kr(), global_task, store_name, 0, 0, 0, "", "client missing"])
        return

    try:
        token = get_access_token(client_id, client_secret)
    except Exception as e:
        plog(f"[ERROR] {store_name}: 토큰 발급 실패 → {e}")
        results_append_safe(sheets, [now_kr(), global_task, store_name, 0, 0, 0, "", f"token error: {e}"])
        return

    try:
        if global_task == "배송변경":
            handler_delivery_update(sheets=sheets, token=token, store_row=store_row, cfg_row=cfg_row)
        elif global_task == "상품삭제":
            handler_delete_oldest(sheets=sheets, token=token, store_row=store_row, cfg_row=cfg_row)
        elif global_task == "혜택설정":
            handler_benefit_update(sheets=sheets, token=token, store_row=store_row, cfg_row=cfg_row)

    except Exception as e:
        plog(f"[ERROR] {store_name}: {global_task} 실패 → {e}")
        results_append_safe(sheets, [now_kr(), global_task, store_name, 0, 0, 0, "", f"job error: {e}"])


# ================= 메인 =================
def main():
    _install_sigint_handler()
    plog("[RUN] smartstore_all_in_one v1.1 시작")

    load_dotenv()
    
    def find_credentials(env_key, default_names):
        env_val = os.getenv(env_key)
        if env_val and os.path.exists(env_val):
            return env_val
        
        # 현재 디렉토리 및 루트 디렉토리에서 후보 파일들 검색
        search_dirs = [os.getcwd(), os.path.dirname(os.path.abspath(__file__))]
        for d in search_dirs:
            for name in default_names:
                target = os.path.join(d, name)
                if os.path.exists(target):
                    return target
        return default_names[0] if default_names else "service.json"

    service_json = find_credentials("SERVICE_ACCOUNT_JSON", [
        "autosms-466614-951e91617c69.json", 
        "service.json",
        "auto-smartstore-update-61c3a948c45c.json"
    ])
    
    spreadsheet_key = os.getenv("SPREADSHEET_KEY") or ""
    if not spreadsheet_key:
        raise RuntimeError("SPREADSHEET_KEY 환경변수 필요")

    plog(f"[ENV] PARALLEL_STORES={os.getenv('PARALLEL_STORES')}, PARALLEL_WORKERS={os.getenv('PARALLEL_WORKERS')}")

    sheets = Sheets(spreadsheet_key, service_json)

    # stores 시트 → A열 전역 작업/A2~ TRUE 계정
    stores_rows = sheets.get_all_records(STORES_SHEET)
    try:
        ws_stores = sheets.sh.worksheet(STORES_SHEET)
        a_col = ws_stores.col_values(1)
    except (gspread.WorksheetNotFound, gspread.exceptions.APIError):
        a_col = []
    global_task = S(a_col[0]) if a_col else ""
    plog(f"[GLOBAL] A1 = {global_task}")

    if not global_task or global_task == "-":
        plog("[INFO] 전역 작업명이 비어있거나 '-' → 수행할 작업 없음")
        return
    if global_task not in GLOBAL_TASK_OPTIONS:
        plog(f"[WARN] 지원하지 않는 작업명: {global_task}")
        plog(f"[WARN] 사용 가능 작업: {', '.join(GLOBAL_TASK_OPTIONS)}")
        return

    enabled_stores: List[Dict[str, Any]] = []
    for idx, row in enumerate(stores_rows):
        flag = a_col[idx + 1] if len(a_col) > idx + 1 else ""
        if B(flag):
            enabled_stores.append(row)

    plog(f"[RUN] 작업: {global_task} / 대상 계정: {len(enabled_stores)}개")
    if not enabled_stores:
        plog("[INFO] TRUE 로 설정된 계정이 없어 종료합니다.")
        return

    # 전역 작업은 직렬
    if global_task in ("등록갯수", "배송코드"):
        run_global_task(sheets, enabled_stores, global_task)
        return

    # 중복삭제는 설정 시트 없이 stores 정보만으로 동작
    if global_task == "중복삭제":
        plog(f"[중복삭제] 대상 계정: {len(enabled_stores)}개")
        for store_row in enabled_stores:
            if STOP_EVENT.is_set():
                break
            store_name = S(store_row.get("store_name"))
            client_id = S(store_row.get("client_id"))
            client_secret = S(store_row.get("client_secret"))

            if not store_name or not client_id or not client_secret:
                plog(f"[중복삭제][WARN] {store_name or '(no name)'}: client_id/client_secret 누락 → 스킵")
                results_append_safe(
                    sheets,
                    [now_kr(), "중복삭제", store_name, 0, 0, 0, "", "client missing"],
                )
                _update_dedup_count_in_delete_sheet(sheets, store_name or "", 0)
                continue

            try:
                token = get_access_token(client_id, client_secret)
            except Exception as e:
                plog(f"[중복삭제][ERROR] {store_name}: 토큰 발급 실패 → {e}")
                results_append_safe(
                    sheets,
                    [now_kr(), "중복삭제", store_name, 0, 0, 0, "", f"token error: {e}"],
                )
                _update_dedup_count_in_delete_sheet(sheets, store_name, 0)
                continue

            handler_dedup_delete(sheets, token, store_row)

        return

    # 계정별 설정
    cfg_rows_all = sheets.get_all_records(global_task)

    def _cfg_for(store_name: str) -> Optional[Dict[str, Any]]:
        return _merge_default_row(cfg_rows_all, store_name)

    parallel_on = B(os.getenv("PARALLEL_STORES"))
    max_workers = N(os.getenv("PARALLEL_WORKERS")) or 4

    if not parallel_on:
        plog("[INFO] 병렬 비활성화 → 순차 실행")
        for store_row in enabled_stores:
            if STOP_EVENT.is_set():
                break
            store_name = S(store_row.get("store_name"))
            cfg_row = _cfg_for(store_name)
            if not cfg_row:
                plog(f"[WARN] {store_name}: {global_task} 시트에서 DEFAULT/스토어 행을 찾지 못함 → 스킵")
                results_append_safe(sheets, [now_kr(), global_task, store_name, 0, 0, 0, "", "no config row"])
                continue
            _run_store_job(sheets, global_task, store_row, cfg_row)
    else:
        plog(f"[PARALLEL] 활성화: workers={max_workers}")
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = []
                for store_row in enabled_stores:
                    if STOP_EVENT.is_set():
                        break
                    store_name = S(store_row.get("store_name"))
                    cfg_row = _cfg_for(store_name)
                    if not cfg_row:
                        plog(f"[WARN] {store_name}: {global_task} 시트에서 DEFAULT/스토어 행을 찾지 못함 → 스킵")
                        results_append_safe(sheets, [now_kr(), global_task, store_name, 0, 0, 0, "", "no config row"])
                        continue
                    futures.append(ex.submit(_run_store_job, sheets, global_task, store_row, cfg_row))
                for fut in as_completed(futures):
                    if STOP_EVENT.is_set():
                        break
                    try:
                        fut.result()
                    except Exception as e:
                        plog(f"[PARALLEL][ERR] {e}")
        except KeyboardInterrupt:
            plog("\n[CTRL+C] 중단 요청 수신 → 실행 중 작업 취소 시도")
            STOP_EVENT.set()
            raise


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        plog("\n[DONE] 사용자 요청으로 안전하게 종료했습니다.")
