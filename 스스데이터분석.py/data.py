# -*- coding: utf-8 -*-
"""
네이버 스마트스토어 로그인 → 마케팅분석 데이터 → 구글시트 저장
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import threading
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException
import subprocess
import os
import json

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials


class SmartStoreMarketing:
    def __init__(self, root):
        self.root = root
        self.root.title("스마트스토어 마케팅분석 수집기 v1.1")
        self.root.geometry("900x850")
        
        self.accounts = []
        self.driver = None
        self.chrome_process = None
        self.is_running = False
        self.current_account_index = 0
        
        # 구글 시트 설정
        self.json_path = ""
        self.spreadsheet_id = ""
        self.gc = None
        self.spreadsheet = None
        
        # 설정 파일 경로
        self.config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        self.load_config()
        
        self.setup_ui()
        self.root.after(500, self.auto_start_chrome)
        
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # ========== 구글시트 설정 ==========
        google_frame = ttk.LabelFrame(main_frame, text="구글시트 설정", padding="10")
        google_frame.pack(fill=tk.X, pady=(0, 10))
        
        # JSON 파일 선택
        json_row = ttk.Frame(google_frame)
        json_row.pack(fill=tk.X, pady=3)
        ttk.Label(json_row, text="서비스계정 JSON:", width=15).pack(side=tk.LEFT)
        self.json_path_var = tk.StringVar(value=self.json_path)
        ttk.Entry(json_row, textvariable=self.json_path_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(json_row, text="찾기", command=self.browse_json).pack(side=tk.LEFT)
        
        # 구글시트 ID 입력
        sheet_row = ttk.Frame(google_frame)
        sheet_row.pack(fill=tk.X, pady=3)
        ttk.Label(sheet_row, text="구글시트 ID:", width=15).pack(side=tk.LEFT)
        self.sheet_id_var = tk.StringVar(value=self.spreadsheet_id)
        ttk.Entry(sheet_row, textvariable=self.sheet_id_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(sheet_row, text="연결", command=self.connect_google_sheets).pack(side=tk.LEFT)
        
        # 연결 상태
        status_row = ttk.Frame(google_frame)
        status_row.pack(fill=tk.X, pady=3)
        self.google_status = ttk.Label(status_row, text="● 구글시트 미연결", foreground="red", font=('', 10))
        self.google_status.pack(side=tk.LEFT)
        
        # 도움말
        help_text = "* 구글시트 ID는 URL에서 /d/ 뒤의 긴 문자열입니다\n  예: https://docs.google.com/spreadsheets/d/여기가ID/edit"
        ttk.Label(google_frame, text=help_text, foreground="gray", font=('', 9)).pack(anchor=tk.W)
        
        # ========== Chrome 상태 ==========
        top_frame = ttk.LabelFrame(main_frame, text="Chrome 상태", padding="5")
        top_frame.pack(fill=tk.X, pady=(0, 10))
        
        status_frame = ttk.Frame(top_frame)
        status_frame.pack(fill=tk.X)
        
        self.chrome_status = ttk.Label(status_frame, text="● Chrome 시작 중...", foreground="orange", font=('', 10))
        self.chrome_status.pack(side=tk.LEFT)
        
        ttk.Button(status_frame, text="Chrome 재시작", command=self.reconnect_chrome).pack(side=tk.RIGHT)
        
        # 계정 입력
        input_frame = ttk.LabelFrame(main_frame, text="계정 입력", padding="10")
        input_frame.pack(fill=tk.X, pady=(0, 10))
        
        input_row = ttk.Frame(input_frame)
        input_row.pack(fill=tk.BOTH, expand=True)
        
        # 아이디
        id_frame = ttk.Frame(input_row)
        id_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        ttk.Label(id_frame, text="아이디 (한 줄에 하나씩)", font=('', 10, 'bold')).pack(anchor=tk.W)
        self.id_text = scrolledtext.ScrolledText(id_frame, height=5, width=25)
        self.id_text.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 비밀번호
        pw_frame = ttk.Frame(input_row)
        pw_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 5))
        ttk.Label(pw_frame, text="비밀번호 (한 줄에 하나씩)", font=('', 10, 'bold')).pack(anchor=tk.W)
        self.pw_text = scrolledtext.ScrolledText(pw_frame, height=5, width=25)
        self.pw_text.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 버튼
        btn_frame = ttk.Frame(input_row)
        btn_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(5, 0))
        ttk.Label(btn_frame, text="").pack(pady=5)
        ttk.Button(btn_frame, text="▶ 계정 추가", command=self.apply_accounts).pack(fill=tk.X, ipady=8, pady=3)
        ttk.Button(btn_frame, text="입력창 비우기", command=self.clear_input).pack(fill=tk.X, pady=3)
        
        self.count_label = ttk.Label(btn_frame, text="0개 / 0개", foreground="blue")
        self.count_label.pack(pady=(10, 0))
        
        self.id_text.bind('<KeyRelease>', self.update_counts)
        self.pw_text.bind('<KeyRelease>', self.update_counts)
        self.id_text.bind('<<Paste>>', lambda e: self.root.after(100, self.update_counts))
        self.pw_text.bind('<<Paste>>', lambda e: self.root.after(100, self.update_counts))
        
        # 계정 목록
        list_frame = ttk.LabelFrame(main_frame, text="등록된 계정", padding="10")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        columns = ("no", "id", "status")
        self.account_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=5)
        self.account_tree.heading("no", text="번호")
        self.account_tree.heading("id", text="아이디")
        self.account_tree.heading("status", text="상태")
        self.account_tree.column("no", width=50, anchor=tk.CENTER)
        self.account_tree.column("id", width=200)
        self.account_tree.column("status", width=200, anchor=tk.CENTER)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.account_tree.yview)
        self.account_tree.configure(yscrollcommand=scrollbar.set)
        self.account_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        acc_btn_frame = ttk.Frame(list_frame)
        acc_btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))
        self.account_count = ttk.Label(acc_btn_frame, text="총 0개 계정", font=('', 10, 'bold'))
        self.account_count.pack(side=tk.LEFT)
        ttk.Button(acc_btn_frame, text="전체 삭제", command=self.clear_accounts).pack(side=tk.RIGHT)
        
        # 실행 버튼
        exec_frame = ttk.Frame(main_frame)
        exec_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.exec_btn = ttk.Button(exec_frame, text="▶ 전체 계정 자동 실행", command=self.start_all)
        self.exec_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=10, padx=(0, 5))
        
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
        
    def load_config(self):
        """설정 파일 불러오기"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.json_path = config.get('json_path', '')
                    self.spreadsheet_id = config.get('spreadsheet_id', '')
        except:
            pass
            
    def save_config(self):
        """설정 파일 저장"""
        try:
            config = {
                'json_path': self.json_path_var.get(),
                'spreadsheet_id': self.sheet_id_var.get()
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except:
            pass
            
    def browse_json(self):
        """JSON 파일 선택"""
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
        
    def update_counts(self, event=None):
        id_lines = [l.strip() for l in self.id_text.get("1.0", tk.END).strip().split('\n') if l.strip()]
        pw_lines = [l.strip() for l in self.pw_text.get("1.0", tk.END).strip().split('\n') if l.strip()]
        self.count_label.configure(text=f"ID: {len(id_lines)}개 / PW: {len(pw_lines)}개")
        
        if len(id_lines) == len(pw_lines) and len(id_lines) > 0:
            self.count_label.configure(foreground="green")
        elif len(id_lines) != len(pw_lines) and (len(id_lines) > 0 or len(pw_lines) > 0):
            self.count_label.configure(foreground="red")
        else:
            self.count_label.configure(foreground="blue")
            
    def apply_accounts(self):
        id_lines = [l.strip() for l in self.id_text.get("1.0", tk.END).strip().split('\n') if l.strip()]
        pw_lines = [l.strip() for l in self.pw_text.get("1.0", tk.END).strip().split('\n') if l.strip()]
        
        if not id_lines or not pw_lines:
            messagebox.showwarning("경고", "아이디와 비밀번호를 입력하세요.")
            return
            
        if len(id_lines) != len(pw_lines):
            messagebox.showerror("오류", f"아이디({len(id_lines)}개)와 비밀번호({len(pw_lines)}개) 개수가 다릅니다!")
            return
            
        added = 0
        for user_id, password in zip(id_lines, pw_lines):
            if not any(acc['id'] == user_id for acc in self.accounts):
                self.accounts.append({'id': user_id, 'pw': password, 'status': '대기'})
                added += 1
                
        self.refresh_account_list()
        self.log(f"{added}개 계정 추가됨")
        if added > 0:
            messagebox.showinfo("완료", f"{added}개 계정 추가됨")
            
    def clear_input(self):
        self.id_text.delete("1.0", tk.END)
        self.pw_text.delete("1.0", tk.END)
        self.update_counts()
        
    def clear_accounts(self):
        if self.accounts and messagebox.askyesno("확인", "모든 계정을 삭제하시겠습니까?"):
            self.accounts = []
            self.current_account_index = 0
            self.refresh_account_list()
            self.log("전체 계정 삭제됨")
            
    def refresh_account_list(self):
        for item in self.account_tree.get_children():
            self.account_tree.delete(item)
        for i, acc in enumerate(self.accounts, 1):
            self.account_tree.insert("", tk.END, values=(i, acc['id'], acc['status']))
        self.account_count.configure(text=f"총 {len(self.accounts)}개 계정")
        
    def update_account_status(self, user_id, status):
        for acc in self.accounts:
            if acc['id'] == user_id:
                acc['status'] = status
                break
        self.root.after(0, self.refresh_account_list)
        
    def auto_start_chrome(self):
        thread = threading.Thread(target=self._start_chrome_thread)
        thread.daemon = True
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
        thread = threading.Thread(target=self._start_chrome_thread)
        thread.daemon = True
        thread.start()
        
    def connect_google_sheets(self):
        """구글 시트 연결"""
        thread = threading.Thread(target=self._connect_google_sheets_thread)
        thread.daemon = True
        thread.start()
        
    def _connect_google_sheets_thread(self):
        try:
            json_path = self.json_path_var.get().strip()
            spreadsheet_id = self.sheet_id_var.get().strip()
            
            if not json_path:
                self.root.after(0, lambda: messagebox.showwarning("경고", "서비스계정 JSON 파일을 선택하세요."))
                return
                
            if not spreadsheet_id:
                self.root.after(0, lambda: messagebox.showwarning("경고", "구글시트 ID를 입력하세요."))
                return
                
            if not os.path.exists(json_path):
                self.root.after(0, lambda: self.google_status.configure(text="● JSON 파일 없음", foreground="red"))
                self.log(f"파일 없음: {json_path}")
                return
            
            self.log("구글 시트 연결 중...")
            self.root.after(0, lambda: self.google_status.configure(text="● 연결 중...", foreground="orange"))
            
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            
            credentials = Credentials.from_service_account_file(json_path, scopes=scopes)
            self.gc = gspread.authorize(credentials)
            self.spreadsheet = self.gc.open_by_key(spreadsheet_id)
            
            # 설정 저장
            self.save_config()
            
            self.root.after(0, lambda: self.google_status.configure(
                text=f"● 연결됨: {self.spreadsheet.title}", foreground="green"))
            self.log(f"구글 시트 연결 완료: {self.spreadsheet.title}")
            
        except gspread.exceptions.SpreadsheetNotFound:
            self.root.after(0, lambda: self.google_status.configure(text="● 시트를 찾을 수 없음", foreground="red"))
            self.log("구글 시트를 찾을 수 없습니다. ID를 확인하세요.")
            self.root.after(0, lambda: messagebox.showerror("오류", "구글 시트를 찾을 수 없습니다.\n\n1. 시트 ID가 맞는지 확인\n2. 서비스 계정 이메일에 시트 공유 필요"))
        except Exception as e:
            self.root.after(0, lambda: self.google_status.configure(
                text="● 구글시트 연결 실패", foreground="red"))
            self.log(f"구글 시트 연결 실패: {e}")
            
    def safe_click(self, element):
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.3)
            element.click()
        except ElementClickInterceptedException:
            self.driver.execute_script("arguments[0].click();", element)
            
    def start_all(self):
        """전체 계정 자동 실행"""
        if not self.driver:
            messagebox.showwarning("경고", "Chrome이 연결되지 않았습니다.")
            return
            
        if not self.spreadsheet:
            messagebox.showwarning("경고", "구글 시트가 연결되지 않았습니다.\n먼저 '연결' 버튼을 클릭하세요.")
            return
            
        if not self.accounts:
            messagebox.showwarning("경고", "등록된 계정이 없습니다.")
            return
            
        self.is_running = True
        self.exec_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        
        thread = threading.Thread(target=self._run_all_accounts)
        thread.daemon = True
        thread.start()
        
    def stop_process(self):
        self.is_running = False
        self.log("중지 요청됨...")
        
    def _run_all_accounts(self):
        """전체 계정 순차 처리"""
        total = len(self.accounts)
        success = 0
        failed = 0
        
        for i, account in enumerate(self.accounts):
            if not self.is_running:
                self.log("사용자에 의해 중지됨")
                break
                
            user_id = account['id']
            password = account['pw']
            
            self.root.after(0, lambda p=(i/total)*100: self.progress_var.set(p))
            self.root.after(0, lambda s=f"진행: {i+1}/{total} - {user_id}": 
                          self.progress_label.configure(text=s))
            
            self.log(f"\n{'='*50}")
            self.log(f"[{i+1}/{total}] {user_id} 처리 시작")
            self.update_account_status(user_id, "진행중...")
            
            try:
                # 1. 로그인
                if not self.do_login(user_id, password):
                    raise Exception("로그인 실패")
                self.log(f"  ✓ 로그인 성공")

                time.sleep(2)

                # 2. 스토어 이름 가져오기
                store_name = self.get_store_name()
                self.log(f"  ✓ 스토어 이름: {store_name}")

                # 3. 마케팅분석 데이터 수집
                data = self.collect_marketing_data()
                self.log(f"  ✓ 마케팅분석 데이터 수집: {len(data)-1}개 행")

                # 4. 쇼핑파트너센터 데이터 수집 (상품클릭리포트 + 쇼핑몰정보)
                report_data, mall_info_data = self.collect_shopping_partner_data()
                self.log(f"  ✓ 상품클릭리포트 수집: {len(report_data)-1}개 행")
                self.log(f"  ✓ 쇼핑몰정보 수집: {len(mall_info_data)-1}개 항목")

                # 5. 구글 시트에 저장
                if data or report_data or mall_info_data:
                    self.save_to_google_sheets(store_name, data, report_data, mall_info_data)
                    self.log(f"  ✓ 구글 시트 저장 완료")

                # 6. 로그아웃
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
            
        self.root.after(0, lambda: self.progress_var.set(100))
        self.root.after(0, lambda: self.progress_label.configure(
            text=f"완료! 성공: {success}, 실패: {failed}"))
        self.root.after(0, lambda: self.exec_btn.configure(state=tk.NORMAL))
        self.root.after(0, lambda: self.stop_btn.configure(state=tk.DISABLED))
        self.is_running = False
        self.log(f"\n전체 완료 - 성공: {success}, 실패: {failed}")
        
    def do_login(self, user_id, password):
        """네이버 스마트스토어 로그인"""
        try:
            self.driver.get("https://sell.smartstore.naver.com/#/home/about")
            time.sleep(2)
            
            wait = WebDriverWait(self.driver, 15)
            
            # 이미 로그인 상태면 로그아웃
            if "dashboard" in self.driver.current_url:
                self.do_logout()
                time.sleep(2)
                self.driver.get("https://sell.smartstore.naver.com/#/home/about")
                time.sleep(2)
            
            # 로그인 버튼 클릭
            try:
                login_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-login")))
                self.safe_click(login_btn)
                time.sleep(2)
            except:
                pass
            
            # 아이디 입력
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
            
            # 비밀번호 입력
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
            
            # 로그인 제출
            try:
                login_submit = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], button.Button_btn__VF3g3")
                self.safe_click(login_submit)
            except:
                pw_input.send_keys(Keys.ENTER)
            
            time.sleep(3)
            
            # 대시보드 확인
            try:
                wait.until(lambda d: "dashboard" in d.current_url)
                return True
            except:
                time.sleep(5)
                if "dashboard" in self.driver.current_url:
                    return True
                    
            # 캡차 대기
            if "nid.naver.com" in self.driver.current_url:
                self.log("  ⚠ 캡차 필요 - 20초 대기")
                time.sleep(20)
                if "dashboard" in self.driver.current_url:
                    return True
                    
            return False
            
        except Exception as e:
            self.log(f"  로그인 오류: {e}")
            return False
            
    def get_store_name(self):
        """스토어 이름 가져오기"""
        try:
            wait = WebDriverWait(self.driver, 10)
            
            # 대시보드로 이동
            self.driver.get("https://sell.smartstore.naver.com/#/home/dashboard")
            time.sleep(2)
            
            # span.shop 요소에서 스토어 이름 추출
            store_elem = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "span.shop")))
            store_name = store_elem.text.strip()
            
            return store_name if store_name else "Unknown"
            
        except Exception as e:
            self.log(f"  스토어 이름 가져오기 실패: {e}")
            return "Unknown"
            
    def collect_marketing_data(self):
        """마케팅분석 데이터 수집"""
        wait = WebDriverWait(self.driver, 20)
        all_data = []

        try:
            # 1. 데이터분석 메뉴 클릭
            self.log("    → 데이터분석 메뉴 클릭")
            time.sleep(2)

            # 여러 셀렉터 시도
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

            # 2. 마케팅분석 클릭
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
                # 직접 URL 이동
                self.driver.get("https://sell.smartstore.naver.com/#/bizadvisor/marketing")
                self.log("    → 마케팅분석 URL 직접 이동")
            time.sleep(3)

            # 2-1. 상품노출성과 탭 클릭
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
                # 직접 URL 이동
                self.driver.get("https://sell.smartstore.naver.com/#/bizadvisor/marketing/expose")
                self.log("    → 상품노출성과 URL 직접 이동")
            time.sleep(3)

            # 3. iframe으로 전환
            self.log("    → iframe 전환")
            try:
                iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe#__delegate")))
                self.driver.switch_to.frame(iframe)
                self.log("    → iframe 전환 완료")
            except Exception as e:
                self.log(f"    → iframe 전환 실패, 계속 진행: {e}")
            time.sleep(2)

            # 4. 날짜 선택 - 캘린더 팝업 열기
            self.log("    → 날짜 선택 시작")
            try:
                # 날짜 선택 버튼 클릭 (캘린더 팝업 열기)
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
                self.log(f"    → 날짜 선택 실패: {e}, URL 파라미터 방식 시도")
                # iframe에서 나와서 URL로 시도
                self.driver.switch_to.default_content()
                from datetime import timedelta
                yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                date_url = f"https://sell.smartstore.naver.com/#/bizadvisor/marketing/expose?periodType=DAY&startDate={yesterday}&endDate={yesterday}"
                self.driver.get(date_url)
                time.sleep(5)
                # 다시 iframe 전환
                try:
                    iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe#__delegate")))
                    self.driver.switch_to.frame(iframe)
                except:
                    pass

            # 5. 테이블 로딩 대기
            self.log("    → 테이블 데이터 수집 중...")
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.tbl_list")))
            time.sleep(2)

            # 헤더 추가
            headers = ["상품명", "상품ID", "채널그룹", "채널명", "키워드", "평균노출순위", "유입수"]
            all_data.append(headers)

            # 전체 행 추가 (total_row)
            try:
                total_row = self.driver.find_element(By.CSS_SELECTOR, "tr.total_row")
                total_cells = total_row.find_elements(By.TAG_NAME, "td")
                if len(total_cells) >= 7:
                    total_data = [cell.text.strip() for cell in total_cells[:7]]
                    all_data.append(total_data)
                    self.log(f"    → 전체 행: {total_data}")
            except Exception as e:
                self.log(f"    → 전체 행 없음: {e}")

            # 페이지네이션 처리
            page_num = 1
            stop_collecting = False  # 유입수 0 발견시 중단 플래그

            while not stop_collecting:
                self.log(f"    → 페이지 {page_num} 수집 중...")
                time.sleep(1)

                # 현재 페이지 데이터 수집
                rows = self.driver.find_elements(By.CSS_SELECTOR, "table.tbl_list tbody tr:not(.total_row)")
                self.log(f"    → 페이지 {page_num}에서 {len(rows)}개 행 발견")

                page_count = 0
                for row in rows:
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if len(cells) >= 7:
                            # 유입수 확인 (7번째 열, 인덱스 6)
                            inflow_text = cells[6].text.strip()
                            try:
                                inflow = int(inflow_text.replace(",", ""))
                                # 유입수가 0이면 수집 중단
                                if inflow == 0:
                                    self.log(f"    → 유입수 0 발견, 수집 중단")
                                    stop_collecting = True
                                    break
                                # 유입수가 1 이상인 행만 수집
                                if inflow >= 1:
                                    row_data = []
                                    for j, cell in enumerate(cells[:7]):
                                        if j == 0:  # 상품명 (링크 텍스트)
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
                    except Exception as e:
                        continue

                self.log(f"    → 페이지 {page_num}에서 유입수>=1인 행: {page_count}개")

                # 유입수 0 발견시 중단
                if stop_collecting:
                    break

                # 다음 페이지 확인
                try:
                    # disabled가 아닌 next 버튼 찾기
                    next_btn = self.driver.find_element(By.CSS_SELECTOR, "li.btn.next:not(.disabled) a")
                    if next_btn:
                        self.safe_click(next_btn)
                        time.sleep(3)
                        page_num += 1
                    else:
                        break
                except:
                    # 다음 페이지 없음
                    self.log("    → 마지막 페이지")
                    break

            # iframe에서 나오기
            self.driver.switch_to.default_content()

            self.log(f"    → 총 {len(all_data)-1}개 행 수집 완료 (헤더 제외)")
            return all_data

        except Exception as e:
            self.log(f"    데이터 수집 오류: {e}")
            import traceback
            self.log(f"    상세 오류: {traceback.format_exc()}")
            # iframe에서 나오기
            try:
                self.driver.switch_to.default_content()
            except:
                pass
            return all_data
            
    def save_to_google_sheets(self, store_name, data, report_data=None, mall_info_data=None):
        """구글 시트에 저장 (기존 시트에 추가)"""
        try:
            # 기존 시트 확인
            try:
                worksheet = self.spreadsheet.worksheet(store_name)
                self.log(f"    → 기존 시트 '{store_name}' 찾음")
            except gspread.exceptions.WorksheetNotFound:
                # 시트가 없으면 생성
                worksheet = self.spreadsheet.add_worksheet(title=store_name, rows=1000, cols=10)
                self.log(f"    → 새 시트 '{store_name}' 생성")

            # 기존 데이터 삭제 후 새로 저장
            worksheet.clear()

            current_row = 0

            # 1. 마케팅분석 데이터 저장 (1행부터)
            if data:
                worksheet.update(range_name='A1', values=data)
                current_row = len(data)
                self.log(f"    → 마케팅분석 {len(data)}개 행 저장 완료 (1행~{current_row}행)")

            # 2. 상품클릭리포트 데이터 저장 (마케팅 데이터 끝 + 2행)
            if report_data and len(report_data) > 0:
                report_start_row = current_row + 2
                worksheet.update(range_name=f'A{report_start_row}', values=report_data)
                current_row = report_start_row + len(report_data) - 1
                self.log(f"    → 상품클릭리포트 {len(report_data)}개 행 저장 완료 ({report_start_row}행~)")

            # 3. 쇼핑몰 정보 데이터 저장 (상품클릭리포트 끝 + 2행)
            if mall_info_data and len(mall_info_data) > 0:
                mall_start_row = current_row + 2
                worksheet.update(range_name=f'A{mall_start_row}', values=mall_info_data)
                self.log(f"    → 쇼핑몰 정보 {len(mall_info_data)}개 행 저장 완료 ({mall_start_row}행~)")

        except Exception as e:
            self.log(f"    구글 시트 저장 오류: {e}")
            raise
            
    def collect_shopping_partner_data(self):
        """쇼핑파트너센터 상품클릭리포트 + 쇼핑몰정보 데이터 수집"""
        wait = WebDriverWait(self.driver, 20)
        report_data = []  # 상품클릭리포트
        mall_info_data = []  # 쇼핑몰 정보
        main_window = self.driver.current_window_handle

        try:
            self.log("    → 쇼핑파트너센터 이동 시작")

            # 1. 쇼핑파트너센터 링크 클릭 (새 창 열림)
            shopping_link = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(@href,'center.shopping.naver.com')]")))
            self.safe_click(shopping_link)
            self.log("    → 쇼핑파트너센터 클릭")
            time.sleep(3)

            # 2. 새 창으로 전환
            all_windows = self.driver.window_handles
            for window in all_windows:
                if window != main_window:
                    self.driver.switch_to.window(window)
                    break
            self.log("    → 새 창으로 전환")
            time.sleep(2)

            # 3. 상품리포트 메뉴 클릭
            try:
                report_link = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//a[@href='/report/order']")))
                self.safe_click(report_link)
                self.log("    → 상품리포트 클릭")
            except:
                pass
            time.sleep(2)

            # 4. 상품클릭리포트-모바일 클릭
            try:
                mobile_link = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//a[@href='/report/mobile/order']")))
                self.safe_click(mobile_link)
                self.log("    → 상품클릭리포트-모바일 클릭")
            except:
                # 직접 URL 이동
                self.driver.get("https://center.shopping.naver.com/report/mobile/order")
                self.log("    → 상품클릭리포트-모바일 URL 직접 이동")
            time.sleep(3)

            # 5. iframe 확인 및 전환
            try:
                iframe = self.driver.find_element(By.CSS_SELECTOR, "iframe")
                self.driver.switch_to.frame(iframe)
                self.log("    → iframe 전환")
            except:
                pass
            time.sleep(2)

            # 6. 상품별 탭 클릭
            try:
                prod_tab = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//a[contains(@href,'prod_list.nhn')]")))
                self.safe_click(prod_tab)
                self.log("    → 상품별 탭 클릭")
            except:
                pass
            time.sleep(3)

            # 7. 조회 버튼 클릭
            try:
                search_btn = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "a.btn2.btn2_grn#searchBtn")))
                self.safe_click(search_btn)
                self.log("    → 조회 버튼 클릭")
            except:
                pass
            time.sleep(3)

            # 8. 테이블 데이터 수집 (페이지네이션 처리)
            self.log("    → 상품클릭리포트-모바일 상품별 데이터 수집 중...")

            # 헤더 추가
            headers = ["상품ID", "상품명", "노출수", "클릭수", "클릭율", "적용수수료", "클릭당수수료"]
            report_data.append(headers)

            # 합계 행 수집 (tfoot) - 첫 페이지에서만
            try:
                tfoot = self.driver.find_element(By.CSS_SELECTOR, "table.tbl tfoot tr")
                tfoot_cells = tfoot.find_elements(By.TAG_NAME, "td")
                th_cell = tfoot.find_element(By.TAG_NAME, "th")
                if tfoot_cells:
                    total_data = [th_cell.text.strip()]  # "합계 (검색결과 : N건)"
                    for cell in tfoot_cells:
                        text = cell.text.strip()
                        if text and text != "":  # division 셀 제외
                            total_data.append(text)
                    report_data.append(total_data)
                    self.log(f"    → 합계 행: {total_data}")
            except Exception as e:
                self.log(f"    → 합계 행 없음: {e}")

            # 페이지네이션 처리
            page_num = 1
            stop_collecting = False

            while not stop_collecting:
                self.log(f"    → 페이지 {page_num} 수집 중...")
                time.sleep(1)

                # "데이터가 없습니다." 체크
                try:
                    no_data_cell = self.driver.find_element(By.XPATH, "//table[@class='tbl tbl_v3']//tbody//td[contains(text(),'데이터가 없습니다')]")
                    if no_data_cell:
                        self.log(f"    → '데이터가 없습니다.' 발견, 수집 중단")
                        stop_collecting = True
                        break
                except:
                    pass  # 데이터가 있는 경우

                # 데이터 행 수집 (tbody)
                try:
                    rows = self.driver.find_elements(By.CSS_SELECTOR, "table.tbl tbody tr")
                    page_count = 0

                    for row in rows:
                        try:
                            cells = row.find_elements(By.TAG_NAME, "td")
                            if len(cells) >= 7:
                                # "데이터가 없습니다." 행 스킵
                                first_cell_text = cells[0].text.strip()
                                if "데이터가 없습니다" in first_cell_text:
                                    self.log(f"    → '데이터가 없습니다.' 발견, 수집 중단")
                                    stop_collecting = True
                                    break

                                row_data = []
                                for i, cell in enumerate(cells):
                                    text = cell.text.strip()
                                    # division 셀(빈 셀) 제외
                                    if i == 5:  # division 열 스킵
                                        continue
                                    # 상품명에서 불필요한 텍스트 제거
                                    if i == 1:
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

                # 수집 중단 플래그 체크
                if stop_collecting:
                    break

                # 다음 페이지 확인 및 이동
                try:
                    # "다음 ›" 링크 찾기
                    next_link = self.driver.find_element(By.XPATH, "//div[@class='paginate paginate_regular']//a[contains(text(),'다음')]")
                    if next_link:
                        self.safe_click(next_link)
                        time.sleep(2)
                        page_num += 1
                    else:
                        break
                except:
                    # 다음 페이지 없음
                    self.log("    → 마지막 페이지")
                    break

            self.log(f"    → 상품클릭리포트 총 {len(report_data)-1}개 행 수집 완료 (헤더 제외)")

            # 6. iframe에서 나오기
            try:
                self.driver.switch_to.default_content()
            except:
                pass

            # ========== 7. 홈으로 이동하여 쇼핑몰 정보 수집 ==========
            self.log("    → 홈으로 이동하여 쇼핑몰 정보 수집")
            try:
                home_link = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//a[@href='/main']")))
                self.safe_click(home_link)
                self.log("    → 홈 클릭")
            except:
                self.driver.get("https://center.shopping.naver.com/main")
                self.log("    → 홈 URL 직접 이동")
            time.sleep(3)

            # iframe 전환 (홈 페이지도 iframe 안에 있을 수 있음)
            try:
                iframe = self.driver.find_element(By.CSS_SELECTOR, "iframe")
                self.driver.switch_to.frame(iframe)
                self.log("    → 홈 iframe 전환")
            except:
                pass
            time.sleep(2)

            # 쇼핑몰 정보 수집
            mall_info_data.append(["항목", "값"])  # 헤더

            try:
                # 쇼핑몰 ID
                mall_id = self.driver.find_element(By.CSS_SELECTOR, "li.id span.fb").text.strip()
                mall_info_data.append(["쇼핑몰 ID", mall_id])

                # 쇼핑몰 명
                mall_name = self.driver.find_element(By.CSS_SELECTOR, "li.name span:not(strong span)").text.strip()
                mall_info_data.append(["쇼핑몰 명", mall_name])

                # 쇼핑몰 타입
                mall_type = self.driver.find_element(By.CSS_SELECTOR, "li.type span:not(strong span)").text.strip()
                mall_info_data.append(["쇼핑몰 타입", mall_type])

                # 쇼핑몰 몰등급
                mall_grade = self.driver.find_element(By.CSS_SELECTOR, "li.grade span:not(strong span)").text.strip()
                mall_info_data.append(["쇼핑몰 몰등급", mall_grade])

                # 안읽은 쪽지
                unread_msg = self.driver.find_element(By.CSS_SELECTOR, "li.msg em.point2").text.strip()
                mall_info_data.append(["안읽은 쪽지", unread_msg])

                # 받은쪽지
                recv_msg = self.driver.find_element(By.XPATH, "//li[@class='msg']//span[@class='even']/following-sibling::em").text.strip()
                mall_info_data.append(["받은쪽지", recv_msg])

                # 클린위반
                clean_violation = self.driver.find_element(By.CSS_SELECTOR, "li.clean em.point2 a").text.strip()
                mall_info_data.append(["클린위반", clean_violation])

                self.log(f"    → 쇼핑몰 정보 수집 완료: {mall_name}")

            except Exception as e:
                self.log(f"    → 쇼핑몰 정보 수집 오류: {e}")

            # iframe에서 나오기
            try:
                self.driver.switch_to.default_content()
            except:
                pass

            # 8. 새 창 닫기
            self.driver.close()
            self.log("    → 쇼핑파트너센터 창 닫기")

            # 9. 원래 창으로 복귀
            self.driver.switch_to.window(main_window)
            self.log("    → 원래 창으로 복귀")
            time.sleep(1)

            return report_data, mall_info_data

        except Exception as e:
            self.log(f"    쇼핑파트너 데이터 수집 오류: {e}")
            import traceback
            self.log(f"    상세 오류: {traceback.format_exc()}")

            # 새 창 닫기 시도
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

    def do_logout(self):
        """로그아웃"""
        try:
            wait = WebDriverWait(self.driver, 10)
            
            try:
                logout_link = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//a[contains(text(),'로그아웃')]")))
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