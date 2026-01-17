#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
11번가 구글시트 기반 전체 상품 전시중지 / 전시재개 자동화
- 11번가 "다중 상품 조회(prodmarket)" API로 prdNo 목록을 가져와서
- stopdisplay / startdisplay 로 전시중지 / 전시재개 처리
- 계정 단위 병렬 + 상품 단위 병렬 처리

[구글시트 - "11번가" 탭]
A: active       (TRUE 일 때만 실행)
B: store_name   (로그용)
C: API KEY      (11번가 openapikey)
D: jobs         ("판매중지" | "판매재개")
E: 결과         (예: "판매중지 성공 10 / 실패 0 (총 10개)")
F: updated_at   (YYYY-MM-DD HH:MM:SS)

[.env]
SPREADSHEET_KEY=<스프레드시트 키>
SERVICE_ACCOUNT_JSON=C:/autosystem/auto-smartstore-update-61c3a948c45c.json
ELEVENST_STORE_WORKERS=3      # 동시에 처리할 계정 수 (기본 3)
ELEVENST_PRODUCT_WORKERS=5    # 계정당 동시에 처리할 상품 수 (기본 5)

기본 동작:
- prodmarket 다중상품조회로 prdNo 리스트 가져오기
- STATUS_FILTER = "103" → "판매중" 상품만 대상으로 전시중지/재개
- ThreadPoolExecutor 로
  * 계정 단위 병렬 (store-level)
  * 각 계정 내부는 상품 단위 병렬 (product-level)
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
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================== .env 로드 ==================
load_dotenv()

SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY", "").strip()
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON", "").strip()
STORE_WORKERS = int(os.getenv("ELEVENST_STORE_WORKERS", "3"))
PRODUCT_WORKERS = int(os.getenv("ELEVENST_PRODUCT_WORKERS", "5"))

if not SPREADSHEET_KEY:
    raise RuntimeError("SPREADSHEET_KEY 환경변수가 설정되어 있지 않습니다 (.env 확인).")
if not SERVICE_ACCOUNT_JSON:
    raise RuntimeError("SERVICE_ACCOUNT_JSON 환경변수가 설정되어 있지 않습니다 (.env 확인).")

# ================== Google 인증 ==================
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    SERVICE_ACCOUNT_JSON,
    SCOPES,
)
gc = gspread.authorize(creds)

CONFIG_SHEET_NAME = "11번가"

# ================== 11번가 API 설정 ==================
BASE_URL = "http://api.11st.co.kr"

# 다중 상품 조회 API
MULTI_SEARCH_PATH = "/rest/prodmarketservice/prodmarket"

# 전시중지 / 전시재개 API
STOP_PATH = "/rest/prodstatservice/stat/stopdisplay"
START_PATH = "/rest/prodstatservice/stat/startdisplay"

# 한 페이지당 최대 500개 (문서상 최대)
SEARCH_LIMIT = 500

# 판매상태 필터
# - "103"  : 판매중인 상품만 대상 (추천)
# - None   : 상태 상관없이 전체 (과거/종료/품절까지 전부 포함)
STATUS_FILTER: Optional[str] = "103"


# ================== 11번가 요청 래퍼 ==================
def post_xml_prodmarket(url: str, api_key: str, body_xml: str) -> Tuple[str, int]:
    """
    prodmarket 다중상품조회 전용 요청
    - Method: POST
    - Content-Type: text/xml;charset=euc-kr
    - Accept: application/xml
    - Body: SearchProduct XML 전체
    """
    headers = {
        "openapikey": api_key,
        "Content-Type": "text/xml;charset=euc-kr",
        "Accept": "application/xml",
    }

    data = body_xml.encode("euc-kr", errors="ignore")
    res = requests.post(url, headers=headers, data=data, timeout=30)
    raw = res.content.decode("euc-kr", errors="ignore")
    return raw, res.status_code


def put_simple(url: str, api_key: str) -> Tuple[str, int]:
    """
    stopdisplay / startdisplay 전용 요청
    - Method: PUT
    - 바디 없음
    """
    headers = {
        "openapikey": api_key,
        "Accept": "application/xml",
    }
    res = requests.put(url, headers=headers, timeout=30)
    raw = res.content.decode("euc-kr", errors="ignore")
    return raw, res.status_code


# ================== 다중 상품 조회 (전체 prdNo 리스트) ==================
def build_search_xml(limit: int, start: int | None = None) -> str:
    """
    다중 상품 조회용 SearchProduct XML 생성
    - 루트: <SearchProduct>
    - 필수: <limit>
    - 페이징 시 선택: <start>
    - STATUS_FILTER 가 설정되어 있으면 <selStatCd> 추가
    """
    parts = ["<SearchProduct>"]
    if STATUS_FILTER:
        parts.append(f"    <selStatCd>{STATUS_FILTER}</selStatCd>")
    parts.append(f"    <limit>{limit}</limit>")
    if start is not None:
        parts.append(f"    <start>{start}</start>")
    parts.append("</SearchProduct>")
    return "\n".join(parts)


def parse_prdno_list_from_multi_search(raw_xml: str) -> List[str]:
    """
    다중 상품 조회 응답 XML에서 prdNo 리스트 추출
    """
    result: List[str] = []

    try:
        root = ET.fromstring(raw_xml)
    except Exception:
        return result

    for prod in root.iter():
        if prod.tag.endswith("product"):
            prd_no = None
            for child in prod:
                if child.tag.endswith("prdNo"):
                    prd_no = (child.text or "").strip()
                    break
            if prd_no:
                result.append(prd_no)

    return result


def fetch_all_products(api_key: str) -> List[str]:
    """
    해당 계정(API KEY)에 대해 다중 상품 조회 API를 여러 번 호출해서
    모든 prdNo 리스트를 가져온다.
    - STATUS_FILTER 에 따라 상태 필터링
    - 페이지 간 중복 prdNo 제거
    """
    all_prd: List[str] = []
    seen = set()
    page = 0

    while True:
        start = page * SEARCH_LIMIT + 1 if page > 0 else None
        xml_body = build_search_xml(SEARCH_LIMIT, start=start)
        url = f"{BASE_URL}{MULTI_SEARCH_PATH}"

        raw, status = post_xml_prodmarket(url, api_key, xml_body)

        if status != 200:
            print(f"[상품조회] HTTP {status} → 중단")
            print(raw[:300])
            break

        prd_list = parse_prdno_list_from_multi_search(raw)
        if not prd_list:
            # 더 이상 상품 없음
            break

        new_cnt = 0
        for p in prd_list:
            if p not in seen:
                seen.add(p)
                all_prd.append(p)
                new_cnt += 1

        print(
            f"[상품조회] 페이지 {page+1}: 받아온 {len(prd_list)}개 / "
            f"신규 {new_cnt}개 (누적 {len(all_prd)}개)"
        )

        # 500개 미만 나오면 마지막 페이지
        if len(prd_list) < SEARCH_LIMIT:
            break

        page += 1
        time.sleep(0.3)

    return all_prd


# ================== 전시중지 / 전시재개 (단일 상품) ==================
def stop_display(prd_no: str, api_key: str) -> Tuple[bool, str]:
    url = f"{BASE_URL}{STOP_PATH}/{prd_no}"
    raw, status = put_simple(url, api_key)

    if status != 200:
        return False, f"HTTP {status}: {raw[:200]}"

    try:
        root = ET.fromstring(raw)
        result_code = (root.findtext("resultCode") or "").strip()
        message = (root.findtext("message") or "").strip()
    except Exception as e:
        return False, f"XML 파싱 오류: {e}, body={raw[:200]}"

    return result_code == "200", message or raw[:200]


def start_display(prd_no: str, api_key: str) -> Tuple[bool, str]:
    url = f"{BASE_URL}{START_PATH}/{prd_no}"
    raw, status = put_simple(url, api_key)

    if status != 200:
        return False, f"HTTP {status}: {raw[:200]}"

    try:
        root = ET.fromstring(raw)
        result_code = (root.findtext("resultCode") or "").strip()
        message = (root.findtext("message") or "").strip()
    except Exception as e:
        return False, f"XML 파싱 오류: {e}, body={raw[:200]}"

    return result_code == "200", message or raw[:200]


# ================== 스토어 단위 처리 (상품 병렬) ==================
def process_store(
    row_idx: int,
    store_name: str,
    api_key: str,
    job: str,
) -> Tuple[int, str, str]:
    """
    단일 스토어 처리
    - prdNo 목록 조회
    - 상품 단위 병렬로 전시중지/재개
    - 결과 문자열과 업데이트 시간을 리턴
    """
    print(f"\n===== [{row_idx}] {store_name} / {job} 시작 =====")

    # 1) 전체 상품 prdNo 리스트 가져오기
    prd_list = fetch_all_products(api_key)
    total = len(prd_list)

    if total == 0:
        msg = "상품 없음 (다중상품조회 결과 0개)"
        print(f"[{store_name}] {msg}")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return row_idx, msg, now

    print(f"[{store_name}] 대상 상품 수: {total}")
    print(f"[{store_name}] 상품 병렬 처리 시작 (workers={PRODUCT_WORKERS})")

    success = 0
    fail = 0

    def worker(prd_no: str) -> Tuple[str, bool, str]:
        if job == "판매중지":
            ok, message = stop_display(prd_no, api_key)
        else:
            ok, message = start_display(prd_no, api_key)
        return prd_no, ok, message

    # 상품 병렬 처리
    with ThreadPoolExecutor(max_workers=PRODUCT_WORKERS) as executor:
        future_to_prd = {
            executor.submit(worker, prd): prd for prd in prd_list
        }

        for i, future in enumerate(as_completed(future_to_prd), start=1):
            prd_no = future_to_prd[future]
            try:
                prd_no, ok, message = future.result()
            except Exception as e:
                ok = False
                message = f"예외 발생: {e}"

            prefix = f"[{store_name}] [{i}/{total}] prdNo={prd_no}"
            if ok:
                success += 1
                print(f"{prefix} → ✅ {message}")
            else:
                fail += 1
                print(f"{prefix} → ❌ {message}")

    summary = f"{job} 성공 {success} / 실패 {fail} (총 {total}개)"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{store_name}] 완료 → {summary}")

    return row_idx, summary, now


# ================== 메인 (계정 병렬) ==================
def main() -> None:
    sh = gc.open_by_key(SPREADSHEET_KEY)
    ws = sh.worksheet(CONFIG_SHEET_NAME)

    rows = ws.get_all_values()
    jobs: List[Tuple[int, str, str, str]] = []

    # 헤더 제외, 2행부터
    for row_idx, row in enumerate(rows[1:], start=2):
        active = (row[0].strip().upper() if len(row) > 0 else "")
        store_name = (row[1].strip() if len(row) > 1 else "")
        api_key = (row[2].strip() if len(row) > 2 else "")
        job = (row[3].strip() if len(row) > 3 else "")

        if active != "TRUE":
            continue
        if not api_key:
            continue
        if job not in ("판매중지", "판매재개"):
            continue

        jobs.append((row_idx, store_name, api_key, job))

    if not jobs:
        print("[INFO] 처리할 11번가 계정이 없습니다. "
              "(active=TRUE & jobs=판매중지/판매재개 인 행 없음)")
        return

    print(f"[INFO] 계정 병렬 처리 시작 (stores={len(jobs)}, workers={STORE_WORKERS})")

    # 계정 병렬 처리
    with ThreadPoolExecutor(max_workers=STORE_WORKERS) as executor:
        future_to_store = {
            executor.submit(process_store, row_idx, store_name, api_key, job): row_idx
            for (row_idx, store_name, api_key, job) in jobs
        }

        for future in as_completed(future_to_store):
            row_idx = future_to_store[future]
            try:
                r_idx, msg, updated = future.result()
            except Exception as e:
                # 계정 단위 에러
                msg = f"계정 처리 중 예외 발생: {e}"
                updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                r_idx = row_idx

            # 시트 업데이트는 메인 스레드에서만
            ws.update(range_name=f"E{r_idx}:F{r_idx}", values=[[msg, updated]])

    print("[INFO] 모든 11번가 계정 처리 완료")


# ================== 엔트리 포인트 ==================
if __name__ == "__main__":
    main()
