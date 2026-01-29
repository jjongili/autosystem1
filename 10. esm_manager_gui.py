"""
ESM Plus 상품 자동 관리 프로그램
- Selenium JavaScript fetch로 API 호출 (브라우저 세션 직접 사용)
- 브라우저 닫지 않고 유지
"""

import sys
import os
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTextEdit, QProgressBar,
    QMessageBox, QDialog, QFormLayout, QCheckBox, QGroupBox, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By


# ============================================
# 설정 파일 경로
# ============================================
CONFIG_DIR = Path.home() / ".esm_manager"
CONFIG_FILE = CONFIG_DIR / "accounts.json"


@dataclass
class Product:
    """상품 정보"""
    no: int
    goods_no: str
    gmkt_no: str
    iac_no: str


class AccountManager:
    """계정 저장/불러오기 관리"""
    
    def __init__(self):
        CONFIG_DIR.mkdir(exist_ok=True)
        self.accounts = self._load()
    
    def _load(self) -> Dict:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save(self):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.accounts, f, ensure_ascii=False, indent=2)
    
    def add_account(self, name: str, user_id: str, password: str = ""):
        self.accounts[name] = {"user_id": user_id, "password": password}
        self.save()
    
    def remove_account(self, name: str):
        if name in self.accounts:
            del self.accounts[name]
            self.save()
    
    def get_accounts(self) -> List[str]:
        return list(self.accounts.keys())
    
    def get_account(self, name: str) -> Optional[Dict]:
        return self.accounts.get(name)


class ESMSession:
    """ESM API 세션 관리 - Selenium JavaScript fetch 방식"""
    
    BASE_URL = "https://item.esmplus.com"
    LOGIN_URL = "https://signin.esmplus.com/login"
    
    SELL_STATUS = {
        "판매중": ["11"],
        "판매중지": ["21"],
        "품절": ["13"],
        "전체": ["11", "21", "13"],
    }
    
    def __init__(self):
        self.driver = None
        self.logged_in = False
        self.seller_id = ""  # X-A-Seller-Id, X-G-Seller-Id용
    
    def manual_login(self, user_id: str = "", password: str = "") -> bool:
        """브라우저 열어서 로그인 (ID/PW/버튼 자동)"""
        
        # seller_id 저장 (X-A-Seller-Id, X-G-Seller-Id 헤더용)
        self.seller_id = user_id
        
        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        self.driver = webdriver.Chrome(options=options)
        self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
        })
        
        self.driver.get(self.LOGIN_URL)
        time.sleep(2)
        
        # ID/PW 자동입력 및 로그인 버튼 클릭
        if user_id and password:
            try:
                # ID 입력
                for selector in ["input[type='text']", "input[name='id']", "input[id='id']"]:
                    try:
                        elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                        if elem.is_displayed():
                            elem.clear()
                            elem.send_keys(user_id)
                            break
                    except:
                        continue
                
                time.sleep(0.3)
                
                # PW 입력
                pw_input = None
                for selector in ["input[type='password']", "input[name='password']"]:
                    try:
                        elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                        if elem.is_displayed():
                            elem.clear()
                            elem.send_keys(password)
                            pw_input = elem
                            break
                    except:
                        continue
                
                time.sleep(0.3)
                print("ID/PW 자동입력 완료")
                
                # 로그인 버튼 클릭
                login_selectors = [
                    "button[type='submit']",
                    ".btn-login",
                    ".login-btn", 
                    "button.login",
                    "input[type='submit']",
                    ".btn-primary",
                ]
                
                clicked = False
                for selector in login_selectors:
                    try:
                        login_btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                        if login_btn.is_displayed():
                            login_btn.click()
                            clicked = True
                            print(f"로그인 버튼 클릭: {selector}")
                            break
                    except:
                        continue
                
                if not clicked and pw_input:
                    # Enter 키로 시도
                    print("로그인 버튼 못 찾음 - Enter 키로 시도")
                    pw_input.send_keys("\n")
                
            except Exception as e:
                print(f"자동입력 실패: {e}")
        
        return True
    
    def check_login_and_extract(self) -> bool:
        """로그인 확인"""
        
        if not self.driver:
            return False
        
        try:
            current_url = self.driver.current_url
            if "signin" in current_url.lower() or "login" in current_url.lower():
                return False
            
            # www.esmplus.com 상품관리 페이지로 이동
            self.driver.get("https://www.esmplus.com/Home/v2/goods-manage")
            time.sleep(5)
            
            current_url = self.driver.current_url
            if "signin" in current_url.lower() or "login" in current_url.lower():
                return False
            
            print(f"[DEBUG] 현재 URL: {current_url}")
            
            # iframe 찾기 및 전환
            try:
                iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                print(f"[DEBUG] iframe 개수: {len(iframes)}")
                
                for i, iframe in enumerate(iframes):
                    src = iframe.get_attribute('src') or ''
                    print(f"[DEBUG] iframe[{i}]: {src[:80]}")
                    
                    if 'item.esmplus.com' in src:
                        self.driver.switch_to.frame(iframe)
                        print(f"[DEBUG] iframe 전환 성공: {src[:80]}")
                        break
                else:
                    print("[DEBUG] item.esmplus.com iframe 없음, 기본 context 사용")
            except Exception as e:
                print(f"[DEBUG] iframe 전환 실패: {e}")
            
            # API 테스트
            test_result = self._js_fetch(
                "https://item.esmplus.com/api/ea/sellers/goodsManage/gridSetup",
                method="GET"
            )
            
            if test_result is None:
                print("[DEBUG] API 테스트 실패 - None")
                return False
            
            if test_result.get('error'):
                print(f"[DEBUG] API 에러: {test_result.get('error')}")
                return False
            
            print(f"[DEBUG] API 테스트 성공: {str(test_result)[:100]}")
            self.logged_in = True
            return True
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _js_fetch(self, url: str, method: str = "GET", body: dict = None, has_gmkt: bool = True, has_iac: bool = True) -> Optional[Dict]:
        """JavaScript fetch로 API 호출 (execute_async_script 사용)"""
        
        if not self.driver:
            return None
        
        # 브라우저 세션 유효성 검사
        try:
            _ = self.driver.current_url
        except:
            print("브라우저가 닫혔습니다. 재로그인 필요.")
            self.logged_in = False
            self.driver = None
            return None
        
        try:
            # Seller ID 헤더 - 사이트별로 다르게 설정
            seller_id = self.seller_id or ''
            g_seller_id = seller_id if has_gmkt else ""
            a_seller_id = seller_id if has_iac else ""
            
            if body:
                body_json = json.dumps(body)
                script = f'''
                    var callback = arguments[arguments.length - 1];
                    fetch("{url}", {{
                        method: "{method}",
                        headers: {{
                            "Content-Type": "application/json",
                            "Accept": "application/json, text/plain, */*",
                            "X-A-Seller-Id": "{a_seller_id}",
                            "X-G-Seller-Id": "{g_seller_id}",
                            "Origin": "https://item.esmplus.com",
                            "Referer": "https://item.esmplus.com/goods/list"
                        }},
                        body: JSON.stringify({body_json}),
                        credentials: "include"
                    }})
                    .then(response => response.json())
                    .then(data => callback(data))
                    .catch(err => callback({{error: err.message}}));
                '''
            else:
                script = f'''
                    var callback = arguments[arguments.length - 1];
                    fetch("{url}", {{
                        method: "{method}",
                        headers: {{
                            "Accept": "application/json, text/plain, */*",
                            "X-A-Seller-Id": "{a_seller_id}",
                            "X-G-Seller-Id": "{g_seller_id}",
                            "Origin": "https://item.esmplus.com",
                            "Referer": "https://item.esmplus.com/goods/list"
                        }},
                        credentials: "include"
                    }})
                    .then(response => response.json())
                    .then(data => callback(data))
                    .catch(err => callback({{error: err.message}}));
                '''
            
            self.driver.set_script_timeout(30)
            result = self.driver.execute_async_script(script)
            return result
            
        except Exception as e:
            error_msg = str(e)
            if "invalid session id" in error_msg.lower() or "no such window" in error_msg.lower():
                print("브라우저 세션이 종료되었습니다. 재로그인 필요.")
                self.logged_in = False
                self.driver = None
            else:
                print(f"JS Fetch error: {e}")
            return None
    
    def close_browser(self):
        """브라우저 닫기"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
    
    def search_products(
        self,
        sell_status: str = "판매중",
        keyword: str = "",
        page_size: int = 500,
        page_index: int = 1
    ) -> Optional[Dict]:
        """상품 검색"""
        
        if not self.logged_in:
            return None
        
        url = f"{self.BASE_URL}/api/ea/goods/search"
        status_codes = self.SELL_STATUS.get(sell_status, ["11"])
        
        payload = {
            "pageIndex": page_index,
            "pageSize": page_size,
            "query": {
                "goodsIds": "",
                "keyword": keyword,
                "sellStatus": status_codes,
                "category": {},
                "registrationDate": {},
                "shipping": {},
                "additionalService": []
            },
            "sortField": 0,
            "sortOrder": 1
        }
        
        return self._js_fetch(url, method="POST", body=payload)
    
    def get_all_products(self, sell_status: str = "판매중", keyword: str = "", log_callback=None) -> List[Product]:
        """전체 상품 조회"""
        
        def log(msg):
            if log_callback:
                log_callback(msg)
            print(msg)
        
        all_items = []
        page_index = 1
        
        while True:
            result = self.search_products(sell_status, keyword, 500, page_index)
            
            if not result:
                log(f"페이지 {page_index} 검색 실패")
                break
            
            if result.get('resultCode') != 0:
                log(f"페이지 {page_index} 에러: {result.get('message', 'Unknown')}")
                break
            
            items = result.get('data', {}).get('items', [])
            total = result.get('data', {}).get('total', 0)
            
            log(f"페이지 {page_index}: {len(items)}개 로드 (전체: {total}개)")
            
            if not items:
                break
            
            for item in items:
                site_goods = item.get('siteGoodsNo', {})
                product = Product(
                    no=item.get('no', 0),
                    goods_no=item.get('goodsNo', ''),
                    gmkt_no=site_goods.get('gmkt', '') or '',
                    iac_no=site_goods.get('iac', '') or ''
                )
                all_items.append(product)
            
            if len(all_items) >= total:
                break
            
            page_index += 1
            time.sleep(0.5)
        
        return all_items
    
    def change_sell_status(self, goods_no: str, is_sell: bool, has_gmkt: bool = True, has_iac: bool = True, log_callback=None) -> Dict:
        """판매상태 변경 - 등록된 사이트만 전송"""
        
        def log(msg):
            print(msg)
            if log_callback:
                log_callback(msg)
        
        if not self.logged_in:
            return {'resultCode': -1, 'message': 'Not logged in'}
        
        url = f"{self.BASE_URL}/api/ea/goods/{goods_no}/sellStatus"
        
        log(f"[DEBUG] has_gmkt={has_gmkt}, has_iac={has_iac}")
        
        # 등록된 사이트의 키만 포함 (null 안됨, 없는 사이트 키도 안됨)
        is_sell_data = {}
        if has_gmkt:
            is_sell_data["gmkt"] = is_sell
        if has_iac:
            is_sell_data["iac"] = is_sell
        
        if not is_sell_data:
            return {'resultCode': -1, 'message': 'No site registered'}
        
        payload = {"isSell": is_sell_data}
        
        log(f"[DEBUG] Payload: {json.dumps(payload)}")
        log(f"[DEBUG] Headers: X-G-Seller-Id={self.seller_id if has_gmkt else ''}, X-A-Seller-Id={self.seller_id if has_iac else ''}")
        
        result = self._js_fetch(url, method="PUT", body=payload, has_gmkt=has_gmkt, has_iac=has_iac)
        
        if result is None:
            return {'resultCode': -1, 'message': 'JS Fetch failed'}
        
        return result
    
    def delete_product(self, goods_no: str, has_gmkt: bool = True, has_iac: bool = True) -> Dict:
        """상품 삭제"""
        
        if not self.logged_in:
            return {'resultCode': -1, 'message': 'Not logged in'}
        
        url = f"{self.BASE_URL}/api/ea/goods/{goods_no}"
        
        result = self._js_fetch(url, method="DELETE", has_gmkt=has_gmkt, has_iac=has_iac)
        
        if result is None:
            return {'resultCode': -1, 'message': 'JS Fetch failed'}
        
        return result


# ============================================
# Worker Thread (순차 처리 - 브라우저 사용)
# ============================================
class WorkerThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)
    
    def __init__(self, session: ESMSession, products: List[Product], action: str):
        super().__init__()
        self.session = session
        self.products = products
        self.action = action
        self._stop_flag = False
    
    def stop(self):
        self._stop_flag = True
    
    def run(self):
        results = {'success': 0, 'failed': 0, 'errors': []}
        total = len(self.products)
        
        if self.action == 'stop_and_delete':
            # 1단계: 판매중지
            self.progress.emit(0, total, "1단계: 판매중지...")
            for i, product in enumerate(self.products):
                if self._stop_flag:
                    break
                
                result = self.session.change_sell_status(
                    product.goods_no, False,
                    bool(product.gmkt_no), bool(product.iac_no)
                )
                
                self.progress.emit(i + 1, total, f"판매중지 {i+1}/{total}")
                time.sleep(0.1)
            
            time.sleep(1)
            
            # 2단계: 삭제
            self.progress.emit(0, total, "2단계: 삭제...")
            for i, product in enumerate(self.products):
                if self._stop_flag:
                    break
                
                result = self.session.delete_product(
                    product.goods_no,
                    bool(product.gmkt_no), bool(product.iac_no)
                )
                
                if result.get('resultCode') == 0:
                    results['success'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append({
                        'goods_no': product.goods_no,
                        'message': result.get('message', 'Unknown')
                    })
                
                self.progress.emit(i + 1, total, f"삭제 {i+1}/{total}")
                time.sleep(0.1)
        else:
            for i, product in enumerate(self.products):
                if self._stop_flag:
                    break
                
                if self.action == 'stop':
                    result = self.session.change_sell_status(
                        product.goods_no, False,
                        bool(product.gmkt_no), bool(product.iac_no)
                    )
                elif self.action == 'start':
                    result = self.session.change_sell_status(
                        product.goods_no, True,
                        bool(product.gmkt_no), bool(product.iac_no)
                    )
                elif self.action == 'delete':
                    result = self.session.delete_product(
                        product.goods_no,
                        bool(product.gmkt_no), bool(product.iac_no)
                    )
                
                if result.get('resultCode') == 0:
                    results['success'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append({
                        'goods_no': product.goods_no,
                        'message': result.get('message', 'Unknown')
                    })
                
                self.progress.emit(i + 1, total, f"처리중 {i+1}/{total}")
                time.sleep(0.1)
        
        self.finished.emit(results)


# ============================================
# Login Dialog
# ============================================
class LoginDialog(QDialog):
    def __init__(self, account_manager: AccountManager, parent=None):
        super().__init__(parent)
        self.account_manager = account_manager
        self.session = None
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("ESM Plus 로그인")
        self.setFixedSize(400, 300)
        
        layout = QVBoxLayout()
        
        # 계정 선택
        account_layout = QHBoxLayout()
        account_layout.addWidget(QLabel("저장된 계정:"))
        
        self.account_combo = QComboBox()
        self.account_combo.addItem("-- 새 계정 --")
        for name in self.account_manager.get_accounts():
            self.account_combo.addItem(name)
        self.account_combo.currentTextChanged.connect(self.on_account_selected)
        account_layout.addWidget(self.account_combo)
        
        self.delete_btn = QPushButton("삭제")
        self.delete_btn.setFixedWidth(50)
        self.delete_btn.clicked.connect(self.delete_account)
        account_layout.addWidget(self.delete_btn)
        
        layout.addLayout(account_layout)
        
        # 계정 정보 입력
        form_layout = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("계정 별명 (저장용)")
        form_layout.addRow("계정 이름:", self.name_edit)
        
        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("ESM Plus 아이디")
        form_layout.addRow("아이디:", self.id_edit)
        
        self.pw_edit = QLineEdit()
        self.pw_edit.setPlaceholderText("ESM Plus 비밀번호")
        self.pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form_layout.addRow("비밀번호:", self.pw_edit)
        
        layout.addLayout(form_layout)
        
        # 저장 체크박스
        save_layout = QHBoxLayout()
        self.save_check = QCheckBox("계정 저장")
        self.save_check.setChecked(True)
        save_layout.addWidget(self.save_check)
        
        self.save_pw_check = QCheckBox("비밀번호도 저장")
        self.save_pw_check.setChecked(False)
        save_layout.addWidget(self.save_pw_check)
        save_layout.addStretch()
        
        layout.addLayout(save_layout)
        
        # 안내
        info_label = QLabel("※ ID/PW 자동입력 및 로그인 버튼 클릭됨\n   캡차/2FA만 처리 후 '로그인 완료' 클릭")
        info_label.setStyleSheet("color: #666; margin: 10px 0;")
        layout.addWidget(info_label)
        
        # 버튼
        btn_layout = QHBoxLayout()
        
        self.open_browser_btn = QPushButton("브라우저 열기")
        self.open_browser_btn.clicked.connect(self.open_browser)
        btn_layout.addWidget(self.open_browser_btn)
        
        self.confirm_btn = QPushButton("로그인 완료")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self.confirm_login)
        btn_layout.addWidget(self.confirm_btn)
        
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
    
    def on_account_selected(self, name: str):
        if name == "-- 새 계정 --":
            self.name_edit.clear()
            self.id_edit.clear()
            self.pw_edit.clear()
            self.name_edit.setEnabled(True)
        else:
            account = self.account_manager.get_account(name)
            if account:
                self.name_edit.setText(name)
                self.id_edit.setText(account.get('user_id', ''))
                self.pw_edit.setText(account.get('password', ''))
                self.name_edit.setEnabled(False)
    
    def delete_account(self):
        name = self.account_combo.currentText()
        if name != "-- 새 계정 --":
            reply = QMessageBox.question(self, "계정 삭제", f"'{name}' 계정을 삭제하시겠습니까?")
            if reply == QMessageBox.StandardButton.Yes:
                self.account_manager.remove_account(name)
                self.account_combo.removeItem(self.account_combo.currentIndex())
    
    def open_browser(self):
        user_id = self.id_edit.text().strip()
        password = self.pw_edit.text().strip()
        
        if not user_id or not password:
            QMessageBox.warning(self, "입력 오류", "아이디와 비밀번호를 입력하세요.")
            return
        
        self.session = ESMSession()
        self.session.manual_login(user_id, password)
        
        self.open_browser_btn.setEnabled(False)
        self.confirm_btn.setEnabled(True)
        
        QMessageBox.information(self, "안내", 
            "ID/PW 입력 및 로그인 버튼 클릭 완료!\n"
            "캡차나 2FA가 있으면 처리하세요.\n\n"
            "로그인 완료 후 '로그인 완료' 버튼을 클릭하세요.")
    
    def confirm_login(self):
        if not self.session:
            return
        
        if self.session.check_login_and_extract():
            if self.save_check.isChecked():
                name = self.name_edit.text().strip()
                user_id = self.id_edit.text().strip()
                password = self.pw_edit.text().strip() if self.save_pw_check.isChecked() else ""
                if name and user_id:
                    self.account_manager.add_account(name, user_id, password)
            
            # 브라우저 닫지 않음!
            self.accept()
        else:
            QMessageBox.warning(self, "실패", "로그인이 확인되지 않았습니다.")
    
    def reject(self):
        if self.session:
            self.session.close_browser()
        super().reject()
    
    def get_session(self) -> Optional[ESMSession]:
        return self.session


# ============================================
# Main Window
# ============================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.account_manager = AccountManager()
        self.session = None
        self.products = []
        self.worker = None
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("ESM Plus 상품 관리 (브라우저 모드)")
        self.setMinimumSize(800, 600)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # 상단
        top_layout = QHBoxLayout()
        
        self.status_label = QLabel("● 로그인 필요")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        top_layout.addWidget(self.status_label)
        
        top_layout.addStretch()
        
        self.login_btn = QPushButton("로그인")
        self.login_btn.clicked.connect(self.show_login)
        top_layout.addWidget(self.login_btn)
        
        layout.addLayout(top_layout)
        
        # 검색
        search_group = QGroupBox("상품 검색")
        search_layout = QHBoxLayout()
        
        search_layout.addWidget(QLabel("상태:"))
        self.status_combo = QComboBox()
        self.status_combo.addItems(["판매중", "판매중지", "품절", "전체"])
        search_layout.addWidget(self.status_combo)
        
        search_layout.addWidget(QLabel("키워드:"))
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("검색어 (선택)")
        search_layout.addWidget(self.keyword_edit)
        
        self.search_btn = QPushButton("검색")
        self.search_btn.clicked.connect(self.search_products)
        self.search_btn.setEnabled(False)
        search_layout.addWidget(self.search_btn)
        
        search_group.setLayout(search_layout)
        layout.addWidget(search_group)
        
        # 테이블
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["No", "상품번호", "G마켓", "옥션"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        
        # 작업
        action_group = QGroupBox("일괄 작업")
        action_layout = QHBoxLayout()
        
        action_layout.addStretch()
        
        self.test_btn = QPushButton("테스트(1개)")
        self.test_btn.clicked.connect(self.test_single)
        self.test_btn.setEnabled(False)
        action_layout.addWidget(self.test_btn)
        
        self.stop_btn = QPushButton("판매중지")
        self.stop_btn.clicked.connect(lambda: self.execute_action('stop'))
        self.stop_btn.setEnabled(False)
        action_layout.addWidget(self.stop_btn)
        
        self.start_btn = QPushButton("판매재개")
        self.start_btn.clicked.connect(lambda: self.execute_action('start'))
        self.start_btn.setEnabled(False)
        action_layout.addWidget(self.start_btn)
        
        self.delete_btn = QPushButton("삭제")
        self.delete_btn.setStyleSheet("background-color: #ff6b6b; color: white;")
        self.delete_btn.clicked.connect(lambda: self.execute_action('stop_and_delete'))
        self.delete_btn.setEnabled(False)
        action_layout.addWidget(self.delete_btn)
        
        action_group.setLayout(action_layout)
        layout.addWidget(action_group)
        
        # 진행바
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # 로그
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        layout.addWidget(self.log_text)
    
    def log(self, msg: str):
        self.log_text.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
    
    def show_login(self):
        dialog = LoginDialog(self.account_manager, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.session = dialog.get_session()
            if self.session and self.session.logged_in:
                self.status_label.setText("● 로그인됨 (브라우저 유지)")
                self.status_label.setStyleSheet("color: green; font-weight: bold;")
                self.login_btn.setText("재로그인")
                self.search_btn.setEnabled(True)
                self.log(f"로그인 성공 - Seller ID: {self.session.seller_id}")
    
    def search_products(self):
        if not self.session:
            return
        
        status = self.status_combo.currentText()
        keyword = self.keyword_edit.text().strip()
        
        self.log(f"검색중... (상태: {status})")
        self.search_btn.setEnabled(False)
        QApplication.processEvents()
        
        self.products = self.session.get_all_products(status, keyword, self.log)
        
        self.table.setRowCount(len(self.products))
        for i, p in enumerate(self.products):
            self.table.setItem(i, 0, QTableWidgetItem(str(p.no)))
            self.table.setItem(i, 1, QTableWidgetItem(p.goods_no))
            self.table.setItem(i, 2, QTableWidgetItem(p.gmkt_no))
            self.table.setItem(i, 3, QTableWidgetItem(p.iac_no))
        
        self.log(f"검색 완료: {len(self.products)}개")
        self.search_btn.setEnabled(True)
        
        has_products = len(self.products) > 0
        self.test_btn.setEnabled(has_products)
        self.stop_btn.setEnabled(has_products)
        self.start_btn.setEnabled(has_products)
        self.delete_btn.setEnabled(has_products)
    
    def test_single(self):
        if not self.products:
            return
        
        p = self.products[0]
        self.log(f"=== 테스트: {p.goods_no} ===")
        self.log(f"G마켓: '{p.gmkt_no}', 옥션: '{p.iac_no}'")
        self.log(f"has_gmkt={bool(p.gmkt_no)}, has_iac={bool(p.iac_no)}")
        
        result = self.session.change_sell_status(
            p.goods_no, False,
            bool(p.gmkt_no), bool(p.iac_no),
            log_callback=self.log
        )
        
        self.log(f"응답: {result}")
        
        if result.get('resultCode') == 0:
            self.log("✓ 성공!")
            QMessageBox.information(self, "성공", "테스트 성공!")
        else:
            self.log(f"✗ 실패: {result.get('message')}")
            QMessageBox.warning(self, "실패", f"에러: {result.get('message')}")
    
    def execute_action(self, action: str):
        if not self.products:
            return
        
        action_names = {'stop': '판매중지', 'start': '판매재개', 'stop_and_delete': '삭제'}
        
        if action == 'stop_and_delete':
            reply = QMessageBox.warning(self, "⚠️ 경고",
                f"{len(self.products)}개 상품을 삭제합니다.\n복구 불가!\n\n계속?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        else:
            reply = QMessageBox.question(self, "확인",
                f"{len(self.products)}개 상품을 {action_names[action]}?")

        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self.set_ui_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(self.products))
        
        self.log(f"{action_names[action]} 시작 ({len(self.products)}개)")
        
        self.worker = WorkerThread(self.session, self.products, action)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()
    
    def on_progress(self, current: int, total: int, msg: str):
        self.progress_bar.setValue(current)
        if current % 50 == 0:
            self.log(msg)
    
    def on_finished(self, results: Dict):
        self.progress_bar.setVisible(False)
        self.set_ui_enabled(True)
        
        self.log(f"완료 - 성공: {results['success']}, 실패: {results['failed']}")
        
        if results.get('errors'):
            for err in results['errors'][:5]:
                self.log(f"  ✗ {err['goods_no']}: {err['message']}")
        
        QMessageBox.information(self, "완료",
            f"성공: {results['success']}\n실패: {results['failed']}")
        
        self.search_products()
    
    def set_ui_enabled(self, enabled: bool):
        self.search_btn.setEnabled(enabled)
        self.test_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(enabled)
        self.start_btn.setEnabled(enabled)
        self.delete_btn.setEnabled(enabled)
        self.login_btn.setEnabled(enabled)
    
    def closeEvent(self, event):
        if self.session:
            reply = QMessageBox.question(self, "종료",
                "브라우저도 닫으시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.session.close_browser()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    font = QFont()
    font.setPointSize(10)
    app.setFont(font)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
