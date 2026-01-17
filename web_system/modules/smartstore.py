"""
스마트스토어 올인원 모듈
- 기존 smartstore_all_in_one_v1_1.py 로직을 웹 서버용으로 재구성
- 작업: 등록갯수, 배송코드, 배송변경, 상품삭제, 중복삭제
"""

import os
import time
import json
import base64
import threading
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime

import requests
import bcrypt
import gspread
from google.oauth2.service_account import Credentials

# ================= 상수/엔드포인트 =================
API_HOST = "https://api.commerce.naver.com"
TOKEN_URL = f"{API_HOST}/external/v1/oauth2/token"
SEARCH_URL = f"{API_HOST}/external/v1/products/search"
ORIGIN_DELETE_URL_V2 = f"{API_HOST}/external/v2/products/origin-products"
BULK_UPDATE_URL = f"{API_HOST}/external/v1/products/origin-products/bulk-update"
ADDR_PAGED = f"{API_HOST}/external/v1/seller/addressbooks-for-page"
ADDR_LIST = f"{API_HOST}/external/v1/seller/addressbooks"

REQUEST_TIMEOUT = 40
HTTP_SESSION = requests.Session()

# 중단 이벤트
STOP_EVENT = threading.Event()


def now_kr() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ================= 토큰 발급 =================
def get_access_token(client_id: str, client_secret: str) -> str:
    """스마트스토어 API 토큰 발급"""
    timestamp = str(int(time.time() * 1000))
    pwd = f"{client_id}_{timestamp}"
    hashed = bcrypt.hashpw(pwd.encode(), client_secret.encode())
    signature = base64.b64encode(hashed).decode()
    
    data = {
        "client_id": client_id,
        "timestamp": timestamp,
        "grant_type": "client_credentials",
        "client_secret_sign": signature,
        "type": "SELF"
    }
    
    r = HTTP_SESSION.post(TOKEN_URL, data=data, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()["access_token"]


def auth_headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }


# ================= 상품수량 조회 =================
def fetch_product_counts(access_token: str) -> Dict[str, int]:
    """상품수량 조회 (전체, 판매중, 판매중지, 승인대기)"""
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
    
    return {
        "전체": total_elements({}),
        "판매중": count_by_status("SALE"),
        "판매중지": count_by_status("SUSPENSION"),
        "승인대기": count_by_status("WAIT")
    }


# ================= 배송코드 조회 =================
def fetch_delivery_codes(access_token: str) -> Dict[str, Optional[int]]:
    """배송코드 조회 (국내출고지, 해외출고지, 반품지)"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    result = {"국내출고지": None, "해외출고지": None, "반품지": None}
    
    # 페이지 API 먼저 시도
    try:
        r = HTTP_SESSION.get(ADDR_PAGED, headers=headers, params={"page": 1, "size": 100}, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            items = data.get("contents") or data.get("addressBooks") or []
            for item in items:
                addr_type = item.get("addressType", "")
                addr_id = item.get("id") or item.get("addressBookId")
                if addr_type == "DISPATCH" and result["국내출고지"] is None:
                    result["국내출고지"] = addr_id
                elif addr_type == "GLOBAL_DISPATCH" and result["해외출고지"] is None:
                    result["해외출고지"] = addr_id
                elif addr_type == "RETURN" and result["반품지"] is None:
                    result["반품지"] = addr_id
    except Exception:
        pass
    
    # 리스트 API fallback
    if not any(result.values()):
        try:
            r = HTTP_SESSION.get(ADDR_LIST, headers=headers, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                items = r.json() if isinstance(r.json(), list) else r.json().get("addressBooks", [])
                for item in items:
                    addr_type = item.get("addressType", "")
                    addr_id = item.get("id") or item.get("addressBookId")
                    if addr_type == "DISPATCH" and result["국내출고지"] is None:
                        result["국내출고지"] = addr_id
                    elif addr_type == "GLOBAL_DISPATCH" and result["해외출고지"] is None:
                        result["해외출고지"] = addr_id
                    elif addr_type == "RETURN" and result["반품지"] is None:
                        result["반품지"] = addr_id
        except Exception:
            pass
    
    return result


# ================= 배송정보 변경 =================
def change_delivery_info(
    access_token: str,
    delivery_attribute_type: str,  # "NORMAL" or "TODAY"
    delivery_fee_type: str,  # "FREE", "CONDITIONAL_FREE", "PAID" 등
    base_fee: int = 0,
    free_threshold: Optional[int] = None,
    log_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """배송정보 일괄 변경"""
    headers = auth_headers(access_token)
    
    def log(msg):
        if log_callback:
            log_callback(msg)
        print(msg)
    
    # 1) 전체 상품 조회
    all_origin_nos = []
    page = 1
    while True:
        if STOP_EVENT.is_set():
            return {"success": False, "message": "중단됨"}
        
        body = {"page": page, "size": 100}
        r = HTTP_SESSION.post(SEARCH_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        
        contents = data.get("contents") or []
        for item in contents:
            origin_no = item.get("originProductNo")
            if origin_no:
                all_origin_nos.append(origin_no)
        
        total_pages = data.get("totalPages", 1)
        log(f"[배송변경] 페이지 {page}/{total_pages} - {len(contents)}개 수집")
        
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.2)
    
    if not all_origin_nos:
        return {"success": True, "message": "변경할 상품 없음", "updated": 0}
    
    log(f"[배송변경] 총 {len(all_origin_nos)}개 상품 변경 시작")
    
    # 2) 배송 정보 구성
    delivery_info = {
        "deliveryAttributeType": delivery_attribute_type,
        "deliveryFee": {
            "deliveryFeeType": delivery_fee_type,
            "baseFee": base_fee
        }
    }
    if free_threshold and delivery_fee_type == "CONDITIONAL_FREE":
        delivery_info["deliveryFee"]["freeConditionalAmount"] = free_threshold
    
    # 3) 일괄 업데이트 (100개씩)
    success_count = 0
    fail_count = 0
    
    for i in range(0, len(all_origin_nos), 100):
        if STOP_EVENT.is_set():
            return {"success": False, "message": "중단됨", "updated": success_count}
        
        batch = all_origin_nos[i:i+100]
        
        update_body = {
            "originProducts": [
                {
                    "originProductNo": ono,
                    "deliveryInfo": delivery_info
                }
                for ono in batch
            ]
        }
        
        try:
            r = HTTP_SESSION.put(BULK_UPDATE_URL, headers=headers, json=update_body, timeout=60)
            if r.status_code == 200:
                success_count += len(batch)
            else:
                fail_count += len(batch)
                log(f"[배송변경] 실패: {r.status_code} - {r.text[:200]}")
        except Exception as e:
            fail_count += len(batch)
            log(f"[배송변경] 오류: {e}")
        
        log(f"[배송변경] 진행: {min(i+100, len(all_origin_nos))}/{len(all_origin_nos)}")
        time.sleep(0.3)
    
    return {
        "success": True,
        "message": f"완료: 성공 {success_count}, 실패 {fail_count}",
        "updated": success_count
    }


# ================= 상품 삭제 =================
def delete_products(
    access_token: str,
    filters: Optional[Dict] = None,
    exclude_codes: Optional[set] = None,
    log_callback: Optional[Callable] = None,
    progress_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """조건에 맞는 상품 삭제"""
    headers = auth_headers(access_token)
    exclude_codes = exclude_codes or set()
    
    def log(msg):
        if log_callback:
            log_callback(msg)
        print(msg)
    
    def progress(current, total):
        if progress_callback:
            progress_callback(current, total)
    
    # 1) 삭제 대상 상품 조회
    target_products = []
    page = 1
    
    while True:
        if STOP_EVENT.is_set():
            return {"success": False, "message": "중단됨"}
        
        body = {"page": page, "size": 100}
        if filters:
            body.update(filters)
        
        r = HTTP_SESSION.post(SEARCH_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        
        contents = data.get("contents") or []
        for item in contents:
            origin_no = item.get("originProductNo")
            seller_code = item.get("sellerManagementCode") or ""
            
            # 삭제금지 코드 제외
            if seller_code in exclude_codes:
                continue
            
            if origin_no:
                target_products.append(origin_no)
        
        total_pages = data.get("totalPages", 1)
        log(f"[상품삭제] 페이지 {page}/{total_pages} 수집")
        
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.2)
    
    if not target_products:
        return {"success": True, "message": "삭제할 상품 없음", "deleted": 0}
    
    log(f"[상품삭제] 총 {len(target_products)}개 삭제 시작")
    
    # 2) 삭제 실행 (100개씩)
    deleted = 0
    failed = 0
    
    for i in range(0, len(target_products), 100):
        if STOP_EVENT.is_set():
            return {"success": False, "message": "중단됨", "deleted": deleted}
        
        batch = target_products[i:i+100]
        batch_str = ",".join(str(x) for x in batch)
        
        try:
            url = f"{ORIGIN_DELETE_URL_V2}?originProductNos={batch_str}"
            r = HTTP_SESSION.delete(url, headers=headers, timeout=60)
            
            if r.status_code == 200:
                deleted += len(batch)
            else:
                failed += len(batch)
                log(f"[상품삭제] 실패: {r.status_code}")
        except Exception as e:
            failed += len(batch)
            log(f"[상품삭제] 오류: {e}")
        
        # 진행률 업데이트 (매 배치마다)
        current_count = min(i+100, len(target_products))
        progress(current_count, len(target_products))
        
        # 로그는 그대로
        log(f"[상품삭제] 진행: {current_count}/{len(target_products)}")
        time.sleep(0.5)
    
    return {
        "success": True,
        "message": f"완료: 삭제 {deleted}, 실패 {failed}",
        "deleted": deleted
    }


# ================= 중복 상품 삭제 =================
def delete_duplicate_products(
    access_token: str,
    exclude_codes: Optional[set] = None,
    log_callback: Optional[Callable] = None,
    progress_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """중복 상품 삭제 (동일 판매자상품코드 중 최신 1개만 유지)"""
    headers = auth_headers(access_token)
    exclude_codes = exclude_codes or set()
    
    def log(msg):
        if log_callback:
            log_callback(msg)
        print(msg)
    
    def progress(current, total):
        if progress_callback:
            progress_callback(current, total)
    
    # 1) 전체 상품 조회
    products = {}  # seller_code -> [(origin_no, created_at), ...]
    page = 1
    
    while True:
        if STOP_EVENT.is_set():
            return {"success": False, "message": "중단됨"}
        
        body = {"page": page, "size": 100}
        r = HTTP_SESSION.post(SEARCH_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        
        contents = data.get("contents") or []
        for item in contents:
            origin_no = item.get("originProductNo")
            seller_code = item.get("sellerManagementCode") or ""
            created_at = item.get("createdAt") or ""
            
            if not seller_code or not origin_no:
                continue
            
            if seller_code not in products:
                products[seller_code] = []
            products[seller_code].append((origin_no, created_at))
        
        total_pages = data.get("totalPages", 1)
        log(f"[중복삭제] 페이지 {page}/{total_pages} 수집")
        
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.2)
    
    # 2) 중복 찾기 (동일 판매자코드 2개 이상)
    duplicates_to_delete = []
    
    for seller_code, items in products.items():
        if len(items) < 2:
            continue
        
        # 삭제금지 코드 제외
        if seller_code in exclude_codes:
            continue
        
        # 최신순 정렬, 첫 번째(최신) 제외하고 나머지 삭제
        sorted_items = sorted(items, key=lambda x: x[1], reverse=True)
        for origin_no, _ in sorted_items[1:]:
            duplicates_to_delete.append(origin_no)
    
    if not duplicates_to_delete:
        return {"success": True, "message": "중복 상품 없음", "deleted": 0}
    
    log(f"[중복삭제] 총 {len(duplicates_to_delete)}개 중복 삭제 시작")
    
    # 3) 삭제 실행
    deleted = 0
    failed = 0
    
    for i in range(0, len(duplicates_to_delete), 100):
        if STOP_EVENT.is_set():
            return {"success": False, "message": "중단됨", "deleted": deleted}
        
        batch = duplicates_to_delete[i:i+100]
        batch_str = ",".join(str(x) for x in batch)
        
        try:
            url = f"{ORIGIN_DELETE_URL_V2}?originProductNos={batch_str}"
            r = HTTP_SESSION.delete(url, headers=headers, timeout=60)
            
            if r.status_code == 200:
                deleted += len(batch)
            else:
                failed += len(batch)
        except Exception as e:
            failed += len(batch)
            log(f"[중복삭제] 오류: {e}")
        
        # 진행률 업데이트 (매 배치마다)
        current_count = min(i+100, len(duplicates_to_delete))
        progress(current_count, len(duplicates_to_delete))
        
        # 로그는 그대로
        log(f"[중복삭제] 진행: {current_count}/{len(duplicates_to_delete)}")
        time.sleep(0.5)
    
    return {
        "success": True,
        "message": f"완료: 삭제 {deleted}, 실패 {failed}",
        "deleted": deleted
    }


# ================= 구글시트 기록 =================
def save_to_sheet(
    gsheet_client,
    sheet_name: str,
    store_name: str,
    data: Dict[str, Any],
    headers: List[str]
) -> bool:
    """구글시트에 결과 기록"""
    try:
        try:
            ws = gsheet_client.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            ws = gsheet_client.add_worksheet(title=sheet_name, rows=200, cols=len(headers))
            ws.update(range_name="1:1", values=[headers], value_input_option="RAW")
        
        all_vals = ws.get_all_values() or []
        if not all_vals:
            ws.update(range_name="1:1", values=[headers], value_input_option="RAW")
            all_vals = [headers]
        
        sheet_headers = all_vals[0] if all_vals else headers
        
        # 스토어명 컬럼 찾기 (한글/영어 둘 다 지원)
        store_col_idx = None
        for idx, h in enumerate(sheet_headers):
            if h in ["store_name", "스토어명"]:
                store_col_idx = idx
                break
        
        if store_col_idx is None:
            print(f"[ERROR] {sheet_name} 시트에 store_name 또는 스토어명 컬럼 없음")
            return
            
        row_map = {}
        for i, row in enumerate(all_vals[1:], start=2):
            if len(row) > store_col_idx and row[store_col_idx]:
                row_map[row[store_col_idx]] = i
        
        # 데이터 준비 (시트에 있는 실제 헤더 키 사용)
        store_header_key = sheet_headers[store_col_idx]
        data[store_header_key] = store_name
        data["updated_at"] = now_kr()
        row_to_write = [data.get(h, "") for h in sheet_headers]
        
        # 기록
        target_row = row_map.get(store_name)
        if target_row is None:
            ws.append_row(row_to_write, value_input_option="RAW")
        else:
            def col_letter(n):
                result = ""
                while n > 0:
                    n, remainder = divmod(n - 1, 26)
                    result = chr(65 + remainder) + result
                return result
            
            end_col = col_letter(len(sheet_headers))
            rng = f"A{target_row}:{end_col}{target_row}"
            ws.update(range_name=rng, values=[row_to_write], value_input_option="RAW")
        
        return True
    except Exception as e:
        print(f"[시트기록] 오류: {e}")
        return False


# ================= 메인 실행 함수 =================
def run_task(
    task: str,
    store_name: str,
    client_id: str,
    client_secret: str,
    gsheet_client=None,
    options: Optional[Dict] = None,
    log_callback: Optional[Callable] = None,
    progress_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    작업 실행
    - task: 등록갯수, 배송코드, 배송변경, 상품삭제, 중복삭제
    """
    options = options or {}
    
    def log(msg):
        if log_callback:
            log_callback(msg)
        print(f"[{store_name}] {msg}")
    
    try:
        # 토큰 발급
        log("토큰 발급 중...")
        token = get_access_token(client_id, client_secret)
        log("토큰 발급 성공")
        
        if task == "등록갯수":
            counts = fetch_product_counts(token)
            log(f"결과: 전체={counts['전체']}, 판매중={counts['판매중']}, 중지={counts['판매중지']}, 대기={counts['승인대기']}")
            
            if gsheet_client:
                save_to_sheet(
                    gsheet_client, "등록갯수", store_name, counts,
                    ["store_name", "전체", "판매중", "판매중지", "승인대기", "updated_at"]
                )
            
            return {"success": True, "data": counts}
        
        elif task == "배송코드":
            codes = fetch_delivery_codes(token)
            log(f"결과: {codes}")
            
            if gsheet_client:
                save_to_sheet(
                    gsheet_client, "배송코드", store_name, codes,
                    ["store_name", "국내출고지", "해외출고지", "반품지", "updated_at"]
                )
            
            return {"success": True, "data": codes}
        
        elif task == "배송변경":
            result = change_delivery_info(
                token,
                delivery_attribute_type=options.get("delivery_type", "NORMAL"),
                delivery_fee_type=options.get("fee_type", "PAID"),
                base_fee=options.get("base_fee", 3000),
                free_threshold=options.get("free_threshold"),
                log_callback=log
            )
            return result
        
        elif task == "상품삭제":
            result = delete_products(
                token,
                filters=options.get("filters"),
                exclude_codes=options.get("exclude_codes"),
                log_callback=log,
                progress_callback=progress_callback
            )
            return result
        
        elif task == "중복삭제":
            result = delete_duplicate_products(
                token,
                exclude_codes=options.get("exclude_codes"),
                log_callback=log,
                progress_callback=progress_callback
            )
            return result
        
        else:
            return {"success": False, "message": f"알 수 없는 작업: {task}"}
    
    except Exception as e:
        log(f"오류: {e}")
        return {"success": False, "message": str(e)}


def stop_all():
    """모든 작업 중단"""
    STOP_EVENT.set()


def reset_stop():
    """중단 플래그 리셋"""
    STOP_EVENT.clear()
