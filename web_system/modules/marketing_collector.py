# -*- coding: utf-8 -*-
"""
스마트스토어 마케팅 데이터 수집 모듈 (CDP 버전)
- client_v1.5.py 로그인 로직 통합
- Chrome DevTools Protocol (CDP) 사용
- SMS API 연동 2차 인증 처리
"""

import sys
import io

# Windows 콘솔 한글 출력 인코딩 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os
import re
import json
import time
import requests
from datetime import datetime
from pathlib import Path

import signal
import atexit
import subprocess

import gspread
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# 전역 드라이버 참조 (인터럽트 시 정리용)
_active_driver = None

def _cleanup_driver():
    """프로세스 종료 시 드라이버 정리"""
    global _active_driver
    if _active_driver:
        try:
            _active_driver.quit()
            print("[마케팅수집] 크롬 드라이버 정리됨")
        except:
            pass
        _active_driver = None

def _signal_handler(signum, frame):
    """Ctrl+C 등 시그널 핸들러"""
    print(f"\n[마케팅수집] 시그널 {signum} 수신, 크롬 정리 중...")
    _cleanup_driver()
    sys.exit(0)

# atexit 및 시그널 등록
atexit.register(_cleanup_driver)
if sys.platform != 'win32':
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

# 서버 설정
SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "pkonomiautokey2024")


class MarketingDataCollector:
    """마케팅 데이터 수집기 - CDP + Selenium 하이브리드"""

    def __init__(self, google_sheets_client, marketing_spreadsheet_id, chrome_port=9222):
        self.gc = google_sheets_client
        self.marketing_spreadsheet_id = marketing_spreadsheet_id
        self.chrome_port = chrome_port
        self.driver = None
        self.marketing_spreadsheet = None
        self.ws = None  # CDP WebSocket
        self.cdp_id = 0

    def connect_spreadsheet(self):
        try:
            self.marketing_spreadsheet = self.gc.open_by_key(self.marketing_spreadsheet_id)
            return True
        except Exception as e:
            print(f"마케팅 스프레드시트 연결 실패: {e}")
            return False

    def connect_chrome(self):
        """Chrome 연결 (Selenium)
        - 기존 디버깅 포트로 열린 크롬이 있으면 재사용
        - 없으면 새로 실행 (user-data-dir 프로필 사용)

        환경변수:
          SMARTSTORE_CHROME_PROFILE_DIR: 크롬 프로필 경로 (기본: ../runtime/chrome_profile)
          SMARTSTORE_HEADLESS: 1이면 headless 실행
          SMARTSTORE_CHROME_PORT: 디버깅 포트 (기본: 9333)
        """
        global _active_driver

        debug_port = int(os.environ.get("SMARTSTORE_CHROME_PORT", "9333"))

        # 1. 기존 크롬 연결 시도 (디버깅 포트) - 빠른 체크
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)  # 0.5초 타임아웃
            result = sock.connect_ex(('127.0.0.1', debug_port))
            sock.close()

            if result == 0:  # 포트 열려있음 = 크롬 실행중
                options = Options()
                options.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")
                self.driver = webdriver.Chrome(options=options)
                _ = self.driver.current_url
                print(f"[마케팅수집] 기존 크롬 연결 성공 (포트 {debug_port})")
                _active_driver = self.driver
                return True
            else:
                print(f"[마케팅수집] 포트 {debug_port} 닫힘, 새 크롬 실행...")
        except Exception as e:
            print(f"[마케팅수집] 기존 크롬 연결 실패: {e}")

        # 2. 새 크롬 실행
        try:
            profile_dir = os.environ.get("SMARTSTORE_CHROME_PROFILE_DIR", "").strip()
            if not profile_dir:
                profile_dir = os.path.join(os.path.dirname(__file__), "..", "runtime", "marketing_chrome_profile")
            profile_dir = os.path.abspath(profile_dir)
            os.makedirs(profile_dir, exist_ok=True)

            # 프로필 잠금 파일 제거 (이전 비정상 종료 시 남은 잠금)
            lock_file = os.path.join(profile_dir, "SingletonLock")
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                    print(f"[마케팅수집] 프로필 잠금 해제: {lock_file}")
                except:
                    pass

            options = Options()

            # Headless는 네이버 로그인에서 추가인증/캡차를 유발하는 경우가 많아 기본 비활성
            headless_env = os.environ.get("SMARTSTORE_HEADLESS", "0").strip().lower() in ("1", "true", "yes")
            if headless_env:
                options.add_argument("--headless=new")

            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-gpu")
            options.add_argument("--lang=ko-KR")
            options.add_argument(f"--remote-debugging-port={debug_port}")

            # 자동화 탐지 완화
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)

            options.add_argument(f"--user-data-dir={profile_dir}")

            self.driver = webdriver.Chrome(options=options)

            # navigator.webdriver 숨김 (가능한 경우)
            try:
                self.driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {
                        "source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                    },
                )
            except Exception:
                pass

            print(f"[마케팅수집] 새 크롬 실행 (포트 {debug_port}, 프로필: {profile_dir})")
            _active_driver = self.driver
            return True
        except Exception as e:
            print(f"Chrome 연결 실패: {e}")
            return False

    def disconnect(self):
        """크롬 연결 해제 (창은 유지, 드라이버만 분리)"""
        global _active_driver
        if self.driver:
            try:
                # quit() 대신 close()도 안 함 - 창 유지
                self.driver = None
                _active_driver = None
                print("[마케팅수집] 크롬 드라이버 분리 (창 유지)")
            except:
                pass

    def quit(self):
        """크롬 완전 종료"""
        global _active_driver
        if self.driver:
            try:
                self.driver.quit()
                print("[마케팅수집] 크롬 종료됨")
            except:
                pass
            self.driver = None
            _active_driver = None

    def _js_exists(self, selector):
        """요소 존재 확인"""
        try:
            safe_selector = selector.replace('"', "'")
            js = f'document.querySelector("{safe_selector}") !== null'
            return self.driver.execute_script(js) or False
        except:
            return False

    def _debug_dir(self):
        d = os.environ.get("SMARTSTORE_DEBUG_DIR", "").strip()
        if not d:
            d = os.path.join(os.path.dirname(__file__), "..", "runtime", "smartstore_debug")
        d = os.path.abspath(d)
        os.makedirs(d, exist_ok=True)
        return d

    def _dump_debug(self, label: str):
        """실패 원인 분석용: screenshot + html + meta 저장"""
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_label = re.sub(r"[^a-zA-Z0-9._-]+", "_", label)[:80]
            base = os.path.join(self._debug_dir(), f"{ts}_{safe_label}")

            try:
                self.driver.save_screenshot(base + ".png")
            except Exception:
                pass

            try:
                with open(base + ".html", "w", encoding="utf-8") as f:
                    f.write(self.driver.page_source or "")
            except Exception:
                pass

            try:
                meta = {
                    "label": label,
                    "ts": ts,
                    "url": getattr(self.driver, "current_url", ""),
                    "title": getattr(self.driver, "title", ""),
                }
                with open(base + ".json", "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            print(f"[DEBUG] dump saved: {base}.[png/html/json]")
        except Exception:
            pass

    def _page_contains_any(self, needles):
        try:
            html = (self.driver.page_source or "").lower()
            return any(n.lower() in html for n in needles)
        except Exception:
            return False

    def _retry_after_captcha(self, user_id, password):
        """캡차/보안문자 수동 처리 후 로그인 재시도"""
        try:
            # 현재 URL 확인
            current_url = self.driver.current_url
            if "sell.smartstore.naver.com" in current_url and "login" not in current_url.lower():
                print(f"  [OK] 캡차 처리 후 로그인 성공")
                return True

            # 캡차가 여전히 있는지 확인
            if self._page_contains_any(["보안문자", "캡차", "captcha"]):
                print(f"  [FAIL] 캡차가 여전히 해결되지 않음")
                return False

            # ID/PW 입력창이 있다면 다시 입력 시도
            if self._js_exists("input#id, input[name='id'], input[type='email']"):
                print(f"  -> 캡차 처리 완료, 로그인 재시도...")
                return self.do_login(user_id, password)

            return False
        except Exception as e:
            print(f"  -> 캡차 재시도 오류: {e}")
            return False

    def _get_sms_code(self, refresh=False):
        """서버에서 SMS 인증번호 가져오기"""
        try:
            url = f"{SERVER_URL}/api/sms/auth-code"
            if refresh:
                url += "?refresh=true"
            headers = {"X-API-Key": API_KEY}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                code = data.get("code")
                code_time = data.get("time", "")
                if code and code.isdigit() and len(code) >= 4:
                    return {"code": code, "time": code_time}
        except Exception as e:
            print(f"SMS 코드 조회 오류: {e}")
        return None

    def _clear_sms_code(self):
        """기존 SMS 인증번호 초기화"""
        try:
            url = f"{SERVER_URL}/api/sms/auth-code/clear"
            headers = {"X-API-Key": API_KEY}
            resp = requests.post(url, headers=headers, timeout=5)
            return resp.status_code == 200
        except:
            return False

    def _wait_sms_code(self, timeout=60, after_time=None):
        """SMS 인증번호 대기"""
        print(f"  -> SMS 인증번호 대기 중... (기준시간: {after_time})")

        start = time.time()
        while time.time() - start < timeout:
            # 실시간 새로고침 파라미터 전달
            result = self._get_sms_code(refresh=True)
            if result:
                code = result.get("code")
                code_time = result.get("time", "")

                # 시간 기반 필터링
                if after_time and code_time:
                    if code_time <= after_time:
                        print(f"  -> 이전 인증번호 무시: {code} ({code_time} <= {after_time})")
                        continue

                if code:
                    print(f"  -> 인증번호 수신: {code} (시간: {code_time})")
                    return code

        print("  -> 인증번호 수신 실패 (타임아웃)")
        return None

    def _check_2fa_needed(self):
        """2차 인증 필요 여부 확인 (속도 최적화 버전)"""
        try:
            curr_url = self.driver.current_url.lower()
            # 1. URL 패턴 확인 (가장 빠름)
            if not any(x in curr_url for x in ["2step", "auth", "accounts.commerce.naver.com"]):
                return False

            # 2. 고유 요소 존재 여부만 즉시 확인 (innerText 대신 특정 요소만 타겟팅)
            # '2단계 인증' 텍스트 포함 여부와 버튼/입력창 존재 여부를 묶어서 신속하게 체크
            check_js = """
                return !!(
                    document.querySelector('button.TextField_btn_certify__2GCpl') || 
                    document.querySelector('input.TextField_ipt__szCeX') ||
                    document.body.innerText.includes('2단계 인증')
                );
            """
            return bool(self.driver.execute_script(check_js))
        except:
            return False

    def _handle_2fa(self):
        """2차 인증 처리 - 엔터 키 방식"""
        try:
            # 0. 기존 인증번호 초기화 (서버 clear_time 갱신)
            self._clear_sms_code()
            
            # 인증 요청 클릭 직후의 시간을 send_time으로 설정 (필터링 기준)
            # 서버에서 초기화된 시점 이후의 메시지만 가져오게 됨
            send_time = datetime.now().strftime("%H:%M:%S")
            self._log(f"[2FA] 처리 시작 (인증 요청 기준 시간: {send_time})")

            # 1. 인증 버튼에 포커스 후 엔터 키 전송
            click_result = "not found"
            try:
                from selenium.webdriver.common.keys import Keys

                # 방법1: 인증 버튼 찾아서 엔터
                auth_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button.TextField_btn_certify__2GCpl")
                if not auth_buttons:
                    auth_buttons = self.driver.find_elements(By.XPATH, "//button[contains(text(),'인증')]")

                self._log(f"[2FA] 인증 버튼 개수: {len(auth_buttons)}")

                for i, btn in enumerate(auth_buttons):
                    if btn.is_displayed() and btn.is_enabled():
                        self._log(f"[2FA] 버튼 {i}에 엔터 전송...")
                        btn.send_keys(Keys.ENTER)
                        click_result = f"enter sent: button {i}"
                        break

                # 방법2: ActionChains으로 엔터
                if "enter" not in click_result and auth_buttons:
                    try:
                        actions = ActionChains(self.driver)
                        actions.move_to_element(auth_buttons[0]).send_keys(Keys.ENTER).perform()
                        click_result = "enter sent: ActionChains"
                    except Exception as e:
                        self._log(f"[2FA] ActionChains 실패: {e}")

                # 방법3: body에 Tab + Enter (포커스 이동 후 엔터)
                if "enter" not in click_result:
                    try:
                        body = self.driver.find_element(By.TAG_NAME, "body")
                        body.send_keys(Keys.TAB, Keys.TAB, Keys.ENTER)
                        click_result = "enter sent: Tab+Enter"
                    except Exception as e:
                        self._log(f"[2FA] Tab+Enter 실패: {e}")

            except Exception as e:
                self._log(f"[2FA] 버튼 찾기 오류: {e}")

            self._log(f"[2FA] 인증버튼: {click_result}")

            if "enter" in str(click_result):
                # alert 팝업 처리 (Selenium 방식)
                time.sleep(0.5)
                try:
                    from selenium.webdriver.common.alert import Alert
                    alert = Alert(self.driver)
                    alert.accept()
                    self._log("[2FA] Selenium alert 수락")
                except Exception as e:
                    self._log(f"[2FA] alert 없음: {type(e).__name__}")

                # 2. 팝업 확인 버튼 - 엔터로 처리
                self._log("[2FA] 팝업 대기 (1초)...")
                time.sleep(1)

                # 팝업 확인 버튼도 엔터로
                popup_result = "not tried"
                try:
                    from selenium.webdriver.common.keys import Keys
                    popup_btns = self.driver.find_elements(By.CSS_SELECTOR, "button.PopupCommon_btn__FhbVj")
                    if popup_btns:
                        popup_btns[0].send_keys(Keys.ENTER)
                        popup_result = "enter sent: popup"
                    else:
                        # 폴백: body에 엔터
                        body = self.driver.find_element(By.TAG_NAME, "body")
                        body.send_keys(Keys.ENTER)
                        popup_result = "enter sent: body"
                except Exception as e:
                    self._log(f"[2FA] 팝업 엔터 실패: {e}")

                self._log(f"[2FA] 팝업처리: {popup_result}")
                time.sleep(0.5)
            else:
                self._log("[2FA] 인증버튼 못찾음")

            # 3. SMS 인증번호 대기
            code = self._wait_sms_code(after_time=send_time)
            if not code:
                # 폴백: 시간 필터 없이 가장 최신 인증번호 다시 한 번 시도
                self._log("[2FA] 조건에 맞는 인증번호 대기 실패. 필터 없이 재시도...")
                result = self._get_sms_code()
                if result:
                    code = result.get("code")
            
            if not code:
                self._log("[2FA] 인증번호를 끝내 받지 못함")
                return False

            # 4. 인증번호 입력 (인증 버튼 클릭 후 나타나는 입력창)
            self._log(f"[2FA] 인증번호 입력 시도: {code}")
            input_js = f'''
                (function() {{
                    var input = null;
                    
                    // 방법1: 활성화된 섹션 내에서 찾기
                    var activeSection = document.querySelector('li.TwoStepCertify_on__nASYZ') ||
                                        document.querySelector('li.TwoStepCertify_choice_item__8pXFr.TwoStepCertify_on__nASYZ');

                    if (activeSection) {{
                        var inputs = activeSection.querySelectorAll('input.TextField_ipt__szCeX');
                        for (var inp of inputs) {{
                            if (!inp.readOnly && !inp.disabled) {{
                                input = inp;
                                break;
                            }}
                        }}
                    }}

                    // 방법2: 페이지 전체에서 입력창 탐색
                    if (!input) {{
                        var allInputs = document.querySelectorAll('input.TextField_ipt__szCeX:not([readonly])');
                        if (allInputs.length > 0) input = allInputs[0];
                    }}
                    
                    if (!input) {{
                        input = document.querySelector('input[placeholder*="인증번호"]') ||
                                document.querySelector('input[placeholder*="6자리"]') ||
                                document.querySelector('input[maxlength="6"]:not([readonly])') ||
                                document.querySelector('input[inputmode="numeric"]:not([readonly])');
                    }}

                    if (input) {{
                        input.focus();
                        input.value = ""; // 기존 값 비우기
                        
                        // React/Vue 등 가상 DOM 대응을 위한 Setter 호출
                        var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        nativeSetter.call(input, "{code}");
                        
                        // 이벤트 발생시켜 데이터 바인딩 업데이트
                        input.dispatchEvent(new Event('input', {{bubbles: true}}));
                        input.dispatchEvent(new Event('change', {{bubbles: true}}));
                        
                        // 입력값 확인을 위한 리턴
                        return 'input ok: ' + (input.placeholder || input.className) + ' (value: ' + input.value + ')';
                    }}
                    return 'input not found';
                }})()
            '''
            input_result = self.driver.execute_script(input_js) or ""
            self._log(f"[2FA] 입력결과: {input_result}")
            time.sleep(1.0) # 입력 후 잠시 대기

            # 5. 최종 확인 버튼 클릭 (2026-01-16 디버깅 확인된 클래스: Button_btn__wNWXt Button_btn_plain__vwFfm)
            confirm_btn_js = '''
                (function() {
                    // 방법1: 정확한 클래스 조합으로 찾기 (디버깅 확인됨)
                    var confirmBtn = document.querySelector('button.Button_btn__wNWXt.Button_btn_plain__vwFfm:not([disabled])');
                    if (confirmBtn && confirmBtn.textContent.trim() === '확인') {
                        confirmBtn.click();
                        return 'clicked: Button_btn_plain 확인';
                    }

                    // 방법2: TwoStepCertify_btn_box 안의 버튼
                    var btnBox = document.querySelector('div[class*="TwoStepCertify_btn_box"]');
                    if (btnBox) {
                        var btn = btnBox.querySelector('button:not([disabled])');
                        if (btn) {
                            btn.click();
                            return 'clicked: TwoStepCertify_btn_box button';
                        }
                    }

                    // 방법3: Button_btn__wNWXt 클래스의 확인 버튼
                    var allBtns = document.querySelectorAll('button.Button_btn__wNWXt:not([disabled])');
                    for (var btn of allBtns) {
                        if (btn.textContent.trim() === '확인') {
                            btn.click();
                            return 'clicked: Button_btn confirm';
                        }
                    }

                    // 방법4: 팝업 버튼이 아닌 일반 확인 버튼 (텍스트로)
                    var buttons = document.querySelectorAll('button:not([disabled]):not([class*="PopupCommon"])');
                    for (var b of buttons) {
                        var text = b.textContent.trim();
                        if (text === '확인') {
                            b.click();
                            return 'clicked: general 확인';
                        }
                    }
                    return 'confirm button not found or disabled';
                })()
            '''
            confirm_result = self.driver.execute_script(confirm_btn_js) or ""
            self._log(f"[2FA] 최종확인: {confirm_result}")

            time.sleep(2)
            return True

        except Exception as e:
            self._log(f"[2FA] 오류: {e}")
            return False

    def do_login(self, user_id, password):
        """
        스마트스토어 로그인
        - 네이버 커머스 로그인 페이지 (이메일/판매자 아이디 탭이 기본)
        - Selenium send_keys로 입력
        - SMS 2차 인증 처리
        """
        try:
            # 디버그: 전달받은 값 확인
            print(f"  [DEBUG] do_login 호출됨")
            print(f"  [DEBUG] user_id: '{user_id}' (type: {type(user_id).__name__}, len: {len(str(user_id)) if user_id else 0})")
            print(f"  [DEBUG] password: {'*' * len(str(password)) if password else 'None'} (len: {len(str(password)) if password else 0})")

            if not user_id or not password:
                print(f"  [FAIL] ID 또는 PW가 비어있음!")
                return False

            # 1. 로그인 페이지 이동
            login_url = "https://accounts.commerce.naver.com/login?url=https%3A%2F%2Fsell.smartstore.naver.com%2F%23%2Flogin-callback"
            print(f"  [DEBUG] 로그인 페이지 이동: {login_url}")
            self.driver.get(login_url)
            time.sleep(3)

            # 이미 로그인 상태인지 확인
            current_url = self.driver.current_url
            print(f"  [DEBUG] 현재 URL: {current_url}")
            if "sell.smartstore.naver.com" in current_url and "login" not in current_url.lower():
                print(f"  [OK] 이미 로그인 상태")
                return True

            # 2. ID 입력창 대기
            print(f"  [DEBUG] ID 입력창 찾는 중...")
            wait = WebDriverWait(self.driver, 10)
            try:
                id_input = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'input[placeholder="아이디 또는 이메일 주소"]')
                ))
                print(f"  [DEBUG] ID 입력창 찾음!")
            except Exception as e:
                print(f"  [FAIL] ID 입력창을 찾을 수 없음: {e}")
                self._dump_debug("login_no_id_input")
                return False

            # 3. ID 입력 (send_keys 사용)
            print(f"  [DEBUG] ID 입력 시작...")
            id_input.click()
            time.sleep(0.2)
            id_input.clear()
            id_input.send_keys(user_id)
            # 입력된 값 확인
            entered_id = id_input.get_attribute('value')
            print(f"  -> ID 입력 완료 (입력된 값: '{entered_id}')")
            time.sleep(0.3)

            # 4. PW 입력
            print(f"  [DEBUG] PW 입력창 찾는 중...")
            try:
                pw_input = self.driver.find_element(By.CSS_SELECTOR, 'input[placeholder="비밀번호"]')
                print(f"  [DEBUG] PW 입력창 찾음!")
                pw_input.click()
                time.sleep(0.2)
                pw_input.clear()
                pw_input.send_keys(password)
                # 입력된 값 확인
                entered_pw = pw_input.get_attribute('value')
                print(f"  -> PW 입력 완료 (입력된 길이: {len(entered_pw)})")
            except Exception as e:
                print(f"  [FAIL] PW 입력 실패: {e}")
                self._dump_debug("login_pw_input_fail")
                return False
            time.sleep(0.3)

            # 5. 로그인: Enter 키로 제출
            pw_input.send_keys(Keys.ENTER)
            print(f"  -> Enter 키로 로그인 제출 (2FA 감시 시작)")

            # 7. 로그인 성공 대기 (SMS 인증 포함)
            max_wait = 600
            start_time = time.time()
            last_url = ""

            while time.time() - start_time < max_wait:
                current_url = self.driver.current_url

                # URL 변경 감지 시 로그
                if current_url != last_url:
                    print(f"  [DEBUG] URL 변경: {current_url[:70]}...")
                    last_url = current_url

                # 1. 2FA 페이지 감지 (URL에 accounts.commerce.naver.com 포함)
                if "accounts.commerce.naver.com" in current_url:
                    # 페이지 로딩 완료 대기 (document.readyState)
                    try:
                        ready_state = self.driver.execute_script("return document.readyState")
                        if ready_state != "complete":
                            time.sleep(0.3)
                            continue

                        # 로딩 완료 후 1초 대기 (DOM 렌더링 안정화)
                        time.sleep(1)

                        # 2FA 요소가 DOM에 존재하는지 확인
                        has_2fa_elements = self.driver.execute_script("""
                            return !!(
                                document.querySelector('li.TwoStepCertify_on__nASYZ') ||
                                document.querySelector('button.TextField_btn_certify__2GCpl')
                            );
                        """)
                        if has_2fa_elements:
                            print(f"  -> 2FA 감지됨 (페이지 로딩 완료 + DOM 확인). 즉시 처리.")
                            self._handle_2fa()
                            # 처리 후 페이지 전환 대기
                            time.sleep(2)
                            continue
                    except Exception as e:
                        print(f"  [DEBUG] 2FA 체크 오류: {e}")
                        pass

                # 2. 로그인 성공 조건 체크
                is_seller_home = "sell.smartstore.naver.com" in current_url
                is_not_auth_page = not any(x in current_url.lower() for x in ["login", "2step", "auth", "accounts.commerce"])

                if is_seller_home and is_not_auth_page:
                    print(f"  [OK] 로그인 성공! (URL: {current_url[:60]}...)")
                    return True

                time.sleep(0.3)

            print("  [FAIL] 로그인 타임아웃")
            return False

        except Exception as e:
            print(f"로그인 오류: {e}")
            import traceback
            traceback.print_exc()
            return False

    def safe_click(self, element):
        try:
            element.click()
        except:
            self.driver.execute_script("arguments[0].click();", element)

    def close_all_popups(self):
        """팝업 닫기"""
        try:
            try:
                close_btns = self.driver.find_elements(By.XPATH, "//button[contains(text(),'닫기')]")
                for btn in close_btns:
                    if btn.is_displayed():
                        self.safe_click(btn)
                        time.sleep(0.5)
            except:
                pass

            try:
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            except:
                pass

            try:
                selectors = ["button.close", "button.btn_close", ".close-button"]
                for sel in selectors:
                    btns = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    for btn in btns:
                        if btn.is_displayed():
                            self.safe_click(btn)
            except:
                pass

        except Exception:
            pass

    def _log(self, msg):
        """실시간 로그 출력 (타임스탬프 + flush)"""
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", flush=True)

    async def collect_multiple_accounts(self, account_infos, task_id, progress_dict):
        self._log(f"[시작] 마케팅 데이터 수집 - {len(account_infos)}개 계정")

        try:
            if not self.connect_chrome():
                self._log("[ERROR] Chrome 연결 실패")
                progress_dict[task_id]['status'] = 'error'
                return

            self._log("[OK] Chrome 연결 성공")
            total = len(account_infos)
            success = 0

            for i, account in enumerate(account_infos):
                progress_dict[task_id]['current'] = i + 1
                self._log(f"\n{'='*50}")
                self._log(f"[{i+1}/{total}] {account['login_id']} 처리 시작")
                self._log(f"{'='*50}")

                try:
                    # 1. 로그인
                    self._log(f"[단계1] 로그인 시도...")
                    if not self.do_login(account['login_id'], account['password']):
                        raise Exception("로그인 실패")
                    self._log(f"[단계1] 로그인 성공!")

                    # 2. 비즈어드바이저 수집 (상품노출성과)
                    self._log(f"[단계2] 비즈어드바이저 데이터 수집 시작...")
                    marketing_data = self.collect_marketing_data()
                    self._log(f"[단계2] 비즈어드바이저 수집 완료 - {len(marketing_data)}건")

                    # 3. 전체채널 데이터 수집 (추가)
                    self._log(f"[단계3] 전체채널 데이터 수집 시작...")
                    channel_data = self.collect_channel_data()
                    self._log(f"[단계3] 전체채널 수집 완료 - {len(channel_data)}건")

                    # 4. 쇼핑파트너센터 수집 (클릭리포트, 몰정보)
                    self._log(f"[단계4] 쇼핑파트너센터 데이터 수집 시작...")
                    report_data, mall_info = self.collect_shopping_partner_data()
                    self._log(f"[단계4] 쇼핑파트너센터 수집 완료 - 리포트:{len(report_data)}건, 몰정보:{len(mall_info)}건")

                    # 5. 저장
                    store_name = account.get('store_name') or account['login_id']
                    self._log(f"[단계5] 구글시트 저장 중... ({store_name})")
                    self.save_to_sheets(store_name, marketing_data, report_data, mall_info, channel_data)
                    self._log(f"[단계5] 저장 완료!")

                    # 6. 로그아웃
                    self._log(f"[단계6] 로그아웃...")
                    self.do_logout()

                    success += 1
                    self._log(f"[완료] {store_name} 처리 성공!")

                except Exception as e:
                    self._log(f"[오류] {account['login_id']} 처리 중 실패: {e}")
                    import traceback
                    traceback.print_exc()
                    self._dump_debug(f"fail_{account['login_id']}")

            progress_dict[task_id]['status'] = 'completed'
            progress_dict[task_id]['message'] = f"작업 완료 (성공: {success}/{total})"
            self._log(f"\n[최종] 전체 작업 종료 (성공: {success}, 실패: {total-success})")

        except Exception as e:
            self._log(f"[치명적 오류] {e}")
            progress_dict[task_id]['status'] = 'error'
        finally:
            self._log("[정리] 브라우저 세션을 종료합니다.")
            if self.driver:
                try:
                    self.driver.quit()
                    self.driver = None
                except:
                    pass

    def collect_marketing_data(self):
        """1. 비즈어드바이저 - 상품노출성과"""
        all_data = []
        try:
            wait = WebDriverWait(self.driver, 20)

            print("    -> 상품노출성과 페이지 이동")
            self.driver.get("https://sell.smartstore.naver.com/#/bizadvisor/marketing/expose")
            time.sleep(4)
            self.close_all_popups()

            # iframe 전환 (Naver Naver Biz Advisor)
            try:
                # 1순위: ID 기반 탐색
                iframe_selector = "iframe#__delegate"
                if self._js_exists(iframe_selector):
                    iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, iframe_selector)))
                    self.driver.switch_to.frame(iframe)
                    print("    -> iframe (__delegate) 전환 완료")
                else:
                    # 2순위: 탭에서 유일한 iframe 또는 특정 사이즈 iframe 찾기
                    iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                    if iframes:
                        self.driver.switch_to.frame(iframes[0])
                        print(f"    -> iframe (TAG) 전환 완료 (총 {len(iframes)}개 중 첫번째)")
                    else:
                        raise Exception("iframe을 찾을 수 없습니다.")
            except Exception as e:
                print(f"    -> iframe 전환 실패: {e}")
                # 분석을 위한 로그 남기기
                self._dump_debug("bizadvisor_iframe_fail")
            time.sleep(2)

            # 날짜: 어제 선택
            try:
                date_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "a.btn.select_data")))
                self.safe_click(date_btn)
                time.sleep(1)

                yesterday_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//div[@class='fix_range']//a/span[text()='어제']/..")))
                self.safe_click(yesterday_btn)
                time.sleep(0.5)

                apply_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "span.select_range")))
                self.safe_click(apply_btn)
                time.sleep(3)
            except Exception as e:
                print(f"    -> 날짜 선택 실패: {e}")

            # 노출개수 1000
            try:
                selectbox = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "div.selectbox_box.list_count div.selectbox_label a")))
                self.safe_click(selectbox)
                time.sleep(1)

                option_1000 = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//div[@class='selectbox_box list_count']//ul/li/a[text()='1000']")))
                self.safe_click(option_1000)
                time.sleep(3)
            except Exception as e:
                print(f"    -> 노출개수 변경 실패: {e}")

            # 테이블 로딩 대기
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.tbl_list")))
            time.sleep(2)

            # 헤더
            headers = ["상품명", "상품ID", "채널그룹", "채널명", "키워드", "평균노출순위", "유입수"]
            all_data.append(headers)

            # 전체 행
            try:
                total_row = self.driver.find_element(By.CSS_SELECTOR, "tr.total_row")
                total_cells = total_row.find_elements(By.TAG_NAME, "td")
                if len(total_cells) >= 7:
                    total_data = [cell.text.strip() for cell in total_cells[:7]]
                    all_data.append(total_data)
            except:
                pass

            # 페이지네이션 수집
            page_num = 1
            stop_collecting = False

            while not stop_collecting:
                print(f"    -> 페이지 {page_num} 수집 중...")
                time.sleep(1)

                rows = self.driver.find_elements(By.CSS_SELECTOR, "table.tbl_list tbody tr:not(.total_row)")
                collected_count = 0

                for row in rows:
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if len(cells) < 7:
                            continue

                        inflow_str = cells[6].text.replace(",", "").strip()
                        try:
                            inflow = int(inflow_str) if inflow_str.isdigit() else 0
                        except:
                            inflow = 0

                        if inflow == 0:
                            stop_collecting = True
                            break

                        row_data = []
                        for idx, cell in enumerate(cells[:7]):
                            if idx == 0:
                                try:
                                    link = cell.find_element(By.TAG_NAME, "a")
                                    row_data.append(link.text.strip())
                                except:
                                    row_data.append(cell.text.strip())
                            else:
                                row_data.append(cell.text.strip())

                        all_data.append(row_data)
                        collected_count += 1
                    except:
                        continue

                print(f"    -> 페이지 {page_num}: {collected_count}건")

                if stop_collecting or collected_count == 0:
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
                    break

            self.driver.switch_to.default_content()
            print(f"    -> 상품노출성과 총 {len(all_data)-1}개 행 수집 완료")
            return all_data

        except Exception as e:
            print(f"    -> 비즈어드바이저 수집 실패: {e}")
            try:
                self.driver.switch_to.default_content()
            except:
                pass
            return all_data

    def collect_channel_data(self):
        """전체채널 데이터 수집 (채널명, 유입수)"""
        wait = WebDriverWait(self.driver, 20)
        channel_data = []

        try:
            # 1. 마케팅분석 메뉴로 이동
            print("    -> 마케팅분석 메뉴로 이동 (전체채널)")
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
                print("    -> 데이터분석 클릭 완료")
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
                print("    -> 마케팅분석 클릭 완료")
            else:
                self.driver.get("https://sell.smartstore.naver.com/#/bizadvisor/marketing")
                print("    -> 마케팅분석 URL 직접 이동")
            time.sleep(3)

            # 3. 전체채널 탭 확인 (기본 선택되어 있음)
            print("    -> 전체채널 탭 확인")
            try:
                channel_tab = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//ul[@class='seller-menu-tap']//a[contains(@href,'bizadvisor/marketing')]/span[text()='전체채널']/..")))
                self.safe_click(channel_tab)
                print("    -> 전체채널 탭 클릭")
            except:
                print("    -> 전체채널 탭 이미 선택됨")
            time.sleep(2)

            # 4. iframe 전환
            print("    -> iframe 전환")
            try:
                iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe#__delegate")))
                self.driver.switch_to.frame(iframe)
                print("    -> iframe 전환 완료")
            except Exception as e:
                print(f"    -> iframe 전환 실패, 계속 진행: {e}")
            time.sleep(2)

            # 5. 날짜 선택 - "어제" 선택
            print("    -> 날짜 선택 (어제)")
            try:
                date_btn = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "a.btn.select_data")))
                self.safe_click(date_btn)
                print("    -> 캘린더 팝업 열림")
                time.sleep(1)

                yesterday_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//div[@class='fix_range']//a/span[text()='어제']/..")))
                self.safe_click(yesterday_btn)
                print("    -> '어제' 선택")
                time.sleep(1)

                apply_btn = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "span.select_range")))
                self.safe_click(apply_btn)
                print("    -> '적용' 클릭 완료")
                time.sleep(3)

            except Exception as e:
                print(f"    -> 날짜 선택 실패: {e}")

            # 6. 차원 "상세" 선택
            print("    -> 차원 '상세' 선택")
            try:
                detail_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//div[@class='search_filter']//dd[@data-test-id='table-container-top-search-filter-dimension-opts']//a/span[text()='상세']/..")))
                self.safe_click(detail_btn)
                print("    -> '상세' 선택 완료")
                time.sleep(3)
            except Exception as e:
                print(f"    -> '상세' 선택 실패: {e}")

            # 7. 노출개수 1000으로 변경
            print("    -> 노출개수 1000으로 변경")
            try:
                selectbox = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "div.selectbox_box.list_count div.selectbox_label a")))
                self.safe_click(selectbox)
                time.sleep(1)

                option_1000 = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//div[@class='selectbox_box list_count']//ul/li/a[text()='1000']")))
                self.safe_click(option_1000)
                print("    -> 노출개수 1000 선택 완료")
                time.sleep(3)
            except Exception as e:
                print(f"    -> 노출개수 변경 실패: {e}")

            # 8. 테이블 데이터 수집
            print("    -> 전체채널 테이블 데이터 수집 중...")
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
                    channel_name = total_cells[2].text.strip()
                    inflow = total_cells[5].text.strip()
                    channel_data.append([channel_name, inflow])
                    print(f"    -> 전체 행: {channel_name}, {inflow}")
            except Exception as e:
                print(f"    -> 전체 행 없음: {e}")

            # 페이지네이션 처리
            page_num = 1
            while True:
                print(f"    -> 페이지 {page_num} 수집 중...")
                time.sleep(1)

                rows = self.driver.find_elements(By.CSS_SELECTOR, "table.tbl_list tbody tr:not(.total_row)")
                print(f"    -> 페이지 {page_num}에서 {len(rows)}개 행 발견")

                page_count = 0
                for row in rows:
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if len(cells) >= 6:
                            channel_name = cells[2].text.strip()
                            inflow_text = cells[5].text.strip()

                            try:
                                inflow = int(inflow_text.replace(",", ""))
                                if inflow >= 1:
                                    channel_data.append([channel_name, inflow_text])
                                    page_count += 1
                            except ValueError:
                                pass
                    except Exception as e:
                        continue

                print(f"    -> 페이지 {page_num}에서 유입수>=1인 행: {page_count}개")

                try:
                    next_btn = self.driver.find_element(By.CSS_SELECTOR, "li.btn.next:not(.disabled) a")
                    if next_btn:
                        self.safe_click(next_btn)
                        time.sleep(3)
                        page_num += 1
                    else:
                        break
                except:
                    print("    -> 마지막 페이지")
                    break

            self.driver.switch_to.default_content()
            print(f"    -> 전체채널 총 {len(channel_data)-1}개 행 수집 완료 (헤더 제외)")
            return channel_data

        except Exception as e:
            print(f"    전체채널 데이터 수집 오류: {e}")
            try:
                self.driver.switch_to.default_content()
            except:
                pass
            return channel_data

    def collect_shopping_partner_data(self):
        """2. 쇼핑파트너센터 - 상품클릭리포트 & 쇼핑몰정보"""
        report_data = []
        mall_info_data = []

        main_window = self.driver.current_window_handle

        try:
            wait = WebDriverWait(self.driver, 20)

            # 메인으로
            self.driver.get("https://sell.smartstore.naver.com/#/home/dashboard")
            time.sleep(3)
            self.close_all_popups()

            # 쇼핑파트너센터 링크
            try:
                link = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//a[contains(@href,'center.shopping.naver.com')]")))
                self.safe_click(link)
            except:
                self.driver.execute_script("window.open('https://center.shopping.naver.com/main')")

            time.sleep(3)

            # 새 창 전환
            windows = self.driver.window_handles
            if len(windows) > 1:
                for w in windows:
                    if w != main_window:
                        self.driver.switch_to.window(w)
                        break

            # 상품클릭리포트-모바일
            try:
                self.driver.get("https://center.shopping.naver.com/report/mobile/order")
                time.sleep(3)
            except:
                pass

            # iframe
            try:
                iframe = self.driver.find_element(By.CSS_SELECTOR, "iframe")
                self.driver.switch_to.frame(iframe)
            except:
                pass
            time.sleep(2)

            # 상품별 탭
            try:
                prod_tab = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//a[contains(@href,'prod_list.nhn')]")))
                self.safe_click(prod_tab)
                time.sleep(3)
            except:
                pass

            # 일간 선택
            try:
                daily_btn = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "li._quick_today a")))
                self.safe_click(daily_btn)
                time.sleep(2)
            except:
                pass

            # 조회
            try:
                btn = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "a.btn2.btn2_grn#searchBtn, a#searchBtn")))
                self.safe_click(btn)
                time.sleep(3)
            except:
                pass

            # 수집
            report_data.append(["상품ID", "상품명", "노출수", "클릭수", "클릭율", "적용수수료", "클릭당수수료"])

            page_num = 1
            while True:
                rows = self.driver.find_elements(By.CSS_SELECTOR, "table.tbl tbody tr")
                cnt = 0
                for row in rows:
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if len(cells) < 7:
                            continue
                        if "데이터가 없습니다" in cells[0].text:
                            break

                        r_data = []
                        for i, cell in enumerate(cells):
                            if i == 5:
                                continue
                            txt = cell.text.strip()
                            if i == 1:
                                txt = txt.replace("상품별 보기", "").strip()
                            r_data.append(txt)

                        if len(r_data) >= 7:
                            report_data.append(r_data[:7])
                            cnt += 1
                    except:
                        continue

                if cnt == 0:
                    break

                try:
                    next_btn = self.driver.find_element(By.XPATH, "//div[@class='paginate paginate_regular']//a[contains(text(),'다음')]")
                    self.safe_click(next_btn)
                    time.sleep(2)
                    page_num += 1
                except:
                    break

            self.driver.switch_to.default_content()

            # 쇼핑몰 정보
            self.driver.get("https://center.shopping.naver.com/main")
            time.sleep(3)
            try:
                iframe = self.driver.find_element(By.CSS_SELECTOR, "iframe")
                self.driver.switch_to.frame(iframe)
            except:
                pass

            mall_info_data.append(["항목", "값"])
            # 쇼핑몰 ID
            try:
                mid = self.driver.find_element(By.CSS_SELECTOR, "li.id span.fb").text.strip()
                mall_info_data.append(["쇼핑몰 ID", mid])
            except:
                pass

            # 쇼핑몰 명
            try:
                mnm = self.driver.find_element(By.CSS_SELECTOR, "li.name span:not(strong span)").text.strip()
                mall_info_data.append(["쇼핑몰 명", mnm])
            except:
                pass

            # 쇼핑몰 타입
            try:
                mtp = self.driver.find_element(By.CSS_SELECTOR, "li.type span:not(strong span)").text.strip()
                mall_info_data.append(["쇼핑몰 타입", mtp])
            except:
                pass

            # 쇼핑몰 등급 (추가)
            try:
                mall_grade = self.driver.find_element(By.CSS_SELECTOR, "li.grade span:not(strong span)").text.strip()
                mall_info_data.append(["쇼핑몰 몰등급", mall_grade])
            except:
                pass

            # 안읽은 쪽지 (추가)
            try:
                unread_msg = self.driver.find_element(By.CSS_SELECTOR, "li.msg em.point2").text.strip()
                mall_info_data.append(["안읽은 쪽지", unread_msg])
            except:
                pass

            # 받은쪽지 (추가)
            try:
                recv_msg = self.driver.find_element(
                    By.XPATH, "//li[@class='msg']//span[@class='even']/following-sibling::em").text.strip()
                mall_info_data.append(["받은쪽지", recv_msg])
            except:
                pass

            # 클린위반 (추가)
            try:
                clean_violation = self.driver.find_element(By.CSS_SELECTOR, "li.clean em.point2 a").text.strip()
                mall_info_data.append(["클린위반", clean_violation])
            except:
                pass

            self.driver.switch_to.default_content()

            # 창 닫기
            if len(self.driver.window_handles) > 1:
                self.driver.close()
                self.driver.switch_to.window(main_window)

            return report_data, mall_info_data

        except Exception as e:
            print(f"    -> 쇼핑파트너센터 수집 실패: {e}")
            if len(self.driver.window_handles) > 1:
                try:
                    self.driver.close()
                    self.driver.switch_to.window(main_window)
                except:
                    pass
            return report_data, mall_info_data

    def save_to_sheets(self, store_name, marketing_data, report_data, mall_info_data, channel_data=None):
        """데이터 저장 (data111.py와 동일한 레이아웃)"""
        try:
            if not self.marketing_spreadsheet:
                self.connect_spreadsheet()

            # 최대 행/열 계산
            max_rows = max(
                len(marketing_data) if marketing_data else 0,
                len(report_data) if report_data else 0,
                len(mall_info_data) if mall_info_data else 0,
                len(channel_data) if channel_data else 0
            )
            max_rows = max(max_rows + 100, 1000)
            max_cols = 35  # S열(19) + 전체채널(2열) + 여유

            try:
                ws = self.marketing_spreadsheet.worksheet(store_name)
                if ws.row_count < max_rows or ws.col_count < max_cols:
                    ws.resize(rows=max_rows, cols=max_cols)
            except:
                ws = self.marketing_spreadsheet.add_worksheet(store_name, max_rows, max_cols)

            ws.clear()

            # 마케팅분석 데이터 (A~G열)
            if marketing_data and len(marketing_data) > 0:
                ws.update(values=marketing_data, range_name='A1')
                print(f"    -> 마케팅분석 {len(marketing_data)}개 행 저장 완료 (A~G열)")

            # 상품클릭리포트 (I열~)
            if report_data and len(report_data) > 0:
                ws.update(values=report_data, range_name='I1')
                print(f"    -> 상품클릭리포트 {len(report_data)}개 행 저장 완료 (I열~)")

            # 쇼핑몰 정보 (Q열~)
            if mall_info_data and len(mall_info_data) > 0:
                ws.update(values=mall_info_data, range_name='Q1')
                print(f"    -> 쇼핑몰 정보 {len(mall_info_data)}개 행 저장 완료 (Q열~)")

            # 전체채널 데이터 (S열~)
            if channel_data and len(channel_data) > 0:
                ws.update(values=channel_data, range_name='S1')
                print(f"    -> 전체채널 {len(channel_data)}개 행 저장 완료 (S열~)")

            print(f"  -> 시트 저장 완료: {store_name}", flush=True)

        except Exception as e:
            print(f"구글 시트 저장 실패: {e}")

    def do_logout(self):
        try:
            self.driver.get("https://nid.naver.com/nidlogin.logout?returl=https://sell.smartstore.naver.com/")
            time.sleep(2)
        except:
            pass


if __name__ == "__main__":
    import sys
    import asyncio
    from google.oauth2.service_account import Credentials

    try:
        account_ids_str = os.environ.get("MARKETING_ACCOUNT_IDS", "")
        spreadsheet_key = os.environ.get("MARKETING_SPREADSHEET_KEY", "")
        if not account_ids_str or not spreadsheet_key:
            print("[ERROR] 환경변수 부족")
            sys.exit(1)

        account_ids = account_ids_str.split(",")

        credentials_file = os.environ.get("SERVICE_ACCOUNT_JSON", "credentials.json")
        if not os.path.exists(credentials_file):
            credentials_file = os.path.join(os.path.dirname(__file__), "credentials.json")
            if not os.path.exists(credentials_file):
                credentials_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "credentials.json")

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(credentials_file, scopes=scopes)
        gc = gspread.authorize(creds)

        main_sheet_key = os.environ.get("SPREADSHEET_KEY", "")
        if not main_sheet_key:
            sys.exit(1)

        main_wb = gc.open_by_key(main_sheet_key)
        accounts_ws = main_wb.worksheet("계정목록")
        accounts_data = accounts_ws.get_all_records()

        selected_accounts = []
        for account in accounts_data:
            platform = str(account.get("platform") or account.get("플랫폼") or "").strip()
            if "스마트" not in platform and "smart" not in platform.lower():
                continue

            aid = str(account.get("login_id") or account.get("아이디") or account.get("로그인ID") or "").strip()
            aname = str(account.get("store_name") or account.get("스토어명") or "").strip()
            apw = str(account.get("password") or account.get("비밀번호") or account.get("패스워드") or "").strip()

            matched = False
            for req in account_ids:
                if req.strip() == aid or req.strip() == aname:
                    matched = True
                    break

            if matched:
                selected_accounts.append({
                    'login_id': aid,
                    'password': apw,
                    'store_name': aname,
                    'platform': 'smartstore'
                })
                print(f"[INFO] 선택됨: {aid}")

        if not selected_accounts:
            print("[ERROR] 매칭된 계정 없음")
            sys.exit(1)

        collector = MarketingDataCollector(gc, spreadsheet_key)

        async def run():
            task_id = "cli"
            prog = {task_id: {'status': 'running', 'logs': [], 'current': 0}}
            await collector.collect_multiple_accounts(selected_accounts, task_id, prog)
            for l in prog[task_id]['logs']:
                print(l)

        asyncio.run(run())

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
