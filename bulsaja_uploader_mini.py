# -*- coding: utf-8 -*-
"""
불사자 업로더 - 미니 터미널 UI (서버용)
- 로그와 진행상황만 표시
- 시작/중단 버튼
- 서버 연결 시 WebSocket으로 작업 명령 수신

by 프코노미
"""

import os
import sys
import json
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

import tkinter as tk
from tkinter import ttk, scrolledtext

# 공통 모듈 경로 추가
sys.path.insert(0, str(Path(__file__).parent))

# 메인 업로더에서 필요한 클래스 가져오기
try:
    from importlib import import_module
    uploader_module = import_module("7. bulsaja_uploader_v1.5")
    UploaderEngine = uploader_module.UploaderEngine
    load_config = uploader_module.load_config
    save_config = uploader_module.save_config
    MARKET_IDS = uploader_module.MARKET_IDS
    UPLOAD_CONDITIONS = uploader_module.UPLOAD_CONDITIONS
    OPTION_SORT_OPTIONS = uploader_module.OPTION_SORT_OPTIONS
except ImportError as e:
    print(f"업로더 모듈 로드 실패: {e}")
    sys.exit(1)


class MiniTerminalGUI:
    """미니 터미널 GUI - 서버용"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🚀 불사자 업로더 - 서버 모드")
        self.root.geometry("500x400")
        self.root.configure(bg="#1a1a24")

        # 설정 로드
        self.config_data = load_config()

        # 상태 변수
        self.is_running = False
        self.engine = None
        self.ws_connected = False

        # GUI 변수 (엔진 호환용)
        self._init_gui_vars()

        # UI 구성
        self._build_ui()

        # 엔진 초기화
        self._init_engine()

    def _init_gui_vars(self):
        """GUI 변수 초기화 (엔진 호환용)"""
        # 체크박스 변수들
        self.skip_already_uploaded_var = tk.BooleanVar(value=True)
        self.skip_failed_tag_var = tk.BooleanVar(value=True)
        self.prevent_duplicate_upload_var = tk.BooleanVar(value=False)
        self.ss_category_search_var = tk.BooleanVar(value=True)
        self.esm_option_normalize_var = tk.BooleanVar(value=True)
        self.esm_discount_3_var = tk.BooleanVar(value=True)
        self.thumbnail_match_var = tk.BooleanVar(value=True)
        self.skip_sku_update_var = tk.BooleanVar(value=False)
        self.skip_price_update_var = tk.BooleanVar(value=False)

        # 텍스트 필드 (엔진에서 접근)
        self.exclude_cat_text = None  # 나중에 초기화
        self.banned_kw_text = None    # 나중에 초기화

        # 설정값 로드
        c = self.config_data
        if "skip_failed_tag" in c:
            self.skip_failed_tag_var.set(c["skip_failed_tag"])

    def _build_ui(self):
        """UI 구성"""
        # 메인 프레임 (어두운 배경)
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 스타일 설정
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background="#1a1a24")
        style.configure("TLabel", background="#1a1a24", foreground="#f1f5f9")
        style.configure("TButton", padding=6)
        style.configure("Green.TButton", background="#10b981")
        style.configure("Red.TButton", background="#ef4444")

        # === 헤더 ===
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))

        title_label = tk.Label(header_frame, text="🚀 불사자 업로더",
                               font=('Segoe UI', 14, 'bold'),
                               bg="#1a1a24", fg="#f97316")
        title_label.pack(side=tk.LEFT)

        # 연결 상태 표시
        self.status_label = tk.Label(header_frame, text="⚫ 대기 중",
                                     font=('Segoe UI', 10),
                                     bg="#1a1a24", fg="#64748b")
        self.status_label.pack(side=tk.RIGHT)

        # === 진행 상황 ===
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 10))

        self.progress_label = tk.Label(progress_frame, text="진행: 0/0 (0%)",
                                       font=('JetBrains Mono', 11),
                                       bg="#1a1a24", fg="#f1f5f9")
        self.progress_label.pack(side=tk.LEFT)

        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate', length=300)
        self.progress_bar.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))

        # === 로그 ===
        log_frame = ttk.Frame(main_frame)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.log_text = tk.Text(log_frame, height=15, state='disabled',
                                bg="#12121a", fg="#f1f5f9",
                                font=('Consolas', 9), wrap=tk.WORD,
                                insertbackground="#f1f5f9")
        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)

        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 로그 색상 태그
        self.log_text.tag_configure("error", foreground="#ef4444")
        self.log_text.tag_configure("success", foreground="#10b981")
        self.log_text.tag_configure("warning", foreground="#f59e0b")
        self.log_text.tag_configure("info", foreground="#3b82f6")
        self.log_text.tag_configure("skip", foreground="#64748b")

        # === 버튼 ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X)

        self.btn_start = tk.Button(btn_frame, text="▶ 시작",
                                   command=self.start_upload,
                                   bg="#10b981", fg="white",
                                   font=('Segoe UI', 10, 'bold'),
                                   width=12, height=2)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_stop = tk.Button(btn_frame, text="■ 중지",
                                  command=self.stop_upload,
                                  bg="#ef4444", fg="white",
                                  font=('Segoe UI', 10, 'bold'),
                                  width=12, height=2,
                                  state='disabled')
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_connect = tk.Button(btn_frame, text="🔗 서버 연결",
                                     command=self.connect_server,
                                     bg="#3b82f6", fg="white",
                                     font=('Segoe UI', 10),
                                     width=12, height=2)
        self.btn_connect.pack(side=tk.RIGHT)

        # === 숨겨진 텍스트 필드 (엔진 호환용) ===
        # 제외 카테고리, 금지 키워드
        hidden_frame = tk.Frame(self.root)
        self.exclude_cat_text = tk.Text(hidden_frame, height=1, width=1)
        self.banned_kw_text = tk.Text(hidden_frame, height=1, width=1)

        # 설정에서 로드
        c = self.config_data
        if "exclude_categories" in c:
            self.exclude_cat_text.insert("1.0", c["exclude_categories"])
        if "banned_keywords" in c:
            self.banned_kw_text.insert("1.0", c["banned_keywords"])

    def _init_engine(self):
        """업로더 엔진 초기화"""
        try:
            # 가격 설정 (기본값)
            class PriceSettings:
                exchange_rate = float(self.config_data.get("exchange_rate", 195))
                card_fee = float(self.config_data.get("card_fee", 3.3))
                margin_rate_min = 15
                margin_rate_max = 25
                margin_fixed = int(self.config_data.get("margin_fixed", 3000))
                discount_rate_min = 0
                discount_rate_max = 10
                round_unit = int(self.config_data.get("round_unit", 100))

            # 엔진 생성
            self.engine = UploaderEngine(self, PriceSettings())
            self.log("✅ 업로더 엔진 초기화 완료")
        except Exception as e:
            self.log(f"❌ 엔진 초기화 실패: {e}")

    def log(self, message: str):
        """로그 출력"""
        def _log():
            self.log_text.config(state='normal')
            timestamp = datetime.now().strftime("%H:%M:%S")

            # 태그 결정
            tag = None
            if any(x in message for x in ["❌", "실패", "에러", "오류"]):
                tag = "error"
            elif any(x in message for x in ["✅", "성공", "완료"]):
                tag = "success"
            elif any(x in message for x in ["⚠️", "경고"]):
                tag = "warning"
            elif any(x in message for x in ["⏭️", "건너뜀", "스킵"]):
                tag = "skip"
            elif any(x in message for x in ["📤", "🚀", "🔍"]):
                tag = "info"

            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n", tag)
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')

        self.root.after(0, _log)

    def update_progress(self, current: int, total: int):
        """진행상황 업데이트"""
        def _update():
            percent = (current / total * 100) if total > 0 else 0
            self.progress_label.config(text=f"진행: {current}/{total} ({percent:.1f}%)")
            self.progress_bar['value'] = percent
        self.root.after(0, _update)

    def update_status(self, status: str, color: str = "#64748b"):
        """상태 업데이트"""
        def _update():
            self.status_label.config(text=status, fg=color)
        self.root.after(0, _update)

    def start_upload(self):
        """업로드 시작"""
        if self.is_running:
            return

        self.is_running = True
        self.btn_start.config(state='disabled')
        self.btn_stop.config(state='normal')
        self.update_status("🟢 실행 중", "#10b981")

        # 백그라운드 스레드에서 실행
        threading.Thread(target=self._run_upload, daemon=True).start()

    def _run_upload(self):
        """업로드 실행 (백그라운드)"""
        try:
            c = self.config_data

            # 그룹 목록 파싱
            group_text = c.get("group_text", "")
            if not group_text:
                self.log("❌ 그룹 설정이 없습니다. 메인 프로그램에서 설정하세요.")
                self.on_finished()
                return

            groups = [g.strip() for g in group_text.split(',') if g.strip()]
            if not groups:
                self.log("❌ 처리할 그룹이 없습니다.")
                self.on_finished()
                return

            # 작업 그룹 파싱
            work_groups_str = c.get("work_groups", "1")
            work_indices = self._parse_work_range(work_groups_str)

            # 그룹 매핑
            selected_groups = []
            for idx in work_indices:
                idx_int = int(idx)
                if 1 <= idx_int <= len(groups):
                    selected_groups.append(groups[idx_int - 1])

            if not selected_groups:
                self.log("❌ 선택된 그룹이 없습니다.")
                self.on_finished()
                return

            self.log(f"📁 작업 그룹: {', '.join(selected_groups)}")

            # 설정값
            upload_count = int(c.get("upload_count", 10))
            option_count = int(c.get("option_count", 5))
            option_sort = OPTION_SORT_OPTIONS.get(c.get("option_sort", "가격낮은순"), "price_asc")

            # 업로드 조건
            condition_key = c.get("upload_condition", "미업로드(수집완료+수정중+검토완료)")
            status_filters = UPLOAD_CONDITIONS.get(condition_key, ["0", "1", "2"])

            # 마켓
            markets = c.get("markets", ["스마트스토어"])

            self.log(f"📊 설정: 그룹당 {upload_count}개, 옵션 {option_count}개")
            self.log(f"🛒 마켓: {', '.join(markets)}")

            # 각 마켓별로 실행
            for market_name in markets:
                if not self.is_running:
                    break

                self.log(f"\n{'='*40}")
                self.log(f"🚀 [{market_name}] 업로드 시작")
                self.log(f"{'='*40}")

                self.engine.process_groups(
                    selected_groups, upload_count, option_count, option_sort,
                    status_filters, 1, "original", False, False, market_name
                )

            self.log("\n✅ 모든 작업 완료")

        except Exception as e:
            self.log(f"❌ 오류 발생: {e}")
        finally:
            self.on_finished()

    def _parse_work_range(self, range_str: str) -> List[str]:
        """작업 범위 파싱"""
        result = []
        range_str = range_str.strip()

        if '-' in range_str and ',' not in range_str:
            parts = range_str.split('-')
            if len(parts) == 2:
                try:
                    start = int(parts[0])
                    end = int(parts[1])
                    result = [str(i) for i in range(start, end + 1)]
                except ValueError:
                    result = [range_str]
        elif ',' in range_str:
            result = [x.strip() for x in range_str.split(',') if x.strip()]
        else:
            result = [range_str]

        return result

    def stop_upload(self):
        """업로드 중지"""
        self.is_running = False
        if self.engine:
            self.engine.is_running = False
        self.log("🛑 중지 요청됨...")
        self.update_status("🟡 중지 중...", "#f59e0b")

    def on_finished(self):
        """작업 완료 콜백"""
        def _finish():
            self.is_running = False
            self.btn_start.config(state='normal')
            self.btn_stop.config(state='disabled')
            self.update_status("⚫ 대기 중", "#64748b")
        self.root.after(0, _finish)

    def connect_server(self):
        """서버 연결 (WebSocket)"""
        # TODO: WebSocket 서버 연결 구현
        self.log("🔗 서버 연결 기능은 추후 구현 예정입니다.")
        self.update_status("🔗 연결 시도 중...", "#3b82f6")

    def run(self):
        """GUI 실행"""
        self.log("🚀 미니 터미널 시작")
        self.log("📋 설정은 메인 프로그램(7. bulsaja_uploader_v1.5.py)에서 변경하세요.")
        self.root.mainloop()


def main():
    app = MiniTerminalGUI()
    app.run()


if __name__ == "__main__":
    main()
