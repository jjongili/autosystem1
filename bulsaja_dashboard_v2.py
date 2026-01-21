# -*- coding: utf-8 -*-
"""
불사자 업로더 대시보드 v2
- 대시보드 기반 멀티세션 관리
- 세션별 개별 로그 파일 저장
- 로그 보기 버튼으로 개별 로그 확인
- v1.5 전체 설정 포함
"""

import os
import sys
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

import tkinter as tk
from tkinter import ttk, messagebox

# 공통 모듈
sys.path.insert(0, str(Path(__file__).parent))
from bulsaja_common import BulsajaAPIClient, filter_bait_options, load_bait_keywords

CONFIG_FILE = "bulsaja_uploader_config.json"
LOG_DIR = Path(__file__).parent / "upload_logs"

# 마켓 타입 매핑
MARKET_TYPES = {
    '스마트스토어': 'SMARTSTORE',
    '11번가': 'ST11',
    'G마켓/옥션': 'ESM',
    '쿠팡': 'COUPANG'
}


class SessionLogger:
    """세션별 로그 관리"""

    def __init__(self, session_id: int, group_name: str):
        self.session_id = session_id
        self.group_name = group_name

        LOG_DIR.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_group = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in group_name)
        self.log_file = LOG_DIR / f"{timestamp}_S{session_id}_{safe_group}.log"

        with open(self.log_file, 'w', encoding='utf-8') as f:
            f.write(f"={'='*60}\n")
            f.write(f"세션 #{session_id} - {group_name}\n")
            f.write(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"={'='*60}\n\n")

        self.lines = []

    def log(self, msg: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] [{level}] {msg}"
        self.lines.append((line, level))

        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(line + "\n")

        return line

    def close(self, success: int, failed: int):
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"결과: 성공 {success}건, 실패 {failed}건\n")
            f.write(f"{'='*60}\n")


class LogViewerWindow:
    """개별 로그 뷰어 창"""

    def __init__(self, parent, session_id: int, group_name: str, logger: SessionLogger):
        self.window = tk.Toplevel(parent)
        self.window.title(f"로그 - 세션 #{session_id}: {group_name}")
        self.window.geometry("700x500")

        self.logger = logger
        self.auto_scroll = tk.BooleanVar(value=True)

        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(btn_frame, text="새로고침", command=self.refresh).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(btn_frame, text="자동 스크롤", variable=self.auto_scroll).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="파일 열기", command=self.open_file).pack(side=tk.LEFT, padx=5)
        ttk.Label(btn_frame, text=f"파일: {logger.log_file.name}", foreground="gray").pack(side=tk.RIGHT, padx=5)

        self.text = tk.Text(self.window, bg='#1e1e1e', fg='#e0e0e0', font=('Consolas', 10))
        scrollbar = ttk.Scrollbar(self.window, orient=tk.VERTICAL, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.text.tag_configure('INFO', foreground='#a0a0a0')
        self.text.tag_configure('SUCCESS', foreground='#00cc00')
        self.text.tag_configure('ERROR', foreground='#ff4444')
        self.text.tag_configure('WARNING', foreground='#ffaa00')
        self.text.tag_configure('PROGRESS', foreground='#00aaff')

        self.refresh()
        self.auto_refresh()

    def refresh(self):
        self.text.configure(state='normal')
        self.text.delete('1.0', tk.END)
        for line, level in self.logger.lines:
            self.text.insert(tk.END, line + "\n", level)
        if self.auto_scroll.get():
            self.text.see(tk.END)
        self.text.configure(state='disabled')

    def auto_refresh(self):
        if self.window.winfo_exists():
            self.refresh()
            self.window.after(1000, self.auto_refresh)

    def open_file(self):
        os.startfile(self.logger.log_file)


class DashboardUploader:
    """대시보드 기반 업로더"""

    def __init__(self, root):
        self.root = root
        self.root.title("불사자 업로더 대시보드 v2")
        self.root.geometry("1100x800")

        self.config = self._load_config()
        self.sessions = {}
        self.loggers = {}
        self.running = False

        self._create_ui()
        self._load_groups()

    def _load_config(self) -> dict:
        config_path = Path(__file__).parent / CONFIG_FILE
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _save_config(self):
        config_path = Path(__file__).parent / CONFIG_FILE
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def _create_ui(self):
        # ========== 상단: 그룹 선택 ==========
        top_frame = ttk.LabelFrame(self.root, text="마켓 그룹 선택", padding=5)
        top_frame.pack(fill=tk.X, padx=10, pady=5)

        # 스크롤 가능한 그룹 영역
        group_canvas = tk.Canvas(top_frame, height=100)
        group_scrollbar_y = ttk.Scrollbar(top_frame, orient=tk.VERTICAL, command=group_canvas.yview)
        group_scrollbar_x = ttk.Scrollbar(top_frame, orient=tk.HORIZONTAL, command=group_canvas.xview)
        self.group_frame = ttk.Frame(group_canvas)

        self.group_frame.bind("<Configure>", lambda e: group_canvas.configure(scrollregion=group_canvas.bbox("all")))
        group_canvas.create_window((0, 0), window=self.group_frame, anchor="nw")
        group_canvas.configure(yscrollcommand=group_scrollbar_y.set, xscrollcommand=group_scrollbar_x.set)

        group_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        group_scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        group_canvas.pack(fill=tk.BOTH, expand=True)

        self.group_vars = {}

        # 그룹 선택 버튼
        btn_row = ttk.Frame(top_frame)
        btn_row.pack(fill=tk.X, pady=2)
        ttk.Button(btn_row, text="전체선택", command=self._select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="전체해제", command=self._deselect_all).pack(side=tk.LEFT, padx=2)

        # ========== 설정 영역 ==========
        settings_frame = ttk.LabelFrame(self.root, text="업로드 설정", padding=5)
        settings_frame.pack(fill=tk.X, padx=10, pady=5)

        # --- 1행: 가격 설정 ---
        row1 = ttk.Frame(settings_frame)
        row1.pack(fill=tk.X, pady=2)

        ttk.Label(row1, text="환율:").pack(side=tk.LEFT)
        self.exchange_rate_var = tk.StringVar(value=str(self.config.get('exchange_rate', 200)))
        ttk.Entry(row1, textvariable=self.exchange_rate_var, width=5).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row1, text="카드수수료%:").pack(side=tk.LEFT)
        self.card_fee_var = tk.StringVar(value=str(self.config.get('card_fee', 3.3)))
        ttk.Entry(row1, textvariable=self.card_fee_var, width=5).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row1, text="마진율%:").pack(side=tk.LEFT)
        self.margin_rate_var = tk.StringVar(value=str(self.config.get('margin_rate', 30)))
        ttk.Entry(row1, textvariable=self.margin_rate_var, width=5).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row1, text="마진고정:").pack(side=tk.LEFT)
        self.margin_fixed_var = tk.StringVar(value=str(self.config.get('margin_fixed', 0)))
        ttk.Entry(row1, textvariable=self.margin_fixed_var, width=6).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row1, text="할인율%:").pack(side=tk.LEFT)
        self.discount_rate_var = tk.StringVar(value=str(self.config.get('discount_rate', 0)))
        ttk.Entry(row1, textvariable=self.discount_rate_var, width=5).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row1, text="절사단위:").pack(side=tk.LEFT)
        self.round_unit_var = tk.StringVar(value=str(self.config.get('round_unit', 10)))
        ttk.Entry(row1, textvariable=self.round_unit_var, width=5).pack(side=tk.LEFT, padx=2)

        # --- 2행: 업로드 설정 ---
        row2 = ttk.Frame(settings_frame)
        row2.pack(fill=tk.X, pady=2)

        ttk.Label(row2, text="업로드수:").pack(side=tk.LEFT)
        self.upload_count_var = tk.StringVar(value=str(self.config.get('upload_count', 10)))
        ttk.Entry(row2, textvariable=self.upload_count_var, width=6).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row2, text="동시세션:").pack(side=tk.LEFT)
        self.concurrent_var = tk.StringVar(value=str(self.config.get('concurrent', 3)))
        ttk.Combobox(row2, textvariable=self.concurrent_var, width=4,
                    values=['1', '2', '3', '4', '5']).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row2, text="옵션수:").pack(side=tk.LEFT)
        self.option_count_var = tk.StringVar(value=str(self.config.get('option_count', 5)))
        ttk.Entry(row2, textvariable=self.option_count_var, width=5).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row2, text="옵션정렬:").pack(side=tk.LEFT)
        self.option_sort_var = tk.StringVar(value=self.config.get('option_sort', 'price_asc'))
        ttk.Combobox(row2, textvariable=self.option_sort_var, width=10,
                    values=['price_asc', 'price_desc', 'price_main']).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row2, text="제목옵션:").pack(side=tk.LEFT)
        self.title_option_var = tk.StringVar(value=self.config.get('title_option', '원본유지'))
        ttk.Combobox(row2, textvariable=self.title_option_var, width=15,
                    values=['원본유지', '옵션명추가', '브랜드추가']).pack(side=tk.LEFT, padx=2)

        # --- 3행: 가격 필터 ---
        row3 = ttk.Frame(settings_frame)
        row3.pack(fill=tk.X, pady=2)

        ttk.Label(row3, text="최소가격:").pack(side=tk.LEFT)
        self.min_price_var = tk.StringVar(value=str(self.config.get('min_price', 0)))
        ttk.Entry(row3, textvariable=self.min_price_var, width=8).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row3, text="최대가격:").pack(side=tk.LEFT)
        self.max_price_var = tk.StringVar(value=str(self.config.get('max_price', 9999999)))
        ttk.Entry(row3, textvariable=self.max_price_var, width=10).pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(row3, text="업로드조건:").pack(side=tk.LEFT)
        self.upload_condition_var = tk.StringVar(value=self.config.get('upload_condition', '전체'))
        ttk.Combobox(row3, textvariable=self.upload_condition_var, width=25,
                    values=['전체', '번역완료', '이미지수정완료', '번역+이미지완료']).pack(side=tk.LEFT, padx=2)

        # --- 4행: 마켓 선택 (체크박스) ---
        row4 = ttk.Frame(settings_frame)
        row4.pack(fill=tk.X, pady=2)

        ttk.Label(row4, text="대상마켓:").pack(side=tk.LEFT)
        self.market_vars = {}
        for market_name in ['스마트스토어', '11번가', 'G마켓/옥션', '쿠팡']:
            var = tk.BooleanVar(value=(market_name == self.config.get('market_name', '스마트스토어')))
            self.market_vars[market_name] = var
            ttk.Checkbutton(row4, text=market_name, variable=var).pack(side=tk.LEFT, padx=5)

        # --- 5행: 옵션 체크박스 ---
        row5 = ttk.Frame(settings_frame)
        row5.pack(fill=tk.X, pady=2)

        self.thumbnail_match_var = tk.BooleanVar(value=self.config.get('thumbnail_match', False))
        ttk.Checkbutton(row5, text="썸네일매칭 대표상품", variable=self.thumbnail_match_var).pack(side=tk.LEFT, padx=5)

        self.skip_sku_update_var = tk.BooleanVar(value=self.config.get('skip_sku_update', False))
        ttk.Checkbutton(row5, text="SKU수정안함", variable=self.skip_sku_update_var).pack(side=tk.LEFT, padx=5)

        self.skip_price_update_var = tk.BooleanVar(value=self.config.get('skip_price_update', False))
        ttk.Checkbutton(row5, text="가격수정안함", variable=self.skip_price_update_var).pack(side=tk.LEFT, padx=5)

        self.prevent_duplicate_var = tk.BooleanVar(value=self.config.get('prevent_duplicate', True))
        ttk.Checkbutton(row5, text="불사자중복방지", variable=self.prevent_duplicate_var).pack(side=tk.LEFT, padx=5)

        self.skip_already_uploaded_var = tk.BooleanVar(value=self.config.get('skip_already_uploaded', False))
        ttk.Checkbutton(row5, text="해당마켓 미업로드만", variable=self.skip_already_uploaded_var).pack(side=tk.LEFT, padx=5)

        # --- 6행: 마켓별 옵션 ---
        row6 = ttk.Frame(settings_frame)
        row6.pack(fill=tk.X, pady=2)

        self.esm_discount_3_var = tk.BooleanVar(value=self.config.get('esm_discount_3', False))
        ttk.Checkbutton(row6, text="ESM/11번가 할인3%", variable=self.esm_discount_3_var).pack(side=tk.LEFT, padx=5)

        self.esm_option_normalize_var = tk.BooleanVar(value=self.config.get('esm_option_normalize', False))
        ttk.Checkbutton(row6, text="ESM옵션표준화", variable=self.esm_option_normalize_var).pack(side=tk.LEFT, padx=5)

        self.ss_category_search_var = tk.BooleanVar(value=self.config.get('ss_category_search', True))
        ttk.Checkbutton(row6, text="SS카테고리검색", variable=self.ss_category_search_var).pack(side=tk.LEFT, padx=5)

        # --- 실행 버튼 ---
        btn_frame = ttk.Frame(settings_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        ttk.Button(btn_frame, text="▶ 업로드 시작", command=self._start_upload).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="■ 전체 중지", command=self._stop_all).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="설정 저장", command=self._save_all_settings).pack(side=tk.LEFT, padx=5)

        # ========== 대시보드 테이블 ==========
        dash_frame = ttk.LabelFrame(self.root, text="세션 대시보드", padding=5)
        dash_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        columns = ('session', 'group', 'market', 'status', 'progress', 'success', 'failed', 'current')
        self.tree = ttk.Treeview(dash_frame, columns=columns, show='headings', height=12)

        self.tree.heading('session', text='#')
        self.tree.heading('group', text='그룹')
        self.tree.heading('market', text='마켓')
        self.tree.heading('status', text='상태')
        self.tree.heading('progress', text='진행률')
        self.tree.heading('success', text='성공')
        self.tree.heading('failed', text='실패')
        self.tree.heading('current', text='현재 작업')

        self.tree.column('session', width=40, anchor='center')
        self.tree.column('group', width=120)
        self.tree.column('market', width=80)
        self.tree.column('status', width=80, anchor='center')
        self.tree.column('progress', width=70, anchor='center')
        self.tree.column('success', width=50, anchor='center')
        self.tree.column('failed', width=50, anchor='center')
        self.tree.column('current', width=350)

        tree_scroll = ttk.Scrollbar(dash_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind('<Double-1>', self._on_tree_double_click)

        # 버튼 행
        tree_btn_frame = ttk.Frame(dash_frame)
        tree_btn_frame.pack(fill=tk.X, pady=3)

        ttk.Button(tree_btn_frame, text="선택 세션 중지", command=self._stop_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(tree_btn_frame, text="선택 로그 보기", command=self._view_selected_log).pack(side=tk.LEFT, padx=3)
        ttk.Button(tree_btn_frame, text="로그 폴더 열기", command=self._open_log_folder).pack(side=tk.RIGHT, padx=3)

        # ========== 하단: 통합 로그 ==========
        log_frame = ttk.LabelFrame(self.root, text="통합 요약 로그", padding=3)
        log_frame.pack(fill=tk.X, padx=10, pady=5)

        self.summary_log = tk.Text(log_frame, height=5, bg='#2d2d2d', fg='#e0e0e0', font=('Consolas', 9))
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.summary_log.yview)
        self.summary_log.configure(yscrollcommand=log_scroll.set)

        self.summary_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.summary_log.tag_configure('info', foreground='#a0a0a0')
        self.summary_log.tag_configure('success', foreground='#00cc00')
        self.summary_log.tag_configure('error', foreground='#ff4444')

    def _load_groups(self):
        """마켓 그룹 로드"""
        try:
            api = BulsajaAPIClient(
                self.config.get('access_token', ''),
                self.config.get('refresh_token', '')
            )

            response = api.session.post(f"{api.BASE_URL}/market/groups/", json={})
            response.raise_for_status()
            groups = response.json()

            # 5열 그리드로 표시
            for i, group in enumerate(groups):
                group_name = group.get('name', '')
                if not group_name:
                    continue

                var = tk.BooleanVar(value=False)
                self.group_vars[group_name] = {'var': var, 'id': group.get('id')}

                cb = ttk.Checkbutton(self.group_frame, text=group_name, variable=var)
                cb.grid(row=i // 5, column=i % 5, padx=5, pady=2, sticky='w')

        except Exception as e:
            ttk.Label(self.group_frame, text=f"그룹 로드 실패: {e}", foreground="red").grid(row=0, column=0)

    def _select_all(self):
        for data in self.group_vars.values():
            if isinstance(data, dict):
                data['var'].set(True)

    def _deselect_all(self):
        for data in self.group_vars.values():
            if isinstance(data, dict):
                data['var'].set(False)

    def _save_all_settings(self):
        """모든 설정 저장"""
        self.config['exchange_rate'] = float(self.exchange_rate_var.get())
        self.config['card_fee'] = float(self.card_fee_var.get())
        self.config['margin_rate'] = float(self.margin_rate_var.get())
        self.config['margin_fixed'] = float(self.margin_fixed_var.get())
        self.config['discount_rate'] = float(self.discount_rate_var.get())
        self.config['round_unit'] = int(self.round_unit_var.get())
        self.config['upload_count'] = int(self.upload_count_var.get())
        self.config['concurrent'] = int(self.concurrent_var.get())
        self.config['option_count'] = int(self.option_count_var.get())
        self.config['option_sort'] = self.option_sort_var.get()
        self.config['title_option'] = self.title_option_var.get()
        self.config['min_price'] = int(self.min_price_var.get())
        self.config['max_price'] = int(self.max_price_var.get())
        self.config['upload_condition'] = self.upload_condition_var.get()
        self.config['thumbnail_match'] = self.thumbnail_match_var.get()
        self.config['skip_sku_update'] = self.skip_sku_update_var.get()
        self.config['skip_price_update'] = self.skip_price_update_var.get()
        self.config['prevent_duplicate'] = self.prevent_duplicate_var.get()
        self.config['skip_already_uploaded'] = self.skip_already_uploaded_var.get()
        self.config['esm_discount_3'] = self.esm_discount_3_var.get()
        self.config['esm_option_normalize'] = self.esm_option_normalize_var.get()
        self.config['ss_category_search'] = self.ss_category_search_var.get()

        self._save_config()
        messagebox.showinfo("저장", "설정이 저장되었습니다")

    def _get_selected_markets(self) -> List[str]:
        """선택된 마켓 목록"""
        return [name for name, var in self.market_vars.items() if var.get()]

    def _start_upload(self):
        """업로드 시작"""
        # 선택된 그룹
        selected_groups = [(name, data['id']) for name, data in self.group_vars.items()
                          if isinstance(data, dict) and data['var'].get()]

        if not selected_groups:
            messagebox.showwarning("경고", "그룹을 1개 이상 선택하세요")
            return

        # 선택된 마켓
        selected_markets = self._get_selected_markets()
        if not selected_markets:
            messagebox.showwarning("경고", "마켓을 1개 이상 선택하세요")
            return

        # 설정 저장
        self._save_all_settings()

        # 기존 세션 클리어
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.sessions.clear()
        self.loggers.clear()

        self.running = True

        # 세션 생성 (그룹 x 마켓 조합)
        session_id = 0
        for group_name, group_id in selected_groups:
            for market_name in selected_markets:
                session_id += 1

                logger = SessionLogger(session_id, f"{group_name}_{market_name}")
                self.loggers[session_id] = logger

                item_id = self.tree.insert('', tk.END, values=(
                    session_id, group_name, market_name, "⏳ 대기", "0/0", 0, 0, "초기화 중..."
                ))

                self.sessions[session_id] = {
                    'item_id': item_id,
                    'group_name': group_name,
                    'group_id': group_id,
                    'market_name': market_name,
                    'success': 0,
                    'failed': 0,
                    'total': 0,
                    'current': 0,
                    'running': True,
                    'logger': logger
                }

        # 동시 세션 수 제한하며 실행
        max_concurrent = int(self.concurrent_var.get())
        self._log_summary(f"업로드 시작: {len(self.sessions)}개 세션 (동시 {max_concurrent}개)", 'info')

        # 세션 순차 실행 (동시성 제한)
        threading.Thread(target=self._run_sessions_with_limit, args=(max_concurrent,), daemon=True).start()

    def _run_sessions_with_limit(self, max_concurrent: int):
        """동시성 제한하며 세션 실행"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {executor.submit(self._run_session, sid): sid for sid in self.sessions.keys()}
            for future in as_completed(futures):
                session_id = futures[future]
                try:
                    future.result()
                except Exception as e:
                    self._log_summary(f"[S{session_id}] 오류: {e}", 'error')

    def _run_session(self, session_id: int):
        """세션 실행"""
        session = self.sessions[session_id]
        logger = session['logger']
        group_name = session['group_name']
        group_id = session['group_id']
        market_name = session['market_name']

        logger.log(f"세션 시작 - 그룹: {group_name}, 마켓: {market_name}")

        try:
            api = BulsajaAPIClient(
                self.config.get('access_token', ''),
                self.config.get('refresh_token', '')
            )

            # 마켓 ID 조회
            target_type = MARKET_TYPES.get(market_name, 'SMARTSTORE')
            markets_url = f"{api.BASE_URL}/market/group/{group_id}/markets"
            response = api.session.get(markets_url)
            markets = response.json()

            market_id = None
            for market in markets:
                if market.get('type') == target_type:
                    market_id = market.get('id')
                    break

            if not market_id:
                logger.log(f"마켓 ID를 찾을 수 없음: {target_type}", "ERROR")
                self._update_session(session_id, status="❌ 오류", current="마켓 ID 없음")
                return

            logger.log(f"마켓 ID: {market_id}")

            # 상품 목록 조회
            products = api.get_product_list(
                group_name=group_name,
                status_filters=['0', '1', '2'],
                limit=int(self.upload_count_var.get())
            )

            if not products:
                logger.log("업로드할 상품이 없음", "WARNING")
                self._update_session(session_id, status="⚠ 없음", current="상품 없음")
                return

            session['total'] = len(products)
            logger.log(f"상품 {len(products)}개 로드")
            self._update_session(session_id, status="🔄 진행중")

            # 상품 업로드
            for i, product in enumerate(products):
                if not session['running'] or not self.running:
                    logger.log("사용자에 의해 중지됨", "WARNING")
                    self._update_session(session_id, status="⏹ 중지", current="사용자 중지")
                    break

                product_id = product.get('ID', product.get('id', ''))
                product_name = product.get('uploadCommonProductName', '')[:25]

                session['current'] = i + 1
                self._update_session(session_id, current=f"[{i+1}/{len(products)}] {product_name}")
                logger.log(f"처리 중: {product_name}", "PROGRESS")

                try:
                    upload_url = f"{api.BASE_URL}/market/{market_id}/upload/"
                    payload = {
                        "productId": product_id,
                        "preventDuplicate": self.prevent_duplicate_var.get()
                    }
                    result = api.session.post(upload_url, json=payload)
                    result_data = result.json()

                    if result_data.get('code') == 1:
                        session['success'] += 1
                        logger.log(f"✓ 성공: {product_name}", "SUCCESS")
                        self._log_summary(f"[S{session_id}] ✓ {product_name}", 'success')
                    else:
                        session['failed'] += 1
                        error_msg = result_data.get('message', '알 수 없는 오류')[:40]
                        logger.log(f"✗ 실패: {product_name} - {error_msg}", "ERROR")
                        self._log_summary(f"[S{session_id}] ✗ {product_name}", 'error')

                except Exception as e:
                    session['failed'] += 1
                    logger.log(f"✗ 오류: {product_name} - {str(e)[:40]}", "ERROR")

                self._update_session(session_id)
                time.sleep(1.5)

            # 완료
            logger.log(f"완료 - 성공: {session['success']}, 실패: {session['failed']}")
            logger.close(session['success'], session['failed'])
            self._update_session(session_id, status="✅ 완료", current="완료")
            self._log_summary(f"[S{session_id}] {group_name}/{market_name} 완료 - 성공:{session['success']} 실패:{session['failed']}", 'info')

        except Exception as e:
            logger.log(f"세션 오류: {str(e)}", "ERROR")
            self._update_session(session_id, status="❌ 오류", current=str(e)[:40])

    def _update_session(self, session_id: int, status: str = None, current: str = None):
        session = self.sessions.get(session_id)
        if not session:
            return

        item_id = session['item_id']
        try:
            values = list(self.tree.item(item_id, 'values'))
            if status:
                values[3] = status
            values[4] = f"{session['current']}/{session['total']}"
            values[5] = session['success']
            values[6] = session['failed']
            if current:
                values[7] = current
            self.tree.item(item_id, values=values)
        except:
            pass

    def _log_summary(self, msg: str, tag: str = 'info'):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.summary_log.configure(state='normal')
        self.summary_log.insert(tk.END, f"[{timestamp}] {msg}\n", tag)
        self.summary_log.see(tk.END)
        lines = int(self.summary_log.index('end-1c').split('.')[0])
        if lines > 100:
            self.summary_log.delete('1.0', '2.0')
        self.summary_log.configure(state='disabled')

    def _stop_selected(self):
        for item in self.tree.selection():
            values = self.tree.item(item, 'values')
            session_id = int(values[0])
            if session_id in self.sessions:
                self.sessions[session_id]['running'] = False

    def _stop_all(self):
        self.running = False
        for session in self.sessions.values():
            session['running'] = False

    def _view_selected_log(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("알림", "세션을 선택하세요")
            return

        for item in selected:
            values = self.tree.item(item, 'values')
            session_id = int(values[0])
            self._open_log_viewer(session_id)

    def _on_tree_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            values = self.tree.item(item, 'values')
            session_id = int(values[0])
            self._open_log_viewer(session_id)

    def _open_log_viewer(self, session_id: int):
        if session_id not in self.sessions:
            return
        session = self.sessions[session_id]
        LogViewerWindow(self.root, session_id, f"{session['group_name']}_{session['market_name']}", session['logger'])

    def _open_log_folder(self):
        LOG_DIR.mkdir(exist_ok=True)
        os.startfile(LOG_DIR)


def main():
    root = tk.Tk()
    app = DashboardUploader(root)
    root.mainloop()


if __name__ == "__main__":
    main()
