# -*- coding: utf-8 -*-
# ========================================
# ⚠️ 주의사항: 수정 시 반드시 API 문서 참고!
# 참조: .claude/memory/bulsaja_api_structure.md
# - 필드값, 계산 로직 변경 금지
# - v1.6과 동일한 로직 유지 필수
# ========================================
"""
불사자 상품 업로더 v2.0 (PyQt6)
- 효율적인 레이아웃 (접기/펼치기, 드롭다운)
- 수정업로드 모드
- 태그 선택 옵션
- v1.6 모든 기능 포팅

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

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QFormLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QTextEdit,
    QGroupBox, QScrollArea, QFrame, QProgressBar, QSplitter,
    QToolButton, QSizePolicy, QMessageBox, QInputDialog, QTabWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor, QIcon

# 공통 모듈
from bulsaja_common import (
    filter_bait_options, DEFAULT_BAIT_KEYWORDS, STRONG_BAIT_KEYWORDS,
    select_main_option, BulsajaAPIClient as CommonAPIClient,
    load_bait_keywords, KEYWORD_SAFE_CONTEXT_MAP, SAFE_CONTEXT_KEYWORDS
)

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

# 업로드 조건
UPLOAD_CONDITIONS = {
    "미업로드(수집완료+수정중+검토완료)": ["0", "1", "2", "수집 완료", "수정중", "검토 완료"],
    "수집완료만": ["0", "수집 완료"],
    "수정중만": ["1", "수정중"],
    "검토완료만": ["2", "검토 완료"],
    "업로드완료(판매중)": ["3", "판매중", "업로드 완료"],
    "전체": None,
}

# 썸네일 매칭 설정
THUMBNAIL_MATCH_ENABLED = True

# 제외 키워드
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
    margin_rate_min: float = 25.0
    margin_rate_max: float = 30.0
    margin_fixed: int = 15000
    discount_rate_min: float = 20.0
    discount_rate_max: float = 30.0
    delivery_fee: int = 0
    round_unit: int = 100
    min_price: int = 20000
    max_price: int = 100000000


import random


def extract_image_id(url: str) -> str:
    """이미지 URL에서 고유 ID 추출"""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path
        filename = path.split('/')[-1] if '/' in path else path
        name_part = filename.rsplit('.', 1)[0] if '.' in filename else filename
        return name_part
    except:
        return url


def match_thumbnail_to_sku(thumbnails: List[str], skus: List[Dict]) -> Optional[int]:
    """대표 썸네일과 매칭되는 SKU 인덱스 찾기"""
    if not thumbnails or not skus:
        return None

    main_thumb_id = extract_image_id(thumbnails[0])
    if not main_thumb_id:
        return None

    for idx, sku in enumerate(skus):
        sku_image_url = sku.get('urlRef') or sku.get('image') or ''
        if not sku_image_url:
            continue

        sku_image_id = extract_image_id(sku_image_url)
        if main_thumb_id in sku_image_id or sku_image_id in main_thumb_id:
            return idx

    main_thumb_url = thumbnails[0].lower()
    for idx, sku in enumerate(skus):
        sku_image_url = (sku.get('urlRef') or sku.get('image') or '').lower()
        if not sku_image_url:
            continue
        if 'alicdn.com' in main_thumb_url and 'alicdn.com' in sku_image_url:
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


# ==================== 접기 가능한 그룹박스 ====================
class CollapsibleBox(QGroupBox):
    """접기/펼치기 가능한 그룹박스"""

    def __init__(self, title: str, parent=None, collapsed: bool = False):
        super().__init__(parent)

        self.toggle_button = QToolButton(self)
        self.toggle_button.setStyleSheet("QToolButton { border: none; }")
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.DownArrow)
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(not collapsed)
        self.toggle_button.clicked.connect(self.toggle)

        self.content_area = QFrame(self)
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 0, 0, 0)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.toggle_button)
        main_layout.addWidget(self.content_area)

        if collapsed:
            self.content_area.hide()

    def toggle(self):
        checked = self.toggle_button.isChecked()
        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.content_area.setVisible(checked)

    def addWidget(self, widget):
        self.content_layout.addWidget(widget)

    def addLayout(self, layout):
        self.content_layout.addLayout(layout)

# ==================== 업로드 워커 스레드 ====================
class UploadWorker(QThread):
    """업로드 작업을 처리하는 워커 스레드"""

    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)  # (current_product, total_products)
    group_signal = pyqtSignal(str, int, int)  # (group_name, current_group, total_groups)
    finished_signal = pyqtSignal(dict)

    def __init__(self, uploader, settings):
        super().__init__()
        self.uploader = uploader
        self.settings = settings
        self.is_running = True

    def run(self):
        try:
            self.uploader.run_upload_thread(self.settings, self)
        except Exception as e:
            self.log_signal.emit(f"❌ 오류: {e}")
        finally:
            self.finished_signal.emit({})

    def stop(self):
        self.is_running = False


# ==================== API 클라이언트 ====================
class BulsajaAPIClient(CommonAPIClient):
    """불사자 API 클라이언트 확장"""

    # 태그 생성 캐시 (중복 생성 방지)
    _created_tags_cache = set()
    _tag_create_lock = threading.Lock()

    def __init__(self):
        super().__init__()
        self.access_token = None
        self.refresh_token = None

    def set_tokens(self, access_token: str, refresh_token: str):
        self.access_token = access_token
        self.refresh_token = refresh_token
        # 부모 클래스의 _setup_session() 호출하여 session.headers 업데이트
        self._setup_session()

    def is_connected(self) -> bool:
        return bool(self.access_token and self.refresh_token)

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
            print(f"[TAG] 태그 목록 조회 실패: {e}")
            return []

    def create_tag(self, tag_name: str) -> bool:
        """새 태그 생성"""
        url = f"{self.BASE_URL}/manage/groups"
        try:
            response = self.session.post(url, json={"name": tag_name})
            response.raise_for_status()
            print(f"[TAG] 태그 생성됨: {tag_name}")
            return True
        except Exception as e:
            print(f"[TAG] 태그 생성 실패: {e}")
            return False

    def apply_tag_to_products(self, product_ids: List[str], tag_name: str) -> Tuple[bool, int]:
        """
        상품들에 태그 적용
        Returns:
            (성공여부, 적용된 상품 수)
        """
        if not product_ids:
            return False, 0

        # 태그가 없으면 생성 (락 + 캐시로 중복 생성 방지)
        with self._tag_create_lock:
            if tag_name not in self._created_tags_cache:
                existing_tags = self.get_existing_tags()
                if tag_name not in existing_tags:
                    if not self.create_tag(tag_name):
                        return False, 0
                self._created_tags_cache.add(tag_name)

        url = f"{self.BASE_URL}/sourcing/bulk-update-groups"
        # 502/503 등 서버 오류 시 재시도 (최대 3회, 간격 2/4/8초)
        for attempt in range(3):
            try:
                response = self.session.post(url, json={
                    "productIds": product_ids,
                    "groupName": tag_name
                })
                response.raise_for_status()
                print(f"[TAG] 태그 '{tag_name}' 적용 완료: {len(product_ids)}개 상품")
                return True, len(product_ids)
            except Exception as e:
                is_server_error = "500" in str(e) or "502" in str(e) or "503" in str(e) or "504" in str(e)
                if is_server_error and attempt < 2:
                    wait = 2 ** (attempt + 1)  # 2, 4초
                    print(f"[TAG] 서버 오류, {wait}초 후 재시도 ({attempt+1}/3): {e}")
                    import time
                    time.sleep(wait)
                    continue
                print(f"[TAG] 태그 적용 실패: {e}")
                return False, 0

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


# v2.0은 독립 실행 (v1.6 불필요)


# ==================== 업로더 클래스 ====================
class BulsajaUploader:
    """업로드 로직 처리 클래스 (v2.0 독립 구현)"""

    def __init__(self, gui):
        self.gui = gui
        self.api_client = BulsajaAPIClient()
        self.is_running = False
        self.stats = {'success': 0, 'failed': 0, 'skipped': 0, 'duplicate_failed': 0, 'failed_ids': []}
        self._tagged_ids = set()
        self._tag_lock = threading.Lock()

        # 가격 설정
        self.price_settings = PriceSettings()
        # 제외 키워드
        self.exclude_keywords = EXCLUDE_KEYWORDS[:]
        # 마켓 ID 캐시
        self._group_market_cache = {}
        # 마켓 그룹 ID 매핑 (group_name → group_id)
        self._market_group_id_map: Dict[str, int] = {}
        # [v1.6 동일] 가격 필드명 캐시 (자동 감지용)
        self.origin_price_field = None

    def load_market_group_ids(self) -> Dict[str, int]:
        """마켓 그룹 목록 조회 후 name→id 매핑 생성"""
        if self._market_group_id_map:
            return self._market_group_id_map

        url = f"{self.api_client.BASE_URL}/market/groups/"
        try:
            response = self.api_client.session.post(url, json={})
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                for g in data:
                    name = g.get('name', '')
                    gid = g.get('id')
                    if name and gid:
                        self._market_group_id_map[name] = gid
        except Exception as e:
            print(f"[ERROR] 마켓 그룹 ID 매핑 로드 실패: {e}")

        return self._market_group_id_map

    def get_market_group_id(self, group_name: str) -> Optional[int]:
        """그룹명으로 마켓 그룹 ID 조회"""
        if not self._market_group_id_map:
            self.load_market_group_ids()
        return self._market_group_id_map.get(group_name)

    def get_market_id_in_group(self, group_name: str, market_name: str) -> Optional[int]:
        """그룹 내 특정 마켓의 ID 조회 (v1.6 동일 로직)"""
        cache_key = (group_name, market_name)
        if cache_key in self._group_market_cache:
            return self._group_market_cache[cache_key]

        # 그룹 ID 조회
        group_id = self.get_market_group_id(group_name)
        if not group_id:
            return None

        # 그룹 내 마켓 목록 조회
        url = f"{self.api_client.BASE_URL}/market/group/{group_id}/markets"
        try:
            response = self.api_client.session.get(url)
            response.raise_for_status()
            markets = response.json()
        except Exception as e:
            print(f"[ERROR] 그룹 마켓 조회 실패: {e}")
            return None

        target_type = MARKET_TYPES.get(market_name, "SMARTSTORE")
        for market in markets:
            if market.get('type') == target_type:
                market_id = market.get('id')
                self._group_market_cache[cache_key] = market_id
                return market_id

        return None

    def upload_product(self, product_id: str, group_name: str, market_name: str = "스마트스토어",
                       prevent_duplicate: bool = True) -> Tuple[bool, str]:
        """상품 업로드 (v1.6 동일 로직)"""
        # 그룹 내 마켓 ID 조회
        market_id = self.get_market_id_in_group(group_name, market_name)
        if not market_id:
            return False, f"그룹 '{group_name}'에서 '{market_name}' 마켓을 찾을 수 없음"

        market_type = MARKET_TYPES.get(market_name, "SMARTSTORE")

        # 데이터 확보
        base_data = self.api_client.get_upload_fields(product_id) if hasattr(self.api_client, 'get_upload_fields') else None
        if not base_data:
            base_data = self.api_client.get_product_detail(product_id) or {}

        # Notices 추출
        notices = base_data.get('uploadNotices') or base_data.get('notices')

        # 쿠팡 고시정보 강제 재설정
        if market_name == "쿠팡":
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

        # 업로드 URL
        url = f"{self.api_client.BASE_URL}/market/{market_id}/upload/"

        # 화이트리스트 기반 페이로드 구성
        allowed_keys = [
            "uploadBulsajaCode", "uploadTrackcopyCode", "uploadSelectedMarketGroupId",
            "uploadSkus", "uploadSkuProps", "uploadThumbnails", "uploadVideoUrls",
            "uploadDetailContents", "uploadDetail_page", "uploadDelivery",
            "uploadBrand", "uploadCategory", "uploadSmartStoreTags", "uploadCommonTags",
            "uploadCommonProductName", "uploadProductSearchText", "uploadSearchCategory",
            "uploadCoupangOptionMode", "uploadCoupangProductName", "uploadSmartStoreProductName",
            "uploadContact", "uploadFake_pct",
            "uploadBase_price", "uploadSetting", "uplaodSetting",
            "uploadRecentExchangeRate", "uploadOverseaDeliveryFee",
            "card_fee", "raise_digit", "percent_margin", "plus_margin", "discount_rate",
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
            for key in allowed_keys:
                if key in base_data and base_data[key] is not None:
                    payload[key] = base_data[key]
                # 오타 대응
                if key == "uploadSetting" and "uplaodSetting" in base_data and "uploadSetting" not in payload:
                    payload["uploadSetting"] = base_data["uplaodSetting"]

        # uploadSetting 강제 생성
        if 'uploadSetting' not in payload:
            payload['uploadSetting'] = {
                "is_tax_free": False, "coupang_thumbnail_mode": "OPTION_IMAGE",
                "maker": "", "brand": "", "min_purchase_qty": 0, "max_purchase_qty": 0
            }

        # [v1.6 동일] uploadSetting 내부 필드를 최상위에도 중복 배치
        setting_obj = payload.get('uploadSetting') or payload.get('uplaodSetting') or {}
        if isinstance(setting_obj, dict):
            for key in ['is_tax_free', 'coupang_thumbnail_mode', 'maker', 'brand',
                        'max_purchase_qty', 'min_purchase_qty', 'minor_limit',
                        'shipment_date', 'add_first_option_to_smartstore']:
                if key in setting_obj and key not in payload:
                    payload[key] = setting_obj[key]

        # 상품명 설정
        product_name = base_data.get('productName') or base_data.get('uploadCommonProductName', "상품")
        payload['search'] = product_name
        payload['name'] = product_name

        # [v1.6 동일] 쿠팡 메타 카테고리 정보 조회 및 병합
        if market_name == "쿠팡" and base_data:
            try:
                group_id = self.get_market_group_id(group_name)
                category_id = None

                # 방법 A: categoryList에서 검색
                cat_list = base_data.get('categoryList', [])
                if cat_list:
                    for cat in cat_list:
                        if cat.get('id') == 'cp':
                            category_id = cat.get('code')
                            break

                # 방법 B: uploadCategory 내에서 검색
                if not category_id:
                    up_cat = base_data.get('uploadCategory')
                    if up_cat and isinstance(up_cat, dict):
                        category_id = up_cat.get('code') or up_cat.get('cp_category', {}).get('code')

                # 방법 C: cp_category에서 검색
                if not category_id:
                    cp_cat = base_data.get('cp_category')
                    if cp_cat and isinstance(cp_cat, dict):
                        category_id = cp_cat.get('code')

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

                # 방법 F: top-level 'code' 키 확인
                if not category_id:
                    code_val = base_data.get('code')
                    if code_val and str(code_val).isdigit():
                        category_id = code_val

                if group_id and category_id:
                    # 메타 정보 조회
                    meta_url = f"{self.api_client.BASE_URL}/market/group/{group_id}/meta/?categoryId={category_id}"
                    meta_res = self.api_client.session.get(meta_url)

                    cat_name = base_data.get('category', {}).get('name') if isinstance(base_data.get('category'), dict) else "기타"

                    # [골드 스탠다드] cp_category 및 categoryList를 최상위(Root)에 배치
                    payload['code'] = str(category_id)
                    payload['cp_category'] = {"name": cat_name, "code": str(category_id)}

                    # categoryList에 additional(필수 옵션 정보) 포함
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

                    # [중요] uploadCategory 내부에도 cp_category와 categoryList 중복 배치
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
                        if real_data and 'isAllowSingleItem' in real_data:
                            payload['isAllowSingleItem'] = real_data['isAllowSingleItem']

            except Exception as e:
                pass  # 쿠팡 메타 로직 실패해도 업로드 시도

        try:
            response = self.api_client.session.post(url, json=payload, timeout=30)
            response.raise_for_status()

            try:
                result = response.json()
                if isinstance(result, dict):
                    if result.get('error') or result.get('errors'):
                        error_msg = result.get('error') or result.get('errors') or result.get('message', '')
                        return False, f"업로드 실패: {str(error_msg)[:100]}"
                    if result.get('success') == False:
                        return False, f"업로드 실패: {result.get('message', '알 수 없는 오류')[:100]}"
                return True, "성공"
            except:
                return True, "성공"

        except requests.exceptions.Timeout:
            return False, "서버 응답 시간 초과 (30초)"
        except requests.exceptions.HTTPError as e:
            error_detail = ""
            try:
                error_detail = e.response.text[:200]
            except:
                pass
            return False, f"HTTP {e.response.status_code}: {error_detail}"
        except Exception as e:
            return False, f"예외: {str(e)}"

    def update_product_fields(self, product_id: str, product_data: Dict) -> Tuple[bool, str]:
        """상품 정보 업데이트 (서버에 저장)"""
        url = f"{self.api_client.BASE_URL}/sourcing/uploadfields/{product_id}"
        try:
            response = self.api_client.session.put(url, json=product_data)
            response.raise_for_status()

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

    def log(self, message: str):
        if self.gui:
            self.gui.log(message)

    def _create_gui_adapter(self, settings, log_func=None):
        """PyQt6 설정을 v1.6 tkinter GUI 형식으로 변환하는 어댑터

        Args:
            settings: 설정 딕셔너리
            log_func: 로그 출력 함수 (QThread에서는 worker.log_signal.emit 사용)
        """
        # log_func가 없으면 self.log 사용 (주의: QThread에서는 크래시 발생 가능)
        actual_log_func = log_func or self.log

        class GUIAdapter:
            """v1.6 업로더가 기대하는 tkinter GUI 인터페이스를 시뮬레이션"""
            def __init__(self, settings, log_func):
                self._settings = settings
                self._log_func = log_func

                # v1.6이 기대하는 변수들을 Mock 객체로 생성
                self.update_upload_mode_var = MockVar(settings.get('update_upload_mode', False))
                self.skip_already_uploaded_var = MockVar(settings.get('skip_already_uploaded', True))
                self.banned_kw_enabled_var = MockVar(settings.get('banned_kw_enabled', True))
                self.exclude_kw_enabled_var = MockVar(settings.get('exclude_kw_enabled', True))
                self.esm_discount_3_var = MockVar(settings.get('esm_discount_3', False))
                self.esm_option_normalize_var = MockVar(settings.get('esm_option_normalize', False))
                self.ss_category_search_var = MockVar(settings.get('ss_category_search', False))
                self.skip_failed_tag_var = MockVar(settings.get('skip_failed_tag', False))
                self.prevent_duplicate_upload_var = MockVar(settings.get('prevent_duplicate', True))
                self.thumbnail_match_var = MockVar(settings.get('thumbnail_match', True))
                self.skip_sku_update_var = MockVar(settings.get('skip_sku_update', False))
                self.skip_price_update_var = MockVar(settings.get('skip_price_update', False))

                # 텍스트 입력 Mock
                self.banned_kw_text = MockText(settings.get('banned_keywords', ''))
                self.keyword_text = MockText(settings.get('exclude_keywords', ''))
                self.exclude_cat_text = MockText(settings.get('exclude_categories', ''))

            def log(self, message):
                self._log_func(message)

        class MockVar:
            """tkinter 변수 Mock"""
            def __init__(self, value):
                self._value = value
            def get(self):
                return self._value
            def set(self, value):
                self._value = value

        class MockText:
            """tkinter Text 위젯 Mock"""
            def __init__(self, text):
                self._text = text
            def get(self, start, end):
                return self._text

        return GUIAdapter(settings, actual_log_func)

    def run_upload_thread(self, settings, worker):
        """업로드 스레드 실행"""
        self.is_running = True
        self.stats = {'success': 0, 'failed': 0, 'skipped': 0, 'duplicate_failed': 0, 'failed_ids': []}
        self._tagged_ids = set()

        try:
            group_names = settings.get('group_names', [])
            target_markets = settings.get('target_markets', [])

            if not group_names:
                worker.log_signal.emit("⚠️ 작업 그룹이 없습니다")
                return

            if not target_markets:
                worker.log_signal.emit("⚠️ 업로드 마켓이 선택되지 않았습니다")
                return

            worker.log_signal.emit(f"🚀 업로드 시작: {len(group_names)}개 그룹, 마켓: {', '.join(target_markets)}")

            # 업로드 실행
            self._run_upload(settings, worker, group_names, target_markets)

            # 완료 통계
            worker.log_signal.emit("")
            worker.log_signal.emit("=" * 50)
            worker.log_signal.emit(f"📊 업로드 완료")
            worker.log_signal.emit(f"   ✅ 성공: {self.stats['success']}개")
            worker.log_signal.emit(f"   ❌ 실패: {self.stats['failed']}개")
            worker.log_signal.emit(f"   🔁 중복실패: {self.stats['duplicate_failed']}개")
            worker.log_signal.emit(f"   ⏭️ 건너뜀: {self.stats['skipped']}개")

            if self.stats['failed_ids']:
                worker.log_signal.emit("")
                worker.log_signal.emit(f"❌ 실패 목록 ({len(self.stats['failed_ids'])}개):")
                for fail_id in self.stats['failed_ids']:
                    worker.log_signal.emit(f"   - {fail_id}")

            if self._tagged_ids:
                worker.log_signal.emit("")
                worker.log_signal.emit(f"🏷️ 태그 적용됨: {len(self._tagged_ids)}개 상품")

            worker.log_signal.emit("=" * 50)

        except Exception as e:
            worker.log_signal.emit(f"❌ Error: {e}")
            import traceback
            worker.log_signal.emit(traceback.format_exc())
        finally:
            self.is_running = False

    def _run_upload(self, settings, worker, group_names, target_markets):
        """업로드 실행 (v2.0 독립 구현)"""
        # 가격 설정 적용
        self.price_settings.exchange_rate = settings.get('exchange_rate', 215)
        self.price_settings.card_fee_rate = settings.get('card_fee', 3.3)

        margin_rate = settings.get('margin_rate', '25,30')
        if ',' in str(margin_rate):
            min_m, max_m = map(float, str(margin_rate).split(','))
            self.price_settings.margin_rate_min = min_m
            self.price_settings.margin_rate_max = max_m
        else:
            self.price_settings.margin_rate_min = float(margin_rate)
            self.price_settings.margin_rate_max = float(margin_rate)

        self.price_settings.margin_fixed = settings.get('margin_fixed', 15000)

        discount_rate = settings.get('discount_rate', '20,30')
        if ',' in str(discount_rate):
            min_d, max_d = map(float, str(discount_rate).split(','))
            self.price_settings.discount_rate_min = min_d
            self.price_settings.discount_rate_max = max_d
        else:
            self.price_settings.discount_rate_min = float(discount_rate)
            self.price_settings.discount_rate_max = float(discount_rate)

        self.price_settings.round_unit = settings.get('round_unit', 100)
        self.price_settings.min_price = settings.get('min_price', 20000)
        self.price_settings.max_price = settings.get('max_price', 100000000)

        # 제외 키워드 설정
        exclude_kw_text = settings.get('exclude_keywords', '')
        if exclude_kw_text:
            self.exclude_keywords = [kw.strip() for kw in exclude_kw_text.split(',') if kw.strip()]

        # [v1.6 동일] 테스트 ID 모드 처리
        test_id = settings.get('test_id', '').strip()
        if test_id:
            worker.log_signal.emit(f"🧪 [테스트 모드] 상품 ID '{test_id}' 단일 처리 시작")
            try:
                # 1. 상품 상세 정보 조회
                detail = self.api_client.get_product_detail(test_id)
                if not detail:
                    worker.log_signal.emit(f"❌ 상품 ID '{test_id}' 정보를 가져올 수 없습니다.")
                    return

                # 2. 소속 그룹 찾기
                target_group_id = detail.get('uploadSelectedMarketGroupId')
                target_group_name = ""

                # 그룹 ID -> 그룹명 역검색
                group_map = self.load_market_group_ids()
                for g_name, g_id in group_map.items():
                    if str(g_id) == str(target_group_id):
                        target_group_name = g_name
                        break

                if not target_group_name:
                    worker.log_signal.emit(f"⚠️ 소속 그룹 ID({target_group_id})를 찾을 수 없음")
                    if group_names:
                        target_group_name = group_names[0]
                        worker.log_signal.emit(f"   👉 대체 그룹 사용: {target_group_name}")
                    else:
                        worker.log_signal.emit(f"❌ 실패: 소속 그룹 없음, 대체 그룹도 없음")
                        return
                else:
                    worker.log_signal.emit(f"   ✅ 소속 그룹 감지: {target_group_name} (ID: {target_group_id})")

                # 3. 단일 상품 처리
                product_lite = {
                    'ID': test_id,
                    'uploadCommonProductName': detail.get('uploadCommonProductName', detail.get('productName', '테스트상품'))
                }

                option_count = settings.get('option_count', 10)
                option_sort = settings.get('option_sort', 'price_asc')
                title_mode = settings.get('title_mode', 'shuffle_skip3')

                worker.log_signal.emit(f"   📋 대상 마켓: {', '.join(target_markets)}")

                for m_name in target_markets:
                    if not worker.is_running:
                        break
                    worker.log_signal.emit(f"   ▶ [{m_name}] 업로드 시도...")

                    result = self.process_product(
                        product_lite, target_group_name, option_count, option_sort,
                        title_mode, m_name, 1, 1, settings,
                        lambda msg: worker.log_signal.emit(msg)
                    )

                    status = result.get('status', 'failed')
                    if status == 'success':
                        self.stats['success'] += 1
                        worker.log_signal.emit(f"   ✅ [{m_name}] 업로드 성공!")
                    elif status == 'skipped':
                        self.stats['skipped'] += 1
                        worker.log_signal.emit(f"   ⏭️ [{m_name}] 건너뜀: {result.get('message', '')}")
                    else:
                        self.stats['failed'] += 1
                        worker.log_signal.emit(f"   ❌ [{m_name}] 실패: {result.get('message', '')[:100]}")

                worker.log_signal.emit(f"\n🧪 [테스트 모드] 완료")
                return  # 테스트 모드는 여기서 종료

            except Exception as e:
                worker.log_signal.emit(f"❌ 테스트 모드 오류: {e}")
                import traceback
                worker.log_signal.emit(traceback.format_exc())
                return

        # 마켓 한도 추적
        market_limit_reached = set()

        total_groups = len(group_names)
        for g_idx, group_name in enumerate(group_names, 1):
            if not worker.is_running:
                self.is_running = False
                break

            # 그룹 정보 업데이트
            worker.group_signal.emit(group_name, g_idx, total_groups)
            worker.progress_signal.emit(0, 1)  # 진행률 초기화
            worker.log_signal.emit(f"\n📁 [{g_idx}/{total_groups}] 그룹: {group_name}")

            # 상품 로드
            upload_count = settings.get('upload_count', 100)
            status_filters = settings.get('status_filters', None)
            skip_failed_tag = settings.get('skip_failed_tag', False)
            # [수정] 사용자 설정 fail_tag 사용 (하드코딩 제거)
            exclude_tag = settings.get('fail_tag', '업로드실패') if skip_failed_tag else None

            # [수정] 미업로드만 체크 시 → 상태 "3"(판매중) 상품도 포함
            # 이유: "미업로드" 조건은 글로벌 상태(0/1/2)로 필터링하므로
            #       다른 마켓에 업로드된 상품(상태=3)이 제외됨
            #       → 해당 마켓 미업로드 체크(uploadedMarkets)에서 정확히 필터링
            skip_already_uploaded = settings.get('skip_already_uploaded', True)
            if skip_already_uploaded and status_filters and "3" not in status_filters:
                status_filters = list(status_filters) + ["3", "판매중", "업로드 완료"]

            try:
                products, total = self.api_client.get_products_by_group(
                    group_name, 0, upload_count, status_filters, exclude_tag=exclude_tag
                )

                if not products:
                    worker.log_signal.emit(f"   ⚠️ 상품 없음")
                    continue

                worker.log_signal.emit(f"   📦 {len(products)}개 상품 로드됨")

                option_count = settings.get('option_count', 10)
                option_sort = settings.get('option_sort', 'price_asc')
                title_mode = settings.get('title_mode', 'shuffle_skip3')

                for p_idx, product in enumerate(products, 1):
                    if not worker.is_running:
                        break

                    # 상품 진행률 업데이트
                    worker.progress_signal.emit(p_idx, len(products))

                    for market_name in target_markets:
                        if market_name in market_limit_reached:
                            continue

                        if not worker.is_running:
                            break

                        # process_product 호출
                        result = self.process_product(
                            product, group_name, option_count, option_sort,
                            title_mode, market_name, p_idx, len(products),
                            settings, lambda msg: worker.log_signal.emit(msg)
                        )

                        # 결과 처리
                        status = result.get('status', 'failed')
                        if status == 'success':
                            self.stats['success'] += 1
                        elif status == 'skipped':
                            self.stats['skipped'] += 1
                        elif status == 'duplicate_failed':
                            self.stats['duplicate_failed'] += 1
                        elif status in ['quota_limit', 'market_limit']:
                            market_limit_reached.add(market_name)
                            worker.log_signal.emit(f"   → {market_name} 한도 도달")
                        else:
                            self.stats['failed'] += 1
                            product_id = product.get('sourcingProductId', '') or product.get('ID', '')
                            product_name = product.get('uploadCommonProductName', '')[:20]
                            self.stats['failed_ids'].append(f"{product_id} ({product_name})")

            except Exception as e:
                worker.log_signal.emit(f"   ❌ 그룹 처리 오류: {e}")
                import traceback
                worker.log_signal.emit(traceback.format_exc())

    def write_detail_log(self, product_id: str, content: str):
        """상세 로그를 파일에 기록"""
        try:
            # log 디렉토리 없으면 생성
            if not os.path.exists("log"):
                os.makedirs("log")

            today = datetime.now().strftime("%Y%m%d")
            filename = f"log/upload_detail_{today}.log"
            timestamp = datetime.now().strftime("%H:%M:%S")

            with open(filename, "a", encoding="utf-8") as f:
                f.write(f"\n[{timestamp}] [Product: {product_id}]\n")
                f.write(content)
                f.write("-" * 50 + "\n")
        except Exception as e:
            print(f"로그 파일 기록 실패: {e}")

    def _tag_failed_async(self, product_id: str, existing_tags: list = None, fail_tag: str = "업로드실패"):
        """
        실패 상품에 태그를 비동기로 적용 (별도 스레드)

        Args:
            product_id: 상품 ID
            existing_tags: 상품의 기존 태그 목록 (중복 방지용)
            fail_tag: 적용할 태그명 (None이면 태그 안 달음)
        """
        # 태그없음 설정 시 태그 안 달음
        if not fail_tag:
            return

        # 기존에 해당 태그가 있으면 스킵 (중복 생성 방지)
        if existing_tags:
            if fail_tag in existing_tags:
                print(f"[TAG] ⏭️ {product_id} 이미 '{fail_tag}' 태그 있음 - 스킵")
                return

        def _apply():
            try:
                with self._tag_lock:
                    if product_id in self._tagged_ids:
                        return  # 이미 태그됨 (현재 세션)
                    self._tagged_ids.add(product_id)

                success, _ = self.api_client.apply_tag_to_products([product_id], fail_tag)
                if success:
                    print(f"[TAG] 🏷️ {product_id} '{fail_tag}' 태그 적용 완료")
            except Exception as e:
                print(f"[TAG] 태그 적용 실패: {e}")

        # 별도 스레드에서 실행 (업로드 속도 영향 없음)
        threading.Thread(target=_apply, daemon=True).start()

    def detect_origin_price_field(self, sku: Dict) -> Tuple[str, float]:
        """
        [v1.6 동일] SKU에서 원가 필드를 자동 감지
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
        """[v1.6 동일] 안전하게 SKU 원가를 가져오는 헬퍼"""
        if self.origin_price_field:
            val = sku.get(self.origin_price_field, 0)
            try:
                return float(val)
            except:
                return 0.0

        # 필드가 아직 확정 안됐거나 없는 경우 탐색
        field, price = self.detect_origin_price_field(sku)
        if field:
            self.origin_price_field = field  # 캐시 저장
            return price
        return 0.0

    def filter_options(self, skus: List[Dict], settings: PriceSettings) -> List[Dict]:
        """[v1.6 동일] 옵션 필터링"""
        filtered = []
        for sku in skus:
            text = sku.get('text', '') or sku.get('_text', '')
            # GUI에서 설정한 제외 키워드 사용
            if any(keyword in text for keyword in self.exclude_keywords):
                continue
            # 가격 계산 (안전한 필드 접근)
            origin_price = self.get_sku_origin_price(sku)

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
        """[v1.6 동일] 옵션 정렬"""
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
        [v1.6 동일] 옵션 개수 제한
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
                       option_sort: str, title_mode: str, market_name: str,
                       current_idx: int, total_count: int, settings: Dict,
                       log_func) -> Dict:
        """상품 처리 및 업로드 (v1.6 동일 로직)"""
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
            existing_tags = None  # 태그 중복 방지용 (detail 로드 후 설정)

            # [v1.5] 금지 키워드 체크 (상품명 기준) - [v1.6] ON/OFF 체크박스 + 안전 컨텍스트 추가
            banned_kw_enabled = settings.get('banned_kw_enabled', True)
            banned_kw_text = settings.get('banned_keywords', '')
            if banned_kw_enabled and banned_kw_text:
                banned_keywords = [kw.strip().lower() for kw in banned_kw_text.split(',') if kw.strip()]
                product_name_lower = full_product_name.lower()
                found_banned = None
                for bkw in banned_keywords:
                    if bkw in product_name_lower:
                        found_banned = bkw
                        break

                # [v1.6] 안전 컨텍스트 체크 - 금지 키워드가 있어도 안전 컨텍스트가 있으면 통과
                if found_banned:
                    is_safe_context = False
                    safe_context_found = []

                    # 1. 키워드별 전용 안전 컨텍스트 확인
                    keyword_contexts = KEYWORD_SAFE_CONTEXT_MAP.get(found_banned, None)
                    if keyword_contexts is not None and len(keyword_contexts) > 0:
                        for ctx in keyword_contexts:
                            if ctx.lower() in product_name_lower:
                                is_safe_context = True
                                safe_context_found.append(ctx)

                    # 2. 일반 안전 컨텍스트 확인 (키워드별 정의 없을 때)
                    if not is_safe_context and keyword_contexts is None:
                        for safe_kw in SAFE_CONTEXT_KEYWORDS:
                            if safe_kw.lower() in product_name_lower:
                                is_safe_context = True
                                safe_context_found.append(safe_kw)
                                break  # 하나만 찾으면 됨

                    if is_safe_context:
                        # 안전 컨텍스트 발견 → 통과 (로그만 남김)
                        progress_str = f"[{current_idx}/{total_count}] " if total_count > 0 else ""
                        market_short = MARKET_SHORT.get(market_name, market_name)
                        log_func(f"✅ {progress_str}[{market_short}] 금지키워드 [{found_banned}] 안전컨텍스트 [{','.join(safe_context_found[:2])}] → 통과")
                    else:
                        # 안전 컨텍스트 없음 → 스킵
                        progress_str = f"[{current_idx}/{total_count}] " if total_count > 0 else ""
                        market_short = MARKET_SHORT.get(market_name, market_name)
                        log_func("")
                        log_func(f"⏭️ {progress_str}[{market_short}] {product_id} - 금지키워드 [{found_banned}]")
                        log_func(f"   {product_name}")
                        result['status'] = 'skipped'
                        result['message'] = f'금지키워드: {found_banned}'
                        return result

            detail = self.api_client.get_product_detail(product_id)

            # [v1.6] 기존 태그 추출 (중복 태그 적용 방지용)
            existing_tags = detail.get('tags', []) or detail.get('groups', []) or []

            # [v1.6] 수정 업로드 모드 확인
            update_mode = settings.get('update_upload_mode', False)

            # [v1.4] 해당 마켓 미업로드 체크 (수정 업로드 모드에서는 스킵)
            if not update_mode:
                skip_already_uploaded = settings.get('skip_already_uploaded', True)
                if skip_already_uploaded:
                    uploaded_markets = detail.get('uploadedMarkets', '') or ''
                    market_type = MARKET_TYPES.get(market_name, '')
                    if market_type and market_type in uploaded_markets:
                        progress_str = f"[{current_idx}/{total_count}] " if total_count > 0 else ""
                        market_short = MARKET_SHORT.get(market_name, market_name)
                        log_func("")
                        log_func(f"⏭️ {progress_str}[{market_short}] {product_id} - 이미 업로드됨")
                        log_func(f"   {product_name}")
                        result['status'] = 'skipped'
                        result['message'] = f'이미 {market_name}에 업로드됨'
                        return result

            upload_skus = detail.get('uploadSkus', [])
            if not upload_skus:
                progress_str = f"[{current_idx}/{total_count}] " if total_count > 0 else ""
                market_short = MARKET_SHORT.get(market_name, market_name)
                log_func("")
                log_func(f"⏭️ {progress_str}[{market_short}] {product_id} - SKU 없음")
                log_func(f"   {product_name}")
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
                log_func(f"   🧹 중복 옵션 제거(ID/값): {len(upload_skus)}개 → {len(unique_skus)}개")
                upload_skus = unique_skus

            # 해외배송비 가져오기 (상품별 설정값 사용)
            delivery_fee = detail.get('uploadOverseaDeliveryFee', 0) or 0

            # 로그 시작 (상품별 구분을 위해 빈 줄 + ID/상품명 분리)
            progress_str = f"[{current_idx}/{total_count}] " if total_count > 0 else ""
            market_short = MARKET_SHORT.get(market_name, market_name)
            # [v1.6] 수정 업로드 모드 표시
            mode_str = "[수정]" if update_mode else ""
            log_func("")  # 상품 간 구분선
            log_func(f"📤 {progress_str}[{market_short}]{mode_str} {product_id}")
            log_func(f"   {product_name}")

            margin_rate = int(random.uniform(self.price_settings.margin_rate_min, self.price_settings.margin_rate_max))
            # ESM/11번가 할인율 3% 고정 (GUI 옵션)
            esm_discount_3 = settings.get('esm_discount_3', True)
            if esm_discount_3 and market_name in ["G마켓/옥션", "11번가"]:
                discount_rate = 3
            else:
                discount_rate = int(random.uniform(self.price_settings.discount_rate_min, self.price_settings.discount_rate_max))

            # 2. 미끼 옵션 필터링 + 가격 범위 필터링
            valid_skus = []
            excluded_by_keyword = []  # (id, text, price, 매칭키워드)
            excluded_by_price = []    # (id, text, price, 이유)

            # [v1.4] 미끼 키워드 빈도+가격 분석 - [v1.6] ON/OFF 체크박스 추가
            # 키워드가 2개 이상 옵션에 포함되고, 해당 옵션들 가격이 미끼 가격이 아니면 → 상품 특성으로 간주
            exclude_kw_enabled = settings.get('exclude_kw_enabled', True)
            keyword_skus = {}  # 키워드별 매칭된 SKU 리스트
            if exclude_kw_enabled:
                for kw in self.exclude_keywords:
                    matching = [sku for sku in upload_skus if kw in (sku.get('text', '') or sku.get('_text', ''))]
                    if matching:
                        keyword_skus[kw] = matching

            # 전체 옵션 평균 가격 (위안)
            all_prices = [self.get_sku_origin_price(sku) for sku in upload_skus if self.get_sku_origin_price(sku) > 0]
            avg_price = sum(all_prices) / len(all_prices) if all_prices else 0

            # 2개 이상 옵션에 포함된 키워드는 가격 검증 (단, 강력 미끼 키워드 제외)
            excluded_common_keywords = set()
            for kw, matching_skus in keyword_skus.items():
                # 강력 미끼 키워드는 가격과 무관하게 절대 통과 불가
                if kw in STRONG_BAIT_KEYWORDS:
                    continue

                if len(matching_skus) >= 2:  # 최소 2개 이상 옵션에 포함
                    # 해당 키워드 포함 옵션들의 평균 가격
                    kw_prices = [self.get_sku_origin_price(sku) for sku in matching_skus if self.get_sku_origin_price(sku) > 0]
                    kw_avg = sum(kw_prices) / len(kw_prices) if kw_prices else 0

                    # 전체 평균의 50% 이상이면 미끼 가격 아님 → 키워드 필터링 제외
                    if avg_price > 0 and kw_avg >= avg_price * 0.5:
                        excluded_common_keywords.add(kw)

            # 실제 필터링에 사용할 키워드 (공통+정상가격 키워드 제외) - [v1.6] ON/OFF 체크박스 추가
            if exclude_kw_enabled:
                effective_exclude_keywords = [kw for kw in self.exclude_keywords if kw not in excluded_common_keywords]
            else:
                effective_exclude_keywords = []  # 비활성화 시 빈 리스트

            if excluded_common_keywords and exclude_kw_enabled:
                log_func(f"   ℹ️ 공통키워드 통과: {', '.join(excluded_common_keywords)} (2개+ 옵션, 정상가격)")

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
            log_func(filter_msg)

            if not valid_skus:
                if detail_log_buffer:
                    self.write_detail_log(product_id, detail_log_buffer)
                # 매칭된 키워드 요약 (중복 제거, 최대 5개)
                if excluded_by_keyword:
                    matched_kws = list(set([kw for _, _, _, kw in excluded_by_keyword]))[:5]
                    log_func(f"   🔍 매칭키워드: {', '.join(matched_kws)}")
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

                    log_func(f"   📊 가격클러스터 미끼제거: {len(excluded_by_cluster)}개")
                    detail_log_buffer += f"\n[가격클러스터 미끼제거] {len(excluded_by_cluster)}개\n"
                    detail_log_buffer += f"   └ 저가그룹: {low_cluster['count']}개 ({low_cluster['min_price']:.0f}~{low_cluster['max_price']:.0f}위안)\n"
                    detail_log_buffer += f"   └ 주가격대: {main_cluster['count']}개 ({main_cluster['min_price']:.0f}~{main_cluster['max_price']:.0f}위안)\n"
                    detail_log_buffer += f"   └ 가격갭: {gap:.1f}배 (저가비율: {low_cluster['ratio']*100:.0f}%)\n"
                    for sku_id, text, price in excluded_by_cluster:
                        detail_log_buffer += f"      └ id={sku_id}, {price}위안, {text}\n"

            if detail_log_buffer:
                self.write_detail_log(product_id, detail_log_buffer)

            log_func(f"   🎯 필터링 후 남은 옵션: {len(valid_skus)}개")

            if not valid_skus:
                result['status'] = 'skipped'
                result['message'] = '클러스터 필터링 후 유효 옵션 없음'
                return result

            # 4. 옵션 정렬
            if option_sort == "price_asc":
                valid_skus.sort(key=lambda x: self.get_sku_origin_price(x))
                log_func(f"   📈 정렬: 가격낮은순")
            elif option_sort == "price_desc":
                valid_skus.sort(key=lambda x: self.get_sku_origin_price(x), reverse=True)
                log_func(f"   📉 정렬: 가격높은순")

            # 5. 옵션 개수 제한
            if option_count > 0:
                selected_skus = valid_skus[:option_count]
                log_func(f"   ✂️ 옵션 제한: {len(valid_skus)}개 → {len(selected_skus)}개")
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
            log_func(f"   💹 가격설정: 마진율 {margin_rate}%, 정액 {self.price_settings.margin_fixed:,}원, 배송비 {delivery_fee:,}원, 할인율 {discount_rate}%")

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
                log_func(f"   👑 대표: {sale_price_krw:,}원")
                if min_price_sku.get('exclude') is True:
                    min_price_sku['exclude'] = False
            else:
                log_func(f"   ⚠️ 경고: 유효한 옵션 없음 - 업로드 실패 가능")

            # [중요] 선택된 모든 옵션의 exclude를 false로 강제 변경 (업로드 범위 내 옵션은 모두 판매 상태)
            # [v1.6+] 재고 0인 옵션은 999로 변경 (마켓 등록 요구사항: 재고 1개 이상 필수)
            stock_fixed_count = 0
            for sku in selected_skus:
                if sku.get('exclude') is True:
                    sku['exclude'] = False
                # 재고가 0 또는 없으면 999로 설정
                stock = sku.get('stock', 0)
                if stock is None or stock == 0:
                    sku['stock'] = 999
                    stock_fixed_count += 1

            if stock_fixed_count > 0:
                log_func(f"   📦 재고 0 → 999 변경: {stock_fixed_count}개 옵션")

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
                     log_func(f"   ⏭️ {result['message']} (스킵)")
                     return result

                 # 차원이 부족한 경우 복구 시도 (1단→2단만)
                 if max_text_dims > current_defined_dims and max_text_dims == 2:
                     log_func(f"   🛠️ 옵션 차원 불일치 감지 ({current_defined_dims}단 -> {max_text_dims}단) - 자동 복구 시도")
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
                         log_func(f"   ✅ 누락된 서브 옵션({len(new_sub_values)}개) 복구 완료")
                         current_defined_dims += 1 # 차원 갱신

                 # 여전히 차원이 부족하면 스킵 (데이터 부정확성 차단)
                 if max_text_dims > current_defined_dims:
                     result['status'] = 'skipped'
                     result['message'] = f'옵션 차원 불일치 (복구 실패: {current_defined_dims}단 vs {max_text_dims}단)'
                     log_func(f"   ⏭️ {result['message']} (스킵)")
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
                         log_func(f"   🧹 옵션 동기화(메인): {len(main_vals)}개 -> {len(new_main_vals)}개")

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
                         log_func(f"   🧹 옵션 동기화(서브): {len(new_sub_options)}개 남음")
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
            ss_category_search = settings.get('ss_category_search', True)
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
                    log_func(f"   🏷️ SS 카테고리: {display_cat}")
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
                    log_func(f"   🏷️ ESM 카테고리 수동지정: {fixed_full_name}")

                if cat_info:
                    if 'uploadCategory' not in detail: detail['uploadCategory'] = {}
                    # ESM은 계층 구조가 포함된 name과 categoryList가 중요
                    detail['uploadCategory']['esm_category'] = {
                        "name": cat_info.get('name'),
                        "code": cat_info.get('code'),
                        "search": full_product_name,
                        "categoryList": [cat_info]
                    }
                    log_func(f"   🏷️ ESM 카테고리 확정: {cat_info.get('name')}")
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
                    log_func(f"   🏷️ ESM 카테고리: {display_cat}")

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
            exclude_cat_text = settings.get('exclude_categories', '')
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

                # 쿠팡 카테고리도 체크
                if not searched_cat_name and market_name == "쿠팡" and 'cp_category' in detail.get('uploadCategory', {}):
                    searched_cat_name = detail['uploadCategory']['cp_category'].get('name', '')

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
                        log_func(f"   ⏭️ 제외카테고리 [{found_exclude_cat}] → {searched_cat_name[:30]}")
                        result['status'] = 'skipped'
                        result['message'] = f'제외카테고리: {found_exclude_cat}'
                        return result

            # [신규] ESM 추천 옵션 매핑 오류 및 중복 방지 (옵션명 표준화) - GUI 옵션
            # ESM = G마켓/옥션만 해당 (이베이셀러마스터), 11번가는 SK플래닛 자체 셀러오피스 사용
            esm_option_normalize = settings.get('esm_option_normalize', True)
            if esm_option_normalize and market_name == "G마켓/옥션" and 'uploadSkuProps' in detail:
                sku_props = detail['uploadSkuProps']
                if 'mainOption' in sku_props and sku_props['mainOption']:
                    original_prop = sku_props['mainOption'].get('prop_name', '')
                    if original_prop not in ["색상", "사이즈"]:
                        sku_props['mainOption']['prop_name'] = "색상"
                        log_func(f"   🎨 ESM 옵션명 표준화: '{original_prop}' -> '색상'")

                if 'subOption' in sku_props and isinstance(sku_props['subOption'], list):
                    for sub_opt in sku_props['subOption']:
                        original_prop = sub_opt.get('prop_name', '')
                        if original_prop not in ["색상", "사이즈"]:
                            sub_opt['prop_name'] = "사이즈"
                            log_func(f"   📏 ESM 서브옵션명 표준화: '{original_prop}' -> '사이즈'")

            # 12. 전체 업데이트 (SKU, 가격, 카테고리 등 한 번에 전송)
            skip_sku_update = settings.get('skip_sku_update', False)
            if skip_sku_update:
                log_func(f"   ⚠️ SKU 수정 건너뜀 (테스트 모드)")
            else:
                update_success, update_msg = self.update_product_fields(product_id, detail)
                if not update_success:
                    result['status'] = 'failed'
                    result['message'] = f'상품 정보 업데이트 실패: {update_msg}'
                    log_func(f"   ❌ 업데이트 실패: {update_msg}")
                    self._tag_failed_async(product_id, existing_tags, settings.get('fail_tag', '업로드실패'))  # 실패 태그 적용 (중복 방지)
                    return result

            # 13. 업로드 (그룹명으로 그룹ID 조회하여 업로드)
            # 불사자 중복 업로드 방지 옵션 (수정 업로드 모드에서는 강제 False)
            if update_mode:
                prevent_duplicate = False  # 수정 업로드: 중복 방지 해제
            else:
                prevent_duplicate = settings.get('prevent_duplicate', True)
            upload_success, upload_msg = self.upload_product(product_id, group_name, market_name, prevent_duplicate)
            if not upload_success:
                # 카테고리 오류 시 (여기서는 이미 통합 업데이트 했으므로 재시도 로직이 좀 다르지만, 혹시 몰라 유지)
                if "카테고리" in upload_msg and market_name == "스마트스토어":
                     # 기존 재시도 로직은 복잡해지므로, 일단 실패 로그만 남김
                     pass

                # [v1.6] 일일 등록제한 감지 (500개 제한) - 태그 안 달고 해당 마켓만 스킵
                is_quota_limit = any(kw in upload_msg for kw in ['500개', '등록제한', '1일 500개'])
                if is_quota_limit:
                    result['status'] = 'quota_limit'
                    result['market'] = market_name  # 마켓 정보 추가
                    result['message'] = f'{market_name} 일일 등록제한 (500개)'
                    log_func(f"   🚫 일일 등록제한 (500개) 도달 - {market_name} 건너뜀")
                    # is_running = False 안 함 → 다른 마켓은 계속 진행
                    return result

                # 마켓 한도 초과 감지 (5,000개 제한)
                is_market_limit = '5,000개' in upload_msg or '최대 5,000개' in upload_msg or '5000개' in upload_msg
                if is_market_limit:
                    result['status'] = 'market_limit'
                    result['market'] = market_name  # 마켓 정보 추가
                    result['message'] = f'{market_name} 한도 초과 (5,000개)'
                    log_func(f"   🚫 마켓 한도 초과: {market_name} 5,000개 제한")
                    return result

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
                log_func(f"   {fail_icon} {fail_type}: {display_msg}")
                self.write_detail_log(product_id, f"[{fail_type}]\n{upload_msg}\n")
                self._tag_failed_async(product_id, existing_tags, settings.get('fail_tag', '업로드실패'))  # 실패 태그 적용 (중복 방지)

                return result

            log_func(f"   ✅ 업로드 성공!")

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
            self._tag_failed_async(product_id, existing_tags, settings.get('fail_tag', '업로드실패'))  # 실패 태그 적용 (중복 방지)

        return result


# ==================== 메인 GUI ====================
class MainWindow(QMainWindow):
    """메인 윈도우"""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("불사자 상품 업로더 v2.0")
        self.setMinimumSize(200, 200)
        self.resize(950, 1050)

        self.config_data = load_config()
        self.uploader = BulsajaUploader(self)
        self.worker = None

        self.setup_ui()
        self.load_saved_settings()

    def setup_ui(self):
        """UI 설정"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(5)

        # 스크롤 영역 (설정 전체 - 숨길 수 있음)
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(5)

        # === 1. API 연결 ===
        self.setup_api_section(scroll_layout)

        # === 2. 마진 설정 (접기 가능) ===
        self.setup_margin_section(scroll_layout)

        # === 3. 업로드 설정 ===
        self.setup_upload_section(scroll_layout)

        # === 4. 마켓 그룹 설정 ===
        self.setup_group_section(scroll_layout)

        # === 5. 필터 설정 (접기 가능) ===
        self.setup_filter_section(scroll_layout)

        scroll_layout.addStretch()
        self.settings_scroll.setWidget(scroll_content)
        main_layout.addWidget(self.settings_scroll, 1)

        # === 6. 진행바 & 버튼 ===
        self.setup_control_section(main_layout)

        # === 7. 로그 ===
        self.setup_log_section(main_layout)

    def setup_api_section(self, parent_layout):
        """API 연결 섹션"""
        group = QGroupBox("🔑 API 연결")
        layout = QHBoxLayout(group)

        self.btn_chrome = QPushButton("🌐 크롬")
        self.btn_chrome.setFixedWidth(70)
        self.btn_chrome.clicked.connect(self.open_debug_chrome)

        self.btn_token = QPushButton("🔑 토큰")
        self.btn_token.setFixedWidth(70)
        self.btn_token.clicked.connect(self.extract_tokens)

        self.btn_connect = QPushButton("🔗 연결")
        self.btn_connect.setFixedWidth(70)
        self.btn_connect.clicked.connect(self.connect_api)

        self.api_status_label = QLabel("연결 안 됨")
        self.api_status_label.setStyleSheet("color: gray;")

        layout.addWidget(self.btn_chrome)
        layout.addWidget(self.btn_token)
        layout.addWidget(self.btn_connect)
        layout.addWidget(self.api_status_label)
        layout.addStretch()

        layout.addWidget(QLabel("포트:"))
        self.port_input = QLineEdit("9222")
        self.port_input.setFixedWidth(60)
        layout.addWidget(self.port_input)

        parent_layout.addWidget(group)

    def setup_margin_section(self, parent_layout):
        """마진 설정 섹션"""
        self.margin_box = CollapsibleBox("💰 마진 설정", collapsed=False)
        box = self.margin_box

        form = QFormLayout()
        form.setHorizontalSpacing(15)

        # 첫 번째 행
        row1 = QHBoxLayout()

        self.exchange_rate_input = QLineEdit("215")
        self.exchange_rate_input.setFixedWidth(60)
        row1.addWidget(QLabel("환율:"))
        row1.addWidget(self.exchange_rate_input)

        self.card_fee_input = QLineEdit("3.3")
        self.card_fee_input.setFixedWidth(50)
        row1.addWidget(QLabel("카드수수료(%):"))
        row1.addWidget(self.card_fee_input)

        self.margin_rate_input = QLineEdit("25,30")
        self.margin_rate_input.setFixedWidth(70)
        row1.addWidget(QLabel("마진율(%):"))
        row1.addWidget(self.margin_rate_input)

        self.margin_fixed_input = QLineEdit("15000")
        self.margin_fixed_input.setFixedWidth(70)
        row1.addWidget(QLabel("정액마진:"))
        row1.addWidget(self.margin_fixed_input)

        row1.addStretch()
        box.addLayout(row1)

        # 두 번째 행
        row2 = QHBoxLayout()

        self.discount_rate_input = QLineEdit("20,30")
        self.discount_rate_input.setFixedWidth(70)
        row2.addWidget(QLabel("할인율(%):"))
        row2.addWidget(self.discount_rate_input)

        self.round_unit_input = QLineEdit("100")
        self.round_unit_input.setFixedWidth(60)
        row2.addWidget(QLabel("올림단위:"))
        row2.addWidget(self.round_unit_input)

        # 배송비는 상품별 설정값(uploadOverseaDeliveryFee) 사용

        row2.addStretch()
        box.addLayout(row2)

        parent_layout.addWidget(box)

    def setup_upload_section(self, parent_layout):
        """업로드 설정 섹션"""
        group = QGroupBox("📤 업로드 설정")
        layout = QVBoxLayout(group)

        # 첫 번째 행: 기본 설정
        row1 = QHBoxLayout()

        row1.addWidget(QLabel("업로드수:"))
        self.upload_count_input = QLineEdit("9000")
        self.upload_count_input.setFixedWidth(60)
        row1.addWidget(self.upload_count_input)

        row1.addWidget(QLabel("동시세션:"))
        self.concurrent_combo = QComboBox()
        self.concurrent_combo.addItems(["1", "2", "3", "4", "5"])
        self.concurrent_combo.setFixedWidth(50)
        row1.addWidget(self.concurrent_combo)

        row1.addWidget(QLabel("옵션수:"))
        self.option_count_input = QLineEdit("10")
        self.option_count_input.setFixedWidth(50)
        row1.addWidget(self.option_count_input)

        row1.addWidget(QLabel("옵션정렬:"))
        self.option_sort_combo = QComboBox()
        self.option_sort_combo.addItems(list(OPTION_SORT_OPTIONS.keys()))
        self.option_sort_combo.setFixedWidth(100)
        row1.addWidget(self.option_sort_combo)

        row1.addStretch()
        layout.addLayout(row1)

        # 두 번째 행: 상품명, 업로드조건
        row2 = QHBoxLayout()

        row2.addWidget(QLabel("상품명:"))
        self.title_option_combo = QComboBox()
        self.title_option_combo.addItems(list(TITLE_OPTIONS.keys()))
        self.title_option_combo.setFixedWidth(160)
        self.title_option_combo.setCurrentIndex(2)  # 앞3개단어제외 셔플
        row2.addWidget(self.title_option_combo)

        row2.addWidget(QLabel("업로드조건:"))
        self.upload_condition_combo = QComboBox()
        self.upload_condition_combo.addItems(list(UPLOAD_CONDITIONS.keys()))
        self.upload_condition_combo.setFixedWidth(230)
        row2.addWidget(self.upload_condition_combo)

        row2.addStretch()
        layout.addLayout(row2)

        # 세 번째 행: 마켓 선택
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("마켓:"))

        self.market_checkboxes = {}
        for market_name in MARKET_IDS.keys():
            cb = QCheckBox(market_name)
            cb.setChecked(market_name == "스마트스토어")
            self.market_checkboxes[market_name] = cb
            row3.addWidget(cb)

        row3.addStretch()
        layout.addLayout(row3)

        # 네 번째 행: 옵션 체크박스들
        row4 = QHBoxLayout()

        self.skip_already_uploaded_cb = QCheckBox("미업로드만")
        self.skip_already_uploaded_cb.setChecked(True)
        row4.addWidget(self.skip_already_uploaded_cb)

        self.update_upload_mode_cb = QCheckBox("수정업로드")
        self.update_upload_mode_cb.setToolTip("이미 업로드된 상품을 재업로드 (중복방지 해제)")
        row4.addWidget(self.update_upload_mode_cb)

        row4.addStretch()
        layout.addLayout(row4)

        # 다섯 번째 행: 추가 옵션들
        row5 = QHBoxLayout()

        self.prevent_duplicate_cb = QCheckBox("중복방지")
        self.prevent_duplicate_cb.setChecked(True)
        row5.addWidget(self.prevent_duplicate_cb)

        self.skip_failed_tag_cb = QCheckBox("실패태그건너뜀")
        row5.addWidget(self.skip_failed_tag_cb)

        self.esm_discount_cb = QCheckBox("ESM/11번가 3%")
        row5.addWidget(self.esm_discount_cb)

        self.esm_option_norm_cb = QCheckBox("ESM옵션표준화")
        row5.addWidget(self.esm_option_norm_cb)

        self.ss_category_cb = QCheckBox("SS카테고리검색")
        row5.addWidget(self.ss_category_cb)

        row5.addStretch()
        layout.addLayout(row5)

        # 여섯 번째 행: 태그 설정 (신규)
        row6 = QHBoxLayout()

        row6.addWidget(QLabel("실패시 태그:"))
        self.fail_tag_combo = QComboBox()
        self.fail_tag_combo.addItems(["업로드실패", "태그없음", "직접입력..."])
        self.fail_tag_combo.setFixedWidth(120)
        self.fail_tag_combo.currentTextChanged.connect(self.on_fail_tag_changed)
        row6.addWidget(self.fail_tag_combo)

        self.custom_fail_tag_input = QLineEdit()
        self.custom_fail_tag_input.setFixedWidth(100)
        self.custom_fail_tag_input.setPlaceholderText("태그명")
        self.custom_fail_tag_input.hide()
        row6.addWidget(self.custom_fail_tag_input)

        row6.addWidget(QLabel("테스트ID:"))
        self.test_id_input = QLineEdit()
        self.test_id_input.setFixedWidth(120)
        self.test_id_input.setPlaceholderText("특정 ID만 테스트")
        row6.addWidget(self.test_id_input)

        row6.addStretch()
        layout.addLayout(row6)

        # 일곱 번째 행: 가격 범위
        row7 = QHBoxLayout()

        row7.addWidget(QLabel("옵션가격 범위:"))
        self.min_price_input = QLineEdit("20000")
        self.min_price_input.setFixedWidth(80)
        row7.addWidget(self.min_price_input)
        row7.addWidget(QLabel("~"))
        self.max_price_input = QLineEdit("100000000")
        self.max_price_input.setFixedWidth(100)
        row7.addWidget(self.max_price_input)
        row7.addWidget(QLabel("원"))

        row7.addStretch()
        layout.addLayout(row7)

        parent_layout.addWidget(group)

    def setup_group_section(self, parent_layout):
        """마켓 그룹 설정 섹션"""
        group = QGroupBox("📁 마켓 그룹")
        layout = QHBoxLayout(group)

        layout.addWidget(QLabel("작업 그룹:"))
        self.work_groups_input = QLineEdit()
        self.work_groups_input.setPlaceholderText("비우면 드롭다운 선택")
        self.work_groups_input.setToolTip("비어있으면 드롭다운 선택 사용\n숫자: 1-5 또는 1,3,5\n이름: 그룹명 일부")
        self.work_groups_input.setFixedWidth(120)
        layout.addWidget(self.work_groups_input)

        self.btn_load_groups = QPushButton("📥")
        self.btn_load_groups.setFixedWidth(30)
        self.btn_load_groups.setToolTip("그룹 목록 로드")
        self.btn_load_groups.clicked.connect(self.load_market_groups)
        layout.addWidget(self.btn_load_groups)

        layout.addWidget(QLabel("그룹:"))
        # 그룹 목록 드롭다운 (선택 참조용)
        self.group_combo = QComboBox()
        self.group_combo.setMinimumWidth(180)
        self.group_combo.setToolTip("로드된 그룹 목록 (참조용)")
        layout.addWidget(self.group_combo)

        layout.addStretch()
        parent_layout.addWidget(group)

    def setup_filter_section(self, parent_layout):
        """필터 설정 섹션 (접기 가능)"""
        self.filter_box = CollapsibleBox("🚫 필터 설정", collapsed=True)
        box = self.filter_box

        # 제외 카테고리
        cat_layout = QHBoxLayout()
        cat_layout.addWidget(QLabel("제외 카테고리:"))
        self.exclude_cat_input = QLineEdit()
        self.exclude_cat_input.setPlaceholderText("쉼표로 구분 (예: 의류, 신발)")
        cat_layout.addWidget(self.exclude_cat_input)
        box.addLayout(cat_layout)

        # 금지 키워드
        banned_layout = QHBoxLayout()
        self.banned_kw_enabled_cb = QCheckBox("금지키워드:")
        self.banned_kw_enabled_cb.setChecked(True)
        banned_layout.addWidget(self.banned_kw_enabled_cb)
        self.banned_kw_input = QLineEdit()
        self.banned_kw_input.setPlaceholderText("쉼표 구분 (상품명에 포함시 업로드 패스)")
        banned_layout.addWidget(self.banned_kw_input)
        box.addLayout(banned_layout)

        # 미끼 키워드
        bait_layout = QHBoxLayout()
        self.exclude_kw_enabled_cb = QCheckBox("미끼키워드:")
        self.exclude_kw_enabled_cb.setChecked(True)
        bait_layout.addWidget(self.exclude_kw_enabled_cb)
        self.keyword_text = QTextEdit()
        self.keyword_text.setMaximumHeight(40)
        default_keywords = ", ".join(EXCLUDE_KEYWORDS)
        self.keyword_text.setPlainText(default_keywords)
        bait_layout.addWidget(self.keyword_text)

        self.btn_reset_keywords = QPushButton("기본값")
        self.btn_reset_keywords.setFixedWidth(60)
        self.btn_reset_keywords.clicked.connect(self.reset_keywords)
        bait_layout.addWidget(self.btn_reset_keywords)
        box.addLayout(bait_layout)

        parent_layout.addWidget(box)

    def setup_control_section(self, parent_layout):
        """컨트롤 버튼 섹션 (2행: 버튼 → 진행바)"""
        control_frame = QFrame()
        main_layout = QVBoxLayout(control_frame)
        main_layout.setContentsMargins(0, 5, 0, 5)
        main_layout.setSpacing(5)

        # === Row 1: 버튼 ===
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_toggle_settings = QPushButton("▼ 설정 접기")
        self.btn_toggle_settings.setFixedWidth(90)
        self.btn_toggle_settings.clicked.connect(self.toggle_settings)
        btn_layout.addWidget(self.btn_toggle_settings)

        self.btn_save = QPushButton("💾 설정 저장")
        self.btn_save.clicked.connect(self.save_settings)
        btn_layout.addWidget(self.btn_save)

        self.btn_start = QPushButton("🚀 업로드 시작")
        self.btn_start.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
        self.btn_start.clicked.connect(self.start_upload)
        btn_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("🛑 중지")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_upload)
        btn_layout.addWidget(self.btn_stop)

        main_layout.addLayout(btn_layout)

        # === Row 2: 진행바 ===
        progress_layout = QHBoxLayout()

        self.group_label = QLabel("그룹: -")
        self.group_label.setMinimumWidth(150)
        progress_layout.addWidget(self.group_label)

        self.progress_label = QLabel("대기 중")
        self.progress_label.setMinimumWidth(80)
        progress_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        progress_layout.addWidget(self.progress_bar, 1)  # stretch=1로 남은 공간 차지

        main_layout.addLayout(progress_layout)

        parent_layout.addWidget(control_frame)

    def setup_log_section(self, parent_layout):
        """로그 섹션"""
        group = QGroupBox("📋 로그")
        layout = QVBoxLayout(group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(200)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.log_text)

        parent_layout.addWidget(group, 1)

    # ========== 이벤트 핸들러 ==========

    def on_fail_tag_changed(self, text):
        """실패 태그 콤보박스 변경"""
        if text == "직접입력...":
            self.custom_fail_tag_input.show()
        else:
            self.custom_fail_tag_input.hide()

    def log(self, message: str):
        """로그 출력"""
        import html as html_lib
        timestamp = datetime.now().strftime("%H:%M:%S")

        # 마켓 플랫폼별 색상 (v1.6 동일)
        market_colors = {
            "[N]": "#00CC00",      # 스마트스토어 - 초록
            "[11]": "#E60000",     # 11번가 - 빨강
            "[C]": "#00BFFF",      # 쿠팡 - 하늘색
            "[G|A]": "#0066FF",    # G마켓/옥션 - 파랑
            "[G]": "#0066FF",      # 지마켓 - 파랑
            "[A]": "#9932CC",      # 옥션 - 자주색
        }

        # 기본 색상 결정
        color = "#d4d4d4"  # 기본 회색
        if any(x in message for x in ["❌", "실패", "에러", "오류"]):
            color = "#f44336"  # 빨강
        elif any(x in message for x in ["✅", "성공", "완료"]):
            color = "#4CAF50"  # 초록
        elif any(x in message for x in ["⚠️", "경고", "주의"]):
            color = "#ff9800"  # 주황
        elif any(x in message for x in ["⏭️", "건너뜀", "스킵"]):
            color = "#9e9e9e"  # 회색
        elif any(x in message for x in ["📤", "🚀", "🔍", "📁"]):
            color = "#2196F3"  # 파랑

        # 메시지 HTML 이스케이프 후 마켓 태그 색상 적용
        escaped_msg = html_lib.escape(message)
        for tag, tag_color in market_colors.items():
            escaped_tag = html_lib.escape(tag)
            if escaped_tag in escaped_msg:
                colored_tag = f'<span style="color: {tag_color}; font-weight: bold;">{escaped_tag}</span>'
                escaped_msg = escaped_msg.replace(escaped_tag, colored_tag)

        html = f'<span style="color: #888;">[{timestamp}]</span> <span style="color: {color};">{escaped_msg}</span><br>'

        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)
        self.log_text.insertHtml(html)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def update_progress(self, current, total):
        """상품 진행 상황 업데이트"""
        pct = int((current / total) * 100) if total > 0 else 0
        self.progress_label.setText(f"{current}/{total}")
        self.progress_bar.setValue(pct)

    def update_group(self, group_name, current_group, total_groups):
        """그룹 진행 상황 업데이트"""
        short_name = group_name[:20] + "..." if len(group_name) > 20 else group_name
        self.group_label.setText(f"{short_name} ({current_group}/{total_groups})")

    def open_debug_chrome(self):
        """디버그 모드 크롬 열기"""
        port = self.port_input.text()
        cmd = f'start chrome --remote-debugging-port={port} --remote-allow-origins=* --user-data-dir="%TEMP%\\ChromeDebug" https://www.bulsaja.com'
        import subprocess
        subprocess.Popen(cmd, shell=True)
        self.log(f"🌐 크롬 디버그 모드 시작 (포트: {port})")

    def extract_tokens(self):
        """토큰 추출 (bulsaja_common.py 로직 사용)"""
        try:
            port = int(self.port_input.text())
            self.log(f"🔑 토큰 추출 시도 (포트: {port})")

            # 디버그 페이지 목록 가져오기
            try:
                response = requests.get(f"http://127.0.0.1:{port}/json", timeout=3)
                pages = response.json()
            except Exception as e:
                self.log(f"⚠️ 크롬 디버그 포트 {port} 연결 실패")
                self.log(f"   → 크롬을 완전히 종료 후 '🌐 크롬' 버튼으로 다시 여세요")
                return

            # 불사자 페이지 찾기
            target_page = None
            for page in pages:
                if 'bulsaja.com' in page.get('url', ''):
                    target_page = page
                    break

            if not target_page:
                self.log("⚠️ 불사자 페이지를 찾을 수 없습니다")
                self.log("   → 불사자 웹사이트에 접속하세요")
                return

            # WebSocket으로 토큰 추출
            ws_url = target_page.get('webSocketDebuggerUrl', '')
            if not ws_url:
                self.log("⚠️ WebSocket URL을 찾을 수 없습니다")
                return

            ws = websocket.create_connection(ws_url, timeout=5)

            # localStorage에서 토큰 가져오기 (불사자 구조: localStorage.token.state)
            ws.send(json.dumps({
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
            }))

            result = json.loads(ws.recv())
            ws.close()

            if 'result' in result and 'result' in result['result']:
                token_data = json.loads(result['result']['result'].get('value', '{}'))
                access_token = token_data.get('accessToken', '')
                refresh_token = token_data.get('refreshToken', '')

                if access_token and refresh_token:
                    self.uploader.api_client.set_tokens(access_token, refresh_token)
                    self.api_status_label.setText("연결됨")
                    self.api_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                    self.log("✅ 토큰 추출 성공")
                    # 자동으로 마켓 그룹 로드
                    QTimer.singleShot(100, self.load_market_groups)
                else:
                    self.log("⚠️ 토큰이 비어있습니다. 불사자에 로그인하세요.")
            else:
                self.log("⚠️ 토큰 파싱 실패")

        except Exception as e:
            self.log(f"❌ 토큰 추출 실패: {e}")

    def connect_api(self):
        """API 연결"""
        if not self.uploader.api_client.is_connected():
            self.log("⚠️ 먼저 토큰을 추출하세요")
            return

        try:
            # 연결 테스트 (마켓 그룹 목록 조회)
            groups = self.uploader.api_client.get_market_groups()
            if groups:
                self.api_status_label.setText("연결됨")
                self.api_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
                self.log(f"✅ API 연결 성공 ({len(groups)}개 그룹)")
            else:
                self.api_status_label.setText("연결됨 (그룹없음)")
                self.api_status_label.setStyleSheet("color: #ff9800;")
                self.log("⚠️ API 연결됨, 그룹 없음")
        except Exception as e:
            self.log(f"⚠️ API 연결 확인: {e}")
            # 연결 오류여도 토큰이 있으면 연결된 것으로 간주
            self.api_status_label.setText("연결됨 (미확인)")
            self.api_status_label.setStyleSheet("color: #ff9800;")

    def load_market_groups(self):
        """마켓 그룹 목록 로드"""
        if not self.uploader.api_client.is_connected():
            self.log("⚠️ 먼저 API에 연결하세요")
            return

        try:
            self.log("📥 마켓 그룹 목록 로드 중...")
            groups = self.uploader.api_client.get_market_groups()

            if groups:
                # get_market_groups()는 이미 정렬된 문자열 리스트 반환
                self.group_combo.clear()
                self.group_combo.addItems(groups)
                self.log(f"✅ {len(groups)}개 그룹 로드됨")
            else:
                self.log("⚠️ 그룹이 없습니다")

        except Exception as e:
            self.log(f"❌ 그룹 로드 실패: {e}")

    def reset_keywords(self):
        """미끼 키워드 기본값으로 초기화"""
        default_keywords = ", ".join(EXCLUDE_KEYWORDS)
        self.keyword_text.setPlainText(default_keywords)
        self.log("🔄 미끼 키워드 초기화됨")

    def get_settings(self) -> dict:
        """현재 설정 수집"""
        # 마켓 선택
        target_markets = [name for name, cb in self.market_checkboxes.items() if cb.isChecked()]

        # 업로드 조건
        condition_text = self.upload_condition_combo.currentText()
        status_filters = UPLOAD_CONDITIONS.get(condition_text, None)

        # 그룹명 파싱
        group_names = self.parse_group_names()

        # 실패 태그
        fail_tag = self.fail_tag_combo.currentText()
        if fail_tag == "직접입력...":
            fail_tag = self.custom_fail_tag_input.text() or "업로드실패"
        elif fail_tag == "태그없음":
            fail_tag = None

        return {
            # 마진 설정
            'exchange_rate': float(self.exchange_rate_input.text() or 215),
            'card_fee': float(self.card_fee_input.text() or 3.3),
            'margin_rate': self.margin_rate_input.text() or "25,30",
            'margin_fixed': int(self.margin_fixed_input.text() or 15000),
            'discount_rate': self.discount_rate_input.text() or "20,30",
            'round_unit': int(self.round_unit_input.text() or 100),
            # delivery_fee는 상품별 설정값(uploadOverseaDeliveryFee) 사용

            # 업로드 설정
            'upload_count': int(self.upload_count_input.text() or 9000),
            'concurrent': int(self.concurrent_combo.currentText()),
            'option_count': int(self.option_count_input.text() or 10),
            'option_sort': OPTION_SORT_OPTIONS.get(self.option_sort_combo.currentText(), 'price_asc'),
            'title_mode': TITLE_OPTIONS.get(self.title_option_combo.currentText(), 'shuffle_skip3'),
            'status_filters': status_filters,
            'target_markets': target_markets,
            'group_names': group_names,

            # 체크박스 옵션
            'thumbnail_match': True,  # v1.6 호환용 (사용 안 함)
            'skip_sku_update': False,  # 제거됨
            'skip_price_update': False,  # 제거됨
            'skip_already_uploaded': self.skip_already_uploaded_cb.isChecked(),
            'update_upload_mode': self.update_upload_mode_cb.isChecked(),
            'prevent_duplicate': self.prevent_duplicate_cb.isChecked(),
            'skip_failed_tag': self.skip_failed_tag_cb.isChecked(),
            'esm_discount_3': self.esm_discount_cb.isChecked(),
            'esm_option_normalize': self.esm_option_norm_cb.isChecked(),
            'ss_category_search': self.ss_category_cb.isChecked(),

            # 태그 설정
            'fail_tag': fail_tag,
            'test_id': self.test_id_input.text().strip(),

            # 가격 범위
            'min_price': int(self.min_price_input.text() or 20000),
            'max_price': int(self.max_price_input.text() or 100000000),

            # 필터
            'exclude_categories': self.exclude_cat_input.text(),
            'banned_kw_enabled': self.banned_kw_enabled_cb.isChecked(),
            'banned_keywords': self.banned_kw_input.text(),
            'exclude_kw_enabled': self.exclude_kw_enabled_cb.isChecked(),
            'exclude_keywords': self.keyword_text.toPlainText(),
        }

    def parse_group_names(self) -> List[str]:
        """그룹명 입력 파싱 (숫자, 범위, 이름 지원)

        - 입력칸 비어있음 → 드롭다운에서 선택한 그룹 사용
        - 입력칸에 값 있음 → 입력값 우선 (숫자, 범위, 이름)
        """
        import re

        # 콤보박스에서 모든 그룹 가져오기
        all_groups = [self.group_combo.itemText(i) for i in range(self.group_combo.count())]

        if not all_groups:
            return []

        work_groups_text = self.work_groups_input.text().strip()

        # 입력칸이 비어있으면 드롭다운 선택 항목 사용
        if not work_groups_text:
            current_selection = self.group_combo.currentText()
            if current_selection:
                return [current_selection]
            return []

        # 그룹 매핑 생성
        mapping = {}
        prefix_pattern = re.compile(r'^(\d+)[_\-]')

        for idx, group_name in enumerate(all_groups, 1):
            match = prefix_pattern.match(group_name)
            if match:
                num = match.group(1)
                mapping[num] = group_name
                mapping[str(int(num))] = group_name
            mapping[str(idx)] = group_name

        # 입력 파싱
        result = []
        parts = [p.strip() for p in work_groups_text.replace(',', ' ').split() if p.strip()]

        for part in parts:
            # 범위 (예: 1-5)
            if '-' in part and part.replace('-', '').isdigit():
                try:
                    start, end = map(int, part.split('-'))
                    for i in range(start, end + 1):
                        if str(i) in mapping:
                            result.append(mapping[str(i)])
                except:
                    pass
            # 숫자
            elif part.isdigit():
                if part in mapping:
                    result.append(mapping[part])
            # 그룹명 또는 마켓명 일부
            else:
                for g in all_groups:
                    if part in g or g.endswith(part) or g.endswith(f"_{part}"):
                        result.append(g)
                        break

        return list(dict.fromkeys(result))  # 중복 제거

    def start_upload(self):
        """업로드 시작"""
        try:
            if not self.uploader.api_client.is_connected():
                QMessageBox.warning(self, "경고", "API에 먼저 연결하세요")
                return

            settings = self.get_settings()

            if not settings['group_names']:
                QMessageBox.warning(self, "경고", "작업 그룹을 입력하거나 드롭다운에서 선택하세요")
                return

            if not settings['target_markets']:
                QMessageBox.warning(self, "경고", "업로드 마켓을 선택하세요")
                return

            # UI 상태 변경
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)

            # 설정 섹션 접기
            self.collapse_settings()

            # 워커 스레드 시작
            self.worker = UploadWorker(self.uploader, settings)
            self.worker.log_signal.connect(self.log)
            self.worker.progress_signal.connect(self.update_progress)
            self.worker.group_signal.connect(self.update_group)
            self.worker.finished_signal.connect(self.on_upload_finished)
            self.worker.start()

        except Exception as e:
            import traceback
            error_msg = f"❌ 업로드 시작 오류: {e}\n{traceback.format_exc()}"
            self.log(error_msg)
            QMessageBox.critical(self, "오류", str(e))
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)

    def stop_upload(self):
        """업로드 중지"""
        if self.worker:
            self.worker.stop()
            self.log("🛑 중지 요청됨...")

    def toggle_settings(self):
        """설정 영역 전체 펼치기/접기 토글"""
        if self.settings_scroll.isVisible():
            self.settings_scroll.hide()
            self.btn_toggle_settings.setText("▶ 설정 펼치기")
        else:
            self.settings_scroll.show()
            self.btn_toggle_settings.setText("▼ 설정 접기")

    def collapse_settings(self):
        """설정 영역 전체 숨기기 (업로드 시작 시)"""
        self.settings_scroll.hide()
        self.btn_toggle_settings.setText("▶ 설정 펼치기")

    def on_upload_finished(self, result):
        """업로드 완료"""
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.group_label.setText("완료")
        self.progress_label.setText("")
        self.progress_bar.setValue(100)

    def save_settings(self):
        """설정 저장"""
        settings = self.get_settings()

        self.config_data.update({
            'port': self.port_input.text(),
            'exchange_rate': self.exchange_rate_input.text(),
            'card_fee': self.card_fee_input.text(),
            'margin_rate': self.margin_rate_input.text(),
            'margin_fixed': self.margin_fixed_input.text(),
            'discount_rate': self.discount_rate_input.text(),
            'round_unit': self.round_unit_input.text(),
            'upload_count': self.upload_count_input.text(),
            'concurrent': self.concurrent_combo.currentText(),
            'option_count': self.option_count_input.text(),
            'option_sort': self.option_sort_combo.currentText(),
            'title_option': self.title_option_combo.currentText(),
            'upload_condition': self.upload_condition_combo.currentText(),
            'work_groups': self.work_groups_input.text(),
            'group_list': [self.group_combo.itemText(i) for i in range(self.group_combo.count())],
            'markets': [name for name, cb in self.market_checkboxes.items() if cb.isChecked()],
            'skip_already_uploaded': self.skip_already_uploaded_cb.isChecked(),
            'update_upload_mode': self.update_upload_mode_cb.isChecked(),
            'prevent_duplicate': self.prevent_duplicate_cb.isChecked(),
            'skip_failed_tag': self.skip_failed_tag_cb.isChecked(),
            'esm_discount_3': self.esm_discount_cb.isChecked(),
            'esm_option_normalize': self.esm_option_norm_cb.isChecked(),
            'ss_category_search': self.ss_category_cb.isChecked(),
            'fail_tag': self.fail_tag_combo.currentText(),
            'custom_fail_tag': self.custom_fail_tag_input.text(),
            'test_id': self.test_id_input.text(),
            'min_price': self.min_price_input.text(),
            'max_price': self.max_price_input.text(),
            'exclude_categories': self.exclude_cat_input.text(),
            'banned_kw_enabled': self.banned_kw_enabled_cb.isChecked(),
            'banned_keywords': self.banned_kw_input.text(),
            'exclude_kw_enabled': self.exclude_kw_enabled_cb.isChecked(),
            'exclude_keywords': self.keyword_text.toPlainText(),
        })

        if save_config(self.config_data):
            self.log("✅ 설정 저장됨")
        else:
            self.log("❌ 설정 저장 실패")

    def load_saved_settings(self):
        """저장된 설정 로드"""
        c = self.config_data

        if 'port' in c: self.port_input.setText(c['port'])
        if 'exchange_rate' in c: self.exchange_rate_input.setText(c['exchange_rate'])
        if 'card_fee' in c: self.card_fee_input.setText(c['card_fee'])
        if 'margin_rate' in c: self.margin_rate_input.setText(c['margin_rate'])
        if 'margin_fixed' in c: self.margin_fixed_input.setText(c['margin_fixed'])
        if 'discount_rate' in c: self.discount_rate_input.setText(c['discount_rate'])
        if 'round_unit' in c: self.round_unit_input.setText(c['round_unit'])
        if 'upload_count' in c: self.upload_count_input.setText(c['upload_count'])
        if 'concurrent' in c: self.concurrent_combo.setCurrentText(c['concurrent'])
        if 'option_count' in c: self.option_count_input.setText(c['option_count'])
        if 'option_sort' in c: self.option_sort_combo.setCurrentText(c['option_sort'])
        if 'title_option' in c: self.title_option_combo.setCurrentText(c['title_option'])
        if 'upload_condition' in c: self.upload_condition_combo.setCurrentText(c['upload_condition'])
        if 'work_groups' in c: self.work_groups_input.setText(c['work_groups'])
        # 그룹 목록 로드 (새 형식: group_list, 구 형식: group_text)
        if 'group_list' in c:
            self.group_combo.clear()
            self.group_combo.addItems(c['group_list'])
        elif 'group_text' in c:
            # 구 형식 호환 (쉼표 구분 텍스트)
            groups = [g.strip() for g in c['group_text'].split(',') if g.strip()]
            self.group_combo.clear()
            self.group_combo.addItems(groups)
        if 'markets' in c:
            for name, cb in self.market_checkboxes.items():
                cb.setChecked(name in c['markets'])
        if 'skip_already_uploaded' in c: self.skip_already_uploaded_cb.setChecked(c['skip_already_uploaded'])
        if 'update_upload_mode' in c: self.update_upload_mode_cb.setChecked(c['update_upload_mode'])
        if 'prevent_duplicate' in c: self.prevent_duplicate_cb.setChecked(c['prevent_duplicate'])
        if 'skip_failed_tag' in c: self.skip_failed_tag_cb.setChecked(c['skip_failed_tag'])
        if 'esm_discount_3' in c: self.esm_discount_cb.setChecked(c['esm_discount_3'])
        if 'esm_option_normalize' in c: self.esm_option_norm_cb.setChecked(c['esm_option_normalize'])
        if 'ss_category_search' in c: self.ss_category_cb.setChecked(c['ss_category_search'])
        if 'fail_tag' in c: self.fail_tag_combo.setCurrentText(c['fail_tag'])
        if 'custom_fail_tag' in c: self.custom_fail_tag_input.setText(c['custom_fail_tag'])
        if 'test_id' in c: self.test_id_input.setText(c['test_id'])
        if 'min_price' in c: self.min_price_input.setText(c['min_price'])
        if 'max_price' in c: self.max_price_input.setText(c['max_price'])
        if 'exclude_categories' in c: self.exclude_cat_input.setText(c['exclude_categories'])
        if 'banned_kw_enabled' in c: self.banned_kw_enabled_cb.setChecked(c['banned_kw_enabled'])
        if 'banned_keywords' in c: self.banned_kw_input.setText(c['banned_keywords'])
        if 'exclude_kw_enabled' in c: self.exclude_kw_enabled_cb.setChecked(c['exclude_kw_enabled'])
        if 'exclude_keywords' in c: self.keyword_text.setPlainText(c['exclude_keywords'])

    def closeEvent(self, event):
        """종료 시"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        event.accept()


# ==================== 메인 ====================
def main():
    app = QApplication(sys.argv)

    # 스타일 설정
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
