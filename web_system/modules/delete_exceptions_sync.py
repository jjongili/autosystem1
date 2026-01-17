#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
delete_exceptions_sync.py

외부 매출 스프레드시트(1~12월 시트)의 "판매자 상품코드"를
메인 autosystem 스프레드시트의 "삭제금지상품" 탭으로 동기화한다.

이번 버전 변경점:
- 마지막 주문일자 기준은 오직 `삭제금지상품!B1`만 사용
- B1 값이 없으면 전체 기간 대상으로 동기화
- B1 값이 있으면, 해당 '월' 시트만 스캔(예: B1=2025-11-03 → 11월 시트만)
- 월 시트(1~12월, jan~dec 등 영문 월명 포함)만 처리
- 기존 '삭제금지상품_설정' 탭은 더 이상 사용하지 않음
"""

from __future__ import annotations

import os
import sys
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv


# -------------------- 공통 유틸 --------------------

def log(msg: str) -> None:
    print(msg)
    sys.stdout.flush()

def S(v: Any) -> str:
    try:
        return "" if v is None else str(v).strip()
    except Exception:
        return ""

def normalise_header_name(h: str) -> str:
    """
    헤더명을 비교하기 쉽게 정규화:
    - 소문자
    - 공백/탭 제거
    - 특수기호 일부 제거
    """
    s = S(h).lower()
    s = s.replace(" ", "").replace("\t", "")
    s = s.replace("_", "").replace("-", "")
    return s

def parse_kr_date(text: str) -> Optional[datetime]:
    """
    "주문일자" 형태의 문자열을 datetime 으로 파싱.
    가능한 패턴들을 최대한 커버.
    """
    s = S(text)
    if not s:
        return None

    # 숫자 / . / - / / / 공백만 남기기
    s = re.sub(r"[^\d\-\.\/ ]", "", s)

    patterns = [
        "%Y-%m-%d",
        "%Y.%m.%d",
        "%Y.%m. %d",
        "%Y. %m. %d",
        "%Y/%m/%d",
        "%Y%m%d",
    ]
    for p in patterns:
        try:
            return datetime.strptime(s, p)
        except Exception:
            continue

    # 추가 fallback: 8자리 비정형
    m = re.search(r"(\d{4})[^\d]?(\d{1,2})[^\d]?(\d{1,2})", s)
    if m:
        y = int(m.group(1))
        mth = int(m.group(2))
        d = int(m.group(3))
        try:
            return datetime(y, mth, d)
        except Exception:
            return None

    return None


# -------------------- Google Sheets 래퍼 --------------------

class SheetClient:
    def __init__(self, spreadsheet_key: str, service_json_path: str):
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            service_json_path, scope
        )
        gc = gspread.authorize(creds)
        self.sh = gc.open_by_key(spreadsheet_key)

    def ensure_sheet_with_headers(self, title: str, headers: List[str]) -> gspread.Worksheet:
        try:
            ws = self.sh.worksheet(title)
            first_row = ws.row_values(1)
            if first_row != headers:
                ws.update("1:1", [headers], value_input_option="RAW")
            return ws
        except gspread.WorksheetNotFound:
            ws = self.sh.add_worksheet(title=title, rows=2000, cols=len(headers))
            ws.update("1:1", [headers], value_input_option="RAW")
            return ws

    def get_worksheet(self, title: str) -> gspread.Worksheet:
        return self.sh.worksheet(title)

    def list_worksheets(self) -> List[gspread.Worksheet]:
        return self.sh.worksheets()


# -------------------- 삭제금지상품!B1: 마지막 주문일자 읽기 --------------------

DELETE_SHEET_NAME = "삭제금지상품"

def get_last_order_date_from_b1(main_client: SheetClient) -> Optional[datetime]:
    """
    '삭제금지상품' 시트의 B1 셀을 마지막 주문일자로 사용.
    없으면 None 반환.
    """
    try:
        ws = main_client.sh.worksheet(DELETE_SHEET_NAME)
    except gspread.WorksheetNotFound:
        # 시트가 없다면 만들어 두고(헤더만) B1 기준일은 없는 것으로 처리
        ws = main_client.sh.add_worksheet(title=DELETE_SHEET_NAME, rows=5000, cols=2)
        ws.update("A1", [["판매자상품코드"]], value_input_option="RAW")
        return None

    try:
        val = S(ws.acell("B1").value)
    except Exception as e:
        log(f"[WARN] 삭제금지상품!B1 읽기 실패: {e}")
        return None

    if not val:
        return None

    # 여러 날짜 형식 지원
    try:
        return datetime.fromisoformat(val)
    except Exception:
        return parse_kr_date(val)


# -------------------- 삭제금지상품 시트: 기존 코드 읽기/추가 --------------------

def get_existing_delete_codes(main_client: SheetClient) -> Tuple[gspread.Worksheet, set]:
    """
    메인 스프레드시트에서 '삭제금지상품' 시트를 준비하고,
    1열의 모든 판매자 상품코드를 set 으로 반환.
    (A1 헤더 '판매자상품코드'가 없으면 생성)
    """
    try:
        ws = main_client.sh.worksheet(DELETE_SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = main_client.sh.add_worksheet(
            title=DELETE_SHEET_NAME, rows=5000, cols=2
        )
        ws.update("A1", [["판매자상품코드"]], value_input_option="RAW")

    try:
        first_row = ws.row_values(1) or []
        if not first_row or S(first_row[0]) == "":
            ws.update("A1", [["판매자상품코드"]], value_input_option="RAW")
    except Exception as e:
        raise RuntimeError(f"'삭제금지상품' 시트 준비 실패: {e}")

    try:
        col_values = ws.col_values(1)
    except Exception as e:
        raise RuntimeError(f"'삭제금지상품' 시트 읽기 실패: {e}")

    existing = set()
    for v in col_values[1:]:  # 헤더 제외
        code = S(v)
        if code:
            existing.add(code)

    return ws, existing

def append_new_delete_codes(ws: gspread.Worksheet, new_codes: List[str]) -> None:
    """
    삭제금지상품 시트에 새 코드들을 append.
    """
    if not new_codes:
        return
    rows = [[code] for code in new_codes]
    ws.append_rows(rows, value_input_option="RAW")


# -------------------- 월 시트 판별 --------------------

MONTH_EN = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

MONTH_REGEX = re.compile(
    r"""^\s*
        (?:
            (0?[1-9]|1[0-2])\s*(?:월|month|m)?   # 1, 01, 1월, 01월, 1month, 1m
            |
            (jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)
        )
        \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

def parse_month_from_title(title: str) -> Optional[int]:
    """시트 제목에서 월(1~12)을 추출. 매칭 실패 시 None."""
    t = S(title)
    if not t:
        return None

    m = MONTH_REGEX.match(t)
    if not m:
        return None

    g1, g2 = m.group(1), m.group(2)
    if g1:
        try:
            n = int(g1)
            if 1 <= n <= 12:
                return n
        except ValueError:
            return None
    if g2:
        return MONTH_EN.get(g2.lower())

    return None


# -------------------- 매출(1~12월) 시트에서 코드 수집 --------------------

def collect_codes_from_source(
    source_client: SheetClient, last_date: Optional[datetime]
) -> Tuple[set, Optional[datetime]]:
    """
    매출 스프레드시트의 '월 시트(1~12월)'에서
    - 2행 헤더의 "판매자 상품코드", "주문일자(또는 주문일시)" 열을 찾아
    - 3행부터 seller_code / order_date 를 읽어온 뒤
      last_date 기준(포함)으로 필터링하여 set 으로 수집.

    반환:
      (코드 집합, 이번 스캔 중 발견한 주문일자의 최댓값)
    * 이 버전에서는 B1 자동 갱신을 수행하지 않는다.
    * B1(기준일)이 존재하면 해당 '월' 시트만 스캔한다.
    """
    all_codes: set = set()
    max_order_date: Optional[datetime] = last_date

    sheets_list = source_client.list_worksheets()

    # 월 시트만 필터링
    month_sheets: List[Tuple[int, gspread.Worksheet]] = []
    for ws in sheets_list:
        mnum = parse_month_from_title(ws.title)
        if mnum is not None:
            month_sheets.append((mnum, ws))

    if not month_sheets:
        log("[WARN] 처리할 월 시트를 찾지 못함 (1~12월 명명 규칙 확인 필요)")
        return all_codes, max_order_date

    # ★ B1 기준일이 있으면 해당 월 ~ 현재 월까지 스캔
    if last_date is not None:
        start_month = last_date.month
        current_month = datetime.now().month
        
        # 연도가 바뀌는 경우 처리 (예: 기준일 12월, 현재 1월)
        if current_month < start_month:
            # 기준일 월~12월 + 1월~현재월
            target_months = list(range(start_month, 13)) + list(range(1, current_month + 1))
        else:
            target_months = list(range(start_month, current_month + 1))
        
        month_sheets = [(m, ws) for (m, ws) in month_sheets if m in target_months]
        log(f"[INFO] 기준일 존재 → {start_month}월~{current_month}월 시트 스캔 (대상: {target_months})")
    else:
        log("[INFO] 기준일 없음 → 모든 월 시트 스캔")

    month_sheets.sort(key=lambda x: x[0])  # 1→12 순

    for month_num, ws in month_sheets:
        title = ws.title
        log(f"[SRC] 월 시트 스캔: {title} (월={month_num})")

        try:
            values = ws.get_all_values()
        except Exception as e:
            log(f"[WARN] 시트 '{title}' 읽기 실패: {e}")
            continue

        if len(values) < 2:
            continue

        header_row = values[1]  # 2행이 헤더라고 가정
        header_map = {
            normalise_header_name(h): idx for idx, h in enumerate(header_row)
        }

        seller_idx = None
        order_idx = None

        for norm_h, idx in header_map.items():
            if norm_h == normalise_header_name("판매자 상품코드"):
                seller_idx = idx
            if norm_h in (normalise_header_name("주문일자"), normalise_header_name("주문일시")):
                order_idx = idx

        if seller_idx is None or order_idx is None:
            log(f"[INFO] '{title}': '판매자 상품코드' 또는 '주문일자' 헤더 없음 → 스킵")
            continue

        # 3행부터 실제 데이터
        for row in values[2:]:
            if seller_idx >= len(row) or order_idx >= len(row):
                continue

            seller_code = S(row[seller_idx])
            order_str = S(row[order_idx])
            if not seller_code:
                continue

            order_dt = parse_kr_date(order_str)
            if order_dt is None:
                continue

            # last_date 이후(포함)만 수집
            if last_date is not None and order_dt < last_date:
                continue

            all_codes.add(seller_code)

            if max_order_date is None or order_dt > max_order_date:
                max_order_date = order_dt

        log(f"[SRC] '{title}' 누적 수집 코드 수: {len(all_codes)}")

    return all_codes, max_order_date


# -------------------- 메인 동기화 로직 --------------------

def sync_delete_exceptions() -> None:
    load_dotenv()

    service_json = os.getenv("SERVICE_ACCOUNT_JSON") or "service.json"
    main_key = os.getenv("SPREADSHEET_KEY") or ""
    source_key = os.getenv("DELETE_SOURCE_SPREADSHEET_KEY") or ""

    if not main_key:
        raise RuntimeError("SPREADSHEET_KEY 환경변수가 필요합니다.")
    if not source_key:
        raise RuntimeError("DELETE_SOURCE_SPREADSHEET_KEY 환경변수가 필요합니다.")

    log("[RUN] delete_exceptions_sync 시작")

    main_client = SheetClient(main_key, service_json)
    source_client = SheetClient(source_key, service_json)

    # 1) 기존 삭제금지상품 + B1(last_order_date) 읽기
    ws_delete, existing_codes = get_existing_delete_codes(main_client)
    last_date = get_last_order_date_from_b1(main_client)

    if last_date:
        log(f"[INFO] 마지막 주문일자 기준(B1): {last_date.strftime('%Y-%m-%d')}")
    else:
        log("[INFO] 삭제금지상품!B1 값이 없어, 전체 기간 대상 동기화 수행")

    # 2) 매출 시트에서 신규 코드 수집 (월 시트만; B1이 있으면 해당 월만)
    src_codes, max_order_date = collect_codes_from_source(source_client, last_date)
    log(f"[INFO] 소스에서 가져온 전체 코드 수: {len(src_codes)}")

    # 3) 기존 삭제금지상품과 중복 제거
    new_codes = sorted(code for code in src_codes if code and code not in existing_codes)
    log(f"[INFO] 기존 삭제금지상품과 중복 제거 후 신규 코드 수: {len(new_codes)}")

    # 4) 신규 코드 append
    if new_codes:
        append_new_delete_codes(ws_delete, new_codes)
        log(f"[WRITE] 삭제금지상품 시트에 {len(new_codes)}개 코드 추가")
    else:
        log("[WRITE] 추가할 신규 코드 없음")

    # ※ 요청사항에 따라 B1은 자동 갱신하지 않습니다.
    # if max_order_date:
    #     ws_delete.update("B1", [[max_order_date.strftime("%Y-%m-%d")]], value_input_option="RAW")

    log("[DONE] delete_exceptions_sync 완료")


# -------------------- 엔트리 포인트 --------------------

if __name__ == "__main__":
    sync_delete_exceptions()
