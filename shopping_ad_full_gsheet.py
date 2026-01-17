#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
네이버 쇼핑검색광고 상품소재 자동 등록
- 구글시트에서 스토어 정보 (client_id, client_secret) 로드
- 커머스 API로 상품 목록 + nvmid(네이버쇼핑상품번호) 조회
- SearchAd API로 광고소재 등록

필요 환경변수 (.env):
  SERVICE_ACCOUNT_JSON=서비스계정.json
  SPREADSHEET_KEY=구글시트ID

필요 패키지:
  pip install requests python-dotenv gspread oauth2client bcrypt --break-system-packages
"""

import os
import time
import hmac
import hashlib
import base64
import json
import requests
from typing import Dict, List, Optional, Any

from dotenv import load_dotenv

# bcrypt (커머스 API 인증용)
try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    print("⚠️ bcrypt 미설치. pip install bcrypt --break-system-packages")

# gspread (구글시트용)
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
    print("⚠️ gspread 미설치. pip install gspread oauth2client --break-system-packages")

load_dotenv()

# ============== SearchAd API 인증 정보 ==============
SEARCHAD_API_KEY = os.getenv("SEARCHAD_API_KEY", "0100000000d66d56180a1e02adef67fdfd4c4e3d64531bcc9a5d52648d63fe994beea92637")
SEARCHAD_SECRET_KEY = os.getenv("SEARCHAD_SECRET_KEY", "AQAAAADWbVYYCh4Cre9n/f1MTj1kvaSTtbCoM9RF+wUgLRlfXQ==")
SEARCHAD_CUSTOMER_ID = os.getenv("SEARCHAD_CUSTOMER_ID", "2623436")
SEARCHAD_BASE_URL = "https://api.searchad.naver.com"

# ============== 커머스 API ==============
COMMERCE_API_HOST = "https://api.commerce.naver.com"


# ============================================================
# 구글시트 연동
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
    구글시트 stores 탭에서 스토어 정보 로드
    
    필수 컬럼: store_name, client_id, client_secret
    선택 컬럼: biz_id (비즈채널ID), active
    """
    sh = open_google_sheet(service_account_json, spreadsheet_key)
    
    # stores 시트 찾기
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
        # active 체크 (없으면 기본 True)
        active = str(row.get("active", "TRUE")).strip().upper()
        if active not in ("TRUE", "1", "Y", "YES", "ON", "활성", "사용", ""):
            continue
        
        store_name = str(row.get("store_name", "")).strip()
        client_id = str(row.get("client_id", "")).strip()
        client_secret = str(row.get("client_secret", "")).strip()
        biz_id = str(row.get("biz_id") or row.get("비즈채널id") or row.get("bizchannelid") or "").strip()
        
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
# 커머스 API (스마트스토어)
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


def fetch_channel_product_nos(client_id: str, client_secret: str, 
                               status: str = "SALE", 
                               max_count: int = None) -> List[str]:
    """
    스마트스토어 상품 목록 조회 (channelProductNo)
    
    Returns:
        channelProductNo 목록
    """
    token = get_commerce_token(client_id, client_secret)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    product_nos = []
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
            # channelProducts 배열에서 channelProductNo 추출
            channel_products = item.get("channelProducts") or []
            for cp in channel_products:
                channel_no = cp.get("channelProductNo")
                if channel_no:
                    product_nos.append(str(channel_no))
        
        if max_count and len(product_nos) >= max_count:
            product_nos = product_nos[:max_count]
            break
        
        total = data.get("totalElements", 0)
        if page * page_size >= total:
            break
        
        page += 1
        time.sleep(0.5)  # API 호출 간격 (2/s 제한)
    
    print(f"✓ channelProductNo {len(product_nos)}개 조회 완료")
    return product_nos


def get_nvmid_from_channel_product(client_id: str, client_secret: str, 
                                    channel_product_no: str) -> Optional[str]:
    """
    channelProductNo로 nvmid(네이버쇼핑상품번호) 조회
    
    GET /external/v2/products/channel-products/{channelProductNo}
    → smartstoreChannelProduct.knowledgeShoppingProductId
    """
    token = get_commerce_token(client_id, client_secret)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    
    url = f"{COMMERCE_API_HOST}/external/v2/products/channel-products/{channel_product_no}"
    r = requests.get(url, headers=headers, timeout=30)
    
    if not r.ok:
        return None
    
    data = r.json()
    
    # nvmid 추출 경로들
    nvmid = (
        data.get("smartstoreChannelProduct", {}).get("knowledgeShoppingProductId")
        or data.get("channelProduct", {}).get("knowledgeShoppingProductId")
        or data.get("knowledgeShoppingProductId")
    )
    
    return str(nvmid) if nvmid else None


def fetch_nvmids(client_id: str, client_secret: str, 
                 channel_product_nos: List[str]) -> Dict[str, str]:
    """
    channelProductNo 목록 → nvmid 매핑
    
    Returns:
        {channelProductNo: nvmid} 딕셔너리
    """
    result = {}
    total = len(channel_product_nos)
    
    for i, cp_no in enumerate(channel_product_nos):
        nvmid = get_nvmid_from_channel_product(client_id, client_secret, cp_no)
        if nvmid:
            result[cp_no] = nvmid
        
        if (i + 1) % 10 == 0:
            print(f"  nvmid 조회 중: {i+1}/{total}")
        
        time.sleep(0.5)  # API 호출 간격
    
    print(f"✓ nvmid {len(result)}개 조회 완료 (총 {total}개 중)")
    return result


# ============================================================
# SearchAd API
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
        print(f"[{method}] {path} → {r.status_code}: {r.text[:300]}")
        return None
    
    return r.json() if r.text else {}


def register_shopping_ads(adgroup_id: str, nvmids: List[str], bid_amt: int = 70) -> List[Dict]:
    """
    쇼핑검색광고 상품소재 등록
    
    Args:
        adgroup_id: 광고그룹 ID
        nvmids: 네이버쇼핑상품번호(nvmid) 목록
        bid_amt: 입찰가
    
    Returns:
        등록된 소재 목록
    """
    # 기존 소재 확인
    existing_ads = searchad_api("GET", "/ncc/ads", {"nccAdgroupId": adgroup_id}) or []
    existing_refs = {a.get("referenceKey") for a in existing_ads}
    
    # 새 상품만 필터링
    new_nvmids = [n for n in nvmids if n not in existing_refs]
    
    if not new_nvmids:
        print("모든 상품이 이미 등록되어 있습니다.")
        return []
    
    print(f"등록할 상품: {len(new_nvmids)}개 (기존 {len(existing_refs)}개)")
    
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
            print(f"  배치 {i//batch_size + 1}: {len(result)}개 등록 성공")
        
        time.sleep(0.5)
    
    return all_results


# ============================================================
# 메인 실행
# ============================================================
def main():
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
    
    # 스토어 목록 출력
    print("\n스토어 목록:")
    for i, s in enumerate(stores):
        print(f"  [{i}] {s['name']} (biz_id: {s.get('biz_id', 'N/A')})")
    
    # 2) 대상 스토어 선택 (예: 푸로테카)
    target_store_name = "푸로테카"  # 변경 가능
    store = next((s for s in stores if s['name'] == target_store_name), stores[0])
    print(f"\n[2] 대상 스토어: {store['name']}")
    
    # 3) 커머스 API로 상품 조회
    print("\n[3] 커머스 API로 상품 조회")
    try:
        # channelProductNo 조회
        channel_nos = fetch_channel_product_nos(
            store['client_id'], 
            store['client_secret'],
            max_count=10  # 테스트용 10개
        )
        
        if not channel_nos:
            print("조회된 상품이 없습니다.")
            return
        
        # nvmid 조회
        print("\n[4] nvmid(네이버쇼핑상품번호) 조회")
        nvmid_map = fetch_nvmids(store['client_id'], store['client_secret'], channel_nos)
        
        if not nvmid_map:
            print("nvmid를 조회할 수 없습니다.")
            return
        
        print("\n상품번호 매핑:")
        for cp_no, nvmid in list(nvmid_map.items())[:5]:
            print(f"  channelProductNo: {cp_no} → nvmid: {nvmid}")
        
    except Exception as e:
        print(f"❌ 커머스 API 오류: {e}")
        return
    
    # 4) SearchAd API로 광고그룹 찾기
    print("\n[5] SearchAd API - 캠페인/광고그룹 조회")
    
    campaigns = searchad_api("GET", "/ncc/campaigns") or []
    shopping_camps = [c for c in campaigns if c.get("campaignTp") == "SHOPPING"]
    
    # 스토어명으로 캠페인 찾기
    target_camp = next((c for c in shopping_camps if store['name'] in c.get("name", "")), None)
    
    if not target_camp:
        print(f"'{store['name']}' 캠페인을 찾을 수 없습니다.")
        print("쇼핑 캠페인 목록:")
        for c in shopping_camps[:5]:
            print(f"  - {c['name']}")
        return
    
    print(f"캠페인: {target_camp['name']}")
    
    # 광고그룹 찾기
    groups = searchad_api("GET", "/ncc/adgroups", {"nccCampaignId": target_camp["nccCampaignId"]}) or []
    
    # 비즈채널 연결된 그룹 찾기
    target_group = next((g for g in groups if g.get("nccBusinessChannelId")), None)
    
    if not target_group:
        print("비즈채널이 연결된 광고그룹이 없습니다.")
        return
    
    print(f"광고그룹: {target_group['name']} (bizChannel: {target_group.get('nccBusinessChannelId')})")
    
    # 5) 소재 등록
    print("\n[6] 상품소재 등록")
    nvmids = list(nvmid_map.values())
    
    results = register_shopping_ads(
        adgroup_id=target_group["nccAdgroupId"],
        nvmids=nvmids,
        bid_amt=70
    )
    
    if results:
        print(f"\n✅ 총 {len(results)}개 소재 등록 완료!")
        for ad in results[:5]:
            print(f"  - {ad.get('nccAdId')}: nvmid={ad.get('referenceKey')}")
    else:
        print("\n등록된 소재가 없습니다.")


if __name__ == "__main__":
    main()
