# -*- coding: utf-8 -*-
"""
시뮬레이터 GUI v4 - PyQt6 최적화 버전
- QThreadPool을 이용한 이미지 병렬 로딩
- 대량 데이터 처리 최적화
- 3개 탭: 수집 / 검수 / 설정
"""

import sys
import os
import json
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QCheckBox, QRadioButton,
    QGroupBox, QTabWidget, QScrollArea, QTextEdit, QProgressBar, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QFileDialog, QSplitter, QFrame,
    QButtonGroup, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRunnable, QThreadPool, QObject, QSize, QTimer
from PyQt6.QtGui import QPixmap, QImage, QFont, QColor, QPainter

# 불사자 공통 모듈
try:
    from bulsaja_common import (
        BulsajaAPIClient, extract_tokens_from_browser,
        filter_bait_options, select_main_option,
        load_bait_keywords, save_bait_keywords,
        load_banned_words, load_excluded_words, check_product_safety,
        load_category_risk_settings, save_category_risk_settings,
        DEFAULT_CATEGORY_RISK_SETTINGS, get_category_risk_level,
        MARKET_IDS, DEFAULT_BAIT_KEYWORDS
    )
    BULSAJA_API_AVAILABLE = True
except ImportError:
    BULSAJA_API_AVAILABLE = False

# 검수 수준 옵션
CHECK_LEVELS = {
    "보통 (자동판단)": "normal",
    "엄격 (AI검수)": "strict",
    "검수제외": "skip",
}

# 엑셀 라이브러리
try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font as XLFont, PatternFill, Alignment, Border, Side
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


# ============================================================
# 설정
# ============================================================
CONFIG_FILE = "simulator_gui_v4_config.json"
DEBUG_PORT = 9222

# 수집 조건
UPLOAD_CONDITIONS = {
    "미업로드(수집완료+수정중+검토완료)": ["0", "1", "2", "수집 완료", "수정중", "검토 완료"],
    "수집완료만": ["0", "수집 완료"],
    "수정중만": ["1", "수정중"],
    "검토완료만": ["2", "검토 완료"],
    "업로드완료(판매중)": ["3", "판매중", "업로드 완료"],
    "전체": None,
}

# 옵션 정렬
OPTION_SORT_OPTIONS = {
    "가격낮은순": "price_asc",
    "주요가격대": "price_main",
    "가격높은순": "price_desc",
}

# 상품명 처리
TITLE_OPTIONS = {
    "원마켓 상품명 그대로 사용": "original",
    "앞4개단어제외 셔플": "shuffle_skip4",
    "앞3개단어제외 셔플": "shuffle_skip3",
    "모든단어 셔플": "shuffle_all",
}


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_config(config: dict) -> bool:
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except:
        return False


# ============================================================
# 이미지 캐시 (메모리 캐싱)
# ============================================================
class ImageCache:
    """URL 해시 기반 메모리 캐시"""

    def __init__(self, max_size: int = 200):
        self._cache: Dict[str, QPixmap] = {}
        self._max_size = max_size

    def get(self, url: str) -> Optional[QPixmap]:
        key = hashlib.md5(url.encode()).hexdigest()
        return self._cache.get(key)

    def put(self, url: str, pixmap: QPixmap):
        if len(self._cache) >= self._max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
        key = hashlib.md5(url.encode()).hexdigest()
        self._cache[key] = pixmap

    def clear(self):
        self._cache.clear()


image_cache = ImageCache()


# ============================================================
# 이미지 다운로드 워커 (QThreadPool용)
# ============================================================
class WorkerSignals(QObject):
    """워커 시그널"""
    finished = pyqtSignal(str, QPixmap)  # (product_id, pixmap)
    error = pyqtSignal(str, str)  # (product_id, error_msg)


class ImageDownloadWorker(QRunnable):
    """
    백그라운드 이미지 다운로드 워커
    - QThreadPool에서 병렬 실행
    - 다운로드 후 리사이징하여 메모리 최적화
    """

    def __init__(self, product_id: str, url: str, size: QSize = QSize(60, 60)):
        super().__init__()
        self.product_id = product_id
        self.url = url
        self.size = size
        self.signals = WorkerSignals()

    def run(self):
        try:
            # 캐시 확인
            cached = image_cache.get(self.url)
            if cached:
                self.signals.finished.emit(self.product_id, cached)
                return

            # HTTP 요청
            with urlopen(self.url, timeout=10) as response:
                data = response.read()

            # QImage 로드
            image = QImage()
            if not image.loadFromData(data):
                raise ValueError("이미지 로드 실패")

            # 리사이징 (SmoothTransformation)
            scaled = image.scaled(
                self.size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            pixmap = QPixmap.fromImage(scaled)
            image_cache.put(self.url, pixmap)
            self.signals.finished.emit(self.product_id, pixmap)

        except Exception as e:
            self.signals.error.emit(self.product_id, str(e))


# ============================================================
# 상품 수집 워커 (QThread)
# ============================================================
class CollectWorker(QThread):
    """상품 수집 백그라운드 워커 + 검수 로직"""
    progress = pyqtSignal(int, int, str)  # current, total, message
    log = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str, list)  # success, message, data

    def __init__(self, api_client, groups: List[str], settings: dict):
        super().__init__()
        self.api_client = api_client
        self.groups = groups
        self.settings = settings
        self.is_running = True

    def stop(self):
        self.is_running = False

    def run(self):
        try:
            all_products = []
            total_groups = len(self.groups)

            # 검수 설정 로드
            bait_keywords = self.settings.get('bait_keywords', [])
            excluded_words = self.settings.get('excluded_words', set())
            check_level = self.settings.get('check_level', 'normal')
            option_count = self.settings.get('option_count', 10)

            for idx, group_name in enumerate(self.groups):
                if not self.is_running:
                    break

                self.log.emit(f"📁 [{idx+1}/{total_groups}] {group_name} 수집 중...")
                self.progress.emit(idx + 1, total_groups, group_name)

                try:
                    # 상품 조회
                    max_products = self.settings.get('max_products', 100)
                    status_filters = self.settings.get('status_filters')

                    products, total = self.api_client.get_products_by_group(
                        group_name, 0, max_products, status_filters
                    )

                    if products:
                        # 각 상품 검수 처리
                        for p in products:
                            p['group_name'] = group_name
                            self._inspect_product(p, bait_keywords, excluded_words, check_level, option_count)
                        all_products.extend(products)

                        # 안전/위험 카운트
                        safe_count = sum(1 for p in products if p.get('is_safe', True))
                        unsafe_count = len(products) - safe_count
                        self.log.emit(f"   ✅ {len(products)}개 수집 (안전:{safe_count} 위험:{unsafe_count})")
                    else:
                        self.log.emit(f"   ⏭️ 상품 없음")

                except Exception as e:
                    self.log.emit(f"   ❌ 오류: {e}")

            self.finished_signal.emit(True, f"수집 완료: {len(all_products)}개", all_products)

        except Exception as e:
            self.finished_signal.emit(False, str(e), [])

    def _inspect_product(self, product: dict, bait_keywords: list,
                         excluded_words: set, check_level: str, option_count: int):
        """상품 검수 (미끼필터, 대표옵션, 안전검사)"""
        try:
            product_name = product.get('uploadCommonProductName', '')
            category_name = product.get('uploadCategory', '')

            # 1. 상품명 안전 검사
            if BULSAJA_API_AVAILABLE:
                safety = check_product_safety(
                    product_name, excluded_words,
                    check_level=check_level,
                    category_name=category_name
                )
                product['is_safe'] = safety['is_safe']
                product['unsafe_keywords'] = safety.get('all_found', [])

                # 위험 사유 포맷팅
                if not safety['is_safe']:
                    categories = []
                    cats = safety.get('categories', {})
                    if cats.get('adult'):
                        categories.append(f"성인:{','.join(cats['adult'][:2])}")
                    if cats.get('medical'):
                        categories.append(f"의료:{','.join(cats['medical'][:2])}")
                    if cats.get('child'):
                        categories.append(f"유아:{','.join(cats['child'][:2])}")
                    if cats.get('prohibited'):
                        categories.append(f"금지:{','.join(cats['prohibited'][:2])}")
                    if cats.get('brand'):
                        categories.append(f"브랜드:{','.join(cats['brand'][:2])}")
                    product['unsafe_reason'] = ' / '.join(categories) if categories else '위험키워드감지'
                else:
                    product['unsafe_reason'] = ''
            else:
                product['is_safe'] = True
                product['unsafe_reason'] = ''

            # 2. SKU 정보 처리
            upload_skus = product.get('uploadSkus', []) or product.get('uploadCommonOptions', []) or []
            product['total_options'] = len(upload_skus)

            if upload_skus and BULSAJA_API_AVAILABLE:
                # 미끼옵션 필터링
                valid_skus, bait_skus = filter_bait_options(upload_skus, bait_keywords)

                product['valid_options'] = len(valid_skus)
                product['bait_options'] = len(bait_skus)
                product['bait_option_list'] = []

                # 미끼 옵션 정보
                for bait_sku in bait_skus[:5]:
                    opt_name = bait_sku.get('text_ko', '') or bait_sku.get('optionName', '') or ''
                    bait_price = bait_sku.get('_origin_price', 0) or bait_sku.get('price', 0)
                    product['bait_option_list'].append(f"{opt_name[:15]}({bait_price})")

                # 대표옵션 선택 (이미지 있는 최저가)
                if valid_skus:
                    main_idx, main_method = select_main_option(product_name, valid_skus)
                    main_sku = valid_skus[main_idx]

                    product['main_option_name'] = main_sku.get('text_ko', '') or main_sku.get('optionName', '')
                    product['main_option_method'] = main_method
                    product['main_option_image'] = main_sku.get('urlRef', '') or main_sku.get('optionImage', '')

                    # 대표옵션 가격 기준 최종 옵션 목록
                    def safe_price(val):
                        try:
                            return float(val) if val else 0.0
                        except:
                            return 0.0

                    main_price = safe_price(main_sku.get('_origin_price') or main_sku.get('price'))

                    if option_count > 0:
                        eligible = [s for s in valid_skus if safe_price(s.get('_origin_price') or s.get('price')) >= main_price]
                        eligible.sort(key=lambda x: safe_price(x.get('_origin_price') or x.get('price')))
                        final_skus = eligible[:option_count]
                    else:
                        final_skus = valid_skus

                    product['final_options'] = len(final_skus)
                    product['final_option_list'] = []

                    for sku in final_skus:
                        opt_name = sku.get('text_ko', '') or sku.get('optionName', '')
                        opt_price = safe_price(sku.get('_origin_price') or sku.get('price'))
                        product['final_option_list'].append(f"{opt_name[:20]}({opt_price:.1f})")

        except Exception as e:
            product['is_safe'] = True
            product['unsafe_reason'] = f"검수오류: {str(e)[:30]}"


# ============================================================
# 이미지 라벨 (플레이스홀더 포함)
# ============================================================
class ImageLabel(QLabel):
    """플레이스홀더 지원 이미지 라벨"""

    def __init__(self, size: int = 60, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.show_placeholder()

    def show_placeholder(self):
        self.setText("...")
        self.setStyleSheet("""
            QLabel {
                background-color: #E0E0E0;
                border: 1px solid #BDBDBD;
                border-radius: 4px;
                color: #757575;
                font-size: 10px;
            }
        """)

    def show_error(self):
        self.setText("X")
        self.setStyleSheet("""
            QLabel {
                background-color: #FFCDD2;
                border: 1px solid #EF9A9A;
                border-radius: 4px;
                color: #C62828;
            }
        """)

    def set_image(self, pixmap: QPixmap):
        self.setText("")
        self.setPixmap(pixmap)
        self.setStyleSheet("""
            QLabel {
                background-color: white;
                border: 1px solid #BDBDBD;
                border-radius: 4px;
            }
        """)


# ============================================================
# 메인 윈도우
# ============================================================
class SimulatorGUIv4(QMainWindow):
    """시뮬레이터 GUI v4 - PyQt6 최적화 버전"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("불사자 시뮬레이터 v4 (PyQt6)")
        self.setMinimumSize(1400, 900)

        # 상태
        self.api_client = None
        self.products = []
        self.selected_options = {}
        self.image_labels = {}  # {product_id: ImageLabel}

        # QThreadPool 설정
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(10)

        # 설정 로드
        self.config = load_config()

        self._build_ui()

    def _build_ui(self):
        """UI 구성"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # 탭 위젯
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #BDBDBD;
                border-radius: 4px;
            }
            QTabBar::tab {
                padding: 8px 20px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #E3F2FD;
            }
        """)

        # 각 탭 생성
        self.collection_tab = QWidget()
        self.review_tab = QWidget()
        self.settings_tab = QWidget()

        self.tabs.addTab(self.collection_tab, "  📥 수집  ")
        self.tabs.addTab(self.review_tab, "  🔍 검수  ")
        self.tabs.addTab(self.settings_tab, "  ⚙️ 설정  ")

        self._build_collection_tab()
        self._build_review_tab()
        self._build_settings_tab()

        main_layout.addWidget(self.tabs)

        # 기본 탭: 검수
        self.tabs.setCurrentIndex(1)

    def _build_collection_tab(self):
        """수집 탭 UI"""
        layout = QVBoxLayout(self.collection_tab)

        # 스크롤 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # === API 연결 ===
        api_group = QGroupBox("🔑 API 연결")
        api_layout = QVBoxLayout(api_group)

        api_row1 = QHBoxLayout()
        self.chrome_btn = QPushButton("🌐 크롬 열기")
        self.chrome_btn.clicked.connect(self._open_chrome)
        api_row1.addWidget(self.chrome_btn)

        self.token_btn = QPushButton("🔑 토큰 추출")
        self.token_btn.clicked.connect(self._extract_token)
        api_row1.addWidget(self.token_btn)

        self.connect_btn = QPushButton("🔗 연결")
        self.connect_btn.clicked.connect(self._connect_api)
        api_row1.addWidget(self.connect_btn)

        api_row1.addWidget(QLabel("포트:"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1000, 65535)
        self.port_spin.setValue(9222)
        self.port_spin.setFixedWidth(80)
        api_row1.addWidget(self.port_spin)

        self.api_status = QLabel("⚫ 미연결")
        self.api_status.setStyleSheet("font-weight: bold;")
        api_row1.addWidget(self.api_status)
        api_row1.addStretch()
        api_layout.addLayout(api_row1)

        api_row2 = QHBoxLayout()
        api_row2.addWidget(QLabel("Access:"))
        self.access_input = QLineEdit()
        self.access_input.setPlaceholderText("토큰 추출 또는 수동 입력")
        api_row2.addWidget(self.access_input)
        api_row2.addWidget(QLabel("Refresh:"))
        self.refresh_input = QLineEdit()
        api_row2.addWidget(self.refresh_input)
        api_layout.addLayout(api_row2)

        scroll_layout.addWidget(api_group)

        # === 그룹 설정 ===
        group_group = QGroupBox("📁 마켓그룹 설정")
        group_layout = QVBoxLayout(group_group)

        group_row1 = QHBoxLayout()
        group_row1.addWidget(QLabel("그룹당 최대:"))
        self.max_products_spin = QSpinBox()
        self.max_products_spin.setRange(1, 10000)
        self.max_products_spin.setValue(100)
        self.max_products_spin.setFixedWidth(80)
        group_row1.addWidget(self.max_products_spin)

        group_row1.addWidget(QLabel("작업 그룹:"))
        self.work_groups_input = QLineEdit("1-5")
        self.work_groups_input.setFixedWidth(100)
        group_row1.addWidget(self.work_groups_input)
        group_row1.addWidget(QLabel("(예: 1-5 또는 1,3,5)"))

        self.load_groups_btn = QPushButton("📥 그룹 로드")
        self.load_groups_btn.clicked.connect(self._load_groups)
        group_row1.addWidget(self.load_groups_btn)
        group_row1.addStretch()
        group_layout.addLayout(group_row1)

        self.groups_text = QTextEdit()
        self.groups_text.setMaximumHeight(60)
        self.groups_text.setPlaceholderText("그룹 목록 (쉼표 구분)")
        group_layout.addWidget(self.groups_text)

        scroll_layout.addWidget(group_group)

        # === 수집 조건 ===
        condition_group = QGroupBox("📋 수집 조건")
        condition_layout = QHBoxLayout(condition_group)

        condition_layout.addWidget(QLabel("수집조건:"))
        self.condition_combo = QComboBox()
        self.condition_combo.addItems(list(UPLOAD_CONDITIONS.keys()))
        self.condition_combo.setFixedWidth(280)
        condition_layout.addWidget(self.condition_combo)

        condition_layout.addWidget(QLabel("수집수:"))
        self.collect_count_spin = QSpinBox()
        self.collect_count_spin.setRange(1, 99999)
        self.collect_count_spin.setValue(9999)
        self.collect_count_spin.setFixedWidth(80)
        condition_layout.addWidget(self.collect_count_spin)
        condition_layout.addStretch()

        scroll_layout.addWidget(condition_group)

        # === 옵션 설정 ===
        option_group = QGroupBox("⚙️ 옵션 설정")
        option_layout = QHBoxLayout(option_group)

        option_layout.addWidget(QLabel("옵션수:"))
        self.option_count_spin = QSpinBox()
        self.option_count_spin.setRange(1, 100)
        self.option_count_spin.setValue(10)
        self.option_count_spin.setFixedWidth(60)
        option_layout.addWidget(self.option_count_spin)

        option_layout.addWidget(QLabel("옵션정렬:"))
        self.option_sort_combo = QComboBox()
        self.option_sort_combo.addItems(list(OPTION_SORT_OPTIONS.keys()))
        option_layout.addWidget(self.option_sort_combo)

        option_layout.addWidget(QLabel("상품명:"))
        self.title_combo = QComboBox()
        self.title_combo.addItems(list(TITLE_OPTIONS.keys()))
        self.title_combo.setCurrentText("앞3개단어제외 셔플")
        option_layout.addWidget(self.title_combo)
        option_layout.addStretch()

        scroll_layout.addWidget(option_group)

        # === 검수 설정 ===
        inspect_group = QGroupBox("🔍 검수 설정")
        inspect_layout = QHBoxLayout(inspect_group)

        inspect_layout.addWidget(QLabel("검수수준:"))
        self.check_level_combo = QComboBox()
        self.check_level_combo.addItems(list(CHECK_LEVELS.keys()))
        self.check_level_combo.setFixedWidth(150)
        self.check_level_combo.setToolTip(
            "보통: 프로그램 자동 판단 (안전 컨텍스트 적용)\n"
            "엄격: AI 확인 필수\n"
            "검수제외: 항상 안전으로 처리"
        )
        inspect_layout.addWidget(self.check_level_combo)

        self.filter_bait_check = QCheckBox("미끼옵션 필터링")
        self.filter_bait_check.setChecked(True)
        inspect_layout.addWidget(self.filter_bait_check)

        self.show_unsafe_only_check = QCheckBox("위험상품만 표시")
        self.show_unsafe_only_check.setChecked(False)
        inspect_layout.addWidget(self.show_unsafe_only_check)

        inspect_layout.addStretch()
        scroll_layout.addWidget(inspect_group)

        # === 마진 설정 ===
        margin_group = QGroupBox("💰 마진 설정")
        margin_layout = QHBoxLayout(margin_group)

        margin_layout.addWidget(QLabel("환율:"))
        self.exchange_spin = QSpinBox()
        self.exchange_spin.setRange(100, 500)
        self.exchange_spin.setValue(215)
        self.exchange_spin.setFixedWidth(60)
        margin_layout.addWidget(self.exchange_spin)

        margin_layout.addWidget(QLabel("최저가:"))
        self.min_price_spin = QSpinBox()
        self.min_price_spin.setRange(0, 1000000)
        self.min_price_spin.setValue(30000)
        self.min_price_spin.setFixedWidth(80)
        margin_layout.addWidget(self.min_price_spin)

        margin_layout.addWidget(QLabel("최고가:"))
        self.max_price_spin = QSpinBox()
        self.max_price_spin.setRange(0, 100000000)
        self.max_price_spin.setValue(100000000)
        self.max_price_spin.setFixedWidth(100)
        margin_layout.addWidget(self.max_price_spin)
        margin_layout.addStretch()

        scroll_layout.addWidget(margin_group)

        # === 실행 버튼 ===
        action_group = QGroupBox("🚀 실행")
        action_layout = QHBoxLayout(action_group)

        self.collect_btn = QPushButton("📥 수집 시작")
        self.collect_btn.setFixedHeight(40)
        self.collect_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.collect_btn.clicked.connect(self._start_collect)
        action_layout.addWidget(self.collect_btn)

        self.stop_btn = QPushButton("⏹️ 중지")
        self.stop_btn.setFixedHeight(40)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_collect)
        action_layout.addWidget(self.stop_btn)

        scroll_layout.addWidget(action_group)

        # === 진행 상황 ===
        progress_group = QGroupBox("📊 진행 상황")
        progress_layout = QVBoxLayout(progress_group)

        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("대기 중...")
        progress_layout.addWidget(self.progress_label)

        scroll_layout.addWidget(progress_group)

        # === 로그 ===
        log_group = QGroupBox("📋 로그")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setMaximumHeight(200)
        log_layout.addWidget(self.log_text)

        scroll_layout.addWidget(log_group)
        scroll_layout.addStretch()

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

    def _build_review_tab(self):
        """검수 탭 UI - 상품 테이블 + 이미지 그리드"""
        layout = QVBoxLayout(self.review_tab)

        # 상단 컨트롤
        control_layout = QHBoxLayout()

        self.open_excel_btn = QPushButton("📂 엑셀 열기")
        self.open_excel_btn.clicked.connect(self._open_excel)
        control_layout.addWidget(self.open_excel_btn)

        self.save_excel_btn = QPushButton("💾 엑셀 저장")
        self.save_excel_btn.clicked.connect(self._save_excel)
        control_layout.addWidget(self.save_excel_btn)

        self.apply_btn = QPushButton("📤 불사자 반영")
        self.apply_btn.clicked.connect(self._apply_to_bulsaja)
        control_layout.addWidget(self.apply_btn)

        control_layout.addStretch()

        self.product_count_label = QLabel("상품: 0개")
        self.product_count_label.setStyleSheet("font-weight: bold;")
        control_layout.addWidget(self.product_count_label)

        layout.addLayout(control_layout)

        # 스플리터 (테이블 + 상세)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 왼쪽: 상품 테이블
        table_widget = QWidget()
        table_layout = QVBoxLayout(table_widget)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self.product_table = QTableWidget()
        self.product_table.setColumnCount(10)
        self.product_table.setHorizontalHeaderLabels([
            "썸네일", "상품명", "안전", "위험사유", "옵션", "미끼", "대표옵션", "가격", "그룹", "ID"
        ])
        # 컬럼 너비 설정
        header = self.product_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # 썸네일
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # 상품명
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # 위험사유
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # 대표옵션
        self.product_table.setColumnWidth(0, 60)
        self.product_table.setColumnWidth(2, 50)
        self.product_table.setColumnWidth(4, 50)
        self.product_table.setColumnWidth(5, 50)
        self.product_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.product_table.itemSelectionChanged.connect(self._on_product_selected)
        table_layout.addWidget(self.product_table)

        # 페이지네이션
        page_layout = QHBoxLayout()
        self.prev_btn = QPushButton("◀ 이전")
        self.prev_btn.clicked.connect(lambda: self._change_page(-1))
        page_layout.addWidget(self.prev_btn)

        self.page_label = QLabel("1 / 1")
        page_layout.addWidget(self.page_label)

        self.next_btn = QPushButton("다음 ▶")
        self.next_btn.clicked.connect(lambda: self._change_page(1))
        page_layout.addWidget(self.next_btn)

        page_layout.addStretch()

        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["20", "50", "100"])
        self.page_size_combo.currentTextChanged.connect(self._on_page_size_changed)
        page_layout.addWidget(QLabel("페이지 크기:"))
        page_layout.addWidget(self.page_size_combo)

        table_layout.addLayout(page_layout)
        splitter.addWidget(table_widget)

        # 오른쪽: 상세 정보
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)

        detail_label = QLabel("📋 상품 상세")
        detail_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        detail_layout.addWidget(detail_label)

        # 썸네일 크게
        self.detail_thumbnail = ImageLabel(150)
        detail_layout.addWidget(self.detail_thumbnail)

        # 옵션 이미지 그리드
        option_label = QLabel("옵션 이미지:")
        detail_layout.addWidget(option_label)

        self.option_grid_scroll = QScrollArea()
        self.option_grid_scroll.setWidgetResizable(True)
        self.option_grid_scroll.setMaximumHeight(200)

        self.option_grid = QWidget()
        self.option_grid_layout = QGridLayout(self.option_grid)
        self.option_grid_layout.setSpacing(4)
        self.option_grid_scroll.setWidget(self.option_grid)
        detail_layout.addWidget(self.option_grid_scroll)

        # 상품 정보
        self.detail_info = QTextEdit()
        self.detail_info.setReadOnly(True)
        detail_layout.addWidget(self.detail_info)

        splitter.addWidget(detail_widget)
        splitter.setSizes([700, 300])

        layout.addWidget(splitter)

        # 페이지 상태
        self.current_page = 0
        self.page_size = 20

    def _build_settings_tab(self):
        """설정 탭 UI"""
        layout = QVBoxLayout(self.settings_tab)

        # 미끼 키워드
        keyword_group = QGroupBox("🚫 미끼 키워드")
        keyword_layout = QVBoxLayout(keyword_group)

        keyword_layout.addWidget(QLabel("제외할 키워드 (쉼표 구분):"))
        self.keyword_text = QTextEdit()
        self.keyword_text.setMaximumHeight(100)
        if BULSAJA_API_AVAILABLE:
            keywords = load_bait_keywords()
            self.keyword_text.setText(','.join(keywords))
        keyword_layout.addWidget(self.keyword_text)

        keyword_btn_layout = QHBoxLayout()
        save_keyword_btn = QPushButton("💾 저장")
        save_keyword_btn.clicked.connect(self._save_keywords)
        keyword_btn_layout.addWidget(save_keyword_btn)

        reset_keyword_btn = QPushButton("기본값")
        reset_keyword_btn.clicked.connect(self._reset_keywords)
        keyword_btn_layout.addWidget(reset_keyword_btn)
        keyword_btn_layout.addStretch()
        keyword_layout.addLayout(keyword_btn_layout)

        layout.addWidget(keyword_group)

        # 컬럼 설정
        column_group = QGroupBox("📊 표시 컬럼 설정")
        column_layout = QVBoxLayout(column_group)
        column_layout.addWidget(QLabel("추후 추가 예정"))
        layout.addWidget(column_group)

        layout.addStretch()

    # ============================================================
    # API 연결
    # ============================================================
    def _open_chrome(self):
        """크롬 디버그 모드로 열기"""
        port = self.port_spin.value()
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]

        chrome_path = None
        for p in chrome_paths:
            if os.path.exists(p):
                chrome_path = p
                break

        if not chrome_path:
            QMessageBox.warning(self, "오류", "Chrome을 찾을 수 없습니다.")
            return

        user_data = os.path.expandvars(r"%TEMP%\chrome_debug_simulator")
        cmd = [
            chrome_path,
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={user_data}",
            "https://www.bulsaja.com"
        ]

        try:
            subprocess.Popen(cmd)
            self._log(f"🌐 크롬 열림 (포트: {port})")
        except Exception as e:
            QMessageBox.warning(self, "오류", f"크롬 실행 실패: {e}")

    def _extract_token(self):
        """토큰 추출"""
        if not BULSAJA_API_AVAILABLE:
            QMessageBox.warning(self, "오류", "bulsaja_common 모듈이 없습니다.")
            return

        port = self.port_spin.value()
        self._log(f"🔑 토큰 추출 중... (포트: {port})")

        success, access, refresh, msg = extract_tokens_from_browser(port)
        if success and access:
            self.access_input.setText(access)
            self.refresh_input.setText(refresh)
            self._log("✅ 토큰 추출 성공")
            self._connect_api()
        else:
            self._log(f"❌ 토큰 추출 실패: {msg}")
            QMessageBox.warning(self, "실패", msg)

    def _connect_api(self):
        """API 연결"""
        if not BULSAJA_API_AVAILABLE:
            QMessageBox.warning(self, "오류", "bulsaja_common 모듈이 없습니다.")
            return

        access = self.access_input.text().strip()
        refresh = self.refresh_input.text().strip()

        if not access or not refresh:
            QMessageBox.warning(self, "경고", "토큰을 입력해주세요.")
            return

        try:
            self.api_client = BulsajaAPIClient(access, refresh)
            groups = self.api_client.get_market_groups()

            self.api_status.setText(f"🟢 연결됨 ({len(groups)}개 그룹)")
            self.api_status.setStyleSheet("font-weight: bold; color: #4CAF50;")
            self._log(f"✅ API 연결 성공! {len(groups)}개 그룹")

            # 그룹 목록 설정
            self.groups_text.setText(', '.join(groups))

        except Exception as e:
            self.api_status.setText("🔴 연결 실패")
            self.api_status.setStyleSheet("font-weight: bold; color: #F44336;")
            self._log(f"❌ 연결 실패: {e}")
            QMessageBox.critical(self, "오류", f"연결 실패:\n{e}")

    def _load_groups(self):
        """그룹 목록 로드"""
        if not self.api_client:
            QMessageBox.warning(self, "경고", "먼저 API에 연결하세요.")
            return

        try:
            groups = self.api_client.get_market_groups()
            self.groups_text.setText(', '.join(groups))
            self._log(f"📥 {len(groups)}개 그룹 로드됨")
        except Exception as e:
            self._log(f"❌ 그룹 로드 실패: {e}")

    # ============================================================
    # 수집
    # ============================================================
    def _start_collect(self):
        """수집 시작"""
        if not self.api_client:
            QMessageBox.warning(self, "경고", "먼저 API에 연결하세요.")
            return

        # 그룹 파싱
        groups_text = self.groups_text.toPlainText().strip()
        if not groups_text:
            QMessageBox.warning(self, "경고", "그룹을 입력하세요.")
            return

        all_groups = [g.strip() for g in groups_text.split(',') if g.strip()]
        work_range = self.work_groups_input.text().strip()

        # 범위 파싱
        selected_groups = []
        try:
            if '-' in work_range:
                start, end = map(int, work_range.split('-'))
                selected_groups = all_groups[start-1:end]
            elif ',' in work_range:
                indices = [int(x.strip()) for x in work_range.split(',')]
                selected_groups = [all_groups[i-1] for i in indices if 0 < i <= len(all_groups)]
            else:
                idx = int(work_range)
                if 0 < idx <= len(all_groups):
                    selected_groups = [all_groups[idx-1]]
        except:
            selected_groups = all_groups

        if not selected_groups:
            QMessageBox.warning(self, "경고", "유효한 그룹이 없습니다.")
            return

        self._log(f"🚀 수집 시작: {len(selected_groups)}개 그룹")

        # 미끼 키워드 로드
        bait_keywords = []
        excluded_words = set()
        if BULSAJA_API_AVAILABLE:
            bait_keywords = load_bait_keywords() if self.filter_bait_check.isChecked() else []
            excluded_words = load_excluded_words()

        # 검수 수준
        check_level_text = self.check_level_combo.currentText()
        check_level = CHECK_LEVELS.get(check_level_text, 'normal')

        # 설정
        settings = {
            'max_products': self.max_products_spin.value(),
            'status_filters': UPLOAD_CONDITIONS.get(self.condition_combo.currentText()),
            'bait_keywords': bait_keywords,
            'excluded_words': excluded_words,
            'check_level': check_level,
            'option_count': self.option_count_spin.value(),
        }

        self._log(f"   검수수준: {check_level_text}, 미끼필터: {'O' if bait_keywords else 'X'}")

        # 워커 시작
        self.collect_worker = CollectWorker(self.api_client, selected_groups, settings)
        self.collect_worker.progress.connect(self._on_collect_progress)
        self.collect_worker.log.connect(self._log)
        self.collect_worker.finished_signal.connect(self._on_collect_finished)

        self.collect_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)

        self.collect_worker.start()

    def _stop_collect(self):
        """수집 중지"""
        if hasattr(self, 'collect_worker'):
            self.collect_worker.stop()
            self._log("⏹️ 중지 요청됨...")

    def _on_collect_progress(self, current: int, total: int, group_name: str):
        """수집 진행 상황"""
        percent = int(current / total * 100) if total > 0 else 0
        self.progress_bar.setValue(percent)
        self.progress_label.setText(f"진행: {current}/{total} - {group_name}")

    def _on_collect_finished(self, success: bool, message: str, products: list):
        """수집 완료"""
        self.collect_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        self.progress_label.setText(message)

        if success and products:
            self.products = products
            self._log(f"✅ {message}")
            self._update_product_table()
            self.tabs.setCurrentIndex(1)  # 검수 탭으로 이동
        else:
            self._log(f"⚠️ {message}")

    # ============================================================
    # 검수 탭
    # ============================================================
    def _update_product_table(self):
        """상품 테이블 업데이트"""
        self.product_count_label.setText(f"상품: {len(self.products)}개")

        # 페이지 계산
        total_pages = max(1, (len(self.products) + self.page_size - 1) // self.page_size)
        self.current_page = min(self.current_page, total_pages - 1)

        start_idx = self.current_page * self.page_size
        end_idx = min(start_idx + self.page_size, len(self.products))
        page_products = self.products[start_idx:end_idx]

        self.page_label.setText(f"{self.current_page + 1} / {total_pages}")

        # 위험상품만 표시 옵션
        show_unsafe_only = self.show_unsafe_only_check.isChecked() if hasattr(self, 'show_unsafe_only_check') else False
        if show_unsafe_only:
            page_products = [p for p in page_products if not p.get('is_safe', True)]

        # 테이블 채우기
        self.product_table.setRowCount(len(page_products))

        for row, product in enumerate(page_products):
            product_id = product.get('ID', '')

            # 0. 썸네일
            thumb_label = ImageLabel(50)
            self.image_labels[product_id] = thumb_label
            self.product_table.setCellWidget(row, 0, thumb_label)

            # 썸네일 로드 (백그라운드)
            thumb_url = product.get('uploadCommonThumbnail', '')
            if thumb_url:
                self._load_image_async(product_id, thumb_url)

            # 1. 상품명
            name = product.get('uploadCommonProductName', '')[:50]
            name_item = QTableWidgetItem(name)
            self.product_table.setItem(row, 1, name_item)

            # 2. 안전
            is_safe = product.get('is_safe', True)
            safe_text = "✅" if is_safe else "⚠️"
            safe_item = QTableWidgetItem(safe_text)
            if not is_safe:
                safe_item.setBackground(QColor("#FFCDD2"))
            self.product_table.setItem(row, 2, safe_item)

            # 3. 위험사유
            unsafe_reason = product.get('unsafe_reason', '')
            reason_item = QTableWidgetItem(unsafe_reason[:30] if unsafe_reason else '')
            if unsafe_reason:
                reason_item.setBackground(QColor("#FFCDD2"))
            self.product_table.setItem(row, 3, reason_item)

            # 4. 옵션수 (유효/전체)
            total_opts = product.get('total_options', 0)
            valid_opts = product.get('valid_options', total_opts)
            if valid_opts != total_opts:
                opt_text = f"{valid_opts}/{total_opts}"
            else:
                opt_text = str(total_opts)
            self.product_table.setItem(row, 4, QTableWidgetItem(opt_text))

            # 5. 미끼옵션수
            bait_count = product.get('bait_options', 0)
            bait_item = QTableWidgetItem(str(bait_count) if bait_count > 0 else '')
            if bait_count > 0:
                bait_item.setBackground(QColor("#FFF9C4"))  # 노랑
            self.product_table.setItem(row, 5, bait_item)

            # 6. 대표옵션
            main_option = product.get('main_option_name', '')[:20]
            main_method = product.get('main_option_method', '')
            main_text = f"{main_option}" if main_option else ''
            if main_method:
                main_text = f"{main_option}({main_method})"
            self.product_table.setItem(row, 6, QTableWidgetItem(main_text[:25]))

            # 7. 가격
            price = product.get('uploadCommonSalePrice', 0)
            self.product_table.setItem(row, 7, QTableWidgetItem(f"{price:,}" if price else ''))

            # 8. 그룹
            group = product.get('group_name', '')
            self.product_table.setItem(row, 8, QTableWidgetItem(group))

            # 9. ID
            self.product_table.setItem(row, 9, QTableWidgetItem(product_id))

        self.product_table.resizeRowsToContents()

    def _load_image_async(self, product_id: str, url: str):
        """비동기 이미지 로드"""
        worker = ImageDownloadWorker(product_id, url, QSize(50, 50))
        worker.signals.finished.connect(self._on_image_loaded)
        worker.signals.error.connect(self._on_image_error)
        self.thread_pool.start(worker)

    def _on_image_loaded(self, product_id: str, pixmap: QPixmap):
        """이미지 로드 완료"""
        if product_id in self.image_labels:
            self.image_labels[product_id].set_image(pixmap)

    def _on_image_error(self, product_id: str, error: str):
        """이미지 로드 에러"""
        if product_id in self.image_labels:
            self.image_labels[product_id].show_error()

    def _change_page(self, delta: int):
        """페이지 변경"""
        total_pages = max(1, (len(self.products) + self.page_size - 1) // self.page_size)
        new_page = self.current_page + delta

        if 0 <= new_page < total_pages:
            self.current_page = new_page
            self._update_product_table()

    def _on_page_size_changed(self, size_text: str):
        """페이지 크기 변경"""
        self.page_size = int(size_text)
        self.current_page = 0
        self._update_product_table()

    def _on_product_selected(self):
        """상품 선택 시"""
        rows = self.product_table.selectedItems()
        if not rows:
            return

        row = self.product_table.currentRow()
        start_idx = self.current_page * self.page_size
        product_idx = start_idx + row

        if 0 <= product_idx < len(self.products):
            product = self.products[product_idx]
            self._show_product_detail(product)

    def _show_product_detail(self, product: dict):
        """상품 상세 표시"""
        # 썸네일
        thumb_url = product.get('uploadCommonThumbnail', '')
        if thumb_url:
            worker = ImageDownloadWorker("detail", thumb_url, QSize(150, 150))
            worker.signals.finished.connect(
                lambda pid, pix: self.detail_thumbnail.set_image(pix)
            )
            self.thread_pool.start(worker)

        # 옵션 이미지 그리드
        for i in reversed(range(self.option_grid_layout.count())):
            widget = self.option_grid_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()

        options = product.get('uploadCommonOptions', []) or []
        for i, opt in enumerate(options[:20]):  # 최대 20개
            opt_url = opt.get('optionImage', '')
            if opt_url:
                label = ImageLabel(50)
                self.option_grid_layout.addWidget(label, i // 8, i % 8)

                worker = ImageDownloadWorker(f"opt_{i}", opt_url, QSize(50, 50))
                worker.signals.finished.connect(
                    lambda pid, pix, lbl=label: lbl.set_image(pix)
                )
                self.thread_pool.start(worker)

        # 상세 정보 (검수 결과 포함)
        is_safe = product.get('is_safe', True)
        safe_status = "✅ 안전" if is_safe else "⚠️ 위험"
        unsafe_reason = product.get('unsafe_reason', '')
        main_option = product.get('main_option_name', '')
        main_method = product.get('main_option_method', '')
        bait_count = product.get('bait_options', 0)
        bait_list = product.get('bait_option_list', [])
        final_options = product.get('final_option_list', [])

        info = f"""상품명: {product.get('uploadCommonProductName', '')}

[검수결과] {safe_status}
{f'위험사유: {unsafe_reason}' if unsafe_reason else ''}

그룹: {product.get('group_name', '')}
ID: {product.get('ID', '')}
가격: {product.get('uploadCommonSalePrice', 0):,}원
카테고리: {product.get('uploadCategory', '')}

[옵션정보]
전체옵션: {product.get('total_options', len(options))}개
유효옵션: {product.get('valid_options', len(options))}개
미끼옵션: {bait_count}개
{f'미끼: {", ".join(bait_list[:3])}' if bait_list else ''}

[대표옵션]
{main_option} ({main_method})
{f'이미지: {product.get("main_option_image", "없음")[:50]}' if product.get("main_option_image") else ''}

[최종옵션목록]
{chr(10).join(f"• {opt}" for opt in final_options[:8]) if final_options else '없음'}
"""
        self.detail_info.setText(info)

    # ============================================================
    # 엑셀
    # ============================================================
    def _open_excel(self):
        """엑셀 열기"""
        if not OPENPYXL_AVAILABLE:
            QMessageBox.warning(self, "오류", "openpyxl이 설치되지 않았습니다.")
            return

        filepath, _ = QFileDialog.getOpenFileName(
            self, "엑셀 열기", "", "Excel Files (*.xlsx)"
        )
        if not filepath:
            return

        try:
            wb = load_workbook(filepath)
            ws = wb.active

            # 데이터 읽기
            headers = [cell.value for cell in ws[1]]
            self.products = []

            for row in ws.iter_rows(min_row=2, values_only=True):
                product = dict(zip(headers, row))
                if product.get('ID') or product.get('불사자ID'):
                    # ID 필드 정규화
                    if '불사자ID' in product:
                        product['ID'] = product['불사자ID']
                    self.products.append(product)

            wb.close()
            self._log(f"📂 엑셀 로드: {len(self.products)}개 상품")
            self._update_product_table()

        except Exception as e:
            self._log(f"❌ 엑셀 로드 실패: {e}")
            QMessageBox.critical(self, "오류", f"엑셀 로드 실패:\n{e}")

    def _save_excel(self):
        """엑셀 저장"""
        if not OPENPYXL_AVAILABLE:
            QMessageBox.warning(self, "오류", "openpyxl이 설치되지 않았습니다.")
            return

        if not self.products:
            QMessageBox.warning(self, "경고", "저장할 상품이 없습니다.")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "엑셀 저장",
            f"simulation_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            "Excel Files (*.xlsx)"
        )
        if not filepath:
            return

        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "상품목록"

            # 헤더
            headers = ['ID', '상품명', '그룹', '가격', '옵션수', '안전', '썸네일URL']
            ws.append(headers)

            # 데이터
            for p in self.products:
                options = p.get('uploadCommonOptions', []) or []
                ws.append([
                    p.get('ID', ''),
                    p.get('uploadCommonProductName', ''),
                    p.get('group_name', ''),
                    p.get('uploadCommonSalePrice', 0),
                    len(options),
                    '안전' if p.get('is_safe', True) else '위험',
                    p.get('uploadCommonThumbnail', ''),
                ])

            wb.save(filepath)
            self._log(f"💾 엑셀 저장: {filepath}")
            QMessageBox.information(self, "저장 완료", f"저장됨: {filepath}")

        except Exception as e:
            self._log(f"❌ 저장 실패: {e}")
            QMessageBox.critical(self, "오류", f"저장 실패:\n{e}")

    def _apply_to_bulsaja(self):
        """불사자에 반영"""
        QMessageBox.information(self, "알림", "추후 구현 예정")

    # ============================================================
    # 설정
    # ============================================================
    def _save_keywords(self):
        """키워드 저장"""
        if BULSAJA_API_AVAILABLE:
            keywords = [k.strip() for k in self.keyword_text.toPlainText().split(',') if k.strip()]
            save_bait_keywords(keywords)
            self._log("💾 미끼 키워드 저장됨")
            QMessageBox.information(self, "저장", "미끼 키워드가 저장되었습니다.")

    def _reset_keywords(self):
        """키워드 초기화"""
        if BULSAJA_API_AVAILABLE:
            self.keyword_text.setText(','.join(DEFAULT_BAIT_KEYWORDS))
            self._log("🔄 미끼 키워드 초기화됨")

    # ============================================================
    # 유틸
    # ============================================================
    def _log(self, message: str):
        """로그 출력"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")


# ============================================================
# 메인
# ============================================================
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = SimulatorGUIv4()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
