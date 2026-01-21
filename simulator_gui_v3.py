# -*- coding: utf-8 -*-
"""
시뮬레이터 GUI v3 - 확장된 데이터 수집 + 컬럼 설정 + 불사자 API 연동
- 썸네일 분석 (누끼/텍스트 점수)
- 컬럼 표시/순서 설정
- 더 많은 정보 수집
- 불사자 API로 대표옵션 업데이트
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import os
import json
import threading
import subprocess
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    from PIL import Image, ImageTk
    import requests
    from io import BytesIO
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# 불사자 공통 모듈 (업로더/시뮬레이터 동일하게 사용)
try:
    from bulsaja_common import (
        BulsajaAPIClient, extract_tokens_from_browser,
        filter_bait_options, select_main_option,
        match_thumbnail_to_sku,
        load_bait_keywords, save_bait_keywords,
        load_banned_words, load_excluded_words,
        check_product_safety,
        load_category_risk_settings, save_category_risk_settings,
        DEFAULT_CATEGORY_RISK_SETTINGS,
        MARKET_IDS, DEFAULT_BAIT_KEYWORDS
    )
    BULSAJA_API_AVAILABLE = True
except ImportError:
    BULSAJA_API_AVAILABLE = False

# 엑셀 라이브러리 (상세 형식)
try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


# ==================== 설정 파일 ====================
CONFIG_FILE = "simulator_gui_v3_config.json"
DEBUG_PORT = 9222


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


# 전체 컬럼 정의 (수집 가능한 모든 데이터)
ALL_COLUMNS = {
    # 기본 정보
    "thumbnail": {"name": "썸네일", "width": 100, "category": "기본", "default": True},
    "options": {"name": "옵션 선택", "width": 450, "category": "기본", "default": True},
    "product_name": {"name": "상품명", "width": 180, "category": "기본", "default": True},
    "is_safe": {"name": "안전", "width": 50, "category": "기본", "default": True},
    "option_count": {"name": "옵션수", "width": 60, "category": "기본", "default": True},
    "group_name": {"name": "그룹명", "width": 100, "category": "기본", "default": True},

    # 썸네일 분석
    "thumb_score": {"name": "썸네일점수", "width": 80, "category": "썸네일", "default": True},
    "thumb_nukki": {"name": "누끼", "width": 50, "category": "썸네일", "default": False},
    "thumb_text": {"name": "텍스트", "width": 50, "category": "썸네일", "default": False},
    "thumb_action": {"name": "필요작업", "width": 80, "category": "썸네일", "default": True},

    # 가격 정보
    "price_cny": {"name": "위안가", "width": 70, "category": "가격", "default": False},
    "price_krw": {"name": "원화가", "width": 80, "category": "가격", "default": False},
    "sale_price": {"name": "판매가", "width": 80, "category": "가격", "default": True},

    # 옵션 상세
    "total_options": {"name": "전체옵션", "width": 60, "category": "옵션", "default": False},
    "bait_options": {"name": "미끼옵션", "width": 60, "category": "옵션", "default": True},
    "main_option": {"name": "대표옵션", "width": 100, "category": "옵션", "default": False},

    # 기타
    "product_id": {"name": "불사자ID", "width": 100, "category": "기타", "default": True},
    "unsafe_reason": {"name": "위험사유", "width": 150, "category": "기타", "default": False},
}

DEFAULT_COLUMN_ORDER = [
    "product_id", "thumbnail", "options", "product_name", "thumb_score", "thumb_action",
    "is_safe", "bait_options", "sale_price", "option_count", "group_name"
]

# ==================== 수집 설정 (업로더 v1.5와 동일) ====================

# 업로드 조건 (불사자 상태값)
UPLOAD_CONDITIONS = {
    "미업로드(수집완료+수정중+검토완료)": ["0", "1", "2", "수집 완료", "수정중", "검토 완료"],
    "수집완료만": ["0", "수집 완료"],
    "수정중만": ["1", "수정중"],
    "검토완료만": ["2", "검토 완료"],
    "업로드완료(판매중)": ["3", "판매중", "업로드 완료"],
    "전체": None,  # 필터 없음
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


# ==================== 엑셀 반영 클래스 ====================
class ExcelApplier:
    """엑셀에서 수정한 내용을 불사자에 반영"""

    def __init__(self, api_client, log_callback=None):
        self.api_client = api_client
        self.log = log_callback or print
        self.is_running = False
        self.stats = {
            "total": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
        }

    def read_excel(self, filepath: str) -> List[Dict]:
        """엑셀 파일 읽기 (상세정보 시트 우선)"""
        try:
            wb = load_workbook(filepath, data_only=True)

            # 상세정보 시트 우선, 없으면 첫 번째 시트
            if "상세정보" in wb.sheetnames:
                ws = wb["상세정보"]
            else:
                ws = wb.active

            # 헤더 읽기
            headers = []
            for col in range(1, ws.max_column + 1):
                val = ws.cell(row=1, column=col).value
                headers.append(str(val).strip() if val else f"col_{col}")

            # 데이터 읽기
            data = []
            for row_idx in range(2, ws.max_row + 1):
                row_data = {}
                for col_idx, header in enumerate(headers, 1):
                    val = ws.cell(row=row_idx, column=col_idx).value
                    row_data[header] = val
                # 불사자ID가 있는 행만 추가
                if row_data.get('불사자ID') or row_data.get('id'):
                    data.append(row_data)

            wb.close()
            return data

        except Exception as e:
            self.log(f"❌ 엑셀 읽기 실패: {e}")
            return []

    def parse_selected_option(self, select_value: str, options_text: str) -> Optional[Dict]:
        """
        선택된 옵션 파싱
        select_value: 'A', 'B', 'C' 등
        options_text: 'A. 옵션1(10.5)\nB. 옵션2(15.0)' 형태
        """
        import re
        if not select_value or not options_text:
            return None

        select_value = str(select_value).strip().upper()
        if not select_value:
            return None

        # 옵션 목록 파싱
        lines = options_text.strip().split('\n')
        for idx, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue

            # "A. 옵션명(가격)" 형태 파싱
            if line.startswith(f"{select_value}."):
                option_part = line[2:].strip()
                price_match = re.search(r'\((\d+\.?\d*)\)$', option_part)
                price = float(price_match.group(1)) if price_match else 0
                name = re.sub(r'\(\d+\.?\d*\)$', '', option_part).strip()

                return {
                    'name': name,
                    'price': price,
                    'index': idx,
                    'label': select_value
                }

        return None

    def apply_changes(self, excel_data: List[Dict], options: Dict):
        """엑셀 변경사항을 불사자에 반영"""
        self.is_running = True
        self.stats = {"total": 0, "updated": 0, "skipped": 0, "failed": 0}

        apply_main_option = options.get('apply_main_option', True)
        skip_dangerous = options.get('skip_dangerous', True)

        self.log("")
        self.log("=" * 50)
        self.log("📝 엑셀 반영 시작")
        self.log(f"   총 {len(excel_data)}개 상품")
        self.log(f"   대표옵션 반영: {'O' if apply_main_option else 'X'}")
        self.log(f"   위험상품 스킵: {'O' if skip_dangerous else 'X'}")
        self.log("=" * 50)

        for idx, row in enumerate(excel_data):
            if not self.is_running:
                break

            self.stats['total'] += 1
            product_id = str(row.get('불사자ID') or row.get('id') or '').strip()

            if not product_id:
                self.stats['skipped'] += 1
                continue

            # 안전여부 확인
            safety_value = str(row.get('안전여부', '')).strip().upper()
            is_dangerous = safety_value in ['X', '위험', 'DANGER', 'FALSE', '0']

            if is_dangerous and skip_dangerous:
                self.stats['skipped'] += 1
                continue

            # 대표옵션 변경
            if apply_main_option:
                select_value = row.get('선택', 'A')
                options_text = row.get('최종옵션목록') or row.get('옵션명', '')

                selected = self.parse_selected_option(select_value, options_text)
                if selected and selected['label'] != 'A':
                    # A가 아닌 다른 옵션을 선택한 경우 → 대표옵션 변경
                    try:
                        detail = self.api_client.get_product_detail(product_id)
                        upload_skus = detail.get('uploadSkus', [])

                        if upload_skus and selected['index'] < len(upload_skus):
                            # 모든 옵션 main_product False로
                            for sku in upload_skus:
                                sku['main_product'] = False
                            # 선택된 옵션 main_product True로
                            upload_skus[selected['index']]['main_product'] = True

                            # API 업데이트
                            update_data = {'uploadSkus': upload_skus}
                            success = self.api_client.update_product(product_id, update_data)

                            if success:
                                self.stats['updated'] += 1
                                self.log(f"✅ [{idx+1}] {product_id} → 옵션 {selected['label']} 선택")
                            else:
                                self.stats['failed'] += 1
                                self.log(f"❌ [{idx+1}] {product_id} → 업데이트 실패")
                        else:
                            self.stats['skipped'] += 1
                    except Exception as e:
                        self.stats['failed'] += 1
                        self.log(f"❌ [{idx+1}] {product_id} → 오류: {e}")
                else:
                    self.stats['skipped'] += 1
            else:
                self.stats['skipped'] += 1

            # 10개마다 로그
            if (idx + 1) % 10 == 0:
                self.log(f"   ... {idx+1}/{len(excel_data)} 처리 완료")

        self.log("")
        self.log("=" * 50)
        self.log("📊 반영 완료")
        self.log(f"   총: {self.stats['total']} / 업데이트: {self.stats['updated']}")
        self.log(f"   스킵: {self.stats['skipped']} / 실패: {self.stats['failed']}")
        self.log("=" * 50)


class ColumnSettingsDialog:
    """컬럼 설정 다이얼로그"""

    def __init__(self, parent, current_columns: List[str], column_order: List[str]):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("컬럼 설정")
        self.dialog.geometry("500x600")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self.result = None
        self.current_columns = set(current_columns)
        self.column_order = list(column_order)

        self._create_ui()

    def _create_ui(self):
        # 설명
        ttk.Label(self.dialog, text="표시할 컬럼을 선택하고 순서를 조정하세요",
                 font=("맑은 고딕", 10)).pack(pady=10)

        # 메인 프레임
        main_frame = ttk.Frame(self.dialog)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 왼쪽: 체크박스 목록
        left_frame = ttk.LabelFrame(main_frame, text="컬럼 선택", padding=5)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        # 카테고리별 그룹
        self.checkboxes = {}
        categories = {}
        for col_id, col_info in ALL_COLUMNS.items():
            cat = col_info["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append((col_id, col_info))

        for cat_name, cols in categories.items():
            cat_frame = ttk.LabelFrame(left_frame, text=cat_name, padding=3)
            cat_frame.pack(fill=tk.X, pady=2)

            for col_id, col_info in cols:
                var = tk.BooleanVar(value=col_id in self.current_columns)
                cb = ttk.Checkbutton(cat_frame, text=col_info["name"], variable=var)
                cb.pack(anchor=tk.W)
                self.checkboxes[col_id] = var

        # 오른쪽: 순서 조정
        right_frame = ttk.LabelFrame(main_frame, text="컬럼 순서", padding=5)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # 리스트박스
        self.listbox = tk.Listbox(right_frame, height=15, selectmode=tk.SINGLE)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for col_id in self.column_order:
            if col_id in ALL_COLUMNS:
                self.listbox.insert(tk.END, f"{ALL_COLUMNS[col_id]['name']} ({col_id})")

        # 버튼
        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5)

        ttk.Button(btn_frame, text="▲", width=3, command=self._move_up).pack(pady=2)
        ttk.Button(btn_frame, text="▼", width=3, command=self._move_down).pack(pady=2)

        # 하단 버튼
        bottom_frame = ttk.Frame(self.dialog)
        bottom_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(bottom_frame, text="기본값", command=self._reset_default).pack(side=tk.LEFT)
        ttk.Button(bottom_frame, text="취소", command=self.dialog.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bottom_frame, text="적용", command=self._apply).pack(side=tk.RIGHT)

    def _move_up(self):
        idx = self.listbox.curselection()
        if idx and idx[0] > 0:
            i = idx[0]
            item = self.listbox.get(i)
            self.listbox.delete(i)
            self.listbox.insert(i - 1, item)
            self.listbox.selection_set(i - 1)
            # 순서 업데이트
            self.column_order[i], self.column_order[i-1] = self.column_order[i-1], self.column_order[i]

    def _move_down(self):
        idx = self.listbox.curselection()
        if idx and idx[0] < self.listbox.size() - 1:
            i = idx[0]
            item = self.listbox.get(i)
            self.listbox.delete(i)
            self.listbox.insert(i + 1, item)
            self.listbox.selection_set(i + 1)
            # 순서 업데이트
            self.column_order[i], self.column_order[i+1] = self.column_order[i+1], self.column_order[i]

    def _reset_default(self):
        # 체크박스 초기화
        for col_id, col_info in ALL_COLUMNS.items():
            self.checkboxes[col_id].set(col_info["default"])

        # 순서 초기화
        self.column_order = list(DEFAULT_COLUMN_ORDER)
        self.listbox.delete(0, tk.END)
        for col_id in self.column_order:
            if col_id in ALL_COLUMNS:
                self.listbox.insert(tk.END, f"{ALL_COLUMNS[col_id]['name']} ({col_id})")

    def _apply(self):
        selected = [col_id for col_id, var in self.checkboxes.items() if var.get()]
        self.result = {
            "columns": selected,
            "order": self.column_order
        }
        self.dialog.destroy()


class SimulatorGUIv3:
    """시뮬레이터 GUI v3 - 탭 구조 (수집|검수|설정)"""

    def __init__(self, root):
        self.root = root
        self.root.title("불사자 시뮬레이터 v3")
        self.root.geometry("1600x900")

        self.data = []
        self.selected_options = {}
        self.option_frames = {}
        self.image_cache = {}

        # 컬럼 설정
        self.visible_columns = [col for col, info in ALL_COLUMNS.items() if info["default"]]
        self.column_order = list(DEFAULT_COLUMN_ORDER)

        # 설정 파일 로드
        self._load_settings()

        self._create_ui()
        # 검수 탭에서 최신 파일 자동 로드
        self.root.after(100, self._auto_load_latest)

    def _load_settings(self):
        """설정 파일 로드"""
        settings_file = Path(__file__).parent / "simulator_settings.json"
        if settings_file.exists():
            try:
                with open(settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    self.visible_columns = settings.get("visible_columns", self.visible_columns)
                    self.column_order = settings.get("column_order", self.column_order)
            except:
                pass

    def _save_settings(self):
        """설정 파일 저장"""
        settings_file = Path(__file__).parent / "simulator_settings.json"
        settings = {
            "visible_columns": self.visible_columns,
            "column_order": self.column_order
        }
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

    def _create_ui(self):
        """탭 기반 UI 생성"""
        # 탭 컨테이너
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 각 탭 프레임 생성
        self.collection_tab = ttk.Frame(self.notebook)
        self.review_tab = ttk.Frame(self.notebook)
        self.settings_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.collection_tab, text="  수집  ")
        self.notebook.add(self.review_tab, text="  검수  ")
        self.notebook.add(self.settings_tab, text="  설정  ")

        # 각 탭 UI 생성
        self._create_collection_tab()
        self._create_review_tab()
        self._create_settings_tab()

        # 기본 탭: 검수
        self.notebook.select(self.review_tab)

    def _create_collection_tab(self):
        """수집 탭 UI - 업로더 v1.5와 동일한 설정"""
        frame = self.collection_tab

        # 스크롤 가능한 프레임
        canvas = tk.Canvas(frame)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # === 0. API 연결 ===
        conn_frame = ttk.LabelFrame(scrollable, text="🔑 API 연결", padding=5)
        conn_frame.pack(fill=tk.X, padx=10, pady=5)

        conn_row = ttk.Frame(conn_frame)
        conn_row.pack(fill=tk.X, pady=2)

        ttk.Button(conn_row, text="🌐 크롬", command=self._open_debug_chrome, width=8).pack(side=tk.LEFT)
        ttk.Button(conn_row, text="🔑 토큰", command=self._extract_tokens, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(conn_row, text="🔗 연결", command=self._connect_api, width=8).pack(side=tk.LEFT, padx=2)

        self.api_status = ttk.Label(conn_row, text="연결 안 됨", foreground="gray")
        self.api_status.pack(side=tk.LEFT, padx=10)

        ttk.Label(conn_row, text="포트:").pack(side=tk.RIGHT)
        self.port_var = tk.StringVar(value="9222")
        ttk.Entry(conn_row, textvariable=self.port_var, width=6).pack(side=tk.RIGHT, padx=2)

        # === 1. 그룹 선택 (시뮬레이터와 동일) ===
        group_frame = ttk.LabelFrame(scrollable, text="📁 마켓그룹 설정", padding=5)
        group_frame.pack(fill=tk.X, padx=10, pady=5)

        row1 = ttk.Frame(group_frame)
        row1.pack(fill=tk.X, pady=2)

        ttk.Label(row1, text="그룹당 최대 상품:").pack(side=tk.LEFT)
        self.max_products_var = tk.StringVar(value="100")
        ttk.Entry(row1, textvariable=self.max_products_var, width=8).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row1, text="작업 그룹:").pack(side=tk.LEFT)
        self.work_groups_var = tk.StringVar(value="1-5")
        ttk.Entry(row1, textvariable=self.work_groups_var, width=15).pack(side=tk.LEFT, padx=2)
        ttk.Label(row1, text="(예: 1-5 또는 1,3,5)", foreground="gray").pack(side=tk.LEFT, padx=5)
        ttk.Button(row1, text="📥 그룹목록", command=self._load_market_groups, width=10).pack(side=tk.RIGHT)

        row1b = ttk.Frame(group_frame)
        row1b.pack(fill=tk.X, pady=2)
        ttk.Label(row1b, text="마켓 그룹 목록 (쉼표 구분, 숫자 맵핑용):").pack(anchor=tk.W)

        self.group_text = scrolledtext.ScrolledText(group_frame, height=2, width=80, font=('Consolas', 9))
        self.group_text.pack(fill=tk.X, expand=True, pady=2)

        ttk.Label(group_frame, text="예: 01_푸로테카,02_스트롬브린 → 작업그룹에서 1, 1-3 등으로 사용",
                  foreground="gray").pack(anchor=tk.W)

        # === 2. 수집 조건 ===
        condition_frame = ttk.LabelFrame(scrollable, text="📋 수집 조건", padding=5)
        condition_frame.pack(fill=tk.X, padx=10, pady=5)

        row2 = ttk.Frame(condition_frame)
        row2.pack(fill=tk.X, pady=2)

        ttk.Label(row2, text="수집조건:").pack(side=tk.LEFT)
        self.upload_condition_var = tk.StringVar(value="미업로드(수집완료+수정중+검토완료)")
        ttk.Combobox(row2, textvariable=self.upload_condition_var, width=35,
                     values=list(UPLOAD_CONDITIONS.keys())).pack(side=tk.LEFT, padx=5)

        ttk.Label(row2, text="수집수:").pack(side=tk.LEFT, padx=(10, 0))
        self.collect_count_var = tk.StringVar(value="9999")
        ttk.Entry(row2, textvariable=self.collect_count_var, width=6).pack(side=tk.LEFT, padx=2)

        # === 3. 옵션 설정 ===
        option_frame = ttk.LabelFrame(scrollable, text="⚙️ 옵션 설정", padding=5)
        option_frame.pack(fill=tk.X, padx=10, pady=5)

        row3 = ttk.Frame(option_frame)
        row3.pack(fill=tk.X, pady=2)

        ttk.Label(row3, text="옵션수:").pack(side=tk.LEFT)
        self.option_count_var = tk.StringVar(value="10")
        ttk.Entry(row3, textvariable=self.option_count_var, width=5).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row3, text="옵션정렬:").pack(side=tk.LEFT)
        self.option_sort_var = tk.StringVar(value="가격낮은순")
        ttk.Combobox(row3, textvariable=self.option_sort_var, width=10,
                     values=list(OPTION_SORT_OPTIONS.keys())).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row3, text="상품명:").pack(side=tk.LEFT)
        self.title_option_var = tk.StringVar(value="앞3개단어제외 셔플")
        ttk.Combobox(row3, textvariable=self.title_option_var, width=18,
                     values=list(TITLE_OPTIONS.keys())).pack(side=tk.LEFT, padx=2)

        row4 = ttk.Frame(option_frame)
        row4.pack(fill=tk.X, pady=2)

        ttk.Label(row4, text="최저가격:").pack(side=tk.LEFT)
        self.min_price_var = tk.StringVar(value="30000")
        ttk.Entry(row4, textvariable=self.min_price_var, width=8).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row4, text="최대가격:").pack(side=tk.LEFT)
        self.max_price_var = tk.StringVar(value="100000000")
        ttk.Entry(row4, textvariable=self.max_price_var, width=10).pack(side=tk.LEFT, padx=2)

        # === 4. 미끼 키워드 설정 ===
        keyword_frame = ttk.LabelFrame(scrollable, text="🚫 미끼 키워드 (학습/수정 가능)", padding=5)
        keyword_frame.pack(fill=tk.X, padx=10, pady=5)

        keyword_row1 = ttk.Frame(keyword_frame)
        keyword_row1.pack(fill=tk.X, pady=2)

        ttk.Label(keyword_row1, text="제외 키워드 (쉼표 구분):").pack(side=tk.LEFT)
        ttk.Button(keyword_row1, text="기본값", command=self._reset_keywords, width=6).pack(side=tk.RIGHT)
        ttk.Button(keyword_row1, text="💾 저장", command=self._save_keywords, width=6).pack(side=tk.RIGHT, padx=2)

        self.keyword_text = scrolledtext.ScrolledText(keyword_frame, height=3, width=80, font=('Consolas', 9))
        self.keyword_text.pack(fill=tk.X, expand=True)
        # 기본 미끼 키워드 로드
        bait_keywords = load_bait_keywords() if BULSAJA_API_AVAILABLE else []
        self.keyword_text.insert("1.0", ','.join(bait_keywords))

        # === 5. 카테고리별 검수 설정 ===
        category_frame = ttk.LabelFrame(scrollable, text="🛡️ 카테고리별 검수 수준", padding=5)
        category_frame.pack(fill=tk.X, padx=10, pady=5)

        cat_row1 = ttk.Frame(category_frame)
        cat_row1.pack(fill=tk.X, pady=2)

        ttk.Label(cat_row1, text="검수 수준:").pack(side=tk.LEFT)

        self.check_level_var = tk.StringVar(value="normal")
        ttk.Radiobutton(cat_row1, text="보통 (프로그램)", variable=self.check_level_var, value="normal").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(cat_row1, text="엄격 (AI확인)", variable=self.check_level_var, value="strict").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(cat_row1, text="제외", variable=self.check_level_var, value="skip").pack(side=tk.LEFT, padx=5)

        ttk.Button(cat_row1, text="⚙️ 카테고리 설정", command=self._open_category_settings, width=14).pack(side=tk.RIGHT)

        cat_row2 = ttk.Frame(category_frame)
        cat_row2.pack(fill=tk.X, pady=2)

        ttk.Label(cat_row2, text="위험 카테고리 (자동 엄격):").pack(side=tk.LEFT)
        self.risk_categories_var = tk.StringVar(value="패션의류,패션잡화,유아동,의료기기,화장품,시계,가방")
        ttk.Entry(cat_row2, textvariable=self.risk_categories_var, width=60).pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)

        ttk.Label(category_frame, text="※ 엄격: 위험 키워드 발견 시 Gemini AI로 재확인 | 보통: 안전 컨텍스트로 자동 판단",
                  foreground="gray").pack(anchor=tk.W)

        # === 6. 저장 설정 ===
        save_frame = ttk.LabelFrame(scrollable, text="💾 저장 설정", padding=5)
        save_frame.pack(fill=tk.X, padx=10, pady=5)

        save_row = ttk.Frame(save_frame)
        save_row.pack(fill=tk.X, pady=2)

        ttk.Label(save_row, text="저장 경로:").pack(side=tk.LEFT)
        self.save_path_var = tk.StringVar(value=f"simulation_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
        ttk.Entry(save_row, textvariable=self.save_path_var, width=50).pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        ttk.Button(save_row, text="찾아보기", command=self._browse_save_path, width=8).pack(side=tk.RIGHT)

        # === 7. 마진 설정 ===
        margin_frame = ttk.LabelFrame(scrollable, text="💰 마진 설정", padding=5)
        margin_frame.pack(fill=tk.X, padx=10, pady=5)

        row5 = ttk.Frame(margin_frame)
        row5.pack(fill=tk.X, pady=2)

        ttk.Label(row5, text="환율(위안):").pack(side=tk.LEFT)
        self.exchange_rate_var = tk.StringVar(value="215")
        ttk.Entry(row5, textvariable=self.exchange_rate_var, width=6).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row5, text="카드수수료(%):").pack(side=tk.LEFT)
        self.card_fee_var = tk.StringVar(value="3.3")
        ttk.Entry(row5, textvariable=self.card_fee_var, width=5).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row5, text="마진(min,max):").pack(side=tk.LEFT)
        self.margin_rate_var = tk.StringVar(value="25,30")
        ttk.Entry(row5, textvariable=self.margin_rate_var, width=8).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row5, text="더하기마진:").pack(side=tk.LEFT)
        self.margin_fixed_var = tk.StringVar(value="15000")
        ttk.Entry(row5, textvariable=self.margin_fixed_var, width=7).pack(side=tk.LEFT, padx=2)

        row6 = ttk.Frame(margin_frame)
        row6.pack(fill=tk.X, pady=2)

        ttk.Label(row6, text="할인율(min,max):").pack(side=tk.LEFT)
        self.discount_rate_var = tk.StringVar(value="20,30")
        ttk.Entry(row6, textvariable=self.discount_rate_var, width=8).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row6, text="가격단위:").pack(side=tk.LEFT)
        self.round_unit_var = tk.StringVar(value="100")
        ttk.Entry(row6, textvariable=self.round_unit_var, width=5).pack(side=tk.LEFT, padx=2)

        # === 6. 버튼 ===
        btn_frame = ttk.Frame(scrollable)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="수집 시작", command=self._start_collection).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="수집 중지", command=self._stop_collection).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="엑셀로 저장", command=self._save_collection_to_excel).pack(side=tk.LEFT, padx=20)
        ttk.Button(btn_frame, text="검수 탭으로 →", command=lambda: self.notebook.select(self.review_tab)).pack(side=tk.RIGHT, padx=5)

        # === 7. 진행 상황 ===
        progress_frame = ttk.LabelFrame(scrollable, text="📊 진행 상황", padding=5)
        progress_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.collection_status = tk.StringVar(value="대기 중...")
        ttk.Label(progress_frame, textvariable=self.collection_status, font=("맑은 고딕", 10)).pack(anchor=tk.W)

        self.collection_progress = ttk.Progressbar(progress_frame, length=400, mode='determinate')
        self.collection_progress.pack(fill=tk.X, pady=5)

        self.collection_log = tk.Text(progress_frame, height=12, width=80, font=("Consolas", 9))
        self.collection_log.pack(fill=tk.BOTH, expand=True)

    def _create_review_tab(self):
        """검수 탭 UI - 기존 메인 화면"""
        frame = self.review_tab

        # 상단 툴바
        toolbar = ttk.Frame(frame, padding=5)
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="엑셀 열기", command=self._load_excel).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="컬럼 설정", command=self._open_column_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="썸네일 분석", command=self._analyze_thumbnails).pack(side=tk.LEFT, padx=5)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Label(toolbar, text="파일:").pack(side=tk.LEFT)
        self.file_label = ttk.Label(toolbar, text="(없음)", foreground="gray")
        self.file_label.pack(side=tk.LEFT, padx=5)

        ttk.Button(toolbar, text="불사자 업데이트", command=self._update_bulsaja).pack(side=tk.RIGHT, padx=5)
        ttk.Button(toolbar, text="저장", command=self._save_changes).pack(side=tk.RIGHT, padx=5)

        # 썸네일 변경 옵션
        self.update_thumbnail_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="썸네일도 변경", variable=self.update_thumbnail_var).pack(side=tk.RIGHT, padx=5)

        self.count_label = ttk.Label(toolbar, text="상품: 0개")
        self.count_label.pack(side=tk.RIGHT, padx=20)

        # 메인 영역 (스크롤)
        main_frame = ttk.Frame(frame)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.canvas = tk.Canvas(main_frame, bg="white")
        scrollbar_y = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        scrollbar_x = ttk.Scrollbar(main_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)

        self.scrollable_frame = ttk.Frame(self.canvas)
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

    def _create_settings_tab(self):
        """설정 탭 UI"""
        frame = self.settings_tab

        # 컬럼 설정
        col_frame = ttk.LabelFrame(frame, text="컬럼 설정", padding=10)
        col_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 왼쪽: 체크박스 목록
        left_frame = ttk.Frame(col_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        # 카테고리별 그룹
        self.settings_checkboxes = {}
        categories = {}
        for col_id, col_info in ALL_COLUMNS.items():
            cat = col_info["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append((col_id, col_info))

        row = 0
        for cat_name, cols in categories.items():
            cat_label = ttk.Label(left_frame, text=f"[{cat_name}]", font=("맑은 고딕", 9, "bold"))
            cat_label.grid(row=row, column=0, sticky=tk.W, pady=(10, 2))
            row += 1

            for col_id, col_info in cols:
                var = tk.BooleanVar(value=col_id in self.visible_columns)
                cb = ttk.Checkbutton(left_frame, text=col_info["name"], variable=var,
                                    command=self._on_settings_column_change)
                cb.grid(row=row, column=0, sticky=tk.W, padx=20)
                self.settings_checkboxes[col_id] = var
                row += 1

        # 오른쪽: 순서 조정
        right_frame = ttk.Frame(col_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        ttk.Label(right_frame, text="컬럼 순서 (드래그 또는 버튼)", font=("맑은 고딕", 9, "bold")).pack(anchor=tk.W)

        order_frame = ttk.Frame(right_frame)
        order_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.order_listbox = tk.Listbox(order_frame, height=15, selectmode=tk.SINGLE, font=("맑은 고딕", 9))
        self.order_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for col_id in self.column_order:
            if col_id in ALL_COLUMNS:
                self.order_listbox.insert(tk.END, f"{ALL_COLUMNS[col_id]['name']} ({col_id})")

        btn_frame = ttk.Frame(order_frame)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5)

        ttk.Button(btn_frame, text="▲ 위로", width=8, command=self._move_column_up).pack(pady=2)
        ttk.Button(btn_frame, text="▼ 아래로", width=8, command=self._move_column_down).pack(pady=2)
        ttk.Button(btn_frame, text="기본값", width=8, command=self._reset_column_settings).pack(pady=10)

        # 하단 버튼
        bottom_frame = ttk.Frame(frame)
        bottom_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(bottom_frame, text="설정 저장", command=self._apply_and_save_settings).pack(side=tk.RIGHT, padx=5)

    # ===== API 연결 함수들 =====
    def _open_debug_chrome(self):
        """크롬을 디버그 모드로 열기"""
        import subprocess
        port = self.port_var.get()

        # Windows 크롬 경로
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]

        chrome_path = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_path = path
                break

        if not chrome_path:
            messagebox.showerror("오류", "크롬을 찾을 수 없습니다")
            return

        try:
            cmd = f'"{chrome_path}" --remote-debugging-port={port} --user-data-dir="{os.path.expanduser("~")}\\chrome_debug"'
            subprocess.Popen(cmd, shell=True)
            self._log_collection(f"🌐 크롬 디버그 모드 실행 (포트: {port})")
            self._log_collection("   → 불사자 사이트에 로그인하세요")
        except Exception as e:
            messagebox.showerror("오류", f"크롬 실행 실패: {e}")

    def _extract_tokens(self):
        """크롬에서 토큰 추출"""
        if not BULSAJA_API_AVAILABLE:
            messagebox.showerror("오류", "bulsaja_common 모듈이 필요합니다")
            return

        self._log_collection("🔑 토큰 추출 중...")

        def extract():
            success, access_token, refresh_token, error = extract_tokens_from_browser()
            if success:
                self.access_token = access_token
                self.refresh_token = refresh_token
                self._log_collection("✅ 토큰 추출 성공")
                self.root.after(0, lambda: self.api_status.config(text="토큰 추출됨", foreground="orange"))
            else:
                self._log_collection(f"❌ 토큰 추출 실패: {error}")
                self.root.after(0, lambda: self.api_status.config(text="토큰 실패", foreground="red"))

        threading.Thread(target=extract, daemon=True).start()

    def _connect_api(self):
        """API 연결"""
        if not hasattr(self, 'access_token') or not self.access_token:
            messagebox.showwarning("경고", "먼저 토큰을 추출하세요")
            return

        self._log_collection("🔗 API 연결 중...")

        try:
            self.api_client = BulsajaAPIClient(self.access_token, self.refresh_token)
            # 연결 테스트
            success, msg, total = self.api_client.test_connection()
            if success:
                self.api_status.config(text=f"연결됨 (총 {total}개)", foreground="green")
                self._log_collection(f"✅ API 연결 성공 - {msg}")
            else:
                self.api_status.config(text="연결 실패", foreground="red")
                self._log_collection(f"❌ API 연결 실패: {msg}")
        except Exception as e:
            self.api_status.config(text="연결 실패", foreground="red")
            self._log_collection(f"❌ API 연결 실패: {e}")

    # ===== 수집 탭 함수들 =====
    def _load_market_groups(self):
        """마켓 그룹 목록 조회 (시뮬레이터와 동일)"""
        if not hasattr(self, 'api_client') or not self.api_client:
            messagebox.showwarning("경고", "먼저 API에 연결하세요")
            return

        self._log_collection("📥 마켓 그룹 목록 조회 중...")

        try:
            groups = self.api_client.get_market_groups()
            if groups:
                self.group_text.delete("1.0", tk.END)
                self.group_text.insert("1.0", ','.join(groups))
                self._log_collection(f"✅ {len(groups)}개 그룹 로드됨")
            else:
                self._log_collection("⚠️ 그룹 없음 또는 조회 실패")
        except Exception as e:
            self._log_collection(f"❌ 그룹 로드 실패: {e}")

    def _reset_keywords(self):
        """미끼 키워드 기본값으로 초기화"""
        self.keyword_text.delete("1.0", tk.END)
        default_keywords = DEFAULT_BAIT_KEYWORDS if BULSAJA_API_AVAILABLE else []
        self.keyword_text.insert("1.0", ','.join(default_keywords))
        self._log_collection("🔄 미끼 키워드 기본값으로 초기화")

    def _save_keywords(self):
        """미끼 키워드 저장"""
        text = self.keyword_text.get("1.0", tk.END).strip()
        keywords = [k.strip() for k in text.split(',') if k.strip()]
        if BULSAJA_API_AVAILABLE and save_bait_keywords(keywords):
            self._log_collection(f"✅ 미끼 키워드 저장됨 ({len(keywords)}개)")
        else:
            self._log_collection("❌ 미끼 키워드 저장 실패")

    def _open_category_settings(self):
        """카테고리별 검수 설정 다이얼로그"""
        dialog = tk.Toplevel(self.root)
        dialog.title("카테고리별 검수 설정")
        dialog.geometry("600x500")
        dialog.transient(self.root)
        dialog.grab_set()

        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="카테고리별 검수 수준을 설정합니다. (strict=AI확인, normal=프로그램, skip=제외)",
                  foreground="gray").pack(anchor=tk.W)

        # 현재 설정 로드
        current_settings = load_category_risk_settings() if BULSAJA_API_AVAILABLE else {}

        # 스크롤 가능한 리스트
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        canvas = tk.Canvas(list_frame)
        scrollbar_cat = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar_cat.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar_cat.pack(side="right", fill="y")

        # 카테고리 목록
        categories = [
            "패션의류", "패션잡화", "화장품/미용", "디지털/가전", "가구/인테리어",
            "출산/육아", "식품", "스포츠/레저", "생활/건강", "여가/생활편의",
            "면세점", "도서/음반/DVD"
        ]

        self.category_vars = {}
        for cat in categories:
            row = ttk.Frame(scrollable_frame)
            row.pack(fill=tk.X, pady=2)

            ttk.Label(row, text=cat, width=20).pack(side=tk.LEFT)

            var = tk.StringVar(value=current_settings.get(cat, "normal"))
            self.category_vars[cat] = var

            ttk.Radiobutton(row, text="보통", variable=var, value="normal").pack(side=tk.LEFT, padx=5)
            ttk.Radiobutton(row, text="엄격", variable=var, value="strict").pack(side=tk.LEFT, padx=5)
            ttk.Radiobutton(row, text="제외", variable=var, value="skip").pack(side=tk.LEFT, padx=5)

        # 버튼 프레임
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=10)

        def save_cat_settings():
            settings = {cat: var.get() for cat, var in self.category_vars.items()}
            if BULSAJA_API_AVAILABLE:
                save_category_risk_settings(settings)
            self._log_collection("✅ 카테고리 검수 설정 저장됨")
            dialog.destroy()

        ttk.Button(btn_frame, text="저장", command=save_cat_settings).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="취소", command=dialog.destroy).pack(side=tk.RIGHT, padx=5)

    def _browse_save_path(self):
        """저장 경로 선택"""
        filepath = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            initialfile=self.save_path_var.get()
        )
        if filepath:
            self.save_path_var.set(filepath)

    def _parse_group_mapping(self) -> Dict[str, str]:
        """그룹 매핑 텍스트 파싱 (시뮬레이터와 동일)"""
        import re
        mapping = {}
        text = self.group_text.get("1.0", tk.END).strip()
        if not text:
            return mapping

        groups = [g.strip() for g in text.split(',') if g.strip()]
        prefix_pattern = re.compile(r'^(\d+)[_\-]')

        has_prefix_pattern = any(prefix_pattern.match(g) for g in groups)

        if has_prefix_pattern:
            for group_name in groups:
                match = prefix_pattern.match(group_name)
                if match:
                    num_str = match.group(1)
                    mapping[num_str] = group_name
                    mapping[str(int(num_str))] = group_name
                    mapping[f"{int(num_str):02d}"] = group_name
        else:
            for idx, group_name in enumerate(groups, 1):
                mapping[str(idx)] = group_name
                mapping[f"{idx:02d}"] = group_name

        return mapping

    def _parse_work_range(self, range_str: str) -> List[str]:
        """작업 범위 파싱 (1-5 또는 1,3,5)"""
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

    def _get_work_group_names(self) -> List[str]:
        """작업 범위에서 실제 그룹명 목록 가져오기"""
        mapping = self._parse_group_mapping()
        range_nums = self._parse_work_range(self.work_groups_var.get())
        group_names = []
        for num in range_nums:
            if num in mapping:
                group_names.append(mapping[num])
            else:
                self._log_collection(f"⚠️ 그룹 번호 {num}에 해당하는 그룹명 없음")
        return group_names

    def _start_collection(self):
        """수집 시작 (시뮬레이터와 동일 - 여러 그룹 지원)"""
        if not hasattr(self, 'api_client') or not self.api_client:
            messagebox.showwarning("경고", "먼저 API에 연결하세요")
            return

        group_names = self._get_work_group_names()
        if not group_names:
            messagebox.showwarning("경고", "작업할 그룹이 없습니다.\n작업범위와 그룹목록을 확인하세요.")
            return

        max_products = int(self.max_products_var.get())

        self._log_collection("")
        self._log_collection("=" * 50)
        self._log_collection("📦 수집 시작")
        self._log_collection(f"   그룹: {', '.join(group_names)}")
        self._log_collection(f"   그룹당 최대 상품: {max_products}개")
        self._log_collection("=" * 50)

        self.collection_status.set(f"수집 중: {len(group_names)}개 그룹")
        self.is_collecting = True

        def collect():
            try:
                collected_data = []
                total_groups = len(group_names)

                for group_idx, group_name in enumerate(group_names):
                    if not self.is_collecting:
                        break

                    self._log_collection(f"\n[{group_idx+1}/{total_groups}] '{group_name}' 그룹 처리 중...")

                    # 상품 목록 조회
                    products, total_count = self.api_client.get_products_by_group(group_name, limit=max_products)
                    self._log_collection(f"   📦 {len(products)}개 상품 발견 (전체 {total_count}개)")

                    # 상세 정보 수집
                    for i, prod in enumerate(products[:max_products]):
                        if not self.is_collecting:
                            break

                        progress = ((group_idx * max_products) + i + 1) / (total_groups * max_products) * 100
                        self.root.after(0, lambda v=min(progress, 100): self.collection_progress.config(value=v))
                        self.root.after(0, lambda s=f"수집 중: {group_name} ({i+1}/{len(products)})": self.collection_status.set(s))

                        prod_id = prod.get("ID", "") or prod.get("id", "")
                        try:
                            detail = self.api_client.get_product_detail(prod_id)
                            detail['_group_name'] = group_name  # 그룹명 추가
                            collected_data.append(detail)
                            prod_name = prod.get('uploadCommonProductName', '') or prod.get('name', '')
                            self._log_collection(f"   [{i+1}/{len(products)}] {prod_name[:25]}...")
                        except Exception as e:
                            self._log_collection(f"   ❌ {prod_id}: {e}")

                self.collected_data = collected_data
                self._log_collection(f"\n✅ 수집 완료: 총 {len(collected_data)}개")
                self.root.after(0, lambda: self.collection_status.set(f"완료: {len(collected_data)}개"))
                self.root.after(0, lambda: self.collection_progress.config(value=100))

            except Exception as e:
                self._log_collection(f"❌ 수집 실패: {e}")
                self.root.after(0, lambda: self.collection_status.set("수집 실패"))

        threading.Thread(target=collect, daemon=True).start()

    def _stop_collection(self):
        """수집 중지"""
        self.is_collecting = False
        self._log_collection("⏹️ 수집 중지 요청")
        self.collection_status.set("중지됨")

    def _save_collection_to_excel(self):
        """수집 데이터를 엑셀로 저장 (시뮬레이터 형식)"""
        if not hasattr(self, 'collected_data') or not self.collected_data:
            messagebox.showwarning("경고", "먼저 수집을 실행하세요")
            return

        if not OPENPYXL_AVAILABLE:
            messagebox.showerror("오류", "openpyxl이 필요합니다: pip install openpyxl")
            return

        # 저장 경로 설정에서 가져오기
        filepath = self.save_path_var.get()
        if not filepath:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M')
            filepath = f"simulation_{timestamp}.xlsx"

        # 파일 선택 다이얼로그 (경로 확인/변경 가능)
        filepath = filedialog.asksaveasfilename(
            title="시뮬레이션 엑셀 저장",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile=filepath
        )

        if not filepath:
            return

        self._log_collection(f"💾 엑셀 저장 시작: {filepath}")
        self._log_collection(f"📊 {len(self.collected_data)}개 상품 분석 및 저장 중...")

        def save_task():
            try:
                # 키워드 로드
                banned_words, _ = load_banned_words()
                excluded_words = load_excluded_words()
                bait_keywords = load_bait_keywords()

                # 상품 분석 및 결과 수집
                results = []
                stats = {"total": 0, "safe": 0, "unsafe": 0, "bait_found": 0}

                # 검수 설정 가져오기
                check_level = self.check_level_var.get()
                risk_categories = [c.strip() for c in self.risk_categories_var.get().split(',') if c.strip()]

                for idx, product in enumerate(self.collected_data):
                    stats["total"] += 1

                    # 카테고리 확인하여 검수 레벨 결정
                    product_category = product.get('categoryPath', '') or product.get('category', '') or ''
                    product_check_level = check_level

                    # 위험 카테고리에 해당하면 엄격 검수
                    for risk_cat in risk_categories:
                        if risk_cat and risk_cat.lower() in product_category.lower():
                            product_check_level = 'strict'
                            break

                    result = self._analyze_single_product(product, bait_keywords, excluded_words, product_check_level)
                    result['group_name'] = product.get('_group_name', '')  # 수집 시 저장한 그룹명 사용
                    result['category'] = product_category[:30]  # 카테고리 기록
                    results.append(result)

                    if result['is_safe']:
                        stats["safe"] += 1
                    else:
                        stats["unsafe"] += 1
                    if result['bait_options'] > 0:
                        stats["bait_found"] += 1

                    if (idx + 1) % 10 == 0:
                        self._log_collection(f"  분석 중... {idx+1}/{len(self.collected_data)}")

                # 엑셀 저장
                self._save_results_to_excel(filepath, results, stats)

                self._log_collection(f"✅ 저장 완료: {filepath}")
                self._log_collection(f"   총 {stats['total']}개 / 안전 {stats['safe']}개 / 위험 {stats['unsafe']}개")
                self.root.after(0, lambda: messagebox.showinfo("완료", f"엑셀 저장 완료!\n\n{filepath}"))

            except Exception as e:
                self._log_collection(f"❌ 저장 실패: {e}")
                self.root.after(0, lambda: messagebox.showerror("오류", f"저장 실패: {e}"))

        threading.Thread(target=save_task, daemon=True).start()

    def _analyze_single_product(self, product: Dict, bait_keywords: list, excluded_words: list, check_level: str = 'normal') -> Dict:
        """단일 상품 분석 (기존 시뮬레이터 로직)

        Args:
            product: 상품 정보
            bait_keywords: 미끼 키워드 목록
            excluded_words: 제외 단어 목록
            check_level: 검수 레벨 (strict/normal/skip)
        """
        product_id = product.get('ID', '') or product.get('id', '')
        product_name = product.get('uploadCommonProductName', '') or product.get('name', '')

        result = {
            'id': product_id,
            'name': product_name,
            'is_safe': True,
            'unsafe_reason': '',
            'unsafe_keywords': [],
            'safe_context': '',  # 안전 컨텍스트로 무시된 키워드
            'check_level': check_level,  # 사용된 검수 레벨
            'ai_judgment': '',  # AI 판단 결과 (strict 모드)
            'total_options': 0,
            'valid_options': 0,
            'final_options': 0,
            'bait_options': 0,
            'bait_option_list': [],
            'main_option_name': '',
            'main_option_method': '',
            'final_option_list': [],
            'cn_option_list': [],
            'thumbnail_url': '',
            'main_option_image': '',
            'min_price_cny': 0,
            'max_price_cny': 0,
        }

        try:
            # 1. 상품명 안전 검사 (검수 레벨에 따라 AI 사용 여부 결정)
            safety = check_product_safety(product_name, excluded_words, check_level=check_level)
            result['is_safe'] = safety['is_safe']
            result['unsafe_keywords'] = safety.get('all_found', [])

            # 안전 컨텍스트로 무시된 키워드 기록
            if safety.get('safe_context_found'):
                result['safe_context'] = ', '.join(safety['safe_context_found'][:3])

            # AI 판단 결과 기록 (strict 모드)
            if safety.get('ai_judgment'):
                result['ai_judgment'] = ', '.join(safety['ai_judgment'][:3])

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
                result['unsafe_reason'] = ' / '.join(categories)

            # 2. 썸네일 URL
            thumbnails = product.get('uploadThumbnails', [])
            if thumbnails:
                result['thumbnail_url'] = thumbnails[0]

            # 3. SKU 정보
            upload_skus = product.get('uploadSkus', [])
            if not upload_skus:
                upload_skus = product.get('original_skus', [])

            result['total_options'] = len(upload_skus)

            if upload_skus:
                # 가격 범위
                prices = [sku.get('_origin_price', 0) for sku in upload_skus if sku.get('_origin_price', 0) > 0]
                if prices:
                    result['min_price_cny'] = min(prices)
                    result['max_price_cny'] = max(prices)

                # 미끼옵션 필터링
                valid_skus, bait_skus = filter_bait_options(upload_skus, bait_keywords)

                result['valid_options'] = len(valid_skus)
                result['bait_options'] = len(bait_skus)

                # 미끼 옵션 정보 수집
                for bait_sku in bait_skus:
                    option_text_ko = bait_sku.get('text_ko', '') or ''
                    bait_price = bait_sku.get('_origin_price', 0)
                    display_text = option_text_ko[:20] if option_text_ko else ''
                    price_part = f"({bait_price})" if bait_price else ""
                    result['bait_option_list'].append(f"{display_text}{price_part}")

                # 대표옵션 선택: 상품명 매칭 → 첫 번째 옵션 폴백
                if valid_skus:
                    main_sku_idx, main_method = select_main_option(product_name, valid_skus)
                    main_sku = valid_skus[main_sku_idx]
                    result['main_option_name'] = main_sku.get('text_ko', '') or main_sku.get('text', '')
                    result['main_option_method'] = main_method

                    # 대표 옵션 이미지 URL
                    main_option_img = main_sku.get('urlRef', '') or main_sku.get('image', '')
                    if main_option_img:
                        result['main_option_image'] = main_option_img

                    # 옵션 개수 제한 (5개)
                    option_count = self.option_count_var.get() if hasattr(self, 'option_count_var') else 5
                    main_sku_price = main_sku.get('_origin_price', 0)

                    if option_count > 0:
                        eligible_skus = [
                            sku for sku in valid_skus
                            if sku.get('_origin_price', 0) >= main_sku_price
                        ]
                        eligible_skus.sort(key=lambda x: x.get('_origin_price', 0))
                        final_skus = eligible_skus[:option_count]
                    else:
                        final_skus = valid_skus

                    result['final_options'] = len(final_skus)

                    # 최종 옵션 목록
                    for sku in final_skus:
                        opt_name = sku.get('text_ko', '') or sku.get('text', '')
                        opt_cn = sku.get('text', '') or ''
                        opt_price = sku.get('_origin_price', 0)
                        result['final_option_list'].append(f"{opt_name[:20]}({opt_price:.1f})")
                        result['cn_option_list'].append(opt_cn[:20])

        except Exception as e:
            result['unsafe_reason'] = f"분석오류: {str(e)[:50]}"

        return result

    def _format_options_abc(self, options: list, max_count: int = 10) -> str:
        """옵션 목록을 A, B, C 형태로 포맷팅"""
        import re
        if not options:
            return ''

        result = []
        labels = 'ABCDEFGHIJ'
        for i, opt in enumerate(options[:max_count]):
            label = labels[i] if i < len(labels) else str(i + 1)
            opt_name = str(opt) if opt else ''
            opt_name = re.sub(r'^[A-Za-z]\.\s*', '', opt_name).strip()
            opt_name = opt_name[:30]
            result.append(f"{label}. {opt_name}")

        return '\n'.join(result)

    def _save_results_to_excel(self, filepath: str, results: list, stats: dict):
        """분석 결과를 엑셀로 저장 (기존 시뮬레이터 형식)"""
        from datetime import datetime
        wb = Workbook()
        ws = wb.active
        ws.title = "분석결과"

        # 스타일 정의
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        border = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin')
        )
        unsafe_fill = PatternFill(start_color="FFCDD2", end_color="FFCDD2", fill_type="solid")
        safe_fill = PatternFill(start_color="C8E6C9", end_color="C8E6C9", fill_type="solid")
        select_fill = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")
        wrap_align = Alignment(vertical="top", wrap_text=True)
        center_align = Alignment(horizontal="center", vertical="center")

        # 헤더
        headers = [
            "썸네일\n이미지", "옵션\n이미지", "상품명", "안전여부", "위험사유",
            "전체옵션", "유효옵션", "최종옵션", "미끼옵션", "미끼옵션목록",
            "대표옵션", "선택방식", "선택", "옵션명", "중국어\n옵션명", "그룹명"
        ]

        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = border

        # 데이터 입력
        for row_idx, result in enumerate(results, 2):
            col = 1

            # 1. 썸네일 이미지
            thumb_url = result.get('thumbnail_url', '')
            ws.cell(row=row_idx, column=col, value=f'=IMAGE("{thumb_url}")' if thumb_url else '')
            col += 1

            # 2. 옵션 이미지
            option_img = result.get('main_option_image', '')
            ws.cell(row=row_idx, column=col, value=f'=IMAGE("{option_img}")' if option_img else '')
            col += 1

            # 3. 상품명
            ws.cell(row=row_idx, column=col, value=result.get('name', '')[:50])
            col += 1

            # 4. 안전여부
            is_safe = result.get('is_safe', True)
            status_cell = ws.cell(row=row_idx, column=col, value='O' if is_safe else 'X')
            status_cell.alignment = center_align
            status_cell.fill = safe_fill if is_safe else unsafe_fill
            col += 1

            # 5. 위험사유
            ws.cell(row=row_idx, column=col, value=result.get('unsafe_reason', ''))
            col += 1

            # 6-9. 옵션 수량
            ws.cell(row=row_idx, column=col, value=result.get('total_options', 0))
            col += 1
            ws.cell(row=row_idx, column=col, value=result.get('valid_options', 0))
            col += 1
            ws.cell(row=row_idx, column=col, value=result.get('final_options', 0))
            col += 1
            ws.cell(row=row_idx, column=col, value=result.get('bait_options', 0))
            col += 1

            # 10. 미끼옵션목록
            bait_cell = ws.cell(row=row_idx, column=col,
                               value=self._format_options_abc(result.get('bait_option_list', [])[:5]))
            bait_cell.alignment = wrap_align
            col += 1

            # 11. 대표옵션
            ws.cell(row=row_idx, column=col, value=result.get('main_option_name', ''))
            col += 1

            # 12. 선택방식
            ws.cell(row=row_idx, column=col, value=result.get('main_option_method', ''))
            col += 1

            # 13. 선택 (사용자 입력용, 기본값 A)
            select_cell = ws.cell(row=row_idx, column=col, value='A')
            select_cell.alignment = center_align
            select_cell.fill = select_fill
            col += 1

            # 14. 옵션명
            ws.cell(row=row_idx, column=col,
                   value=self._format_options_abc(result.get('final_option_list', []))).alignment = wrap_align
            col += 1

            # 15. 중국어 옵션명
            ws.cell(row=row_idx, column=col,
                   value=self._format_options_abc(result.get('cn_option_list', []))).alignment = wrap_align
            col += 1

            # 16. 그룹명
            ws.cell(row=row_idx, column=col, value=result.get('group_name', ''))
            col += 1

            # 테두리 적용
            for c in range(1, col):
                ws.cell(row=row_idx, column=c).border = border

        # 열 너비 조정
        column_widths = [15, 15, 40, 8, 20, 8, 8, 8, 8, 30, 25, 12, 6, 35, 35, 12]
        for i, width in enumerate(column_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = width

        # 행 높이 조정
        for row_idx in range(2, len(results) + 2):
            ws.row_dimensions[row_idx].height = 80
        ws.row_dimensions[1].height = 40

        # 필터 설정
        ws.auto_filter.ref = ws.dimensions

        # === 상세정보 시트 ===
        ws_detail = wb.create_sheet("상세정보")
        detail_headers = [
            "그룹", "불사자ID", "상품명", "안전여부", "위험사유",
            "전체옵션", "유효옵션", "최종옵션", "미끼옵션", "미끼옵션목록",
            "선택", "대표옵션", "최저가(CNY)", "최고가(CNY)", "최종옵션목록", "메인썸네일URL", "옵션이미지URL"
        ]
        for col, header in enumerate(detail_headers, 1):
            cell = ws_detail.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = border

        for row_idx, result in enumerate(results, 2):
            ws_detail.cell(row=row_idx, column=1, value=result.get('group_name', '')).border = border
            ws_detail.cell(row=row_idx, column=2, value=result.get('id', '')).border = border
            ws_detail.cell(row=row_idx, column=3, value=result.get('name', '')[:50]).border = border

            safe_cell = ws_detail.cell(row=row_idx, column=4, value='안전' if result.get('is_safe') else '위험')
            safe_cell.border = border
            safe_cell.alignment = center_align
            safe_cell.fill = safe_fill if result.get('is_safe') else unsafe_fill

            ws_detail.cell(row=row_idx, column=5, value=result.get('unsafe_reason', '')).border = border
            ws_detail.cell(row=row_idx, column=6, value=result.get('total_options', 0)).border = border
            ws_detail.cell(row=row_idx, column=7, value=result.get('valid_options', 0)).border = border
            ws_detail.cell(row=row_idx, column=8, value=result.get('final_options', 0)).border = border
            ws_detail.cell(row=row_idx, column=9, value=result.get('bait_options', 0)).border = border

            bait_cell = ws_detail.cell(row=row_idx, column=10,
                                       value=self._format_options_abc(result.get('bait_option_list', [])[:5]))
            bait_cell.alignment = wrap_align
            bait_cell.border = border

            select_cell2 = ws_detail.cell(row=row_idx, column=11, value='A')
            select_cell2.alignment = center_align
            select_cell2.fill = select_fill
            select_cell2.border = border

            ws_detail.cell(row=row_idx, column=12, value=result.get('main_option_name', '')).border = border
            ws_detail.cell(row=row_idx, column=13, value=result.get('min_price_cny', 0)).border = border
            ws_detail.cell(row=row_idx, column=14, value=result.get('max_price_cny', 0)).border = border

            final_opt_cell = ws_detail.cell(row=row_idx, column=15,
                                            value=self._format_options_abc(result.get('final_option_list', [])))
            final_opt_cell.alignment = wrap_align
            final_opt_cell.border = border

            ws_detail.cell(row=row_idx, column=16, value=result.get('thumbnail_url', '')).border = border
            ws_detail.cell(row=row_idx, column=17, value=result.get('main_option_image', '')).border = border

        # 상세시트 열 너비
        detail_widths = [12, 12, 40, 8, 25, 8, 8, 8, 8, 35, 6, 25, 10, 10, 40, 45, 45]
        for i, width in enumerate(detail_widths, 1):
            ws_detail.column_dimensions[get_column_letter(i)].width = width

        # === 통계 시트 ===
        ws_stats = wb.create_sheet("통계")
        stats_data = [
            ["항목", "값"],
            ["전체 상품", stats['total']],
            ["안전 상품", stats['safe']],
            ["위험 상품", stats['unsafe']],
            ["미끼옵션 발견 상품", stats['bait_found']],
            ["분석 일시", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ]
        for row_idx, row_data in enumerate(stats_data, 1):
            for col_idx, value in enumerate(row_data, 1):
                ws_stats.cell(row=row_idx, column=col_idx, value=value)

        wb.save(filepath)

    def _log_collection(self, msg):
        """수집 로그 출력"""
        def update():
            self.collection_log.insert(tk.END, msg + "\n")
            self.collection_log.see(tk.END)
        self.root.after(0, update)

    # ===== 설정 탭 함수들 =====
    def _on_settings_column_change(self):
        """설정 탭에서 컬럼 체크박스 변경 시"""
        pass  # 실시간 미리보기는 추후 구현

    def _move_column_up(self):
        """컬럼 위로 이동"""
        idx = self.order_listbox.curselection()
        if idx and idx[0] > 0:
            i = idx[0]
            item = self.order_listbox.get(i)
            self.order_listbox.delete(i)
            self.order_listbox.insert(i - 1, item)
            self.order_listbox.selection_set(i - 1)
            self.column_order[i], self.column_order[i-1] = self.column_order[i-1], self.column_order[i]

    def _move_column_down(self):
        """컬럼 아래로 이동"""
        idx = self.order_listbox.curselection()
        if idx and idx[0] < self.order_listbox.size() - 1:
            i = idx[0]
            item = self.order_listbox.get(i)
            self.order_listbox.delete(i)
            self.order_listbox.insert(i + 1, item)
            self.order_listbox.selection_set(i + 1)
            self.column_order[i], self.column_order[i+1] = self.column_order[i+1], self.column_order[i]

    def _reset_column_settings(self):
        """컬럼 설정 기본값으로 리셋"""
        # 체크박스 리셋
        for col_id, col_info in ALL_COLUMNS.items():
            if col_id in self.settings_checkboxes:
                self.settings_checkboxes[col_id].set(col_info["default"])

        # 순서 리셋
        self.column_order = list(DEFAULT_COLUMN_ORDER)
        self.order_listbox.delete(0, tk.END)
        for col_id in self.column_order:
            if col_id in ALL_COLUMNS:
                self.order_listbox.insert(tk.END, f"{ALL_COLUMNS[col_id]['name']} ({col_id})")

    def _apply_and_save_settings(self):
        """설정 적용 및 저장"""
        # 선택된 컬럼 수집
        self.visible_columns = [col_id for col_id, var in self.settings_checkboxes.items() if var.get()]
        self._save_settings()
        self._render_data()
        messagebox.showinfo("알림", "설정이 저장되었습니다.")

    def _open_column_settings(self):
        """컬럼 설정 다이얼로그"""
        dialog = ColumnSettingsDialog(self.root, self.visible_columns, self.column_order)
        self.root.wait_window(dialog.dialog)

        if dialog.result:
            self.visible_columns = dialog.result["columns"]
            self.column_order = dialog.result["order"]
            self._save_settings()
            self._render_data()

    def _auto_load_latest(self):
        """최신 시뮬레이션 파일 자동 로드"""
        base_dir = Path(__file__).parent
        simulation_files = list(base_dir.glob("simulation_*.xlsx"))

        if simulation_files:
            simulation_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            self._load_excel_file(str(simulation_files[0]))

    def _load_excel(self):
        """파일 선택"""
        filepath = filedialog.askopenfilename(
            title="시뮬레이션 엑셀 선택",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            initialdir=str(Path(__file__).parent)
        )
        if filepath:
            self._load_excel_file(filepath)

    def _load_excel_file(self, filepath):
        """엑셀 파일 로드"""
        if not PANDAS_AVAILABLE:
            messagebox.showerror("오류", "pandas가 필요합니다: pip install pandas openpyxl")
            return

        try:
            df = pd.read_excel(filepath, engine='openpyxl')
        except Exception as e:
            try:
                df = pd.read_excel(filepath)
            except Exception as e2:
                messagebox.showerror("오류", f"엑셀 로드 실패:\n{e}\n{e2}")
                return

        self._parse_excel_data(df)
        self.file_label.config(text=Path(filepath).name, foreground="black")
        self.count_label.config(text=f"상품: {len(self.data)}개")
        self._render_data()

    def _parse_excel_data(self, df):
        """엑셀 데이터 파싱 - 확장된 정보 수집"""
        self.data = []

        for idx, row in df.iterrows():
            # 불사자ID 추출 (여러 컬럼명 시도)
            product_id = (self._safe_str(row.get("불사자ID", "")) or
                         self._safe_str(row.get("상품ID", "")) or
                         self._safe_str(row.get("id", ""))).strip()

            item = {
                "row_idx": idx,
                # 기본 정보
                "product_name": self._safe_str(row.get("상품명", ""))[:30],
                "product_id": product_id,
                "is_safe": row.get("안전여부") == "O" if pd.notna(row.get("안전여부")) else True,
                "unsafe_reason": self._safe_str(row.get("위험사유", "")),
                "group_name": self._safe_str(row.get("그룹명", "")),

                # 썸네일
                "thumbnail_formula": self._safe_str(row.get("썸네일\n이미지", "")),
                "thumbnail_url": "",

                # 썸네일 분석 결과 (나중에 채움)
                "thumb_score": 0,
                "thumb_nukki": False,
                "thumb_text": False,
                "thumb_action": "-",

                # 옵션 정보
                "option_image_formula": self._safe_str(row.get("옵션\n이미지", "")),
                "total_options": int(row.get("전체옵션", 0)) if pd.notna(row.get("전체옵션")) else 0,
                "final_options": int(row.get("최종옵션", 0)) if pd.notna(row.get("최종옵션")) else 0,
                "bait_options": int(row.get("미끼옵션", 0)) if pd.notna(row.get("미끼옵션")) else 0,
                "main_option": self._safe_str(row.get("대표옵션", "")),
                "selected": self._safe_str(row.get("선택", "A")),
                "option_names": self._safe_str(row.get("옵션명", "")),
                "cn_option_names": self._safe_str(row.get("중국어\n옵션명", "")),

                # 가격 정보
                "price_cny": self._safe_float(row.get("위안가", 0)),
                "price_krw": self._safe_float(row.get("원화가", 0)),
                "sale_price": self._safe_float(row.get("판매가", 0)),
            }

            # URL 추출
            item["thumbnail_url"] = self._extract_image_url(item["thumbnail_formula"])
            item["option_image_url"] = self._extract_image_url(item["option_image_formula"])

            # 옵션 파싱
            item["options"] = self._parse_options(item["option_names"], item["cn_option_names"])

            # 옵션수 계산
            item["option_count"] = f"{item['final_options']}/{item['total_options']}"

            self.data.append(item)
            self.selected_options[idx] = item["selected"]

    def _safe_str(self, val) -> str:
        """안전한 문자열 변환"""
        if pd.isna(val):
            return ""
        return str(val)

    def _safe_float(self, val) -> float:
        """안전한 숫자 변환"""
        if pd.isna(val):
            return 0.0
        try:
            return float(val)
        except:
            return 0.0

    def _extract_image_url(self, formula) -> str:
        """=IMAGE("url") 에서 URL 추출"""
        if not formula:
            return ""
        if formula.startswith('=IMAGE("') and formula.endswith('")'):
            return formula[8:-2]
        return formula

    def _parse_options(self, option_names, cn_option_names) -> List[Dict]:
        """옵션명 파싱"""
        options = []
        if not option_names:
            return options

        ko_lines = option_names.strip().split('\n')
        cn_lines = cn_option_names.strip().split('\n') if cn_option_names else []

        for i, line in enumerate(ko_lines):
            line = line.strip()
            if not line:
                continue

            if '. ' in line:
                parts = line.split('. ', 1)
                label = parts[0].strip()
                name = parts[1].strip() if len(parts) > 1 else ""
            else:
                label = chr(ord('A') + i)
                name = line

            cn_name = ""
            if i < len(cn_lines):
                cn_line = cn_lines[i].strip()
                if '. ' in cn_line:
                    cn_name = cn_line.split('. ', 1)[1] if len(cn_line.split('. ', 1)) > 1 else cn_line
                else:
                    cn_name = cn_line

            options.append({
                "label": label,
                "name": name,
                "cn_name": cn_name
            })

        return options

    def _render_data(self):
        """데이터 렌더링"""
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        self.option_frames = {}

        if not self.data:
            ttk.Label(self.scrollable_frame, text="데이터 없음").pack(pady=50)
            return

        # 표시할 컬럼 (순서대로)
        visible_ordered = [col for col in self.column_order if col in self.visible_columns]
        # 순서에 없는 컬럼 추가
        for col in self.visible_columns:
            if col not in visible_ordered:
                visible_ordered.append(col)

        # 헤더
        self._create_header(visible_ordered)

        # 데이터 행
        for item in self.data:
            self._create_row(item, visible_ordered)

    def _create_header(self, columns):
        """헤더 생성"""
        header_frame = tk.Frame(self.scrollable_frame, bg="#4472C4")
        header_frame.pack(fill=tk.X, pady=(0, 2))

        for col_id in columns:
            col_info = ALL_COLUMNS.get(col_id, {"name": col_id, "width": 100})
            lbl = tk.Label(
                header_frame,
                text=col_info["name"],
                width=col_info["width"] // 8,
                bg="#4472C4",
                fg="white",
                font=("맑은 고딕", 9, "bold"),
                pady=5
            )
            lbl.pack(side=tk.LEFT, padx=1)

    def _create_row(self, item, columns):
        """데이터 행 생성"""
        row_idx = item["row_idx"]
        bg_color = "#C8E6C9" if item.get("is_safe", True) else "#FFCDD2"

        row_frame = tk.Frame(self.scrollable_frame, bg=bg_color, relief="solid", bd=1)
        row_frame.pack(fill=tk.X, pady=1)

        for col_id in columns:
            col_info = ALL_COLUMNS.get(col_id, {"width": 100})
            width = col_info["width"]

            cell_frame = tk.Frame(row_frame, width=width, height=90, bg=bg_color)
            cell_frame.pack(side=tk.LEFT, padx=1, pady=2)
            cell_frame.pack_propagate(False)

            # 컬럼별 렌더링
            if col_id == "thumbnail":
                self._render_thumbnail(cell_frame, item, bg_color)
            elif col_id == "options":
                self._render_options(cell_frame, item, row_idx, bg_color)
            elif col_id == "is_safe":
                self._render_safe(cell_frame, item, bg_color)
            elif col_id == "thumb_score":
                self._render_thumb_score(cell_frame, item, bg_color)
            elif col_id == "thumb_action":
                self._render_thumb_action(cell_frame, item, bg_color)
            elif col_id == "sale_price":
                self._render_price(cell_frame, item.get("sale_price", 0), bg_color)
            elif col_id == "price_cny":
                self._render_price(cell_frame, item.get("price_cny", 0), bg_color, "CNY")
            elif col_id == "price_krw":
                self._render_price(cell_frame, item.get("price_krw", 0), bg_color)
            else:
                # 일반 텍스트 컬럼
                value = str(item.get(col_id, ""))[:20]
                tk.Label(cell_frame, text=value, bg=bg_color,
                        font=("맑은 고딕", 9), wraplength=width-10).pack(expand=True)

    def _render_thumbnail(self, frame, item, bg_color):
        """썸네일 렌더링"""
        thumb_label = tk.Label(frame, text="[썸네일]", bg=bg_color, font=("맑은 고딕", 8))
        thumb_label.pack(expand=True)

        if PIL_AVAILABLE and item.get("thumbnail_url"):
            self._load_image(item["thumbnail_url"], thumb_label, 80, 80)

    def _render_options(self, frame, item, row_idx, bg_color):
        """옵션 선택 영역 렌더링"""
        options = item.get("options", [])
        max_display = 4

        for i, opt in enumerate(options[:max_display]):
            is_selected = (self.selected_options.get(row_idx, "A") == opt["label"])

            opt_frame = tk.Frame(
                frame,
                width=85, height=80,
                bg="#2196F3" if is_selected else "#E0E0E0",
                relief="solid",
                bd=2 if is_selected else 1,
                cursor="hand2"
            )
            opt_frame.pack(side=tk.LEFT, padx=2, pady=2)
            opt_frame.pack_propagate(False)

            opt_frame.bind("<Button-1>", lambda e, r=row_idx, o=opt["label"]: self._on_option_click(r, o))

            lbl_color = "white" if is_selected else "black"
            lbl_bg = "#2196F3" if is_selected else "#E0E0E0"

            label_widget = tk.Label(opt_frame, text=opt["label"], bg=lbl_bg, fg=lbl_color,
                                   font=("맑은 고딕", 11, "bold"))
            label_widget.pack(pady=2)
            label_widget.bind("<Button-1>", lambda e, r=row_idx, o=opt["label"]: self._on_option_click(r, o))

            name_short = opt["name"][:7] + ".." if len(opt["name"]) > 7 else opt["name"]
            name_widget = tk.Label(opt_frame, text=name_short, bg=lbl_bg, fg=lbl_color,
                                  font=("맑은 고딕", 8), wraplength=75)
            name_widget.pack(pady=1)
            name_widget.bind("<Button-1>", lambda e, r=row_idx, o=opt["label"]: self._on_option_click(r, o))

            self.option_frames[(row_idx, opt["label"])] = {
                "frame": opt_frame,
                "label": label_widget,
                "name": name_widget
            }

        if len(options) > max_display:
            more_btn = tk.Label(frame, text=f"+{len(options)-max_display}",
                               bg="#9E9E9E", fg="white", font=("맑은 고딕", 9),
                               width=4, cursor="hand2")
            more_btn.pack(side=tk.LEFT, padx=2, pady=30)

    def _render_safe(self, frame, item, bg_color):
        """안전 여부 렌더링"""
        safe_text = "O" if item.get("is_safe", True) else "X"
        safe_color = "#4CAF50" if item.get("is_safe", True) else "#F44336"
        tk.Label(frame, text=safe_text, bg=bg_color, fg=safe_color,
                font=("맑은 고딕", 16, "bold")).pack(expand=True)

    def _render_thumb_score(self, frame, item, bg_color):
        """썸네일 점수 렌더링"""
        score = item.get("thumb_score", 0)

        if score >= 80:
            color = "#4CAF50"  # 녹색
        elif score >= 50:
            color = "#FF9800"  # 주황
        elif score > 0:
            color = "#F44336"  # 빨강
        else:
            color = "gray"

        tk.Label(frame, text=f"{score}점", bg=bg_color, fg=color,
                font=("맑은 고딕", 12, "bold")).pack(expand=True)

    def _render_thumb_action(self, frame, item, bg_color):
        """필요 작업 렌더링"""
        action = item.get("thumb_action", "-")

        action_colors = {
            "none": ("#4CAF50", "OK"),
            "translate": ("#FF9800", "번역"),
            "nukki": ("#2196F3", "누끼"),
            "both": ("#9C27B0", "둘다"),
            "manual": ("#F44336", "수동"),
            "-": ("gray", "-")
        }

        color, text = action_colors.get(action, ("gray", action))
        tk.Label(frame, text=text, bg=bg_color, fg=color,
                font=("맑은 고딕", 10, "bold")).pack(expand=True)

    def _render_price(self, frame, price, bg_color, prefix=""):
        """가격 렌더링"""
        if price > 0:
            if prefix:
                text = f"{prefix} {price:,.0f}"
            else:
                text = f"{price:,.0f}원"
        else:
            text = "-"

        tk.Label(frame, text=text, bg=bg_color,
                font=("맑은 고딕", 9)).pack(expand=True)

    def _on_option_click(self, row_idx, option_label):
        """옵션 클릭"""
        old_selected = self.selected_options.get(row_idx, "A")

        if (row_idx, old_selected) in self.option_frames:
            old_widgets = self.option_frames[(row_idx, old_selected)]
            old_widgets["frame"].config(bg="#E0E0E0", bd=1)
            old_widgets["label"].config(bg="#E0E0E0", fg="black")
            old_widgets["name"].config(bg="#E0E0E0", fg="black")

        if (row_idx, option_label) in self.option_frames:
            new_widgets = self.option_frames[(row_idx, option_label)]
            new_widgets["frame"].config(bg="#2196F3", bd=2)
            new_widgets["label"].config(bg="#2196F3", fg="white")
            new_widgets["name"].config(bg="#2196F3", fg="white")

        self.selected_options[row_idx] = option_label

    def _analyze_thumbnails(self):
        """썸네일 분석 실행"""
        if not self.data:
            messagebox.showwarning("경고", "먼저 데이터를 로드하세요")
            return

        try:
            from thumbnail_analyzer import ThumbnailAnalyzer
        except ImportError:
            messagebox.showerror("오류", "thumbnail_analyzer.py가 필요합니다")
            return

        # 진행 다이얼로그
        progress = tk.Toplevel(self.root)
        progress.title("썸네일 분석 중...")
        progress.geometry("300x100")
        progress.transient(self.root)

        progress_var = tk.StringVar(value="분석 준비 중...")
        ttk.Label(progress, textvariable=progress_var).pack(pady=20)
        pb = ttk.Progressbar(progress, length=250, mode='determinate')
        pb.pack(pady=10)

        progress.update()

        analyzer = ThumbnailAnalyzer()
        total = len(self.data)

        for i, item in enumerate(self.data):
            progress_var.set(f"분석 중... {i+1}/{total}")
            pb['value'] = (i + 1) / total * 100
            progress.update()

            if item.get("thumbnail_url"):
                try:
                    result = analyzer.analyze_thumbnail(item["thumbnail_url"], i)
                    item["thumb_score"] = result.total_score
                    item["thumb_nukki"] = result.is_nukki
                    item["thumb_text"] = result.has_text
                    item["thumb_action"] = result.recommendation.replace("needs_", "").replace("best", "none")
                except Exception as e:
                    item["thumb_score"] = 0
                    item["thumb_action"] = "error"

        progress.destroy()
        self._render_data()
        messagebox.showinfo("완료", f"{total}개 썸네일 분석 완료")

    def _load_image(self, url, label, width, height):
        """이미지 로드"""
        try:
            if url in self.image_cache:
                photo = self.image_cache[url]
            else:
                response = requests.get(url, timeout=5)
                img = Image.open(BytesIO(response.content))
                img = img.resize((width, height), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.image_cache[url] = photo

            label.config(image=photo, text="")
            label.image = photo
        except:
            pass

    def _save_changes(self):
        """변경사항 저장"""
        changes = []
        for row_idx, selected in self.selected_options.items():
            if row_idx < len(self.data):
                original = self.data[row_idx].get("selected", "A")
                if selected != original:
                    changes.append(f"Row {row_idx}: {original} -> {selected}")

        if changes:
            msg = f"변경: {len(changes)}개\n" + "\n".join(changes[:15])
            if len(changes) > 15:
                msg += f"\n... +{len(changes)-15}개"
            messagebox.showinfo("변경사항", msg)
        else:
            messagebox.showinfo("변경사항", "변경 없음")

    def _update_bulsaja(self):
        """불사자 업데이트 - 선택된 옵션을 대표상품으로 변경"""
        if not BULSAJA_API_AVAILABLE:
            messagebox.showerror("오류", "bulsaja_common 모듈을 찾을 수 없습니다.\n\npip install websocket-client 후 재시도")
            return

        if not self.data:
            messagebox.showwarning("경고", "먼저 데이터를 로드하세요")
            return

        # 변경된 항목 수집
        changes = []
        for item in self.data:
            row_idx = item["row_idx"]
            product_id = item.get("product_id", "")
            original_selected = item.get("selected", "A")
            current_selected = self.selected_options.get(row_idx, "A")

            if not product_id:
                continue

            # 선택이 변경된 경우만 추가
            if current_selected != original_selected:
                changes.append({
                    "product_id": product_id,
                    "product_name": item.get("product_name", ""),
                    "old_option": original_selected,
                    "new_option": current_selected,
                    "options": item.get("options", [])
                })

        if not changes:
            messagebox.showinfo("알림", "변경된 옵션이 없습니다.\n\n옵션을 클릭하여 대표상품을 변경하세요.")
            return

        # 확인 메시지
        msg = f"총 {len(changes)}개 상품의 대표옵션을 변경합니다.\n\n"
        for c in changes[:5]:
            msg += f"• {c['product_name'][:15]}... : {c['old_option']} → {c['new_option']}\n"
        if len(changes) > 5:
            msg += f"... +{len(changes) - 5}개"

        if not messagebox.askyesno("불사자 업데이트 확인", msg):
            return

        # 진행 다이얼로그
        progress_dialog = tk.Toplevel(self.root)
        progress_dialog.title("불사자 업데이트 중...")
        progress_dialog.geometry("400x200")
        progress_dialog.transient(self.root)
        progress_dialog.grab_set()

        status_var = tk.StringVar(value="토큰 추출 중...")
        ttk.Label(progress_dialog, textvariable=status_var, font=("맑은 고딕", 10)).pack(pady=20)
        progress_bar = ttk.Progressbar(progress_dialog, length=350, mode='determinate')
        progress_bar.pack(pady=10)

        log_text = tk.Text(progress_dialog, height=5, width=50, font=("Consolas", 9))
        log_text.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        def log(msg):
            log_text.insert(tk.END, msg + "\n")
            log_text.see(tk.END)
            progress_dialog.update()

        def run_update():
            # 1. 토큰 추출
            log("🔑 크롬에서 토큰 추출 중...")
            success, access_token, refresh_token, error = extract_tokens_from_browser()

            if not success:
                log(f"❌ 토큰 추출 실패: {error}")
                status_var.set("토큰 추출 실패")
                messagebox.showerror("오류", f"토큰 추출 실패:\n{error}\n\n크롬에서 불사자 사이트에 로그인되어 있어야 합니다.")
                progress_dialog.destroy()
                return

            log(f"✅ 토큰 추출 성공")

            # 2. API 클라이언트 생성
            api_client = BulsajaAPIClient(access_token, refresh_token)

            # 3. 각 상품 업데이트
            success_count = 0
            fail_count = 0
            total = len(changes)

            for i, change in enumerate(changes):
                product_id = change["product_id"]
                new_option_label = change["new_option"]
                options = change["options"]

                status_var.set(f"업데이트 중... ({i+1}/{total})")
                progress_bar['value'] = (i + 1) / total * 100
                progress_dialog.update()

                # 옵션 라벨로 인덱스 찾기 (A=0, B=1, ...)
                try:
                    new_option_idx = ord(new_option_label.upper()) - ord('A')
                except:
                    log(f"⚠️ {product_id}: 잘못된 옵션 라벨 '{new_option_label}'")
                    fail_count += 1
                    continue

                # 4. 상품 상세 정보 조회
                try:
                    detail = api_client.get_product_detail(product_id)
                except Exception as e:
                    log(f"❌ {product_id}: 상세 조회 실패 - {e}")
                    fail_count += 1
                    continue

                upload_skus = detail.get("uploadSkus", [])
                if not upload_skus:
                    log(f"⚠️ {product_id}: SKU 없음")
                    fail_count += 1
                    continue

                # 5. 대표상품 변경 (main_product 플래그)
                # 기존 8. bulsaja_simulator.py의 apply_changes() 로직과 동일하게 구현
                # 모든 옵션 main_product = False → 선택된 인덱스만 True
                target_label = f"{new_option_label.upper()}."  # "A.", "B.", "C." 등

                # 모든 옵션의 main_product를 false로
                for sku in upload_skus:
                    sku['main_product'] = False

                # 선택된 옵션을 main_product = True로 설정
                found_target = False
                if new_option_idx < len(upload_skus):
                    upload_skus[new_option_idx]['main_product'] = True
                    found_target = True
                else:
                    # 인덱스가 범위를 벗어나면 옵션명(text)으로 검색
                    for sku in upload_skus:
                        sku_text = sku.get('text', '') or ''
                        if sku_text.strip().startswith(target_label):
                            sku['main_product'] = True
                            found_target = True
                            break

                if not found_target:
                    log(f"⚠️ {product_id}: 옵션 {new_option_label} 찾지 못함")
                    fail_count += 1
                    continue

                # 6. 썸네일 변경 (옵션 활성화 시)
                update_thumbnail = self.update_thumbnail_var.get()
                upload_thumbnails = detail.get("uploadThumbnails", [])
                upload_sku_props = detail.get("uploadSkuProps", {})

                if update_thumbnail and upload_sku_props:
                    # uploadSkuProps에서 선택된 옵션의 이미지 URL 찾기
                    main_option = upload_sku_props.get("mainOption", {})
                    values = main_option.get("values", [])

                    # 선택된 옵션의 이미지 URL 찾기
                    option_image_url = None
                    for val in values:
                        val_name = val.get("name", "")
                        if val_name.strip().startswith(target_label):
                            option_image_url = val.get("imageUrl", "")
                            break

                    # 인덱스로도 시도 (라벨 매칭 실패 시)
                    if not option_image_url and new_option_idx < len(values):
                        option_image_url = values[new_option_idx].get("imageUrl", "")

                    # 썸네일 배열 업데이트 (옵션 이미지를 첫 번째로)
                    if option_image_url and option_image_url not in upload_thumbnails[:1]:
                        # 기존 배열에서 해당 이미지 제거 후 맨 앞에 추가
                        if option_image_url in upload_thumbnails:
                            upload_thumbnails.remove(option_image_url)
                        upload_thumbnails.insert(0, option_image_url)
                        log(f"🖼️ {product_id}: 썸네일 변경됨")

                # 7. API로 업데이트
                update_data = {"uploadSkus": upload_skus}
                if update_thumbnail and upload_thumbnails:
                    update_data["uploadThumbnails"] = upload_thumbnails

                success_result, msg = api_client.update_product_fields(product_id, update_data)

                if success_result:
                    log(f"✅ {product_id}: 옵션 {new_option_label}로 변경")
                    success_count += 1
                else:
                    log(f"❌ {product_id}: {msg}")
                    fail_count += 1

            # 결과 요약
            status_var.set(f"완료! 성공: {success_count}, 실패: {fail_count}")
            log(f"\n{'='*40}")
            log(f"📊 업데이트 완료: 성공 {success_count}개, 실패 {fail_count}개")

            messagebox.showinfo("완료", f"불사자 업데이트 완료\n\n✅ 성공: {success_count}개\n❌ 실패: {fail_count}개")

            # 원본 선택값 업데이트 (변경 완료된 것으로 반영)
            for change in changes:
                for item in self.data:
                    if item.get("product_id") == change["product_id"]:
                        item["selected"] = change["new_option"]
                        break

        # 스레드로 실행
        threading.Thread(target=run_update, daemon=True).start()


def main():
    root = tk.Tk()
    app = SimulatorGUIv3(root)
    root.mainloop()


if __name__ == "__main__":
    main()
