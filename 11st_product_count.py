#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
11번가 판매중 상품수 확인
- 구글시트 "11번가" 탭에서 active=TRUE인 계정의 판매중 상품수 조회
- 결과를 콘솔에 출력하고, 시트 E열에 상품수 기록

[.env]
SPREADSHEET_KEY=<스프레드시트 키>
SERVICE_ACCOUNT_JSON=C:/autosystem/auto-smartstore-update-61c3a948c45c.json
"""

import os
import time
from datetime import datetime
from typing import List, Tuple, Optional

import requests
import xml.etree.ElementTree as ET
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

# ================== .env 로드 ==================
load_dotenv()

SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY", "").strip()
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON", "").strip()

if not SPREADSHEET_KEY:
    raise RuntimeError("SPREADSHEET_KEY 환경변수가 설정되어 있지 않습니다.")
if not SERVICE_ACCOUNT_JSON:
    raise RuntimeError("SERVICE_ACCOUNT_JSON 환경변수가 설정되어 있지 않습니다.")

# ================== Google 인증 ==================
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_JSON, SCOPES)
gc = gspread.authorize(creds)

CONFIG_SHEET_NAME = "11번가"

# ================== 11번가 API 설정 ==================
BASE_URL = "http://api.11st.co.kr"
MULTI_SEARCH_PATH = "/rest/prodmarketservice/prodmarket"
SEARCH_LIMIT = 500
STATUS_FILTER: Optional[str] = "103"  # 판매중


def post_xml_prodmarket(url: str, api_key: str, body_xml: str) -> Tuple[str, int]:
    headers = {
        "openapikey": api_key,
        "Content-Type": "text/xml;charset=euc-kr",
        "Accept": "application/xml",
    }
    data = body_xml.encode("euc-kr", errors="ignore")
    res = requests.post(url, headers=headers, data=data, timeout=30)
    raw = res.content.decode("euc-kr", errors="ignore")
    return raw, res.status_code


def build_search_xml(limit: int, start: int | None = None) -> str:
    parts = ["<SearchProduct>"]
    if STATUS_FILTER:
        parts.append(f"    <selStatCd>{STATUS_FILTER}</selStatCd>")
    parts.append(f"    <limit>{limit}</limit>")
    if start is not None:
        parts.append(f"    <start>{start}</start>")
    parts.append("</SearchProduct>")
    return "\n".join(parts)


def parse_prdno_list(raw_xml: str) -> List[str]:
    result: List[str] = []
    try:
        root = ET.fromstring(raw_xml)
    except Exception:
        return result

    for prod in root.iter():
        if prod.tag.endswith("product"):
            for child in prod:
                if child.tag.endswith("prdNo"):
                    prd_no = (child.text or "").strip()
                    if prd_no:
                        result.append(prd_no)
                    break
    return result


def count_products(api_key: str) -> int:
    """판매중 상품수 카운트"""
    all_prd: List[str] = []
    seen = set()
    page = 0

    while True:
        start = page * SEARCH_LIMIT + 1 if page > 0 else None
        xml_body = build_search_xml(SEARCH_LIMIT, start=start)
        url = f"{BASE_URL}{MULTI_SEARCH_PATH}"

        raw, status = post_xml_prodmarket(url, api_key, xml_body)

        if status != 200:
            print(f"  [오류] HTTP {status}")
            break

        prd_list = parse_prdno_list(raw)
        if not prd_list:
            break

        for p in prd_list:
            if p not in seen:
                seen.add(p)
                all_prd.append(p)

        if len(prd_list) < SEARCH_LIMIT:
            break

        page += 1
        time.sleep(0.3)

    return len(all_prd)


def main() -> None:
    sh = gc.open_by_key(SPREADSHEET_KEY)
    ws = sh.worksheet(CONFIG_SHEET_NAME)
    rows = ws.get_all_values()

    print("=" * 50)
    print("11번가 판매중 상품수 확인")
    print("=" * 50)

    total_products = 0
    active_stores = 0

    for row_idx, row in enumerate(rows[1:], start=2):
        active = (row[0].strip().upper() if len(row) > 0 else "")
        store_name = (row[1].strip() if len(row) > 1 else f"Store_{row_idx}")
        api_key = (row[2].strip() if len(row) > 2 else "")

        if active != "TRUE" or not api_key:
            continue

        active_stores += 1
        print(f"\n[{store_name}] 조회 중...")
        
        count = count_products(api_key)
        total_products += count
        
        print(f"[{store_name}] 판매중 상품: {count}개")

        # 시트에 결과 기록 (E열: 상품수, F열: 조회시간)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.update(range_name=f"E{row_idx}:F{row_idx}", values=[[f"판매중 {count}개", now]])

    print("\n" + "=" * 50)
    print(f"총 {active_stores}개 계정, 판매중 상품 합계: {total_products}개")
    print("=" * 50)


if __name__ == "__main__":
    main()
