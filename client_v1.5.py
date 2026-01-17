"""
프코노미 클라이언트 프로그램
- 시스템 트레이 상주
- 웹서버 연동 자동로그인 (크롬 디버깅 세션 유지)
- 올인원 작업, 알리 수집 등 기능
"""
import sys
import os
import json
import time
import subprocess
import threading
import requests
import re
import socket
from pathlib import Path
from datetime import datetime

import websocket  # pip install websocket-client

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSystemTrayIcon, QMenu, QTabWidget,
    QLineEdit, QTextEdit, QComboBox, QGroupBox, QScrollArea,
    QFrame, QMessageBox, QCheckBox, QSpinBox, QGridLayout, QCompleter
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread, QStringListModel
from PyQt6.QtGui import QIcon, QAction, QFont, QColor, QPalette, QPixmap, QPainter

# 설정
CONFIG_FILE = Path(__file__).parent / "config.json"
CHROME_USER_DATA = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
DEBUG_PORT = 9222

# 기본 설정
DEFAULT_CONFIG = {
    "server_url": "http://182.222.231.21:8080",
    "api_key": "pkonomiautokey2024",
    "chrome_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "chrome_user_data_base": r"C:\autosystem\chrome_profiles",
    "debug_port": 9400,
    "auto_connect": True,
    "profiles": {}
}


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return DEFAULT_CONFIG.copy()


def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


class ChromeManager:
    """크롬 디버깅 모드 관리"""
    
    def __init__(self, config):
        self.config = config
        self.processes = {}  # profile_name: process
        self.ports = {}  # profile_name: port
    
    def is_port_in_use(self, port):
        """포트 사용 중인지 체크"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(('127.0.0.1', port)) == 0
    
    def find_available_port(self, start_port=9222):
        """사용 가능한 포트 찾기"""
        for port in range(start_port, start_port + 100):
            if not self.is_port_in_use(port):
                return port
        return None
        
    def get_profile_dir(self, profile_name):
        """프로필별 사용자 데이터 디렉토리"""
        base = Path(self.config.get("chrome_user_data_base", r"C:\autosystem\chrome_profiles"))
        return base / profile_name
    
    def launch_chrome(self, profile_name, url=None):
        """크롬 디버깅 모드로 실행"""
        # 이미 실행 중이면 기존 포트 반환
        if profile_name in self.processes:
            proc = self.processes[profile_name]
            if proc.poll() is None:
                port = self.ports.get(profile_name)
                return {"success": True, "message": "이미 실행 중", "port": port}
        
        chrome_path = self.config.get("chrome_path", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        if not Path(chrome_path).exists():
            return {"success": False, "message": f"크롬 경로 없음: {chrome_path}"}
        
        profile_dir = self.get_profile_dir(profile_name)
        profile_dir.mkdir(parents=True, exist_ok=True)
        
        # 사용 가능한 포트 찾기
        base_port = self.config.get("debug_port", 9222)
        port = self.find_available_port(base_port)
        if not port:
            return {"success": False, "message": "사용 가능한 포트 없음"}
        
        args = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-allow-origins=*",
            "--disable-background-networking",
            "--disable-client-side-phishing-detection",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-sync",
            "--new-window",
        ]
        
        if url:
            args.append(url)
        
        try:
            proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.processes[profile_name] = proc
            self.ports[profile_name] = port
            
            # 포트 열릴 때까지 빠르게 체크 (최대 2초)
            for _ in range(20):
                if self.is_port_in_use(port):
                    return {"success": True, "port": port, "pid": proc.pid}
                time.sleep(0.1)
            
            # 포트 안 열렸으면 다른 포트 체크
            for retry_port in range(port + 1, port + 10):
                if self.is_port_in_use(retry_port):
                    self.ports[profile_name] = retry_port
                    return {"success": True, "port": retry_port, "pid": proc.pid}
            
            return {"success": True, "port": port, "pid": proc.pid}
        except Exception as e:
            return {"success": False, "message": str(e)}
    
    def close_chrome(self, profile_name):
        """크롬 종료"""
        if profile_name in self.processes:
            proc = self.processes[profile_name]
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
            del self.processes[profile_name]
            return {"success": True}
        return {"success": False, "message": "실행 중 아님"}
    
    def is_running(self, profile_name):
        if profile_name in self.processes:
            return self.processes[profile_name].poll() is None
        return False


class ServerPoller(QThread):
    """서버 폴링 스레드"""
    login_request = pyqtSignal(dict)
    status_update = pyqtSignal(dict)
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = True
        self.interval = 3  # 3초마다 폴링
        
    def run(self):
        while self.running:
            try:
                url = f"{self.config['server_url']}/api/auto-login/pending"
                headers = {"X-API-Key": self.config.get("api_key", "")}
                
                resp = requests.get(url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("pending"):
                        self.login_request.emit(data)
                    self.status_update.emit({"connected": True})
                else:
                    self.status_update.emit({"connected": False, "error": resp.status_code})
                    
            except requests.exceptions.ConnectionError:
                self.status_update.emit({"connected": False, "error": "연결 실패"})
            except Exception as e:
                self.status_update.emit({"connected": False, "error": str(e)})
            
            time.sleep(self.interval)
    
    def stop(self):
        self.running = False



class AutoLoginWorker(QThread):
    """자동 로그인 워커 - PyChromeDevTools 사용"""
    log_signal = pyqtSignal(str)
    done_signal = pyqtSignal(bool, str)
    
    def __init__(self, chrome_manager, login_data, config):
        super().__init__()
        self.chrome = chrome_manager
        self.login_data = login_data
        self.config = config
        self.cdp = None
        
    def run(self):
        try:
            platform = self.login_data.get("platform", "")
            login_id = self.login_data.get("login_id", "")
            password = self.login_data.get("password", "")
            url = self.login_data.get("url", "")
            window_mode = self.config.get("window_mode", "new_window")
            
            self.log_signal.emit(f"[{platform}] {login_id} 로그인 시작...")
            
            # 프로필 이름 결정
            if window_mode == "new_tab":
                # 새 탭 모드: 플랫폼별로 하나의 프로필 공유
                profile_name = f"{platform}_shared"
            else:
                # 새 창 모드: 계정별 개별 프로필
                profile_name = f"{platform}_{login_id}"
            
            # 기존 창이 있는지 확인
            existing_port = self.chrome.ports.get(profile_name)
            is_new_chrome = existing_port is None
            
            if window_mode == "new_tab" and existing_port:
                # 기존 창에 새 탭 열기
                port = existing_port
                self.log_signal.emit(f"기존 창에 새 탭 열기 (포트: {port})")
                
                # CDP 연결
                self.ws = None
                self.cdp_id = 0
                
                try:
                    # 새 탭 생성
                    new_tab_resp = requests.put(f"http://localhost:{port}/json/new?about:blank", timeout=2)
                    if new_tab_resp.status_code == 200:
                        new_tab = new_tab_resp.json()
                        ws_url = new_tab.get("webSocketDebuggerUrl")
                        if ws_url:
                            self.ws = websocket.create_connection(ws_url, timeout=3)
                            self.log_signal.emit("새 탭 생성 완료")
                except Exception as e:
                    self.log_signal.emit(f"새 탭 생성 실패: {e}")
                    # 실패하면 새 창으로 폴백
                    is_new_chrome = True
            
            if is_new_chrome or not self.ws:
                # 새 크롬 실행
                result = self.chrome.launch_chrome(profile_name, "about:blank")
                
                if not result.get("success"):
                    self.done_signal.emit(False, result.get("message", "크롬 실행 실패"))
                    return
                
                port = result.get("port", 9222)
                self.log_signal.emit(f"크롬 실행됨 (포트: {port})")
                
                # CDP 직접 연결 (WebSocket)
                self.ws = None
                self.cdp_id = 0
                
                import time as t
                t0 = t.time()
                
                # WebSocket URL 찾을 때까지 대기 후 바로 연결
                ws_url = None
                for retry in range(50):  # 최대 5초
                    try:
                        tabs_resp = requests.get(f"http://localhost:{port}/json", timeout=1)
                        if tabs_resp.status_code == 200:
                            tabs = tabs_resp.json()
                            
                            for tab in tabs:
                                if tab.get("type") == "page" and tab.get("webSocketDebuggerUrl"):
                                    ws_url = tab.get("webSocketDebuggerUrl")
                                    break
                            
                            if ws_url:
                                break
                    except:
                        pass
                    time.sleep(0.1)
                
                if ws_url:
                    try:
                        self.ws = websocket.create_connection(ws_url, timeout=3)
                        self.log_signal.emit(f"CDP 연결: {t.time()-t0:.1f}초")
                    except Exception as e:
                        self.log_signal.emit(f"WS 연결 실패: {e}")
            
            if not self.ws:
                self.done_signal.emit(False, "CDP 연결 실패")
                return
            
            # 로그인 페이지로 이동
            self.log_signal.emit("페이지 이동 중...")
            self._cdp_navigate(url)
            
            # 페이지 로딩 대기 (로그인 폼 나올 때까지)
            for _ in range(50):  # 최대 5초
                try:
                    if self._cdp_evaluate('document.querySelector(\'input[type="password"]\') !== null'):
                        break
                except:
                    pass
                time.sleep(0.1)
            
            # 현재 URL 확인
            current_url = self._cdp_evaluate('window.location.href') or ""
            self.log_signal.emit(f"URL: {current_url}")
            
            # 플랫폼별 로그인 처리
            success = False
            if platform == "스마트스토어":
                success = self._login_smartstore(login_id, password)
            elif platform == "쿠팡":
                success = self._login_coupang(login_id, password)
            elif platform == "11번가":
                success = self._login_11st(login_id, password)
            elif platform in ["ESM통합", "지마켓", "옥션"]:
                success = self._login_esm(login_id, password)
            else:
                success = True
            
            if success:
                self.log_signal.emit("로그인 완료!")
                self.done_signal.emit(True, "로그인 성공")
            else:
                self.done_signal.emit(False, "로그인 실패")
            
            # 서버에 완료 알림
            try:
                requests.post(
                    f"{self.config['server_url']}/api/auto-login/complete",
                    headers={"X-API-Key": self.config.get("api_key", "")},
                    json={"platform": platform, "login_id": login_id, "success": success},
                    timeout=5
                )
            except:
                pass
            
            # WebSocket 정리
            try:
                if self.ws:
                    self.ws.close()
            except:
                pass
                
        except Exception as e:
            self.log_signal.emit(f"오류: {e}")
            self.done_signal.emit(False, str(e))
    
    def _cdp_send(self, method, params=None):
        """CDP 명령 전송"""
        self.cdp_id += 1
        msg = {"id": self.cdp_id, "method": method}
        if params:
            msg["params"] = params
        self.ws.send(json.dumps(msg))
        
        # 응답 대기
        while True:
            resp = json.loads(self.ws.recv())
            if resp.get("id") == self.cdp_id:
                return resp.get("result", {})
    
    def _cdp_evaluate(self, expression):
        """JavaScript 실행"""
        result = self._cdp_send("Runtime.evaluate", {"expression": expression})
        return result.get("result", {}).get("value")
    
    def _cdp_navigate(self, url):
        """페이지 이동"""
        return self._cdp_send("Page.navigate", {"url": url})
    
    def _get_cdp_value(self, result):
        """CDP 결과에서 value 추출 (호환용)"""
        if not result:
            return None
        if isinstance(result, dict):
            if "result" in result:
                inner = result["result"]
                if isinstance(inner, dict) and "result" in inner:
                    return inner["result"].get("value")
                return inner.get("value") if isinstance(inner, dict) else inner
        return result
    
    def _js_set_value(self, selector, value):
        """JS로 값 입력"""
        safe_selector = selector.replace('"', "'")
        js = f'''
            (function() {{
                var el = document.querySelector("{safe_selector}");
                if (el) {{
                    el.value = "{value}";
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return true;
                }}
                return false;
            }})()
        '''
        return self._cdp_evaluate(js) or False
    
    def _js_click(self, selector):
        """JS로 클릭"""
        safe_selector = selector.replace('"', "'")
        js = f'''
            (function() {{
                var el = document.querySelector("{safe_selector}");
                if (el) {{
                    el.click();
                    return true;
                }}
                return false;
            }})()
        '''
        return self._cdp_evaluate(js) or False
    
    def _js_exists(self, selector):
        """요소 존재 확인"""
        safe_selector = selector.replace('"', "'")
        js = f'document.querySelector("{safe_selector}") !== null'
        return self._cdp_evaluate(js) or False
    
    def _wait_element(self, selector, timeout=10):
        """요소 대기"""
        start = time.time()
        while time.time() - start < timeout:
            if self._js_exists(selector):
                return True
            time.sleep(0.5)
        return False
    
    def _get_page_source(self):
        """페이지 소스"""
        js = 'document.documentElement.outerHTML'
        return self._cdp_evaluate(js) or ""
    
    def _get_sms_code(self):
        """서버에서 SMS 인증번호 가져오기 (캐시된 코드 - 빠름)"""
        try:
            url = f"{self.config['server_url']}/api/sms/auth-code"
            headers = {"X-API-Key": self.config.get("api_key", "")}
            resp = requests.get(url, headers=headers, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                code = data.get("code")
                code_time = data.get("time", "")  # HH:MM:SS 형식
                if code and code.isdigit() and len(code) >= 4:
                    return {"code": code, "time": code_time}
        except:
            pass
        return None
    
    def _wait_sms_code(self, timeout=60, after_time=None):
        """SMS 인증번호 대기
        after_time: 이 시간 이후에 수신된 인증번호만 사용 (HH:MM:SS 형식)
        """
        self.log_signal.emit("SMS 인증번호 대기 중...")
        if after_time:
            self.log_signal.emit(f"기준 시간: {after_time} 이후 인증번호만 사용")
        
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(2)
            result = self._get_sms_code()
            if result:
                code = result.get("code")
                code_time = result.get("time", "")
                
                # 시간 기반 필터링
                if after_time and code_time:
                    # HH:MM:SS 형식 비교
                    if code_time <= after_time:
                        self.log_signal.emit(f"이전 인증번호 무시: {code} ({code_time} <= {after_time})")
                        continue
                
                if code:
                    self.log_signal.emit(f"인증번호 수신: {code} (시간: {code_time})")
                    return code
        
        self.log_signal.emit("인증번호 수신 실패 (타임아웃)")
        return None
    
    def _handle_2fa(self, input_selector, submit_selector=None):
        """2차 인증 처리"""
        from datetime import datetime
        
        # JavaScript alert 자동 수락 설정
        try:
            self._cdp_send("Page.enable")
            self._cdp_send("Page.handleJavaScriptDialog", {"accept": True})
        except:
            pass
        
        # ★ 인증번호 전송 전에 기존 인증번호 초기화 (clear_time 기록)
        try:
            clear_url = f"{self.config['server_url']}/api/sms/auth-code/clear"
            headers = {"X-API-Key": self.config.get("api_key", "")}
            clear_resp = requests.post(clear_url, headers=headers, timeout=5)
            if clear_resp.status_code == 200:
                self.log_signal.emit("기존 인증번호 초기화 완료")
            time.sleep(0.5)
        except Exception as e:
            self.log_signal.emit(f"인증번호 초기화 실패: {e}")
        
        # 인증번호 전송 전 현재 시간 기록 (이 시간 이후 인증번호만 사용)
        send_time = datetime.now().strftime("%H:%M:%S")
        self.log_signal.emit(f"인증번호 전송 시도 시간: {send_time}")
        
        # 먼저 "인증번호 전송" 버튼 클릭 시도
        self.log_signal.emit("인증번호 전송 버튼 클릭...")
        
        send_btn_js = '''
            (function() {
                var buttons = document.querySelectorAll('button, input[type="submit"], input[type="button"], a.btn, a');
                for (var btn of buttons) {
                    var text = (btn.textContent || btn.value || '').trim();
                    if (text.includes('인증번호 전송') || text.includes('인증번호발송') || 
                        text.includes('문자전송') || text.includes('인증요청')) {
                        btn.click();
                        return 'clicked: ' + text;
                    }
                }
                return 'not found';
            })()
        '''
        click_result = self._cdp_evaluate(send_btn_js) or ""
        self.log_signal.emit(f"전송 버튼: {click_result}")
        
        if "clicked" in str(click_result):
            time.sleep(0.5)
            
            # alert 팝업 확인 버튼 처리
            try:
                self._cdp_send("Page.handleJavaScriptDialog", {"accept": True})
            except:
                pass
            
            time.sleep(1)
        
        # SMS 인증번호 대기 (전송 시간 이후의 인증번호만 사용)
        code = self._wait_sms_code(after_time=send_time)
        if not code:
            return False
        
        # 인증번호 입력
        self.log_signal.emit(f"인증번호 입력: {code}")
        input_js = f'''
            (function() {{
                var input = document.querySelector('input#auth_num_kakao') || 
                            document.querySelector('input#auth_num_email') ||
                            document.querySelector('input[placeholder*="인증"], input[type="text"][maxlength="6"], input[name*="auth"], input#authNo');
                if (input) {{
                    input.value = "{code}";
                    input.dispatchEvent(new Event('input', {{bubbles: true}}));
                    input.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return 'input: ' + (input.id || input.name || 'found');
                }}
                return 'input not found';
            }})()
        '''
        input_result = self._cdp_evaluate(input_js) or ""
        self.log_signal.emit(f"입력 결과: {input_result}")
        
        time.sleep(0.5)
        
        # 확인 버튼
        confirm_js = '''
            (function() {
                var btn = document.querySelector('#auth_kakao_otp button.button_style_01[data-log-actionid-label="confirm"]') ||
                          document.querySelector('button[onclick*="login"]') ||
                          document.querySelector('#auth_kakao_otp button.button_style_01') ||
                          document.querySelector('#auth_email_otp button.button_style_01');
                if (btn) {
                    btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                    return 'clicked: ' + (btn.className || btn.id || 'found');
                }
                
                var buttons = document.querySelectorAll('button, input[type="submit"], a.btn');
                for (var b of buttons) {
                    var text = (b.textContent || b.value || '').trim();
                    if (text === '확인' || text === '인증' || text === '로그인') {
                        b.click();
                        return 'clicked: ' + text;
                    }
                }
                return 'not found';
            })()
        '''
        confirm_result = self._cdp_evaluate(confirm_js) or ""
        self.log_signal.emit(f"확인 버튼: {confirm_result}")
        
        time.sleep(1)
        return True
    
    def _generate_new_password(self, old_password):
        """마지막 특수문자 순환하여 새 비밀번호 생성"""
        if not old_password:
            return old_password
        
        special_chars = ['!', '@', '#', '$', '%', '^', '&', '*']
        last_char = old_password[-1]
        
        if last_char in special_chars:
            # 다음 특수문자로 변경
            idx = special_chars.index(last_char)
            new_char = special_chars[(idx + 1) % len(special_chars)]
            return old_password[:-1] + new_char
        else:
            # 마지막이 특수문자가 아니면 ! 추가
            return old_password + '!'
    
    def _update_password_to_server(self, platform, login_id, new_password):
        """서버에 새 비밀번호 저장"""
        try:
            url = f"{self.config['server_url']}/api/update-password"
            headers = {"X-API-Key": self.config.get("api_key", "")}
            resp = requests.post(url, headers=headers, json={
                "platform": platform,
                "login_id": login_id,
                "new_password": new_password
            }, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    self.log_signal.emit(f"비밀번호 서버 저장 완료")
                    return True
                else:
                    self.log_signal.emit(f"비밀번호 저장 실패: {data.get('message')}")
            return False
        except Exception as e:
            self.log_signal.emit(f"비밀번호 저장 오류: {e}")
            return False
    
    def _handle_password_change(self, platform=None, login_id=None, current_password=None):
        """비밀번호 변경 페이지 처리 - 실제 변경 수행"""
        page = self._get_page_source()
        
        # 비밀번호 변경 페이지인지 확인
        if not ("비밀번호" in page and ("변경" in page or "만료" in page)):
            return False
        
        # 11번가 비밀번호 변경 페이지 감지
        if "11st.co.kr" in (self._cdp_evaluate('window.location.href') or "") or "passwordCampaign" in page:
            self.log_signal.emit("11번가 비밀번호 변경 페이지 감지")
            
            if not current_password:
                self.log_signal.emit("현재 비밀번호 정보 없음 - 건너뛰기")
                # 30일 후에 변경 클릭
                skip_js = '''
                    (function() {
                        var btns = document.querySelectorAll('button, a');
                        for (var b of btns) {
                            if (b.textContent.includes('30일') || b.textContent.includes('후에')) {
                                b.click();
                                return true;
                            }
                        }
                        return false;
                    })()
                '''
                self._cdp_evaluate(skip_js)
                return True
            
            # 새 비밀번호 생성
            new_password = self._generate_new_password(current_password)
            self.log_signal.emit(f"비밀번호 변경: {current_password[-3:]}*** → {new_password[-3:]}***")
            
            time.sleep(0.5)
            
            # 현재 비밀번호 입력
            current_pw_js = f'''
                (function() {{
                    var inputs = document.querySelectorAll('input[type="password"]');
                    for (var inp of inputs) {{
                        var placeholder = inp.placeholder || '';
                        if (placeholder.includes('현재') || inp.id.includes('current') || inp.name.includes('current')) {{
                            inp.value = "{current_password}";
                            inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                            inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                            return 'current set';
                        }}
                    }}
                    // 첫 번째 password 입력칸
                    if (inputs.length >= 1) {{
                        inputs[0].value = "{current_password}";
                        inputs[0].dispatchEvent(new Event('input', {{bubbles: true}}));
                        return 'first set';
                    }}
                    return 'not found';
                }})()
            '''
            result = self._cdp_evaluate(current_pw_js)
            self.log_signal.emit(f"현재 비밀번호 입력: {result}")
            time.sleep(0.3)
            
            # 새 비밀번호 입력 (2개 필드)
            new_pw_js = f'''
                (function() {{
                    var inputs = document.querySelectorAll('input[type="password"]');
                    var filled = 0;
                    for (var i = 1; i < inputs.length; i++) {{
                        inputs[i].value = "{new_password}";
                        inputs[i].dispatchEvent(new Event('input', {{bubbles: true}}));
                        inputs[i].dispatchEvent(new Event('change', {{bubbles: true}}));
                        filled++;
                    }}
                    return 'filled: ' + filled;
                }})()
            '''
            result = self._cdp_evaluate(new_pw_js)
            self.log_signal.emit(f"새 비밀번호 입력: {result}")
            time.sleep(0.5)
            
            # 비밀번호 변경 버튼 클릭
            change_btn_js = '''
                (function() {
                    var btns = document.querySelectorAll('button, input[type="submit"]');
                    for (var b of btns) {
                        var text = b.textContent || b.value || '';
                        if (text.includes('비밀번호 변경') || text.includes('변경하기') || text.includes('확인')) {
                            if (!text.includes('30일') && !text.includes('후에')) {
                                b.click();
                                return 'clicked: ' + text;
                            }
                        }
                    }
                    return 'not found';
                })()
            '''
            result = self._cdp_evaluate(change_btn_js)
            self.log_signal.emit(f"변경 버튼: {result}")
            
            time.sleep(2)
            
            # "로그인 유지" 버튼 클릭
            keep_login_js = '''
                (function() {
                    var btns = document.querySelectorAll('button, a');
                    for (var b of btns) {
                        var text = b.textContent || '';
                        if (text.includes('로그인 유지')) {
                            b.click();
                            return 'clicked: 로그인 유지';
                        }
                    }
                    return 'not found';
                })()
            '''
            result = self._cdp_evaluate(keep_login_js)
            if result and 'clicked' in str(result):
                self.log_signal.emit(f"로그인 유지: {result}")
            
            time.sleep(2)
            
            # 비밀번호 변경 후 2차 인증이 나올 수 있음
            if self._check_2fa_needed():
                self.log_signal.emit("비밀번호 변경 후 2차 인증 감지")
                self._handle_2fa("input[type='text']", "button[type='submit']")
            
            time.sleep(1)
            
            # 서버에 새 비밀번호 저장
            if platform and login_id:
                self._update_password_to_server(platform, login_id, new_password)
                # 로그인 정보도 업데이트
                self.login_data['password'] = new_password
            
            return True
        
        # 다른 플랫폼은 기존처럼 건너뛰기
        skip_js = '''
            (function() {
                var btns = document.querySelectorAll('button, a, span');
                for (var b of btns) {
                    var text = b.textContent || '';
                    if (text.includes('다음에') || text.includes('나중에') || text.includes('건너뛰기') || text.includes('30일')) {
                        b.click();
                        return true;
                    }
                }
                return false;
            })()
        '''
        if self._cdp_evaluate(skip_js):
            self.log_signal.emit("비밀번호 변경 팝업 건너뜀")
            time.sleep(1)
            return True
        return False
    
    def _check_2fa_needed(self):
        """2차 인증 필요 여부"""
        page = self._get_page_source()
        keywords = ["인증번호", "본인확인", "추가 인증", "2단계"]
        return any(kw in page for kw in keywords)
    
    def _login_smartstore(self, login_id, password):
        try:
            time.sleep(1)  # 페이지 로딩 대기
            
            # ID 입력창 찾기
            id_exists = self._js_exists("input[id='id'], input[name='id'], input[placeholder*='아이디'], input[placeholder*='이메일']")
            if not id_exists:
                self.log_signal.emit("이미 로그인됨")
                return True
            
            # ID 입력 (React 호환 - nativeInputValueSetter 사용)
            id_input_js = f'''
                (function() {{
                    var el = document.querySelector("input[id='id'], input[name='id'], input[placeholder*='아이디'], input[placeholder*='이메일']");
                    if (!el) return 'input not found';
                    
                    el.focus();
                    var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    nativeSetter.call(el, "{login_id}");
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return 'id set: ' + el.value;
                }})()
            '''
            result = self._cdp_evaluate(id_input_js)
            self.log_signal.emit(f"ID 입력: {result}")
            time.sleep(0.3)
            
            # PW 입력 (React 호환)
            pw_input_js = f'''
                (function() {{
                    var el = document.querySelector("input[id='pw'], input[name='pw'], input[type='password']");
                    if (!el) return 'input not found';
                    
                    el.focus();
                    var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    nativeSetter.call(el, "{password}");
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return 'pw set';
                }})()
            '''
            result = self._cdp_evaluate(pw_input_js)
            self.log_signal.emit(f"PW 입력: {result}")
            time.sleep(0.3)
            
            # 로그인 버튼 클릭
            login_js = '''
                (function() {
                    var submitBtn = document.querySelector('button[type="submit"]');
                    if (submitBtn) {
                        submitBtn.click();
                        return 'clicked submit';
                    }
                    
                    var form = document.querySelector('form');
                    if (form) {
                        var formBtns = form.querySelectorAll('button');
                        for (var btn of formBtns) {
                            if (btn.textContent.trim() === '로그인') {
                                btn.click();
                                return 'clicked form button';
                            }
                        }
                    }
                    
                    var allBtns = document.querySelectorAll('button');
                    for (var btn of allBtns) {
                        var text = btn.textContent.trim();
                        var parent = btn.parentElement;
                        var isTab = btn.getAttribute('role') === 'tab' || 
                                    (parent && parent.getAttribute('role') === 'tablist') ||
                                    text.includes('아이디로');
                        if (text === '로그인' && !isTab) {
                            btn.click();
                            return 'clicked login button';
                        }
                    }
                    
                    var pw = document.querySelector('input[type="password"]');
                    if (pw) {
                        pw.focus();
                        pw.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', keyCode: 13, which: 13, bubbles: true}));
                        return 'enter key';
                    }
                    return 'not found';
                })()
            '''
            result = self._cdp_evaluate(login_js)
            self.log_signal.emit(f"로그인 버튼: {result}")
            
            time.sleep(2)
            
            # 2차 인증 처리
            if self._check_2fa_needed():
                self.log_signal.emit("2차 인증 감지")
                if not self._handle_2fa("input[type='text'], input[type='number']", "button[type='submit']"):
                    return False
            
            self._handle_password_change()
            return True
        except Exception as e:
            self.log_signal.emit(f"스마트스토어 로그인 오류: {e}")
            return False
    
    def _login_coupang(self, login_id, password):
        try:
            time.sleep(1)
            
            if not self._js_exists("input[name='username']"):
                self.log_signal.emit("이미 로그인됨")
                return True
            
            self._js_set_value("input[name='username']", login_id)
            time.sleep(0.2)
            self._js_set_value("input[name='password']", password)
            time.sleep(0.2)
            self._js_click("button[type='submit'], #kc-login")
            self.log_signal.emit("쿠팡 로그인 시도")
            
            time.sleep(2)
            
            if self._check_2fa_needed():
                if not self._handle_2fa("input[type='text']", "button[type='submit']"):
                    return False
            
            self._handle_password_change()
            return True
        except Exception as e:
            self.log_signal.emit(f"쿠팡 로그인 오류: {e}")
            return False
    
    def _login_11st(self, login_id, password):
        try:
            time.sleep(1)
            
            # 로그인 폼 요소 찾기
            if not self._js_exists("#loginName, input[name='loginName']"):
                self.log_signal.emit("이미 로그인됨")
                # 비밀번호 변경 페이지일 수 있음
                self._handle_password_change("11번가", login_id, password)
                return True
            
            # 아이디/비밀번호 입력
            self._js_set_value("#loginName, input[name='loginName']", login_id)
            time.sleep(0.2)
            self._js_set_value("#passWord, input[name='passWord']", password)
            time.sleep(0.2)
            
            # 로그인 버튼 클릭
            self._js_click("button.btn_login, button[type='submit']")
            self.log_signal.emit("11번가 로그인 시도")
            
            time.sleep(2)
            
            if self._check_2fa_needed():
                if not self._handle_2fa("input[type='text']", "button[type='submit']"):
                    return False
            
            # 비밀번호 변경 페이지 처리 (11번가 전용)
            time.sleep(1)
            self._handle_password_change("11번가", login_id, password)
            return True
        except Exception as e:
            self.log_signal.emit(f"11번가 로그인 오류: {e}")
            return False
    
    def _login_esm(self, login_id, password):
        try:
            time.sleep(1)
            
            if not self._js_exists("#txtID"):
                return True
            
            self._js_set_value("#txtID", login_id)
            time.sleep(0.2)
            self._js_set_value("#txtPWD", password)
            time.sleep(0.2)
            self._js_click("#btnLogin")
            self.log_signal.emit("ESM 로그인 시도")
            
            time.sleep(2)
            
            if self._check_2fa_needed():
                if not self._handle_2fa("input[type='text']", "#btnAuthConfirm"):
                    return False
            
            self._handle_password_change()
            return True
        except Exception as e:
            self.log_signal.emit(f"ESM 로그인 오류: {e}")
            return False


class MainWindow(QMainWindow):
    """메인 윈도우"""
    
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.chrome = ChromeManager(self.config)
        self.poller = None
        self.login_worker = None
        
        self.init_ui()
        self.init_tray()
        self.start_polling()
        
    def init_ui(self):
        self.setWindowTitle("프코노미 클라이언트")
        self.setMinimumSize(600, 500)
        
        # 중앙 위젯
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 상단 상태바
        status_frame = QFrame()
        status_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        status_layout = QHBoxLayout(status_frame)
        
        self.status_label = QLabel("● 서버 연결 확인 중...")
        self.status_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.status_label)
        
        status_layout.addStretch()
        
        self.server_url_label = QLabel(f"서버: {self.config['server_url']}")
        status_layout.addWidget(self.server_url_label)
        
        layout.addWidget(status_frame)
        
        # 탭 위젯
        tabs = QTabWidget()
        layout.addWidget(tabs)
        
        # 탭 1: 자동 로그인
        tabs.addTab(self.create_login_tab(), "🔐 자동 로그인")
        
        # 탭 2: 바로가기
        tabs.addTab(self.create_shortcuts_tab(), "🔗 바로가기")
        
        # 탭 3: 설정
        tabs.addTab(self.create_settings_tab(), "⚙️ 설정")
        
        # 로그 영역
        log_group = QGroupBox("로그")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.log_text.setStyleSheet("font-family: Consolas; font-size: 11px; background: #1e1e1e; color: #d4d4d4;")
        log_layout.addWidget(self.log_text)
        
        layout.addWidget(log_group)
        
    def create_login_tab(self):
        """자동 로그인 탭"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 설명
        desc = QLabel("웹서버에서 자동 로그인 요청 시 자동으로 처리합니다.\n크롬 디버깅 모드로 세션이 유지됩니다.")
        desc.setStyleSheet("color: #666; padding: 10px;")
        layout.addWidget(desc)
        
        # 빠른 로그인 (마켓 선택)
        quick_group = QGroupBox("빠른 로그인")
        quick_layout = QVBoxLayout(quick_group)
        
        # 플랫폼 선택
        platform_layout = QHBoxLayout()
        platform_layout.addWidget(QLabel("플랫폼:"))
        self.quick_platform_combo = QComboBox()
        self.quick_platform_combo.addItems(["스마트스토어", "쿠팡", "11번가", "ESM통합", "지마켓", "옥션"])
        self.quick_platform_combo.currentTextChanged.connect(self.on_quick_platform_changed)
        self.quick_platform_combo.setMinimumWidth(120)
        platform_layout.addWidget(self.quick_platform_combo)
        platform_layout.addStretch()
        quick_layout.addLayout(platform_layout)
        
        # 마켓 검색/선택
        market_layout = QHBoxLayout()
        market_layout.addWidget(QLabel("마켓:"))
        self.market_combo = QComboBox()
        self.market_combo.setEditable(True)
        self.market_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.market_combo.setMinimumWidth(250)
        self.market_combo.lineEdit().setPlaceholderText("마켓명 검색...")
        market_layout.addWidget(self.market_combo)
        
        # 마켓 목록 새로고침 버튼
        refresh_market_btn = QPushButton("🔄")
        refresh_market_btn.setFixedWidth(35)
        refresh_market_btn.clicked.connect(self.load_market_list)
        market_layout.addWidget(refresh_market_btn)
        quick_layout.addLayout(market_layout)
        
        # 빠른 로그인 버튼
        quick_login_btn = QPushButton("🔐 선택 마켓 로그인")
        quick_login_btn.clicked.connect(self.quick_login)
        quick_login_btn.setStyleSheet("padding: 10px; font-weight: bold; background: #4CAF50; color: white;")
        quick_layout.addWidget(quick_login_btn)
        
        layout.addWidget(quick_group)
        
        # 수동 로그인
        manual_group = QGroupBox("수동 입력 로그인")
        manual_layout = QGridLayout(manual_group)
        
        manual_layout.addWidget(QLabel("플랫폼:"), 0, 0)
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(["스마트스토어", "쿠팡", "11번가", "ESM통합", "지마켓", "옥션"])
        manual_layout.addWidget(self.platform_combo, 0, 1)
        
        manual_layout.addWidget(QLabel("아이디:"), 1, 0)
        self.login_id_input = QLineEdit()
        manual_layout.addWidget(self.login_id_input, 1, 1)
        
        manual_layout.addWidget(QLabel("비밀번호:"), 2, 0)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        manual_layout.addWidget(self.password_input, 2, 1)
        
        login_btn = QPushButton("🔐 로그인 실행")
        login_btn.clicked.connect(self.manual_login)
        login_btn.setStyleSheet("padding: 10px; font-weight: bold;")
        manual_layout.addWidget(login_btn, 3, 0, 1, 2)
        
        layout.addWidget(manual_group)
        
        # 실행 중인 세션
        session_group = QGroupBox("실행 중인 크롬 세션")
        session_layout = QVBoxLayout(session_group)
        
        self.session_list = QTextEdit()
        self.session_list.setReadOnly(True)
        self.session_list.setMaximumHeight(80)
        session_layout.addWidget(self.session_list)
        
        refresh_btn = QPushButton("🔄 새로고침")
        refresh_btn.clicked.connect(self.refresh_sessions)
        session_layout.addWidget(refresh_btn)
        
        layout.addWidget(session_group)
        layout.addStretch()
        
        # 마켓 목록 저장용
        self.market_list_cache = {}  # {platform: [{login_id, shop_alias, password}, ...]}
        
        return widget
    
    def load_market_list(self):
        """서버에서 마켓 목록 로드"""
        platform = self.quick_platform_combo.currentText()
        self.log(f"마켓 목록 로드 중... ({platform})")
        
        try:
            url = f"{self.config['server_url']}/api/accounts?platform={platform}"
            headers = {"X-API-Key": self.config.get("api_key", "")}
            resp = requests.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                accounts = data if isinstance(data, list) else data.get("accounts", [])
                
                # 캐시 저장
                self.market_list_cache[platform] = accounts
                
                # 콤보박스 업데이트
                self.market_combo.clear()
                
                items = []
                for acc in accounts:
                    # 한글 우선, 영어 fallback
                    shop_alias = (acc.get("스토어명") or 
                                  acc.get("shop_alias") or 
                                  acc.get("store_name") or 
                                  acc.get("아이디") or
                                  acc.get("login_id") or "")
                    login_id = acc.get("아이디") or acc.get("login_id") or ""
                    display = f"{shop_alias}" if shop_alias != login_id else login_id
                    items.append(display)
                    self.market_combo.addItem(display, acc)  # userData에 계정 정보 저장
                
                # 자동완성 설정
                completer = QCompleter(items)
                completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                completer.setFilterMode(Qt.MatchFlag.MatchContains)
                self.market_combo.setCompleter(completer)
                
                self.log(f"마켓 {len(accounts)}개 로드 완료")
            else:
                self.log(f"마켓 목록 로드 실패: {resp.status_code}")
        except Exception as e:
            self.log(f"마켓 목록 로드 오류: {e}")
    
    def on_quick_platform_changed(self, platform):
        """플랫폼 변경 시 마켓 목록 로드"""
        if platform in self.market_list_cache:
            # 캐시에서 로드
            accounts = self.market_list_cache[platform]
            self.market_combo.clear()
            items = []
            for acc in accounts:
                # 한글 우선, 영어 fallback
                shop_alias = (acc.get("스토어명") or 
                              acc.get("shop_alias") or 
                              acc.get("store_name") or 
                              acc.get("아이디") or
                              acc.get("login_id") or "")
                login_id = acc.get("아이디") or acc.get("login_id") or ""
                display = f"{shop_alias}" if shop_alias != login_id else login_id
                items.append(display)
                self.market_combo.addItem(display, acc)
            
            completer = QCompleter(items)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self.market_combo.setCompleter(completer)
        else:
            # 서버에서 로드
            self.load_market_list()
    
    def quick_login(self):
        """선택된 마켓으로 빠른 로그인"""
        idx = self.market_combo.currentIndex()
        if idx < 0:
            self.log("마켓을 선택하세요")
            return
        
        acc = self.market_combo.itemData(idx)
        if not acc:
            self.log("마켓 정보를 찾을 수 없습니다")
            return
        
        platform = self.quick_platform_combo.currentText()
        login_id = acc.get("login_id", "")
        password = acc.get("password", "")
        
        if not login_id or not password:
            self.log("로그인 정보가 없습니다")
            return
        
        self.log(f"빠른 로그인: {platform} / {login_id}")
        self.start_login(platform, login_id, password)
    
    def create_shortcuts_tab(self):
        """바로가기 탭"""
        from functools import partial
        
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        desc = QLabel("통합관리 시스템 바로가기")
        desc.setStyleSheet("color: #666; padding: 10px; font-size: 12px;")
        layout.addWidget(desc)
        
        # 바로가기 버튼 그리드
        btn_layout = QGridLayout()
        btn_layout.setSpacing(10)
        
        shortcuts = [
            ("📱 SMS", "sms"),
            ("🖥️ 관제센터", "monitor"),
            ("📊 마켓현황", "market-table"),
            ("💰 매출현황", "sales"),
            ("📋 계정관리", "accounts"),
            ("⚡ All-in-One", "allinone"),
            ("⏰ 스케줄러", "scheduler"),
            ("🔥 불사자", "bulsaja"),
            ("🔧 기타기능", "tools"),
            ("⚙️ 설정", "settings"),
        ]
        
        for i, (name, tab_id) in enumerate(shortcuts):
            btn = QPushButton(name)
            btn.setMinimumHeight(60)
            btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                        stop:0 #667eea, stop:1 #764ba2);
                    color: white;
                    font-size: 12px;
                    font-weight: bold;
                    border: none;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                        stop:0 #764ba2, stop:1 #667eea);
                }
                QPushButton:pressed {
                    background: #5a6fd6;
                }
            """)
            btn.clicked.connect(partial(self.open_web_tab, tab_id))
            btn_layout.addWidget(btn, i // 5, i % 5)
        
        layout.addLayout(btn_layout)
        layout.addStretch()
        
        return widget
    
    def open_web_tab(self, tab_id):
        """웹 탭 열기"""
        import webbrowser
        url = f"{self.config['server_url']}/#{tab_id}"
        webbrowser.open(url)
        self.log(f"웹 탭 열기: {tab_id}")
    
    def create_settings_tab(self):
        """설정 탭"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 서버 설정
        server_group = QGroupBox("서버 설정")
        server_layout = QGridLayout(server_group)
        
        server_layout.addWidget(QLabel("서버 URL:"), 0, 0)
        self.server_url_input = QLineEdit(self.config.get("server_url", ""))
        server_layout.addWidget(self.server_url_input, 0, 1)
        
        server_layout.addWidget(QLabel("API 키:"), 1, 0)
        self.api_key_input = QLineEdit(self.config.get("api_key", ""))
        server_layout.addWidget(self.api_key_input, 1, 1)
        
        layout.addWidget(server_group)
        
        # 크롬 설정
        chrome_group = QGroupBox("크롬 설정")
        chrome_layout = QGridLayout(chrome_group)
        
        chrome_layout.addWidget(QLabel("크롬 경로:"), 0, 0)
        self.chrome_path_input = QLineEdit(self.config.get("chrome_path", ""))
        chrome_layout.addWidget(self.chrome_path_input, 0, 1)
        
        chrome_layout.addWidget(QLabel("디버그 포트:"), 1, 0)
        self.debug_port_input = QSpinBox()
        self.debug_port_input.setRange(9000, 9999)
        self.debug_port_input.setValue(self.config.get("debug_port", 9222))
        chrome_layout.addWidget(self.debug_port_input, 1, 1)
        
        # 창 열기 방식 추가 (체크박스)
        self.new_tab_checkbox = QCheckBox("새 탭으로 열기 (기존 창에 추가)")
        self.new_tab_checkbox.setChecked(self.config.get("window_mode", "new_window") == "new_tab")
        chrome_layout.addWidget(self.new_tab_checkbox, 2, 0, 1, 2)
        
        layout.addWidget(chrome_group)
        
        # 저장 버튼
        save_btn = QPushButton("💾 설정 저장")
        save_btn.clicked.connect(self.save_settings)
        save_btn.setStyleSheet("padding: 10px; font-weight: bold;")
        layout.addWidget(save_btn)
        
        layout.addStretch()
        
        return widget
    
    def init_tray(self):
        """시스템 트레이 초기화"""
        self.tray = QSystemTrayIcon(self)
        
        # P 로고 아이콘 생성
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 배경 (파란색 그라데이션 효과를 단색으로)
        painter.setBrush(QColor("#4A90D9"))  # 파란색
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, 32, 32, 6, 6)
        
        # P 글자
        painter.setPen(QColor("white"))
        font = painter.font()
        font.setPixelSize(22)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "P")
        
        painter.end()
        
        self.tray.setIcon(QIcon(pixmap))
        
        # 트레이 메뉴
        menu = QMenu()
        
        show_action = QAction("열기", self)
        show_action.triggered.connect(self.show)
        menu.addAction(show_action)
        
        menu.addSeparator()
        
        quit_action = QAction("종료", self)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)
        
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()
        
        self.tray.setToolTip("프코노미 클라이언트")
    
    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.activateWindow()
    
    def closeEvent(self, event):
        """창 닫기 시 트레이로 최소화"""
        event.ignore()
        self.hide()
        self.tray.showMessage("프코노미 클라이언트", "시스템 트레이에서 실행 중입니다.", QSystemTrayIcon.MessageIcon.Information, 2000)
    
    def quit_app(self):
        """앱 종료"""
        if self.poller:
            self.poller.stop()
            self.poller.wait()
        QApplication.quit()
    
    def start_polling(self):
        """서버 폴링 시작"""
        self.poller = ServerPoller(self.config)
        self.poller.login_request.connect(self.handle_login_request)
        self.poller.status_update.connect(self.handle_status_update)
        self.poller.start()
        
        # 마켓 목록 초기 로드 (1초 후)
        QTimer.singleShot(1000, self.load_market_list)
    
    def handle_login_request(self, data):
        """로그인 요청 처리"""
        self.log(f"로그인 요청 수신: {data.get('platform')} - {data.get('login_id')}")
        
        if self.login_worker and self.login_worker.isRunning():
            self.log("이미 로그인 진행 중...")
            return
        
        self.login_worker = AutoLoginWorker(self.chrome, data, self.config)
        self.login_worker.log_signal.connect(self.log)
        self.login_worker.done_signal.connect(self.handle_login_done)
        self.login_worker.start()
    
    def handle_login_done(self, success, message):
        if success:
            self.tray.showMessage("로그인 완료", message, QSystemTrayIcon.MessageIcon.Information, 3000)
        else:
            self.tray.showMessage("로그인 실패", message, QSystemTrayIcon.MessageIcon.Warning, 3000)
    
    def handle_status_update(self, data):
        """서버 상태 업데이트"""
        if data.get("connected"):
            self.status_label.setText("● 서버 연결됨")
            self.status_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
        else:
            error = data.get("error", "알 수 없음")
            self.status_label.setText(f"● 서버 연결 안됨 ({error})")
            self.status_label.setStyleSheet("font-weight: bold; color: #f44336;")
    
    def manual_login(self):
        """수동 로그인"""
        platform = self.platform_combo.currentText()
        login_id = self.login_id_input.text().strip()
        password = self.password_input.text()
        
        if not login_id or not password:
            QMessageBox.warning(self, "입력 오류", "아이디와 비밀번호를 입력하세요.")
            return
        
        urls = {
            '스마트스토어': 'https://accounts.commerce.naver.com/login?url=https%3A%2F%2Fsell.smartstore.naver.com%2F%23%2Flogin-callback',
            '쿠팡': 'https://xauth.coupang.com/auth/realms/seller/protocol/openid-connect/auth?response_type=code&client_id=wing&redirect_uri=https%3A%2F%2Fwing.coupang.com%2Fsso%2Flogin%3FreturnUrl%3D%252F&state=login&login=true&scope=openid',
            '11번가': 'https://login.11st.co.kr/auth/front/selleroffice/login.tmall',
            'ESM통합': 'https://signin.esmplus.com/login',
            '지마켓': 'https://signin.esmplus.com/login',
            '옥션': 'https://signin.esmplus.com/login'
        }
        
        data = {
            "platform": platform,
            "login_id": login_id,
            "password": password,
            "url": urls.get(platform, "")
        }
        
        self.handle_login_request(data)
    
    def refresh_sessions(self):
        """세션 목록 새로고침"""
        sessions = []
        for name, proc in self.chrome.processes.items():
            if proc.poll() is None:
                sessions.append(f"✅ {name} (PID: {proc.pid})")
            else:
                sessions.append(f"❌ {name} (종료됨)")
        
        if sessions:
            self.session_list.setText("\n".join(sessions))
        else:
            self.session_list.setText("실행 중인 세션 없음")
    
    def run_allinone(self, task_id):
        """올인원 작업 실행"""
        self.log(f"올인원 작업 요청: {task_id}")
        try:
            url = f"{self.config['server_url']}/api/allinone/run"
            headers = {"X-API-Key": self.config.get("api_key", "")}
            resp = requests.post(url, headers=headers, json={"task": task_id}, timeout=10)
            if resp.status_code == 200:
                self.log("작업 요청 성공")
            else:
                self.log(f"작업 요청 실패: {resp.status_code}")
        except Exception as e:
            self.log(f"오류: {e}")
    
    def ali_launch_browser(self):
        """알리 브라우저 실행"""
        self.log("알리 브라우저 실행 요청...")
        try:
            url = f"{self.config['server_url']}/api/tools/ali/connect"
            headers = {"X-API-Key": self.config.get("api_key", "")}
            resp = requests.post(url, headers=headers, json={"port": 9222}, timeout=30)
            data = resp.json()
            if data.get("success"):
                self.log("알리 브라우저 실행 성공")
            else:
                self.log(f"실패: {data.get('message')}")
        except Exception as e:
            self.log(f"오류: {e}")
    
    def ali_collect(self):
        """알리 수집 시작"""
        sheet_url = self.ali_sheet_url.text().strip()
        month = self.ali_month.currentText()
        
        if not sheet_url:
            QMessageBox.warning(self, "입력 오류", "시트 URL을 입력하세요.")
            return
        
        self.log(f"알리 수집 시작: {month}")
        try:
            url = f"{self.config['server_url']}/api/tools/ali/collect"
            headers = {"X-API-Key": self.config.get("api_key", "")}
            resp = requests.post(url, headers=headers, json={"sheet_url": sheet_url, "month": month}, timeout=10)
            data = resp.json()
            if data.get("success"):
                self.log("수집 시작됨")
            else:
                self.log(f"실패: {data.get('message')}")
        except Exception as e:
            self.log(f"오류: {e}")
    
    def save_settings(self):
        """설정 저장"""
        self.config["server_url"] = self.server_url_input.text().strip()
        self.config["api_key"] = self.api_key_input.text().strip()
        self.config["chrome_path"] = self.chrome_path_input.text().strip()
        self.config["debug_port"] = self.debug_port_input.value()
        self.config["window_mode"] = "new_tab" if self.new_tab_checkbox.isChecked() else "new_window"
        
        save_config(self.config)
        self.server_url_label.setText(f"서버: {self.config['server_url']}")
        
        # 폴링 재시작
        if self.poller:
            self.poller.config = self.config
        
        QMessageBox.information(self, "저장 완료", "설정이 저장되었습니다.")
        self.log("설정 저장됨")
    
    def log(self, message):
        """로그 출력"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        # 스크롤 맨 아래로
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 트레이에서 계속 실행
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
