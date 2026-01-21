# -*- coding: utf-8 -*-
"""
불사자 상품 업로더 v1.2
- 구글시트 설정 화면과 동일한 GUI
- 마켓 그룹 선택 (다중 선택)
- 동시 세션 설정
- 옵션 설정 (개수, 정렬, 필터링)
- 그룹별 마켓 ID 동적 매핑 (v1.2)

by 프코노미
"""

import os
import time
import threading
import json
import math
import requests
import websocket
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import concurrent.futures

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# 공통 모듈 (미끼 옵션 필터링, 대표옵션 선택, API 클라이언트)
from bulsaja_common import filter_bait_options, DEFAULT_BAIT_KEYWORDS, select_main_option, BulsajaAPIClient as CommonAPIClient

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
    "쿠팡": "COUPANG",
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
EXCLUDE_KEYWORDS = [
    # 맞춤/주문제작 관련
    '맞춤', '맞춤형', '맞춤제작', '커스텀', 'custom', 'DIY',
    '주문제작', '주문 제작', '제작문의', '별도제작', '특별제작',

    # 계약/예약금 관련
    '계약', '계약금', '선금', '예약금', '보증금', '착수금',
    '정금', '잔금', '추가금', '차액',

    # 문의/상담 관련
    '고객센터', '상담', '연락주세요', '전화주세요',
    '채팅문의', '문의요망', '문의필수', '먼저문의',

    # 비고/안내 관련
    '비고', '참고', '안내', '공지', '필독', '주의', '확인필수',

    # 부품/액세서리 미끼
    '부품', '부속', '액세서리', '소모품', '교체품', '리필',
    '충전기', '어댑터', '케이블', '선만', '젠더',

    # 샘플/테스트
    '샘플', 'sample', '테스트', 'test', '무료체험', '체험판',

    # 옵션 선택 유도
    '옵션선택', '옵션필수', '필수선택', '선택필수', '색상선택', '사이즈선택',
    '옵션확인', '옵션문의', '선택안함', '해당없음',

    # 배송/추가비용 관련
    '배송비', '추가배송', '도서산간', '제주', '택배비',
    '설치비', '조립비', '출장비',

    # 가격 미끼
    '1원', '10원', '100원', '0원', '무료', 'free',
    '할인쿠폰', '쿠폰', '적립금',

    # 중국어 미끼 (타오바오)
    '定制', '定做', '订制', '订做',  # 맞춤제작
    '联系', '咨询', '客服',  # 문의/상담
    '配件', '零件', '附件',  # 부품/액세서리
    '邮费', '运费',  # 배송비
    '样品', '试用',  # 샘플

    # 중국어 버전/등급 구분선 (저가 미끼 표시)
    '以下是轻盈款', '以下是轻便款', '以下是简易款', '以下是基础款',  # 가벼운/간이/기초
    '以下是入门款', '以下是经济款', '以下是简约款', '以下是普通款',  # 입문/경제/심플/보통
    '轻盈款', '轻便款',  # 가벼운 버전 (구분선 없이도)
]


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

    # 미끼 판별: 최저가 클러스터가 전체의 min_cluster_ratio 미만이면 미끼
    bait_ids = []
    if len(clusters) >= 2:
        lowest_cluster = cluster_info[0]
        next_cluster = cluster_info[1]

        # 조건: 최저가 그룹 비율 < 30% AND 다음 그룹과의 가격 갭이 2배 이상
        if lowest_cluster['ratio'] < min_cluster_ratio:
            price_gap = next_cluster['min_price'] / lowest_cluster['max_price'] if lowest_cluster['max_price'] > 0 else 0
            if price_gap >= gap_threshold:
                bait_ids = lowest_cluster['sku_ids']

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


def calculate_price(origin_price_cny: float, settings: PriceSettings) -> Tuple[int, int, float, float]:
    """
    가격 계산 (마진, 할인율 랜덤 적용)
    Returns: (원가(원), 판매가(원), 적용된 마진율, 적용된 할인율)
    """
    # 랜덤 마진율
    margin_rate = random.uniform(settings.margin_rate_min, settings.margin_rate_max)
    # 랜덤 할인율
    discount_rate = random.uniform(settings.discount_rate_min, settings.discount_rate_max)

    origin_price_krw = origin_price_cny * settings.exchange_rate
    price_with_fee = origin_price_krw * (1 + settings.card_fee_rate / 100)
    price_with_margin = price_with_fee * (1 + margin_rate / 100) + settings.margin_fixed
    sale_price = math.ceil(price_with_margin / settings.round_unit) * settings.round_unit
    return int(origin_price_krw), int(sale_price), margin_rate, discount_rate


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

    def upload_product(self, product_id: str, group_name: str, market_name: str = "스마트스토어") -> Tuple[bool, str]:
        """
        상품 업로드
        Args:
            product_id: 불사자 상품 ID
            group_name: 마켓 그룹명 (예: "03_코드리크")
            market_name: 업로드할 마켓 플랫폼명
        """
        # 그룹 내 마켓 ID 조회
        market_id = self.get_market_id_in_group(group_name, market_name)
        if not market_id:
            return False, f"그룹 '{group_name}'에서 '{market_name}' 마켓을 찾을 수 없음"

        market_type = MARKET_TYPES.get(market_name, "SMARTSTORE")

        url = f"{self.BASE_URL}/market/{market_id}/upload/"
        payload = {
            "productId": product_id,
            "notices": None,
            "preventDuplicateUpload": True,
            "removeDuplicateWords": True,
            "targetMarket": market_type,
        }

        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()

            try:
                result = response.json()
                if isinstance(result, dict):
                    if result.get('error') or result.get('errors'):
                        error_msg = result.get('error') or result.get('errors') or result.get('message', '')
                        return False, f"업로드 실패: {str(error_msg)[:100]}"
                    if result.get('success') == False:
                        return False, f"업로드 실패: {result.get('message', '알 수 없는 오류')[:100]}"
                    status = result.get('uploadStatus') or result.get('status')
                    if status and str(status).lower() in ['failed', 'error', 'failure']:
                        return False, f"업로드 실패: {result.get('message', status)[:100]}"
                return True, f"응답: {str(result)[:100]}"
            except:
                text = response.text[:100] if response.text else ""
                return True, f"raw: {text}"

        except requests.exceptions.HTTPError as e:
            error_detail = ""
            try:
                error_detail = e.response.text[:200]
            except:
                pass
            return False, f"HTTP {e.response.status_code}: {error_detail}"
        except Exception as e:
            return False, str(e)

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


# ==================== 업로더 클래스 ====================
class BulsajaUploader:
    def __init__(self, gui):
        self.gui = gui
        self.api_client: Optional[BulsajaAPIClient] = None
        self.is_running = False
        self.price_settings = PriceSettings()
        self.exclude_keywords = EXCLUDE_KEYWORDS[:]  # 제외 키워드 (GUI에서 업데이트 가능)
        self.stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0}

    def log(self, message):
        if self.gui:
            self.gui.log(message)
        else:
            print(message)

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
            origin_price = sku.get('_origin_price', 0)
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
            return sorted(skus, key=lambda x: x.get('_origin_price', 0))
        elif sort_type == "price_desc":
            return sorted(skus, key=lambda x: x.get('_origin_price', 0), reverse=True)
        elif sort_type == "price_main":
            # 주요가격대: 평균가에 가까운 옵션 우선
            if not skus:
                return skus
            # 전체 옵션의 평균 원가 계산
            total_price = sum(sku.get('_origin_price', 0) for sku in skus)
            avg_price = total_price / len(skus)
            def distance_from_avg(sku):
                return abs(sku.get('_origin_price', 0) - avg_price)
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
                if sku.get('_origin_price', 0) >= main_sku_price
            ]
            # 가격 오름차순 정렬
            eligible_skus.sort(key=lambda x: x.get('_origin_price', 0))
            return eligible_skus[:max_count]
        else:
            # 기존 방식: 앞에서부터 자르기
            if len(skus) > max_count:
                return skus[:max_count]
            return skus

    def process_product(self, product: Dict, group_name: str, option_count: int,
                       option_sort: str, title_mode: str = "original",
                       skip_sku_update: bool = False, skip_price_update: bool = False,
                       market_name: str = "스마트스토어") -> Dict:
        product_id = product.get('ID', '')
        product_name = product.get('uploadCommonProductName', '')[:25]

        result = {
            'id': product_id,
            'name': product_name,
            'status': 'success',
            'message': ''
        }

        try:
            detail = self.api_client.get_product_detail(product_id)

            upload_skus = detail.get('uploadSkus', [])
            if not upload_skus:
                result['status'] = 'skipped'
                result['message'] = 'SKU 없음'
                return result

            # 디버그: 첫 번째 SKU 구조 확인
            if upload_skus:
                first_sku = upload_skus[0]
                sku_keys = list(first_sku.keys())
                self.log(f"   🔍 SKU 필드: {', '.join(sku_keys[:15])}...")
                # 가격 관련 필드 확인
                price_fields = {k: first_sku.get(k) for k in first_sku.keys() if 'price' in k.lower() or 'sale' in k.lower() or 'origin' in k.lower()}
                if price_fields:
                    self.log(f"   💲 가격필드: {price_fields}")

            # 로그 시작
            self.log(f"📤 상품 ID: {product_id}")
            self.log(f"   💱 적용 환율: {self.price_settings.exchange_rate}")
            self.log(f"   💳 적용 카드수수료: {self.price_settings.card_fee_rate}%")
            self.log(f"   📈 적용 올림단위: {self.price_settings.round_unit}원")
            margin_rate = random.uniform(self.price_settings.margin_rate_min, self.price_settings.margin_rate_max)
            self.log(f"   📊 적용 정률마진: {margin_rate:.0f}%")
            self.log(f"   💰 적용 정액마진: {self.price_settings.margin_fixed:,}원")
            discount_rate = random.uniform(self.price_settings.discount_rate_min, self.price_settings.discount_rate_max)
            self.log(f"   🏷️ 적용 할인율: {discount_rate:.0f}%")

            # 1. 미끼 옵션 필터링 + 가격 범위 필터링
            valid_skus = []
            excluded_by_keyword = 0
            excluded_by_price = 0
            for sku in upload_skus:
                # 미끼 키워드 체크
                text = sku.get('text', '') or sku.get('_text', '')
                if any(kw in text for kw in self.exclude_keywords):
                    excluded_by_keyword += 1
                    continue
                # 가격 범위 체크
                origin_price = sku.get('_origin_price', 0)
                if origin_price <= 0:
                    excluded_by_price += 1
                    continue
                origin_krw = origin_price * self.price_settings.exchange_rate
                price_with_fee = origin_krw * (1 + self.price_settings.card_fee_rate / 100)
                sale_price = price_with_fee * (1 + self.price_settings.margin_rate_min / 100) + self.price_settings.margin_fixed
                sale_price = math.ceil(sale_price / self.price_settings.round_unit) * self.price_settings.round_unit
                if sale_price < self.price_settings.min_price or sale_price > self.price_settings.max_price:
                    excluded_by_price += 1
                    continue
                valid_skus.append(sku)

            self.log(f"   📦 전체 SKU: {len(upload_skus)}개")
            if excluded_by_keyword > 0:
                self.log(f"   🔍 키워드 필터링: {excluded_by_keyword}개 제외")
            if excluded_by_price > 0:
                self.log(f"   💰 가격범위 필터링: {excluded_by_price}개 제외 (범위: {self.price_settings.min_price:,}~{self.price_settings.max_price:,}원)")

            if not valid_skus:
                result['status'] = 'skipped'
                result['message'] = '유효 옵션 없음'
                self.log(f"   ⏭️ 유효 옵션 없음 (스킵)")
                return result

            # 2. 가격 클러스터링으로 미끼 탐지
            bait_ids, cluster_info = detect_bait_by_price_cluster(valid_skus)
            excluded_by_cluster = 0

            if bait_ids:
                # 미끼로 판단된 SKU 제거
                before_count = len(valid_skus)
                valid_skus = [sku for sku in valid_skus if sku.get('id') not in bait_ids]
                excluded_by_cluster = before_count - len(valid_skus)

                # 클러스터 정보 로그
                if cluster_info and len(cluster_info) >= 2:
                    low_cluster = cluster_info[0]
                    main_cluster = cluster_info[1]
                    self.log(f"   📊 가격 클러스터 분석:")
                    self.log(f"      └ 저가그룹: {low_cluster['count']}개 ({low_cluster['min_price']:.0f}~{low_cluster['max_price']:.0f}위안) → 미끼 제거")
                    self.log(f"      └ 주가격대: {main_cluster['count']}개 ({main_cluster['min_price']:.0f}~{main_cluster['max_price']:.0f}위안)")
                    gap = main_cluster['min_price'] / low_cluster['max_price'] if low_cluster['max_price'] > 0 else 0
                    self.log(f"      └ 가격갭: {gap:.1f}배 (저가그룹 비율: {low_cluster['ratio']*100:.0f}%)")

            self.log(f"   🎯 필터링 후 남은 옵션: {len(valid_skus)}개")

            if not valid_skus:
                result['status'] = 'skipped'
                result['message'] = '클러스터 필터링 후 유효 옵션 없음'
                self.log(f"   ⏭️ 유효 옵션 없음 (스킵)")
                return result

            # 4. 옵션 정렬
            if option_sort == "price_asc":
                valid_skus.sort(key=lambda x: x.get('_origin_price', 0))
                self.log(f"   📈 정렬: 가격낮은순")
            elif option_sort == "price_desc":
                valid_skus.sort(key=lambda x: x.get('_origin_price', 0), reverse=True)
                self.log(f"   📉 정렬: 가격높은순")

            # 5. 옵션 개수 제한
            if option_count > 0:
                selected_skus = valid_skus[:option_count]
                self.log(f"   ✂️ 옵션 제한: {len(valid_skus)}개 → {len(selected_skus)}개")
            else:
                selected_skus = valid_skus

            # 6. 선택된 SKU ID 목록
            selected_ids = {sku.get('id') for sku in selected_skus}

            # 7. 가격 계산 및 exclude/main_product 설정
            min_price = float('inf')
            max_price = 0
            min_price_idx = -1
            included_count = 0
            excluded_count = 0
            for idx, sku in enumerate(upload_skus):
                if sku.get('id') in selected_ids:
                    sku['exclude'] = False
                    included_count += 1

                    if skip_price_update:
                        # 가격 수정 안함 - 기존 sale_price 사용
                        sale_price = sku.get('sale_price', 0)
                    else:
                        # 가격 계산
                        origin_cny = sku.get('_origin_price', 0)
                        origin_krw, sale_price, _, _ = calculate_price(origin_cny, self.price_settings)
                        sku['origin_price'] = origin_krw
                        sku['sale_price'] = sale_price

                    if sale_price < min_price:
                        min_price = sale_price
                        min_price_idx = idx
                    if sale_price > max_price:
                        max_price = sale_price
                else:
                    sku['exclude'] = True
                    excluded_count += 1
                sku['main_product'] = False

            # 8. main_product 설정 (최저가)
            if min_price_idx >= 0:
                upload_skus[min_price_idx]['main_product'] = True

            self.log(f"   💵 선택된 {len(selected_skus)}개 옵션: {min_price:,}~{max_price:,}원")
            self.log(f"   👑 대표상품: 최저가 {min_price:,}원")

            # 9. 변경사항 저장
            detail['uploadSkus'] = upload_skus

            # 디버그: 수정 후 대표옵션 SKU 확인
            if min_price_idx >= 0:
                main_sku = upload_skus[min_price_idx]
                price_fields = {k: main_sku.get(k) for k in main_sku.keys() if 'price' in k.lower() or 'sale' in k.lower() or 'origin' in k.lower() or k in ['exclude', 'main_product']}
                self.log(f"   🔧 대표SKU 수정값: {price_fields}")

            # 10. 상품명 셔플 처리
            original_name = detail.get('uploadCommonProductName', '')
            if title_mode != "original" and original_name:
                detail['uploadCommonProductName'] = shuffle_product_name(original_name, title_mode)

            # 11. 업데이트 (SKU 수정 건너뛰기 옵션)
            if skip_sku_update:
                self.log(f"   ⚠️ SKU 수정 건너뜀 (테스트 모드)")
            else:
                update_success, update_msg = self.api_client.update_product_fields(product_id, detail)
                if not update_success:
                    result['status'] = 'failed'
                    result['message'] = f'SKU 수정 실패: {update_msg}'
                    self.log(f"   ❌ SKU 수정 실패: {update_msg}")
                    return result
                self.log(f"   📝 SKU 업데이트: {update_msg}")

            # 12. 업로드 (그룹명으로 그룹ID 조회하여 업로드)
            upload_success, upload_msg = self.api_client.upload_product(product_id, group_name, market_name)
            if not upload_success:
                result['status'] = 'failed'
                result['message'] = upload_msg
                self.log(f"   ❌ 업로드 실패: {upload_msg[:50]}")
                return result

            self.log(f"   ✅ 업로드 성공!")

            # 결과 메시지
            result['message'] = f'SKU {len(selected_skus)}개, 최저가 {min_price:,}원'

        except Exception as e:
            result['status'] = 'failed'
            result['message'] = str(e)

        return result

    def process_group(self, group_name: str, upload_count: int,
                     option_count: int, option_sort: str, status_filters: List[str],
                     title_mode: str = "original", skip_sku_update: bool = False,
                     skip_price_update: bool = False, market_name: str = "스마트스토어"):
        """단일 그룹 처리 (그룹명으로 마켓그룹ID 조회하여 업로드)"""
        try:
            products, total = self.api_client.get_products_by_group(
                group_name, 0, upload_count, status_filters
            )

            if not products:
                self.log(f"   ⚠️ {group_name}: 상품 없음")
                return 0, 0, 0

            success = 0
            failed = 0
            skipped = 0

            for product in products:
                if not self.is_running:
                    break

                result = self.process_product(product, group_name, option_count, option_sort, title_mode, skip_sku_update, skip_price_update, market_name)
                product_name = product.get('uploadCommonProductName', '')[:20]

                if result['status'] == 'success':
                    self.log(f"   ✅ {product_name} - {result['message']}")
                    success += 1
                elif result['status'] == 'skipped':
                    self.log(f"   ⏭️ {product_name} - {result['message']}")
                    skipped += 1
                else:
                    self.log(f"   ❌ {product_name} - {result['message']}")
                    failed += 1

            return success, failed, skipped

        except Exception as e:
            self.log(f"   ❌ {group_name} 처리 오류: {e}")
            return 0, 0, 0

    def process_groups(self, group_names: List[str], upload_count: int,
                      option_count: int, option_sort: str, status_filters: List[str],
                      concurrent_sessions: int, title_mode: str = "original",
                      skip_sku_update: bool = False, skip_price_update: bool = False,
                      market_name: str = "스마트스토어"):
        """여러 그룹 처리 (그룹명 = 마켓그룹, 그룹ID로 업로드)"""
        self.stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0}
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

        try:
            if concurrent_sessions <= 1:
                # 순차 처리
                for task_idx, group_name in enumerate(group_names, 1):
                    if not self.is_running:
                        break
                    self.log(f"\n[{task_idx}/{total_tasks}] 📦 {group_name}")
                    s, f, sk = self.process_group(
                        group_name, upload_count,
                        option_count, option_sort, status_filters, title_mode, skip_sku_update, skip_price_update, market_name
                    )
                    self.stats['success'] += s
                    self.stats['failed'] += f
                    self.stats['skipped'] += sk
                    if self.gui:
                        self.gui.update_progress(task_idx, total_tasks)
            else:
                # 병렬 처리
                with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_sessions) as executor:
                    futures = {}
                    for group_name in group_names:
                        if not self.is_running:
                            break
                        future = executor.submit(
                            self.process_group,
                            group_name, upload_count,
                            option_count, option_sort, status_filters, title_mode, skip_sku_update, skip_price_update, market_name
                        )
                        futures[future] = group_name

                    completed = 0
                    for future in concurrent.futures.as_completed(futures):
                        group_name = futures[future]
                        try:
                            s, f, sk = future.result()
                            self.stats['success'] += s
                            self.stats['failed'] += f
                            self.stats['skipped'] += sk
                            self.log(f"📦 {group_name} 완료 (성공:{s}, 실패:{f}, 스킵:{sk})")
                        except Exception as e:
                            self.log(f"❌ {group_name} 오류: {e}")
                        completed += 1
                        if self.gui:
                            self.gui.update_progress(completed, total_tasks)

        except Exception as e:
            self.log(f"❌ 처리 중 오류: {e}")

        finally:
            self.stats['total'] = self.stats['success'] + self.stats['failed'] + self.stats['skipped']
            self.log("")
            self.log("=" * 50)
            self.log(f"📊 처리 결과")
            self.log(f"   전체: {self.stats['total']}개")
            self.log(f"   성공: {self.stats['success']}개")
            self.log(f"   실패: {self.stats['failed']}개")
            self.log(f"   스킵: {self.stats['skipped']}개")
            self.log("=" * 50)
            self.is_running = False
            if self.gui:
                self.gui.on_finished()


# ==================== GUI 클래스 ====================
class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("불사자 상품 업로더 v1.1")
        self.geometry("900x900")
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
        ttk.Entry(row2, textvariable=self.round_unit_var, width=5).pack(side=tk.LEFT, padx=2)

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

        ttk.Button(btn_frame, text="💾 설정 저장", command=self.save_settings).pack(side=tk.RIGHT)

        # === 로그 ===
        log_frame = ttk.LabelFrame(main_frame, text="📋 로그", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=12, state='disabled',
                                                   font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Footer
        footer = ttk.Frame(main_frame)
        footer.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(footer, text="v1.1 by 프코노미", foreground="gray").pack(side=tk.RIGHT)

    def load_saved_settings(self):
        c = self.config_data
        if "port" in c: self.port_var.set(c["port"])
        if "exchange_rate" in c: self.exchange_rate_var.set(c["exchange_rate"])
        if "card_fee" in c: self.card_fee_var.set(c["card_fee"])
        if "margin_rate" in c: self.margin_rate_var.set(c["margin_rate"])
        if "margin_fixed" in c: self.margin_fixed_var.set(c["margin_fixed"])
        if "discount_rate" in c: self.discount_rate_var.set(c["discount_rate"])
        if "round_unit" in c: self.round_unit_var.set(c["round_unit"])
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

    def save_settings(self):
        self.config_data["port"] = self.port_var.get()
        self.config_data["exchange_rate"] = self.exchange_rate_var.get()
        self.config_data["card_fee"] = self.card_fee_var.get()
        self.config_data["margin_rate"] = self.margin_rate_var.get()
        self.config_data["margin_fixed"] = self.margin_fixed_var.get()
        self.config_data["discount_rate"] = self.discount_rate_var.get()
        self.config_data["round_unit"] = self.round_unit_var.get()
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
        save_config(self.config_data)
        self.log("✅ 설정 저장됨")

    def log(self, message):
        def _log():
            self.log_text.config(state='normal')
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')
        self.after(0, _log)

    def update_progress(self, current, total):
        def _update():
            self.progress_var.set(f"{current}/{total} 그룹 처리 중...")
            self.progress_bar['value'] = (current / total) * 100 if total > 0 else 0
        self.after(0, _update)

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
        """미끼 키워드를 기본값으로 초기화"""
        self.keyword_text.delete("1.0", tk.END)
        self.keyword_text.insert("1.0", ','.join(EXCLUDE_KEYWORDS))
        self.log("🔄 미끼 키워드 기본값으로 초기화")

    def get_exclude_keywords(self) -> List[str]:
        """현재 설정된 제외 키워드 목록 반환"""
        text = self.keyword_text.get("1.0", tk.END).strip()
        if not text:
            return EXCLUDE_KEYWORDS[:]
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
