"""
스마트스토어 찜 자동화 프로그램 v1.6
- 각 계정별 별도 프로필 폴더 사용 (충돌 방지)
- 숨김 모드 (화면 밖 실행)
- 설정 자동 저장/불러오기 (URL 포함)
- 연속 스킵 옵션 (20/40/80/전체)
- URL 순서 랜덤 셔플
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
import queue
import re
import os
import json
import random
from datetime import datetime

# 설정 파일 경로 (고정 위치 - 어디서 실행해도 동일)
CONFIG_FILE = os.path.join(os.path.expanduser("~"), "zzim_config.json")

# ═══════════════════════════════════════════════════════════════
# webdriver-manager 설치 확인
# ═══════════════════════════════════════════════════════════════
try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_WEBDRIVER_MANAGER = True
except ImportError:
    USE_WEBDRIVER_MANAGER = False
    print("⚠️ webdriver-manager가 설치되지 않았습니다.")
    print("   설치 명령어: pip install webdriver-manager")

# ═══════════════════════════════════════════════════════════════
# 설정
# ═══════════════════════════════════════════════════════════════
CHROMEDRIVER_PATH = "E:/gpt-자동화/percenty_auto/chromedriver.exe"

# 각 계정별 별도 프로필 폴더 (동시 실행 시 충돌 방지)
BASE_PROFILE_DIR = r"E:\gpt-자동화\찜자동화_프로필"

# 네이버 계정별 프로필 설정 (6개) - 각각 별도 폴더 사용
PROFILES = [
    {"name": "계정1", "folder": "account1"},
    {"name": "계정2", "folder": "account2"},
    {"name": "계정3", "folder": "account3"},
    {"name": "계정4", "folder": "account4"},
    {"name": "계정5", "folder": "account5"},
    {"name": "계정6", "folder": "account6"},
]

MAX_PAGES = 80


class ZzimAutomation:
    def __init__(self, root):
        self.root = root
        self.root.title("🛒 스마트스토어 찜 자동화 v1.6")
        self.root.geometry("900x850")
        self.root.resizable(True, True)
        
        self.drivers = {}
        self.stop_flags = {}
        self.log_queue = queue.Queue()
        self.is_running = False
        
        # 저장된 설정 불러오기
        self.config = self.load_config()
        
        self.setup_ui()
        self.update_log()
        self.init_profile_folders()
        
        if USE_WEBDRIVER_MANAGER:
            self.log("✅ webdriver-manager 사용 가능")
        else:
            self.log("⚠️ webdriver-manager 미설치")
    
    def load_config(self):
        """설정 파일 불러오기"""
        default_config = {
            "profile_path": os.path.join(os.path.expanduser("~"), "찜자동화_프로필"),
            "driver_path": "",
            "auto_driver": True,
            "browser_count": 2,
            "max_pages": 80,
            "hidden_mode": True,
            "urls": "",
            "skip_threshold": "전체"
        }
        
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    default_config.update(saved)
        except:
            pass
        
        return default_config
    
    def save_config(self):
        """설정 파일 저장"""
        try:
            config = {
                "profile_path": self.profile_path_entry.get().strip(),
                "driver_path": self.driver_path_entry.get().strip(),
                "auto_driver": self.auto_driver_var.get(),
                "browser_count": int(self.browser_count.get()),
                "max_pages": int(self.max_page_entry.get()) if self.max_page_entry.get().isdigit() else 80,
                "hidden_mode": self.hidden_var.get(),
                "urls": self.url_text.get("1.0", "end").strip(),
                "skip_threshold": self.skip_threshold.get()
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"설정 저장 실패: {e}")
    
    def init_profile_folders(self):
        """프로필 폴더 자동 생성"""
        base_dir = self.profile_path_entry.get().strip()
        
        if not os.path.exists(base_dir):
            try:
                os.makedirs(base_dir)
                self.log(f"📁 기본 폴더 생성: {base_dir}")
            except Exception as e:
                self.log(f"❌ 폴더 생성 실패: {e}")
                return
        
        for profile in PROFILES:
            profile_dir = os.path.join(base_dir, profile["folder"])
            if not os.path.exists(profile_dir):
                try:
                    os.makedirs(profile_dir)
                    self.log(f"📁 {profile['name']} 폴더 생성: {profile_dir}")
                except Exception as e:
                    self.log(f"❌ {profile['name']} 폴더 생성 실패: {e}")
    
    def setup_ui(self):
        # ═══════════════════════════════════════════════════════════════
        # URL 입력
        # ═══════════════════════════════════════════════════════════════
        frame_url = ttk.LabelFrame(self.root, text="📌 스마트스토어 URL 입력 (한 줄에 하나씩)", padding=10)
        frame_url.pack(fill="x", padx=10, pady=5)
        
        self.url_text = scrolledtext.ScrolledText(frame_url, height=5, width=100)
        self.url_text.pack(fill="x")
        # 저장된 URL 불러오기
        saved_urls = self.config.get("urls", "")
        if saved_urls:
            self.url_text.insert("1.0", saved_urls)
        else:
            self.url_text.insert("1.0", "https://smartstore.naver.com/스토어명1\nhttps://smartstore.naver.com/스토어명2")
        
        # URL 변경 시 자동 저장
        self.url_text.bind("<KeyRelease>", lambda e: self.save_config())
        
        # ═══════════════════════════════════════════════════════════════
        # 경로 설정
        # ═══════════════════════════════════════════════════════════════
        frame_path = ttk.LabelFrame(self.root, text="📂 경로 설정", padding=10)
        frame_path.pack(fill="x", padx=10, pady=5)
        
        row_profile = ttk.Frame(frame_path)
        row_profile.pack(fill="x", pady=2)
        ttk.Label(row_profile, text="프로필 저장 폴더:").pack(side="left")
        self.profile_path_entry = ttk.Entry(row_profile, width=50)
        self.profile_path_entry.insert(0, self.config["profile_path"])
        self.profile_path_entry.pack(side="left", padx=5)
        
        ttk.Button(row_profile, text="폴더 생성", command=self.init_profile_folders).pack(side="left", padx=5)
        
        row_driver = ttk.Frame(frame_path)
        row_driver.pack(fill="x", pady=2)
        ttk.Label(row_driver, text="크롬드라이버 경로:").pack(side="left")
        self.driver_path_entry = ttk.Entry(row_driver, width=50)
        self.driver_path_entry.insert(0, self.config["driver_path"])
        self.driver_path_entry.pack(side="left", padx=5)
        
        self.auto_driver_var = tk.BooleanVar(value=self.config["auto_driver"])
        ttk.Checkbutton(row_driver, text="자동 관리", variable=self.auto_driver_var).pack(side="left", padx=10)
        
        # ═══════════════════════════════════════════════════════════════
        # 설정
        # ═══════════════════════════════════════════════════════════════
        frame_settings = ttk.LabelFrame(self.root, text="⚙️ 설정", padding=10)
        frame_settings.pack(fill="x", padx=10, pady=5)
        
        row1 = ttk.Frame(frame_settings)
        row1.pack(fill="x", pady=3)
        
        ttk.Label(row1, text="동시 실행:").pack(side="left")
        self.browser_count = ttk.Combobox(row1, values=[1, 2, 3, 4, 5, 6], width=3, state="readonly")
        self.browser_count.set(self.config["browser_count"])
        self.browser_count.pack(side="left", padx=5)
        
        ttk.Label(row1, text="최대 페이지:").pack(side="left", padx=(10,0))
        self.max_page_entry = ttk.Entry(row1, width=5)
        self.max_page_entry.insert(0, str(self.config["max_pages"]))
        self.max_page_entry.pack(side="left", padx=5)
        
        self.hidden_var = tk.BooleanVar(value=self.config["hidden_mode"])
        ttk.Checkbutton(row1, text="🙈 숨김 모드 (PC 사용 가능)", variable=self.hidden_var).pack(side="left", padx=20)
        
        # 연속 스킵 옵션
        row1_2 = ttk.Frame(frame_settings)
        row1_2.pack(fill="x", pady=3)
        
        ttk.Label(row1_2, text="연속 스킵 시 다음 스토어:").pack(side="left")
        self.skip_threshold = ttk.Combobox(row1_2, values=["전체", "20", "40", "80"], width=6, state="readonly")
        self.skip_threshold.set(self.config.get("skip_threshold", "전체"))
        self.skip_threshold.pack(side="left", padx=5)
        ttk.Label(row1_2, text="(이미 찜된 상품 연속 N개 스킵 시 → 다음 스토어로)").pack(side="left")
        
        # 계정 선택
        row2 = ttk.Frame(frame_settings)
        row2.pack(fill="x", pady=5)
        
        ttk.Label(row2, text="계정 선택:").pack(side="left")
        
        self.account_vars = []
        for i, profile in enumerate(PROFILES):
            var = tk.BooleanVar(value=(i < 2))
            cb = ttk.Checkbutton(row2, text=profile["name"], variable=var)
            cb.pack(side="left", padx=5)
            self.account_vars.append(var)
        
        # ═══════════════════════════════════════════════════════════════
        # 버튼
        # ═══════════════════════════════════════════════════════════════
        frame_buttons = ttk.Frame(self.root, padding=10)
        frame_buttons.pack(fill="x", padx=10)
        
        self.btn_test = ttk.Button(frame_buttons, text="🔍 로그인 설정 (최초 1회)", command=self.test_browsers)
        self.btn_test.pack(side="left", padx=5)
        
        self.btn_start = ttk.Button(frame_buttons, text="▶️ 찜하기 시작", command=self.start_automation)
        self.btn_start.pack(side="left", padx=5)
        
        self.btn_stop = ttk.Button(frame_buttons, text="⏹️ 전체 중지", command=self.stop_all, state="disabled")
        self.btn_stop.pack(side="left", padx=5)
        
        self.btn_clear_log = ttk.Button(frame_buttons, text="🗑️ 로그 지우기", command=self.clear_log)
        self.btn_clear_log.pack(side="right", padx=5)
        
        # ═══════════════════════════════════════════════════════════════
        # 진행 상황
        # ═══════════════════════════════════════════════════════════════
        frame_progress = ttk.LabelFrame(self.root, text="📊 진행 상황", padding=10)
        frame_progress.pack(fill="x", padx=10, pady=5)
        
        self.progress_labels = {}
        for i, profile in enumerate(PROFILES):
            row = ttk.Frame(frame_progress)
            row.pack(fill="x", pady=2)
            
            ttk.Label(row, text=f"{profile['name']}:", width=8).pack(side="left")
            
            progress = ttk.Progressbar(row, length=250, mode="determinate")
            progress.pack(side="left", padx=5)
            
            status_label = ttk.Label(row, text="대기 중", width=45)
            status_label.pack(side="left", padx=5)
            
            self.progress_labels[i] = {"progress": progress, "status": status_label}
        
        # ═══════════════════════════════════════════════════════════════
        # 로그
        # ═══════════════════════════════════════════════════════════════
        frame_log = ttk.LabelFrame(self.root, text="📜 실행 로그", padding=10)
        frame_log.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(frame_log, height=10, state="disabled")
        self.log_text.pack(fill="both", expand=True)
    
    def log(self, message, account_idx=None):
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{PROFILES[account_idx]['name']}]" if account_idx is not None else "[시스템]"
        self.log_queue.put(f"[{timestamp}] {prefix} {message}")
    
    def update_log(self):
        while not self.log_queue.empty():
            message = self.log_queue.get()
            self.log_text.config(state="normal")
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.root.after(100, self.update_log)
    
    def clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
    
    def update_progress(self, account_idx, current, total, status_text):
        def update():
            if account_idx in self.progress_labels:
                progress = self.progress_labels[account_idx]["progress"]
                status = self.progress_labels[account_idx]["status"]
                if total > 0:
                    progress["value"] = (current / total) * 100
                status.config(text=status_text)
        self.root.after(0, update)
    
    def get_selected_accounts(self):
        return [i for i, var in enumerate(self.account_vars) if var.get()]
    
    def get_profile_path(self, account_idx):
        """계정별 프로필 경로 반환"""
        base_dir = self.profile_path_entry.get().strip()
        return os.path.join(base_dir, PROFILES[account_idx]["folder"])
    
    def create_driver(self, account_idx, hidden=True, test_mode=False):
        """브라우저 드라이버 생성 - 각 계정별 별도 폴더"""
        profile_path = self.get_profile_path(account_idx)
        
        # 폴더 없으면 생성
        if not os.path.exists(profile_path):
            os.makedirs(profile_path)
        
        options = Options()
        
        # 각 계정마다 별도의 user-data-dir 사용 (충돌 방지)
        options.add_argument(f"user-data-dir={profile_path}")
        
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        if test_mode:
            options.add_argument("--start-maximized")
        elif hidden:
            options.add_argument("--window-position=-2400,-2400")
            options.add_argument("--window-size=1920,1080")
        else:
            options.add_argument("--start-maximized")
        
        if self.auto_driver_var.get() and USE_WEBDRIVER_MANAGER:
            service = Service(ChromeDriverManager().install())
        else:
            driver_path = self.driver_path_entry.get().strip()
            service = Service(driver_path)
        
        driver = webdriver.Chrome(service=service, options=options)
        driver.implicitly_wait(5)
        
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            '''
        })
        
        return driver
    
    def test_browsers(self):
        """로그인 설정 - 하나씩 순차적으로"""
        selected = self.get_selected_accounts()
        
        if not selected:
            messagebox.showwarning("경고", "테스트할 계정을 선택하세요.")
            return
        
        # 기존 드라이버 닫기
        for driver in list(self.drivers.values()):
            try:
                driver.quit()
            except:
                pass
        self.drivers.clear()
        
        self.log(f"🔐 로그인 설정 시작 - {len(selected)}개 계정")
        self.log("⚠️ 각 브라우저에서 네이버 로그인 후 창을 닫지 마세요!")
        
        def test_thread():
            for idx in selected:
                try:
                    profile_path = self.get_profile_path(idx)
                    self.log(f"브라우저 열기... (프로필: {profile_path})", idx)
                    
                    driver = self.create_driver(idx, hidden=False, test_mode=True)
                    driver.get("https://nid.naver.com/nidlogin.login")
                    self.drivers[idx] = driver
                    
                    self.log(f"✅ 브라우저 열림 - 네이버 로그인하세요!", idx)
                    
                    # 다음 계정 열기 전 잠시 대기
                    time.sleep(1)
                    
                except Exception as e:
                    self.log(f"❌ 오류: {str(e)}", idx)
            
            self.log("=" * 50)
            self.log("📢 모든 브라우저에서 로그인 완료 후 '찜하기 시작' 클릭")
            self.log("📢 로그인 후 브라우저는 자동으로 닫히거나 수동으로 닫아도 됩니다")
        
        threading.Thread(target=test_thread, daemon=True).start()
    
    def get_urls(self):
        text = self.url_text.get("1.0", "end").strip()
        urls = [url.strip() for url in text.split("\n") if url.strip() and url.strip().startswith("http")]
        return urls
    
    def start_automation(self):
        urls = self.get_urls()
        if not urls:
            messagebox.showwarning("경고", "유효한 URL을 입력하세요.")
            return
        
        selected_accounts = self.get_selected_accounts()
        if not selected_accounts:
            messagebox.showwarning("경고", "사용할 계정을 선택하세요.")
            return
        
        # 기존 테스트 브라우저 닫기
        for driver in list(self.drivers.values()):
            try:
                driver.quit()
            except:
                pass
        self.drivers.clear()
        
        browser_count = int(self.browser_count.get())
        max_pages = int(self.max_page_entry.get()) if self.max_page_entry.get().isdigit() else MAX_PAGES
        hidden = self.hidden_var.get()
        skip_threshold = self.skip_threshold.get()
        skip_limit = None if skip_threshold == "전체" else int(skip_threshold)
        
        accounts_to_use = selected_accounts[:browser_count]
        
        self.log(f"🚀 찜 자동화 시작")
        self.log(f"- URL: {len(urls)}개 / 계정: {len(accounts_to_use)}개 / 페이지: {max_pages}")
        self.log(f"- 숨김 모드: {'예' if hidden else '아니오'}")
        self.log(f"- 연속 스킵: {skip_threshold}{'개 → 다음 스토어' if skip_limit else ' (전체 확인)'}")
        
        self.is_running = True
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        
        # URL 분배
        url_assignments = {idx: [] for idx in accounts_to_use}
        for i, url in enumerate(urls):
            account_idx = accounts_to_use[i % len(accounts_to_use)]
            url_assignments[account_idx].append(url)
        
        # 각 계정별 URL 순서 랜덤 셔플
        for idx in accounts_to_use:
            random.shuffle(url_assignments[idx])
        
        for account_idx in accounts_to_use:
            self.stop_flags[account_idx] = False
            assigned_urls = url_assignments[account_idx]
            
            if assigned_urls:
                self.log(f"담당 URL: {len(assigned_urls)}개", account_idx)
                thread = threading.Thread(
                    target=self.run_zzim_for_account,
                    args=(account_idx, assigned_urls, max_pages, hidden, skip_limit),
                    daemon=True
                )
                thread.start()
    
    def run_zzim_for_account(self, account_idx, urls, max_pages, hidden, skip_limit):
        driver = None
        total_zzim = 0
        
        try:
            self.log(f"브라우저 시작...", account_idx)
            self.update_progress(account_idx, 0, 100, "브라우저 시작 중...")
            
            driver = self.create_driver(account_idx, hidden)
            self.drivers[account_idx] = driver
            
            for url_idx, url in enumerate(urls):
                if self.stop_flags.get(account_idx):
                    break
                
                self.log(f"스토어: {url.split('/')[-1]} ({url_idx + 1}/{len(urls)})", account_idx)
                
                full_url = self.build_product_list_url(url)
                self.log(f"접속 URL: {full_url}", account_idx)
                driver.get(full_url)
                time.sleep(2)
                
                zzim_count, skipped_by_threshold = self.zzim_store(driver, account_idx, max_pages, url_idx + 1, len(urls), skip_limit)
                total_zzim += zzim_count
                
                if skipped_by_threshold:
                    self.log(f"⏭️ 연속 스킵 {skip_limit}개 → 다음 스토어", account_idx)
                
                self.log(f"✅ 완료 - 찜 {zzim_count}개", account_idx)
            
            self.log(f"🎉 전체 완료 - 총 {total_zzim}개", account_idx)
            self.update_progress(account_idx, 100, 100, f"완료! 총 {total_zzim}개")
            
        except Exception as e:
            self.log(f"❌ 오류: {str(e)}", account_idx)
            self.update_progress(account_idx, 0, 100, f"오류 발생")
        
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
                if account_idx in self.drivers:
                    del self.drivers[account_idx]
            
            self.check_all_completed()
    
    def build_product_list_url(self, store_url):
        store_url = store_url.rstrip("/")
        return f"{store_url}/category/ALL?st=RECENT&dt=IMAGE&page=1&size=80"
    
    def zzim_store(self, driver, account_idx, max_pages, current_store, total_stores, skip_limit):
        """한 스토어의 모든 상품 찜하기"""
        zzim_count = 0
        current_page = 1
        consecutive_skips = 0  # 연속 스킵 카운트
        skipped_by_threshold = False
        
        while current_page <= max_pages:
            if self.stop_flags.get(account_idx):
                self.log(f"🛑 중지", account_idx)
                break
            
            progress_pct = ((current_store - 1) / total_stores * 100) + (current_page / max_pages / total_stores * 100)
            self.update_progress(account_idx, progress_pct, 100, f"스토어 {current_store}/{total_stores} - {current_page}p")
            
            try:
                time.sleep(1)
                
                like_buttons = []
                selectors = [
                    'button.zzim_button',
                    'button[class*="zzim"]',
                    'button[class*="wish"]',
                    '[class*="zzim_btn"]',
                    'button[class*="ZzimBtn"]',
                    '[class*="ZzimBtn"]',
                ]
                
                for selector in selectors:
                    like_buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                    if like_buttons:
                        self.log(f"찜 버튼 발견: {selector} ({len(like_buttons)}개)", account_idx)
                        break
                
                if not like_buttons:
                    self.log(f"⚠️ {current_page}p - 찜 버튼 없음 (셀렉터 확인 필요)", account_idx)
                    if not self.go_to_next_page(driver, current_page):
                        break
                    current_page += 1
                    continue
                
                page_zzim = 0
                skip_count = 0
                
                for button in like_buttons:
                    if self.stop_flags.get(account_idx):
                        break
                    
                    # 연속 스킵 체크
                    if skip_limit and consecutive_skips >= skip_limit:
                        skipped_by_threshold = True
                        break
                    
                    try:
                        is_zzimed = False
                        skip_reason = ""
                        
                        aria_pressed = button.get_attribute("aria-pressed")
                        if aria_pressed == "true":
                            is_zzimed = True
                            skip_reason = f"aria-pressed={aria_pressed}"
                        
                        if not is_zzimed:
                            aria_label = button.get_attribute("aria-label") or ""
                            if "해제" in aria_label or "취소" in aria_label:
                                is_zzimed = True
                                skip_reason = f"aria-label={aria_label}"
                        
                        if is_zzimed:
                            skip_count += 1
                            consecutive_skips += 1  # 연속 스킵 증가
                            if skip_count <= 3:  # 처음 3개만 로그
                                self.log(f"  스킵: {skip_reason}", account_idx)
                            continue
                        
                        # 찜 클릭 성공 시 연속 스킵 리셋
                        consecutive_skips = 0
                        
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                        time.sleep(0.1)
                        
                        try:
                            button.click()
                            zzim_count += 1
                            page_zzim += 1
                        except Exception as click_err:
                            try:
                                driver.execute_script("arguments[0].click();", button)
                                zzim_count += 1
                                page_zzim += 1
                            except Exception as js_err:
                                self.log(f"  클릭 실패: {str(js_err)[:30]}", account_idx)
                        
                        time.sleep(2)
                        
                    except Exception as e:
                        self.log(f"  버튼 처리 오류: {str(e)[:30]}", account_idx)
                        continue
                
                self.log(f"{current_page}p - 찜 {page_zzim}개, 스킵 {skip_count}개 (누적 {zzim_count})", account_idx)
                
                # 연속 스킵 임계값 도달 시 종료
                if skipped_by_threshold:
                    break
                
                if not self.go_to_next_page(driver, current_page):
                    self.log(f"마지막 페이지", account_idx)
                    break
                
                current_page += 1
                time.sleep(1.5)
                
            except Exception as e:
                self.log(f"⚠️ 오류: {str(e)[:30]}", account_idx)
                break
        
        return zzim_count, skipped_by_threshold
    
    def go_to_next_page(self, driver, current_page):
        next_page = current_page + 1
        
        try:
            next_btn = driver.find_element(By.LINK_TEXT, str(next_page))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
            next_btn.click()
            return True
        except:
            pass
        
        try:
            next_btn = driver.find_element(By.LINK_TEXT, "다음")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
            next_btn.click()
            return True
        except:
            pass
        
        try:
            current_url = driver.current_url
            if "page=" in current_url:
                new_url = re.sub(r'page=\d+', f'page={next_page}', current_url)
                driver.get(new_url)
                return True
        except:
            pass
        
        return False
    
    def stop_all(self):
        self.log("🛑 전체 중지")
        for idx in self.stop_flags:
            self.stop_flags[idx] = True
        self.is_running = False
        self.btn_stop.config(state="disabled")
        self.btn_start.config(state="normal")
    
    def check_all_completed(self):
        if not self.drivers:
            self.is_running = False
            self.root.after(0, lambda: self.btn_stop.config(state="disabled"))
            self.root.after(0, lambda: self.btn_start.config(state="normal"))
            self.log("✅ 모든 작업 완료")
    
    def on_close(self):
        if self.is_running:
            if not messagebox.askyesno("확인", "작업 중입니다. 종료할까요?"):
                return
        
        # 설정 저장
        self.save_config()
        
        self.stop_all()
        for driver in list(self.drivers.values()):
            try:
                driver.quit()
            except:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = ZzimAutomation(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
