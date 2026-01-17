# ============================================
# 알리익스프레스 송장번호 자동 수집 (GUI 버전)
# ============================================

import time
import re
import os
import json
import threading
import requests
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import gspread
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

# ============================================
# 설정
# ============================================

CREDENTIALS_FILE = "autosms-466614-951e91617c69.json"  # 서비스 계정 JSON 파일
SETTINGS_FILE = "settings.json"  # 설정 저장 파일

# Chrome 프로필 경로 (기존 로그인 상태 유지)
# Windows: C:/Users/사용자명/AppData/Local/Google/Chrome/User Data
# Mac: /Users/사용자명/Library/Application Support/Google/Chrome
CHROME_PROFILE_PATH = ""  # 비워두면 자동 탐색

# 열 위치 (1부터 시작)
COL_PLATFORM = 30      # AD열: 플랫폼 (타오바오/알리)
COL_ORDER_ID = 31      # AE열: 주문번호
COL_CARRIER = 43       # AQ열: 택배회사
COL_TRACKING = 44      # AR열: 송장번호
START_ROW = 3          # 시작 행


# ============================================
# 택배사 구분
# ============================================

def get_carrier_name(tracking_no):
    tracking_no = str(tracking_no).strip()
    if tracking_no.startswith('50') or tracking_no.startswith('56'):
        return 'CJ대한통운'
    elif tracking_no.startswith('51'):
        return '한진택배'
    elif tracking_no.startswith('9'):
        return '투데이'
    elif tracking_no.startswith('52'):
        return '경동'
    elif tracking_no.startswith('54'):
        return '로젠'
    else:
        return '확인필요'


def get_carrier_code(carrier_name):
    """택배사명 → Delivery Tracker API 코드"""
    codes = {
        'CJ대한통운': 'kr.cjlogistics',
        '한진택배': 'kr.hanjin',
        '투데이': 'kr.todaypickup',
        '경동': 'kr.kdexp',
        '로젠': 'kr.logen',
        '우체국': 'kr.epost'
    }
    return codes.get(carrier_name)


def check_domestic_delivery(carrier_name, tracking_no):
    """국내 배송조회 (Delivery Tracker API)"""
    carrier_code = get_carrier_code(carrier_name)
    if not carrier_code:
        return False
    
    tracking_no = str(tracking_no).replace('-', '').replace(' ', '')
    url = f"https://apis.tracker.delivery/carriers/{carrier_code}/tracks/{tracking_no}"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return False
        
        data = response.json()
        if data.get('progresses') and len(data['progresses']) > 0:
            return True
        return False
    except:
        return False


def get_chrome_profile_path():
    """Chrome 프로필 경로 자동 탐색"""
    if CHROME_PROFILE_PATH:
        return CHROME_PROFILE_PATH
    
    # Windows
    win_path = os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\User Data')
    if os.path.exists(win_path):
        return win_path
    
    # Mac
    mac_path = os.path.expanduser('~/Library/Application Support/Google/Chrome')
    if os.path.exists(mac_path):
        return mac_path
    
    # Linux
    linux_path = os.path.expanduser('~/.config/google-chrome')
    if os.path.exists(linux_path):
        return linux_path
    
    return None


def load_settings():
    """저장된 설정 불러오기"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_settings(settings):
    """설정 저장"""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except:
        pass


# ============================================
# GUI 클래스
# ============================================

class AliTrackingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("알리익스프레스 송장번호 수집기")
        self.root.geometry("600x500")
        self.root.resizable(False, False)
        
        self.driver = None
        self.is_running = False
        self.settings = load_settings()
        
        self.create_widgets()
        self.load_saved_values()
    
    def create_widgets(self):
        # 상단 프레임
        top_frame = ttk.Frame(self.root, padding="10")
        top_frame.pack(fill=tk.X)
        
        # 시트 URL 입력
        ttk.Label(top_frame, text="구글 시트 URL 또는 ID:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.sheet_url = ttk.Entry(top_frame, width=70)
        self.sheet_url.grid(row=1, column=0, columnspan=3, sticky=tk.W+tk.E, pady=5)
        
        # 월 선택
        ttk.Label(top_frame, text="월 선택:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.month_var = tk.StringVar()
        self.month_combo = ttk.Combobox(top_frame, textvariable=self.month_var, width=10, state="readonly")
        self.month_combo['values'] = [f"{i}월" for i in range(1, 13)]
        self.month_combo.current(0)
        self.month_combo.grid(row=2, column=1, sticky=tk.W, pady=5)
        
        # 디버그 포트
        ttk.Label(top_frame, text="Chrome 디버그 포트:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.debug_port = ttk.Entry(top_frame, width=10)
        self.debug_port.insert(0, "9222")
        self.debug_port.grid(row=3, column=1, sticky=tk.W, pady=5)
        ttk.Label(top_frame, text="(기본: 9222)").grid(row=3, column=2, sticky=tk.W, pady=5)
        
        # 버튼 프레임
        btn_frame = ttk.Frame(self.root, padding="10")
        btn_frame.pack(fill=tk.X)
        
        self.login_btn = ttk.Button(btn_frame, text="1. 브라우저 연결", command=self.open_browser)
        self.login_btn.pack(side=tk.LEFT, padx=5)
        
        self.start_btn = ttk.Button(btn_frame, text="2. 수집 시작", command=self.start_collection, state=tk.DISABLED)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = ttk.Button(btn_frame, text="중지", command=self.stop_collection, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        # 로그 영역
        log_frame = ttk.LabelFrame(self.root, text="로그", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # 상태바
        self.status_var = tk.StringVar(value="준비")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
    
    def log(self, message):
        """로그 출력"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def load_saved_values(self):
        """저장된 값 불러오기"""
        if 'sheet_url' in self.settings:
            self.sheet_url.insert(0, self.settings['sheet_url'])
        if 'month' in self.settings:
            try:
                idx = [f"{i}월" for i in range(1, 13)].index(self.settings['month'])
                self.month_combo.current(idx)
            except:
                pass
        if 'debug_port' in self.settings:
            self.debug_port.delete(0, tk.END)
            self.debug_port.insert(0, self.settings['debug_port'])
    
    def save_current_values(self):
        """현재 값 저장"""
        self.settings['sheet_url'] = self.sheet_url.get().strip()
        self.settings['month'] = self.month_var.get()
        self.settings['debug_port'] = self.debug_port.get().strip()
        save_settings(self.settings)
    
    def get_sheet_id(self, url_or_id):
        """URL 또는 ID에서 시트 ID 추출"""
        url_or_id = url_or_id.strip()
        
        # 이미 ID만 입력한 경우 (URL 형식이 아닌 경우)
        if not url_or_id.startswith('http'):
            return url_or_id
        
        # URL에서 ID 추출
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url_or_id)
        if match:
            return match.group(1)
        
        return None
    
    def connect_sheet(self, sheet_id, sheet_name):
        """구글 시트 연결"""
        try:
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
            client = gspread.authorize(creds)
            spreadsheet = client.open_by_key(sheet_id)
            sheet = spreadsheet.worksheet(sheet_name)
            return sheet
        except Exception as e:
            self.log(f"시트 연결 오류: {e}")
            return None
    
    def open_browser(self):
        """브라우저 열기 (디버그 모드 연결)"""
        port = self.debug_port.get().strip()
        
        if not port.isdigit():
            messagebox.showerror("오류", "포트 번호를 숫자로 입력하세요.")
            return
        
        self.log("Chrome 디버그 모드 연결 중...")
        self.log(f"포트: {port}")
        self.log("")
        self.log("※ Chrome을 먼저 디버그 모드로 실행하세요:")
        self.log(f'   chrome.exe --remote-debugging-port={port}')
        self.log("")
        self.status_var.set("Chrome 연결 중...")
        
        try:
            options = Options()
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
            
            self.driver = webdriver.Chrome(options=options)
            
            self.log("Chrome 연결 성공!")
            self.log("알리익스프레스 로그인 상태 확인 후 '수집 시작' 클릭")
            self.status_var.set("준비 완료")
            
            self.login_btn.config(state=tk.DISABLED)
            self.start_btn.config(state=tk.NORMAL)
            
        except Exception as e:
            self.log(f"연결 오류: {e}")
            self.log("")
            self.log("=" * 40)
            self.log("Chrome 디버그 모드 실행 방법:")
            self.log("")
            self.log("1. 실행 중인 Chrome 모두 닫기")
            self.log("2. Win+R → 아래 명령어 입력:")
            self.log(f'   chrome.exe --remote-debugging-port={port}')
            self.log("3. Chrome에서 알리익스프레스 로그인")
            self.log("4. 다시 '브라우저 연결' 클릭")
            self.log("=" * 40)
            messagebox.showerror("연결 실패", 
                f"Chrome 디버그 모드에 연결할 수 없습니다.\n\n"
                f"1. Chrome을 모두 닫고\n"
                f"2. Win+R → chrome.exe --remote-debugging-port={port}\n"
                f"3. 알리익스프레스 로그인\n"
                f"4. 다시 시도")
    
    def get_ali_tracking(self, order_id):
        """알리 배송 페이지에서 송장번호 추출"""
        url = f"https://www.aliexpress.com/p/tracking/index.html?_addShare=no&_login=yes&tradeOrderId={order_id}"
        
        try:
            self.driver.get(url)
            time.sleep(3)
            
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
            
            # 운송장 번호 패턴 찾기
            match = re.search(r'운송장\s*번호[:\s]*(\d+)', page_text)
            if match:
                return match.group(1)
            
            match = re.search(r'Tracking\s*(?:number|no)[:\s]*(\d+)', page_text, re.IGNORECASE)
            if match:
                return match.group(1)
            
            return None
            
        except Exception as e:
            self.log(f"  조회 오류: {e}")
            return None
    
    def start_collection(self):
        """수집 시작"""
        sheet_url = self.sheet_url.get().strip()
        sheet_name = self.month_var.get()
        
        if not sheet_url:
            messagebox.showwarning("입력 필요", "구글 시트 URL 또는 ID를 입력하세요.")
            return
        
        sheet_id = self.get_sheet_id(sheet_url)
        if not sheet_id:
            messagebox.showerror("오류", "올바른 구글 시트 URL 또는 ID가 아닙니다.")
            return
        
        # 설정 저장
        self.save_current_values()
        
        self.is_running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        
        # 별도 스레드에서 실행
        thread = threading.Thread(target=self.run_collection, args=(sheet_id, sheet_name))
        thread.daemon = True
        thread.start()
    
    def run_collection(self, sheet_id, sheet_name):
        """수집 실행 (백그라운드)"""
        self.log(f"\n[{sheet_name}] 시트 연결 중...")
        self.status_var.set(f"[{sheet_name}] 시트 연결 중...")
        
        sheet = self.connect_sheet(sheet_id, sheet_name)
        if not sheet:
            self.finish_collection()
            return
        
        self.log("시트 연결 완료!")
        self.log("데이터 읽는 중...")
        
        try:
            all_data = sheet.get_all_values()
        except Exception as e:
            self.log(f"데이터 읽기 오류: {e}")
            self.finish_collection()
            return
        
        # 조회 대상 찾기
        targets = []
        for idx, row in enumerate(all_data):
            row_num = idx + 1
            if row_num < START_ROW:
                continue
            
            platform = row[COL_PLATFORM - 1] if len(row) >= COL_PLATFORM else ""
            order_id = row[COL_ORDER_ID - 1] if len(row) >= COL_ORDER_ID else ""
            tracking = row[COL_TRACKING - 1] if len(row) >= COL_TRACKING else ""
            
            if platform.strip() == "알리" and order_id.strip() and not tracking.strip():
                targets.append({
                    'row': row_num,
                    'order_id': order_id.strip()
                })
        
        self.log(f"조회 대상: {len(targets)}건")
        
        if not targets:
            self.log("조회할 건이 없습니다.")
            self.finish_collection()
            return
        
        # 송장번호 수집
        success_count = 0
        for i, target in enumerate(targets):
            if not self.is_running:
                self.log("\n수집 중단됨")
                break
            
            self.status_var.set(f"{i+1}/{len(targets)} 조회중...")
            self.log(f"\n{i+1}/{len(targets)} - 주문번호: {target['order_id']}")
            
            tracking_no = self.get_ali_tracking(target['order_id'])
            
            if tracking_no:
                carrier = get_carrier_name(tracking_no)
                self.log(f"  → 송장번호: {tracking_no} ({carrier})")
                
                # 국내 배송조회
                self.log(f"  → 국내 배송조회 중...")
                is_delivered = check_domestic_delivery(carrier, tracking_no)
                
                try:
                    sheet.update_cell(target['row'], COL_CARRIER, carrier)
                    sheet.update_cell(target['row'], COL_TRACKING, tracking_no)
                    
                    # 배송정보 확인되면 노란색 배경
                    if is_delivered:
                        # gspread format으로 노란색 배경 적용
                        sheet.format(f'AQ{target["row"]}:AR{target["row"]}', {
                            'backgroundColor': {'red': 1, 'green': 1, 'blue': 0}
                        })
                        self.log(f"  → 배송정보 확인됨 (노란색 표시)")
                    else:
                        self.log(f"  → 아직 배송정보 없음")
                    
                    success_count += 1
                    time.sleep(1)
                except Exception as e:
                    self.log(f"  → 시트 업데이트 오류: {e}")
            else:
                self.log(f"  → 송장번호 없음 (아직 미배송)")
            
            time.sleep(2)
        
        self.log(f"\n{'='*40}")
        self.log(f"완료! 총 {success_count}건 업데이트됨")
        self.log(f"{'='*40}")
        
        self.finish_collection()
    
    def stop_collection(self):
        """수집 중지"""
        self.is_running = False
        self.status_var.set("중지 중...")
    
    def finish_collection(self):
        """수집 완료 처리"""
        self.is_running = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("완료")
    
    def on_closing(self):
        """프로그램 종료"""
        # 설정 저장
        self.save_current_values()
        
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
        self.root.destroy()


# ============================================
# 메인 실행
# ============================================

if __name__ == "__main__":
    root = tk.Tk()
    app = AliTrackingApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
