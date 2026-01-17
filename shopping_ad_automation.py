#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
네이버 쇼핑검색광고 상품소재 자동 등록 (v2)

플로우:
  1. 구글시트에서 스토어 정보 로드 (client_id, client_secret)
  2. 커머스 API로 상품 목록 조회 (channelProductNo + 상품명)
  3. 네이버 쇼핑 검색 API로 nvmid 조회 (상품명 → productId)
  4. SearchAd API로 광고소재 등록

필요 환경변수 (.env):
  # 구글시트
  SERVICE_ACCOUNT_JSON=서비스계정.json
  SPREADSHEET_KEY=구글시트ID
  
  # 네이버 검색 API (developers.naver.com)
  NAVER_CLIENT_ID=xxx
  NAVER_CLIENT_SECRET=xxx
  
  # SearchAd API (검색광고)
  SEARCHAD_API_KEY=xxx
  SEARCHAD_SECRET_KEY=xxx
  SEARCHAD_CUSTOMER_ID=xxx

필요 패키지:
  pip install requests python-dotenv gspread oauth2client bcrypt
"""

import os
import re
import time
import hmac
import hashlib
import base64
import json
import requests
from typing import Dict, List, Optional, Any, Tuple

from dotenv import load_dotenv

# bcrypt (커머스 API 인증용)
try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    print("⚠️ bcrypt 미설치. pip install bcrypt")

# gspread (구글시트용)
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
    print("⚠️ gspread 미설치. pip install gspread oauth2client")

load_dotenv()


# ============================================================
# 설정
# ============================================================

# 네이버 검색 API (developers.naver.com)
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "wLJxa2pupN4FLzJXx5uv")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "HpZRVLTOTl")

# SearchAd API (검색광고)
SEARCHAD_API_KEY = os.getenv("SEARCHAD_API_KEY", "0100000000d66d56180a1e02adef67fdfd4c4e3d64531bcc9a5d52648d63fe994beea92637")
SEARCHAD_SECRET_KEY = os.getenv("SEARCHAD_SECRET_KEY", "AQAAAADWbVYYCh4Cre9n/f1MTj1kvaSTtbCoM9RF+wUgLRlfXQ==")
SEARCHAD_CUSTOMER_ID = os.getenv("SEARCHAD_CUSTOMER_ID", "2623436")
SEARCHAD_BASE_URL = "https://api.searchad.naver.com"

# 커머스 API
COMMERCE_API_HOST = "https://api.commerce.naver.com"


# ============================================================
# 1. 구글시트 연동
# ============================================================
def open_google_sheet(service_account_json: str = None, spreadsheet_key: str = None):
    """구글시트 열기"""
    if not GSPREAD_AVAILABLE:
        raise RuntimeError("gspread 패키지가 설치되지 않았습니다.")
    
    sa_json = service_account_json or os.getenv("SERVICE_ACCOUNT_JSON")
    sheet_key = spreadsheet_key or os.getenv("SPREADSHEET_KEY")
    
    if not sa_json or not sheet_key:
        raise RuntimeError("환경변수 SERVICE_ACCOUNT_JSON / SPREADSHEET_KEY 필요")
    
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(sa_json, scope)
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_key)


def load_stores_from_gsheet(service_account_json: str = None, 
                            spreadsheet_key: str = None,
                            sheet_name: str = "stores") -> List[Dict[str, Any]]:
    """
    구글시트에서 스토어 정보 로드
    
    필수 컬럼: store_name, client_id, client_secret
    선택 컬럼: biz_id, active
    """
    sh = open_google_sheet(service_account_json, spreadsheet_key)
    
    ws = None
    for name in (sheet_name, "stores", "store", "스토어"):
        try:
            ws = sh.worksheet(name)
            break
        except gspread.WorksheetNotFound:
            continue
    
    if ws is None:
        raise RuntimeError(f"'{sheet_name}' 시트를 찾을 수 없습니다.")
    
    rows = ws.get_all_records()
    stores = []
    
    for row in rows:
        active = str(row.get("active", "TRUE")).strip().upper()
        if active not in ("TRUE", "1", "Y", "YES", "ON", "활성", "사용", ""):
            continue
        
        store_name = str(row.get("store_name", "")).strip()
        client_id = str(row.get("client_id", "")).strip()
        client_secret = str(row.get("client_secret", "")).strip()
        biz_id = str(row.get("biz_id") or row.get("비즈채널id") or "").strip()
        
        if store_name and client_id and client_secret:
            stores.append({
                "name": store_name,
                "client_id": client_id,
                "client_secret": client_secret,
                "biz_id": biz_id,
            })
    
    print(f"✓ 구글시트에서 {len(stores)}개 스토어 로드")
    return stores


# ============================================================
# 2. 커머스 API (스마트스토어)
# ============================================================
def sign_commerce_secret(client_id: str, client_secret: str, ts_ms: int) -> str:
    """커머스 API 서명 생성 (bcrypt)"""
    if not BCRYPT_AVAILABLE:
        raise RuntimeError("bcrypt 패키지가 설치되지 않았습니다.")
    
    pwd = f"{client_id}_{ts_ms}".encode("utf-8")
    hashed = bcrypt.hashpw(pwd, client_secret.strip().encode("utf-8"))
    return base64.b64encode(hashed).decode("utf-8")


def get_commerce_token(client_id: str, client_secret: str) -> str:
    """커머스 API 액세스 토큰 발급"""
    ts = int(time.time() * 1000)
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "timestamp": ts,
        "client_secret_sign": sign_commerce_secret(client_id, client_secret, ts),
        "type": "SELF",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    
    r = requests.post(f"{COMMERCE_API_HOST}/external/v1/oauth2/token", data=data, headers=headers, timeout=30)
    if r.status_code == 403:
        raise RuntimeError("403 Forbidden: 허용 IP/권한/스코프 확인 필요")
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_products_with_names(client_id: str, client_secret: str, 
                              status: str = "SALE", 
                              max_count: int = None) -> List[Dict[str, str]]:
    """
    스마트스토어 상품 목록 조회 (channelProductNo + 상품명)
    
    Returns:
        [{"channelProductNo": "xxx", "name": "상품명"}, ...]
    """
    token = get_commerce_token(client_id, client_secret)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    products = []
    page = 1
    page_size = 100
    
    while True:
        body = {
            "page": page,
            "size": page_size,
            "productStatusTypes": [status]
        }
        
        r = requests.post(f"{COMMERCE_API_HOST}/external/v1/products/search", 
                         headers=headers, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        
        contents = data.get("contents") or []
        if not contents:
            break
        
        for item in contents:
            product_name = item.get("name", "")
            channel_products = item.get("channelProducts") or []
            
            for cp in channel_products:
                channel_no = cp.get("channelProductNo")
                if channel_no:
                    products.append({
                        "channelProductNo": str(channel_no),
                        "name": product_name
                    })
        
        if max_count and len(products) >= max_count:
            products = products[:max_count]
            break
        
        total = data.get("totalElements", 0)
        if page * page_size >= total:
            break
        
        page += 1
        time.sleep(0.5)
    
    print(f"✓ 상품 {len(products)}개 조회 완료")
    return products


# ============================================================
# 3. 네이버 쇼핑 검색 API (nvmid 조회)
# ============================================================
def search_naver_shopping(query: str, display: int = 10) -> Optional[Dict]:
    """
    네이버 쇼핑 검색 API 호출
    
    Args:
        query: 검색어 (상품명)
        display: 결과 개수 (최대 100)
    
    Returns:
        검색 결과 JSON
    """
    url = "https://openapi.naver.com/v1/search/shop.json"
    
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    
    params = {
        "query": query,
        "display": display,
        "sort": "sim"  # 정확도순
    }
    
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"  검색 API 오류: {r.status_code}")
            return None
    except Exception as e:
        print(f"  검색 API 예외: {e}")
        return None


def find_nvmid_by_product_name(product_name: str, store_name: str = None) -> Optional[str]:
    """
    상품명으로 nvmid(productId) 찾기
    
    Args:
        product_name: 상품명
        store_name: 스토어명 (선택, 판매처 필터링용)
    
    Returns:
        nvmid (productId) 또는 None
    """
    result = search_naver_shopping(product_name, display=20)
    
    if not result:
        return None
    
    items = result.get("items", [])
    
    for item in items:
        mall_name = item.get("mallName", "")
        product_id = item.get("productId")
        
        # 스토어명으로 필터링 (선택)
        if store_name:
            if store_name.lower() in mall_name.lower():
                return product_id
        else:
            # 첫 번째 결과 반환
            return product_id
    
    # 스토어명 필터링 실패 시 첫 번째 결과 반환
    if items:
        return items[0].get("productId")
    
    return None


def fetch_nvmids_via_search(products: List[Dict[str, str]], 
                            store_name: str = None,
                            delay: float = 0.2) -> Dict[str, str]:
    """
    상품 목록에서 nvmid 조회 (네이버 쇼핑 검색 API 사용)
    
    Args:
        products: [{"channelProductNo": "xxx", "name": "상품명"}, ...]
        store_name: 스토어명 (필터링용)
        delay: API 호출 간격 (초)
    
    Returns:
        {channelProductNo: nvmid} 딕셔너리
    """
    result = {}
    total = len(products)
    
    print(f"\nnvmid 조회 시작 (총 {total}개)...")
    
    for i, prod in enumerate(products):
        cp_no = prod["channelProductNo"]
        name = prod["name"]
        
        nvmid = find_nvmid_by_product_name(name, store_name)
        
        if nvmid:
            result[cp_no] = nvmid
            status = "✓"
        else:
            status = "✗"
        
        # 진행률 출력
        if (i + 1) % 5 == 0 or i == total - 1:
            print(f"  [{i+1}/{total}] {status} {name[:30]}... → {nvmid or 'N/A'}")
        
        time.sleep(delay)
    
    print(f"\n✓ nvmid {len(result)}개 조회 완료 (총 {total}개 중)")
    return result


# ============================================================
# 4. SearchAd API (검색광고)
# ============================================================
def searchad_sign(ts: str, method: str, path: str) -> str:
    """SearchAd API 서명 생성"""
    msg = f"{ts}.{method}.{path}"
    return base64.b64encode(
        hmac.new(SEARCHAD_SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()


def searchad_api(method: str, path: str, params: Dict = None, body: Any = None) -> Any:
    """SearchAd API 요청"""
    ts = str(int(time.time() * 1000))
    headers = {
        "X-Timestamp": ts,
        "X-API-KEY": SEARCHAD_API_KEY,
        "X-Signature": searchad_sign(ts, method, path),
        "X-Customer": SEARCHAD_CUSTOMER_ID,
        "Content-Type": "application/json; charset=UTF-8",
    }
    
    r = requests.request(method, SEARCHAD_BASE_URL + path, 
                        headers=headers, params=params, json=body, timeout=30)
    
    if not r.ok:
        print(f"  [{method}] {path} → {r.status_code}: {r.text[:200]}")
        return None
    
    return r.json() if r.text else {}


def get_shopping_campaigns() -> List[Dict]:
    """쇼핑 캠페인 목록 조회"""
    campaigns = searchad_api("GET", "/ncc/campaigns") or []
    return [c for c in campaigns if c.get("campaignTp") == "SHOPPING"]


def get_adgroups(campaign_id: str) -> List[Dict]:
    """광고그룹 목록 조회"""
    return searchad_api("GET", "/ncc/adgroups", {"nccCampaignId": campaign_id}) or []


def get_existing_ads(adgroup_id: str) -> List[Dict]:
    """기존 광고소재 조회"""
    return searchad_api("GET", "/ncc/ads", {"nccAdgroupId": adgroup_id}) or []


def register_shopping_ads(adgroup_id: str, nvmids: List[str], bid_amt: int = 70) -> List[Dict]:
    """
    쇼핑검색광고 상품소재 등록
    
    Args:
        adgroup_id: 광고그룹 ID
        nvmids: nvmid 목록
        bid_amt: 입찰가
    
    Returns:
        등록된 소재 목록
    """
    # 기존 소재 확인
    existing_ads = get_existing_ads(adgroup_id)
    existing_refs = {a.get("referenceKey") for a in existing_ads}
    
    # 새 상품만 필터링
    new_nvmids = [n for n in nvmids if n not in existing_refs]
    
    if not new_nvmids:
        print("  모든 상품이 이미 등록되어 있습니다.")
        return []
    
    print(f"  등록할 상품: {len(new_nvmids)}개 (기존 {len(existing_refs)}개)")
    
    # 소재 등록 (100개씩 배치)
    all_results = []
    batch_size = 100
    
    for i in range(0, len(new_nvmids), batch_size):
        batch = new_nvmids[i:i+batch_size]
        
        payload = [{
            "nccAdgroupId": adgroup_id,
            "type": "SHOPPING_PRODUCT_AD",
            "referenceKey": nvmid,  # ★ nvmid 사용
            "ad": {},
            "adAttr": {"bidAmt": bid_amt, "useGroupBidAmt": False},
        } for nvmid in batch]
        
        result = searchad_api("POST", "/ncc/ads", {"isList": "true"}, payload)
        
        if result:
            all_results.extend(result)
            print(f"    배치 {i//batch_size + 1}: {len(result)}개 등록 성공")
        
        time.sleep(0.5)
    
    return all_results


# ============================================================
# 메인 실행
# ============================================================
def run_automation(store_name: str = None, 
                   max_products: int = 10,
                   bid_amt: int = 70,
                   dry_run: bool = False):
    """
    자동화 실행
    
    Args:
        store_name: 대상 스토어명 (None이면 첫 번째 스토어)
        max_products: 최대 상품 수
        bid_amt: 입찰가
        dry_run: True면 등록하지 않고 조회만
    """
    print("=" * 60)
    print("네이버 쇼핑검색광고 상품소재 자동 등록")
    print("=" * 60)
    
    # 1) 구글시트에서 스토어 정보 로드
    print("\n[1] 구글시트에서 스토어 정보 로드")
    try:
        stores = load_stores_from_gsheet()
    except Exception as e:
        print(f"❌ 구글시트 로드 실패: {e}")
        return
    
    if not stores:
        print("등록된 스토어가 없습니다.")
        return
    
    # 스토어 선택
    if store_name:
        store = next((s for s in stores if s['name'] == store_name), None)
        if not store:
            print(f"'{store_name}' 스토어를 찾을 수 없습니다.")
            return
    else:
        store = stores[0]
    
    print(f"  대상 스토어: {store['name']}")
    
    # 2) 커머스 API로 상품 조회
    print("\n[2] 커머스 API로 상품 조회")
    try:
        products = fetch_products_with_names(
            store['client_id'], 
            store['client_secret'],
            max_count=max_products
        )
        
        if not products:
            print("조회된 상품이 없습니다.")
            return
            
    except Exception as e:
        print(f"❌ 커머스 API 오류: {e}")
        return
    
    # 3) 네이버 쇼핑 검색 API로 nvmid 조회
    print("\n[3] 네이버 쇼핑 검색 API로 nvmid 조회")
    nvmid_map = fetch_nvmids_via_search(products, store_name=store['name'])
    
    if not nvmid_map:
        print("nvmid를 조회할 수 없습니다.")
        return
    
    print("\n상품번호 매핑 (상위 5개):")
    for i, (cp_no, nvmid) in enumerate(list(nvmid_map.items())[:5]):
        prod_name = next((p['name'] for p in products if p['channelProductNo'] == cp_no), "")
        print(f"  {cp_no} → nvmid: {nvmid}")
        print(f"    상품명: {prod_name[:40]}...")
    
    if dry_run:
        print("\n[DRY RUN] 여기서 종료합니다.")
        return
    
    # 4) SearchAd API - 캠페인/광고그룹 조회
    print("\n[4] SearchAd API - 캠페인/광고그룹 조회")
    
    shopping_camps = get_shopping_campaigns()
    
    # 스토어명으로 캠페인 찾기
    target_camp = next((c for c in shopping_camps if store['name'] in c.get("name", "")), None)
    
    if not target_camp:
        print(f"'{store['name']}' 캠페인을 찾을 수 없습니다.")
        print("쇼핑 캠페인 목록:")
        for c in shopping_camps[:5]:
            print(f"  - {c['name']}")
        return
    
    print(f"  캠페인: {target_camp['name']}")
    
    # 광고그룹 찾기
    groups = get_adgroups(target_camp["nccCampaignId"])
    
    # 비즈채널 연결된 그룹 찾기
    target_group = next((g for g in groups if g.get("nccBusinessChannelId")), None)
    
    if not target_group:
        print("비즈채널이 연결된 광고그룹이 없습니다.")
        return
    
    print(f"  광고그룹: {target_group['name']}")
    print(f"  비즈채널: {target_group.get('nccBusinessChannelId')}")
    
    # 5) 소재 등록
    print("\n[5] 상품소재 등록")
    nvmids = list(nvmid_map.values())
    
    results = register_shopping_ads(
        adgroup_id=target_group["nccAdgroupId"],
        nvmids=nvmids,
        bid_amt=bid_amt
    )
    
    if results:
        print(f"\n✅ 총 {len(results)}개 소재 등록 완료!")
        for ad in results[:5]:
            print(f"  - {ad.get('nccAdId')}: nvmid={ad.get('referenceKey')}")
    else:
        print("\n등록된 소재가 없습니다.")


def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description="네이버 쇼핑검색광고 상품소재 자동 등록")
    parser.add_argument("--store", "-s", type=str, help="대상 스토어명")
    parser.add_argument("--max", "-m", type=int, default=10, help="최대 상품 수 (기본: 10)")
    parser.add_argument("--bid", "-b", type=int, default=70, help="입찰가 (기본: 70)")
    parser.add_argument("--dry-run", "-d", action="store_true", help="조회만 하고 등록하지 않음")
    
    args = parser.parse_args()
    
    run_automation(
        store_name=args.store,
        max_products=args.max,
        bid_amt=args.bid,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
