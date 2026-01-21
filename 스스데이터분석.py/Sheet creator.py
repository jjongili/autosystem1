# -*- coding: utf-8 -*-
"""
스마트스토어 로그인 → 스토어 이름으로 구글시트 시트 생성
(시트 생성만 하는 용도)
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
from selenium.common.exceptions import ElementClickInterceptedException
import subprocess
import os
import json

import gspread
from google.oauth2.service_account import Credentials


class SheetCreator:
    def __init__(self, root):
        self.root = root
        self.root.title("구글시트 스토어명 시트 생성기 v1.1")
        self.root.geometry("800x750")
        
        self.accounts = []
        self.driver = None
        self.is_running = False
        
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
        
        id_frame = ttk.Frame(input_row)
        id_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        ttk.Label(id_frame, text="아이디 (한 줄에 하나씩)", font=('', 10, 'bold')).pack(anchor=tk.W)
        self.id_text = scrolledtext.ScrolledText(id_frame, height=6, width=25)
        self.id_text.pack(fill=tk.BOTH, expand=True, pady=5)
        
        pw_frame = ttk.Frame(input_row)
        pw_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 5))
        ttk.Label(pw_frame, text="비밀번호 (한 줄에 하나씩)", font=('', 10, 'bold')).pack(anchor=tk.W)
        self.pw_text = scrolledtext.ScrolledText(pw_frame, height=6, width=25)
        self.pw_text.pack(fill=tk.BOTH, expand=True, pady=5)
        
        btn_frame = ttk.Frame(input_row)
        btn_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(5, 0))
        ttk.Label(btn_frame, text="").pack(pady=5)
        ttk.Button(btn_frame, text="▶ 계정 추가", command=self.apply_accounts).pack(fill=tk.X, ipady=8, pady=3)
        
        self.count_label = ttk.Label(btn_frame, text="0개 / 0개", foreground="blue")
        self.count_label.pack(pady=(10, 0))
        
        self.id_text.bind('<KeyRelease>', self.update_counts)
        self.pw_text.bind('<KeyRelease>', self.update_counts)
        self.id_text.bind('<<Paste>>', lambda e: self.root.after(100, self.update_counts))
        self.pw_text.bind('<<Paste>>', lambda e: self.root.after(100, self.update_counts))
        
        # 계정 목록
        list_frame = ttk.LabelFrame(main_frame, text="등록된 계정", padding="10")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        columns = ("no", "id", "store_name", "status")
        self.account_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=6)
        self.account_tree.heading("no", text="번호")
        self.account_tree.heading("id", text="아이디")
        self.account_tree.heading("store_name", text="스토어명")
        self.account_tree.heading("status", text="상태")
        self.account_tree.column("no", width=50, anchor=tk.CENTER)
        self.account_tree.column("id", width=150)
        self.account_tree.column("store_name", width=150)
        self.account_tree.column("status", width=150, anchor=tk.CENTER)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.account_tree.yview)
        self.account_tree.configure(yscrollcommand=scrollbar.set)
        self.account_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 실행 버튼
        exec_frame = ttk.Frame(main_frame)
        exec_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.exec_btn = ttk.Button(exec_frame, text="▶ 시트 생성 시작", command=self.start_create)
        self.exec_btn.pack(fill=tk.X, ipady=10)
        
        self.progress_label = ttk.Label(main_frame, text="대기 중", font=('', 10))
        self.progress_label.pack()
        
        # 로그
        log_frame = ttk.LabelFrame(main_frame, text="실행 로그", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, state=tk.DISABLED)
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
        elif len(id_lines) != len(pw_lines):
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
                self.accounts.append({'id': user_id, 'pw': password, 'store_name': '', 'status': '대기'})
                added += 1
                
        self.refresh_account_list()
        self.log(f"{added}개 계정 추가됨")
            
    def refresh_account_list(self):
        for item in self.account_tree.get_children():
            self.account_tree.delete(item)
        for i, acc in enumerate(self.accounts, 1):
            self.account_tree.insert("", tk.END, values=(i, acc['id'], acc['store_name'], acc['status']))
            
    def update_account(self, user_id, store_name=None, status=None):
        for acc in self.accounts:
            if acc['id'] == user_id:
                if store_name:
                    acc['store_name'] = store_name
                if status:
                    acc['status'] = status
                break
        self.root.after(0, self.refresh_account_list)
        
    def auto_start_chrome(self):
        thread = threading.Thread(target=self._start_chrome_thread)
        thread.daemon = True
        thread.start()
        
    def _start_chrome_thread(self):
        self.log("Chrome 시작 중...")
        
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
                self.log("기존 Chrome 세션 사용")
            except:
                cmd = f'"{chrome_path}" --remote-debugging-port={port} --user-data-dir="{user_data_dir}"'
                subprocess.Popen(cmd, shell=True)
                time.sleep(3)
            
            options = Options()
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
            
            self.driver = webdriver.Chrome(options=options)
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
                
            scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
            credentials = Credentials.from_service_account_file(json_path, scopes=scopes)
            self.gc = gspread.authorize(credentials)
            self.spreadsheet = self.gc.open_by_key(spreadsheet_id)
            
            # 설정 저장
            self.save_config()
            
            self.root.after(0, lambda: self.google_status.configure(text=f"● 연결됨: {self.spreadsheet.title}", foreground="green"))
            self.log(f"구글 시트 연결 완료: {self.spreadsheet.title}")
            
        except gspread.exceptions.SpreadsheetNotFound:
            self.root.after(0, lambda: self.google_status.configure(text="● 시트를 찾을 수 없음", foreground="red"))
            self.log("구글 시트를 찾을 수 없습니다. ID를 확인하세요.")
            self.root.after(0, lambda: messagebox.showerror("오류", "구글 시트를 찾을 수 없습니다.\n\n1. 시트 ID가 맞는지 확인\n2. 서비스 계정 이메일에 시트 공유 필요"))
        except Exception as e:
            self.root.after(0, lambda: self.google_status.configure(text="● 연결 실패", foreground="red"))
            self.log(f"구글 시트 연결 실패: {e}")
            
    def safe_click(self, element):
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.3)
            element.click()
        except ElementClickInterceptedException:
            self.driver.execute_script("arguments[0].click();", element)
            
    def start_create(self):
        if not self.driver:
            messagebox.showwarning("경고", "Chrome이 연결되지 않았습니다.")
            return
            
        if not self.spreadsheet:
            messagebox.showwarning("경고", "구글 시트가 연결되지 않았습니다.")
            return
            
        if not self.accounts:
            messagebox.showwarning("경고", "등록된 계정이 없습니다.")
            return
            
        self.exec_btn.configure(state=tk.DISABLED)
        
        thread = threading.Thread(target=self._run_create)
        thread.daemon = True
        thread.start()
        
    def _run_create(self):
        total = len(self.accounts)
        success = 0
        
        for i, account in enumerate(self.accounts):
            user_id = account['id']
            password = account['pw']
            
            self.root.after(0, lambda s=f"진행: {i+1}/{total} - {user_id}": self.progress_label.configure(text=s))
            
            self.log(f"\n[{i+1}/{total}] {user_id}")
            self.update_account(user_id, status="로그인 중...")
            
            try:
                # 1. 로그인
                if not self.do_login(user_id, password):
                    raise Exception("로그인 실패")
                
                time.sleep(2)
                
                # 2. 스토어 이름 가져오기
                store_name = self.get_store_name()
                self.log(f"  → 스토어명: {store_name}")
                self.update_account(user_id, store_name=store_name, status="시트 생성 중...")
                
                # 3. 시트 생성
                self.create_sheet(store_name)
                
                # 4. 로그아웃
                self.do_logout()
                
                success += 1
                self.update_account(user_id, status="✓ 완료")
                
            except Exception as e:
                self.log(f"  ✗ 오류: {e}")
                self.update_account(user_id, status=f"✗ {str(e)[:15]}")
                try:
                    self.do_logout()
                except:
                    pass
                    
            time.sleep(2)
            
        self.root.after(0, lambda: self.progress_label.configure(text=f"완료! {success}/{total} 성공"))
        self.root.after(0, lambda: self.exec_btn.configure(state=tk.NORMAL))
        self.log(f"\n완료: {success}/{total} 시트 생성")
        
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
                if "dashboard" in self.driver.current_url:
                    return True
                    
            if "nid.naver.com" in self.driver.current_url:
                self.log("  ⚠ 캡차 대기 20초")
                time.sleep(20)
                if "dashboard" in self.driver.current_url:
                    return True
                    
            return False
            
        except Exception as e:
            self.log(f"  로그인 오류: {e}")
            return False
            
    def get_store_name(self):
        try:
            wait = WebDriverWait(self.driver, 10)
            self.driver.get("https://sell.smartstore.naver.com/#/home/dashboard")
            time.sleep(2)
            
            store_elem = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.shop")))
            return store_elem.text.strip() or "Unknown"
            
        except Exception as e:
            self.log(f"  스토어명 가져오기 실패: {e}")
            return "Unknown"
            
    def create_sheet(self, store_name):
        try:
            # 이미 존재하는지 확인
            try:
                existing = self.spreadsheet.worksheet(store_name)
                self.log(f"  → 시트 '{store_name}' 이미 존재함")
                return
            except gspread.exceptions.WorksheetNotFound:
                pass
            
            # 새 시트 생성
            self.spreadsheet.add_worksheet(title=store_name, rows=1000, cols=10)
            self.log(f"  → 시트 '{store_name}' 생성 완료!")
            
        except Exception as e:
            self.log(f"  시트 생성 오류: {e}")
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
    app = SheetCreator(root)
    root.mainloop()


if __name__ == "__main__":
    main()