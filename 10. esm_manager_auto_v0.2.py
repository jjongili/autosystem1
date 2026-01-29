"""
ESM Plus 상품 자동 삭제 프로그램
- 계정 리스트 자동 로그인
- 전체 상품 자동 삭제 (판매중지 → 삭제)
- 무인 실행 가능
"""

import sys
import json
import time
from typing import Optional, List, Dict
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QProgressBar, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QSpinBox, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


@dataclass
class Product:
    goods_no: str
    gmkt_no: str
    iac_no: str
    sale_count: int = 0  # 판매 이력


@dataclass
class Account:
    name: str
    user_id: str
    password: str
    status: str = "대기"
    total: int = 0
    deleted: int = 0


class ESMAutoSession:
    """ESM 자동 세션"""
    
    BASE_URL = "https://item.esmplus.com"
    LOGIN_URL = "https://signin.esmplus.com/login"
    
    def __init__(self):
        self.driver = None
        self.seller_id = ""
        self.logged_in = False
    
    def auto_login(self, user_id: str, password: str, log_callback=None) -> bool:
        """완전 자동 로그인"""
        
        def log(msg):
            print(msg)
            if log_callback:
                log_callback(msg)
        
        try:
            options = Options()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            self.driver = webdriver.Chrome(options=options)
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
            })
            
            log(f"로그인 시도: {user_id}")
            self.driver.get(self.LOGIN_URL)
            time.sleep(2)
            
            # ID 입력
            try:
                id_input = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'], input[name='id']"))
                )
                id_input.clear()
                id_input.send_keys(user_id)
                time.sleep(0.3)
            except Exception as e:
                log(f"ID 입력 실패: {e}")
                return False
            
            # PW 입력
            try:
                pw_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='password']")
                pw_input.clear()
                pw_input.send_keys(password)
                time.sleep(0.3)
            except Exception as e:
                log(f"PW 입력 실패: {e}")
                return False
            
            # 로그인 버튼 클릭
            try:
                # 다양한 셀렉터 시도
                login_selectors = [
                    "button[type='submit']",
                    ".btn-login",
                    ".login-btn", 
                    "button.login",
                    "input[type='submit']",
                    ".btn-primary",
                    "#loginButton",
                    ".login_btn",
                ]
                
                clicked = False
                for selector in login_selectors:
                    try:
                        login_btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                        if login_btn.is_displayed():
                            login_btn.click()
                            clicked = True
                            log(f"로그인 버튼 클릭 (CSS): {selector}")
                            break
                    except:
                        continue
                
                # CSS 셀렉터 실패시 XPath로 텍스트 기반 검색
                if not clicked:
                    xpath_selectors = [
                        "//button[contains(text(), '로그인')]",
                        "//input[@value='로그인']",
                        "//a[contains(text(), '로그인')]",
                        "//button[contains(@class, 'login')]",
                        "//div[contains(@class, 'login')]//button",
                        "//form//button",
                        "//button",
                    ]
                    
                    for xpath in xpath_selectors:
                        try:
                            login_btn = self.driver.find_element(By.XPATH, xpath)
                            if login_btn.is_displayed():
                                login_btn.click()
                                clicked = True
                                log(f"로그인 버튼 클릭 (XPath): {xpath}")
                                break
                        except:
                            continue
                
                if not clicked:
                    # Enter 키로 시도
                    log("로그인 버튼 못 찾음 - Enter 키로 시도")
                    pw_input.send_keys("\n")
                
                time.sleep(5)
            except Exception as e:
                log(f"로그인 버튼 클릭 실패: {e}")
                pw_input.send_keys("\n")
                time.sleep(5)
            
            # 로그인 성공 확인
            current_url = self.driver.current_url
            log(f"현재 URL: {current_url}")
            if "signin" in current_url.lower() or "login" in current_url.lower():
                log("로그인 실패 - 아직 로그인 페이지")
                return False
            
            # Seller ID 먼저 설정 (API 호출에 필요)
            self.seller_id = user_id
            
            # 상품관리 페이지로 이동
            self.driver.get("https://www.esmplus.com/Home/v2/goods-manage")
            time.sleep(5)
            
            # 로그인 페이지로 리다이렉트 확인
            current_url = self.driver.current_url
            log(f"상품관리 페이지 URL: {current_url}")
            if "signin" in current_url.lower() or "login" in current_url.lower():
                log("세션 만료 - 로그인 페이지로 리다이렉트됨")
                return False
            
            # item.esmplus.com으로 이동 (API 호출용)
            self.driver.get("https://item.esmplus.com/goods/list")
            time.sleep(3)
            
            # API 테스트
            log("API 테스트 중...")
            test_result = self._js_fetch(
                "https://item.esmplus.com/api/ea/sellers/goodsManage/gridSetup",
                method="GET"
            )
            
            log(f"API 테스트 결과: {test_result}")
            
            if test_result is None or test_result.get('error'):
                log(f"API 테스트 실패: {test_result}")
                return False
            
            self.logged_in = True
            log(f"로그인 성공: {user_id}")
            return True
            
        except Exception as e:
            log(f"로그인 에러: {e}")
            return False
    
    def _js_fetch(self, url: str, method: str = "GET", body: dict = None, 
                  has_gmkt: bool = True, has_iac: bool = True) -> Optional[Dict]:
        """JavaScript fetch API 호출"""
        
        if not self.driver:
            return None
        
        # 브라우저 세션 유효성 검사
        try:
            _ = self.driver.current_url
        except:
            print("브라우저가 닫혔습니다.")
            self.logged_in = False
            self.driver = None
            return None
        
        try:
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
                print("브라우저 세션이 종료되었습니다.")
                self.logged_in = False
                self.driver = None
            else:
                print(f"JS Fetch error: {e}")
            return None
    
    def get_all_products(self, log_callback=None) -> List[Product]:
        """전체 상품 조회 (판매중 + 판매중지)"""
        
        def log(msg):
            if log_callback:
                log_callback(msg)
        
        all_items = []
        
        # 판매중 + 판매중지 상품 모두 조회
        for status_name, status_codes in [("판매중", ["11"]), ("판매중지", ["21"])]:
            page_index = 1
            
            while True:
                url = f"{self.BASE_URL}/api/ea/goods/search"
                payload = {
                    "pageIndex": page_index,
                    "pageSize": 500,
                    "query": {
                        "goodsIds": "",
                        "keyword": "",
                        "sellStatus": status_codes,
                        "category": {},
                        "registrationDate": {},
                        "shipping": {},
                        "additionalService": []
                    },
                    "sortField": 0,
                    "sortOrder": 1
                }
                
                result = self._js_fetch(url, method="POST", body=payload)
                
                if not result or result.get('resultCode') != 0:
                    break
                
                items = result.get('data', {}).get('items', [])
                total = result.get('data', {}).get('total', 0)
                
                log(f"{status_name} 페이지 {page_index}: {len(items)}개 (전체: {total}개)")
                
                # 첫 페이지 첫 상품의 정산금액 로그 (디버그용)
                if page_index == 1 and items:
                    first_item = items[0]
                    settle = first_item.get('settleMoney', {})
                    log(f"[DEBUG] 첫 상품 정산금액: gmkt={settle.get('gmkt', 0)}, iac={settle.get('iac', 0)}")
                
                if not items:
                    break
                
                for item in items:
                    site_goods = item.get('siteGoodsNo', {})
                    
                    # 판매 이력 확인 - settleMoney (정산금액)
                    settle_money = item.get('settleMoney', {})
                    sale_count = 0
                    if isinstance(settle_money, dict):
                        gmkt_settle = settle_money.get('gmkt', 0) or 0
                        iac_settle = settle_money.get('iac', 0) or 0
                        sale_count = gmkt_settle + iac_settle
                    
                    product = Product(
                        goods_no=item.get('goodsNo', ''),
                        gmkt_no=site_goods.get('gmkt', '') or '',
                        iac_no=site_goods.get('iac', '') or '',
                        sale_count=sale_count
                    )
                    all_items.append(product)
                
                if len(items) < 500:
                    break
                
                page_index += 1
                time.sleep(0.3)
        
        return all_items
    
    def change_sell_status(self, goods_no: str, is_sell: bool, 
                           has_gmkt: bool, has_iac: bool) -> Dict:
        """판매상태 변경"""
        
        url = f"{self.BASE_URL}/api/ea/goods/{goods_no}/sellStatus"
        
        is_sell_data = {}
        if has_gmkt:
            is_sell_data["gmkt"] = is_sell
        if has_iac:
            is_sell_data["iac"] = is_sell
        
        if not is_sell_data:
            return {'resultCode': -1, 'message': 'No site'}
        
        payload = {"isSell": is_sell_data}
        result = self._js_fetch(url, method="PUT", body=payload, 
                                has_gmkt=has_gmkt, has_iac=has_iac)
        
        return result or {'resultCode': -1, 'message': 'Failed'}
    
    def delete_product(self, goods_no: str, has_gmkt: bool, has_iac: bool) -> Dict:
        """상품 삭제"""
        
        url = f"{self.BASE_URL}/api/ea/goods/{goods_no}"
        result = self._js_fetch(url, method="DELETE", has_gmkt=has_gmkt, has_iac=has_iac)
        
        return result or {'resultCode': -1, 'message': 'Failed'}
    
    def close(self):
        """브라우저 닫기"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None


class AutoDeleteWorker(QThread):
    """자동 삭제 워커"""
    
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int, str)  # current, total, message
    account_updated = pyqtSignal(int, str, int, int)  # index, status, total, deleted
    finished_signal = pyqtSignal()
    
    def __init__(self, accounts: List[Account], delay: float = 0.1, skip_sold: bool = True):
        super().__init__()
        self.accounts = accounts
        self.delay = delay
        self.skip_sold = skip_sold
        self._stop_flag = False
    
    def stop(self):
        self._stop_flag = True
    
    def log(self, msg: str):
        self.log_signal.emit(msg)
    
    def run(self):
        for idx, account in enumerate(self.accounts):
            if self._stop_flag:
                break
            
            self.log(f"\n{'='*50}")
            self.log(f"계정 처리 시작: {account.name} ({account.user_id})")
            self.log(f"{'='*50}")
            
            self.account_updated.emit(idx, "로그인중...", 0, 0)
            
            session = ESMAutoSession()
            
            # 로그인
            if not session.auto_login(account.user_id, account.password, self.log):
                self.log(f"❌ 로그인 실패: {account.user_id}")
                self.account_updated.emit(idx, "로그인실패", 0, 0)
                session.close()
                continue
            
            self.account_updated.emit(idx, "상품조회중...", 0, 0)
            
            # 상품 조회
            products = session.get_all_products(self.log)
            total = len(products)
            
            self.log(f"총 {total}개 상품 발견")
            
            # 판매이력 있는 상품 필터링
            if self.skip_sold:
                sold_products = [p for p in products if p.sale_count > 0]
                products = [p for p in products if p.sale_count == 0]
                skipped = len(sold_products)
                if skipped > 0:
                    self.log(f"⚠️ 판매이력 있는 상품 {skipped}개 제외")
                total = len(products)
                self.log(f"삭제 대상: {total}개")
            
            self.account_updated.emit(idx, "처리중...", total, 0)
            
            if total == 0:
                self.log("삭제할 상품 없음")
                self.account_updated.emit(idx, "완료(0개)", 0, 0)
                session.close()
                continue
            
            deleted = 0
            failed = 0
            
            # 1단계: 전체 판매중지
            self.log(f"\n[1단계] 판매중지 처리...")
            for i, p in enumerate(products):
                if self._stop_flag:
                    break
                
                result = session.change_sell_status(
                    p.goods_no, False,
                    bool(p.gmkt_no), bool(p.iac_no)
                )
                
                if (i + 1) % 50 == 0:
                    self.log(f"판매중지: {i+1}/{total}")
                    self.progress_signal.emit(i + 1, total, f"판매중지 {i+1}/{total}")
                
                time.sleep(self.delay)
            
            time.sleep(1)
            
            # 2단계: 전체 삭제
            self.log(f"\n[2단계] 삭제 처리...")
            for i, p in enumerate(products):
                if self._stop_flag:
                    break
                
                result = session.delete_product(
                    p.goods_no,
                    bool(p.gmkt_no), bool(p.iac_no)
                )
                
                if result.get('resultCode') == 0:
                    deleted += 1
                else:
                    failed += 1
                    # 처음 5개 실패에 대해서만 에러 로그 출력
                    if failed <= 5:
                        self.log(f"삭제 실패 [{p.goods_no}]: {result}")
                
                if (i + 1) % 50 == 0:
                    self.log(f"삭제: {i+1}/{total} (성공: {deleted}, 실패: {failed})")
                    self.progress_signal.emit(i + 1, total, f"삭제 {i+1}/{total}")
                    self.account_updated.emit(idx, "처리중...", total, deleted)
                
                time.sleep(self.delay)
            
            self.log(f"\n✅ 완료: {account.user_id}")
            self.log(f"   총: {total}, 삭제: {deleted}, 실패: {failed}")
            self.account_updated.emit(idx, f"완료", total, deleted)
            
            session.close()
            time.sleep(2)  # 계정 간 딜레이
        
        self.finished_signal.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.accounts: List[Account] = []
        self.worker = None
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("ESM Plus 자동 삭제")
        self.setMinimumSize(900, 700)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # 계정 입력 영역
        account_group = QGroupBox("계정 리스트 (한 줄에 하나씩: 이름,아이디,비밀번호)")
        account_layout = QVBoxLayout()
        
        self.account_input = QTextEdit()
        self.account_input.setPlaceholderText(
            "예시:\n"
            "스토어1,myid1,mypassword1\n"
            "스토어2,myid2,mypassword2\n"
            "스토어3,myid3,mypassword3"
        )
        self.account_input.setMaximumHeight(150)
        account_layout.addWidget(self.account_input)
        
        btn_layout = QHBoxLayout()
        self.load_btn = QPushButton("계정 로드")
        self.load_btn.clicked.connect(self.load_accounts)
        btn_layout.addWidget(self.load_btn)
        
        btn_layout.addStretch()
        
        btn_layout.addWidget(QLabel("처리 딜레이(초):"))
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 10)
        self.delay_spin.setValue(1)
        self.delay_spin.setFixedWidth(60)
        btn_layout.addWidget(self.delay_spin)
        
        # 판매이력 제외 옵션
        self.skip_sold_check = QCheckBox("판매이력 있는 상품 제외")
        self.skip_sold_check.setChecked(True)
        btn_layout.addWidget(self.skip_sold_check)
        
        account_layout.addLayout(btn_layout)
        account_group.setLayout(account_layout)
        layout.addWidget(account_group)
        
        # 계정 테이블
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["이름", "아이디", "상태", "총 상품", "삭제됨", "비밀번호"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setColumnHidden(5, True)  # 비밀번호 숨김
        layout.addWidget(self.table)
        
        # 실행 버튼
        action_layout = QHBoxLayout()
        action_layout.addStretch()
        
        self.start_btn = QPushButton("🚀 자동 삭제 시작")
        self.start_btn.setStyleSheet("background-color: #ff6b6b; color: white; font-weight: bold; padding: 10px 30px;")
        self.start_btn.clicked.connect(self.start_auto_delete)
        self.start_btn.setEnabled(False)
        action_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("중지")
        self.stop_btn.clicked.connect(self.stop_auto_delete)
        self.stop_btn.setEnabled(False)
        action_layout.addWidget(self.stop_btn)
        
        action_layout.addStretch()
        layout.addLayout(action_layout)
        
        # 진행바
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # 로그
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
    
    def log(self, msg: str):
        self.log_text.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
    
    def load_accounts(self):
        """계정 로드"""
        text = self.account_input.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "오류", "계정 정보를 입력하세요.")
            return
        
        self.accounts = []
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split(',')
            if len(parts) >= 3:
                account = Account(
                    name=parts[0].strip(),
                    user_id=parts[1].strip(),
                    password=parts[2].strip()
                )
                self.accounts.append(account)
        
        # 테이블 업데이트
        self.table.setRowCount(len(self.accounts))
        for i, acc in enumerate(self.accounts):
            self.table.setItem(i, 0, QTableWidgetItem(acc.name))
            self.table.setItem(i, 1, QTableWidgetItem(acc.user_id))
            self.table.setItem(i, 2, QTableWidgetItem(acc.status))
            self.table.setItem(i, 3, QTableWidgetItem(str(acc.total)))
            self.table.setItem(i, 4, QTableWidgetItem(str(acc.deleted)))
            self.table.setItem(i, 5, QTableWidgetItem(acc.password))
        
        self.log(f"{len(self.accounts)}개 계정 로드됨")
        self.start_btn.setEnabled(len(self.accounts) > 0)
    
    def update_account_row(self, idx: int, status: str, total: int, deleted: int):
        """테이블 행 업데이트"""
        if idx < self.table.rowCount():
            self.table.setItem(idx, 2, QTableWidgetItem(status))
            self.table.setItem(idx, 3, QTableWidgetItem(str(total)))
            self.table.setItem(idx, 4, QTableWidgetItem(str(deleted)))
    
    def start_auto_delete(self):
        """자동 삭제 시작"""
        if not self.accounts:
            return
        
        reply = QMessageBox.warning(self, "⚠️ 경고",
            f"{len(self.accounts)}개 계정의 모든 상품을 삭제합니다.\n"
            "복구 불가능합니다!\n\n"
            "정말 시작하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)

        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.load_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        
        delay = self.delay_spin.value() / 10.0  # 0.1초 단위
        skip_sold = self.skip_sold_check.isChecked()
        
        self.worker = AutoDeleteWorker(self.accounts, delay, skip_sold)
        self.worker.log_signal.connect(self.log)
        self.worker.progress_signal.connect(self.on_progress)
        self.worker.account_updated.connect(self.update_account_row)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()
    
    def stop_auto_delete(self):
        """중지"""
        if self.worker:
            self.worker.stop()
            self.log("중지 요청됨...")
    
    def on_progress(self, current: int, total: int, msg: str):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
    
    def on_finished(self):
        self.progress_bar.setVisible(False)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.load_btn.setEnabled(True)
        
        self.log("\n" + "="*50)
        self.log("모든 작업 완료!")
        self.log("="*50)
        
        QMessageBox.information(self, "완료", "모든 계정 처리가 완료되었습니다.")


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
