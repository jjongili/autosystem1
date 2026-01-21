# -*- coding: utf-8 -*-
"""
네이버 스마트스토어 로그인 → 마케팅분석 데이터 → 구글시트 저장
v1.4.2 - 선택한 계정(마켓)만 실행 버튼 추가

✅ 계정은 항상 여기(종합 시트에서 ID/PW):
- 1npEWFWFGoOQjSmEMTNUFzcgCRZIQvo7LAUQMduorK3w

✅ 결과 저장은 항상 여기:
- 1cGVrTCqfxCI-bb5tUJavLZLOMYQ-n4mY_e9EyBiAofY
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import threading
import time
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import ElementClickInterceptedException

import subprocess
import os
import json

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials


# =========================
# ✅ 고정 문서 ID
# =========================
ACCOUNT_SPREADSHEET_ID = "1npEWFWFGoOQjSmEMTNUFzcgCRZIQvo7LAUQMduorK3w"  # 계정(종합)
DEST_SPREADSHEET_ID    = "1cGVrTCqfxCI-bb5tUJavLZLOMYQ-n4mY_e9EyBiAofY"  # 저장(정리)


class SmartStoreMarketing:
    def __init__(self, root):
        self.root = root
        self.root.title("스마트스토어 마케팅분석 수집기 v1.4.2 (선택 실행 추가)")
        self.root.geometry("900x860")

        self.driver = None
        self.chrome_process = None
        self.is_running = False

        # 계정 목록 (구글시트에서 자동 로드)
        self.accounts = []

        # Google Sheets
        self.json_path = ""
        self.gc = None

        self.account_spreadsheet = None   # 계정용(고정)
        self.dest_spreadsheet = None      # 저장용(고정)

        # 계정 시트 설정
        self.account_sheet_name = "종합"
        self.account_header_id = "ID"
        self.account_header_pw = "PW"

        # 예약 실행(사용자 선택 시간)
        self.auto_enabled = False
        self.auto_hour = 5
        self.auto_minute = 0
        self.auto_after_id = None
        self.next_run_strvar = tk.StringVar(value="다음 실행: -")

        # 설정 파일 경로
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_file = os.path.join(base_dir, "config.json")

        self.load_config()
        self.setup_ui()

        self.root.after(500, self.auto_start_chrome)

        # 저장된 설정에서 auto_enabled가 true면 예약 자동 시작
        if self.auto_enabled:
            self.root.after(800, self.start_schedule_from_ui_silent)

    # -------------------------
    # UI
    # -------------------------
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ========== 구글시트 설정 ==========
        google_frame = ttk.LabelFrame(main_frame, text="구글시트(고정) 연결", padding="10")
        google_frame.pack(fill=tk.X, pady=(0, 10))

        # JSON 파일 선택
        json_row = ttk.Frame(google_frame)
        json_row.pack(fill=tk.X, pady=3)
        ttk.Label(json_row, text="서비스계정 JSON:", width=15).pack(side=tk.LEFT)
        self.json_path_var = tk.StringVar(value=self.json_path)
        ttk.Entry(json_row, textvariable=self.json_path_var, width=55).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(json_row, text="찾기", command=self.browse_json).pack(side=tk.LEFT)

        # 고정 문서 안내
        info = (
            f"계정(종합) 고정 ID: {ACCOUNT_SPREADSHEET_ID}\n"
            f"저장(정리) 고정 ID: {DEST_SPREADSHEET_ID}\n"
            f"* '연결'을 누르면 두 문서에 동시에 연결하고, 계정(ID/PW)을 자동으로 불러옵니다."
        )
        ttk.Label(google_frame, text=info, foreground="gray", font=('', 9)).pack(anchor=tk.W, pady=(6, 0))

        # 연결 버튼 + 상태
        row2 = ttk.Frame(google_frame)
        row2.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(row2, text="연결(고정 2문서)", command=self.connect_google_sheets).pack(side=tk.LEFT)

        self.google_status = ttk.Label(row2, text="● 미연결", foreground="red", font=('', 10))
        self.google_status.pack(side=tk.LEFT, padx=10)

        ttk.Button(row2, text="계정 다시 불러오기", command=self.load_accounts_from_account_sheet).pack(side=tk.LEFT)

        # ========== 예약 실행 ==========
        schedule_frame = ttk.LabelFrame(main_frame, text="예약 실행(시간 선택)", padding="10")
        schedule_frame.pack(fill=tk.X, pady=(0, 10))

        row1 = ttk.Frame(schedule_frame)
        row1.pack(fill=tk.X, pady=3)

        ttk.Label(row1, text="매일 실행 시간:", width=15).pack(side=tk.LEFT)

        self.hour_var = tk.StringVar(value=f"{int(self.auto_hour):02d}")
        self.minute_var = tk.StringVar(value=f"{int(self.auto_minute):02d}")

        hour_values = [f"{h:02d}" for h in range(0, 24)]
        minute_values = [f"{m:02d}" for m in range(0, 60)]

        self.hour_combo = ttk.Combobox(row1, textvariable=self.hour_var, values=hour_values, width=5, state="readonly")
        self.hour_combo.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(row1, text=":").pack(side=tk.LEFT)
        self.minute_combo = ttk.Combobox(row1, textvariable=self.minute_var, values=minute_values, width=5, state="readonly")
        self.minute_combo.pack(side=tk.LEFT, padx=(5, 10))

        self.auto_var = tk.BooleanVar(value=self.auto_enabled)
        self.auto_check = ttk.Checkbutton(row1, text="예약 사용", variable=self.auto_var, command=self.on_toggle_auto)
        self.auto_check.pack(side=tk.LEFT)

        row2 = ttk.Frame(schedule_frame)
        row2.pack(fill=tk.X, pady=3)

        self.btn_schedule_start = ttk.Button(row2, text="예약 시작(저장)", command=self.start_schedule_from_ui)
        self.btn_schedule_start.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_schedule_stop = ttk.Button(row2, text="예약 중지", command=self.stop_schedule)
        self.btn_schedule_stop.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(row2, textvariable=self.next_run_strvar, foreground="blue").pack(side=tk.LEFT)

        row3 = ttk.Frame(schedule_frame)
        row3.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(row3, text="지금 1회 실행(전체)", command=self.run_once).pack(side=tk.LEFT)

        # ========== Chrome 상태 ==========
        top_frame = ttk.LabelFrame(main_frame, text="Chrome 상태", padding="5")
        top_frame.pack(fill=tk.X, pady=(0, 10))

        status_frame = ttk.Frame(top_frame)
        status_frame.pack(fill=tk.X)

        self.chrome_status = ttk.Label(status_frame, text="● Chrome 시작 중...", foreground="orange", font=('', 10))
        self.chrome_status.pack(side=tk.LEFT)

        ttk.Button(status_frame, text="Chrome 재시작", command=self.reconnect_chrome).pack(side=tk.RIGHT)

        # ========== 계정 목록 ==========
        list_frame = ttk.LabelFrame(main_frame, text="계정 목록(종합 시트에서 자동 로드) - 선택 후 '선택 실행' 가능", padding="10")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        columns = ("no", "id", "status")
        self.account_tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="headings",
            height=10,
            selectmode="extended"  # ✅ 여러 행 선택 가능
        )
        self.account_tree.heading("no", text="번호")
        self.account_tree.heading("id", text="아이디")
        self.account_tree.heading("status", text="상태")
        self.account_tree.column("no", width=50, anchor=tk.CENTER)
        self.account_tree.column("id", width=260)
        self.account_tree.column("status", width=220, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.account_tree.yview)
        self.account_tree.configure(yscrollcommand=scrollbar.set)
        self.account_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        acc_btn_frame = ttk.Frame(list_frame)
        acc_btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))
        self.account_count = ttk.Label(acc_btn_frame, text="총 0개 계정", font=('', 10, 'bold'))
        self.account_count.pack(side=tk.LEFT)

        # 실행 버튼
        exec_frame = ttk.Frame(main_frame)
        exec_frame.pack(fill=tk.X, pady=(0, 10))

        # ✅ 추가: 선택 계정 실행 버튼
        self.exec_selected_btn = ttk.Button(exec_frame, text="▶ 선택 계정 실행", command=self.start_selected)
        self.exec_selected_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=10, padx=(0, 5))

        self.exec_btn = ttk.Button(exec_frame, text="▶ 전체 계정 자동 실행", command=self.start_all)
        self.exec_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=10, padx=(5, 5))

        self.stop_btn = ttk.Button(exec_frame, text="■ 중지", command=self.stop_process, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=10, padx=(5, 0))

        # 진행률
        self.progress_var = tk.DoubleVar(value=0)
        self.progress = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)
        self.progress.pack(fill=tk.X, pady=5)

        self.progress_label = ttk.Label(main_frame, text="대기 중", font=('', 10))
        self.progress_label.pack()

        # 로그
        log_frame = ttk.LabelFrame(main_frame, text="실행 로그", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # -------------------------
    # config
    # -------------------------
    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.json_path = config.get('json_path', '')

                    self.auto_enabled = bool(config.get('auto_enabled', False))
                    self.auto_hour = int(config.get('auto_hour', 5))
                    self.auto_minute = int(config.get('auto_minute', 0))
        except:
            pass

    def save_config(self):
        try:
            config = {
                'json_path': self.json_path_var.get(),
                'auto_enabled': bool(self.auto_var.get()),
                'auto_hour': int(self.hour_var.get()),
                'auto_minute': int(self.minute_var.get()),
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except:
            pass

    # -------------------------
    # 예약 실행(시간 선택)
    # -------------------------
    def on_toggle_auto(self):
        pass

    def _calc_next_run_datetime(self, hour: int, minute: int) -> datetime:
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        return target

    def start_schedule_from_ui_silent(self):
        try:
            self.auto_var.set(True)
            self.hour_var.set(f"{int(self.auto_hour):02d}")
            self.minute_var.set(f"{int(self.auto_minute):02d}")
            self.start_schedule_from_ui(show_popup=False)
        except:
            pass

    def start_schedule_from_ui(self, show_popup=True):
        try:
            hour = int(self.hour_var.get())
            minute = int(self.minute_var.get())
        except:
            messagebox.showerror("오류", "시간/분이 올바르지 않습니다.")
            return

        self.auto_var.set(True)
        self.auto_enabled = True
        self.auto_hour = hour
        self.auto_minute = minute

        self.save_config()
        self._schedule_next_run(hour, minute)

        if show_popup:
            messagebox.showinfo("완료", f"예약 시작: 매일 {hour:02d}:{minute:02d}")

    def stop_schedule(self):
        self.auto_var.set(False)
        self.auto_enabled = False

        if self.auto_after_id is not None:
            try:
                self.root.after_cancel(self.auto_after_id)
            except:
                pass
            self.auto_after_id = None

        self.next_run_strvar.set("다음 실행: -")
        self.save_config()
        self.log("예약 중지됨")

    def _schedule_next_run(self, hour: int, minute: int):
        if self.auto_after_id is not None:
            try:
                self.root.after_cancel(self.auto_after_id)
            except:
                pass
            self.auto_after_id = None

        next_dt = self._calc_next_run_datetime(hour, minute)
        delay_ms = int((next_dt - datetime.now()).total_seconds() * 1000)
        self.next_run_strvar.set(f"다음 실행: {next_dt.strftime('%Y-%m-%d %H:%M')}")

        self.log(f"예약 설정됨 → {next_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        self.auto_after_id = self.root.after(delay_ms, self._scheduled_run_wrapper)

    def _scheduled_run_wrapper(self):
        try:
            if not self.auto_enabled or not self.auto_var.get():
                self.log("예약이 꺼져 있어서 실행 안함")
                return
            self.log("예약 실행 트리거(전체 1회)")
            self.run_once()
        finally:
            if self.auto_enabled and self.auto_var.get():
                self._schedule_next_run(int(self.hour_var.get()), int(self.minute_var.get()))

    # -------------------------
    # 유틸 / 로그
    # -------------------------
    def browse_json(self):
        filepath = filedialog.askopenfilename(
            title="서비스 계정 JSON 파일 선택",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if filepath:
            self.json_path_var.set(filepath)
            self.save_config()

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def refresh_account_list(self):
        for item in self.account_tree.get_children():
            self.account_tree.delete(item)

        for i, acc in enumerate(self.accounts, 1):
            # iid는 고유하게 (row1, row2...)로 설정
            iid = f"row{i}"
            self.account_tree.insert("", tk.END, iid=iid, values=(i, acc['id'], acc.get('status', '대기')))
        self.account_count.configure(text=f"총 {len(self.accounts)}개 계정")

    def update_account_status(self, user_id, status):
        for acc in self.accounts:
            if acc['id'] == user_id:
                acc['status'] = status
                break
        self.root.after(0, self.refresh_account_list)

    # -------------------------
    # ✅ 구글시트 연결 (고정 2문서)
    # -------------------------
    def connect_google_sheets(self):
        thread = threading.Thread(target=self._connect_google_sheets_thread, daemon=True)
        thread.start()

    def _connect_google_sheets_thread(self):
        try:
            json_path = self.json_path_var.get().strip()
            if not json_path:
                self.root.after(0, lambda: messagebox.showwarning("경고", "서비스계정 JSON 파일을 선택하세요."))
                return
            if not os.path.exists(json_path):
                self.root.after(0, lambda: self.google_status.configure(text="● JSON 파일 없음", foreground="red"))
                self.log(f"파일 없음: {json_path}")
                return

            self.log("구글 시트(고정 2문서) 연결 중...")
            self.root.after(0, lambda: self.google_status.configure(text="● 연결 중...", foreground="orange"))

            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]

            credentials = Credentials.from_service_account_file(json_path, scopes=scopes)
            self.gc = gspread.authorize(credentials)

            # ✅ 계정 문서 연결
            self.account_spreadsheet = self.gc.open_by_key(ACCOUNT_SPREADSHEET_ID)

            # ✅ 저장 문서 연결
            self.dest_spreadsheet = self.gc.open_by_key(DEST_SPREADSHEET_ID)

            self.save_config()

            self.root.after(0, lambda: self.google_status.configure(
                text="● 연결됨(계정+저장)", foreground="green"
            ))
            self.log(f"계정 문서 연결: {self.account_spreadsheet.title}")
            self.log(f"저장 문서 연결: {self.dest_spreadsheet.title}")

            # ✅ 연결되면 계정 자동 로드
            self.root.after(0, self.load_accounts_from_account_sheet)

        except gspread.exceptions.SpreadsheetNotFound:
            self.root.after(0, lambda: self.google_status.configure(text="● 시트를 찾을 수 없음", foreground="red"))
            self.log("고정 구글시트를 찾을 수 없습니다. 공유/ID 확인 필요")
            self.root.after(0, lambda: messagebox.showerror(
                "오류",
                "고정 구글시트를 찾을 수 없습니다.\n\n1) 서비스계정 이메일에 두 문서 공유했는지 확인\n2) 문서 접근 권한 확인"
            ))
        except Exception as e:
            self.root.after(0, lambda: self.google_status.configure(text="● 연결 실패", foreground="red"))
            self.log(f"구글 시트 연결 실패: {e}")

    # -------------------------
    # ✅ 계정 로드(안정형)
    # -------------------------
    def load_accounts_from_account_sheet(self):
        if not self.account_spreadsheet:
            messagebox.showwarning("경고", "계정 문서가 연결되지 않았습니다. 먼저 '연결'을 누르세요.")
            return

        try:
            # 1) 시트 열기: '종합' 실패 시 첫 시트 fallback + 로그
            try:
                ws = self.account_spreadsheet.worksheet(self.account_sheet_name)
            except Exception as e1:
                sheets = self.account_spreadsheet.worksheets()
                if not sheets:
                    raise Exception("계정 문서에 시트가 없습니다.")
                ws = sheets[0]
                self.log(f"[주의] '{self.account_sheet_name}' 시트를 못 찾아서 첫 시트로 대체: {ws.title} ({e1})")

            # 2) 헤더 읽기 + 디버그 로그
            header = ws.row_values(1)
            self.log(f"[디버그] {ws.title} 1행 헤더: {header}")

            header_norm = []
            for h in header:
                h2 = (h or "").replace("\n", " ").strip().upper()
                header_norm.append(h2)

            def find_col(names):
                for name in names:
                    key = name.strip().upper()
                    if key in header_norm:
                        return header_norm.index(key) + 1
                return None

            col_id = find_col([self.account_header_id, "아이디", "ID", "USER", "USERID", "네이버ID"])
            col_pw = find_col([self.account_header_pw, "비밀번호", "PW", "PASSWORD", "PASS", "네이버PW"])

            if not col_id or not col_pw:
                raise Exception(
                    f"헤더를 찾지 못했습니다. (ID열={col_id}, PW열={col_pw})\n"
                    f"현재 헤더(정규화): {header_norm}"
                )

            all_vals = ws.get_all_values()
            if len(all_vals) < 2:
                self.accounts = []
                self.refresh_account_list()
                self.log("계정 시트에 데이터가 없습니다(2행부터).")
                return

            accounts = []
            for r in range(2, len(all_vals) + 1):
                row = all_vals[r-1]
                user_id = row[col_id - 1].strip() if len(row) >= col_id and row[col_id - 1] else ""
                password = row[col_pw - 1].strip() if len(row) >= col_pw and row[col_pw - 1] else ""
                if user_id and password:
                    accounts.append({"id": user_id, "pw": password, "status": "대기"})

            self.accounts = accounts
            self.refresh_account_list()
            self.log(f"계정 {len(self.accounts)}개 불러옴 (시트={ws.title}, ID={col_id}열, PW={col_pw}열)")

        except Exception as e:
            messagebox.showerror("오류", f"계정 불러오기 실패: {e}")
            self.log(f"계정 불러오기 실패: {e}")

    # -------------------------
    # Chrome
    # -------------------------
    def auto_start_chrome(self):
        thread = threading.Thread(target=self._start_chrome_thread, daemon=True)
        thread.start()

    def _start_chrome_thread(self):
        self.log("Chrome 디버깅 모드로 시작 중...")

        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe")
        ]

        chrome_path = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_path = path
                break

        if not chrome_path:
            self.root.after(0, lambda: self.chrome_status.configure(text="● Chrome 없음", foreground="red"))
            return

        try:
            port = 9222
            user_data_dir = r"C:\ChromeDebug"

            try:
                import requests
                requests.get(f"http://127.0.0.1:{port}/json/version", timeout=2)
                self.log("기존 Chrome 세션 발견")
            except:
                cmd = f'"{chrome_path}" --remote-debugging-port={port} --user-data-dir="{user_data_dir}"'
                self.chrome_process = subprocess.Popen(cmd, shell=True)
                self.log("Chrome 실행됨")
                time.sleep(3)

            options = Options()
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")

            self.driver = webdriver.Chrome(options=options)
            self.driver.get("https://sell.smartstore.naver.com/#/home/about")

            self.root.after(0, lambda: self.chrome_status.configure(text="● Chrome 연결됨", foreground="green"))
            self.log("Chrome 연결 완료!")

        except Exception as e:
            self.root.after(0, lambda: self.chrome_status.configure(text="● 연결 실패", foreground="red"))
            self.log(f"Chrome 연결 실패: {e}")

    def reconnect_chrome(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
        thread = threading.Thread(target=self._start_chrome_thread, daemon=True)
        thread.start()

    # -------------------------
    # 실행(수동/예약 공통)
    # -------------------------
    def safe_click(self, element):
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.3)
            element.click()
        except ElementClickInterceptedException:
            self.driver.execute_script("arguments[0].click();", element)

    def _precheck_before_run(self):
        """실행 전 공통 체크"""
        if self.is_running:
            self.log("이미 실행 중이라 실행 요청 스킵")
            return False

        if not self.driver:
            messagebox.showwarning("경고", "Chrome이 연결되지 않았습니다.")
            return False

        if not self.dest_spreadsheet or not self.account_spreadsheet:
            messagebox.showwarning("경고", "구글 시트가 연결되지 않았습니다.\n먼저 '연결' 버튼을 클릭하세요.")
            return False

        if not self.accounts:
            messagebox.showwarning("경고", "계정이 없습니다.\n'연결' 또는 '계정 다시 불러오기'를 먼저 하세요.")
            return False

        return True

    def run_once(self):
        """전체 실행"""
        if not self._precheck_before_run():
            return
        self._start_run_thread(accounts_subset=None)

    def start_all(self):
        self.run_once()

    def start_selected(self):
        """✅ 선택한 계정만 실행"""
        if not self._precheck_before_run():
            return

        selected_iids = self.account_tree.selection()
        if not selected_iids:
            messagebox.showwarning("경고", "계정 목록에서 실행할 계정을 먼저 선택하세요.\n(여러 개 선택: Ctrl/Shift)")
            return

        selected_ids = []
        for iid in selected_iids:
            vals = self.account_tree.item(iid, "values")
            if len(vals) >= 2:
                selected_ids.append(vals[1])

        # accounts에서 매칭
        subset = []
        for acc in self.accounts:
            if acc["id"] in selected_ids:
                subset.append(acc)

        if not subset:
            messagebox.showwarning("경고", "선택된 계정을 찾지 못했습니다. 목록을 새로고침 후 다시 선택해보세요.")
            return

        self._start_run_thread(accounts_subset=subset)

    def _start_run_thread(self, accounts_subset=None):
        """스레드 실행 공통"""
        self.is_running = True
        self.exec_btn.configure(state=tk.DISABLED)
        self.exec_selected_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)

        # 진행률 초기화
        self.progress_var.set(0)
        self.progress_label.configure(text="시작 중...")

        t = threading.Thread(target=self._run_all_accounts, args=(accounts_subset,), daemon=True)
        t.start()

    def stop_process(self):
        self.is_running = False
        self.log("중지 요청됨...")

    # =========================
    # 실행 메인 루프 (전체/선택 공용)
    # =========================
    def _run_all_accounts(self, accounts_subset=None):
        run_list = accounts_subset if accounts_subset is not None else self.accounts

        total = len(run_list)
        success = 0
        failed = 0

        # 실행 시작 로그
        if accounts_subset is None:
            self.log(f"\n[실행] 전체 계정 실행 시작 (총 {total}개)")
        else:
            self.log(f"\n[실행] 선택 계정 실행 시작 (총 {total}개)")

        for i, account in enumerate(run_list):
            if not self.is_running:
                self.log("사용자에 의해 중지됨")
                break

            user_id = account['id']
            password = account['pw']

            self.root.after(0, lambda p=(i / max(total, 1)) * 100: self.progress_var.set(p))
            self.root.after(0, lambda s=f"진행: {i+1}/{total} - {user_id}":
                            self.progress_label.configure(text=s))

            self.log(f"\n{'='*50}")
            self.log(f"[{i+1}/{total}] {user_id} 처리 시작")
            self.update_account_status(user_id, "진행중...")

            try:
                if not self.do_login(user_id, password):
                    raise Exception("로그인 실패")
                self.log("  ✓ 로그인 성공")

                time.sleep(2)

                store_name = self.get_store_name()
                self.log(f"  ✓ 스토어 이름: {store_name}")

                # 전체채널 데이터 수집 (신규 추가)
                channel_data = self.collect_channel_data()
                self.log(f"  ✓ 전체채널 데이터 수집: {max(len(channel_data)-1, 0)}개 행")

                data = self.collect_marketing_data()
                self.log(f"  ✓ 마케팅분석 데이터 수집: {max(len(data)-1, 0)}개 행")

                report_data, mall_info_data = self.collect_shopping_partner_data()
                self.log(f"  ✓ 상품클릭리포트 수집: {max(len(report_data)-1, 0)}개 행")
                self.log(f"  ✓ 쇼핑몰정보 수집: {max(len(mall_info_data)-1, 0)}개 항목")

                if data or report_data or mall_info_data or channel_data:
                    self.save_to_google_sheets(store_name, data, report_data, mall_info_data, channel_data)
                    self.log("  ✓ 구글 시트 저장 완료")

                self.do_logout()

                success += 1
                self.update_account_status(user_id, f"✓ 완료 ({store_name})")

            except Exception as e:
                failed += 1
                self.log(f"  ✗ 오류: {e}")
                self.update_account_status(user_id, f"✗ 실패: {str(e)[:20]}")

                try:
                    self.do_logout()
                except:
                    pass

            time.sleep(2)

        # 종료 처리
        self.root.after(0, lambda: self.progress_var.set(100))
        self.root.after(0, lambda: self.progress_label.configure(text=f"완료! 성공: {success}, 실패: {failed}"))
        self.root.after(0, lambda: self.exec_btn.configure(state=tk.NORMAL))
        self.root.after(0, lambda: self.exec_selected_btn.configure(state=tk.NORMAL))
        self.root.after(0, lambda: self.stop_btn.configure(state=tk.DISABLED))
        self.is_running = False
        self.log(f"\n전체 완료 - 성공: {success}, 실패: {failed}")

    # -------------------------
    # 로그인/스토어명
    # -------------------------
    def do_login(self, user_id, password):
        try:
            self.driver.get("https://sell.smartstore.naver.com/#/home/about")
            time.sleep(2)

            wait = WebDriverWait(self.driver, 15)

            if "dashboard" in self.driver.current_url:
                self.do_logout()
                time.sleep(2)
                self.driver.get("https://sell.smartstore.naver.com/#/home/about")
                time.sleep(2)

            try:
                login_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-login")))
                self.safe_click(login_btn)
                time.sleep(2)
            except:
                pass

            id_input = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input.Login_ipt__6a-x7[type='text'], input[placeholder*='아이디']")))

            try:
                del_btns = self.driver.find_elements(By.CSS_SELECTOR, "button.Login_btn_del__sRNAC")
                if del_btns:
                    self.safe_click(del_btns[0])
                    time.sleep(0.3)
            except:
                pass

            id_input.click()
            id_input.send_keys(Keys.CONTROL + "a")
            id_input.send_keys(user_id)
            time.sleep(0.5)

            pw_input = self.driver.find_element(
                By.CSS_SELECTOR, "input.Login_ipt__6a-x7[type='password'], input[placeholder*='비밀번호']")

            try:
                del_btns = self.driver.find_elements(By.CSS_SELECTOR, "button.Login_btn_del__sRNAC")
                if len(del_btns) > 1:
                    self.safe_click(del_btns[1])
                    time.sleep(0.3)
            except:
                pass

            pw_input.click()
            pw_input.send_keys(Keys.CONTROL + "a")
            pw_input.send_keys(password)
            time.sleep(0.5)

            try:
                login_submit = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], button.Button_btn__VF3g3")
                self.safe_click(login_submit)
            except:
                pw_input.send_keys(Keys.ENTER)

            time.sleep(3)

            try:
                wait.until(lambda d: "dashboard" in d.current_url)
                return True
            except:
                time.sleep(5)
                return "dashboard" in self.driver.current_url

        except Exception as e:
            self.log(f"  로그인 오류: {e}")
            return False

    def get_store_name(self):
        try:
            wait = WebDriverWait(self.driver, 10)
            self.driver.get("https://sell.smartstore.naver.com/#/home/dashboard")
            time.sleep(2)
            store_elem = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.shop")))
            store_name = store_elem.text.strip()
            return store_name if store_name else "Unknown"
        except Exception as e:
            self.log(f"  스토어 이름 가져오기 실패: {e}")
            return "Unknown"

    # ============================================================
    # ✅ 전체채널 데이터 수집 (채널명, 유입수)
    # ============================================================
    def collect_channel_data(self):
        """전체채널 데이터 수집 (채널명, 유입수)"""
        wait = WebDriverWait(self.driver, 20)
        channel_data = []

        try:
            # 1. 마케팅분석 메뉴로 이동
            self.log("    → 마케팅분석 메뉴로 이동 (전체채널)")
            time.sleep(2)

            # 데이터분석 메뉴 클릭
            data_menu = None
            selectors = [
                "//a[@role='menuitem'][contains(text(),'데이터분석')]",
                "//a[contains(text(),'데이터분석')]",
            ]
            for sel in selectors:
                try:
                    data_menu = wait.until(EC.element_to_be_clickable((By.XPATH, sel)))
                    break
                except:
                    continue

            if data_menu:
                self.safe_click(data_menu)
                self.log("    → 데이터분석 클릭 완료")
            time.sleep(2)

            # 2. 마케팅분석 클릭
            marketing_link = None
            selectors = [
                "//a[contains(@href,'bizadvisor/marketing')]",
                "//a[contains(text(),'마케팅분석')]",
                "a[href='#/bizadvisor/marketing']",
            ]
            for sel in selectors:
                try:
                    if sel.startswith("//"):
                        marketing_link = wait.until(EC.element_to_be_clickable((By.XPATH, sel)))
                    else:
                        marketing_link = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                    break
                except:
                    continue

            if marketing_link:
                self.safe_click(marketing_link)
                self.log("    → 마케팅분석 클릭 완료")
            else:
                self.driver.get("https://sell.smartstore.naver.com/#/bizadvisor/marketing")
                self.log("    → 마케팅분석 URL 직접 이동")
            time.sleep(3)

            # 3. 전체채널 탭 확인 (기본 선택되어 있음)
            self.log("    → 전체채널 탭 확인")
            try:
                channel_tab = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//ul[@class='seller-menu-tap']//a[contains(@href,'bizadvisor/marketing')]/span[text()='전체채널']/..")))
                self.safe_click(channel_tab)
                self.log("    → 전체채널 탭 클릭")
            except:
                self.log("    → 전체채널 탭 이미 선택됨")
            time.sleep(2)

            # 4. iframe 전환
            self.log("    → iframe 전환")
            try:
                iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe#__delegate")))
                self.driver.switch_to.frame(iframe)
                self.log("    → iframe 전환 완료")
            except Exception as e:
                self.log(f"    → iframe 전환 실패, 계속 진행: {e}")
            time.sleep(2)

            # 5. 날짜 선택 - "어제" 선택
            self.log("    → 날짜 선택 (어제)")
            try:
                date_btn = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "a.btn.select_data")))
                self.safe_click(date_btn)
                self.log("    → 캘린더 팝업 열림")
                time.sleep(1)

                # "어제" 옵션 클릭
                yesterday_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//div[@class='fix_range']//a/span[text()='어제']/..")))
                self.safe_click(yesterday_btn)
                self.log("    → '어제' 선택")
                time.sleep(1)

                # "적용" 버튼 클릭
                apply_btn = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "span.select_range")))
                self.safe_click(apply_btn)
                self.log("    → '적용' 클릭 완료")
                time.sleep(3)

            except Exception as e:
                self.log(f"    → 날짜 선택 실패: {e}")

            # 6. 차원 "상세" 선택
            self.log("    → 차원 '상세' 선택")
            try:
                detail_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//div[@class='search_filter']//dd[@data-test-id='table-container-top-search-filter-dimension-opts']//a/span[text()='상세']/..")))
                self.safe_click(detail_btn)
                self.log("    → '상세' 선택 완료")
                time.sleep(3)
            except Exception as e:
                self.log(f"    → '상세' 선택 실패: {e}")

            # 7. 노출개수 1000으로 변경
            self.log("    → 노출개수 1000으로 변경")
            try:
                selectbox = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "div.selectbox_box.list_count div.selectbox_label a")))
                self.safe_click(selectbox)
                time.sleep(1)

                option_1000 = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//div[@class='selectbox_box list_count']//ul/li/a[text()='1000']")))
                self.safe_click(option_1000)
                self.log("    → 노출개수 1000 선택 완료")
                time.sleep(3)
            except Exception as e:
                self.log(f"    → 노출개수 변경 실패: {e}")

            # 8. 테이블 데이터 수집
            self.log("    → 전체채널 테이블 데이터 수집 중...")
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.tbl_list")))
            time.sleep(2)

            # 헤더 추가
            headers = ["채널명", "유입수"]
            channel_data.append(headers)

            # 전체 행 수집 (total_row)
            try:
                total_row = self.driver.find_element(By.CSS_SELECTOR, "tr.total_row")
                total_cells = total_row.find_elements(By.TAG_NAME, "td")
                if len(total_cells) >= 6:
                    # 채널명: 3번째 열 (index 2), 유입수: 6번째 열 (index 5)
                    channel_name = total_cells[2].text.strip()
                    inflow = total_cells[5].text.strip()
                    channel_data.append([channel_name, inflow])
                    self.log(f"    → 전체 행: {channel_name}, {inflow}")
            except Exception as e:
                self.log(f"    → 전체 행 없음: {e}")

            # 페이지네이션 처리
            page_num = 1
            while True:
                self.log(f"    → 페이지 {page_num} 수집 중...")
                time.sleep(1)

                rows = self.driver.find_elements(By.CSS_SELECTOR, "table.tbl_list tbody tr:not(.total_row)")
                self.log(f"    → 페이지 {page_num}에서 {len(rows)}개 행 발견")

                page_count = 0
                for row in rows:
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if len(cells) >= 6:
                            # 채널명: 3번째 열 (index 2), 유입수: 6번째 열 (index 5)
                            channel_name = cells[2].text.strip()
                            inflow_text = cells[5].text.strip()

                            # 유입수가 0이 아닌 행만 수집
                            try:
                                inflow = int(inflow_text.replace(",", ""))
                                if inflow >= 1:
                                    channel_data.append([channel_name, inflow_text])
                                    page_count += 1
                            except ValueError:
                                pass
                    except Exception as e:
                        continue

                self.log(f"    → 페이지 {page_num}에서 유입수>=1인 행: {page_count}개")

                # 다음 페이지 확인
                try:
                    next_btn = self.driver.find_element(By.CSS_SELECTOR, "li.btn.next:not(.disabled) a")
                    if next_btn:
                        self.safe_click(next_btn)
                        time.sleep(3)
                        page_num += 1
                    else:
                        break
                except:
                    self.log("    → 마지막 페이지")
                    break

            # iframe에서 나오기
            self.driver.switch_to.default_content()

            self.log(f"    → 전체채널 총 {len(channel_data)-1}개 행 수집 완료 (헤더 제외)")
            return channel_data

        except Exception as e:
            self.log(f"    전체채널 데이터 수집 오류: {e}")
            try:
                self.driver.switch_to.default_content()
            except:
                pass
            return channel_data

    # ============================================================
    # ✅ v1.3 원본 로직 그대로 (마케팅분석: 상품노출성과)
    # ============================================================
    def collect_marketing_data(self):
        wait = WebDriverWait(self.driver, 20)
        all_data = []

        try:
            self.log("    → 데이터분석 메뉴 클릭")
            time.sleep(2)

            data_menu = None
            selectors = [
                "//a[@role='menuitem'][contains(text(),'데이터분석')]",
                "//a[contains(text(),'데이터분석')]",
            ]
            for sel in selectors:
                try:
                    data_menu = wait.until(EC.element_to_be_clickable((By.XPATH, sel)))
                    break
                except:
                    continue

            if data_menu:
                self.safe_click(data_menu)
                self.log("    → 데이터분석 클릭 완료")
            else:
                raise Exception("데이터분석 메뉴를 찾을 수 없음")
            time.sleep(2)

            self.log("    → 마케팅분석 클릭")
            marketing_link = None
            selectors = [
                "//a[contains(@href,'bizadvisor/marketing')]",
                "//a[contains(text(),'마케팅분석')]",
                "a[href='#/bizadvisor/marketing']",
                "a[ui-sref='main.bizadvisor_marketing']",
            ]
            for sel in selectors:
                try:
                    if sel.startswith("//"):
                        marketing_link = wait.until(EC.element_to_be_clickable((By.XPATH, sel)))
                    else:
                        marketing_link = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                    break
                except:
                    continue

            if marketing_link:
                self.safe_click(marketing_link)
                self.log("    → 마케팅분석 클릭 완료")
            else:
                self.driver.get("https://sell.smartstore.naver.com/#/bizadvisor/marketing")
                self.log("    → 마케팅분석 URL 직접 이동")
            time.sleep(3)

            self.log("    → 상품노출성과 탭 클릭")
            expose_tab = None
            selectors = [
                "//span[text()='상품노출성과']",
                "//a[contains(@href,'marketing/expose')]",
                "a[href='#/bizadvisor/marketing/expose']",
                "a[ui-sref='main.bizadvisor_marketing_expose']",
            ]
            for sel in selectors:
                try:
                    if sel.startswith("//"):
                        expose_tab = wait.until(EC.element_to_be_clickable((By.XPATH, sel)))
                    else:
                        expose_tab = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                    break
                except:
                    continue

            if expose_tab:
                self.safe_click(expose_tab)
                self.log("    → 상품노출성과 클릭 완료")
            else:
                self.driver.get("https://sell.smartstore.naver.com/#/bizadvisor/marketing/expose")
                self.log("    → 상품노출성과 URL 직접 이동")
            time.sleep(3)

            self.log("    → iframe 전환")
            try:
                iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe#__delegate")))
                self.driver.switch_to.frame(iframe)
                self.log("    → iframe 전환 완료")
            except Exception as e:
                self.log(f"    → iframe 전환 실패, 계속 진행: {e}")
            time.sleep(2)

            self.log("    → 날짜 선택 시작")
            try:
                date_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "a.btn.select_data")))
                self.safe_click(date_btn)
                self.log("    → 캘린더 팝업 열림")
                time.sleep(1)

                yesterday_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//div[@class='fix_range']//a/span[text()='어제']/..")))
                self.safe_click(yesterday_btn)
                self.log("    → '어제' 선택")
                time.sleep(1)

                apply_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "span.select_range")))
                self.safe_click(apply_btn)
                self.log("    → '적용' 클릭 완료")
                time.sleep(3)

            except Exception as e:
                self.log(f"    → 날짜 선택 실패: {e}")
                self.driver.switch_to.default_content()

            self.log("    → 노출개수 1000으로 변경")
            try:
                selectbox = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "div.selectbox_box.list_count div.selectbox_label a")))
                self.safe_click(selectbox)
                time.sleep(1)
                option_1000 = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//div[@class='selectbox_box list_count']//ul/li/a[text()='1000']")))
                self.safe_click(option_1000)
                self.log("    → 노출개수 1000 선택 완료")
                time.sleep(3)
            except Exception as e:
                self.log(f"    → 노출개수 변경 실패: {e}")

            self.log("    → 테이블 데이터 수집 중...")
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.tbl_list")))
            time.sleep(2)

            headers = ["상품명", "상품ID", "채널그룹", "채널명", "키워드", "평균노출순위", "유입수"]
            all_data.append(headers)

            try:
                total_row = self.driver.find_element(By.CSS_SELECTOR, "tr.total_row")
                total_cells = total_row.find_elements(By.TAG_NAME, "td")
                if len(total_cells) >= 7:
                    total_data = [cell.text.strip() for cell in total_cells[:7]]
                    all_data.append(total_data)
                    self.log(f"    → 전체 행: {total_data}")
            except Exception as e:
                self.log(f"    → 전체 행 없음: {e}")

            page_num = 1
            stop_collecting = False

            while not stop_collecting:
                self.log(f"    → 페이지 {page_num} 수집 중...")
                time.sleep(1)

                rows = self.driver.find_elements(By.CSS_SELECTOR, "table.tbl_list tbody tr:not(.total_row)")
                page_count = 0

                for row in rows:
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if len(cells) >= 7:
                            inflow_text = cells[6].text.strip()
                            try:
                                inflow = int(inflow_text.replace(",", ""))
                                if inflow == 0:
                                    self.log("    → 유입수 0 발견, 수집 중단")
                                    stop_collecting = True
                                    break
                                if inflow >= 1:
                                    row_data = []
                                    for j, cell in enumerate(cells[:7]):
                                        if j == 0:
                                            try:
                                                link = cell.find_element(By.TAG_NAME, "a")
                                                row_data.append(link.text.strip())
                                            except:
                                                row_data.append(cell.text.strip())
                                        else:
                                            row_data.append(cell.text.strip())
                                    all_data.append(row_data)
                                    page_count += 1
                            except ValueError:
                                pass
                    except:
                        continue

                self.log(f"    → 페이지 {page_num}에서 유입수>=1인 행: {page_count}개")

                if stop_collecting:
                    break

                try:
                    next_btn = self.driver.find_element(By.CSS_SELECTOR, "li.btn.next:not(.disabled) a")
                    if next_btn:
                        self.safe_click(next_btn)
                        time.sleep(3)
                        page_num += 1
                    else:
                        break
                except:
                    self.log("    → 마지막 페이지")
                    break

            self.driver.switch_to.default_content()
            self.log(f"    → 총 {max(len(all_data)-1, 0)}개 행 수집 완료 (헤더 제외)")
            return all_data

        except Exception as e:
            self.log(f"    데이터 수집 오류: {e}")
            try:
                self.driver.switch_to.default_content()
            except:
                pass
            return all_data

    # ============================================================
    # ✅ v1.3 원본 로직 그대로 (쇼핑파트너센터)
    # ============================================================
    def collect_shopping_partner_data(self):
        wait = WebDriverWait(self.driver, 20)
        report_data = []
        mall_info_data = []
        main_window = self.driver.current_window_handle

        try:
            self.log("    → 쇼핑파트너센터 이동 시작")

            shopping_link = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(@href,'center.shopping.naver.com')]")))
            self.safe_click(shopping_link)
            self.log("    → 쇼핑파트너센터 클릭")
            time.sleep(3)

            all_windows = self.driver.window_handles
            for window in all_windows:
                if window != main_window:
                    self.driver.switch_to.window(window)
                    break
            self.log("    → 새 창으로 전환")
            time.sleep(2)

            try:
                report_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[@href='/report/order']")))
                self.safe_click(report_link)
                self.log("    → 상품리포트 클릭")
            except:
                pass
            time.sleep(2)

            try:
                mobile_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[@href='/report/mobile/order']")))
                self.safe_click(mobile_link)
                self.log("    → 상품클릭리포트-모바일 클릭")
            except:
                self.driver.get("https://center.shopping.naver.com/report/mobile/order")
                self.log("    → 상품클릭리포트-모바일 URL 직접 이동")
            time.sleep(3)

            try:
                iframe = self.driver.find_element(By.CSS_SELECTOR, "iframe")
                self.driver.switch_to.frame(iframe)
                self.log("    → iframe 전환")
            except:
                pass
            time.sleep(2)

            try:
                prod_tab = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(@href,'prod_list.nhn')]")))
                self.safe_click(prod_tab)
                self.log("    → 상품별 탭 클릭")
            except:
                pass
            time.sleep(3)

            try:
                daily_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "li._quick_today a")))
                self.safe_click(daily_btn)
                self.log("    → 일간 선택")
            except:
                pass
            time.sleep(2)

            try:
                search_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "a.btn2.btn2_grn#searchBtn")))
                self.safe_click(search_btn)
                self.log("    → 조회 버튼 클릭")
            except:
                pass
            time.sleep(3)

            self.log("    → 상품클릭리포트-모바일 상품별 데이터 수집 중...")
            headers = ["상품ID", "상품명", "노출수", "클릭수", "클릭율", "적용수수료", "클릭당수수료"]
            report_data.append(headers)

            page_num = 1
            stop_collecting = False
            while not stop_collecting:
                time.sleep(1)

                try:
                    no_data_cell = self.driver.find_element(
                        By.XPATH, "//table[@class='tbl tbl_v3']//tbody//td[contains(text(),'데이터가 없습니다')]")
                    if no_data_cell:
                        self.log("    → '데이터가 없습니다.' 발견, 수집 중단")
                        break
                except:
                    pass

                try:
                    rows = self.driver.find_elements(By.CSS_SELECTOR, "table.tbl tbody tr")
                    page_count = 0

                    for row in rows:
                        try:
                            cells = row.find_elements(By.TAG_NAME, "td")
                            if len(cells) >= 7:
                                first_cell_text = cells[0].text.strip()
                                if "데이터가 없습니다" in first_cell_text:
                                    stop_collecting = True
                                    break

                                row_data = []
                                for i2, cell in enumerate(cells):
                                    text = cell.text.strip()
                                    if i2 == 5:
                                        continue
                                    if i2 == 1:
                                        text = text.replace("상품별 보기", "").strip()
                                    row_data.append(text)

                                if len(row_data) >= 7:
                                    report_data.append(row_data[:7])
                                    page_count += 1
                        except:
                            continue

                    self.log(f"    → 페이지 {page_num}에서 {page_count}개 행 수집")

                except Exception as e:
                    self.log(f"    → 데이터 행 수집 오류: {e}")
                    break

                if stop_collecting:
                    break

                try:
                    next_link = self.driver.find_element(
                        By.XPATH, "//div[@class='paginate paginate_regular']//a[contains(text(),'다음')]")
                    if next_link:
                        self.safe_click(next_link)
                        time.sleep(2)
                        page_num += 1
                    else:
                        break
                except:
                    self.log("    → 마지막 페이지")
                    break

            self.log(f"    → 상품클릭리포트 총 {max(len(report_data)-1,0)}개 행 수집 완료 (헤더 제외)")

            try:
                self.driver.switch_to.default_content()
            except:
                pass

            # 쇼핑몰 정보(홈)
            self.log("    → 홈으로 이동하여 쇼핑몰 정보 수집")
            try:
                home_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[@href='/main']")))
                self.safe_click(home_link)
                self.log("    → 홈 클릭")
            except:
                self.driver.get("https://center.shopping.naver.com/main")
                self.log("    → 홈 URL 직접 이동")
            time.sleep(3)

            try:
                iframe = self.driver.find_element(By.CSS_SELECTOR, "iframe")
                self.driver.switch_to.frame(iframe)
                self.log("    → 홈 iframe 전환")
            except:
                pass
            time.sleep(2)

            mall_info_data.append(["항목", "값"])
            try:
                mall_id = self.driver.find_element(By.CSS_SELECTOR, "li.id span.fb").text.strip()
                mall_info_data.append(["쇼핑몰 ID", mall_id])
            except:
                pass

            try:
                mall_name = self.driver.find_element(By.CSS_SELECTOR, "li.name span:not(strong span)").text.strip()
                mall_info_data.append(["쇼핑몰 명", mall_name])
            except:
                pass

            try:
                mall_type = self.driver.find_element(By.CSS_SELECTOR, "li.type span:not(strong span)").text.strip()
                mall_info_data.append(["쇼핑몰 타입", mall_type])
            except:
                pass

            try:
                mall_grade = self.driver.find_element(By.CSS_SELECTOR, "li.grade span:not(strong span)").text.strip()
                mall_info_data.append(["쇼핑몰 몰등급", mall_grade])
            except:
                pass

            try:
                unread_msg = self.driver.find_element(By.CSS_SELECTOR, "li.msg em.point2").text.strip()
                mall_info_data.append(["안읽은 쪽지", unread_msg])
            except:
                pass

            try:
                recv_msg = self.driver.find_element(
                    By.XPATH, "//li[@class='msg']//span[@class='even']/following-sibling::em").text.strip()
                mall_info_data.append(["받은쪽지", recv_msg])
            except:
                pass

            try:
                clean_violation = self.driver.find_element(By.CSS_SELECTOR, "li.clean em.point2 a").text.strip()
                mall_info_data.append(["클린위반", clean_violation])
            except:
                pass

            try:
                self.driver.switch_to.default_content()
            except:
                pass

            self.driver.close()
            self.log("    → 쇼핑파트너센터 창 닫기")
            self.driver.switch_to.window(main_window)
            self.log("    → 원래 창으로 복귀")
            time.sleep(1)

            return report_data, mall_info_data

        except Exception as e:
            self.log(f"    쇼핑파트너 데이터 수집 오류: {e}")
            try:
                all_windows = self.driver.window_handles
                for window in all_windows:
                    if window != main_window:
                        self.driver.switch_to.window(window)
                        self.driver.close()
                self.driver.switch_to.window(main_window)
            except:
                pass
            return report_data, mall_info_data

    # ✅ 저장은 항상 "정리되는곳(DEST_SPREADSHEET_ID)"으로!
    def save_to_google_sheets(self, store_name, data, report_data=None, mall_info_data=None, channel_data=None):
        try:
            if not self.dest_spreadsheet:
                raise Exception("저장 문서(dest_spreadsheet)가 연결되지 않았습니다.")

            max_rows = max(len(data) if data else 0,
                           len(report_data) if report_data else 0,
                           len(mall_info_data) if mall_info_data else 0,
                           len(channel_data) if channel_data else 0)
            max_rows = max(max_rows + 100, 1000)
            max_cols = 35  # S열(19) + 전체채널(2열) + 여유

            try:
                worksheet = self.dest_spreadsheet.worksheet(store_name)
                self.log(f"    → (저장문서) 기존 시트 '{store_name}' 찾음")
                if worksheet.row_count < max_rows or worksheet.col_count < max_cols:
                    worksheet.resize(rows=max_rows, cols=max_cols)
                    self.log(f"    → 시트 크기 확장: {max_rows}행 x {max_cols}열")
            except gspread.exceptions.WorksheetNotFound:
                worksheet = self.dest_spreadsheet.add_worksheet(title=store_name, rows=max_rows, cols=max_cols)
                self.log(f"    → (저장문서) 새 시트 '{store_name}' 생성")

            worksheet.clear()

            if data:
                worksheet.update(range_name='A1', values=data)
                self.log(f"    → 마케팅분석 {len(data)}개 행 저장 완료 (A~G열)")

            if report_data and len(report_data) > 0:
                worksheet.update(range_name='I1', values=report_data)
                self.log(f"    → 상품클릭리포트 {len(report_data)}개 행 저장 완료 (I열~)")

            if mall_info_data and len(mall_info_data) > 0:
                worksheet.update(range_name='Q1', values=mall_info_data)
                self.log(f"    → 쇼핑몰 정보 {len(mall_info_data)}개 행 저장 완료 (Q열~)")

            # 전체채널 데이터 저장 (S열부터) - 신규 추가
            if channel_data and len(channel_data) > 0:
                worksheet.update(range_name='S1', values=channel_data)
                self.log(f"    → 전체채널 {len(channel_data)}개 행 저장 완료 (S열~)")

        except Exception as e:
            self.log(f"    구글 시트 저장 오류: {e}")
            raise

    def do_logout(self):
        try:
            wait = WebDriverWait(self.driver, 10)
            try:
                logout_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(),'로그아웃')]")))
                self.safe_click(logout_link)
            except:
                self.driver.get("https://nid.naver.com/nidlogin.logout?returl=https://sell.smartstore.naver.com/")
            time.sleep(2)
        except:
            self.driver.get("https://nid.naver.com/nidlogin.logout?returl=https://sell.smartstore.naver.com/")
            time.sleep(2)


def main():
    root = tk.Tk()
    app = SmartStoreMarketing(root)
    root.mainloop()


if __name__ == "__main__":
    main()
