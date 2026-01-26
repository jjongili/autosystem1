# -*- coding: utf-8 -*-
"""
불사자 상품 업로더 v1.6
- 구글시트 설정 화면과 동일한 GUI
- 마켓 그룹 선택 (다중 선택)
- 동시 세션 설정
- 옵션 설정 (개수, 정렬, 필터링)
- 그룹별 마켓 ID 동적 매핑 (v1.2)
- 카테고리 오류 시 ESM 카테고리로 재시도 (v1.3)
- 가격 계산 공식 수정 (불사자 공식 적용, 카드수수료 포함) (v1.6)

by 프코노미
"""

import os
import sys
import time
import threading
import json
import math
import requests
import websocket
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog

# 공통 모듈 (미끼 옵션 필터링, 대표옵션 선택, API 클라이언트)
from bulsaja_common import filter_bait_options, DEFAULT_BAIT_KEYWORDS, select_main_option, BulsajaAPIClient as CommonAPIClient, load_bait_keywords

# ==================== 설정 ====================
CONFIG_FILE = "bulsaja_uploader_config.json"
DEBUG_PORT = 9222

# 마켓 ID 매핑
MARKET_IDS = {
    "스마트스토어": 10200,
    "11번가": 10201,
    "G마켓/옥션": 10202,
    "쿠팡": 14516,
}

# 마켓 타입 매핑 (API용)
MARKET_TYPES = {
    "스마트스토어": "SMARTSTORE",
    "11번가": "ST11",
    "G마켓/옥션": "ESM",
    "G마켓": "GMARKET",
    "옥션": "AUCTION",
    "쿠팡": "COUPANG",
}

# 마켓명 약자 (로그용)
MARKET_SHORT = {
    "스마트스토어": "N",
    "11번가": "11",
    "G마켓/옥션": "G|A",
    "G마켓": "G",
    "옥션": "A",
    "쿠팡": "C",
}

# 상품명 처리 옵션
TITLE_OPTIONS = {
    "원마켓 상품명 그대로 사용": "original",
    "앞4개단어제외 셔플": "shuffle_skip4",
    "앞3개단어제외 셔플": "shuffle_skip3",
    "모든단어 셔플": "shuffle_all",
}

# 옵션 정렬 옵션
OPTION_SORT_OPTIONS = {
    "가격낮은순": "price_asc",
    "주요가격대": "price_main",
    "가격높은순": "price_desc",
}

# 업로드 조건 (불사자 상태값: 숫자 또는 텍스트)
UPLOAD_CONDITIONS = {
    "미업로드(수집완료+수정중+검토완료)": ["0", "1", "2", "수집 완료", "수정중", "검토 완료"],
    "수집완료만": ["0", "수집 완료"],
    "수정중만": ["1", "수정중"],
    "검토완료만": ["2", "검토 완료"],
    "업로드완료(판매중)": ["3", "판매중", "업로드 완료"],
    "전체": None,  # 필터 없음
}

# 썸네일 매칭 설정
THUMBNAIL_MATCH_ENABLED = True  # 썸네일 매칭 기반 대표상품 선택 활성화

# 제외 키워드 (옵션 필터링용 - 미끼상품 필터)
# bulsaja_common.py의 load_bait_keywords() 사용
EXCLUDE_KEYWORDS = load_bait_keywords()


# ==================== 설정 파일 관리 ====================
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except:
        return False


# ==================== 가격 계산 ====================
@dataclass
class PriceSettings:
    exchange_rate: float = 210.0
    card_fee_rate: float = 3.3
    margin_rate_min: float = 25.0      # 마진 최소
    margin_rate_max: float = 30.0      # 마진 최대
    margin_fixed: int = 15000
    discount_rate_min: float = 20.0    # 할인율 최소
    discount_rate_max: float = 30.0    # 할인율 최대
    delivery_fee: int = 0              # 해외배송비 (전역 설정)
    round_unit: int = 100
    min_price: int = 20000
    max_price: int = 100000000


import random

def extract_image_id(url: str) -> str:
    """이미지 URL에서 고유 ID 추출 (파일명 또는 마지막 경로)"""
    if not url:
        return ""
    # URL에서 파일명 추출
    # 예: https://img.alicdn.com/.../TB2SzofBb1YBuNjSsze0XablFXa_!!277662934.jpg
    # 예: https://cdn.bulsaja.com/.../thumbnail-image/vu33Fg2KXz8balj2.jpeg
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path
        # 마지막 경로 부분 (파일명)
        filename = path.split('/')[-1] if '/' in path else path
        # 확장자 제거
        name_part = filename.rsplit('.', 1)[0] if '.' in filename else filename
        return name_part
    except:
        return url


def match_thumbnail_to_sku(thumbnails: List[str], skus: List[Dict]) -> Optional[int]:
    """
    대표 썸네일과 매칭되는 SKU 인덱스 찾기
    thumbnails: uploadThumbnails 배열 (첫 번째가 대표 이미지)
    skus: uploadSkus 배열
    Returns: 매칭되는 SKU 인덱스 또는 None
    """
    if not thumbnails or not skus:
        return None

    # 대표 썸네일 ID 추출 (첫 번째 이미지)
    main_thumb_id = extract_image_id(thumbnails[0])
    if not main_thumb_id:
        return None

    # 각 SKU의 이미지와 비교
    for idx, sku in enumerate(skus):
        sku_image_url = sku.get('urlRef') or sku.get('image') or ''
        if not sku_image_url:
            continue

        sku_image_id = extract_image_id(sku_image_url)

        # 이미지 ID가 포함되어 있으면 매칭
        if main_thumb_id in sku_image_id or sku_image_id in main_thumb_id:
            return idx

    # 정확한 매칭이 없으면 URL 도메인+경로 일부로 비교
    main_thumb_url = thumbnails[0].lower()
    for idx, sku in enumerate(skus):
        sku_image_url = (sku.get('urlRef') or sku.get('image') or '').lower()
        if not sku_image_url:
            continue
        # 같은 이미지 서버에서 비슷한 경로면 매칭
        if 'alicdn.com' in main_thumb_url and 'alicdn.com' in sku_image_url:
            # alicdn 이미지끼리 파일명 비교
            main_file = main_thumb_url.split('/')[-1]
            sku_file = sku_image_url.split('/')[-1]
            if main_file == sku_file:
                return idx

    return None


def detect_bait_by_price_cluster(skus: List[Dict], gap_threshold: float = 2.0,
                                   min_cluster_ratio: float = 0.3) -> Tuple[List[str], List[Dict]]:
    """
    가격 클러스터링으로 미끼 옵션 탐지

    로직:
    1. 가격순 정렬 후 인접 가격 차이가 gap_threshold(2배) 이상이면 그룹 분리
    2. 최저가 그룹이 전체의 min_cluster_ratio(30%) 미만이면 미끼로 판단

    Args:
        skus: SKU 리스트
        gap_threshold: 가격 갭 임계값 (기본 2.0 = 2배)
        min_cluster_ratio: 미끼로 판단할 최소 비율 (기본 0.3 = 30%)

    Returns:
        (제거된 SKU ID 리스트, 클러스터 정보 리스트)
    """
    if not skus or len(skus) < 3:
        return [], []

    # 가격이 있는 SKU만 추출
    priced_skus = [(sku, sku.get('_origin_price', 0)) for sku in skus if sku.get('_origin_price', 0) > 0]
    if len(priced_skus) < 3:
        return [], []

    # 가격순 정렬
    priced_skus.sort(key=lambda x: x[1])

    # 클러스터 분리 (가격 갭 기준)
    clusters = []
    current_cluster = [priced_skus[0]]

    for i in range(1, len(priced_skus)):
        prev_price = priced_skus[i-1][1]
        curr_price = priced_skus[i][1]

        # 가격 갭 체크 (이전 가격의 gap_threshold배 이상이면 새 클러스터)
        if prev_price > 0 and curr_price / prev_price >= gap_threshold:
            clusters.append(current_cluster)
            current_cluster = [priced_skus[i]]
        else:
            current_cluster.append(priced_skus[i])

    clusters.append(current_cluster)

    # 클러스터 정보 생성
    cluster_info = []
    for i, cluster in enumerate(clusters):
        prices = [p for _, p in cluster]
        cluster_info.append({
            'index': i,
            'count': len(cluster),
            'min_price': min(prices),
            'max_price': max(prices),
            'avg_price': sum(prices) / len(prices),
            'ratio': len(cluster) / len(priced_skus),
            'sku_ids': [sku.get('id') for sku, _ in cluster]
        })

    # 미끼 판별: 옵션 수가 가장 많은 클러스터만 유지, 나머지는 미끼로 제거
    # 동률일 경우 고가 클러스터 유지 (미끼는 보통 저가)
    bait_ids = []
    if len(clusters) >= 2:
        # 옵션 수 기준 정렬 (많은 순), 동률이면 가격 높은 순
        sorted_clusters = sorted(cluster_info, key=lambda x: (-x['count'], -x['avg_price']))
        main_cluster = sorted_clusters[0]  # 유지할 클러스터

        # 나머지 클러스터는 모두 미끼로 처리
        for cluster in sorted_clusters[1:]:
            bait_ids.extend(cluster['sku_ids'])

    return bait_ids, cluster_info


def shuffle_product_name(name: str, mode: str) -> str:
    """
    상품명 셔플 처리
    mode:
      - "original": 원본 그대로
      - "shuffle_skip4": 앞 4개 단어 제외하고 셔플
      - "shuffle_skip3": 앞 3개 단어 제외하고 셔플
      - "shuffle_all": 전체 셔플
    """
    if mode == "original" or not name:
        return name

    words = name.split()
    if len(words) <= 1:
        return name

    if mode == "shuffle_skip4":
        if len(words) <= 4:
            return name
        prefix = words[:4]
        suffix = words[4:]
        random.shuffle(suffix)
        return ' '.join(prefix + suffix)

    elif mode == "shuffle_skip3":
        if len(words) <= 3:
            return name
        prefix = words[:3]
        suffix = words[3:]
        random.shuffle(suffix)
        return ' '.join(prefix + suffix)

    elif mode == "shuffle_all":
        shuffled = words[:]
        random.shuffle(shuffled)
        return ' '.join(shuffled)

    return name


def calculate_price(origin_price_cny: float, settings: PriceSettings, delivery_fee: int = 0) -> Tuple[int, int, int, float, float]:
    """
    가격 계산 (불사자 공식 기준)
    Args:
        origin_price_cny: 위안 원가
        settings: 가격 설정
        delivery_fee: 해외배송비 (원화, uploadOverseaDeliveryFee)
    Returns: (원화원가, 정상가, 판매가, 적용된 마진율, 적용된 할인율)

    불사자 공식:
    - 원화 원가 = 환율 × 상품원가(CNY)  ← 배송비 미포함!
    - 정상가(origin_price) = 원화원가 + 원화원가 × (카드수수료% + 마진율%) + 정액마진 + 해외배송비
    - 판매가(sale_price) = 정상가 × (1 - 할인율%)
    """
    # 랜덤 마진율
    margin_rate = random.uniform(settings.margin_rate_min, settings.margin_rate_max)
    # 랜덤 할인율
    discount_rate = random.uniform(settings.discount_rate_min, settings.discount_rate_max)

    # 원화 원가 = 환율 × 위안원가 (배송비 미포함!)
    origin_price_krw = origin_price_cny * settings.exchange_rate

    # 정상가 = 원화원가 + 원화원가 × (카드수수료 + 마진율) + 정액마진 + 배송비
    base_price = origin_price_krw + origin_price_krw * (settings.card_fee_rate + margin_rate) / 100 + settings.margin_fixed + delivery_fee
    origin_price = math.ceil(base_price / settings.round_unit) * settings.round_unit

    # 판매가 = 정상가 × (1 - 할인율)
    sale_price = origin_price * (1 - discount_rate / 100)
    sale_price = math.ceil(sale_price / settings.round_unit) * settings.round_unit

    return int(origin_price_krw), int(origin_price), int(sale_price), margin_rate, discount_rate


# ==================== 불사자 API 클라이언트 (CommonAPIClient 상속) ====================
class BulsajaAPIClient(CommonAPIClient):
    """업로더 전용 API 클라이언트 - CommonAPIClient 상속 + 업로드 기능 추가"""

    def __init__(self, access_token: str = "", refresh_token: str = ""):
        super().__init__(access_token, refresh_token)
        # 마켓 그룹명 → 그룹ID 매핑 캐시
        self._market_group_id_map: Dict[str, int] = {}

    def load_market_group_ids(self) -> Dict[str, int]:
        """마켓 그룹 목록 조회 후 name→id 매핑 생성"""
        if self._market_group_id_map:
            return self._market_group_id_map

        groups = self.get_market_groups()
        for g in groups:
            name = g.get('name', '')
            gid = g.get('id')
            if name and gid:
                self._market_group_id_map[name] = gid

        if self._market_group_id_map:
            print(f"[INFO] 마켓그룹 ID 매핑 로드됨: {len(self._market_group_id_map)}개")
        return self._market_group_id_map

    def get_market_group_id(self, group_name: str) -> Optional[int]:
        """그룹명으로 마켓 그룹 ID 조회"""
        if not self._market_group_id_map:
            self.load_market_group_ids()
        return self._market_group_id_map.get(group_name)

    def update_product_fields(self, product_id: str, product_data: Dict) -> Tuple[bool, str]:
        url = f"{self.BASE_URL}/sourcing/uploadfields/{product_id}"
        try:
            response = self.session.put(url, json=product_data)
            response.raise_for_status()

            # 응답 내용 확인
            try:
                result = response.json()
                if isinstance(result, dict):
                    if result.get('error') or result.get('errors'):
                        error_msg = result.get('error') or result.get('errors') or result.get('message', '')
                        return False, f"API 오류: {str(error_msg)[:100]}"
                    if result.get('success') == False:
                        return False, f"실패: {result.get('message', '알 수 없는 오류')[:100]}"
                return True, "성공"
            except:
                return True, "성공"

        except requests.exceptions.HTTPError as e:
            error_detail = ""
            try:
                error_detail = e.response.text[:200]
            except:
                pass
            return False, f"HTTP {e.response.status_code}: {error_detail}"
        except Exception as e:
            return False, f"예외: {str(e)}"

    def get_group_markets(self, group_id: int) -> List[Dict]:
        """그룹 내 마켓 목록 조회"""
        url = f"{self.BASE_URL}/market/group/{group_id}/markets"
        try:
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[ERROR] 그룹 마켓 조회 실패: {e}")
            return []

    def get_market_id_in_group(self, group_name: str, market_name: str) -> Optional[int]:
        """그룹 내 특정 마켓의 ID 조회"""
        # 캐시
        cache_key = (group_name, market_name)
        if not hasattr(self, '_group_market_cache'):
            self._group_market_cache = {}
        if cache_key in self._group_market_cache:
            return self._group_market_cache[cache_key]

        # 그룹 ID 조회
        group_id = self.get_market_group_id(group_name)
        if not group_id:
            return None

        # 그룹 내 마켓 목록 조회
        markets = self.get_group_markets(group_id)
        target_type = MARKET_TYPES.get(market_name, "SMARTSTORE")

        for market in markets:
            if market.get('type') == target_type:
                market_id = market.get('id')
                self._group_market_cache[cache_key] = market_id
                print(f"[INFO] {group_name} → {market_name} 마켓 ID: {market_id}")
                return market_id

        print(f"[WARNING] {group_name}에서 {market_name} 마켓을 찾을 수 없음")
        return None

    def upload_product(self, product_id: str, group_name: str, market_name: str = "스마트스토어", prevent_duplicate: bool = True) -> Tuple[bool, str]:
        """
        상품 업로드
        Args:
            product_id: 불사자 상품 ID
            group_name: 마켓 그룹명 (예: "03_코드리크")
            market_name: 업로드할 마켓 플랫폼명
            prevent_duplicate: 불사자 중복 업로드 방지 (True=활성화)
        """
        # 그룹 내 마켓 ID 조회
        market_id = self.get_market_id_in_group(group_name, market_name)
        if not market_id:
            return False, f"그룹 '{group_name}'에서 '{market_name}' 마켓을 찾을 수 없음"

        market_type = MARKET_TYPES.get(market_name, "SMARTSTORE")

        # 1. 데이터 확보 (순서: uploadfields -> product_detail)
        # upload_fields가 비어있으면 product_detail을 사용하여 필수 필드(uploadBulsajaCode 등) 누락 방지
        base_data = self.get_upload_fields(product_id)
        
        if not base_data:
            # uploadfields가 없으면 상세정보로 대체
            try:
                base_data = self.get_product_detail(product_id)
                if market_name == "쿠팡":
                    print(f"[INFO] uploadfields 조회 실패/비어있음 - 상품상세정보를 베이스 데이터로 사용")
            except Exception as e:
                print(f"[WARNING] 기본 데이터 확보 실패: {e}")
                base_data = {}

        # 2. Notices 추출 및 처리
        notices = base_data.get('uploadNotices') or base_data.get('notices')
        
        # 3. Notices 처리 (쿠팡 강제 재설정 - 성공 페이로드 구조 복제!)
        if market_name == "쿠팡":
            print(f"[INFO] 쿠팡 고시정보 강제 재설정 (성공 페이로드 구조)")
            # 중요: notices는 배열이 아니라 객체!
            # noticeCategoryDetailNames 배열 안에 상세 항목들이 들어감
            notices = {
                "noticeCategoryName": "기타 재화",
                "noticeCategoryDetailNames": [
                    {"noticeCategoryDetailName": "품명 및 모델명", "required": "MANDATORY", "content": "상세페이지 참조"},
                    {"noticeCategoryDetailName": "인증/허가 사항", "required": "MANDATORY", "content": "상세페이지 참조"},
                    {"noticeCategoryDetailName": "제조국(원산지)", "required": "MANDATORY", "content": "상세페이지 참조"},
                    {"noticeCategoryDetailName": "제조자(수입자)", "required": "MANDATORY", "content": "상세페이지 참조"},
                    {"noticeCategoryDetailName": "소비자상담 관련 전화번호", "required": "MANDATORY", "content": "상세페이지 참조"}
                ]
            }
            
            # [추가] 생성된 고시정보를 base_data에 반영 및 서버 저장 시도
            if base_data:
                base_data['uploadNotices'] = notices
                print(f"[INFO] 생성된 고시정보 서버에 저장 시도...")
                success, msg = self.update_product_fields(product_id, base_data)
                if success:
                    print(f"[INFO] 고시정보 서버 저장 성공 (데이터 무결성 확보)")
                    # [재시도] 서버가 고쳐졌으므로 uploadfields를 다시 조회
                    try:
                        retry_fields = self.get_upload_fields(product_id)
                        if retry_fields:
                            print(f"[INFO] 수리된 uploadfields 확보 성공! 이것으로 페이로드 교체")
                            base_data = retry_fields
                            notices = base_data.get('uploadNotices') or base_data.get('notices')
                    except Exception as re:
                        print(f"[WARNING] 재조회 실패: {re}")
                        
        print(f"[DEBUG] v1.3.py (Sanitized Payload Version) - Payload 구성 시작")
        
        # URL 정의 (이전 코드에서 누락된 부분 수정)
        url = f"{self.BASE_URL}/market/{market_id}/upload/"
        print(f"[DEBUG] Upload URL: {url}")
        
        # 4. Payload 구성 (Sanitized Construction)
        # 중요: uploadfields.txt (성공 샘플) 분석 기반으로 화이트리스트 확장
        allowed_keys = [
            # 1. 핵심 식별 및 코드
            "uploadBulsajaCode", "uploadTrackcopyCode", "uploadSelectedMarketGroupId",
            
            # 2. 공통 상품 구성
            "uploadSkus", "uploadSkuProps", "uploadThumbnails", "uploadVideoUrls",
            "uploadDetailContents", "uploadDetail_page", "uploadDelivery",
            "uploadBrand", "uploadCategory", "uploadSmartStoreTags", "uploadCommonTags",
            "uploadCommonProductName", "uploadProductSearchText", "uploadSearchCategory",
            
            # 3. 마켓별 전용 필드
            "uploadCoupangOptionMode", "uploadCoupangProductName", "uploadSmartStoreProductName",
            "uploadContact", "uploadFake_pct",
            
            # 4. 가격 및 환율 설정
            "uploadBase_price", "uploadSetting", "uplaodSetting", # 오타 포함
            "uploadRecentExchangeRate", "uploadOverseaDeliveryFee",
            "card_fee", "raise_digit", "percent_margin", "plus_margin", "discount_rate",
            
            # 5. [신규] 최상위 배치 필드 (성공 샘플 기준 추가)
            "is_tax_free", "maker", "brand", "shipment_date", "minor_limit", 
            "max_purchase_qty", "coupang_thumbnail_mode", "add_first_option_to_smartstore"
        ]

        payload = {
            "productId": product_id,
            "notices": notices,
            "preventDuplicateUpload": prevent_duplicate,
            "removeDuplicateWords": True,
            "targetMarket": market_type,
        }

        if base_data:
            # 디버깅
            print(f"[DEBUG] Base Data Keys: {list(base_data.keys())[:10]}... (Total: {len(base_data)})")
            
            for key in allowed_keys:
                if key in base_data:
                    if base_data[key] is not None:
                         payload[key] = base_data[key]
                
                # [오타 대응] uplaodSetting <-> uploadSetting 상호 보완
                if key == "uploadSetting" and "uplaodSetting" in base_data and "uploadSetting" not in payload:
                    payload["uploadSetting"] = base_data["uplaodSetting"]
                if key == "uplaodSetting" and "uploadSetting" in base_data and "uplaodSetting" not in payload:
                    payload["uplaodSetting"] = base_data["uploadSetting"]

                elif base_data.get('uploadBase_price') and key in base_data['uploadBase_price']:
                     payload[key] = base_data['uploadBase_price'][key]

        # 최종 안전장치: payload에 notices 반드시 포함
        payload['notices'] = notices
        
        # [중요] uploadSetting 강제 생성 (500 방지)
        if 'uploadSetting' not in payload:
            payload['uploadSetting'] = {
                "is_tax_free": False, "coupang_thumbnail_mode": "OPTION_IMAGE", 
                "maker": "", "brand": "", "min_purchase_qty": 0, "max_purchase_qty": 0
            }
        
        # [중요] uploadSetting 내부 필드를 최상위에도 중복 배치 (성공 샘플 구조 복제)
        # uploadfields.txt 분석 결과: uplaodSetting 객체 내부의 모든 필드가 root에도 존재해야 함!
        setting_obj = payload.get('uploadSetting') or payload.get('uplaodSetting') or {}
        if isinstance(setting_obj, dict):
            for key in ['is_tax_free', 'coupang_thumbnail_mode', 'maker', 'brand', 
                        'max_purchase_qty', 'min_purchase_qty', 'minor_limit', 
                        'shipment_date', 'add_first_option_to_smartstore']:
                if key in setting_obj and key not in payload:
                    payload[key] = setting_obj[key]
                    print(f"[DEBUG] uploadSetting.{key} → root 복사: {setting_obj[key]}")
        
        # [신규] Root Level Helper 필드 (uploadfields.txt 골드 스탠다드)
        product_name = base_data.get('productName') or base_data.get('uploadCommonProductName', "상품")
        payload['search'] = product_name
        payload['name'] = product_name
        
        # 디버깅: 최종 페이로드 키 확인
        print(f"[DEBUG] Final Payload Keys: {list(payload.keys())}")
        
        # [중요] 쿠팡 메타 카테고리 정보 조회 및 병합 (사용자 피드백 반영)
        # 스마트스토어와 달리 쿠팡은 카테고리별 메타 정보가 필수일 수 있음
        if market_name == "쿠팡":
            try:
                # 1. Group ID 확인 (기본적으로 market_id는 개별 마켓 ID이므로 그룹 ID 조회 필요)
                # 현재 self.get_market_id_in_group 으로직을 역이용하거나, group_name으로 조회
                group_id = self.get_market_group_id(group_name)
                
                # 2. Category ID 확인 (payload나 base_data에서 추출)
                category_id = None
                
                # 방법 A: categoryList에서 검색 (1차 시도)
                cat_list = base_data.get('categoryList', [])
                if cat_list:
                     for cat in cat_list:
                         if cat.get('id') == 'cp':
                             category_id = cat.get('code')
                             print(f"[DEBUG] categoryList에서 쿠팡 코드 발견: {category_id}")
                             break
                
                # 방법 B: uploadCategory 내에서 검색 (3차 시도 - 가장 유력)
                if not category_id:
                     up_cat = base_data.get('uploadCategory')
                     if up_cat and isinstance(up_cat, dict):
                         # cp_category 객체나 code 필드 확인
                         category_id = up_cat.get('code') or up_cat.get('cp_category', {}).get('code')
                         if category_id:
                             print(f"[DEBUG] uploadCategory에서 쿠팡 코드 발견: {category_id}")

                # 방법 C: cp_category에서 검색 (2차 시도)
                if not category_id:
                     cp_cat = base_data.get('cp_category')
                     if cp_cat and isinstance(cp_cat, dict):
                         category_id = cp_cat.get('code')
                         if category_id:
                             print(f"[DEBUG] cp_category에서 쿠팡 코드 발견: {category_id}")

                # 방법 D: category 문자열/객체에서 검색
                if not category_id:
                    cat = base_data.get('category')
                    if isinstance(cat, dict):
                        category_id = cat.get('code')
                    elif isinstance(cat, (str, int)):
                        category_id = cat

                # 방법 E: uploadSearchCategory에서 검색
                if not category_id:
                     s_cat = base_data.get('uploadSearchCategory')
                     if isinstance(s_cat, dict):
                         category_id = s_cat.get('code')
                         if category_id:
                             print(f"[DEBUG] uploadSearchCategory에서 쿠팡 코드 발견: {category_id}")

                # 방법 F: top-level 'code' 키 확인 (일부 상품 데이터에서는 이게 카테고리 코드임)
                if not category_id:
                    code_val = base_data.get('code')
                    if code_val and str(code_val).isdigit():
                        category_id = code_val
                        print(f"[DEBUG] top-level 'code' 필드에서 쿠팡 코드 발견: {category_id}")

                if not category_id:
                    print(f"[WARNING] 쿠팡 카테고리 코드를 찾을 수 없음! (base_data keys: {list(base_data.keys())})")

                if group_id and category_id:
                    meta_url = f"{self.BASE_URL}/market/group/{group_id}/meta/?categoryId={category_id}"
                    print(f"[INFO] 쿠팡 메타 정보 조회 시도: {meta_url}")
                    meta_res = self.session.get(meta_url)
                    
                    cat_name = base_data.get('category', {}).get('name') if isinstance(base_data.get('category'), dict) else "기타"
                    
                    # [골드 스탠다드] cp_category 및 categoryList를 최상위(Root)에 배치
                    payload['code'] = str(category_id)
                    payload['cp_category'] = {"name": cat_name, "code": str(category_id)}
                    
                    # categoryList에 additional(필수 옵션 정보) 포함 (성공 샘플 복제)
                    category_list_item = {
                        "id": "cp", 
                        "code": str(category_id), 
                        "name": cat_name, 
                        "needCert": False,
                        "additional": {
                            "mandatoryType": "NUMBER",
                            "addPrice": True,
                            "requiredOptions": 1,
                            "mandatoryOption": "수량"
                        }
                    }
                    payload['categoryList'] = [category_list_item]
                    
                    # [중요] uploadCategory 내부에도 cp_category와 categoryList 중복 배치!
                    # uploadfields.txt 분석: uploadCategory 안에도 카테고리 정보가 중첩되어 있음
                    payload['uploadCategory'] = {
                        "search": product_name,
                        "uploadCommonProductName": product_name,
                        "cp_category": {"name": cat_name, "code": str(category_id)},
                        "categoryList": [category_list_item],
                        "code": str(category_id),
                        "name": cat_name
                    }
                    
                    if meta_res.status_code == 200:
                        meta_data = meta_res.json()
                        real_data = meta_data.get('data') if isinstance(meta_data.get('data'), dict) else meta_data
                        
                        if real_data:
                            print(f"[INFO] 쿠팡 메타 정보 확보 성공 (속성 {len(real_data.get('attributes', []))}개)")
                            # isAllowSingleItem 등 플래그성 정보 안전하게 병합
                            if 'isAllowSingleItem' in real_data:
                                payload['isAllowSingleItem'] = real_data['isAllowSingleItem']
                    else:
                        print(f"[WARNING] 쿠팡 메타 정보 조회 실패: {meta_res.status_code}")
            except Exception as e:
                print(f"[WARNING] 쿠팡 메타 정보 로직 예외: {e}")

        # [최종 디버깅] 전송 직전 페이로드 요약
        print(f"[DEBUG] 최종 전송 페이로드 요약:")
        print(f"  - productId: {payload.get('productId')}")
        print(f"  - targetMarket: {payload.get('targetMarket')}")
        print(f"  - root name/search/code 존재: {'name' in payload and 'search' in payload and 'code' in payload}")
        print(f"  - cp_category/categoryList 존재: {'cp_category' in payload and 'categoryList' in payload}")
        print(f"  - uploadBulsajaCode 존재: {'uploadBulsajaCode' in payload}")
        print(f"  - uploadCategory 타입: {type(payload.get('uploadCategory'))}")
        # root에 attributes가 있으면 출력 (현재는 제거함)
        if 'attributes' in payload:
             print(f"  - attributes 개수: {len(payload.get('attributes') or [])}")
        print(f"  - notices 개수: {len(payload.get('notices') or [])}")
        print(f"  - uploadSkus 존재: {'uploadSkus' in payload}")
        print(f"  - uploadSetting(오타 포함) 존재: {'uploadSetting' in payload or 'uplaodSetting' in payload}")

        # [디버깅] 페이로드를 파일로 저장 (서버 거부 원인 분석용)
        try:
            import os
            debug_dir = os.path.join(os.path.dirname(__file__), "debug_payloads")
            os.makedirs(debug_dir, exist_ok=True)
            debug_file = os.path.join(debug_dir, f"payload_{product_id}.json")
            with open(debug_file, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            print(f"[DEBUG] 페이로드 저장됨: {debug_file}")
        except Exception as e:
            print(f"[WARNING] 페이로드 저장 실패: {e}")

        try:
            # [수정] 30초 타임아웃 추가 및 JSON 전송
            print(f"[INFO] 업로드 POST 요청 전송 중... (타임아웃: 30초)")
            response = self.session.post(url, json=payload, timeout=30)
            response.raise_for_status()

            # 응답 내용 확인
            try:
                result = response.json()
                if isinstance(result, dict):
                    if result.get('error') or result.get('errors'):
                        error_msg = result.get('error') or result.get('errors') or result.get('message', '')
                        msg = f"업로드 실패: {str(error_msg)[:100]}"
                        print(f"[ERROR] {msg}")
                        return False, msg
                    if result.get('success') == False:
                        msg = f"업로드 실패: {result.get('message', '알 수 없는 오류')[:100]}"
                        print(f"[ERROR] {msg}")
                        return False, msg
                    # 상태 확인
                    status = result.get('status') or result.get('uploadStatus')
                    if status and status.lower() in ['failed', 'error', 'failure']:
                        msg = f"업로드 실패: {result.get('message', status)[:100]}"
                        print(f"[ERROR] {msg}")
                        return False, msg
                msg = f"성공 (응답: {str(result)[:50]})"
                print(f"[SUCCESS] ✅ 업로드 성공! - {msg}")
                return True, msg
            except:
                # JSON 파싱 실패시 텍스트로 확인
                text = response.text[:100] if response.text else "응답 없음"
                msg = f"성공 (raw: {text})"
                print(f"[SUCCESS] ✅ 업로드 성공! - {msg}")
                return True, msg

        except requests.exceptions.Timeout:
            msg = "업로드 실패: 서버 응답 시간 초과 (30초)"
            print(f"[ERROR] ⏱️ {msg}")
            return False, msg
        except requests.exceptions.HTTPError as e:
            # [수정] 로그 간소화: 콘솔에는 상태 코드만 출력 (상세 내용은 리턴 메시지로 전달되어 파일 로그에 기록됨)
            msg = f"HTTP 오류: {e.response.status_code}"
            error_body = ""
            try:
                # 에러 메시지 추출 시도
                error_body = e.response.text[:500]  # 응답 body 전체
                error_json = e.response.json()
                if error_json.get('message'):
                     msg += f" - {error_json.get('message')}"
                elif error_json.get('error'):
                     msg += f" - {error_json.get('error')}"
            except:
                if error_body:
                    msg += f" - {error_body[:200]}"

            print(f"[ERROR] ❌ {msg[:200]}") # 200자로 확장
            return False, msg
        except Exception as e:
            msg = f"예외: {str(e)}"
            print(f"[ERROR] ❌ 예외 발생: {msg[:100]}")
            return False, msg

    def get_market_groups(self) -> List[Dict]:
        """마켓 그룹 목록 조회 (ID 포함)"""
        url = f"{self.BASE_URL}/market/groups/"
        try:
            response = self.session.post(url, json={})
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                # 디버그: 첫 번째 그룹 구조 확인
                if data:
                    print(f"[DEBUG] 마켓그룹 첫번째 구조: {list(data[0].keys())}")
                    print(f"[DEBUG] 마켓그룹 샘플: {data[0]}")
                return data  # 전체 데이터 반환 (id, name 등 포함)
            return []
        except Exception as e:
            print(f"[DEBUG] get_market_groups error: {e}")
            return []

    def get_market_group_names(self) -> List[str]:
        """마켓 그룹 이름만 조회 (기존 호환)"""
        groups = self.get_market_groups()
        return [g.get('name', '') for g in groups if g.get('name')]

    def search_category(self, keyword: str, market_type: str = "ss") -> Optional[Dict]:
        """
        카테고리 검색 API
        Args:
            keyword: 검색 키워드 (상품명)
            market_type: 마켓 타입 (ss=스마트스토어, cp=쿠팡, esm=G마켓/옥션, est=11번가)
        Returns:
            첫 번째 매칭 카테고리 정보 또는 None
        """
        url = f"{self.BASE_URL}/manage/category/bulsaja_category"
        try:
            response = self.session.post(url, json={"keyword": keyword})
            response.raise_for_status()
            result = response.json()

            if result.get('success'):
                category_map = result.get('data', {}).get('categoryMap', {})
                categories = category_map.get(market_type, [])
                if categories:
                    return categories[0]  # 첫 번째 추천 카테고리
            return None
        except Exception as e:
            # print(f"[ERROR] 카테고리 검색 실패: {e}")
            return None

    def update_category(self, product_id: str, product_name: str, market_type: str = "ss") -> Tuple[bool, str]:
        """
        상품 카테고리 자동 매핑 및 업데이트
        Args:
            product_id: 상품 ID
            product_name: 상품명 (카테고리 검색용)
            market_type: 마켓 타입 (ss=스마트스토어)
        Returns:
            (성공여부, 메시지)
        """
        # 카테고리 검색
        category = self.search_category(product_name, market_type)
        if not category:
            return False, "검색결과 없음"

        category_name = category.get('name', '')

        # 마켓 타입별 카테고리 필드명
        category_field_map = {
            "ss": "ss_category",
            "cp": "cp_category",
            "esm": "esm_category",
            "est": "est_category",
        }
        category_field = category_field_map.get(market_type, "ss_category")

        # [수정] 전체 카테고리 객체 구조를 유지하여 업데이트
        update_data = {
            "uploadCategory": {
                category_field: category
            }
        }

        success, msg = self.update_product_fields(product_id, update_data)
        if success:
            return True, f"{category_name}"
        return False, msg

    def update_category_esm_fixed(self, product_id: str) -> Tuple[bool, str]:
        """
        ESM 카테고리 고정 업데이트 (기타전동공구: 300025517)
        """
        fixed_code = "300025517"
        fixed_name = "기타전동공구"
        
        # [수정] 검색 결과를 흉내낸 최소한의 구조 생성
        update_data = {
            "uploadCategory": {
                "esm_category": {
                    "code": fixed_code,
                    "name": fixed_name,
                    "categoryList": [{"name": fixed_name, "code": fixed_code, "id": "esm"}]
                }
            }
        }
        
        success, msg = self.update_product_fields(product_id, update_data)
        if success:
            return True, f"{fixed_name} ({fixed_code}) 고정"
        return False, msg

    # ==================== 태그 관련 메서드 ====================
    def get_existing_tags(self) -> List[str]:
        """기존 태그(그룹) 목록 조회"""
        url = f"{self.BASE_URL}/manage/groups"
        try:
            response = self.session.get(url)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                return [g.get('name', '') for g in data if g.get('name')]
            return []
        except Exception as e:
            print(f"[ERROR] 태그 목록 조회 실패: {e}")
            return []

    def create_tag(self, tag_name: str) -> bool:
        """새 태그 생성"""
        url = f"{self.BASE_URL}/manage/groups"
        try:
            response = self.session.post(url, json={"name": tag_name})
            response.raise_for_status()
            print(f"[INFO] 태그 생성됨: {tag_name}")
            return True
        except Exception as e:
            print(f"[ERROR] 태그 생성 실패: {e}")
            return False

    def apply_tag_to_products(self, product_ids: List[str], tag_name: str) -> Tuple[bool, int]:
        """
        상품들에 태그 적용
        Returns:
            (성공여부, 적용된 상품 수)
        """
        if not product_ids:
            return False, 0

        # 태그가 없으면 생성
        existing_tags = self.get_existing_tags()
        if tag_name not in existing_tags:
            if not self.create_tag(tag_name):
                return False, 0

        url = f"{self.BASE_URL}/sourcing/bulk-update-groups"
        try:
            response = self.session.post(url, json={
                "productIds": product_ids,
                "groupName": tag_name
            })
            response.raise_for_status()
            print(f"[INFO] 태그 '{tag_name}' 적용 완료: {len(product_ids)}개 상품")
            return True, len(product_ids)
        except Exception as e:
            print(f"[ERROR] 태그 적용 실패: {e}")
            return False, 0


# ==================== 업로더 클래스 ====================
class BulsajaUploader:
    def __init__(self, gui):
        self.gui = gui
        self.api_client: Optional[BulsajaAPIClient] = None
        self.is_running = False
        self.price_settings = PriceSettings()
        # 제외 키워드 로드
        self.exclude_keywords = EXCLUDE_KEYWORDS[:]
        
        # 통계
        self.stats = {"total": 0, "success": 0, "failed": 0, "duplicate_failed": 0, "skipped": 0, "failed_ids": []}

        # [신규] 태그 적용 추적 (중복 방지)
        self._tagged_ids = set()
        self._tag_lock = threading.Lock()

        # [수정] 가격 필드명 캐시 (자동 감지용)
        self.origin_price_field = None

        # [신규] 로그 디렉토리 생성
        if not os.path.exists("log"):
            os.makedirs("log")

    def log(self, msg: str):
        if self.gui:
            self.gui.log(msg)
        else:
            print(msg)

    def write_detail_log(self, product_id: str, content: str):
        """상세 로그를 파일에 기록"""
        try:
            today = datetime.now().strftime("%Y%m%d")
            filename = f"log/upload_detail_{today}.log"
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            with open(filename, "a", encoding="utf-8") as f:
                f.write(f"\n[{timestamp}] [Product: {product_id}]\n")
                f.write(content)
                f.write("-" * 50 + "\n")
        except Exception as e:
            print(f"로그 파일 기록 실패: {e}")

    def _tag_failed_async(self, product_id: str):
        """실패 상품에 태그를 비동기로 적용 (별도 스레드)"""
        def _apply():
            try:
                with self._tag_lock:
                    if product_id in self._tagged_ids:
                        return  # 이미 태그됨
                    self._tagged_ids.add(product_id)

                success, _ = self.api_client.apply_tag_to_products([product_id], "업로드실패")
                if success:
                    print(f"[TAG] 🏷️ {product_id} 태그 적용 완료")
            except Exception as e:
                print(f"[TAG] 태그 적용 실패: {e}")

        # 별도 스레드에서 실행 (업로드 속도 영향 없음)
        threading.Thread(target=_apply, daemon=True).start()

    def detect_origin_price_field(self, sku: Dict) -> Tuple[str, float]:
        """
        SKU에서 원가 필드를 자동 감지
        Returns: (필드명, 가격값)
        """
        # 시도할 필드명 우선순위
        price_field_candidates = [
            '_origin_price',    # 기존 코드 사용명
            'originPrice',      # 일반적 API 필드
            'origin_price',     # snake_case
            '_originPrice',     # 내부 필드 가능성
            'price',            # 단순 가격
            'skuPrice',         # SKU 가격
            'salePrice',        # 판매가 (원가 없을 때)
            'originalPrice'
        ]

        # 1. 후보군 확인
        for field in price_field_candidates:
            value = sku.get(field)
            if value is not None:
                try:
                    float_val = float(value)
                    if float_val > 0:
                        return field, float_val
                except (ValueError, TypeError):
                    continue

        # 2. 모든 price/origin 관련 필드 확인 (최후의 수단)
        for key in sku.keys():
            if 'price' in key.lower() or 'origin' in key.lower():
                value = sku.get(key)
                if value is not None:
                    try:
                        float_val = float(value)
                        if float_val > 0:
                            return key, float_val
                    except (ValueError, TypeError):
                        continue

        return None, 0.0

    def get_sku_origin_price(self, sku: Dict) -> float:
        """안전하게 SKU 원가를 가져오는 헬퍼"""
        if self.origin_price_field:
            val = sku.get(self.origin_price_field, 0)
            try:
                return float(val)
            except:
                return 0.0
        
        # 필드가 아직 확정 안됐거나 없는 경우 탐색
        field, price = self.detect_origin_price_field(sku)
        if field:
            self.origin_price_field = field # 캐시 저장
            return price
        return 0.0

    def init_api_client(self, access_token: str, refresh_token: str) -> Tuple[bool, str, int]:
        self.api_client = BulsajaAPIClient(access_token, refresh_token)
        return self.api_client.test_connection()

    def extract_tokens_from_browser(self, port: int = 9222) -> Tuple[bool, str, str, str]:
        try:
            tabs_url = f"http://127.0.0.1:{port}/json"
            try:
                response = requests.get(tabs_url, timeout=3)
                tabs = response.json()
            except:
                return False, "", "", f"크롬 포트 {port} 연결 실패"

            bulsaja_tab = None
            for tab in tabs:
                if 'bulsaja.com' in tab.get('url', ''):
                    bulsaja_tab = tab
                    break

            if not bulsaja_tab:
                return False, "", "", "불사자 탭 없음"

            ws_url = bulsaja_tab.get('webSocketDebuggerUrl')
            if not ws_url:
                return False, "", "", "WebSocket URL 없음"

            ws = websocket.create_connection(ws_url, timeout=5)
            cmd = {
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": """
                        (function() {
                            var tokenStr = localStorage.getItem('token');
                            if (tokenStr) {
                                try {
                                    var tokenObj = JSON.parse(tokenStr);
                                    if (tokenObj.state) {
                                        return JSON.stringify({
                                            accessToken: tokenObj.state.accessToken || '',
                                            refreshToken: tokenObj.state.refreshToken || ''
                                        });
                                    }
                                } catch(e) {}
                            }
                            return JSON.stringify({accessToken: '', refreshToken: ''});
                        })()
                    """,
                    "returnByValue": True
                }
            }
            ws.send(json.dumps(cmd))
            result = json.loads(ws.recv())
            ws.close()

            if 'result' in result and 'result' in result['result']:
                token_data = json.loads(result['result']['result'].get('value', '{}'))
                access_token = token_data.get('accessToken', '')
                refresh_token = token_data.get('refreshToken', '')
                if access_token and refresh_token:
                    return True, access_token, refresh_token, ""

            return False, "", "", "토큰 파싱 실패"
        except Exception as e:
            return False, "", "", f"예외: {e}"

    def filter_options(self, skus: List[Dict], settings: PriceSettings) -> List[Dict]:
        filtered = []
        for sku in skus:
            text = sku.get('text', '') or sku.get('_text', '')
            # GUI에서 설정한 제외 키워드 사용
            if any(keyword in text for keyword in self.exclude_keywords):
                continue
            # 가격 계산 (안전한 필드 접근)
            # origin_price = sku.get('_origin_price', 0) -> 수정
            origin_price = self.get_sku_origin_price(sku)
            # BulsajaUploader 인스턴스 메서드 사용 불가 시 (여긴 독립함수라) 
            # 임시로 직접 필드 탐색 (간단 버전)
            # for f in ['_origin_price', 'originPrice', 'price', 'salePrice']:
            #     if f in sku:
            #         try:
            #             origin_price = float(sku[f])
            #             break
            #         except: pass

            if origin_price <= 0:
                continue
            # 필터링용 가격 계산 (최소 마진 기준)
            origin_krw = origin_price * settings.exchange_rate
            price_with_fee = origin_krw * (1 + settings.card_fee_rate / 100)
            sale_price = price_with_fee * (1 + settings.margin_rate_min / 100) + settings.margin_fixed
            sale_price = math.ceil(sale_price / settings.round_unit) * settings.round_unit
            if sale_price < settings.min_price or sale_price > settings.max_price:
                continue
            filtered.append(sku)
        return filtered

    def sort_options(self, skus: List[Dict], sort_type: str, settings: PriceSettings) -> List[Dict]:
        """옵션 정렬"""
        if sort_type == "price_asc":
            return sorted(skus, key=lambda x: self.get_sku_origin_price(x))
        elif sort_type == "price_desc":
            return sorted(skus, key=lambda x: self.get_sku_origin_price(x), reverse=True)
        elif sort_type == "price_main":
            # 주요가격대: 평균가에 가까운 옵션 우선
            if not skus:
                return skus
            # 전체 옵션의 평균 원가 계산
            total_price = sum(self.get_sku_origin_price(sku) for sku in skus)
            avg_price = total_price / len(skus)
            def distance_from_avg(sku):
                return abs(self.get_sku_origin_price(sku) - avg_price)
            return sorted(skus, key=distance_from_avg)
        return skus

    def limit_options(self, skus: List[Dict], max_count: int, main_sku_price: float = None) -> List[Dict]:
        """
        옵션 개수 제한
        - main_sku_price가 주어지면: 해당 가격 이상인 옵션만 선택 (대표옵션 포함)
        - 가격순 정렬 후 max_count개 선택
        """
        if max_count <= 0:
            return skus

        if main_sku_price is not None:
            # 대표옵션 가격 이상인 옵션만 필터링
            eligible_skus = [
                sku for sku in skus
                if self.get_sku_origin_price(sku) >= main_sku_price
            ]
            # 가격 오름차순 정렬
            eligible_skus.sort(key=lambda x: self.get_sku_origin_price(x))
            return eligible_skus[:max_count]
        else:
            # 기존 방식: 앞에서부터 자르기
            if len(skus) > max_count:
                return skus[:max_count]
            return skus

    def process_product(self, product: Dict, group_name: str, option_count: int,
                       option_sort: str, title_mode: str = "original",
                       skip_sku_update: bool = False, skip_price_update: bool = False,
                       market_name: str = "스마트스토어",
                       current_idx: int = 0, total_count: int = 0) -> Dict:
        product_id = product.get('ID', '')
        full_product_name = product.get('uploadCommonProductName', '')
        product_name = full_product_name[:25]

        result = {
            'id': product_id,
            'name': product_name,
            'status': 'success',
            'message': ''
        }

        try:
            # [v1.5] 금지 키워드 체크 (상품명 기준)
            banned_kw_text = self.gui.banned_kw_text.get("1.0", tk.END).strip() if hasattr(self.gui, 'banned_kw_text') else ""
            if banned_kw_text:
                banned_keywords = [kw.strip().lower() for kw in banned_kw_text.split(',') if kw.strip()]
                product_name_lower = full_product_name.lower()
                found_banned = None
                for bkw in banned_keywords:
                    if bkw in product_name_lower:
                        found_banned = bkw
                        break
                if found_banned:
                    progress_str = f"[{current_idx}/{total_count}] " if total_count > 0 else ""
                    market_short = MARKET_SHORT.get(market_name, market_name)
                    self.log("")
                    self.log(f"⏭️ {progress_str}[{market_short}] {product_id} - 금지키워드 [{found_banned}]")
                    self.log(f"   {product_name}")
                    result['status'] = 'skipped'
                    result['message'] = f'금지키워드: {found_banned}'
                    return result

            detail = self.api_client.get_product_detail(product_id)

            # [v1.4] 해당 마켓 미업로드 체크
            skip_already_uploaded = self.gui.skip_already_uploaded_var.get() if hasattr(self.gui, 'skip_already_uploaded_var') else True
            if skip_already_uploaded:
                uploaded_markets = detail.get('uploadedMarkets', '') or ''
                market_type = MARKET_TYPES.get(market_name, '')
                if market_type and market_type in uploaded_markets:
                    progress_str = f"[{current_idx}/{total_count}] " if total_count > 0 else ""
                    market_short = MARKET_SHORT.get(market_name, market_name)
                    self.log("")
                    self.log(f"⏭️ {progress_str}[{market_short}] {product_id} - 이미 업로드됨")
                    self.log(f"   {product_name}")
                    result['status'] = 'skipped'
                    result['message'] = f'이미 {market_name}에 업로드됨'
                    return result

            upload_skus = detail.get('uploadSkus', [])
            if not upload_skus:
                progress_str = f"[{current_idx}/{total_count}] " if total_count > 0 else ""
                market_short = MARKET_SHORT.get(market_name, market_name)
                self.log("")
                self.log(f"⏭️ {progress_str}[{market_short}] {product_id} - SKU 없음")
                self.log(f"   {product_name}")
                result['status'] = 'skipped'
                result['message'] = 'SKU 없음'
                return result

            # [긴급 수정] 옵션 중복 제거 (데이터 뻥튀기 방지)
            unique_skus = []
            seen_ids = set()
            
            # [추가] 값(텍스트) 기준 중복 제거 (Logical Duplication)
            # SKU ID가 다르더라도 식별값(prop_val_ids 또는 text)이 같으면 중복으로 간주
            seen_values = set()

            for sku in upload_skus:
                sid = sku.get('id')
                
                # 1. ID 기준 중복 체크
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)

                # 2. 값 기준 중복 체크
                # prop_val_ids가 가장 정확 (예: "1:1:1")
                # 없으면 text 사용
                val_key = sku.get('prop_val_ids')
                if not val_key:
                    val_key = sku.get('text', '') or sku.get('_text', '')
                
                # 키가 리스트인 경우 튜플로 변환
                if isinstance(val_key, list):
                    val_key = tuple(val_key)

                if val_key and val_key in seen_values:
                    # 로그는 너무 많을 수 있으므로 생략하거나 디버그 레벨로
                    continue
                
                if val_key:
                    seen_values.add(val_key)

                unique_skus.append(sku)
            
            if len(unique_skus) < len(upload_skus):
                self.log(f"   🧹 중복 옵션 제거(ID/값): {len(upload_skus)}개 → {len(unique_skus)}개")
                upload_skus = unique_skus

            # 해외배송비 가져오기 (상품별 설정값 사용)
            delivery_fee = detail.get('uploadOverseaDeliveryFee', 0) or 0

            # 로그 시작 (상품별 구분을 위해 빈 줄 + ID/상품명 분리)
            progress_str = f"[{current_idx}/{total_count}] " if total_count > 0 else ""
            market_short = MARKET_SHORT.get(market_name, market_name)
            self.log("")  # 상품 간 구분선
            self.log(f"📤 {progress_str}[{market_short}] {product_id}")
            self.log(f"   {product_name}")

            margin_rate = int(random.uniform(self.price_settings.margin_rate_min, self.price_settings.margin_rate_max))
            # ESM/11번가 할인율 3% 고정 (GUI 옵션)
            esm_discount_3 = self.gui.esm_discount_3_var.get() if hasattr(self.gui, 'esm_discount_3_var') else True
            if esm_discount_3 and market_name in ["G마켓/옥션", "11번가"]:
                discount_rate = 3
            else:
                discount_rate = int(random.uniform(self.price_settings.discount_rate_min, self.price_settings.discount_rate_max))
            
            # 2. 미끼 옵션 필터링 + 가격 범위 필터링
            valid_skus = []
            excluded_by_keyword = []  # (id, text, price, 매칭키워드)
            excluded_by_price = []    # (id, text, price, 이유)

            # [v1.4] 미끼 키워드 빈도+가격 분석
            # 키워드가 2개 이상 옵션에 포함되고, 해당 옵션들 가격이 미끼 가격이 아니면 → 상품 특성으로 간주
            keyword_skus = {}  # 키워드별 매칭된 SKU 리스트
            for kw in self.exclude_keywords:
                matching = [sku for sku in upload_skus if kw in (sku.get('text', '') or sku.get('_text', ''))]
                if matching:
                    keyword_skus[kw] = matching

            # 전체 옵션 평균 가격 (위안)
            all_prices = [self.get_sku_origin_price(sku) for sku in upload_skus if self.get_sku_origin_price(sku) > 0]
            avg_price = sum(all_prices) / len(all_prices) if all_prices else 0

            # 2개 이상 옵션에 포함된 키워드는 가격 검증
            excluded_common_keywords = set()
            for kw, matching_skus in keyword_skus.items():
                if len(matching_skus) >= 2:  # 최소 2개 이상 옵션에 포함
                    # 해당 키워드 포함 옵션들의 평균 가격
                    kw_prices = [self.get_sku_origin_price(sku) for sku in matching_skus if self.get_sku_origin_price(sku) > 0]
                    kw_avg = sum(kw_prices) / len(kw_prices) if kw_prices else 0

                    # 전체 평균의 50% 이상이면 미끼 가격 아님 → 키워드 필터링 제외
                    if avg_price > 0 and kw_avg >= avg_price * 0.5:
                        excluded_common_keywords.add(kw)

            # 실제 필터링에 사용할 키워드 (공통+정상가격 키워드 제외)
            effective_exclude_keywords = [kw for kw in self.exclude_keywords if kw not in excluded_common_keywords]

            if excluded_common_keywords:
                self.log(f"   ℹ️ 공통키워드 통과: {', '.join(excluded_common_keywords)} (2개+ 옵션, 정상가격)")

            for sku in upload_skus:
                sku_id = sku.get('id', '?')
                text = sku.get('text', '') or sku.get('_text', '')
                origin_cny = self.get_sku_origin_price(sku)

                # [중요] exclude 필드는 무시! 사용자 원칙: 미끼 아니고 가격 범위 맞으면 업로드

                # 미끼 키워드 체크 (공통 키워드 제외된 목록 사용)
                matched_kw = None
                for kw in effective_exclude_keywords:
                    if kw in text:
                        matched_kw = kw
                        break
                if matched_kw:
                    excluded_by_keyword.append((sku_id, text[:20], origin_cny, matched_kw))
                    continue

                # 가격 범위 체크
                if origin_cny <= 0:
                    excluded_by_price.append((sku_id, text[:20], origin_cny, "가격0"))
                    continue

                # [중요] SKU별 가격 직접 계산 및 설정
                # 불사자 공식 (ADDITIVE):
                #   기준판매가(sale_price) = 원화원가 × (1 + 마진율/100) + 정액마진 + 해외배송비
                #   ※ 마켓수수료(uploadFake_pct)는 업로드 시 마켓에서 자동 적용됨
                #
                # SKU 필드 의미:
                #   origin_price = 원화 원가 (CNY × 환율, 마진 미포함)
                #   sale_price = 기준 판매가 (마진 포함된 실제 판매가)
                #
                # 할인 표시는 uploadBase_price.discount_rate로 마켓에서 처리

                # 1. 원화원가 = CNY × 환율
                origin_krw = origin_cny * self.price_settings.exchange_rate

                # 2. 기준 판매가 계산 (불사자 공식)
                # 기준판매가 = 원화원가 × (1 + 카드수수료 + 마진율) + 정액마진 + 해외배송비
                card_fee_decimal = self.price_settings.card_fee_rate / 100  # 3.3% → 0.033
                margin_rate_decimal = margin_rate / 100  # 26% → 0.26
                base_price = origin_krw * (1 + card_fee_decimal + margin_rate_decimal) + self.price_settings.margin_fixed + delivery_fee
                sale_price_final = math.ceil(base_price / self.price_settings.round_unit) * self.price_settings.round_unit

                # 3. SKU에 가격 설정
                #    origin_price = 원화 원가 (환율만 적용)
                #    sale_price = 기준 판매가 (마진 포함)
                sku['origin_price'] = int(origin_krw)
                sku['sale_price'] = int(sale_price_final)

                if sale_price_final < self.price_settings.min_price:
                    excluded_by_price.append((sku_id, text[:20], origin_cny, f"최소가미만({sale_price_final:,.0f}원)"))
                    continue
                if sale_price_final > self.price_settings.max_price:
                    excluded_by_price.append((sku_id, text[:20], origin_cny, f"최대가초과({sale_price_final:,.0f}원)"))
                    continue

                valid_skus.append(sku)

            # 상세 필터링 로그 처리 (파일 분리)
            detail_log_buffer = ""

            if excluded_by_keyword:
                detail_log_buffer += f"\n[키워드제외] {len(excluded_by_keyword)}개\n"
                for sku_id, text, price, kw in excluded_by_keyword:
                    detail_log_buffer += f"   └ id={sku_id}, {price}위안, '{kw}' 매칭, {text}\n"

            if excluded_by_price:
                detail_log_buffer += f"\n[가격제외] {len(excluded_by_price)}개\n"
                for sku_id, text, price, reason in excluded_by_price:
                    detail_log_buffer += f"   └ id={sku_id}, {price}위안, {reason}, {text}\n"

            # 필터링 결과 요약 (한 줄로)
            filter_msg = f"   📦 SKU {len(upload_skus)} → {len(valid_skus)}개"
            if excluded_by_keyword: filter_msg += f" (키워드제외 {len(excluded_by_keyword)})"
            if excluded_by_price: filter_msg += f" (가격제외 {len(excluded_by_price)})"
            self.log(filter_msg)

            if not valid_skus:
                if detail_log_buffer:
                    self.write_detail_log(product_id, detail_log_buffer)
                # 매칭된 키워드 요약 (중복 제거, 최대 5개)
                if excluded_by_keyword:
                    matched_kws = list(set([kw for _, _, _, kw in excluded_by_keyword]))[:5]
                    self.log(f"   🔍 매칭키워드: {', '.join(matched_kws)}")
                result['status'] = 'skipped'
                result['message'] = '유효 옵션 없음'
                return result

            # 2. 가격 클러스터링으로 미끼 탐지 (가격대별 그룹 분리)
            bait_ids, cluster_info = detect_bait_by_price_cluster(valid_skus)
            excluded_by_cluster = []  # (id, text, price)

            if bait_ids:
                # 미끼로 판단된 SKU 상세 정보 저장
                for sku in valid_skus:
                    if sku.get('id') in bait_ids:
                        excluded_by_cluster.append((
                            sku.get('id', '?'),
                            (sku.get('text', '') or sku.get('_text', ''))[:20],
                            self.get_sku_origin_price(sku)
                        ))
                # 미끼 제거
                valid_skus = [sku for sku in valid_skus if sku.get('id') not in bait_ids]

                # 클러스터 정보 로그 및 파일 기록
                if cluster_info and len(cluster_info) >= 2:
                    low_cluster = cluster_info[0]
                    main_cluster = cluster_info[1]
                    gap = main_cluster['min_price'] / low_cluster['max_price'] if low_cluster['max_price'] > 0 else 0
                    
                    self.log(f"   📊 가격클러스터 미끼제거: {len(excluded_by_cluster)}개")
                    detail_log_buffer += f"\n[가격클러스터 미끼제거] {len(excluded_by_cluster)}개\n"
                    detail_log_buffer += f"   └ 저가그룹: {low_cluster['count']}개 ({low_cluster['min_price']:.0f}~{low_cluster['max_price']:.0f}위안)\n"
                    detail_log_buffer += f"   └ 주가격대: {main_cluster['count']}개 ({main_cluster['min_price']:.0f}~{main_cluster['max_price']:.0f}위안)\n"
                    detail_log_buffer += f"   └ 가격갭: {gap:.1f}배 (저가비율: {low_cluster['ratio']*100:.0f}%)\n"
                    for sku_id, text, price in excluded_by_cluster:
                        detail_log_buffer += f"      └ id={sku_id}, {price}위안, {text}\n"

            if detail_log_buffer:
                self.write_detail_log(product_id, detail_log_buffer)

            self.log(f"   🎯 필터링 후 남은 옵션: {len(valid_skus)}개")

            if not valid_skus:
                result['status'] = 'skipped'
                result['message'] = '클러스터 필터링 후 유효 옵션 없음'
                return result

            # 4. 옵션 정렬
            if option_sort == "price_asc":
                valid_skus.sort(key=lambda x: self.get_sku_origin_price(x))
                self.log(f"   📈 정렬: 가격낮은순")
            elif option_sort == "price_desc":
                valid_skus.sort(key=lambda x: self.get_sku_origin_price(x), reverse=True)
                self.log(f"   📉 정렬: 가격높은순")

            # 5. 옵션 개수 제한
            if option_count > 0:
                selected_skus = valid_skus[:option_count]
                self.log(f"   ✂️ 옵션 제한: {len(valid_skus)}개 → {len(selected_skus)}개")
            else:
                selected_skus = valid_skus

            # 6. 선택된 SKU ID 목록
            selected_ids = {sku.get('id') for sku in selected_skus}

            # 7. uploadBase_price 및 해외배송비 설정
            detail['uploadBase_price'] = {
                "card_fee": self.price_settings.card_fee_rate,
                "discount_rate": discount_rate,
                "discount_unit": "%",
                "percent_margin": margin_rate,
                "plus_margin": self.price_settings.margin_fixed,
                "raise_digit": self.price_settings.round_unit
            }
            # uploadOverseaDeliveryFee는 상품에 이미 설정된 값 사용 (수정 안 함)
            self.log(f"   💹 가격설정: 마진율 {margin_rate}%, 정액 {self.price_settings.margin_fixed:,}원, 배송비 {delivery_fee:,}원, 할인율 {discount_rate}%")

            # 8. main_product 설정 (전체 옵션 중 위안 원가 최저가)
            # 불사자 exclude는 무시하고, 우리 필터링(키워드/가격/클러스터)만 적용해서 대표상품 선택
            # (불사자 exclude된 옵션도 대표상품이 될 수 있음 - 타이어 주입기처럼 정상옵션이 exclude된 경우)

            # 우리가 제외한 옵션 ID (키워드/가격/클러스터 제외)
            our_excluded_ids = set()
            for sku_id, _, _, _ in excluded_by_keyword:
                our_excluded_ids.add(sku_id)
            for sku_id, _, _, _ in excluded_by_price:
                our_excluded_ids.add(sku_id)
            for sku_id, _, _ in excluded_by_cluster:
                our_excluded_ids.add(sku_id)

            # 모든 SKU의 main_product 초기화
            for sku in upload_skus:
                sku['main_product'] = False

            # 우리가 제외하지 않은 옵션 중 최저가 찾기 (불사자 exclude 무시)
            min_price_cny = float('inf')
            min_price_sku = None
            for sku in upload_skus:
                if sku.get('id') in our_excluded_ids:
                    continue
                origin_cny = self.get_sku_origin_price(sku)
                if origin_cny > 0 and origin_cny < min_price_cny:
                    min_price_cny = origin_cny
                    min_price_sku = sku

            if min_price_sku:
                min_price_sku['main_product'] = True
                sale_price_krw = min_price_sku.get('sale_price', 0)
                self.log(f"   👑 대표: {sale_price_krw:,}원")
                if min_price_sku.get('exclude') is True:
                    min_price_sku['exclude'] = False
            else:
                self.log(f"   ⚠️ 경고: 유효한 옵션 없음 - 업로드 실패 가능")

            # [중요] 선택된 모든 옵션의 exclude를 false로 강제 변경 (업로드 범위 내 옵션은 모두 판매 상태)
            for sku in selected_skus:
                if sku.get('exclude') is True:
                    sku['exclude'] = False

            # [긴급 추가] uploadSkuProps와 uploadSkus 동기화 (옵션탭 체크 문제 해결)
            # SKU 필터링 결과에 맞춰 실제 사용되는 옵션값만 props에 남김
            if 'uploadSkuProps' in detail:
                 props = detail['uploadSkuProps']
                 # [최종] 옵션 차원 복구(Recover) 시도 후 실패 시 스킵(Skip)
                 # 가격탭(SKU 텍스트)은 조합형(콤마 존재)인데 옵션탭 구조는 단일 차원인 경우 복구 시도
                 max_text_dims = 1
                 for sku in upload_skus:
                     txt = sku.get('text', '') or sku.get('_text', '')
                     if txt and ',' in txt:
                         max_text_dims = max(max_text_dims, len(txt.split(',')))
                 
                 current_defined_dims = 0
                 if props.get('mainOption') and props['mainOption'].get('values'): current_defined_dims += 1
                 if props.get('subOption'):
                     if isinstance(props['subOption'], list):
                         # [수정] 리스트의 모든 subOption을 카운트 (3단/4단 옵션 지원)
                         for sub in props['subOption']:
                             if sub.get('values'): current_defined_dims += 1
                     elif isinstance(props['subOption'], dict) and props['subOption'].get('values'):
                         current_defined_dims += 1
                 
                 # [추가] 4단 이상 옵션은 마켓에서 지원하지 않음 - 스킵
                 if max_text_dims >= 4:
                     result['status'] = 'skipped'
                     result['message'] = f'{max_text_dims}단 옵션 (마켓 미지원)'
                     self.log(f"   ⏭️ {result['message']} (스킵)")
                     return result

                 # 차원이 부족한 경우 복구 시도 (1단→2단만)
                 if max_text_dims > current_defined_dims and max_text_dims == 2:
                     self.log(f"   🛠️ 옵션 차원 불일치 감지 ({current_defined_dims}단 -> {max_text_dims}단) - 자동 복구 시도")
                     new_sub_values = []
                     seen_sub_vids = set()
                     
                     for sku in upload_skus:
                         txt = sku.get('text', '') or sku.get('_text', '')
                         parts = [p.strip() for p in txt.split(',')]
                         vids = sku.get('prop_val_ids', [])
                         
                         if len(parts) >= 2 and len(vids) >= 2:
                             sub_vid = str(vids[1])
                             sub_name = parts[1]
                             if sub_vid not in seen_sub_vids:
                                 new_sub_values.append({"vid": sub_vid, "prop_val_name": sub_name, "exclude": False})
                                 seen_sub_vids.add(sub_vid)
                     
                     if new_sub_values:
                         new_sub_category = {"prop_name": "추가옵션", "values": new_sub_values}
                         if not props.get('subOption'): props['subOption'] = [new_sub_category]
                         else:
                             if isinstance(props['subOption'], list):
                                 if not props['subOption']: props['subOption'].append(new_sub_category)
                                 else: props['subOption'][0]['values'] = new_sub_values
                             else: props['subOption'] = [new_sub_category]
                         self.log(f"   ✅ 누락된 서브 옵션({len(new_sub_values)}개) 복구 완료")
                         current_defined_dims += 1 # 차원 갱신

                 # 여전히 차원이 부족하면 스킵 (데이터 부정확성 차단)
                 if max_text_dims > current_defined_dims:
                     result['status'] = 'skipped'
                     result['message'] = f'옵션 차원 불일치 (복구 실패: {current_defined_dims}단 vs {max_text_dims}단)'
                     self.log(f"   ⏭️ {result['message']} (스킵)")
                     return result

                 # 1. 실제 사용된 모든 옵션값 수집 (통합 Set)
                 used_vids = set()
                 
                 for sku in upload_skus:
                     p_ids = sku.get('prop_val_ids')
                     if p_ids:
                         for vid in p_ids:
                             used_vids.add(str(vid))
                     else:
                         # [Fallback] prop_val_ids가 없는 경우 id를 vid로 사용 (페이로드 분석 결과)
                         sku_id = sku.get('id')
                         if sku_id:
                             used_vids.add(str(sku_id))
                 
                 # 2. Main Option 필터링 및 활성화
                 if props.get('mainOption'):
                     main_vals = props['mainOption'].get('values') or []
                     new_main_vals = []
                     for v in main_vals:
                         # vid 매칭 확인
                         if str(v.get('vid')) in used_vids:
                             # [중요] 매칭된 옵션 활성화 (exclude: false)
                             if v.get('exclude') is True:
                                 v['exclude'] = False
                             new_main_vals.append(v)
                     
                     if main_vals and not new_main_vals:
                         # [안전장치] 매칭되는 값이 없으면 전체 활성화하여 구조 유지 (단일 옵션 등 대응)
                         for v in main_vals: v['exclude'] = False
                         new_main_vals = main_vals
                     
                     props['mainOption']['values'] = new_main_vals
                     if len(main_vals) != len(new_main_vals):
                         self.log(f"   🧹 옵션 동기화(메인): {len(main_vals)}개 -> {len(new_main_vals)}개")

                 # 3. Sub Option 필터링 및 활성화
                 if props.get('subOption'):
                     new_sub_options = []
                     for sub in props['subOption']:
                         sub_vals = sub.get('values') or []
                         new_sub_vals = []
                         for v in sub_vals:
                             if str(v.get('vid')) in used_vids:
                                 # [중요] 매칭된 옵션 활성화
                                 if v.get('exclude') is True:
                                     v['exclude'] = False
                                 new_sub_vals.append(v)
                         
                         if sub_vals and not new_sub_vals:
                             # [안전장치] 매칭되는 값이 없으면 전체 활성화하여 구조 유지
                             for v in sub_vals: v['exclude'] = False
                             new_sub_vals = sub_vals
                         
                         sub['values'] = new_sub_vals
                         new_sub_options.append(sub)
                     
                     if len(props['subOption']) != len(new_sub_options):
                         self.log(f"   🧹 옵션 동기화(서브): {len(new_sub_options)}개 남음")
                     props['subOption'] = new_sub_options
            
            # 9. 변경사항 저장
            detail['uploadSkus'] = upload_skus
            
            # 10. 상품명 셔플 처리
            original_name = detail.get('uploadCommonProductName', '')
            if title_mode != "original" and original_name:
                detail['uploadCommonProductName'] = shuffle_product_name(original_name, title_mode)

            # 11. 카테고리 설정 (v1.3 수정: 메인 업데이트에 통합)
            # [중요] 별도 호출 시 기존 데이터(SKU)가 날아가는 문제 방지를 위해 detail 객체에 직접 삽입
            full_product_name = detail.get('uploadCommonProductName', '')
            
            # SS 카테고리 재검색 (GUI 옵션)
            ss_category_search = self.gui.ss_category_search_var.get() if hasattr(self.gui, 'ss_category_search_var') else True
            if ss_category_search and market_name == "스마트스토어":
                # 상품명 기반 검색 (객체 구조 유지)
                cat_info = self.api_client.search_category(full_product_name, "ss")
                if cat_info:
                    if 'uploadCategory' not in detail: detail['uploadCategory'] = {}
                    # [구조 표준화] container 구조 적용
                    detail['uploadCategory']['ss_category'] = {
                        "name": cat_info.get('name'),
                        "code": cat_info.get('code'),
                        "search": full_product_name,
                        "categoryList": [cat_info]
                    }
                    cat_name = cat_info.get('name', '')
                    display_cat = (cat_name[:40] + '..') if len(cat_name) > 40 else cat_name
                    self.log(f"   🏷️ SS 카테고리: {display_cat}")
                else:
                    pass  # 실패 로그는 제거
            
            elif market_name in ["G마켓/옥션"]:
                # [v1.3 수정] 사용자 요청: 무조건 '그라인더' 카테고리 적용 (배송비 제한 및 옵션 매칭 해결용)
                force_cat_name = "그라인더"
                cat_info = self.api_client.search_category(force_cat_name, "esm")
                
                if cat_info:
                    if 'uploadCategory' not in detail: detail['uploadCategory'] = {}
                    detail['uploadCategory']['esm_category'] = {
                        "name": cat_info.get('name'),
                        "code": cat_info.get('code'),
                        "search": force_cat_name,
                        "categoryList": [cat_info]
                    }
                    cat_name = cat_info.get('name', '')
                    display_cat = (cat_name[:40] + '..') if len(cat_name) > 40 else cat_name
                    # 로그는 나중에 통합 출력
                else:
                    # API 검색 실패 시 수동 객체 (그라인더)
                    fixed_code = "300021312"
                    fixed_full_name = "공구/안전/산업용품 > 절삭공구 > 그라인더"
                    if 'uploadCategory' not in detail: detail['uploadCategory'] = {}
                    detail['uploadCategory']['esm_category'] = {
                        "code": fixed_code,
                        "name": fixed_full_name,
                        "search": force_cat_name,
                        "categoryList": [{
                            "name": fixed_full_name,
                            "code": fixed_code,
                            "id": "esm",
                            "needCert": False,
                            "additional": {
                                "options": [{"name": "발송일", "code": 1021}],
                                "isBook": False, "addPrice": True, "addOption": True,
                                "gmarket": fixed_code, "auction": "72230100"
                            }
                        }]
                    }
                    self.log(f"   🏷️ ESM 카테고리 수동지정: {fixed_full_name}")

                if cat_info:
                    if 'uploadCategory' not in detail: detail['uploadCategory'] = {}
                    # ESM은 계층 구조가 포함된 name과 categoryList가 중요
                    detail['uploadCategory']['esm_category'] = {
                        "name": cat_info.get('name'),
                        "code": cat_info.get('code'),
                        "search": full_product_name,
                        "categoryList": [cat_info]
                    }
                    self.log(f"   🏷️ ESM 카테고리 확정: {cat_info.get('name')}")
                else:
                    # API 검색도 실패 시 수동 객체 (최후의 보루: 그라인더 코드)
                    fixed_code = "300021312" # G마켓 그라인더 표준 코드 예시
                    fixed_full_name = "공구/안전/산업용품 > 절삭공구 > 그라인더"
                    if 'uploadCategory' not in detail: detail['uploadCategory'] = {}
                    detail['uploadCategory']['esm_category'] = {
                        "code": fixed_code,
                        "name": fixed_full_name,
                        "search": full_product_name,
                        "categoryList": [{
                            "name": fixed_full_name,
                            "code": fixed_code,
                            "id": "esm",
                            "needCert": False,
                            "additional": {
                                "options": [{"name": "발송일", "code": 1021}],
                                "isBook": False, "addPrice": True, "addOption": True,
                                "gmarket": fixed_code, "auction": "72230100" # 그라인더 대응 옥션 코드
                            }
                        }]
                    }
                    cat_name = fixed_full_name
                    display_cat = (cat_name[:40] + '..') if len(cat_name) > 40 else cat_name
                    self.log(f"   🏷️ ESM 카테고리: {display_cat}")

                # [주의] ESM 배송비 캡핑 로직 제거 (기타전동공구 카테고리는 높은 배송비 허용됨)
                pass

            elif market_name == "11번가":
                # 상품명 기반 검색 시도
                cat_info = self.api_client.search_category(full_product_name, "est")
                if cat_info:
                    if 'uploadCategory' not in detail: detail['uploadCategory'] = {}
                    detail['uploadCategory']['est_category'] = {
                        "name": cat_info.get('name'),
                        "code": cat_info.get('code'),
                        "search": full_product_name,
                        "categoryList": [cat_info]
                    }
                    cat_name = cat_info.get('name', '')
                    display_cat = (cat_name[:40] + '..') if len(cat_name) > 40 else cat_name
                    # 로그는 나중에 통합 출력

            # [v1.5] 제외 카테고리 체크 (카테고리명에 제외 키워드가 포함되어 있으면 건너뛰기)
            exclude_cat_text = self.gui.exclude_cat_text.get("1.0", tk.END).strip() if hasattr(self.gui, 'exclude_cat_text') else ""
            if exclude_cat_text:
                exclude_categories = [cat.strip().lower() for cat in exclude_cat_text.split(',') if cat.strip()]
                # 검색된 카테고리명 가져오기
                searched_cat_name = ""
                if 'uploadCategory' in detail:
                    if market_name == "스마트스토어" and 'ss_category' in detail['uploadCategory']:
                        searched_cat_name = detail['uploadCategory']['ss_category'].get('name', '')
                    elif market_name in ["G마켓/옥션"] and 'esm_category' in detail['uploadCategory']:
                        searched_cat_name = detail['uploadCategory']['esm_category'].get('name', '')
                    elif market_name == "11번가" and 'est_category' in detail['uploadCategory']:
                        searched_cat_name = detail['uploadCategory']['est_category'].get('name', '')

                if searched_cat_name:
                    searched_cat_lower = searched_cat_name.lower()
                    found_exclude_cat = None
                    for exc_cat in exclude_categories:
                        if exc_cat in searched_cat_lower:
                            found_exclude_cat = exc_cat
                            break
                    if found_exclude_cat:
                        progress_str = f"[{current_idx}/{total_count}] " if total_count > 0 else ""
                        market_short = MARKET_SHORT.get(market_name, market_name)
                        self.log(f"   ⏭️ 제외카테고리 [{found_exclude_cat}] → {searched_cat_name[:30]}")
                        result['status'] = 'skipped'
                        result['message'] = f'제외카테고리: {found_exclude_cat}'
                        return result

            # [신규] ESM/11번가 추천 옵션 매핑 오류 및 중복 방지 (옵션명 표준화) - GUI 옵션
            esm_option_normalize = self.gui.esm_option_normalize_var.get() if hasattr(self.gui, 'esm_option_normalize_var') else True
            if esm_option_normalize and market_name in ["G마켓/옥션", "11번가"] and 'uploadSkuProps' in detail:
                sku_props = detail['uploadSkuProps']
                if 'mainOption' in sku_props and sku_props['mainOption']:
                    original_prop = sku_props['mainOption'].get('prop_name', '')
                    if original_prop not in ["색상", "사이즈"]:
                        sku_props['mainOption']['prop_name'] = "색상"
                        self.log(f"   🎨 ESM 옵션명 표준화: '{original_prop}' -> '색상'")
                
                if 'subOption' in sku_props and isinstance(sku_props['subOption'], list):
                    for sub_opt in sku_props['subOption']:
                        original_prop = sub_opt.get('prop_name', '')
                        if original_prop not in ["색상", "사이즈"]:
                            sub_opt['prop_name'] = "사이즈"
                            self.log(f"   📏 ESM 서브옵션명 표준화: '{original_prop}' -> '사이즈'")

            # 12. 전체 업데이트 (SKU, 가격, 카테고리 등 한 번에 전송)
            if skip_sku_update:
                self.log(f"   ⚠️ SKU 수정 건너뜀 (테스트 모드)")
            else:
                update_success, update_msg = self.api_client.update_product_fields(product_id, detail)
                if not update_success:
                    result['status'] = 'failed'
                    result['message'] = f'상품 정보 업데이트 실패: {update_msg}'
                    self.log(f"   ❌ 업데이트 실패: {update_msg}")
                    self._tag_failed_async(product_id)  # 실패 태그 적용
                    return result

            # 13. 업로드 (그룹명으로 그룹ID 조회하여 업로드)
            # 불사자 중복 업로드 방지 옵션
            prevent_duplicate = self.gui.prevent_duplicate_upload_var.get() if hasattr(self.gui, 'prevent_duplicate_upload_var') else True
            upload_success, upload_msg = self.api_client.upload_product(product_id, group_name, market_name, prevent_duplicate)
            if not upload_success:
                # 카테고리 오류 시 (여기서는 이미 통합 업데이트 했으므로 재시도 로직이 좀 다르지만, 혹시 몰라 유지)
                if "카테고리" in upload_msg and market_name == "스마트스토어":
                     # 기존 재시도 로직은 복잡해지므로, 일단 실패 로그만 남김
                     pass

                # 중복 실패 감지 (불사자 중복방지 기능으로 인한 실패)
                is_duplicate = any(kw in upload_msg.lower() for kw in ['중복', 'duplicate', 'already'])
                if is_duplicate:
                    result['status'] = 'duplicate_failed'
                else:
                    result['status'] = 'failed'
                result['message'] = upload_msg

                # [수정] 실패 로그 노출 수위 조절 (사용자 요청: 너무 짧지 않게)
                display_msg = (upload_msg[:200] + '...') if len(upload_msg) > 200 else upload_msg
                fail_icon = "🔁" if is_duplicate else "❌"
                fail_type = "중복실패" if is_duplicate else "업로드 실패"
                self.log(f"   {fail_icon} {fail_type}: {display_msg}")
                self.write_detail_log(product_id, f"[{fail_type}]\n{upload_msg}\n")
                self._tag_failed_async(product_id)  # 실패 태그 적용

                return result

            self.log(f"   ✅ 업로드 성공!")

            # 결과 메시지
            result['message'] = f'SKU {len(selected_skus)}개'

            # 성공 로그 기록
            success_log = f"[업로드성공]\n"
            success_log += f"마켓: {market_name}\n"
            success_log += f"SKU: {len(selected_skus)}개\n"
            if selected_skus:
                price_list = [self.get_sku_origin_price(s) for s in selected_skus[:5]]
                success_log += f"가격(위안): {price_list}\n"
            self.write_detail_log(product_id, success_log)

        except Exception as e:
            result['status'] = 'failed'
            result['message'] = str(e)
            self._tag_failed_async(product_id)  # 실패 태그 적용

        return result

    def process_group(self, group_name: str, upload_count: int,
                     option_count: int, option_sort: str, status_filters: List[str],
                     title_mode: str = "original", skip_sku_update: bool = False,
                     skip_price_update: bool = False, market_name: str = "스마트스토어"):
        """단일 그룹 처리 (그룹명으로 마켓그룹ID 조회하여 업로드)"""
        try:
            # 업로드실패 태그 상품 제외 옵션
            skip_failed_tag = self.gui.skip_failed_tag_var.get() if hasattr(self.gui, 'skip_failed_tag_var') else False
            exclude_tag = "업로드실패" if skip_failed_tag else None

            products, total = self.api_client.get_products_by_group(
                group_name, 0, upload_count, status_filters, exclude_tag=exclude_tag
            )

            if not products:
                self.log(f"   ⚠️ {group_name}: 상품 없음")
                return 0, 0, 0, 0

            success = 0
            failed = 0
            duplicate_failed = 0
            skipped = 0
            total_products = len(products)

            for idx, product in enumerate(products, 1):
                if not self.is_running:
                    break

                result = self.process_product(product, group_name, option_count, option_sort, title_mode, skip_sku_update, skip_price_update, market_name, current_idx=idx, total_count=total_products)
                product_name = product.get('uploadCommonProductName', '')[:20]

                if result['status'] == 'success':
                    self.log(f"   ✅ {product_name.ljust(20)} | 성공 ({result['message']})")
                    success += 1
                elif result['status'] == 'skipped':
                    msg = result['message'][:40]
                    self.log(f"   ⏭️ {product_name.ljust(20)} | 건너뜀 ({msg})")
                    skipped += 1
                elif result['status'] == 'duplicate_failed':
                    msg = result['message'][:200]
                    self.log(f"   🔁 {product_name.ljust(20)} | 중복실패 ({msg})")
                    duplicate_failed += 1
                else:
                    msg = result['message'][:200]  # 에러 메시지는 200자까지
                    self.log(f"   ❌ {product_name.ljust(20)} | 실패 ({msg})")
                    failed += 1

            return success, failed, duplicate_failed, skipped

        except Exception as e:
            self.log(f"   ❌ {group_name} 처리 오류: {e}")
            return 0, 0, 0, 0

    def process_groups(self, group_names: List[str], upload_count: int,
                      option_count: int, option_sort: str, status_filters: List[str],
                      concurrent_sessions: int, title_mode: str = "original",
                      skip_sku_update: bool = False, skip_price_update: bool = False,
                      market_name: str = "스마트스토어"):
        """여러 그룹 처리 (그룹명 = 마켓그룹, 그룹ID로 업로드)"""
        self.stats = {"total": 0, "success": 0, "failed": 0, "duplicate_failed": 0, "skipped": 0, "failed_ids": []}
        self._tagged_ids = set()  # 태그 추적 초기화
        self.is_running = True

        # 마켓 그룹 ID 매핑 미리 로드
        self.api_client.load_market_group_ids()

        self.log("")
        self.log("=" * 50)
        self.log(f"🚀 상품 업로드 시작")
        self.log(f"   그룹: {', '.join(group_names)}")
        self.log(f"   업로드마켓: {market_name}")
        self.log(f"   그룹당 업로드: {upload_count}개")
        self.log(f"   옵션 개수: {option_count if option_count > 0 else '전체'}")
        self.log(f"   옵션 정렬: {option_sort}")
        self.log(f"   동시 세션: {concurrent_sessions}")
        self.log(f"   환율: {self.price_settings.exchange_rate}")
        margin_str = f"{self.price_settings.margin_rate_min}~{self.price_settings.margin_rate_max}%" if self.price_settings.margin_rate_min != self.price_settings.margin_rate_max else f"{self.price_settings.margin_rate_min}%"
        self.log(f"   마진: {margin_str} + {self.price_settings.margin_fixed:,}원")
        discount_str = f"{self.price_settings.discount_rate_min}~{self.price_settings.discount_rate_max}%" if self.price_settings.discount_rate_min != self.price_settings.discount_rate_max else f"{self.price_settings.discount_rate_min}%"
        self.log(f"   할인율: {discount_str}")
        self.log("=" * 50)

        total_tasks = len(group_names)

        # [신규] 테스트 ID 모드 처리
        test_id = ""
        if self.gui and hasattr(self.gui, 'test_id_var'):
            test_id = self.gui.test_id_var.get().strip()
        
        if test_id:
            # 테스트 모드: 상품 정보에서 그룹 ID를 찾아 해당 그룹으로 처리
            self.log(f"🧪 [테스트 모드] 상품 ID '{test_id}' 단일 처리 시작")
            
            try:
                # 1. 상품 상세 정보 조회
                detail = self.api_client.get_product_detail(test_id)
                if not detail:
                     self.log(f"❌ 상품 ID '{test_id}' 정보를 가져올 수 없습니다. (존재하지 않거나 권한 없음)")
                     self.is_running = False
                     if self.gui: self.gui.on_finished()
                     return

                # 2. 소속 그룹 찾기 (uploadSelectedMarketGroupId)
                target_group_id = detail.get('uploadSelectedMarketGroupId')
                target_group_name = ""
                
                # 그룹 ID -> 그룹명 매핑 찾기
                # load_market_group_ids는 Name->ID 맵이므로 역검색 필요
                group_map = self.api_client.load_market_group_ids() # {name: id}
                
                # 역검색 (ID -> Name)
                for g_name, g_id in group_map.items():
                    if str(g_id) == str(target_group_id):
                        target_group_name = g_name
                        break
                
                if not target_group_name:
                    self.log(f"⚠️ 경고: 상품의 소속 그룹 ID({target_group_id})에 해당하는 그룹명을 찾을 수 없습니다.")
                    # 그룹을 못 찾으면 사용자가 선택한 그룹 중 첫 번째를 임시로 사용 (fallback)
                    if group_names:
                        target_group_name = group_names[0]
                        self.log(f"   👉 대체 그룹 사용: {target_group_name}")
                    else:
                        self.log(f"❌ 실패: 소속 그룹을 찾을 수 없고, 선택된 대체 그룹도 없습니다.")
                        self.is_running = False
                        if self.gui: self.gui.on_finished()
                        return
                else:
                    self.log(f"   ✅ 소속 그룹 감지: {target_group_name} (ID: {target_group_id})")

                # 3. 단일 상품 처리 (선택된 마켓 순회)
                # process_product에 넘길 product dict 구성 (Lite version)
                product_lite = {
                    'ID': test_id,
                    'uploadCommonProductName': detail.get('uploadCommonProductName', detail.get('productName', '테스트상품'))
                }

                # [수정] 선택된 모든 마켓에 대해 실행
                target_markets = []
                if self.gui and hasattr(self.gui, 'market_vars'):
                     target_markets = [name for name, var in self.gui.market_vars.items() if var.get()]
                
                if not target_markets:
                    # GUI 참조 불가 시 기본 인자 사용
                    target_markets = [market_name]

                self.log(f"   📋 대상 마켓: {', '.join(target_markets)}")

                for m_name in target_markets:
                    self.log(f"   ▶ [{m_name}] 업로드 시도...")
                    
                    result = self.process_product(
                        product_lite, target_group_name, option_count, option_sort,
                        title_mode, skip_sku_update, skip_price_update, m_name,
                        current_idx=1, total_count=1
                    )
                    
                    if result['status'] == 'success':
                        self.log(f"      ✅ 성공: {result['message']}")
                        self.stats['success'] += 1
                    elif result['status'] == 'skipped':
                        self.log(f"      ⏭️ 스킵: {result['message'][:100]}")
                        self.stats['skipped'] += 1
                    elif result['status'] == 'duplicate_failed':
                        self.log(f"      🔁 중복실패: {result['message'][:100]}...")
                        self.stats['duplicate_failed'] += 1
                    else:
                        self.log(f"      ❌ 실패: {result['message'][:100]}...")
                        self.stats['failed'] += 1

                self.stats['total'] = len(target_markets)

            except Exception as e:
                self.log(f"❌ 테스트 중 오류: {e}")
                import traceback
                self.log(traceback.format_exc())

            # 테스트 종료 처리
            self.log("")
            self.log("=" * 50)
            self.log(f"📊 테스트 결과 완료")
            self.log("=" * 50)
            self.is_running = False
            if self.gui:
                self.gui.on_finished()
            return
            
        # 일반 모드 (기존 로직)
        try:
            # [v1.4] 선택된 모든 마켓에 대해 순차 처리
            target_markets = []
            if self.gui and hasattr(self.gui, 'market_vars'):
                target_markets = [name for name, var in self.gui.market_vars.items() if var.get()]

            if not target_markets:
                target_markets = [market_name]  # fallback

            self.log(f"📋 대상 마켓: {', '.join(target_markets)}")

            # [v1.5] 멀티세션(동시세션 > 1)일 때는 단일 그룹만 처리
            # 여러 그룹 처리 시 업로더를 여러 개 실행하도록 안내
            if concurrent_sessions > 1 and len(group_names) > 1:
                self.log(f"⚠️ 멀티세션 모드: 첫 번째 그룹만 처리합니다 ({group_names[0]})")
                self.log(f"   💡 여러 그룹 병렬 처리는 업로더를 여러 개 실행하세요")
                group_names = [group_names[0]]

            # 업로드실패 태그 상품 제외 옵션
            skip_failed_tag = self.gui.skip_failed_tag_var.get() if hasattr(self.gui, 'skip_failed_tag_var') else False
            exclude_tag = "업로드실패" if skip_failed_tag else None

            # [v1.4] 그룹별로 상품 목록을 먼저 가져온 후, 동일한 상품들을 모든 마켓에 업로드
            for g_idx, group_name in enumerate(group_names):
                if not self.is_running: break

                # 상품 목록 한번만 가져오기
                products, total = self.api_client.get_products_by_group(
                    group_name, 0, upload_count, status_filters, exclude_tag=exclude_tag
                )

                if not products:
                    self.log(f"⚠️ {group_name}: 상품 없음")
                    continue

                self.log(f"\n📦 그룹: {group_name} ({len(products)}개 상품)")

                # [v1.5] 동시 세션 처리
                if concurrent_sessions > 1:
                    # 병렬 처리
                    stats_lock = threading.Lock()
                    completed_count = [0]

                    # 작업 목록 생성 (상품 × 마켓)
                    tasks = []
                    for p_idx, product in enumerate(products, 1):
                        for current_market in target_markets:
                            tasks.append((p_idx, product, current_market))

                    def process_task(task):
                        """단일 작업 처리 (스레드에서 실행)"""
                        if not self.is_running:
                            return None
                        p_idx, product, current_market = task
                        result = self.process_product(
                            product, group_name, option_count, option_sort,
                            title_mode, skip_sku_update, skip_price_update, current_market,
                            current_idx=p_idx, total_count=len(products)
                        )
                        return result

                    with ThreadPoolExecutor(max_workers=concurrent_sessions) as executor:
                        futures = {executor.submit(process_task, task): task for task in tasks}

                        for future in as_completed(futures):
                            if not self.is_running:
                                executor.shutdown(wait=False, cancel_futures=True)
                                break

                            result = future.result()
                            if result is None:
                                continue

                            with stats_lock:
                                if result['status'] == 'success':
                                    self.stats['success'] += 1
                                elif result['status'] == 'skipped':
                                    self.stats['skipped'] += 1
                                elif result['status'] == 'duplicate_failed':
                                    self.stats['duplicate_failed'] += 1
                                    fail_info = f"{result.get('id', '?')} ({result.get('name', '')[:15]}) [중복]"
                                    self.stats['failed_ids'].append(fail_info)
                                else:
                                    self.stats['failed'] += 1
                                    fail_info = f"{result.get('id', '?')} ({result.get('name', '')[:15]})"
                                    self.stats['failed_ids'].append(fail_info)
                                self.stats['total'] += 1
                                completed_count[0] += 1

                            if self.gui:
                                total_progress = g_idx * upload_count + completed_count[0] // len(target_markets)
                                total_tasks = len(group_names) * upload_count
                                self.gui.update_progress(total_progress, total_tasks)
                else:
                    # 순차 처리 (기존 로직)
                    for p_idx, product in enumerate(products, 1):
                        if not self.is_running: break

                        product_id = product.get('ID', '')
                        product_name = product.get('uploadCommonProductName', '')[:20]

                        for m_idx, current_market in enumerate(target_markets):
                            if not self.is_running: break

                            result = self.process_product(
                                product, group_name, option_count, option_sort,
                                title_mode, skip_sku_update, skip_price_update, current_market,
                                current_idx=p_idx, total_count=len(products)
                            )

                            if result['status'] == 'success':
                                self.stats['success'] += 1
                            elif result['status'] == 'skipped':
                                self.stats['skipped'] += 1
                            elif result['status'] == 'duplicate_failed':
                                self.stats['duplicate_failed'] += 1
                                fail_info = f"{result.get('id', '?')} ({result.get('name', '')[:15]}) [중복]"
                                self.stats['failed_ids'].append(fail_info)
                            else:
                                self.stats['failed'] += 1
                                # 실패 ID 저장 (상품명 포함)
                                fail_info = f"{result.get('id', '?')} ({result.get('name', '')[:15]})"
                                self.stats['failed_ids'].append(fail_info)
                            self.stats['total'] += 1

                        if self.gui:
                            total_progress = g_idx * upload_count + p_idx
                            total_tasks = len(group_names) * upload_count
                            self.gui.update_progress(total_progress, total_tasks)

            # 완료 요약 로그
            self.log("")
            self.log("=" * 50)
            self.log(f"📊 업로드 완료")
            self.log(f"   ✅ 성공: {self.stats['success']}개")
            self.log(f"   ❌ 실패: {self.stats['failed']}개")
            self.log(f"   🔁 중복실패: {self.stats['duplicate_failed']}개")
            self.log(f"   ⏭️ 건너뜀: {self.stats['skipped']}개")

            # 실패 ID 리스트 출력
            if self.stats['failed_ids']:
                self.log("")
                self.log(f"❌ 실패 목록 ({len(self.stats['failed_ids'])}개):")
                for fail_id in self.stats['failed_ids']:
                    self.log(f"   - {fail_id}")

            # 실패 상품 태그 적용 결과 (비동기로 이미 적용됨)
            if self._tagged_ids:
                self.log("")
                self.log(f"🏷️ '업로드실패' 태그 적용됨: {len(self._tagged_ids)}개 상품")

            self.log("=" * 50)

            if self.gui:
                self.gui.on_finished()

        except Exception as e:
             self.log(f"Error: {e}")
             import traceback
             self.log(traceback.format_exc())
             if self.gui:
                self.gui.on_finished()
        finally:
            self.is_running = False

    def run_upload(self, group_name, upload_count, option_count, option_sort, status_filters, concurrent_sessions, title_mode, skip_sku_update, skip_price_update, market_name):
        """단일 그룹 처리 (그룹명으로 마켓그룹ID 조회하여 업로드)"""
        try:
            # 업로드실패 태그 상품 제외 옵션
            skip_failed_tag = self.gui.skip_failed_tag_var.get() if hasattr(self.gui, 'skip_failed_tag_var') else False
            exclude_tag = "업로드실패" if skip_failed_tag else None

            products, total = self.api_client.get_products_by_group(
                group_name, 0, upload_count, status_filters, exclude_tag=exclude_tag
            )

            if not products:
                self.log(f"   ⚠️ {group_name}: 상품 없음")
                return 0, 0, 0, 0

            success = 0
            failed = 0
            duplicate_failed = 0
            skipped = 0
            total_products = len(products)
            for idx, product in enumerate(products, 1):
                if not self.is_running:
                    break

                result = self.process_product(product, group_name, option_count, option_sort, title_mode, skip_sku_update, skip_price_update, market_name, current_idx=idx, total_count=total_products)
                product_name = product.get('uploadCommonProductName', '')[:20]

                if result['status'] == 'success':
                    self.log(f"   ✅ {product_name}: 성공")
                    success += 1
                elif result['status'] == 'skipped':
                    self.log(f"   ⏭️ {product_name}: {result['message'][:50]}")
                    skipped += 1
                elif result['status'] == 'duplicate_failed':
                    self.log(f"   🔁 {product_name}: {result['message'][:70]}")
                    duplicate_failed += 1
                else:
                    self.log(f"   ❌ {product_name}: {result['message'][:70]}")
                    failed += 1

            return success, failed, duplicate_failed, skipped

        except Exception as e:
            self.log(f"   ❌ 그룹 처리 중 오류: {e}")
            return 0, 0, 0, 0


# ==================== GUI 클래스 ====================
class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("불사자 상품 업로더 v1.3")
        self.geometry("900x1000")
        self.resizable(True, True)

        self.config_data = load_config()
        self.uploader = BulsajaUploader(self)
        self.worker_thread = None
        self.market_groups = []

        self.create_widgets()
        self.load_saved_settings()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # === 1. API 연결 ===
        conn_frame = ttk.LabelFrame(main_frame, text="🔑 API 연결", padding="5")
        conn_frame.pack(fill=tk.X, pady=(0, 5))

        row0 = ttk.Frame(conn_frame)
        row0.pack(fill=tk.X, pady=2)
        ttk.Button(row0, text="🌐 크롬", command=self.open_debug_chrome, width=8).pack(side=tk.LEFT)
        ttk.Button(row0, text="🔑 토큰", command=self.extract_tokens, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(row0, text="🔗 연결", command=self.connect_api, width=8).pack(side=tk.LEFT, padx=2)
        self.api_status = ttk.Label(row0, text="연결 안 됨", foreground="gray")
        self.api_status.pack(side=tk.LEFT, padx=10)
        ttk.Label(row0, text="포트:").pack(side=tk.RIGHT)
        self.port_var = tk.StringVar(value="9222")
        ttk.Entry(row0, textvariable=self.port_var, width=6).pack(side=tk.RIGHT, padx=2)

        # === 2. 마진 설정 ===
        margin_frame = ttk.LabelFrame(main_frame, text="💰 마진설정", padding="5")
        margin_frame.pack(fill=tk.X, pady=(0, 5))

        row1 = ttk.Frame(margin_frame)
        row1.pack(fill=tk.X, pady=2)

        ttk.Label(row1, text="기준환율(위안):").pack(side=tk.LEFT)
        self.exchange_rate_var = tk.StringVar(value="215")
        ttk.Entry(row1, textvariable=self.exchange_rate_var, width=6).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row1, text="카드수수료(%):").pack(side=tk.LEFT)
        self.card_fee_var = tk.StringVar(value="3.3")
        ttk.Entry(row1, textvariable=self.card_fee_var, width=5).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row1, text="퍼센트마진(min,max):").pack(side=tk.LEFT)
        self.margin_rate_var = tk.StringVar(value="25,30")
        ttk.Entry(row1, textvariable=self.margin_rate_var, width=8).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row1, text="더하기마진(원):").pack(side=tk.LEFT)
        self.margin_fixed_var = tk.StringVar(value="15000")
        ttk.Entry(row1, textvariable=self.margin_fixed_var, width=7).pack(side=tk.LEFT, padx=2)

        row2 = ttk.Frame(margin_frame)
        row2.pack(fill=tk.X, pady=2)

        ttk.Label(row2, text="마켓할인율(min,max):").pack(side=tk.LEFT)
        self.discount_rate_var = tk.StringVar(value="20,30")
        ttk.Entry(row2, textvariable=self.discount_rate_var, width=8).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row2, text="가격단위올림(원):").pack(side=tk.LEFT)
        self.round_unit_var = tk.StringVar(value="100")
        ttk.Entry(row2, textvariable=self.round_unit_var, width=5).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row2, text="해외배송비(원):").pack(side=tk.LEFT)
        self.delivery_fee_var = tk.StringVar(value="0")
        ttk.Entry(row2, textvariable=self.delivery_fee_var, width=7).pack(side=tk.LEFT, padx=2)

        # === 3. 상품업로드 설정 ===
        upload_frame = ttk.LabelFrame(main_frame, text="📤 상품업로드 설정", padding="5")
        upload_frame.pack(fill=tk.X, pady=(0, 5))

        row3 = ttk.Frame(upload_frame)
        row3.pack(fill=tk.X, pady=2)

        ttk.Label(row3, text="업로드수:").pack(side=tk.LEFT)
        self.upload_count_var = tk.StringVar(value="9000")
        ttk.Entry(row3, textvariable=self.upload_count_var, width=6).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row3, text="동시세션:").pack(side=tk.LEFT)
        self.concurrent_var = tk.StringVar(value="1")
        ttk.Combobox(row3, textvariable=self.concurrent_var, width=4,
                     values=["1", "2", "3", "4", "5"]).pack(side=tk.LEFT, padx=2)

        row4 = ttk.Frame(upload_frame)
        row4.pack(fill=tk.X, pady=2)

        ttk.Label(row4, text="상품명:").pack(side=tk.LEFT)
        self.title_option_var = tk.StringVar(value="앞3개단어제외 셔플")
        ttk.Combobox(row4, textvariable=self.title_option_var, width=18,
                     values=list(TITLE_OPTIONS.keys())).pack(side=tk.LEFT, padx=(2, 10))

        # [신규] 테스트 업로드 설정
        ttk.Label(row4, text="테스트ID:").pack(side=tk.LEFT)
        self.test_id_var = tk.StringVar(value="")
        ttk.Entry(row4, textvariable=self.test_id_var, width=15).pack(side=tk.LEFT, padx=2)

        ttk.Label(row4, text="옵션수설정:").pack(side=tk.LEFT)
        self.option_count_var = tk.StringVar(value="10")
        ttk.Entry(row4, textvariable=self.option_count_var, width=5).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row4, text="옵션설정:").pack(side=tk.LEFT)
        self.option_sort_var = tk.StringVar(value="가격낮은순")
        ttk.Combobox(row4, textvariable=self.option_sort_var, width=10,
                     values=list(OPTION_SORT_OPTIONS.keys())).pack(side=tk.LEFT, padx=2)

        row5 = ttk.Frame(upload_frame)
        row5.pack(fill=tk.X, pady=2)

        ttk.Label(row5, text="업로드조건:").pack(side=tk.LEFT)
        self.upload_condition_var = tk.StringVar(value="미업로드(수집완료+수정중+검토완료)")
        ttk.Combobox(row5, textvariable=self.upload_condition_var, width=35,
                     values=list(UPLOAD_CONDITIONS.keys())).pack(side=tk.LEFT, padx=(2, 10))

        # 썸네일 매칭 옵션
        self.thumbnail_match_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row5, text="썸네일매칭 대표상품", variable=self.thumbnail_match_var).pack(side=tk.LEFT, padx=5)

        # 디버그: SKU 수정 건너뛰기 (테스트용)
        self.skip_sku_update_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row5, text="⚠️SKU수정안함", variable=self.skip_sku_update_var).pack(side=tk.LEFT, padx=5)

        # 가격 수정 안함 (exclude/main_product만 수정)
        self.skip_price_update_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row5, text="가격수정안함", variable=self.skip_price_update_var).pack(side=tk.LEFT, padx=5)

        # === 마켓 선택 ===
        market_row = ttk.Frame(upload_frame)
        market_row.pack(fill=tk.X, pady=2)

        ttk.Label(market_row, text="업로드마켓:").pack(side=tk.LEFT)
        self.market_vars = {}
        for market_name in MARKET_IDS.keys():
            var = tk.BooleanVar(value=(market_name == "스마트스토어"))  # 기본값: 스마트스토어만 선택
            self.market_vars[market_name] = var
            ttk.Checkbutton(market_row, text=market_name, variable=var).pack(side=tk.LEFT, padx=3)

        row6 = ttk.Frame(upload_frame)
        row6.pack(fill=tk.X, pady=2)

        ttk.Label(row6, text="옵션 최저가격:").pack(side=tk.LEFT)
        self.min_price_var = tk.StringVar(value="30000")
        ttk.Entry(row6, textvariable=self.min_price_var, width=10).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row6, text="옵션 최대가격:").pack(side=tk.LEFT)
        self.max_price_var = tk.StringVar(value="100000000")
        ttk.Entry(row6, textvariable=self.max_price_var, width=12).pack(side=tk.LEFT, padx=2)

        # === 마켓별 옵션 ===
        market_opt_row = ttk.Frame(upload_frame)
        market_opt_row.pack(fill=tk.X, pady=2)

        # ESM/11번가 할인율 3% 고정
        self.esm_discount_3_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(market_opt_row, text="ESM/11번가 할인3%", variable=self.esm_discount_3_var).pack(side=tk.LEFT, padx=5)

        # ESM 옵션명 표준화
        self.esm_option_normalize_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(market_opt_row, text="ESM옵션표준화", variable=self.esm_option_normalize_var).pack(side=tk.LEFT, padx=5)

        # SS 카테고리 재검색
        self.ss_category_search_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(market_opt_row, text="SS카테고리검색", variable=self.ss_category_search_var).pack(side=tk.LEFT, padx=5)

        # 해당 마켓 미업로드만 (이미 업로드된 마켓은 건너뛰기)
        self.skip_already_uploaded_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(market_opt_row, text="해당마켓 미업로드만", variable=self.skip_already_uploaded_var).pack(side=tk.LEFT, padx=5)

        # 불사자 중복 업로드 방지 (preventDuplicateUpload)
        # False 권장: 업로드 실패해도 불사자가 "시도함"으로 기록하여 재시도 차단됨
        self.prevent_duplicate_upload_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(market_opt_row, text="불사자중복방지", variable=self.prevent_duplicate_upload_var).pack(side=tk.LEFT, padx=5)

        # 업로드실패 태그 상품 건너뛰기 (groupFile 필터)
        self.skip_failed_tag_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(market_opt_row, text="실패태그건너뜀", variable=self.skip_failed_tag_var).pack(side=tk.LEFT, padx=5)

        # === 제외 카테고리 설정 ===
        exclude_cat_frame = ttk.LabelFrame(main_frame, text="🚫 제외 카테고리 (카테고리명에 포함시 업로드 패스)", padding="5")
        exclude_cat_frame.pack(fill=tk.X, pady=(0, 5))

        exclude_cat_row = ttk.Frame(exclude_cat_frame)
        exclude_cat_row.pack(fill=tk.X, pady=2)

        ttk.Label(exclude_cat_row, text="제외 키워드 (쉼표 구분):").pack(side=tk.LEFT)
        ttk.Button(exclude_cat_row, text="비우기", command=lambda: self.exclude_cat_text.delete("1.0", tk.END), width=6).pack(side=tk.RIGHT)

        self.exclude_cat_text = scrolledtext.ScrolledText(exclude_cat_frame, height=2, width=80,
                                                           font=('Consolas', 9))
        self.exclude_cat_text.pack(fill=tk.X, expand=True)
        # 기본값: 비어있음 (예시: 건강식품,의약품,화장품)

        # === 금지 키워드 설정 (상품명 기준) ===
        banned_kw_frame = ttk.LabelFrame(main_frame, text="🚫 금지 키워드 (상품명에 포함시 업로드 패스)", padding="5")
        banned_kw_frame.pack(fill=tk.X, pady=(0, 5))

        banned_kw_row = ttk.Frame(banned_kw_frame)
        banned_kw_row.pack(fill=tk.X, pady=2)

        ttk.Label(banned_kw_row, text="금지 키워드 (쉼표 구분):").pack(side=tk.LEFT)
        ttk.Button(banned_kw_row, text="비우기", command=lambda: self.banned_kw_text.delete("1.0", tk.END), width=6).pack(side=tk.RIGHT)

        self.banned_kw_text = scrolledtext.ScrolledText(banned_kw_frame, height=2, width=80,
                                                         font=('Consolas', 9))
        self.banned_kw_text.pack(fill=tk.X, expand=True)
        # 기본값: 비어있음 (예시: 성인용품,담배,주류)

        # === 4. 마켓그룹 설정 ===
        group_frame = ttk.LabelFrame(main_frame, text="📁 마켓그룹 설정", padding="5")
        group_frame.pack(fill=tk.X, pady=(0, 5))

        row7 = ttk.Frame(group_frame)
        row7.pack(fill=tk.X, pady=2)

        ttk.Label(row7, text="작업 그룹 (순서 처리)").pack(side=tk.LEFT)
        ttk.Label(row7, text="그룹:").pack(side=tk.LEFT, padx=(10, 0))
        self.work_groups_var = tk.StringVar(value="13")
        ttk.Entry(row7, textvariable=self.work_groups_var, width=15).pack(side=tk.LEFT, padx=2)
        ttk.Label(row7, text="(예: 13 또는 1-5 또는 1,3,5)", foreground="gray").pack(side=tk.LEFT, padx=5)
        ttk.Button(row7, text="📥 그룹목록", command=self.load_market_groups, width=10).pack(side=tk.RIGHT)

        row8 = ttk.Frame(group_frame)
        row8.pack(fill=tk.X, pady=2)

        ttk.Label(row8, text="마켓 그룹 목록 (쉼표 구분, 숫자 맵핑용):").pack(anchor=tk.W)

        # 그룹 텍스트 입력
        group_text_frame = ttk.Frame(group_frame)
        group_text_frame.pack(fill=tk.X, pady=2)

        self.group_text = scrolledtext.ScrolledText(group_text_frame, height=3, width=80,
                                                     font=('Consolas', 9))
        self.group_text.pack(fill=tk.X, expand=True)

        ttk.Label(group_frame, text="예: 01_푸로테카,02_스트롬브린,03_코드리크 → 작업그룹에서 1, 1-3, 2,4 등으로 사용",
                  foreground="gray").pack(anchor=tk.W)

        # === 5. 미끼 키워드 설정 ===
        keyword_frame = ttk.LabelFrame(main_frame, text="🚫 미끼 키워드 (옵션명에 포함시 제외)", padding="5")
        keyword_frame.pack(fill=tk.X, pady=(0, 5))

        keyword_row1 = ttk.Frame(keyword_frame)
        keyword_row1.pack(fill=tk.X, pady=2)

        ttk.Label(keyword_row1, text="제외 키워드 (쉼표 구분):").pack(side=tk.LEFT)
        ttk.Button(keyword_row1, text="기본값", command=self.reset_keywords, width=6).pack(side=tk.RIGHT)

        self.keyword_text = scrolledtext.ScrolledText(keyword_frame, height=2, width=80,
                                                       font=('Consolas', 9))
        self.keyword_text.pack(fill=tk.X, expand=True)
        # 기본 키워드 로드
        self.keyword_text.insert("1.0", ','.join(EXCLUDE_KEYWORDS))

        # === 진행 상태 ===
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 5))

        self.progress_var = tk.StringVar(value="대기 중...")
        ttk.Label(progress_frame, textvariable=self.progress_var).pack(side=tk.LEFT)
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress_bar.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))

        # === 버튼 ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 5))

        self.btn_start = ttk.Button(btn_frame, text="🚀 업로드 시작", command=self.start_upload)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_stop = ttk.Button(btn_frame, text="🛑 중지", command=self.stop, state="disabled")
        self.btn_stop.pack(side=tk.LEFT)

        # 서버 연결 버튼
        self.server_connected = False
        self.btn_server = ttk.Button(btn_frame, text="🔗 서버 연결", command=self.toggle_server_connection)
        self.btn_server.pack(side=tk.LEFT, padx=(10, 0))

        ttk.Button(btn_frame, text="💾 설정 저장", command=self.save_settings).pack(side=tk.RIGHT)

        # === 로그 ===
        log_frame = ttk.LabelFrame(main_frame, text="📋 로그", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)

        # tk.Text + Scrollbar (색상 태그 지원)
        log_container = ttk.Frame(log_frame)
        log_container.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_container, height=12, state='disabled',
                                font=('Segoe UI Emoji', 10), wrap=tk.WORD)
        log_scrollbar = ttk.Scrollbar(log_container, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)

        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 로그 색상 태그 설정 (아이콘별 고유 컬러 에뮬레이션)
        self.log_text.tag_configure("error", foreground="#E60000")    # 선명한 빨강
        self.log_text.tag_configure("success", foreground="#00CC00")  # 밝은 초록
        self.log_text.tag_configure("warning", foreground="#FF8C00")  # 오렌지
        self.log_text.tag_configure("info", foreground="#007AFF")     # 정보 파랑
        self.log_text.tag_configure("skip", foreground="#808080")     # 회색
        
        # 특정 아이콘 전용 컬러
        self.log_text.tag_configure("icon_gold", foreground="#FFB700")   # 왕관/금색
        self.log_text.tag_configure("icon_brown", foreground="#A0522D")  # 상자/갈색
        self.log_text.tag_configure("icon_gear", foreground="#555555")   # 톱니/어두운 회색
        self.log_text.tag_configure("icon_blue", foreground="#007AFF")   # 업로드/파랑
        self.log_text.tag_configure("icon_green", foreground="#32CD32")  # 차트/밝은 초록
        self.log_text.tag_configure("icon_red", foreground="#FF0000")    # 실패/빨강
        self.log_text.tag_configure("icon_black", foreground="#000000")  # 카테고리/검정

        # 마켓 플랫폼별 색상
        self.log_text.tag_configure("market_N", foreground="#00CC00")    # 스마트스토어 - 초록
        self.log_text.tag_configure("market_11", foreground="#E60000")   # 11번가 - 빨강
        self.log_text.tag_configure("market_C", foreground="#00BFFF")    # 쿠팡 - 하늘색
        self.log_text.tag_configure("market_G", foreground="#0066FF")    # 지마켓 - 파랑
        self.log_text.tag_configure("market_A", foreground="#9932CC")    # 옥션 - 자주색

        # Footer
        footer = ttk.Frame(main_frame)
        footer.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(footer, text="v1.3 by 프코노미", foreground="gray").pack(side=tk.RIGHT)

    def load_saved_settings(self):
        c = self.config_data
        if "port" in c: self.port_var.set(c["port"])
        if "exchange_rate" in c: self.exchange_rate_var.set(c["exchange_rate"])
        if "card_fee" in c: self.card_fee_var.set(c["card_fee"])
        if "margin_rate" in c: self.margin_rate_var.set(c["margin_rate"])
        if "margin_fixed" in c: self.margin_fixed_var.set(c["margin_fixed"])
        if "discount_rate" in c: self.discount_rate_var.set(c["discount_rate"])
        if "round_unit" in c: self.round_unit_var.set(c["round_unit"])
        if "delivery_fee" in c: self.delivery_fee_var.set(c["delivery_fee"])
        if "upload_count" in c: self.upload_count_var.set(c["upload_count"])
        if "concurrent" in c: self.concurrent_var.set(c["concurrent"])
        if "option_count" in c: self.option_count_var.set(c["option_count"])
        if "option_sort" in c: self.option_sort_var.set(c["option_sort"])
        if "min_price" in c: self.min_price_var.set(c["min_price"])
        if "max_price" in c: self.max_price_var.set(c["max_price"])
        if "work_groups" in c: self.work_groups_var.set(c["work_groups"])
        if "group_text" in c:
            self.group_text.delete("1.0", tk.END)
            self.group_text.insert("1.0", c["group_text"])
        if "exclude_keywords" in c:
            self.keyword_text.delete("1.0", tk.END)
            self.keyword_text.insert("1.0", c["exclude_keywords"])
        if "thumbnail_match" in c:
            self.thumbnail_match_var.set(c["thumbnail_match"])
        if "markets" in c:
            for market_name, var in self.market_vars.items():
                var.set(market_name in c["markets"])
        if "skip_failed_tag" in c:
            self.skip_failed_tag_var.set(c["skip_failed_tag"])
        if "exclude_categories" in c:
            self.exclude_cat_text.delete("1.0", tk.END)
            self.exclude_cat_text.insert("1.0", c["exclude_categories"])
        if "banned_keywords" in c:
            self.banned_kw_text.delete("1.0", tk.END)
            self.banned_kw_text.insert("1.0", c["banned_keywords"])

    def save_settings(self):
        self.config_data["port"] = self.port_var.get()
        self.config_data["exchange_rate"] = self.exchange_rate_var.get()
        self.config_data["card_fee"] = self.card_fee_var.get()
        self.config_data["margin_rate"] = self.margin_rate_var.get()
        self.config_data["margin_fixed"] = self.margin_fixed_var.get()
        self.config_data["discount_rate"] = self.discount_rate_var.get()
        self.config_data["round_unit"] = self.round_unit_var.get()
        self.config_data["delivery_fee"] = self.delivery_fee_var.get()
        self.config_data["upload_count"] = self.upload_count_var.get()
        self.config_data["concurrent"] = self.concurrent_var.get()
        self.config_data["option_count"] = self.option_count_var.get()
        self.config_data["option_sort"] = self.option_sort_var.get()
        self.config_data["min_price"] = self.min_price_var.get()
        self.config_data["max_price"] = self.max_price_var.get()
        self.config_data["work_groups"] = self.work_groups_var.get()
        self.config_data["group_text"] = self.group_text.get("1.0", tk.END).strip()
        self.config_data["exclude_keywords"] = self.keyword_text.get("1.0", tk.END).strip()
        self.config_data["thumbnail_match"] = self.thumbnail_match_var.get()
        self.config_data["markets"] = [name for name, var in self.market_vars.items() if var.get()]
        self.config_data["skip_failed_tag"] = self.skip_failed_tag_var.get()
        self.config_data["exclude_categories"] = self.exclude_cat_text.get("1.0", tk.END).strip()
        self.config_data["banned_keywords"] = self.banned_kw_text.get("1.0", tk.END).strip()
        save_config(self.config_data)
        self.log("✅ 설정 저장됨")

    def log(self, message):
        def _log():
            self.log_text.config(state='normal')
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            # 타임스탬프 삽입 (회색)
            self.log_text.insert(tk.END, f"[{timestamp}] ", "skip")

            # 메시지 성격에 따른 기본 태그 결정
            base_tag = None
            if any(x in message for x in ["❌", "실패", "에러", "오류"]): base_tag = "error"
            elif any(x in message for x in ["✅", "성공", "완료"]): base_tag = "success"
            elif any(x in message for x in ["⚠️", "경고", "주의"]): base_tag = "warning"
            elif any(x in message for x in ["스킵", "건너뜀", "제외", "⏭️"]): base_tag = "skip"
            elif any(x in message for x in ["📤", "🚀", "🔍"]): base_tag = "info"

            # 아이콘별 개별 색상 입히기 (Tkinter 흑백 이모지 대응)
            import re
            # 주요 아이콘 패턴 (문자열 내 이모지 추출)
            # 윈도우 Tkinter에서 흑백으로 나오는 것들을 색상 태그로 입힘
            emoji_color_map = {
                "👑": "icon_gold",
                "📦": "icon_brown",
                "⚙️": "icon_gear",
                "🏷️": "icon_black",
                "📤": "icon_blue", "📥": "icon_blue", "🚀": "icon_blue", "🔍": "icon_blue", "🔗": "icon_blue",
                "📊": "icon_green", "📈": "icon_green", "📉": "icon_green", "💹": "icon_green", "✅": "success",
                "❌": "error", "🛑": "error",
                "⚠️": "warning", "⏭️": "skip", "🧹": "skip", "🧼": "skip"
            }
            
            # 마켓 플랫폼 패턴 색상 매핑
            market_tag_map = {
                "[N]": "market_N",     # 스마트스토어 - 초록
                "[11]": "market_11",   # 11번가 - 빨강
                "[C]": "market_C",     # 쿠팡 - 하늘색
                "[G]": "market_G",     # 지마켓 - 파랑
                "[A]": "market_A",     # 옥션 - 자주색
            }

            # 메시지 파싱 (마켓 태그와 이모지 처리)
            i = 0
            while i < len(message):
                # 마켓 태그 체크
                matched_market = None
                for pattern, tag in market_tag_map.items():
                    if message[i:].startswith(pattern):
                        matched_market = (pattern, tag)
                        break

                if matched_market:
                    pattern, tag = matched_market
                    self.log_text.insert(tk.END, pattern, tag)
                    i += len(pattern)
                elif message[i] in emoji_color_map:
                    self.log_text.insert(tk.END, message[i], emoji_color_map[message[i]])
                    i += 1
                else:
                    self.log_text.insert(tk.END, message[i], base_tag)
                    i += 1
            
            self.log_text.insert(tk.END, "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')
        self.after(0, _log)

    def update_progress(self, current, total):
        def _update():
            self.progress_var.set(f"{current}/{total} 그룹 처리 중...")
            self.progress_bar['value'] = (current / total) * 100 if total > 0 else 0
        self.after(0, _update)

    # ========== 서버 연결 기능 ==========
    def toggle_server_connection(self):
        """서버 연결/해제 토글"""
        if self.server_connected:
            self.disconnect_server()
        else:
            self.connect_server()

    def connect_server(self):
        """서버에 WebSocket 연결"""
        try:
            # 서버 URL 입력 받기
            server_url = tk.simpledialog.askstring(
                "서버 연결",
                "서버 URL을 입력하세요:",
                initialvalue="ws://localhost:8000/ws/upload"
            )
            if not server_url:
                return

            self.log(f"🔗 서버 연결 시도: {server_url}")

            # WebSocket 연결 (백그라운드 스레드)
            def connect_ws():
                try:
                    import websocket
                    self.ws = websocket.WebSocket()
                    self.ws.connect(server_url, timeout=10)
                    self.server_connected = True
                    self.after(0, lambda: self.btn_server.config(text="🔌 연결 해제"))
                    self.log("✅ 서버 연결 성공")

                    # 초기 상태 전송
                    self.send_server_status("connected")

                    # 메시지 수신 루프
                    while self.server_connected:
                        try:
                            msg = self.ws.recv()
                            if msg:
                                self.handle_server_message(json.loads(msg))
                        except websocket.WebSocketTimeoutException:
                            continue
                        except Exception as e:
                            if self.server_connected:
                                self.log(f"⚠️ 수신 오류: {e}")
                            break

                except Exception as e:
                    self.log(f"❌ 서버 연결 실패: {e}")
                    self.server_connected = False

            threading.Thread(target=connect_ws, daemon=True).start()

        except Exception as e:
            self.log(f"❌ 연결 오류: {e}")

    def disconnect_server(self):
        """서버 연결 해제"""
        try:
            self.server_connected = False
            if hasattr(self, 'ws') and self.ws:
                self.ws.close()
                self.ws = None
            self.btn_server.config(text="🔗 서버 연결")
            self.log("🔌 서버 연결 해제됨")
        except Exception as e:
            self.log(f"⚠️ 연결 해제 오류: {e}")

    def send_server_status(self, status: str, data: dict = None):
        """서버에 상태 전송"""
        if not self.server_connected or not hasattr(self, 'ws') or not self.ws:
            return
        try:
            msg = {
                "type": "status",
                "status": status,
                "timestamp": datetime.now().isoformat()
            }
            if data:
                msg.update(data)
            self.ws.send(json.dumps(msg))
        except Exception as e:
            self.log(f"⚠️ 상태 전송 실패: {e}")

    def send_server_progress(self, current: int, total: int, message: str = ""):
        """서버에 진행상황 전송"""
        self.send_server_status("progress", {
            "current": current,
            "total": total,
            "percent": round(current / total * 100, 1) if total > 0 else 0,
            "message": message
        })

    def handle_server_message(self, msg: dict):
        """서버에서 받은 메시지 처리"""
        msg_type = msg.get("type", "")
        self.log(f"📨 서버 메시지: {msg_type}")

        if msg_type == "start_upload":
            # 서버에서 업로드 시작 명령
            self.log("🚀 서버 명령: 업로드 시작")
            self.after(0, self.start_upload)

        elif msg_type == "stop_upload":
            # 서버에서 중지 명령
            self.log("🛑 서버 명령: 업로드 중지")
            self.after(0, self.stop)

        elif msg_type == "update_settings":
            # 서버에서 설정 업데이트
            settings = msg.get("settings", {})
            self.log(f"⚙️ 서버 명령: 설정 업데이트")
            # TODO: 설정 반영

    def parse_group_mapping(self) -> Dict[str, str]:
        """그룹 매핑 텍스트 파싱 (시뮬레이터와 동일한 로직)

        그룹명 형식이 '22_리코즈' 처럼 숫자_이름 형태면 → 숫자(22)로 매핑
        그 외에는 순서대로 1,2,3... 매핑
        """
        mapping = {}
        text = self.group_text.get("1.0", tk.END).strip()
        if not text:
            return mapping

        groups = [g.strip() for g in text.split(',') if g.strip()]

        # 숫자 접두사가 있는지 확인 (예: "22_리코즈")
        has_prefix_pattern = False
        import re
        prefix_pattern = re.compile(r'^(\d+)[_\-]')

        for group_name in groups:
            match = prefix_pattern.match(group_name)
            if match:
                has_prefix_pattern = True
                break

        if has_prefix_pattern:
            # 그룹명에 숫자 접두사가 있으면 그 숫자로 매핑
            for group_name in groups:
                match = prefix_pattern.match(group_name)
                if match:
                    num_str = match.group(1)
                    # 01, 1 둘 다 같은 그룹으로 매핑
                    mapping[num_str] = group_name
                    mapping[str(int(num_str))] = group_name  # 앞의 0 제거 버전
                    mapping[f"{int(num_str):02d}"] = group_name  # 2자리 포맷
        else:
            # 숫자 접두사가 없으면 순서대로 매핑
            for idx, group_name in enumerate(groups, 1):
                mapping[str(idx)] = group_name
                mapping[f"{idx:02d}"] = group_name

        return mapping

    def parse_work_range(self, range_str: str) -> List[str]:
        """작업 범위 파싱 (1-20 또는 1,3,5)"""
        result = []
        range_str = range_str.strip()
        if '-' in range_str and ',' not in range_str:
            parts = range_str.split('-')
            if len(parts) == 2:
                try:
                    start = int(parts[0])
                    end = int(parts[1])
                    for i in range(start, end + 1):
                        result.append(str(i))
                except ValueError:
                    pass
        else:
            for item in range_str.split(','):
                item = item.strip()
                if item:
                    result.append(item)
        return result

    def get_group_names_from_range(self) -> List[str]:
        """작업 범위에서 실제 그룹명 목록 가져오기"""
        mapping = self.parse_group_mapping()
        range_nums = self.parse_work_range(self.work_groups_var.get())
        group_names = []
        for num in range_nums:
            if num in mapping:
                group_names.append(mapping[num])
            else:
                self.log(f"⚠️ 그룹 번호 {num}에 해당하는 그룹명 없음")
        return group_names

    def reset_keywords(self):
        """미끼 키워드를 기본값으로 초기화 (bulsaja_common에서 로드)"""
        self.keyword_text.delete("1.0", tk.END)
        keywords = load_bait_keywords()  # 최신 키워드 다시 로드
        self.keyword_text.insert("1.0", ','.join(keywords))
        self.log("🔄 미끼 키워드 기본값으로 초기화")

    def get_exclude_keywords(self) -> List[str]:
        """현재 설정된 제외 키워드 목록 반환"""
        text = self.keyword_text.get("1.0", tk.END).strip()
        if not text:
            return load_bait_keywords()  # common에서 로드
        return [k.strip() for k in text.split(',') if k.strip()]

    def open_debug_chrome(self):
        import subprocess
        port = int(self.port_var.get().strip())
        profile_dir = f"C:\\chrome_debug_profile_{port}"
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        chrome_path = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_path = path
                break
        if not chrome_path:
            messagebox.showerror("오류", "Chrome을 찾을 수 없습니다")
            return
        url = "https://www.bulsaja.com/products/manage/list/"
        cmd = f'"{chrome_path}" --remote-debugging-port={port} --user-data-dir="{profile_dir}" --remote-allow-origins=* "{url}"'
        try:
            subprocess.Popen(cmd, shell=True)
            self.log(f"🌐 크롬 실행 (포트: {port})")
        except Exception as e:
            self.log(f"❌ 크롬 실행 실패: {e}")

    def extract_tokens(self):
        port = int(self.port_var.get().strip())
        self.log(f"🔍 토큰 추출 중...")

        def task():
            success, access, refresh, err = self.uploader.extract_tokens_from_browser(port)
            if success:
                self.config_data["access_token"] = access
                self.config_data["refresh_token"] = refresh
                self.log("✅ 토큰 추출 성공")
                self.after(500, self.connect_api)
            else:
                self.log(f"❌ 토큰 추출 실패: {err}")

        threading.Thread(target=task, daemon=True).start()

    def connect_api(self):
        access = self.config_data.get("access_token", "")
        refresh = self.config_data.get("refresh_token", "")
        if not access or not refresh:
            messagebox.showwarning("경고", "먼저 토큰을 추출하세요")
            return
        self.log("🔗 API 연결 중...")
        success, msg, total = self.uploader.init_api_client(access, refresh)
        if success:
            self.api_status.config(text=f"✅ 연결됨 ({total}개)", foreground="green")
            self.log(f"✅ {msg}")
        else:
            self.api_status.config(text="❌ 실패", foreground="red")
            self.log(f"❌ 연결 실패: {msg}")

    def load_market_groups(self):
        if not self.uploader.api_client:
            messagebox.showwarning("경고", "먼저 API에 연결하세요")
            return

        self.log("📥 마켓 그룹 목록 조회 중...")

        try:
            groups = self.uploader.api_client.get_market_groups()
            if groups:
                # 그룹 이름만 추출
                group_names = [g.get('name', '') for g in groups if g.get('name')]
                self.group_text.delete("1.0", tk.END)
                self.group_text.insert("1.0", ','.join(group_names))
                self.log(f"✅ {len(group_names)}개 그룹 로드됨")
                # 전체 그룹 ID 정보 로그
                self.log("=" * 40)
                self.log("📁 마켓그룹 ID 매핑")
                for g in groups:
                    self.log(f"   {g.get('name')}: ID={g.get('id')}")
                self.log("=" * 40)
            else:
                self.log("⚠️ 그룹 없음 또는 조회 실패")
        except Exception as e:
            self.log(f"❌ 그룹 로드 실패: {e}")

    def parse_range(self, value: str) -> Tuple[float, float]:
        """'25,30' 형식의 문자열을 (min, max) 튜플로 파싱"""
        value = value.strip()
        if ',' in value:
            parts = value.split(',')
            return float(parts[0].strip()), float(parts[1].strip())
        else:
            v = float(value)
            return v, v

    def get_price_settings(self) -> PriceSettings:
        margin_min, margin_max = self.parse_range(self.margin_rate_var.get())
        discount_min, discount_max = self.parse_range(self.discount_rate_var.get())
        return PriceSettings(
            exchange_rate=float(self.exchange_rate_var.get()),
            card_fee_rate=float(self.card_fee_var.get()),
            margin_rate_min=margin_min,
            margin_rate_max=margin_max,
            margin_fixed=int(self.margin_fixed_var.get()),
            discount_rate_min=discount_min,
            discount_rate_max=discount_max,
            delivery_fee=int(self.delivery_fee_var.get()),
            round_unit=int(self.round_unit_var.get()),
            min_price=int(self.min_price_var.get()),
            max_price=int(self.max_price_var.get()),
        )

    def start_upload(self):
        if not self.uploader.api_client:
            messagebox.showwarning("경고", "먼저 API에 연결하세요")
            return

        group_names = self.get_group_names_from_range()
        if not group_names:
            messagebox.showwarning("경고", "작업할 그룹이 없습니다. 작업범위와 그룹목록을 확인하세요.")
            return

        try:
            self.uploader.price_settings = self.get_price_settings()
        except ValueError as e:
            messagebox.showerror("오류", f"설정값 오류: {e}")
            return

        # 제외 키워드 설정
        self.uploader.exclude_keywords = self.get_exclude_keywords()

        # 썸네일 매칭 설정 (전역 변수)
        global THUMBNAIL_MATCH_ENABLED
        THUMBNAIL_MATCH_ENABLED = self.thumbnail_match_var.get()

        upload_count = int(self.upload_count_var.get())
        option_count = int(self.option_count_var.get())
        option_sort = OPTION_SORT_OPTIONS.get(self.option_sort_var.get(), "none")
        title_mode = TITLE_OPTIONS.get(self.title_option_var.get(), "original")
        concurrent_sessions = int(self.concurrent_var.get())
        status_filters = UPLOAD_CONDITIONS.get(self.upload_condition_var.get(), ["0", "1", "2"])
        skip_sku_update = self.skip_sku_update_var.get()
        skip_price_update = self.skip_price_update_var.get()

        # 선택된 마켓 이름 (하나만 선택 가능하도록 첫 번째 선택된 것 사용)
        selected_markets = [name for name, var in self.market_vars.items() if var.get()]
        if not selected_markets:
            messagebox.showwarning("경고", "업로드할 마켓을 선택하세요")
            return
        selected_market_name = selected_markets[0]  # 첫 번째 선택된 마켓

        if skip_sku_update:
            self.log("⚠️ SKU 수정 건너뛰기 모드")
        if skip_price_update:
            self.log("⚠️ 가격 수정 안함 모드 (exclude/main_product만 수정)")

        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")

        self.worker_thread = threading.Thread(
            target=self.uploader.process_groups,
            args=(group_names, upload_count, option_count,
                  option_sort, status_filters, concurrent_sessions, title_mode, skip_sku_update, skip_price_update, selected_market_name),
            daemon=True
        )
        self.worker_thread.start()

    def stop(self):
        self.uploader.is_running = False
        self.log("🛑 중지 요청...")

    def on_finished(self):
        def _update():
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.progress_var.set("완료")
        self.after(0, _update)

    def on_close(self):
        self.uploader.is_running = False
        self.save_settings()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
