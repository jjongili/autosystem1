# -*- coding: utf-8 -*-
"""
불사자(www.bulsaja.com) 이미지 번역 자동화 프로그램
- 썸네일 이미지 자동 번역
- 옵션 이미지 자동 번역
- 다중 탭 동시 처리 (3~5개)
"""

import os
import time
import threading
import json
from datetime import datetime
from typing import List, Optional

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

# ==================== 설정 ====================
CONFIG_FILE = "bulsaja_translator_config.json"
DEBUG_PORT = 9222
BULSAJA_LIST_URL = "https://www.bulsaja.com/products/manage/list/"
CHROME_DEBUG_PROFILE = "C:\\chrome_debug_profile"

# 번역 완료 대기 최대 시간 (초)
MAX_TRANSLATE_WAIT = 120

# ==================== 셀렉터 정의 ====================
SELECTORS = {
    # 목록 페이지
    "product_rows": ".ag-row",
    "product_id": "span[id^='cell-ID-']",
    "edit_button_text": "수정",
    
    # 상세 페이지 - 탭
    "tab_thumbnail": "썸네일",
    "tab_option": "옵션",
    "tab_price": "가격",
    
    # 썸네일 번역
    "thumbnail_select_all_text": "전체 선택",
    "thumbnail_translate_class": "bg-\\[\\#ff5a00\\]",
    
    # 옵션 이미지 번역
    "option_batch_edit_text": "이미지 일괄 편집",
    "option_select_all_text": "전체 선택",
    "option_translate_text": "이미지 번역하기",
    
    # 번역 완료 감지
    "translating_text": "번역중",
}


# ==================== 설정 파일 관리 ====================
def load_config():
    """설정 파일 로드"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_config(config):
    """설정 파일 저장"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"설정 저장 실패: {e}")
        return False


# ==================== 번역 자동화 클래스 ====================
class BulsajaImageTranslator:
    """불사자 이미지 번역 자동화"""
    
    def __init__(self, log_callback=None, progress_callback=None, finished_callback=None):
        self.log = log_callback or print
        self.progress_callback = progress_callback
        self.finished_callback = finished_callback
        
        self.main_driver = None
        self.is_running = False
        
        # 번역 옵션 (기본값)
        self.translate_thumbnail_var = None
        self.translate_option_var = None
        
        # 통계
        self.stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
        }
    
    def setup_driver(self):
        """WebDriver 설정"""
        try:
            options = Options()
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            
            service = Service(ChromeDriverManager().install())
            self.main_driver = webdriver.Chrome(service=service, options=options)
            self.main_driver.maximize_window()
            return True
        except Exception as e:
            self.log(f"❌ WebDriver 설정 실패: {e}")
            return False
    
    def launch_debug_chrome(self, port=DEBUG_PORT):
        """디버깅 모드 크롬 실행"""
        import subprocess
        import platform
        import socket
        
        # 포트가 이미 열려있는지 확인
        def is_port_open(p):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(('127.0.0.1', p))
                sock.close()
                return result == 0
            except:
                return False
        
        # 이미 실행 중이면 새로 실행하지 않음
        if is_port_open(port):
            self.log("✅ 이미 실행 중인 디버깅 크롬 발견")
            return True
        
        # 크롬 경로
        if platform.system() == "Windows":
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            ]
        else:
            chrome_paths = [
                "/usr/bin/google-chrome",
                "/usr/bin/chromium-browser",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            ]
        
        chrome_path = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_path = path
                break
        
        if not chrome_path:
            self.log("❌ 크롬 실행 파일을 찾을 수 없습니다")
            return False
        
        # 프로필 디렉토리 생성
        if not os.path.exists(CHROME_DEBUG_PROFILE):
            os.makedirs(CHROME_DEBUG_PROFILE)
        
        # 크롬 실행
        try:
            self.log("🚀 디버깅 모드 크롬 실행 중...")
            cmd = f'"{chrome_path}" --remote-debugging-port={port} --user-data-dir="{CHROME_DEBUG_PROFILE}" "{BULSAJA_LIST_URL}"'
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # 포트 열릴 때까지 대기
            self.log("⏳ 크롬 시작 대기...")
            for i in range(30):
                if is_port_open(port):
                    self.log(f"✅ 크롬 실행 완료 (포트: {port})")
                    return True
                time.sleep(1)
            
            self.log("⚠️ 포트 열림 확인 실패, 연결 시도...")
            return True
        except Exception as e:
            self.log(f"❌ 크롬 실행 실패: {e}")
            return False
    
    def connect_to_existing_chrome(self, port=DEBUG_PORT):
        """기존 크롬에 연결"""
        try:
            options = Options()
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
            
            service = Service(ChromeDriverManager().install())
            self.main_driver = webdriver.Chrome(service=service, options=options)
            
            # 불사자 리스트 페이지 탭 찾기
            all_handles = self.main_driver.window_handles
            target_handle = None
            
            for handle in all_handles:
                self.main_driver.switch_to.window(handle)
                url = self.main_driver.current_url
                if "bulsaja.com/products/manage/list" in url:
                    path = url.split('?')[0].rstrip('/')
                    if path.endswith('/list') or path.endswith('/list/'):
                        target_handle = handle
                        break
            
            if target_handle:
                self.main_driver.switch_to.window(target_handle)
            else:
                self.main_driver.switch_to.window(all_handles[0])
            
            self.log(f"✅ 크롬 연결 성공 (포트: {port})")
            return True
        except Exception as e:
            self.log(f"❌ 크롬 연결 실패: {e}")
            return False
    
    def find_button_by_text(self, driver, text, tag="button", timeout=5):
        """텍스트로 버튼 찾기"""
        try:
            buttons = WebDriverWait(driver, timeout).until(
                EC.presence_of_all_elements_located((By.TAG_NAME, tag))
            )
            for btn in buttons:
                if btn.text.strip() == text:
                    return btn
        except:
            pass
        return None
    
    def find_tab_button(self, driver, tab_name, timeout=5):
        """탭 버튼 찾기"""
        try:
            tabs = WebDriverWait(driver, timeout).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'button[role="tab"]'))
            )
            for tab in tabs:
                if tab.text.strip() == tab_name:
                    return tab
        except:
            pass
        return None
    
    def wait_for_translate_complete(self, driver, timeout=MAX_TRANSLATE_WAIT):
        """번역 완료 대기"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not self.is_running:
                return False
            
            if SELECTORS["translating_text"] not in driver.page_source:
                return True
            
            time.sleep(1)
        
        self.log("⚠️ 번역 대기 시간 초과")
        return False
    
    def process_thumbnail_translation(self, driver):
        """썸네일 번역 처리"""
        try:
            # 1. 썸네일 탭 클릭
            tab = self.find_tab_button(driver, SELECTORS["tab_thumbnail"])
            if not tab:
                self.log("  ⚠️ 썸네일 탭을 찾을 수 없음")
                return False
            
            tab.click()
            time.sleep(1)
            
            # 2. 전체 선택 버튼 클릭
            select_all = self.find_button_by_text(driver, SELECTORS["thumbnail_select_all_text"])
            if not select_all:
                self.log("  ⚠️ 전체 선택 버튼을 찾을 수 없음")
                return False
            
            select_all.click()
            time.sleep(0.5)
            
            # 3. 빠른 이미지 번역 버튼 클릭
            try:
                translate_btn = driver.find_element(
                    By.CSS_SELECTOR, 
                    f'button.{SELECTORS["thumbnail_translate_class"]}'
                )
                translate_btn.click()
            except:
                # 대안: 텍스트로 찾기
                translate_btn = self.find_button_by_text(driver, "빠른 이미지 번역")
                if translate_btn:
                    translate_btn.click()
                else:
                    self.log("  ⚠️ 번역 버튼을 찾을 수 없음")
                    return False
            
            # 4. 번역 완료 대기
            self.log("  ⏳ 썸네일 번역 중...")
            if not self.wait_for_translate_complete(driver):
                return False
            
            self.log("  ✅ 썸네일 번역 완료")
            return True
            
        except Exception as e:
            self.log(f"  ❌ 썸네일 번역 오류: {e}")
            return False
    
    def process_option_image_translation(self, driver):
        """옵션 이미지 번역 처리"""
        try:
            # 1. 옵션 탭 클릭
            tab = self.find_tab_button(driver, SELECTORS["tab_option"])
            if not tab:
                self.log("  ⚠️ 옵션 탭을 찾을 수 없음")
                return False
            
            tab.click()
            time.sleep(1)
            
            # 2. 이미지 일괄 편집 버튼 클릭
            batch_edit = self.find_button_by_text(driver, SELECTORS["option_batch_edit_text"])
            if not batch_edit:
                self.log("  ⚠️ 이미지 일괄 편집 버튼을 찾을 수 없음")
                return False
            
            batch_edit.click()
            time.sleep(1)
            
            # 3. 전체 선택 버튼 클릭
            select_all = self.find_button_by_text(driver, SELECTORS["option_select_all_text"])
            if not select_all:
                self.log("  ⚠️ 전체 선택 버튼을 찾을 수 없음")
                return False
            
            select_all.click()
            time.sleep(0.5)
            
            # 4. 이미지 번역하기 버튼 클릭
            translate_btn = self.find_button_by_text(driver, SELECTORS["option_translate_text"])
            if not translate_btn:
                self.log("  ⚠️ 이미지 번역하기 버튼을 찾을 수 없음")
                return False
            
            translate_btn.click()
            
            # 5. 번역 완료 대기
            self.log("  ⏳ 옵션 이미지 번역 중...")
            if not self.wait_for_translate_complete(driver):
                return False
            
            self.log("  ✅ 옵션 이미지 번역 완료")
            return True
            
        except Exception as e:
            self.log(f"  ❌ 옵션 이미지 번역 오류: {e}")
            return False
    
    def process_single_product(self, driver, product_id):
        """단일 상품 처리 (새 탭에서)"""
        try:
            self.log(f"📦 상품 처리 중: {product_id}")
            
            # 페이지 로딩 대기
            time.sleep(2)
            
            # 썸네일 번역
            thumbnail_ok = self.process_thumbnail_translation(driver)
            
            # 옵션 이미지 번역
            option_ok = self.process_option_image_translation(driver)
            
            if thumbnail_ok or option_ok:
                self.stats["success"] += 1
                self.log(f"✅ 상품 완료: {product_id}")
                return True
            else:
                self.stats["failed"] += 1
                self.log(f"❌ 상품 실패: {product_id}")
                return False
                
        except Exception as e:
            self.stats["failed"] += 1
            self.log(f"❌ 상품 처리 오류 ({product_id}): {e}")
            return False
    
    def get_product_ids_from_list(self, start_idx, count):
        """목록 페이지에서 상품 정보 가져오기 (AG Grid 방식)"""
        products = []
        seen_indices = set()
        
        try:
            # AG Grid 컨테이너 찾기
            grid_body = self.main_driver.find_element(By.CSS_SELECTOR, ".ag-body-viewport")
            
            # 먼저 스크롤을 맨 위로
            self.main_driver.execute_script("arguments[0].scrollTop = 0;", grid_body)
            time.sleep(0.5)
            
            # 시작 위치로 스크롤 (각 행 높이 약 126px)
            if start_idx > 1:
                scroll_position = (start_idx - 1) * 126
                self.main_driver.execute_script(f"arguments[0].scrollTop = {scroll_position};", grid_body)
                time.sleep(0.3)
            
            # 스크롤하며 필요한 만큼 수집
            no_new_count = 0
            
            while no_new_count < 3 and len(products) < count:
                # 현재 보이는 행 수집
                rows = self.main_driver.find_elements(By.CSS_SELECTOR, "div[role='row'][row-index]")
                new_found = 0
                
                for row in rows:
                    if len(products) >= count:
                        break
                    
                    try:
                        row_index = row.get_attribute("row-index")
                        if not row_index:
                            continue
                        
                        row_idx = int(row_index)
                        
                        # 시작 인덱스 이전은 스킵 (0-based index이므로 start_idx - 1과 비교)
                        if row_idx < start_idx - 1:
                            continue
                        
                        if row_index in seen_indices:
                            continue
                        
                        seen_indices.add(row_index)
                        new_found += 1
                        
                        # row-index 저장 (나중에 수정 버튼 클릭 시 사용)
                        products.append({
                            'row_index': row_idx,
                            'row_id': row.get_attribute("row-id")
                        })
                        
                    except Exception:
                        continue
                
                if len(products) >= count:
                    break
                
                # 새로운 행이 없으면 카운트 증가
                if new_found == 0:
                    no_new_count += 1
                else:
                    no_new_count = 0
                
                # 아래로 스크롤
                self.main_driver.execute_script(
                    "arguments[0].scrollTop += 400;", grid_body
                )
                time.sleep(0.2)
            
            # index 순으로 정렬 (가장 작은 것부터)
            products.sort(key=lambda p: p['row_index'])
            
            if products:
                self.log(f"📋 {len(products)}개 상품 발견 (row-index: {products[0]['row_index']}~{products[-1]['row_index']})")
            else:
                self.log("📋 상품을 찾을 수 없습니다")
            return products
            
        except Exception as e:
            self.log(f"❌ 상품 목록 가져오기 실패: {e}")
            import traceback
            self.log(traceback.format_exc())
            return []
    
    def click_edit_buttons_and_get_tabs(self, products):
        """수정 버튼 클릭하고 새 탭 핸들 반환"""
        original_handles = set(self.main_driver.window_handles)
        opened_products = []
        
        try:
            grid_body = self.main_driver.find_element(By.CSS_SELECTOR, ".ag-body-viewport")
        except:
            self.log("❌ AG Grid를 찾을 수 없습니다")
            return []
        
        for product in products:
            if not self.is_running:
                break
            
            row_index = product['row_index']
            
            try:
                # 해당 행으로 스크롤
                scroll_position = row_index * 126
                self.main_driver.execute_script(f"arguments[0].scrollTop = {scroll_position};", grid_body)
                time.sleep(0.2)
                
                # JavaScript에서 버튼 찾기 + 클릭
                result = self.main_driver.execute_script("""
                    const row = document.querySelector("div[role='row'][row-index='" + arguments[0] + "']");
                    if (!row) return 'row_not_found';
                    const btn = [...row.querySelectorAll('button')].find(b => b.innerText.trim() === '수정');
                    if (!btn) return 'btn_not_found';
                    btn.click();
                    return 'clicked';
                """, str(row_index))
                
                if result == 'clicked':
                    opened_products.append(product)
                    self.log(f"📝 수정 버튼 클릭 (row-index: {row_index})")
                else:
                    self.log(f"⚠️ 실패: {result} (row-index: {row_index})")
                
                time.sleep(1.5)
                
            except Exception as e:
                self.log(f"⚠️ 수정 버튼 클릭 실패 (row-index: {row_index}): {e}")
        
        # 새로 열린 탭 확인
        time.sleep(1)
        current_handles = set(self.main_driver.window_handles)
        new_handles = list(current_handles - original_handles)
        
        self.log(f"📑 {len(new_handles)}개 탭 열림")
        
        # 메인 탭으로 복귀
        if original_handles:
            main_handle = list(original_handles)[0]
            self.main_driver.switch_to.window(main_handle)
        
        return new_handles
    
    def process_single_tab(self, handle, results, index):
        """단일 탭 처리 (스레드용)"""
        try:
            self.main_driver.switch_to.window(handle)
            time.sleep(1)
            
            # URL에서 상품 ID 추출
            url = self.main_driver.current_url
            product_id = url.split('/')[-2] if url.endswith('/') else url.split('/')[-1]
            
            self.log(f"📦 [{index+1}] 상품 처리 시작: {product_id[:20]}...")
            
            # 썸네일 번역
            thumbnail_ok = self.process_thumbnail_translation(self.main_driver, index)
            
            # 옵션 이미지 번역
            option_ok = self.process_option_image_translation(self.main_driver, index)
            
            if thumbnail_ok or option_ok:
                results[index] = "success"
                self.stats["success"] += 1
                self.log(f"✅ [{index+1}] 완료: {product_id[:20]}...")
            else:
                results[index] = "failed"
                self.stats["failed"] += 1
                self.log(f"❌ [{index+1}] 실패: {product_id[:20]}...")
                
        except Exception as e:
            results[index] = "error"
            self.stats["failed"] += 1
            self.log(f"❌ [{index+1}] 오류: {e}")
    
    def process_batch(self, products):
        """배치 처리 (여러 탭 동시)"""
        if not products:
            return
        
        self.log(f"\n🔄 배치 시작: {len(products)}개 상품")
        
        # 1. 수정 버튼 클릭 → 새 탭 열기
        tab_handles = self.click_edit_buttons_and_get_tabs(products)
        
        if not tab_handles:
            self.log("⚠️ 열린 탭이 없습니다")
            return
        
        # 2. 각 탭에서 동시에 번역 시작
        results = {}
        threads = []
        
        do_thumbnail = self.translate_thumbnail_var.get() if self.translate_thumbnail_var else True
        do_option = self.translate_option_var.get() if self.translate_option_var else True
        
        if do_thumbnail:
            for i, handle in enumerate(tab_handles):
                if not self.is_running:
                    break
                
                try:
                    self.main_driver.switch_to.window(handle)
                    time.sleep(1)  # 페이지 로딩 대기
                    
                    url = self.main_driver.current_url
                    product_id = url.split('/')[-2] if url.endswith('/') else url.split('/')[-1]
                    
                    self.log(f"📦 [{i+1}] 번역 시작: {product_id[:20]}...")
                    
                    # 썸네일 탭 → 전체선택 → 번역 클릭
                    self._start_thumbnail_translation(i)
                    
                except Exception as e:
                    self.log(f"⚠️ [{i+1}] 시작 오류: {e}")
            
            # 3. 모든 탭의 번역 완료 대기
            self.log("⏳ 모든 탭 썸네일 번역 완료 대기...")
            self._wait_all_tabs_complete(tab_handles)
        else:
            self.log("ℹ️ 썸네일 번역 건너뜀 (체크 해제됨)")
        
        # 4. 옵션 이미지 번역도 동시 시작
        if do_option:
            self.log("🔄 옵션 이미지 번역 시작...")
            for i, handle in enumerate(tab_handles):
                if not self.is_running:
                    break
                try:
                    self.main_driver.switch_to.window(handle)
                    time.sleep(0.5)
                    self._start_option_translation(i)
                except Exception as e:
                    self.log(f"  [{i+1}] 옵션 탭 전환 오류: {e}")
            
            # 5. 옵션 번역 완료 대기
            self.log("⏳ 옵션 이미지 번역 완료 대기...")
            self._wait_all_tabs_complete(tab_handles)
        else:
            self.log("ℹ️ 옵션 이미지 번역 건너뜀 (체크 해제됨)")
        
        # 6. 모든 탭 닫기
        for handle in tab_handles:
            try:
                self.main_driver.switch_to.window(handle)
                self.main_driver.close()
                self.stats["success"] += 1
            except:
                pass
        
        # 7. 메인 탭으로 복귀
        handles = self.main_driver.window_handles
        if handles:
            self.main_driver.switch_to.window(handles[0])
        
        # 8. 처리된 상품들 "검수 완료" 상태로 변경
        time.sleep(0.5)
        self._set_products_complete(products)
        
        self.log(f"✅ 배치 완료")
    
    def _set_products_complete(self, products):
        """처리된 상품들을 검수 완료 상태로 변경 (참조 코드 방식)"""
        try:
            # AG Grid 컨테이너 찾기
            grid_body = self.main_driver.find_element(By.CSS_SELECTOR, ".ag-body-viewport")
            
            # 최상단으로 스크롤
            self.main_driver.execute_script("arguments[0].scrollTop = 0;", grid_body)
            time.sleep(0.3)
            
            selected_count = 0
            target_indices = {p['row_index'] for p in products}
            seen_indices = set()
            max_scroll_attempts = 50
            scroll_attempts = 0
            
            while selected_count < len(products) and scroll_attempts < max_scroll_attempts:
                # 현재 보이는 행들 가져오기
                rows = self.main_driver.find_elements(By.CSS_SELECTOR, "div[role='row'][row-index]")
                
                for row in rows:
                    if selected_count >= len(products):
                        break
                    
                    try:
                        row_index = row.get_attribute("row-index")
                        if not row_index:
                            continue
                        
                        row_idx = int(row_index)
                        
                        if row_index in seen_indices:
                            continue
                        seen_indices.add(row_index)
                        
                        # 처리한 상품만 선택
                        if row_idx not in target_indices:
                            continue
                        
                        # 체크박스 찾기
                        try:
                            checkbox = row.find_element(By.CSS_SELECTOR, "input.ag-checkbox-input")
                            self.main_driver.execute_script("arguments[0].click();", checkbox)
                            selected_count += 1
                            time.sleep(0.05)
                        except:
                            continue
                        
                    except:
                        continue
                
                if selected_count >= len(products):
                    break
                
                # 아래로 스크롤
                self.main_driver.execute_script("arguments[0].scrollTop += 400;", grid_body)
                time.sleep(0.2)
                scroll_attempts += 1
            
            self.log(f"  {selected_count}개 상품 선택됨")
            
            # grid에 포커스 주고 Insert 키
            self.main_driver.execute_script("arguments[0].focus();", grid_body)
            time.sleep(0.2)
            
            actions = ActionChains(self.main_driver)
            actions.send_keys(Keys.INSERT).perform()
            
            self.log(f"✅ {selected_count}개 상품 검수 완료 처리")
            time.sleep(0.3)
            
        except Exception as e:
            self.log(f"⚠️ 검수 완료 처리 실패: {e}")
    
    def _start_thumbnail_translation(self, tab_index):
        """썸네일 번역 시작 (재시도 포함)"""
        for retry in range(2):  # 최대 2번 시도
            try:
                # 페이지 로딩 대기
                time.sleep(0.5)
                
                # 썸네일 탭 클릭
                tab = self.find_tab_button(self.main_driver, "썸네일", timeout=3)
                if tab:
                    self.main_driver.execute_script("arguments[0].click();", tab)
                    time.sleep(0.5)
                
                # 전체 선택
                select_all = self.find_button_by_text(self.main_driver, "전체 선택", timeout=3)
                if select_all:
                    self.main_driver.execute_script("arguments[0].click();", select_all)
                    time.sleep(0.3)
                
                # 빠른 이미지 번역 클릭
                translate_btn = self.find_button_by_text(self.main_driver, "빠른 이미지 번역", timeout=3)
                if translate_btn:
                    self.main_driver.execute_script("arguments[0].click();", translate_btn)
                    self.log(f"  [{tab_index+1}] 썸네일 번역 시작")
                    return  # 성공
                    
            except Exception as e:
                if retry == 0:
                    time.sleep(1)  # 1초 대기 후 재시도
                else:
                    self.log(f"  [{tab_index+1}] 썸네일 스킵: {str(e)[:50]}")
    
    def _start_option_translation(self, tab_index):
        """옵션 이미지 번역 시작 (재시도 포함)"""
        for retry in range(2):  # 최대 2번 시도
            try:
                # 옵션 탭 클릭
                tab = self.find_tab_button(self.main_driver, "옵션", timeout=3)
                if tab:
                    self.main_driver.execute_script("arguments[0].click();", tab)
                    time.sleep(0.5)
                    if retry == 0:
                        self.log(f"  [{tab_index+1}] 옵션 탭 클릭")
                else:
                    self.log(f"  [{tab_index+1}] ⚠️ 옵션 탭 없음")
                    return
                
                # 이미지 일괄 편집 버튼 찾기
                batch_edit = self.find_button_by_text(self.main_driver, "이미지 일괄 편집", timeout=3)
                if batch_edit:
                    self.main_driver.execute_script("arguments[0].click();", batch_edit)
                    time.sleep(1.5)  # 모달 로딩 대기
                    if retry == 0:
                        self.log(f"  [{tab_index+1}] 이미지 일괄 편집 클릭")
                else:
                    self.log(f"  [{tab_index+1}] ⚠️ 이미지 일괄 편집 버튼 없음")
                    return
                
                # 전체 선택 버튼 찾기 (있으면 클릭)
                select_all = self.find_button_by_text(self.main_driver, "전체 선택", timeout=2)
                if select_all:
                    self.main_driver.execute_script("arguments[0].click();", select_all)
                    time.sleep(0.5)
                    if retry == 0:
                        self.log(f"  [{tab_index+1}] 전체 선택 클릭")
                
                # 이미지 번역하기 버튼 찾기
                translate_btn = self.find_button_by_text(self.main_driver, "이미지 번역하기", timeout=3)
                if translate_btn:
                    is_disabled = translate_btn.get_attribute("disabled")
                    if is_disabled:
                        self.log(f"  [{tab_index+1}] ⚠️ 번역 버튼 비활성화 (이미지 없음)")
                        return
                    self.main_driver.execute_script("arguments[0].click();", translate_btn)
                    self.log(f"  [{tab_index+1}] 옵션 이미지 번역 시작")
                    return  # 성공
                else:
                    if retry == 0:
                        # 모달 닫고 재시도
                        self.main_driver.execute_script("document.body.click();")
                        time.sleep(0.5)
                    else:
                        self.log(f"  [{tab_index+1}] ⚠️ 이미지 번역하기 버튼 없음")
                        
            except Exception as e:
                if retry == 0:
                    time.sleep(1)  # 1초 대기 후 재시도
                else:
                    self.log(f"  [{tab_index+1}] 옵션 스킵: {str(e)[:50]}")
    
    def _wait_all_tabs_complete(self, tab_handles, timeout=MAX_TRANSLATE_WAIT):
        """모든 탭의 번역 완료 대기 (토스트 메시지 감지)"""
        start_time = time.time()
        completed_tabs = set()
        
        while time.time() - start_time < timeout:
            if not self.is_running:
                return
            
            # 아직 완료 안 된 탭만 체크
            for handle in tab_handles:
                if handle in completed_tabs:
                    continue
                    
                try:
                    self.main_driver.switch_to.window(handle)
                    page_text = self.main_driver.page_source
                    
                    # 번역 완료 메시지 감지
                    if "이미지 번역이 완료되었습니다" in page_text:
                        completed_tabs.add(handle)
                    # 번역중이 아니면 완료로 처리 (메시지 놓친 경우)
                    elif "번역중" not in page_text:
                        completed_tabs.add(handle)
                except:
                    completed_tabs.add(handle)
            
            # 모두 완료됐는지 확인
            if len(completed_tabs) >= len(tab_handles):
                self.log("✅ 모든 탭 번역 완료")
                return
            
            # 대기 (탭 전환 간격 늘림)
            time.sleep(3)
        
        self.log("⚠️ 번역 대기 시간 초과")
    
    def process_products(self, start_idx, count, batch_size=3):
        """상품 처리 메인 루프"""
        self.stats = {"total": count, "success": 0, "failed": 0}
        
        self.log("\n" + "=" * 50)
        self.log(f"🚀 이미지 번역 자동화 시작")
        self.log(f"   시작: {start_idx}번 / 처리: {count}개 / 배치: {batch_size}개씩")
        self.log("=" * 50)
        
        try:
            # 전체 상품 정보 가져오기
            all_products = self.get_product_ids_from_list(start_idx, count)
            
            if not all_products:
                self.log("❌ 처리할 상품이 없습니다")
                return
            
            # 배치 단위로 처리
            for i in range(0, len(all_products), batch_size):
                if not self.is_running:
                    self.log("🛑 사용자에 의해 중지됨")
                    break
                
                batch = all_products[i:i + batch_size]
                self.process_batch(batch)
                
                # 진행률 업데이트
                processed = min(i + batch_size, len(all_products))
                if self.progress_callback:
                    self.progress_callback(processed, len(all_products))
                
                # 배치 사이 대기
                if i + batch_size < len(all_products):
                    time.sleep(2)
            
        except Exception as e:
            self.log(f"❌ 처리 중 오류: {e}")
            import traceback
            self.log(traceback.format_exc())
        
        finally:
            self.log("\n" + "=" * 50)
            self.log(f"📊 처리 결과")
            self.log(f"   성공: {self.stats['success']}개")
            self.log(f"   실패: {self.stats['failed']}개")
            self.log("=" * 50)
            
            self.is_running = False
            if self.finished_callback:
                self.finished_callback()
    
    def close(self):
        """리소스 정리"""
        if self.main_driver:
            try:
                self.main_driver.quit()
            except:
                pass


# ==================== GUI 클래스 ====================
class App(tk.Tk):
    """메인 GUI 애플리케이션"""
    
    def __init__(self):
        super().__init__()
        
        self.title("불사자 이미지 번역 자동화")
        self.geometry("700x600")
        self.resizable(True, True)
        
        # 설정 로드
        self.config_data = load_config()
        
        # 번역기 인스턴스
        self.translator = BulsajaImageTranslator(
            log_callback=self.log,
            progress_callback=self.update_progress,
            finished_callback=self.on_finished
        )
        
        self.worker_thread = None
        
        self.create_widgets()
        self.load_saved_settings()
        
        # 종료 시 정리
        self.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def create_widgets(self):
        """위젯 생성"""
        # 메인 프레임
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # === 연결 설정 ===
        conn_frame = ttk.LabelFrame(main_frame, text="크롬 연결", padding="10")
        conn_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 포트 설정
        port_frame = ttk.Frame(conn_frame)
        port_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(port_frame, text="디버그 포트:").pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value=str(DEBUG_PORT))
        ttk.Entry(port_frame, textvariable=self.port_var, width=10).pack(side=tk.LEFT, padx=5)
        
        self.btn_connect = ttk.Button(port_frame, text="🔗 크롬 실행 & 연결", command=self.connect)
        self.btn_connect.pack(side=tk.RIGHT)
        
        # === 작업 설정 ===
        work_frame = ttk.LabelFrame(main_frame, text="작업 설정", padding="10")
        work_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 첫 번째 줄: 시작번호, 처리개수
        row1 = ttk.Frame(work_frame)
        row1.pack(fill=tk.X, pady=2)
        
        ttk.Label(row1, text="시작 번호:").pack(side=tk.LEFT)
        self.start_var = tk.StringVar(value="1")
        ttk.Entry(row1, textvariable=self.start_var, width=8).pack(side=tk.LEFT, padx=(5, 20))
        
        ttk.Label(row1, text="처리 개수:").pack(side=tk.LEFT)
        self.count_var = tk.StringVar(value="10")
        ttk.Entry(row1, textvariable=self.count_var, width=8).pack(side=tk.LEFT, padx=5)
        
        # 두 번째 줄: 동시 탭 수
        row2 = ttk.Frame(work_frame)
        row2.pack(fill=tk.X, pady=2)
        
        ttk.Label(row2, text="동시 탭 수:").pack(side=tk.LEFT)
        self.batch_var = tk.StringVar(value="3")
        batch_combo = ttk.Combobox(row2, textvariable=self.batch_var, 
                                    values=["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"], width=5, state="readonly")
        batch_combo.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row2, text="(권장: 3~5개)").pack(side=tk.LEFT, padx=5)
        
        # === 번역 옵션 ===
        option_frame = ttk.LabelFrame(main_frame, text="번역 옵션", padding="10")
        option_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.thumbnail_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(option_frame, text="썸네일 이미지 번역", 
                        variable=self.thumbnail_var).pack(anchor=tk.W)
        
        self.option_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(option_frame, text="옵션 이미지 번역", 
                        variable=self.option_var).pack(anchor=tk.W)
        
        # === 진행 상태 ===
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.progress_var = tk.StringVar(value="대기 중...")
        ttk.Label(progress_frame, textvariable=self.progress_var).pack(side=tk.LEFT)
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress_bar.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))
        
        # === 버튼 ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.btn_start = ttk.Button(btn_frame, text="🚀 자동화 시작", command=self.start_automation)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 10))
        self.btn_start.config(state="disabled")
        
        self.btn_stop = ttk.Button(btn_frame, text="🛑 중지", command=self.stop)
        self.btn_stop.pack(side=tk.LEFT)
        self.btn_stop.config(state="disabled")
        
        # === 로그 ===
        log_frame = ttk.LabelFrame(main_frame, text="로그", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, state='disabled',
                                                   font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
    
    def load_saved_settings(self):
        """저장된 설정 로드"""
        if "port" in self.config_data:
            self.port_var.set(self.config_data["port"])
        if "batch_size" in self.config_data:
            self.batch_var.set(self.config_data["batch_size"])
        if "start_idx" in self.config_data:
            self.start_var.set(self.config_data["start_idx"])
        if "count" in self.config_data:
            self.count_var.set(self.config_data["count"])
    
    def save_settings(self):
        """설정 저장"""
        self.config_data["port"] = self.port_var.get()
        self.config_data["batch_size"] = self.batch_var.get()
        self.config_data["start_idx"] = self.start_var.get()
        self.config_data["count"] = self.count_var.get()
        save_config(self.config_data)
    
    def log(self, message):
        """로그 출력"""
        def _log():
            self.log_text.config(state='normal')
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')
        
        self.after(0, _log)
    
    def update_progress(self, current, total):
        """진행률 업데이트"""
        def _update():
            self.progress_var.set(f"{current}/{total} 처리 중...")
            self.progress_bar['value'] = (current / total) * 100
        
        self.after(0, _update)
    
    def connect(self):
        """크롬 연결"""
        self.btn_connect.config(state="disabled", text="연결 중...")
        self.save_settings()
        
        threading.Thread(target=self._connect_thread, daemon=True).start()
    
    def _connect_thread(self):
        """연결 스레드"""
        try:
            port = int(self.port_var.get())
        except:
            port = DEBUG_PORT
        
        self.log("🔧 초기화 중...")
        
        # 디버깅 크롬 실행
        if not self.translator.launch_debug_chrome(port):
            self.after(0, self._on_connect_failed)
            return
        
        # 연결 시도
        self.log("🔗 크롬에 연결 시도...")
        
        connected = False
        for attempt in range(10):
            if self.translator.connect_to_existing_chrome(port):
                connected = True
                break
            self.log(f"⏳ 연결 대기 중... ({attempt + 1}/10)")
            time.sleep(1)
        
        if connected:
            self.after(0, self._on_connect_success)
        else:
            self.log("❌ 크롬 연결 실패")
            self.after(0, self._on_connect_failed)
    
    def _on_connect_success(self):
        """연결 성공"""
        self.btn_connect.config(state="normal", text="🔄 재연결")
        self.btn_start.config(state="normal")
        self.log("")
        self.log("=" * 50)
        self.log("✅ 크롬 연결 성공!")
        self.log("📌 로그인 후 상품 리스트가 보이면")
        self.log("   '🚀 자동화 시작' 버튼을 클릭하세요")
        self.log("=" * 50)
    
    def _on_connect_failed(self):
        """연결 실패"""
        self.btn_connect.config(state="normal", text="🔗 크롬 실행 & 연결")
    
    def start_automation(self):
        """자동화 시작"""
        try:
            start_idx = int(self.start_var.get())
            count = int(self.count_var.get())
            batch_size = int(self.batch_var.get())
        except ValueError:
            messagebox.showerror("오류", "숫자를 입력하세요")
            return
        
        if count <= 0:
            messagebox.showwarning("경고", "처리 개수는 1 이상이어야 합니다")
            return
        
        msg = f"다음 설정으로 자동화를 시작합니다:\n\n"
        msg += f"• 시작 번호: {start_idx}\n"
        msg += f"• 처리 개수: {count}\n"
        msg += f"• 동시 탭 수: {batch_size}\n"
        msg += f"• 썸네일 번역: {'✅' if self.thumbnail_var.get() else '❌'}\n"
        msg += f"• 옵션 번역: {'✅' if self.option_var.get() else '❌'}\n\n"
        msg += "상품 리스트 화면이 준비되었나요?"
        
        if not messagebox.askyesno("확인", msg):
            return
        
        self.save_settings()
        
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_connect.config(state="disabled")
        
        # 체크박스 변수 translator에 전달
        self.translator.translate_thumbnail_var = self.thumbnail_var
        self.translator.translate_option_var = self.option_var
        
        self.translator.is_running = True
        self.worker_thread = threading.Thread(
            target=self.translator.process_products,
            args=(start_idx, count, batch_size),
            daemon=True
        )
        self.worker_thread.start()
    
    def stop(self):
        """중지"""
        self.translator.is_running = False
        self.log("🛑 중지 요청...")
    
    def on_finished(self):
        """완료 후"""
        def _finished():
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.btn_connect.config(state="normal", text="🔄 재연결")
            self.progress_var.set("완료")
        
        self.after(0, _finished)
    
    def on_close(self):
        """종료 시"""
        self.translator.is_running = False
        self.translator.close()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
