#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
구매대행 통합관리 시스템 - 백엔드 서버
- 담당자 로그인 (세션 기반)
- 계정 관리 (구글 시트 연동)
- SMS 통합 (3개 폰 프로필)
- 실시간 WebSocket
- 스케줄러 (APScheduler)

실행: python server.py
접속: http://localhost:8000 또는 http://서버IP:8000
"""

import os
import re
import sys
import json
import time

print("\n" + "="*50)
print("🚀 [2026-01-12 UPDATED] WEB SYSTEM SERVER STARTING...")
print("🚀 [CHECK] IF YOU SEE THIS, THE CODE IS RELOADED.")
print("="*50 + "\n")

import asyncio
import hashlib
import secrets
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Request, WebSocket, WebSocketDisconnect, BackgroundTasks, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
import io
import pandas as pd
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# APScheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from modules.delivery_check import DeliveryChecker
from modules.ali_tracking import AliTrackingCollector
from modules.daily_sync import DailyJournalSyncer
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.memory import MemoryJobStore

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# Playwright
from playwright.async_api import async_playwright, Page, BrowserContext

# ========== 설정 ==========
APP_DIR = Path(__file__).resolve().parent

# .env 파일 로드 (현재 폴더 또는 상위 폴더)
env_path = APP_DIR / ".env"
if not env_path.exists():
    env_path = APP_DIR.parent / ".env"
load_dotenv(env_path)
print(f"📁 .env 로드: {env_path} (존재: {env_path.exists()})")

# Playwright 브라우저 경로 설정 (sms_gui.py와 동일 - 다른 PC에서도 작동하도록)
PLAYWRIGHT_BROWSER_DIR = os.environ.get(
    "PLAYWRIGHT_BROWSERS_PATH",
    str(APP_DIR / "pw_browsers")
)
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = PLAYWRIGHT_BROWSER_DIR
print(f"🌐 Playwright 브라우저 경로: {PLAYWRIGHT_BROWSER_DIR}")

# Playwright (SMS 브라우저) - sync_playwright 사용 (sms_gui.py와 동일)
from playwright.sync_api import sync_playwright, Page, BrowserContext as SyncBrowserContext

# 구글 시트 설정
def get_rel_path(env_key, default_name):
    env_val = os.environ.get(env_key)
    if env_val:
        # 1. 절대 경로인 경우 그대로 확인
        if os.path.isabs(env_val) and os.path.exists(env_val):
            return env_val
        # 2. APP_DIR 기준 상대 경로 확인
        path_in_app = APP_DIR / env_val
        if path_in_app.exists():
            return str(path_in_app)
        # 3. 프로젝트 루트(APP_DIR.parent) 기준 상대 경로 확인
        path_in_root = APP_DIR.parent / env_val
        if path_in_root.exists():
            return str(path_in_root)
            
    # 로컬 디렉토리에서 기본 이름으로 찾기
    local_path = APP_DIR / default_name
    if local_path.exists():
        return str(local_path)
    
    # 상위 디렉토리(프로젝트 루트)에서 기본 이름으로 찾기
    parent_path = APP_DIR.parent / default_name
    if parent_path.exists():
        return str(parent_path)
        
    return str(local_path)

CREDENTIALS_FILE = get_rel_path("SERVICE_ACCOUNT_JSON", "autosms-466614-951e91617c69.json")
SPREADSHEET_KEY = os.environ.get("SPREADSHEET_KEY", "1r-ROJ7ksv6qOtOTXbkrprxu17EQmbO-n1J1pm_N5Hh8")
MARKETING_SPREADSHEET_KEY = os.environ.get("MARKETING_SPREADSHEET_KEY", "14l6Y7y7bHcn6LRGlfQ0QOKHNGWI5tFqPWRioxE8aoTo")

# 등록갯수 전용 인증 파일
COUNT_CREDENTIALS_FILE = get_rel_path("COUNT_CREDENTIALS_FILE", "auto-smartstore-update-61c3a948c45c.json")

# 시트 탭 이름
ACCOUNTS_TAB = "계정목록"  # 플랫폼 계정
USERS_TAB = "담당자"       # 담당자 로그인 정보
SMS_LOG_TAB = "SMS로그"    # SMS 발송 기록 (선택)
WORK_LOG_SHEET = "작업로그"  # 작업 기록 (캘린더용)

# 폰 프로필
PHONE_PROFILES = ["8295", "8217", "4682"]

# 프로필 ID → 실제 디렉토리 매핑 (QR 인증 잘못된 경우 여기서 교체)
# 현재: 정상 (디렉토리 이름 교체 완료됨)
PROFILE_DIR_MAPPING = {
    "8295": "8295",
    "8217": "8217",
    "4682": "4682",
}

# PC 식별자 (빈 문자열 - 프로필 직접 사용, 다른 PC로 복사 가능)
import socket
SERVER_ID = ""  # pw_sessions/8295 직접 사용

# 시트 컬럼 매핑 (실제 시트 헤더와 일치)
SHEET_COLUMNS = [
    "플랫폼",
    "아이디",
    "패스워드",
    "쇼핑몰 별칭",
    "사업자번호",
    "스마트스토어 API 연동용 판매자ID",
    "스마트스토어 애플리케이션 ID",
    "스마트스토어 애플리케이션 시크릿",
    "쿠팡 업체코드",
    "쿠팡 Access Key",
    "쿠팡 Secret Key",
    "11번가 API KEY",
    "ESM통합계정",  # 지마켓/옥션이 연결된 ESM통합 계정 ID
    "ESM통합비밀번호"  # ESM통합 계정 비밀번호
]

# 세션 설정
SESSION_EXPIRE_HOURS = 8
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# 서버 설정
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8000))

# ========== 스케줄러 설정 ==========
scheduler = AsyncIOScheduler(
    jobstores={'default': MemoryJobStore()},
    timezone='Asia/Seoul'
)

# 스케줄 저장 (파일 기반)
SCHEDULES_FILE = APP_DIR / "schedules.json"

def load_schedules() -> List[Dict]:
    """저장된 스케줄 로드"""
    if SCHEDULES_FILE.exists():
        try:
            with open(SCHEDULES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return []

def save_schedules(schedules: List[Dict]):
    """스케줄 저장"""
    with open(SCHEDULES_FILE, 'w', encoding='utf-8') as f:
        json.dump(schedules, f, ensure_ascii=False, indent=2)

# 스케줄 작업 실행 함수
async def execute_scheduled_task(schedule_id: str, platform: str, task: str, stores: List[str], options: Dict):
    """스케줄된 작업 실행"""
    print(f"[스케줄러] 작업 시작: {schedule_id} - {platform}/{task}")

    # 작업 로그 기록
    store_count = len(stores) if stores else 0
    log_work(f"스케줄-{task}", platform, store_count, f"스케줄: {schedule_id}", "예약")
    
    try:
        if platform == "스마트스토어":
            # smartstore_allinone.py subprocess 실행 (환경변수로 작업/스토어 전달)
            env = os.environ.copy()
            env["SERVICE_ACCOUNT_JSON"] = os.environ.get("SERVICE_ACCOUNT_JSON", "")
            env["SPREADSHEET_KEY"] = os.environ.get("SPREADSHEET_KEY", "")
            env["PARALLEL_STORES"] = "true"
            env["PARALLEL_WORKERS"] = "4"
            env["PYTHONIOENCODING"] = "utf-8"
            env["AIO_TASK"] = task  # 작업명 전달 (대상 스토어는 시트의 '활성화' 컬럼 참조)
            
            module_path = os.path.join(os.path.dirname(__file__), "modules", "smartstore_allinone.py")
            log_file = os.path.join(os.path.dirname(__file__), "logs", f"schedule_{schedule_id}.log")
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            
            print(f"[스케줄러] smartstore_allinone.py 실행: {task}")
            
            process = subprocess.Popen(
                [sys.executable, module_path],
                stdout=open(log_file, "w", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                env=env,
                cwd=os.path.dirname(__file__)
            )
            
            # 프로세스 완료 대기 (최대 30분)
            try:
                process.wait(timeout=1800)
                print(f"[스케줄러] 프로세스 완료: exit code {process.returncode}")
            except subprocess.TimeoutExpired:
                process.kill()
                print(f"[스케줄러] 프로세스 타임아웃 (30분)")
        
        elif platform == "11번가":
            # 11번가 작업
            print(f"[스케줄러] 11번가 {task} - 아직 미구현")
        
        # 실행 결과 기록
        schedules = load_schedules()
        for s in schedules:
            if s.get('id') == schedule_id:
                s['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                s['run_count'] = s.get('run_count', 0) + 1
                break
        save_schedules(schedules)
        
        print(f"[스케줄러] 작업 완료: {schedule_id}")
    except Exception as e:
        print(f"[스케줄러] 작업 오류: {schedule_id} - {e}")
        import traceback
        traceback.print_exc()

# 불사자 시스템 설정
BULSAJA_SYSTEMS = {
    1: {
        "name": "반대량프리미엄 1",
        "folder": "C:\\자동화시스템",
        "json": "civic-kayak-410304-03d60ceb535f.json",
        "sheet_key": "19glTugSCcouvFQWALuguAO0jeJt1gdnhI-zbDhMds_Y"
    },
    2: {
        "name": "반대량프리미엄 2",
        "folder": "C:\\자동화시스템2",
        "json": "ornate-chemist-466108-p8-0ac0d011d2cd.json",
        "sheet_key": "1lMY0g2P2TKFTI23-zqGO48oCLPCTGqRK2KJcYfD4pf8"
    }
}

BULSAJA_TAB_NAME = "njb_상품관리"
BULSAJA_SHEET_KEY = "19glTugSCcouvFQWALuguAO0jeJt1gdnhI-zbDhMds_Y"
BULSAJA_GROUP_SELECTOR_CELL = "C15"  # 기본값, 모드에 따라 변경
BULSAJA_GROUP_TOKEN_FMT = "{n}번 마켓그룹"

# 플랫폼 설정
PLATFORM_CONFIG = {
    "스마트스토어": {
        "login_url": "https://accounts.commerce.naver.com/login?url=https%3A%2F%2Fsell.smartstore.naver.com%2F%23%2Flogin-callback",
        "color": "#03C75A"
    },
    "쿠팡": {
        "login_url": "https://xauth.coupang.com/auth/realms/seller/protocol/openid-connect/auth?response_type=code&client_id=wing&redirect_uri=https%3A%2F%2Fwing.coupang.com%2Fsso%2Flogin?returnUrl%3D%252F&state=78ad277c-bf25-4992-8f48-c523b37ce667&login=true&ui_locales=ko-KR&scope=openid",
        "color": "#E31837"
    },
    "11번가": {
        "login_url": "https://login.11st.co.kr/auth/front/selleroffice/login.tmall",
        "color": "#FF5A00"
    },
    "ESM통합": {
        "login_url": "https://signin.esmplus.com/login",
        "color": "#6C5CE7",
        "tab_selector": "button[data-montelena-acode='700000273']"  # ESM PLUS 탭
    },
    "지마켓": {
        "login_url": "https://signin.esmplus.com/login",
        "color": "#00C73C",
        "tab_selector": "button[data-montelena-acode='700000274']"  # 지마켓 탭
    },
    "옥션": {
        "login_url": "https://signin.esmplus.com/login",
        "color": "#FF0000",
        "tab_selector": "button[data-montelena-acode='700000275']"  # 옥션 탭
    }
}

# ========== 데이터 모델 ==========
class LoginRequest(BaseModel):
    username: str
    password: str

class AccountModel(BaseModel):
    platform: str
    login_id: str
    password: str = ""
    shop_alias: str = ""  # 하위 호환성 유지
    store_name: str = ""  # 통일된 필드명
    business_number: str = ""
    # 스마트스토어
    ss_seller_id: str = ""
    ss_app_id: str = ""
    ss_app_secret: str = ""
    # 쿠팡
    cp_vendor_code: str = ""
    cp_access_key: str = ""
    cp_secret_key: str = ""
    # 11번가
    st_api_key: str = ""
    api_key: str = ""  # 11번가 API KEY (별칭)
    # ESM 연결
    esm_master: str = ""
    esm_master_pw: str = ""
    esm_id: str = ""  # ESM ID
    esm_pw: str = ""  # ESM PW
    # 기타
    owner: str = ""
    usage: str = ""

class SMSRequest(BaseModel):
    phone_profile: str
    to_number: str
    message: str

@dataclass
class SMSMessage:
    phone_profile: str
    sender: str
    content: str
    timestamp: str
    auth_code: Optional[str] = None

# ========== 권한 레벨 ==========
# 구글 시트 "담당자" 탭의 "권한" 열에 입력
ROLE_ADMIN = "admin"      # 모든 권한
ROLE_OPERATOR = "oper"    # 운영자 (삭제 불가)
ROLE_VIEWER = "viewer"    # 뷰어

# 권한별 허용 기능
ROLE_PERMISSIONS = {
    ROLE_ADMIN: ["view", "edit", "delete", "sms_send", "sms_control", "bulsaja"],
    ROLE_OPERATOR: ["view", "edit", "sms_send", "sms_control", "bulsaja"],
    ROLE_VIEWER: ["view", "sms_view"],
}

def get_role_permissions(role: str) -> list:
    """권한 레벨에 따른 허용 기능 목록 반환"""
    return ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS[ROLE_VIEWER])

def has_permission(role: str, permission: str) -> bool:
    """특정 권한이 있는지 확인"""
    return permission in get_role_permissions(role)

# ========== 세션 관리 ==========
sessions: Dict[str, Dict] = {}  # token -> {username, name, role, expires}

def create_session(username: str, name: str = None, role: str = ROLE_VIEWER) -> str:
    token = secrets.token_urlsafe(32)
    sessions[token] = {
        "username": username,
        "name": name or username,
        "role": role,
        "expires": datetime.now() + timedelta(hours=SESSION_EXPIRE_HOURS)
    }
    return token

def verify_session(token: str) -> Optional[Dict]:
    if not token or token not in sessions:
        return None
    session = sessions[token]
    if datetime.now() > session["expires"]:
        del sessions[token]
        return None
    return {
        "username": session["username"],
        "name": session["name"],
        "role": session.get("role", ROLE_VIEWER)
    }

# API Key (크롬 확장용)
API_KEY = os.environ.get("API_KEY", "pkonomiautokey2024")

def get_current_user(request: Request) -> Dict:
    # 내부 요청(127.0.0.1)은 시스템 계정으로 bypass
    client_host = request.client.host if request.client else ""
    if client_host in ("127.0.0.1", "localhost", "::1"):
        return {"username": "system", "name": "시스템", "role": ROLE_ADMIN}
    
    # API Key 인증 (크롬 확장용)
    api_key = request.headers.get("X-API-Key")
    if api_key and api_key == API_KEY:
        return {"username": "extension", "name": "크롬확장", "role": ROLE_ADMIN}
    
    token = request.cookies.get("session_token")
    user = verify_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return user

def require_permission(request: Request, permission: str) -> Dict:
    """특정 권한 필요한 API에서 사용"""
    user = get_current_user(request)
    if not has_permission(user.get("role", ROLE_VIEWER), permission):
        raise HTTPException(status_code=403, detail="권한이 없습니다")
    return user

# ========== 구글 시트 관리 ==========
class GoogleSheetManager:
    def __init__(self):
        self.client = None
        self.sheet = None
        self.connected = False
    
    def connect(self):
        try:
            print(f"📂 인증 파일 경로: {CREDENTIALS_FILE}")
            print(f"📂 인증 파일 존재: {os.path.exists(CREDENTIALS_FILE)}")
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
            self.client = gspread.authorize(creds)
            
            # 스프레드시트 키로 열기 (우선) 또는 이름으로 열기
            if SPREADSHEET_KEY:
                self.sheet = self.client.open_by_key(SPREADSHEET_KEY)
            else:
                self.sheet = self.client.open("계정관리")
            
            self.connected = True
            print(f"✅ 구글 시트 연결됨: {self.sheet.title}")
            return True
        except Exception as e:
            print(f"❌ 구글 시트 연결 실패: {e}")
            self.connected = False
            return False
    
    def get_worksheet(self, name: str):
        if not self.connected:
            return None
        try:
            return self.sheet.worksheet(name)
        except:
            return None

    def get_external_worksheet(self, key: str, name: str):
        """특정 키를 가진 외부 스프레드시트의 워크시트 가져오기"""
        if not self.connected:
            return None
        try:
            external_sheet = self.client.open_by_key(key)
            return external_sheet.worksheet(name)
        except Exception as e:
            print(f"❌ 외부 시트 워크시트 로드 실패 ({key}, {name}): {e}")
            return None

    def open_worksheet_with_creds(self, creds_path: str, sheet_key: str, ws_name: str):
        """특정 인증 파일로 특정 시트의 워크시트 열기"""
        try:
            if not os.path.exists(creds_path):
                print(f"❌ 인증 파일 없음: {creds_path}")
                return None
            scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
            creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
            client = gspread.authorize(creds)
            sheet = client.open_by_key(sheet_key)
            return sheet.worksheet(ws_name)
        except Exception as e:
            print(f"❌ 외부 인증 시트 로드 실패 ({ws_name}): {e}")
            return None
    
    # 담당자 인증
    def verify_user(self, username: str, password: str) -> Dict:
        ws = self.get_worksheet(USERS_TAB)
        if not ws:
            # 시트 없으면 기본 계정 허용 (admin/admin)
            if username == "admin" and password == "admin":
                return {"success": True, "name": "관리자", "role": ROLE_ADMIN}
            return {"success": False, "name": "", "role": ""}
        
        try:
            records = ws.get_all_records()
            pw_hash = hashlib.sha256(password.encode()).hexdigest()
            
            for row in records:
                # 아이디 컬럼 찾기 (공백 허용 및 유연한 매칭)
                row_user = None
                for k, v in row.items():
                    if k.strip() == "아이디":
                        row_user = v
                        break
                
                if row_user and str(row_user).strip() == str(username).strip():
                    # 패스워드 컬럼 찾기
                    stored_pw = ""
                    for k, v in row.items():
                        if k.strip() in ["패스워드", "비밀번호"]:
                            stored_pw = v
                            break
                    
                    staff_name = row.get("담당자명", username)
                    
                    # 평문 또는 해시 비교 (공백 제거)
                    s_pw = str(stored_pw).strip()
                    if s_pw == str(password).strip() or s_pw == pw_hash:
                        # 권한 매핑 (한글 -> 영어)
                        role_val = str(row.get("권한", "")).strip()
                        if role_val == "관리자":
                            role = ROLE_ADMIN
                        elif role_val == "운영자":
                            role = ROLE_OPERATOR
                        elif role_val == "뷰어":
                            role = ROLE_VIEWER
                        else:
                            role = role_val if role_val in [ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER] else ROLE_VIEWER
                        return {"success": True, "name": staff_name, "role": role}
            
            return {"success": False, "name": "", "role": ""}
        except Exception as e:
            print(f"사용자 인증 오류: {e}")
            return {"success": False, "name": "", "role": ""}
    
    # 계정 목록 조회
    def get_accounts(self, platform: str = None) -> List[Dict]:
        ws = self.get_worksheet(ACCOUNTS_TAB)
        if not ws:
            return []
        
        try:
            records = ws.get_all_records()
            accounts = []
            
            # 첫 번째 레코드의 컬럼명 출력 (디버그)
            if records:
                first_row_keys = list(records[0].keys())
                print(f"[계정목록] 컬럼명: {first_row_keys}")
                # ESM 관련 컬럼 확인
                esm_keys = [k for k in first_row_keys if 'ESM' in k or 'esm' in k]
                print(f"[계정목록] ESM 관련 컬럼: {esm_keys}")
            
            for idx, row in enumerate(records):
                # 스토어명: 스토어명 우선, 하위 호환용으로 다른 컬럼명도 체크
                store_name = (row.get("스토어명", "") or 
                              row.get("쇼핑몰 별칭", "") or 
                              row.get("스토어명", "") or 
                              row.get("마켓명", "") or
                              row.get("계정명", ""))
                
                # ESM ID/PW: 공백 포함된 키도 시도
                esm_id = ""
                esm_pw = ""
                for key in row.keys():
                    key_stripped = key.strip()
                    if key_stripped == "ESM ID":
                        esm_id = row[key]
                    elif key_stripped == "ESM PW":
                        esm_pw = row[key]
                
                # 첫 3개 계정만 ESM 정보 로그
                if idx < 3 and (row.get("플랫폼") in ["지마켓", "옥션"]):
                    print(f"[계정목록] {row.get('플랫폼')} {row.get('아이디')}: esm_id='{esm_id}', esm_pw='{esm_pw}'")
                
                # 한글 키 우선 + 영어 키 하위 호환
                acc = {
                    # 기본 정보 (한글 + 영어)
                    "플랫폼": row.get("플랫폼", ""),
                    "platform": row.get("플랫폼", ""),  # 하위 호환
                    
                    "아이디": row.get("아이디", ""),
                    "login_id": row.get("아이디", ""),  # 하위 호환
                    
                    "패스워드": row.get("패스워드") or row.get("비밀번호", ""),
                    "password": row.get("패스워드") or row.get("비밀번호", ""),  # 하위 호환
                    
                    "스토어명": store_name,
                    
                    "사업자번호": row.get("사업자번호", ""),
                    "business_number": row.get("사업자번호", ""),  # 하위 호환
                    
                    "용도": row.get("용도", ""),
                    "usage": row.get("용도", ""),  # 하위 호환
                    
                    "소유자": row.get("소유자", ""),
                    "owner": row.get("소유자", ""),  # 하위 호환
                    
                    # 스마트스토어
                    "ss_seller_id": row.get("스마트스토어 API 연동용 판매자ID", ""),
                    "ss_app_id": row.get("스마트스토어 애플리케이션 ID", ""),
                    "ss_app_secret": row.get("스마트스토어 애플리케이션 시크릿", ""),
                    
                    # 쿠팡
                    "cp_vendor_code": row.get("쿠팡 업체코드", ""),
                    "cp_access_key": row.get("쿠팡 Access Key", ""),
                    "cp_secret_key": row.get("쿠팡 Secret Key", ""),
                    
                    # 11번가
                    "st_api_key": row.get("11번가 API KEY", ""),
                    "api_key": row.get("11번가 API KEY", ""),  # 별칭
                    
                    # ESM 연결
                    "esm_master": row.get("ESM통합계정", ""),
                    "esm_master_pw": row.get("ESM통합비밀번호", ""),
                    "esm_id": esm_id,
                    "esm_pw": esm_pw
                }
                if acc["아이디"]:
                    if platform is None or acc["플랫폼"] == platform:
                        accounts.append(acc)
            return accounts
        except Exception as e:
            print(f"계정 조회 오류: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    # 계정 추가
    def add_account(self, account: Dict) -> bool:
        ws = self.get_worksheet(ACCOUNTS_TAB)
        if not ws:
            return False
        
        try:
            row = [
                account.get("platform", ""),
                account.get("login_id", ""),
                account.get("password", ""),
                account.get("스토어명", ""),
                account.get("business_number", ""),
                account.get("ss_seller_id", ""),
                account.get("ss_app_id", ""),
                account.get("ss_app_secret", ""),
                account.get("cp_vendor_code", ""),
                account.get("cp_access_key", ""),
                account.get("cp_secret_key", ""),
                account.get("st_api_key", ""),
                account.get("esm_master", ""),
                account.get("esm_master_pw", "")
            ]
            ws.append_row(row)
            return True
        except Exception as e:
            print(f"계정 추가 오류: {e}")
            return False
    
    # 계정 수정
    def update_account(self, old_id: str, platform: str, account: Dict) -> bool:
        ws = self.get_worksheet(ACCOUNTS_TAB)
        if not ws:
            return False
        
        try:
            # 헤더 가져오기
            headers = ws.row_values(1)
            header_map = {h.strip(): i for i, h in enumerate(headers)}
            
            records = ws.get_all_records()
            
            # 필드-헤더 매핑
            field_to_header = {
                "platform": "플랫폼",
                "login_id": "아이디",
                "password": "패스워드",
                "스토어명": "쇼핑몰 별칭",
                "business_number": "사업자번호",
                "ss_seller_id": "스마트스토어 API 연동용 판매자ID",
                "ss_app_id": "스마트스토어 애플리케이션 ID",
                "ss_app_secret": "스마트스토어 애플리케이션 시크릿",
                "cp_vendor_code": "쿠팡 업체코드",
                "cp_access_key": "쿠팡 Access Key",
                "cp_secret_key": "쿠팡 Secret Key",
                "st_api_key": "11번가 API KEY",
                "api_key": "11번가 API KEY",
                "esm_master": "ESM통합계정",
                "esm_master_pw": "ESM통합비밀번호",
                "esm_id": "ESM ID",
                "esm_pw": "ESM PW",
                "owner": "소유자",
                "usage": "용도"
            }
            
            # 지마켓/옥션 ESM 동기화 필요 여부
            esm_sync = platform in ["지마켓", "옥션"] and ("esm_id" in account or "esm_pw" in account)
            other_platform = "옥션" if platform == "지마켓" else "지마켓"
            
            all_updates = []
            found = False
            
            for i, row in enumerate(records):
                row_id = row.get("아이디")
                row_platform = row.get("플랫폼")
                row_num = i + 2
                
                # 현재 계정 업데이트
                if row_id == old_id and row_platform == platform:
                    found = True
                    for field, value in account.items():
                        header = field_to_header.get(field)
                        if header and header in header_map:
                            col_idx = header_map[header]
                            col_letter = chr(65 + col_idx) if col_idx < 26 else f"{chr(64 + col_idx // 26)}{chr(65 + col_idx % 26)}"
                            all_updates.append({"range": f"{col_letter}{row_num}", "values": [[value if value else ""]]})
                
                # 지마켓↔옥션 ESM 동기화
                elif esm_sync and row_id == old_id and row_platform == other_platform:
                    for field in ["esm_id", "esm_pw"]:
                        if field in account:
                            header = field_to_header.get(field)
                            if header and header in header_map:
                                col_idx = header_map[header]
                                col_letter = chr(65 + col_idx) if col_idx < 26 else f"{chr(64 + col_idx // 26)}{chr(65 + col_idx % 26)}"
                                all_updates.append({"range": f"{col_letter}{row_num}", "values": [[account[field] if account[field] else ""]]})
            
            if found and all_updates:
                ws.batch_update(all_updates)
            return found
        except Exception as e:
            print(f"계정 수정 오류: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    # 계정 삭제
    def delete_account(self, account_id: str, platform: str) -> bool:
        ws = self.get_worksheet(ACCOUNTS_TAB)
        if not ws:
            return False
        
        try:
            records = ws.get_all_records()
            for i, row in enumerate(records):
                if row.get("아이디") == account_id and row.get("플랫폼") == platform:
                    ws.delete_rows(i + 2)
                    return True
            return False
        except Exception as e:
            print(f"계정 삭제 오류: {e}")
            return False

# ========== SMS 브라우저 관리 (sms_gui.py 기반) ==========
# 창 설정 (3개 창이 1920px 모니터에 들어오도록)
WIN_LEFT = 10
WIN_TOP = 50
WIN_WIDTH = 400  # 3개 창이 여유있게 들어오도록 더 축소 (500 -> 400)
WIN_HEIGHT = 800
WIN_GAP = 10  # 창 간격

class SMSBrowserManager:
    def __init__(self):
        self.playwright = None
        self.browsers: Dict[str, BrowserContext] = {}
        self.pages: Dict[str, Page] = {}
        self.ready: Dict[str, bool] = {p: False for p in PHONE_PROFILES}
        self.messages: List[SMSMessage] = []
        self.auth_codes: Dict[str, dict] = {}  # {phone: {"code": "123456", "time": "12:34:56"}}
        self.image_cache: Dict[str, Dict[str, str]] = {}  # {sender: {element_idx: filepath}} - 번호별 이미지 캐시
        self.image_cache_limit = 10  # 번호당 최대 캐시 수
        self.cache_file = APP_DIR / "sms_cache.json"
        self.lock = asyncio.Lock()  # 동시 실행 방지를 위한 락 추가
        self.load_cache()

    def load_cache(self):
        """파일에서 SMS 캐시 로드"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.messages = [SMSMessage(**m) for m in data.get("messages", [])]
                    self.auth_codes = data.get("auth_codes", {})
                print(f"📦 [SMS] 캐시 로드 완료: {len(self.messages)}건")
            except Exception as e:
                print(f"⚠️ [SMS] 캐시 로드 오류: {e}")
                self.messages = []
        else:
            self.messages = []

    def save_cache(self):
        """SMS 캐시를 파일에 저장"""
        try:
            # 최근 1000개 정도만 유지 (성능 고려)
            save_msgs = [asdict(m) for m in self.messages[-1000:]]
            data = {
                "messages": save_msgs,
                "auth_codes": self.auth_codes,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ [SMS] 캐시 저장 오류: {e}")
    
    def _add_to_image_cache(self, sender: str, element_idx: str, filepath: str):
        """이미지 캐시에 추가 (번호별 10개 제한)"""
        if sender not in self.image_cache:
            self.image_cache[sender] = {}
        
        cache = self.image_cache[sender]
        cache[element_idx] = filepath
        
        # 캐시 제한 초과 시 오래된 것 삭제
        if len(cache) > self.image_cache_limit:
            oldest_key = list(cache.keys())[0]
            del cache[oldest_key]
    
    def _get_from_image_cache(self, sender: str, element_idx: str) -> Optional[str]:
        """이미지 캐시에서 가져오기"""
        if sender in self.image_cache:
            return self.image_cache[sender].get(element_idx)
        return None
    
    async def init_playwright(self):
        """Playwright 초기화 (async)"""
        if self.playwright is None:
            from playwright.async_api import async_playwright
            self.playwright = await async_playwright().start()
    
    async def _clear_emulation_overrides(self, page: Page, context: BrowserContext):
        """Emulation(뷰포트) 오버라이드 완전 해제"""
        try:
            cdp = await context.new_cdp_session(page)
            try:
                await cdp.send("Emulation.clearDeviceMetricsOverride", {})
            except:
                pass
            try:
                await cdp.send("Emulation.setVisibleSize", {"width": 0, "height": 0})
            except:
                pass
        except Exception as e:
            print(f"[warn] emulation clear failed: {e}")
    
    async def _wait_ui_ready(self, page: Page, timeout_ms: int = 15000) -> bool:
        """UI 준비 대기"""
        sel_any = (
            'a[data-e2e-start-button], '
            'textarea[data-e2e-message-input-box], '
            '[data-e2e-conversation-list]'
        )
        try:
            await page.wait_for_selector(sel_any, timeout=timeout_ms)
            return True
        except:
            return False
    
    async def _stabilize_messages_ui(self, page: Page, context: BrowserContext):
        """초기 진입 시 빈 화면이면 단계적으로 복구"""
        if await self._wait_ui_ready(page, 8000):
            return
        
        # 1) soft reload
        try:
            await page.evaluate("""
                (()=>{
                  const href = location.href;
                  if (href.includes('/web/conversations/new')) {
                    location.href = 'https://messages.google.com/web';
                  } else {
                    location.reload();
                  }
                })();
            """)
        except:
            pass
        
        if await self._wait_ui_ready(page, 12000):
            return
        
        # 2) hard reload
        try:
            cdp = await context.new_cdp_session(page)
            await cdp.send("Page.reload", {"ignoreCache": True})
        except:
            pass
        
        if await self._wait_ui_ready(page, 12000):
            return
        
        # 3) 다시 이동
        try:
            await page.goto("https://messages.google.com/web", wait_until="domcontentloaded", timeout=60000)
        except:
            pass
        
        await self._wait_ui_ready(page, 15000)
    
    async def _ensure_conversation_visible(self, page: Page):
        """대화 미선택 상태면 첫 대화 클릭 혹은 '채팅 시작' 누르기"""
        try:
            if await page.locator('textarea[data-e2e-message-input-box]').count():
                return
            item = page.locator('[role="listitem"], mws-conversation-list-item').first
            if await item.count() and await item.is_visible():
                await item.click()
                await page.wait_for_timeout(300)
                return
            start = page.locator('a[data-e2e-start-button], a[aria-label="채팅 시작"], a[aria-label="Start chat"]')
            if await start.count() and await start.first.is_visible():
                await start.first.click()
                await page.wait_for_timeout(300)
        except:
            pass
    
    async def launch_browser(self, profile_id: str):
        """브라우저 실행 (async - sms_gui.py 방식)"""
        if self.playwright is None:
            from playwright.async_api import async_playwright
            self.playwright = await async_playwright().start()
        
        # 기존 인증된 프로필 사용 (pw_sessions 바로 아래)
        actual_dir_name = PROFILE_DIR_MAPPING.get(profile_id, profile_id)
        profile_dir = APP_DIR / "pw_sessions" / actual_dir_name
        
        # 새 프로필이면 sms_gui 프로필의 식별자를 복사 (다른 PC에서도 같은 브라우저로 인식되도록)
        source_profile = APP_DIR / "auto_sms" / "chrome_profile"
        if not profile_dir.exists() and source_profile.exists():
            profile_dir.mkdir(parents=True, exist_ok=True)
            # Local State 파일 복사 (client_id2, machine_id 등 브라우저 식별자 포함)
            source_local_state = source_profile / "Local State"
            if source_local_state.exists():
                import shutil
                shutil.copy2(source_local_state, profile_dir / "Local State")
                print(f"📋 [{profile_id}] 브라우저 식별자 복사됨 (from sms_gui)")
        else:
            profile_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            APP_URL = "https://messages.google.com/web"
            idx = PHONE_PROFILES.index(profile_id)
            
            # sms_gui.py와 완전히 동일한 설정 (이동 가능한 프로필)
            args = [
                "--disable-infobars",
                "--no-sandbox", "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--no-first-run", "--no-default-browser-check",
                "--disable-features=TranslateUI,CalculateNativeWinOcclusion",
                "--wm-window-animations-disabled",
            ]
            args.insert(0, f"--app={APP_URL}")
            args.append(f"--window-position={WIN_LEFT + idx * (WIN_WIDTH + WIN_GAP)},{WIN_TOP}")
            args.append(f"--window-size={WIN_WIDTH},{WIN_HEIGHT}")
            
            context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                viewport=None,
                args=args,
            )
            
            pages = context.pages
            page = pages[0] if pages else await context.new_page()
            
            # 타임아웃 설정
            context.set_default_timeout(45000)
            page.set_default_timeout(45000)
            page.set_default_navigation_timeout(60000)
            
            # sms_gui.py와 동일: 페이지가 비어있거나 다른 URL이면 이동
            APP_URL = "https://messages.google.com/web"
            try:
                current_url = page.url or ""
                if current_url == "about:blank":
                    await page.goto(APP_URL, wait_until="domcontentloaded", timeout=60000)
                elif "messages.google.com/web" not in current_url:
                    await page.goto(APP_URL, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            
            # sms_gui.py와 동일: UI 로드 대기
            try:
                await page.wait_for_selector(
                    'a[data-e2e-start-button], textarea[data-e2e-message-input-box]', 
                    timeout=60000
                )
            except Exception:
                pass
            
            # CDP를 사용하여 창 크기 강제 설정 (sms_gui.py와 동일 - 프로필 저장값 무시)
            try:
                cdp = await context.new_cdp_session(page)
                target = await cdp.send("Browser.getWindowForTarget")
                wid = target.get("windowId")
                if wid:
                    left_pos = WIN_LEFT + idx * (WIN_WIDTH + WIN_GAP)
                    await cdp.send("Browser.setWindowBounds", {
                        "windowId": wid,
                        "bounds": {
                            "left": left_pos,
                            "top": WIN_TOP,
                            "width": WIN_WIDTH,
                            "height": WIN_HEIGHT,
                            "windowState": "normal"
                        }
                    })
            except Exception as e:
                print(f"⚠️ [{profile_id}] 창 크기 강제 설정 실패: {e}")
            
            self.browsers[profile_id] = context
            self.pages[profile_id] = page
            self.ready[profile_id] = True
            
            # sms_gui.py와 동일하게 초기화 (멀티 세션 지원을 위해 필수)
            await self._clear_emulation_overrides(page, context)
            await self._stabilize_messages_ui(page, context)
            await self._ensure_conversation_visible(page)
            
            print(f"✅ [{profile_id}] 브라우저 시작됨")
            
        except Exception as e:
            print(f"❌ [{profile_id}] 브라우저 시작 실패: {e}")
            self.ready[profile_id] = False
    
    async def launch_all(self):
        """모든 브라우저 실행 (async)"""
        for profile_id in PHONE_PROFILES:
            await self.launch_browser(profile_id)
    
    async def refresh_messages(self) -> List[SMSMessage]:
        """메시지 새로고침 (부분 업데이트 및 캐시 강화)"""
        async with self.lock:  # 락 적용하여 중복 실행 및 경합 방지
            updated_any = False
            
            # 딕셔너리 복사본으로 순회 (동시 수정 방지)
            for profile_id, page in list(self.pages.items()):
                if not self.ready.get(profile_id):
                    continue
                
                try:
                    # 해당 프로필의 새로운 메시지 목록 수집 (임시 리스트)
                    new_profile_messages = []
                    # 대화 목록 항목들 가져오기
                    items = await page.locator('mws-conversation-list-item').all()
                    
                    # 최대 50개까지 가져오기
                    for idx, item in enumerate(items[:50]):
                        try:
                            sender = await item.locator('.name').first.inner_text() if await item.locator('.name').count() else ""
                            content = await item.locator('.snippet, .text-content').first.inner_text() if await item.locator('.snippet, .text-content').count() else ""
                            
                            # 타임스탬프 추출 및 정밀화
                            timestamp = ""
                            ts_loc = item.locator('mws-relative-timestamp.snippet-timestamp')
                            if await ts_loc.count():
                                raw_ts = await ts_loc.first.inner_text()
                                full_ts = await ts_loc.first.get_attribute("title") or ""
                                
                                # 1. '수요일 수' 같은 중복 제거
                                import re
                                # '수요일 수', '금요일 금' 등 패턴 제거
                                raw_val = raw_ts or ""
                                clean_ts = re.sub(r'([가-힣]요일)\s+\1', r'\1', raw_val)
                                # '금요일 금' 등 첫 글자 중복 패턴 제거 (예: 금요일 금 -> 금요일)
                                clean_ts = re.sub(r'(([가-힣])요일)\s+\2(?!\w)', r'\1', clean_ts)
                                
                                # 2. 오늘 문자인 경우 시간 표시 (title 활용)
                                import datetime
                                now = datetime.datetime.now()
                                # Windows 환경에서는 %-m 대신 f-string 사용 (파딩 제거 호환성)
                                today_str = f"{now.month}. {now.day}." # '1. 16.'
                                alternative_today = f"{now.year}. {now.month}. {now.day}." # '2026. 1. 16.'
                                
                                # title에 오늘 날짜나 '오늘', 'Today'가 있으면 시간 추출
                                has_today = False
                                if full_ts:
                                    if today_str in full_ts or alternative_today in full_ts:
                                        has_today = True
                                    elif any(x in full_ts.lower() for x in ['오늘', 'today']):
                                        has_today = True
                                
                                if has_today:
                                    # '오후 8:15' 또는 '20:15' 형태 추출
                                    time_match = re.search(r'((오전|오후)\s+\d{1,2}:\d{2}|\d{1,2}:\d{2})', full_ts)
                                    if time_match:
                                        timestamp = time_match.group(1)
                                
                                if not timestamp:
                                    timestamp = clean_ts.strip()
                            
                            auth_code = self._extract_auth_code(content)
                            
                            if content:
                                msg = SMSMessage(
                                    phone_profile=profile_id,
                                    sender=sender.strip(),
                                    content=content.strip()[:100],
                                    timestamp=timestamp,
                                    auth_code=auth_code
                                )
                                new_profile_messages.append(msg)
                                
                                # 최신 인증코드 업데이트 (화면의 가장 첫 번째 항목일 때)
                                if auth_code and idx == 0:
                                    from datetime import datetime
                                    msg_ts = self._parse_relative_time(timestamp)
                                    self.auth_codes[profile_id] = {
                                        "code": auth_code,
                                        "time": timestamp or datetime.now().strftime("%H:%M:%S"),
                                        "timestamp": msg_ts
                                    }
                        except:
                            continue
                    
                    # 해당 프로필에서 메시지 수집에 성공했을 경우에만 목록 갱신
                    if new_profile_messages:
                        # 기존 리스트에서 해당 프로필 메시지만 제거 후 합치기
                        self.messages = [m for m in self.messages if m.phone_profile != profile_id]
                        self.messages.extend(new_profile_messages)
                        updated_any = True
                        
                except Exception as e:
                    print(f"[{profile_id}] 메시지 읽기 오류: {e}")
            
            # 하나라도 갱신되었다면 캐시 저장
            if updated_any:
                self.save_cache()
            
            return self.messages

    def _parse_relative_time(self, time_str: str) -> float:
        """상대 시간 문자열을 Unix timestamp로 변환
        예: "14분", "2시간", "AM 10:42", "오후 3:23", "어제", "월요일", "조금 전", "방금"
        """
        import time
        from datetime import datetime, timedelta
        
        now = datetime.now()
        time_str = time_str.strip()
        
        try:
            # "조금 전", "방금", "지금" 등 - 가장 최신
            if any(x in time_str for x in ['조금', '방금', '지금', 'now', 'just']):
                return now.timestamp()
            
            # "N분" 또는 "N분 전"
            if '분' in time_str:
                match = re.search(r'(\d+)', time_str)
                if match:
                    minutes = int(match.group(1))
                    return (now - timedelta(minutes=minutes)).timestamp()
            
            # "N시간" 또는 "N시간 전"
            if '시간' in time_str:
                match = re.search(r'(\d+)', time_str)
                if match:
                    hours = int(match.group(1))
                    return (now - timedelta(hours=hours)).timestamp()
            
            # "AM/PM HH:MM" 또는 "오전/오후 HH:MM"
            am_pm_match = re.search(r'(AM|PM|오전|오후)\s*(\d{1,2}):(\d{2})', time_str, re.IGNORECASE)
            if am_pm_match:
                period, hour, minute = am_pm_match.groups()
                hour = int(hour)
                minute = int(minute)
                if period.upper() in ['PM', '오후'] and hour != 12:
                    hour += 12
                elif period.upper() in ['AM', '오전'] and hour == 12:
                    hour = 0
                msg_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if msg_time > now:  # 미래면 어제
                    msg_time -= timedelta(days=1)
                return msg_time.timestamp()
            
            # "어제"
            if '어제' in time_str:
                return (now - timedelta(days=1)).timestamp()
            
            # 요일 ("월요일", "화요일" 등)
            weekdays = {'월': 0, '화': 1, '수': 2, '목': 3, '금': 4, '토': 5, '일': 6}
            for day_name, day_num in weekdays.items():
                if day_name in time_str:
                    days_ago = (now.weekday() - day_num) % 7
                    if days_ago == 0:
                        days_ago = 7  # 같은 요일이면 지난주
                    return (now - timedelta(days=days_ago)).timestamp()
            
        except:
            pass
        
        # 파싱 실패 시 현재 시간
        return time.time()

    def _extract_auth_code(self, text: str) -> Optional[str]:
        if not text:
            return None
        
        # 인증 관련 키워드가 있어야 인증코드로 인식
        keywords = ['인증', '확인', 'code', 'verify', '본인', 'OTP', '코드', '승인', '번호입니다', '번호는']
        has_keyword = any(kw.lower() in text.lower() for kw in keywords)
        
        # 키워드 없으면 인증코드 아님
        if not has_keyword:
            return None
        
        # 전화번호 패턴 제외 (010-XXXX-XXXX, 02-XXXX-XXXX 등)
        # 메시지에서 전화번호 부분 제거
        text_cleaned = re.sub(r'01[0-9]-?\d{3,4}-?\d{4}', '', text)
        text_cleaned = re.sub(r'0\d{1,2}-?\d{3,4}-?\d{4}', '', text_cleaned)
        
        patterns = [
            r'\[(\d{6})\]', r'\((\d{6})\)',  # 대괄호/괄호 안의 6자리 우선 (가장 확실함)
            r'(?<!\d)(\d{6})(?!\d)',        # 연속된 6자리
            r'\[(\d{5})\]', r'\((\d{5})\)',
            r'\[(\d{4})\]', r'\((\d{4})\)',
            r'(?<!\d)(\d{5})(?!\d)',
            r'(?<!\d)(\d{4})(?!\d)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_cleaned)
            if match:
                code = match.group(1)
                
                # 4자리 오탐 필터 강화
                if len(code) == 4:
                    # 1. 연도 패턴 (20XX, 19XX)
                    if code.startswith('20') or code.startswith('19'):
                        continue
                    # 2. 시간 패턴 (HHMM) - 엄격한 키워드 체크
                    if int(code[:2]) <= 24 and int(code[2:]) < 60:
                        strict_keywords = ['인증', 'code', 'OTP', '코드', '확인', '승인']
                        if not any(kw.lower() in text.lower() for kw in strict_keywords):
                            continue
                
                return code
        
        return None
    
    async def send_message(self, profile_id: str, to_number: str, message: str, file_path: str = None) -> bool:
        """메시지 전송 (sms_gui.py의 send_via_messages 기반) - 파일 첨부 지원"""
        if profile_id not in self.pages or not self.ready.get(profile_id):
            print(f"[{profile_id}] 브라우저 미실행 또는 준비 안됨")
            return False

        page = self.pages[profile_id]
        context = self.browsers[profile_id]

        try:
            # UI 안정화
            await self._stabilize_messages_ui(page, context)
            await self._ensure_conversation_visible(page)

            # 홈으로(뒤로)
            try:
                back = page.locator('button[aria-label="뒤로 가기"], button[aria-label="Back"]')
                if await back.count() and await back.first.is_visible():
                    await back.first.click()
                    await page.wait_for_timeout(300)
            except:
                pass

            # 새 대화 시작
            start = page.locator('a[data-e2e-start-button], a[aria-label="채팅 시작"], a[aria-label="Start chat"]')
            await start.wait_for(state="visible", timeout=15000)
            await start.first.click()
            await page.wait_for_timeout(200)

            # 번호 입력
            contact = page.locator('input[data-e2e-contact-input]')
            if not await contact.count():
                contact = page.locator('input[type="text"]')
            await contact.wait_for(state="visible", timeout=15000)
            await contact.fill("")
            await contact.type(to_number, delay=40)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(600)

            # 입력창 포커스/스크롤 보정 + 오버라이드 해제
            try:
                await page.evaluate("""
                  (()=>{
                    const ta=document.querySelector('textarea[data-e2e-message-input-box]')||
                             document.querySelector('textarea[aria-label="메시지"]')||
                             document.querySelector('textarea[aria-label="Message"]')||
                             document.querySelector('textarea');
                    if(ta){ ta.scrollIntoView({block:'center'}); ta.focus(); }
                  })();
                """)
                await self._clear_emulation_overrides(page, context)
            except:
                pass

            # 파일 첨부가 있으면 먼저 처리
            if file_path and os.path.exists(file_path):
                print(f"[{profile_id}] 파일 첨부 시작: {file_path}")
                try:
                    # 첨부 버튼 클릭 (+ 버튼 또는 클립 아이콘)
                    attach_btn = page.locator('button[data-e2e-attach-button], button[aria-label="첨부"], button[aria-label="Attach"], mws-attachment-button button')
                    if await attach_btn.count():
                        await attach_btn.first.click()
                        await page.wait_for_timeout(300)

                    # 파일 input 요소 찾기 (hidden input)
                    file_input = page.locator('input[type="file"]')
                    if await file_input.count():
                        await file_input.first.set_input_files(file_path)
                        print(f"[{profile_id}] 파일 첨부됨: {file_path}")
                        await page.wait_for_timeout(1000)  # 파일 업로드 대기
                    else:
                        print(f"[{profile_id}] 파일 input 요소를 찾을 수 없음")
                except Exception as e:
                    print(f"[{profile_id}] 파일 첨부 오류: {e}")

            # 메시지 입력 (텍스트가 있으면)
            if message:
                textarea = page.locator('textarea[data-e2e-message-input-box]')
                if not await textarea.count():
                    textarea = page.locator("textarea").last
                await textarea.wait_for(state="visible", timeout=15000)
                await textarea.fill(message)

            # 전송 (Enter 또는 전송 버튼)
            try:
                # 전송 버튼이 있으면 클릭
                send_btn = page.locator('button[data-e2e-send-button], button[aria-label="전송"], button[aria-label="Send"]')
                if await send_btn.count() and await send_btn.first.is_visible():
                    await send_btn.first.click()
                else:
                    await page.keyboard.press("Enter")
            except:
                await page.keyboard.press("Enter")
            await page.wait_for_timeout(400)

            print(f"[{profile_id}] 전송 완료: {to_number}" + (f" (파일: {file_path})" if file_path else ""))
            return True

        except Exception as e:
            print(f"[{profile_id}] 전송 오류: {e}")
            return False
    
    async def close_all(self):
        for context in self.browsers.values():
            try:
                await context.close()
            except:
                pass
        self.browsers.clear()
        self.pages.clear()
        
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
    
    async def get_conversation_detail(self, profile_id: str, sender: str, offset: int = 0, limit: int = 20) -> Dict[str, Any]:
        """대화 상세 내용 가져오기 (클릭해서 열기)
        offset: 0이면 최근 20개, 20이면 이전 20개...
        limit: 가져올 메시지 수
        """
        if profile_id not in self.pages or not self.ready.get(profile_id):
            return {"error": "브라우저 미실행"}
        
        page = self.pages[profile_id]
        context = self.browsers[profile_id]
        
        # 다운로드 폴더 생성
        download_dir = APP_DIR / "downloads" / profile_id
        download_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # 뒤로가기 (대화 목록으로)
            try:
                back = page.locator('button[aria-label="뒤로 가기"], button[aria-label="Back"]')
                if await back.count() and await back.first.is_visible():
                    await back.first.click()
                    await page.wait_for_timeout(300)
            except:
                pass
            
            # 1. 대화 목록에서 해당 발신자 찾아 클릭
            items = await page.locator('mws-conversation-list-item').all()
            found = False
            
            # sender에서 숫자만 추출
            import re
            sender_digits = re.sub(r'[^0-9]', '', sender)
            
            for item in items:
                try:
                    name = await item.locator('.name').first.inner_text() if await item.locator('.name').count() else ""
                    name_digits = re.sub(r'[^0-9]', '', name)
                    
                    # 매칭 정밀도 강화
                    is_match = False
                    if sender_digits and name_digits:
                        if sender_digits == name_digits:
                            is_match = True
                        elif len(sender_digits) >= 10 and len(name_digits) >= 10:
                            # 한국 폰 번호 뒷자리 매칭 (끝 8자리 이상 일치)
                            if sender_digits[-8:] == name_digits[-8:]:
                                is_match = True
                    
                    if is_match:
                        await item.click()
                        await page.wait_for_timeout(800)
                        found = True
                        break
                except:
                    continue
            
            # 2. 목록에서 못 찾았을 경우 검색(Fallback) 시도
            if not found and sender_digits:
                try:
                    # '채팅 시작' 버튼 클릭
                    start_chat = page.locator('div.floating-button-container button, a[href*="compose"]')
                    if await start_chat.count():
                        await start_chat.first.click()
                        await page.wait_for_timeout(1000)
                        
                        # 번호 입력
                        input_box = page.locator('mws-contact-search-input input')
                        if await input_box.count():
                            await input_box.first.fill(sender_digits)
                            await page.keyboard.press("Enter")
                            await page.wait_for_timeout(1500)
                            
                            # 대화방 진입 확인 (메시지 입력창 존재 여부)
                            if await page.locator('mws-message-compose textarea').count():
                                found = True
                except Exception as e:
                    print(f"[대화상세] 검색 폴백 시도 중 오류: {e}")
            
            if not found:
                return {"error": f"대화를 찾을 수 없음: {sender}"}
            
            # offset > 0이면 스크롤해서 이전 메시지 로드
            if offset > 0:
                scroll_count = (offset // 20) + 1
                for _ in range(scroll_count):
                    # 대화 영역 맨 위로 스크롤
                    conv_container = page.locator('mws-messages-list, .message-list, [role="list"]')
                    if await conv_container.count():
                        await conv_container.first.evaluate('el => el.scrollTop = 0')
                        await page.wait_for_timeout(500)
            
            # 메시지 읽기 (일반 메시지 + 타임스탬프 tombstone 포함)
            messages = []
            
            # 모든 메시지 관련 요소 가져오기 (메시지 + 타임스탬프)
            # 수동 전송 중이거나 로딩 중인 메시지도 포함하도록 선택자 확장
            all_elements = await page.locator('mws-message-wrapper, mws-tombstone-message-wrapper, mws-message-part, .message-row, .msg-part').all()
            
            total_count = len(all_elements)
            # print(f"[{profile_id}] 메시지 요소 발견: {total_count}개")
            
            # offset과 limit 적용
            if offset == 0:
                # 최근 메시지 (끝에서 limit개)
                start_idx = max(0, total_count - limit)
                end_idx = total_count
            else:
                # 이전 메시지 (offset만큼 앞에서)
                end_idx = max(0, total_count - offset)
                start_idx = max(0, end_idx - limit)
            
            target_elements = all_elements[start_idx:end_idx]
            
            for idx, el in enumerate(target_elements):
                try:
                    # 원래 인덱스 계산
                    original_idx = start_idx + idx
                    
                    # 태그 이름 확인
                    try:
                        tag_name = await el.evaluate('el => el.tagName.toLowerCase()')
                    except:
                        # 요소가 사라졌거나 접근 불가 시 스킵
                        continue
                    
                    if tag_name == 'mws-tombstone-message-wrapper':
                        # 타임스탬프 구분선
                        ts_loc = el.locator('mws-relative-timestamp.tombstone-timestamp')
                        if await ts_loc.count():
                            ts_text = await ts_loc.first.inner_text()
                            if ts_text and ts_text.strip():
                                messages.append({
                                    "type": "timestamp_divider",
                                    "timestamp": ts_text.strip(),
                                    "direction": "system"
                                })
                    else:
                        # 일반 메시지
                        msg_data = await self._parse_message_element(el, page, download_dir, original_idx)
                        if msg_data:
                            msg_data["type"] = "message"
                            messages.append(msg_data)
                            
                            # 인증코드 추출 확인 (디버그)
                            if msg_data.get("text"):
                                auth_code = self._extract_auth_code(msg_data["text"])
                                if auth_code:
                                    print(f"  -> 인증코드 감지: {auth_code}")
                                    msg_data["auth_code"] = auth_code
                                    
                except Exception as e:
                    print(f"요소 파싱 오류(idx={original_idx}): {e}")
                    continue
            
            return {
                "success": True,
                "profile_id": profile_id,
                "sender": sender,
                "messages": messages,
                "total_count": total_count,
                "offset": offset,
                "has_more": start_idx > 0  # 더 이전 메시지가 있는지
            }
            
        except Exception as e:
            print(f"[{profile_id}] 대화 상세 오류: {e}")
            return {"error": str(e)}
    
    async def _parse_message_element(self, msg_el, page: Page, download_dir: Path, idx: int) -> Optional[Dict]:
        """개별 메시지 요소 파싱"""
        try:
            # 발신/수신 구분 - 여러 패턴 체크
            class_attr = await msg_el.get_attribute("class") or ""
            
            # outgoing/from-me 등이 있으면 발신, 없으면 수신
            is_outgoing = any(kw in class_attr.lower() for kw in ["outgoing", "from-me", "sent", "self"])
            is_incoming = any(kw in class_attr.lower() for kw in ["incoming", "received"])
            
            if is_outgoing:
                direction = "outgoing"
            elif is_incoming:
                direction = "incoming"
            else:
                # 클래스로 판단 안 되면 기본 수신
                direction = "incoming"
            
            # 디버그: 첫 5개 메시지만 클래스 출력 (비활성화)
            # if idx < 5:
            #     print(f"[메시지 {idx}] class='{class_attr[:100]}' → {direction}")
            
            # 텍스트 내용
            text_content = ""
            text_el = msg_el.locator('.text-msg, .message-text, [data-e2e-message-text]')
            if await text_el.count():
                text_content = await text_el.first.inner_text()
                # Debug: 텍스트 내용 확인 (비활성화)
                # if len(text_content) > 0:
                #      safe_text = text_content[:50].replace('\n', ' ')
                #      print(f"  [메시지 {idx}] 텍스트 추출: {safe_text}...")
            
            # URL 추출 (텍스트에서)
            urls = re.findall(r'https?://[^\s]+', text_content)
            
            # 이미지 확인 (스크린샷 없이 존재 여부만)
            images = []
            img_elements = await msg_el.locator('img.image-msg, img[data-e2e-message-image], .mms-image img, img[src*="blob:"], img[src*="data:"]').all()
            for img_idx, img_el in enumerate(img_elements):
                try:
                    # 이미지 존재만 확인, 스크린샷은 나중에
                    images.append({
                        "type": "image",
                        "thumbnail": None,  # 나중에 로드
                        "element_idx": f"{idx}_{img_idx}"
                    })
                except Exception as e:
                    print(f"이미지 확인 오류: {e}")
            
            # 동영상 확인
            videos = []
            video_elements = await msg_el.locator('video, .video-msg, [data-e2e-message-video]').all()
            for vid_idx, vid_el in enumerate(video_elements):
                videos.append({
                    "type": "video",
                    "element_idx": f"{idx}_{vid_idx}"
                })
            
            # 파일 확인
            files = []
            file_elements = await msg_el.locator('.file-msg, .attachment, [data-e2e-message-attachment]').all()
            for file_idx, file_el in enumerate(file_elements):
                try:
                    filename = await file_el.inner_text() if await file_el.count() else f"파일_{file_idx}"
                    files.append({
                        "type": "file",
                        "filename": filename.strip()[:50],
                        "element_idx": f"{idx}_{file_idx}"
                    })
                except:
                    pass
            
            # 타임스탬프 (메시지 내: mws-absolute-timestamp, 날짜: mws-relative-timestamp.tombstone-timestamp)
            timestamp = ""
            # 먼저 메시지 내 시간 (mws-absolute-timestamp)
            ts_loc = msg_el.locator('mws-absolute-timestamp')
            if await ts_loc.count():
                ts_text = await ts_loc.first.inner_text()
                if ts_text and ts_text.strip():
                    timestamp = ts_text.strip()
            # 없으면 날짜+시간 (tombstone-timestamp)
            if not timestamp:
                ts_loc = msg_el.locator('mws-relative-timestamp.tombstone-timestamp')
                if await ts_loc.count():
                    ts_text = await ts_loc.first.inner_text()
                    if ts_text and ts_text.strip():
                        timestamp = ts_text.strip()
            
            return {
                "direction": direction,
                "text": text_content.strip(),
                "urls": urls,
                "images": images,
                "videos": videos,
                "files": files,
                "timestamp": timestamp
            }
            
        except Exception as e:
            print(f"메시지 파싱 오류: {e}")
            return None
    
    async def download_media(self, profile_id: str, sender: str, media_type: str, element_idx: str, get_thumbnail: bool = False) -> Optional[str]:
        """이미지/동영상/파일 다운로드
        get_thumbnail=True: 썸네일(작은 이미지) 가져오기
        get_thumbnail=False: 원본 이미지 가져오기
        """
        # 캐시 확인 (썸네일만)
        if get_thumbnail and sender:
            cache_key = f"thumb_{element_idx}"
            cached = self._get_from_image_cache(sender, cache_key)
            if cached:
                # 파일이 존재하는지 확인
                full_path = APP_DIR / cached.lstrip('/')
                if full_path.exists():
                    print(f"[{profile_id}] 캐시에서 썸네일 반환: {cached}")
                    return cached
        
        if profile_id not in self.pages or not self.ready.get(profile_id):
            return None
        
        page = self.pages[profile_id]
        context = self.browsers[profile_id]
        
        download_dir = APP_DIR / "downloads" / profile_id
        download_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            idx, sub_idx = element_idx.split("_")
            idx, sub_idx = int(idx), int(sub_idx)
            
            # 메시지 요소 찾기 (get_conversation_detail과 동일한 셀렉터)
            msg_elements = await page.locator('mws-message-wrapper, mws-tombstone-message-wrapper').all()
            if not msg_elements:
                print(f"[{profile_id}] 메시지 요소 없음 - 대화창이 열려있지 않음")
                return None
            
            # idx가 전체 메시지 중 어디인지 확인
            if idx >= len(msg_elements):
                print(f"[{profile_id}] idx={idx} 가 범위 초과 (total={len(msg_elements)})")
                return None
            
            msg_el = msg_elements[idx]
            
            if media_type == "image":
                img_elements = await msg_el.locator('img.image-msg, img[data-e2e-message-image], .mms-image img, img[src*="blob:"], img[src*="data:"]').all()
                if sub_idx < len(img_elements):
                    img_el = img_elements[sub_idx]
                    
                    if get_thumbnail:
                        # 썸네일: 이미지 src 직접 다운로드 시도
                        try:
                            src = await img_el.get_attribute('src')
                            print(f"[{profile_id}] 썸네일 src: {src[:80] if src else 'None'}...")
                            
                            if src and src.startswith('http'):
                                # HTTP URL이면 직접 다운로드
                                import aiohttp
                                async with aiohttp.ClientSession() as session:
                                    async with session.get(src, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                                        if resp.status == 200:
                                            ext = 'jpg' if 'jpeg' in resp.content_type or 'jpg' in resp.content_type else 'png'
                                            filename = f"thumb_{element_idx}_{int(datetime.now().timestamp())}.{ext}"
                                            filepath = download_dir / filename
                                            with open(filepath, 'wb') as f:
                                                f.write(await resp.read())
                                            print(f"[{profile_id}] 썸네일 HTTP 다운로드 성공")
                                            result_path = f"/downloads/{profile_id}/{filename}"
                                            if sender:
                                                self._add_to_image_cache(sender, f"thumb_{element_idx}", result_path)
                                            return result_path
                            
                            elif src and src.startswith('blob:'):
                                # blob URL은 JavaScript로 fetch
                                print(f"[{profile_id}] blob URL 다운로드 시도")
                                blob_data = await page.evaluate('''async (src) => {
                                    try {
                                        const response = await fetch(src);
                                        const blob = await response.blob();
                                        const reader = new FileReader();
                                        return new Promise((resolve) => {
                                            reader.onloadend = () => resolve(reader.result);
                                            reader.readAsDataURL(blob);
                                        });
                                    } catch (e) {
                                        return null;
                                    }
                                }''', src)
                                
                                if blob_data and blob_data.startswith('data:'):
                                    import base64
                                    header, b64_data = blob_data.split(',', 1)
                                    ext = 'jpg' if 'jpeg' in header else 'png'
                                    filename = f"thumb_{element_idx}_{int(datetime.now().timestamp())}.{ext}"
                                    filepath = download_dir / filename
                                    with open(filepath, 'wb') as f:
                                        f.write(base64.b64decode(b64_data))
                                    print(f"[{profile_id}] 썸네일 blob 다운로드 성공")
                                    result_path = f"/downloads/{profile_id}/{filename}"
                                    if sender:
                                        self._add_to_image_cache(sender, f"thumb_{element_idx}", result_path)
                                    return result_path
                            
                            elif src and src.startswith('data:'):
                                # data URL 직접 디코딩
                                import base64
                                header, b64_data = src.split(',', 1)
                                ext = 'jpg' if 'jpeg' in header else 'png'
                                filename = f"thumb_{element_idx}_{int(datetime.now().timestamp())}.{ext}"
                                filepath = download_dir / filename
                                with open(filepath, 'wb') as f:
                                    f.write(base64.b64decode(b64_data))
                                print(f"[{profile_id}] 썸네일 data URL 디코딩 성공")
                                result_path = f"/downloads/{profile_id}/{filename}"
                                if sender:
                                    self._add_to_image_cache(sender, f"thumb_{element_idx}", result_path)
                                return result_path
                                
                        except Exception as e:
                            print(f"[{profile_id}] 썸네일 다운로드 실패: {e}")

                        # Fallback: 스크린샷
                        try:
                            # 요소가 visible하고 DOM에 있는지 확인
                            is_visible = await img_el.is_visible()
                            if not is_visible:
                                print(f"[{profile_id}] 썸네일 요소가 보이지 않음, 스크롤 시도")
                                await img_el.scroll_into_view_if_needed(timeout=3000)
                                await page.wait_for_timeout(500)

                            # bounding box 확인 (DOM에 있는지)
                            box = await img_el.bounding_box()
                            if not box:
                                print(f"[{profile_id}] 썸네일 요소 bounding box 없음")
                                return None

                            filename = f"thumb_{element_idx}_{int(datetime.now().timestamp())}.png"
                            filepath = download_dir / filename
                            await img_el.screenshot(path=str(filepath), timeout=5000)
                            result_path = f"/downloads/{profile_id}/{filename}"
                            if sender:
                                self._add_to_image_cache(sender, f"thumb_{element_idx}", result_path)
                            return result_path
                        except Exception as e:
                            print(f"[{profile_id}] 썸네일 스크린샷 실패: {str(e)[:100]}")
                            return None
                    else:
                        # 원본: 이미지 클릭해서 팝업 열고 원본 src 가져오기
                        await img_el.click()
                        await page.wait_for_timeout(1500)
                        
                        # 원본 이미지 찾기
                        full_img_selectors = [
                            '.cdk-overlay-container img[alt="전체 크기 이미지"]',
                            '.cdk-overlay-container img[alt="Full size image"]',
                            '.cdk-overlay-container img.ng-star-inserted',
                            '.cdk-overlay-container img',
                            'mat-dialog-container img',
                            '.mdc-dialog__surface img',
                            'div[role="dialog"] img',
                        ]
                        
                        full_img = None
                        for selector in full_img_selectors:
                            locator = page.locator(selector)
                            if await locator.count() > 0:
                                all_imgs = await locator.all()
                                for img in all_imgs:
                                    try:
                                        box = await img.bounding_box()
                                        if box and box['width'] > 100 and box['height'] > 100:
                                            full_img = img
                                            print(f"[{profile_id}] 원본 이미지 찾음: {selector}")
                                            break
                                    except:
                                        continue
                                if full_img:
                                    break
                        
                        if full_img:
                            # src 직접 다운로드 시도
                            try:
                                src = await full_img.get_attribute('src')
                                print(f"[{profile_id}] 원본 이미지 src: {src[:100] if src else 'None'}...")
                                
                                if src and src.startswith('http'):
                                    import aiohttp
                                    async with aiohttp.ClientSession() as session:
                                        async with session.get(src) as resp:
                                            if resp.status == 200:
                                                content_type = resp.content_type or ''
                                                ext = 'jpg' if 'jpeg' in content_type or 'jpg' in content_type else 'png'
                                                filename = f"full_{element_idx}_{int(datetime.now().timestamp())}.{ext}"
                                                filepath = download_dir / filename
                                                with open(filepath, 'wb') as f:
                                                    f.write(await resp.read())
                                                await page.keyboard.press("Escape")
                                                await page.wait_for_timeout(300)
                                                print(f"[{profile_id}] 원본 다운로드 성공: {filename}")
                                                return f"/downloads/{profile_id}/{filename}"
                                
                                elif src and src.startswith('blob:'):
                                    # blob URL은 JavaScript로 fetch해서 다운로드
                                    print(f"[{profile_id}] blob URL 감지, JS로 다운로드 시도")
                                    blob_data = await page.evaluate('''async (src) => {
                                        try {
                                            const response = await fetch(src);
                                            const blob = await response.blob();
                                            const reader = new FileReader();
                                            return new Promise((resolve) => {
                                                reader.onloadend = () => resolve(reader.result);
                                                reader.readAsDataURL(blob);
                                            });
                                        } catch (e) {
                                            return null;
                                        }
                                    }''', src)
                                    
                                    if blob_data and blob_data.startswith('data:'):
                                        import base64
                                        # data:image/jpeg;base64,.... 형식
                                        header, b64_data = blob_data.split(',', 1)
                                        ext = 'jpg' if 'jpeg' in header else 'png'
                                        filename = f"full_{element_idx}_{int(datetime.now().timestamp())}.{ext}"
                                        filepath = download_dir / filename
                                        with open(filepath, 'wb') as f:
                                            f.write(base64.b64decode(b64_data))
                                        await page.keyboard.press("Escape")
                                        await page.wait_for_timeout(300)
                                        print(f"[{profile_id}] blob 다운로드 성공: {filename}")
                                        return f"/downloads/{profile_id}/{filename}"
                                
                            except Exception as e:
                                print(f"[{profile_id}] src 다운로드 실패: {e}")
                            
                            # Fallback: 스크린샷 (타임아웃 5초)
                            try:
                                filename = f"full_{element_idx}_{int(datetime.now().timestamp())}.png"
                                filepath = download_dir / filename
                                await full_img.screenshot(path=str(filepath), timeout=5000)
                                await page.keyboard.press("Escape")
                                await page.wait_for_timeout(300)
                                return f"/downloads/{profile_id}/{filename}"
                            except Exception as e:
                                print(f"[{profile_id}] 원본 스크린샷 실패: {e}")
                                await page.keyboard.press("Escape")
                                return None
                        else:
                            # 원본 못 찾음
                            print(f"[{profile_id}] 원본 이미지 못 찾음")
                            await page.keyboard.press("Escape")
                            await page.wait_for_timeout(300)
                            return None
            
            elif media_type == "video":
                # 동영상 다운로드 버튼 클릭
                video_elements = await msg_el.locator('video, .video-msg').all()
                if sub_idx < len(video_elements):
                    vid_el = video_elements[sub_idx]
                    
                    # 다운로드 버튼 찾기
                    download_btn = msg_el.locator('[aria-label="다운로드"], [aria-label="Download"], .download-btn')
                    if await download_btn.count():
                        async with page.expect_download() as download_info:
                            await download_btn.first.click()
                        download = await download_info.value
                        filename = download.suggested_filename or f"video_{element_idx}.mp4"
                        filepath = download_dir / filename
                        await download.save_as(str(filepath))
                        return f"/downloads/{profile_id}/{filename}"
            
            elif media_type == "file":
                # 파일 다운로드
                file_elements = await msg_el.locator('.file-msg, .attachment').all()
                if sub_idx < len(file_elements):
                    file_el = file_elements[sub_idx]
                    
                    async with page.expect_download() as download_info:
                        await file_el.click()
                    download = await download_info.value
                    filename = download.suggested_filename or f"file_{element_idx}"
                    filepath = download_dir / filename
                    await download.save_as(str(filepath))
                    return f"/downloads/{profile_id}/{filename}"
            
            return None
            
        except Exception as e:
            print(f"[{profile_id}] 미디어 다운로드 오류: {e}")
            return None
    
    async def search_by_phone(self, profile_id: str, phone_number: str) -> Dict[str, Any]:
        """전화번호로 대화 검색 (새 대화 시작 버튼 → 번호 입력)"""
        if profile_id not in self.pages or not self.ready.get(profile_id):
            return {"error": "브라우저 미실행"}
        
        page = self.pages[profile_id]
        
        # 전화번호 정규화 (숫자만)
        clean_number = re.sub(r'[^0-9]', '', phone_number)
        if len(clean_number) < 10:
            return {"error": "올바른 전화번호를 입력하세요"}
        
        try:
            # 뒤로가기 (대화 목록으로)
            try:
                back = page.locator('button[aria-label="뒤로 가기"], button[aria-label="Back"]')
                if await back.count() and await back.first.is_visible():
                    await back.first.click()
                    await page.wait_for_timeout(300)
            except:
                pass
            
            # "채팅 시작" 버튼 클릭
            start_chat = page.locator('button[aria-label="채팅 시작"], button[aria-label="Start chat"], a[href*="new"], [data-e2e-start-chat]')
            if not await start_chat.count():
                return {"error": "채팅 시작 버튼을 찾을 수 없습니다"}
            
            await start_chat.first.click()
            await page.wait_for_timeout(500)
            
            # 전화번호 입력 필드 찾기
            phone_input = page.locator('input[type="text"], input[aria-label*="번호"], input[aria-label*="number"], input[placeholder*="번호"], input[placeholder*="number"]')
            if not await phone_input.count():
                # ESC로 닫고 에러 반환
                await page.keyboard.press("Escape")
                return {"error": "전화번호 입력 필드를 찾을 수 없습니다"}
            
            # 입력 필드 클릭하여 포커스
            await phone_input.first.click()
            await page.wait_for_timeout(200)
            
            # 번호 입력 (타이핑 방식)
            await phone_input.first.fill("")
            await phone_input.first.type(clean_number, delay=50)
            await page.wait_for_timeout(500)
            
            # 엔터 키 입력 (검색 실행)
            await phone_input.first.press("Enter")
            await page.wait_for_timeout(1500)
            
            # 검색 결과 확인
            found = False
            message_count = 0
            formatted_number = clean_number
            
            # 메시지 셀렉터
            message_selectors = [
                'mws-message-wrapper',
                '.message-wrapper',
                '[data-e2e-message]',
                '.message-row',
                'mws-message-part',
                '.text-msg',
                'mws-bottom-nav ~ div [role="listitem"]'
            ]
            
            # 방법 1: 대화 내용이 바로 표시되는 경우
            for selector in message_selectors:
                msg_elements = await page.locator(selector).all()
                if len(msg_elements) > 0:
                    found = True
                    message_count = len(msg_elements)
                    print(f"[검색] 대화 내용 직접 표시됨 ({selector}): {message_count}개 메시지")
                    break
            
            # 방법 2: 연락처 목록이 나타난 경우 - 클릭
            if not found:
                contact_item = page.locator('mws-contact-row, .contact-row, [data-e2e-contact], .contact-item')
                if await contact_item.count() > 0:
                    await contact_item.first.click()
                    await page.wait_for_timeout(1000)
                    
                    for selector in message_selectors:
                        msg_elements = await page.locator(selector).all()
                        if len(msg_elements) > 0:
                            found = True
                            message_count = len(msg_elements)
                            print(f"[검색] 연락처 클릭 후 표시됨 ({selector}): {message_count}개 메시지")
                            break
            
            # 방법 3: URL이 대화 페이지로 변경되었는지 확인
            if not found:
                current_url = page.url
                if '/conversations/' in current_url:
                    # URL 변경됨 = 대화방 존재, 메시지 로딩 대기 (최대 3초 추가)
                    for retry in range(3):
                        await page.wait_for_timeout(1000)
                        for selector in message_selectors:
                            msg_elements = await page.locator(selector).all()
                            if len(msg_elements) > 0:
                                found = True
                                message_count = len(msg_elements)
                                print(f"[검색] URL 변경 후 메시지 로딩됨: {message_count}개 (대기 {retry+1}초)")
                                break
                        if found:
                            break
            
            if found and message_count > 0:
                # 검색한 번호를 그대로 반환 (화면 제목이 아닌)
                # 포맷팅만 추가
                display_number = clean_number
                if len(clean_number) == 11:
                    display_number = f"{clean_number[:3]}-{clean_number[3:7]}-{clean_number[7:]}"
                elif len(clean_number) == 10:
                    display_number = f"{clean_number[:3]}-{clean_number[3:6]}-{clean_number[6:]}"
                
                return {
                    "success": True,
                    "found": True,
                    "phone_number": display_number,
                    "message_count": message_count,
                    "profile_id": profile_id
                }
            else:
                # 대화방은 있지만 메시지가 없거나, 대화방 자체가 없음
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(300)
                
                return {
                    "success": True,
                    "found": False,
                    "phone_number": clean_number,
                    "message": "해당 번호와의 대화 이력이 없습니다"
                }
            
        except Exception as e:
            print(f"[{profile_id}] 전화번호 검색 오류: {e}")
            try:
                await page.keyboard.press("Escape")
            except:
                pass
            return {"error": str(e)}

# ========== WebSocket 관리 ==========
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

# ========== 불사자 매니저 ==========
import subprocess
import threading

class BulsajaManager:
    def __init__(self):
        self.is_running = False
        self.groups: List[Dict] = []  # [{num, status, message}]
        self.process: Optional[subprocess.Popen] = None
        self.stop_flag = False
        self.run_thread = None
        self.base_folder = "C:\\자동화시스템"
        self.logs = []
    
    def set_folder(self, folder: str):
        """폴더 경로 설정"""
        self.base_folder = folder
        return {"success": True, "folder": folder}
    
    def get_folder(self) -> str:
        """현재 폴더 경로"""
        return self.base_folder
    
    def get_active_folder(self) -> str:
        """현재 활성화된 폴더"""
        return self.base_folder
    
    def find_exe(self) -> Optional[Path]:
        """C:\\자동화시스템\\*.exe 패턴으로 exe 찾기"""
        import glob
        exe_pattern = str(Path(self.base_folder) / "*.exe")
        exe_files = glob.glob(exe_pattern)
        if exe_files:
            # 가장 최근 수정된 exe 반환
            return Path(max(exe_files, key=os.path.getmtime))
        return None
    
    def parse_groups(self, text: str) -> List[int]:
        """그룹 문자열 파싱"""
        groups, seen = [], set()
        for part in text.replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                a, b = map(int, part.split("-", 1))
                step = 1 if a <= b else -1
                for n in range(a, b + step, step):
                    if 1 <= n <= 99 and n not in seen:
                        groups.append(n)
                        seen.add(n)
            else:
                n = int(part)
                if 1 <= n <= 99 and n not in seen:
                    groups.append(n)
                    seen.add(n)
        return groups
    
    def group_to_market_name(self, num: int) -> str:
        """그룹 번호를 마켓그룹명으로 변환 (1 → '1번 마켓그룹')"""
        return f"{num}번 마켓그룹"
    
    def start(self, groups_text: str, max_concurrent: int, group_gap: int, settings: dict = None):
        """그룹별 시트 변경 + exe 실행"""
        if self.is_running:
            return {"success": False, "message": "이미 실행 중입니다"}
        
        groups = self.parse_groups(groups_text)
        if not groups:
            return {"success": False, "message": "유효한 그룹이 없습니다"}
        
        # exe 찾기
        exe_path = self.find_exe()
        if not exe_path:
            return {"success": False, "message": f"exe 파일을 찾을 수 없습니다: {self.base_folder}\\*.exe"}
        
        # 초기화
        self.groups = [{"num": g, "status": "pending", "message": ""} for g in groups]
        self.stop_flag = False
        self.is_running = True
        self.logs = []
        
        # 백그라운드 스레드에서 실행
        self.run_thread = threading.Thread(
            target=self._run_groups,
            args=(exe_path, groups, max_concurrent, group_gap, settings or {}),
            daemon=True
        )
        self.run_thread.start()
        
        return {"success": True, "groups": groups}
    
    def _run_groups(self, exe_path: Path, groups: List[int], max_concurrent: int, group_gap: int, settings: dict):
        """그룹별 시트 변경 + exe 실행 (스레드)"""
        import asyncio
        from dotenv import dotenv_values
        
        try:
            # 자동화시스템 폴더의 .env 읽기
            env_path = Path(self.base_folder) / ".env"
            if env_path.exists():
                env_config = dotenv_values(env_path)
                creds_file = env_config.get("SERVICE_ACCOUNT_JSON", CREDENTIALS_FILE)
                sheet_key = env_config.get("SPREADSHEET_KEY", BULSAJA_SHEET_KEY)
                self._add_log(f".env 로드: {env_path}")
            else:
                creds_file = CREDENTIALS_FILE
                sheet_key = BULSAJA_SHEET_KEY
                self._add_log(f".env 없음, 기본값 사용")
            
            # 상대경로면 base_folder 기준으로 변환
            creds_path = Path(creds_file)
            if not creds_path.is_absolute():
                creds_path = Path(self.base_folder) / creds_file
            
            # 구글시트 연결
            creds = Credentials.from_service_account_file(
                str(creds_path),
                scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
            gc = gspread.authorize(creds)
            ws = gc.open_by_key(sheet_key).worksheet(BULSAJA_TAB_NAME)
            
            # ========== 설정값 먼저 저장 ==========
            program = settings.get("program", "")
            if program:
                ws.update_acell("C10", program)
                self._add_log(f"📝 C10 → {program}")
                
                if "상품업로드" in program:
                    target_cell = "C15"
                    if settings.get("uploadMarket"):
                        ws.update_acell("C17", settings["uploadMarket"])
                        self._add_log(f"📝 C17 → {settings['uploadMarket']}")
                    if settings.get("uploadCount"):
                        ws.update_acell("C18", settings["uploadCount"])
                        self._add_log(f"📝 C18 → {settings['uploadCount']}")
                        
                elif "상품삭제" in program:
                    target_cell = "C29"
                    if settings.get("deleteCount"):
                        ws.update_acell("C32", settings["deleteCount"])
                        self._add_log(f"📝 C32 → {settings['deleteCount']}")
                        
                elif "상품복사" in program:
                    target_cell = "C35"
                    if settings.get("copySourceMarket"):
                        ws.update_acell("C29", settings["copySourceMarket"])
                        self._add_log(f"📝 C29 → {settings['copySourceMarket']}")
                    if settings.get("copyCount"):
                        ws.update_acell("C37", settings["copyCount"])
                        self._add_log(f"📝 C37 → {settings['copyCount']}")
                else:
                    target_cell = "C15"
            else:
                # 설정이 없으면 현재 시트 값 사용
                program = ws.acell("C10").value or ""
                if "상품업로드" in program:
                    target_cell = "C15"
                elif "상품삭제" in program:
                    target_cell = "C29"
                elif "상품복사" in program:
                    target_cell = "C35"
                else:
                    target_cell = "C15"
            
            self._add_log(f"프로그램: {program}")
            self._add_log(f"실행파일: {exe_path.name}")
            self._add_log(f"대상 셀: {target_cell}, 그룹: {groups}")
            
            # 동시 실행 관리
            running_processes = []
            group_idx = 0
            
            while group_idx < len(groups) or running_processes:
                if self.stop_flag:
                    self._add_log("⏹️ 중지 요청됨")
                    break
                
                # 완료된 프로세스 정리
                for proc_info in running_processes[:]:
                    proc, gnum = proc_info
                    if proc.poll() is not None:  # 프로세스 종료됨
                        exit_code = proc.returncode
                        if exit_code == 0:
                            self._update_group_status(gnum, "completed", "완료")
                            self._add_log(f"✅ 그룹 {gnum} 완료")
                        else:
                            self._update_group_status(gnum, "failed", f"exit: {exit_code}")
                            self._add_log(f"❌ 그룹 {gnum} 실패 (exit={exit_code})")
                        running_processes.remove(proc_info)
                
                # 새 프로세스 시작 (동시 실행 수 이내)
                while len(running_processes) < max_concurrent and group_idx < len(groups):
                    if self.stop_flag:
                        break
                    
                    gnum = groups[group_idx]
                    group_idx += 1
                    
                    # 시트 셀 변경
                    market_name = self.group_to_market_name(gnum)
                    try:
                        ws.update_acell(target_cell, market_name)
                        self._add_log(f"📝 {target_cell} → {market_name}")
                    except Exception as e:
                        self._update_group_status(gnum, "failed", f"시트 오류: {e}")
                        self._add_log(f"❌ 그룹 {gnum} 시트 변경 실패: {e}")
                        continue
                    
                    # exe 실행 (별도 창에서)
                    try:
                        self._update_group_status(gnum, "running", "실행 중")
                        self._add_log(f"🔧 exe 경로: {exe_path}")
                        
                        # Windows에서 별도 창으로 exe 실행
                        if os.name == "nt":
                            proc = subprocess.Popen(
                                [str(exe_path)],
                                cwd=str(exe_path.parent),
                                creationflags=subprocess.CREATE_NEW_CONSOLE
                            )
                        else:
                            proc = subprocess.Popen(
                                [str(exe_path)],
                                cwd=str(exe_path.parent)
                            )
                        running_processes.append((proc, gnum))
                        self._add_log(f"🚀 그룹 {gnum} exe 실행 (PID: {proc.pid})")
                        
                        # 다음 그룹 전 간격 대기
                        if group_idx < len(groups):
                            self._add_log(f"⏳ {group_gap}초 대기...")
                            for _ in range(group_gap):
                                if self.stop_flag:
                                    break
                                time.sleep(1)
                    except Exception as e:
                        self._update_group_status(gnum, "failed", f"실행 오류: {e}")
                        self._add_log(f"❌ 그룹 {gnum} exe 실행 실패: {e}")
                
                time.sleep(1)  # 폴링 간격
            
            # 남은 프로세스 대기
            for proc, gnum in running_processes:
                try:
                    proc.wait(timeout=300)  # 5분 타임아웃
                    if proc.returncode == 0:
                        self._update_group_status(gnum, "completed", "완료")
                    else:
                        self._update_group_status(gnum, "failed", f"exit: {proc.returncode}")
                except:
                    self._update_group_status(gnum, "failed", "타임아웃")
            
            self._add_log("✅ 모든 작업 완료!")
            
        except Exception as e:
            self._add_log(f"❌ 오류: {e}")
            for g in self.groups:
                if g["status"] in ["pending", "running"]:
                    g["status"] = "failed"
                    g["message"] = str(e)
        finally:
            self.is_running = False
    
    def _add_log(self, msg: str):
        """로그 추가 + WebSocket 브로드캐스트"""
        import asyncio
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[불사자 {timestamp}] {msg}")
        self.logs.append({"time": timestamp, "msg": msg})
        
        # 최근 100줄만 유지
        if len(self.logs) > 100:
            self.logs = self.logs[-100:]
        
        # WebSocket으로 전송
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(ws_manager.broadcast({
                "type": "bulsaja_log",
                "message": msg,
                "timestamp": timestamp
            }))
            loop.close()
        except:
            pass
    
    def _update_group_status(self, group_num: int, status: str, message: str):
        """그룹 상태 업데이트"""
        for g in self.groups:
            if g["num"] == group_num:
                g["status"] = status
                g["message"] = message
                break
    
    def stop(self):
        """실행 중지 - njbul exe들도 종료"""
        self.stop_flag = True
        
        # njbul exe들 강제 종료 (Windows)
        if os.name == "nt":
            try:
                result = subprocess.run(
                    'wmic process where "name like \'njbul%\'" call terminate',
                    shell=True,
                    capture_output=True,
                    text=True
                )
                if "성공" in result.stdout or "successfully" in result.stdout.lower():
                    print(f"[불사자] njbul exe 종료됨")
                elif "인스턴스가 없습니다" in result.stdout or "No Instance" in result.stdout:
                    print(f"[불사자] 실행 중인 njbul exe 없음")
            except Exception as e:
                print(f"[불사자] wmic 오류: {e}")
        
        self.is_running = False
        for g in self.groups:
            if g["status"] == "running" or g["status"] == "pending":
                g["status"] = "failed"
                g["message"] = "중지됨"
        return {"success": True, "message": "njbul exe 종료됨"}
    
    def get_status(self):
        """현재 상태 반환"""
        counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        for g in self.groups:
            counts[g["status"]] = counts.get(g["status"], 0) + 1
        return {
            "is_running": self.is_running,
            "groups": self.groups,
            "counts": counts
        }

# ========== 전역 인스턴스 ==========
gsheet = GoogleSheetManager()
sms_manager = SMSBrowserManager()
ws_manager = ConnectionManager()
bulsaja_manager = BulsajaManager()

# ========== FastAPI 앱 ==========
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작시
    gsheet.connect()
    
    # 스케줄러 시작
    scheduler.start()
    print("[서버시작] 스케줄러 시작됨")
    
    # 저장된 스케줄 복원
    schedules = load_schedules()
    for s in schedules:
        if s.get('enabled', True):
            try:
                add_schedule_job(s)
                print(f"[스케줄러] 복원: {s.get('name')} ({s.get('id')})")
            except Exception as e:
                print(f"[스케줄러] 복원 실패: {s.get('name')} - {e}")
    
    # SMS 브라우저 자동 실행 (기존 오전 10시 원본 복구)
    async def delayed_sms_launch():
        await asyncio.sleep(5)  # 서버 완전히 뜬 후 5초 대기
        print("[서버시작] SMS 브라우저 전체 실행 중...")
        try:
            await sms_manager.launch_all()
            print("[서버시작] SMS 브라우저 전체 실행 완료")
        except Exception as e:
            print(f"[서버시작] SMS 브라우저 실행 오류: {e}")
    
    asyncio.create_task(delayed_sms_launch())
    
    yield
    # 종료시
    scheduler.shutdown(wait=False)
    print("[서버종료] 스케줄러 종료됨")
    
    # SMS 브라우저 종료
    await sms_manager.close_all()
    
    # 라이브 알리 브라우저 종료 (있는 경우)
    try:
        global ali_browser
        if ali_browser:
            # 동기/비동기 브라우저 타입에 따라 대응
            if hasattr(ali_browser, 'close'):
                if asyncio.iscoroutinefunction(ali_browser.close):
                    await ali_browser.close()
                else:
                    ali_browser.close()
            print("[서버종료] 알리 브라우저 종료 완료")
    except Exception as e:
        print(f"[서버종료] 알리 브라우저 종료 중 오류: {e}")

def add_schedule_job(schedule: Dict):
    """스케줄 작업 등록"""
    job_id = schedule['id']
    schedule_type = schedule.get('schedule_type', 'cron')
    
    # 기존 작업 제거
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    if schedule_type == 'cron':
        # cron 표현식: 분 시 일 월 요일
        cron_expr = schedule.get('cron', '0 9 * * *')  # 기본 매일 09:00
        parts = cron_expr.split()
        trigger = CronTrigger(
            minute=parts[0] if len(parts) > 0 else '0',
            hour=parts[1] if len(parts) > 1 else '9',
            day=parts[2] if len(parts) > 2 else '*',
            month=parts[3] if len(parts) > 3 else '*',
            day_of_week=parts[4] if len(parts) > 4 else '*'
        )
    elif schedule_type == 'interval':
        # 간격 (분 단위)
        interval_minutes = schedule.get('interval_minutes', 60)
        trigger = IntervalTrigger(minutes=interval_minutes)
    else:
        return
    
    scheduler.add_job(
        execute_scheduled_task,
        trigger=trigger,
        id=job_id,
        args=[
            job_id,
            schedule.get('platform', '스마트스토어'),
            schedule.get('task', '등록갯수'),
            schedule.get('stores', []),
            schedule.get('options', {})
        ],
        replace_existing=True
    )

app = FastAPI(title="구매대행 통합관리", lifespan=lifespan)

# CORS - 크롬 확장프로그램에서 credentials 포함 요청 허용
# allow_origins=["*"]와 allow_credentials=True는 함께 사용 불가
# 대신 allow_origin_regex로 모든 origin 허용
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r".*",  # 모든 origin 허용 (크롬 확장프로그램 포함)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 & 템플릿
static_dir = APP_DIR / "static"
static_dir.mkdir(exist_ok=True)
templates_dir = APP_DIR / "templates"
templates_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

# ========== API 라우트 ==========

# 로그인 페이지
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

# 로그인 처리
@app.post("/api/login")
async def login(req: LoginRequest):
    result = gsheet.verify_user(req.username, req.password)
    if result["success"]:
        staff_name = result["name"] or req.username
        role = result.get("role", ROLE_VIEWER)
        token = create_session(req.username, staff_name, role)
        response = JSONResponse({
            "success": True,
            "username": req.username,
            "name": staff_name,
            "role": role
        })
        # samesite=lax로 설정 (외부 IP 접속 시에도 쿠키 전송)
        response.set_cookie(
            "session_token", 
            token, 
            httponly=True, 
            max_age=SESSION_EXPIRE_HOURS*3600,
            samesite="lax"
        )
        return response
    raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 틀렸습니다")

# 로그아웃
@app.post("/api/logout")
async def logout(request: Request):
    token = request.cookies.get("session_token")
    if token in sessions:
        del sessions[token]
    response = JSONResponse({"success": True})
    response.delete_cookie("session_token")
    return response

# 메인 페이지
@app.get("/", response_class=HTMLResponse)
async def main_page(request: Request):
    token = request.cookies.get("session_token")
    user = verify_session(token)
    if not user:
        return RedirectResponse("/login")
    return templates.TemplateResponse("index.html", {
        "request": request,
        "username": user["name"],
        "role": user.get("role", ROLE_VIEWER)
    })

# 현재 사용자
@app.get("/api/me")
async def get_me(request: Request):
    user = get_current_user(request)
    role = user.get("role", ROLE_VIEWER)

    response = {
        "username": user["username"],
        "name": user["name"],
        "role": role,
        "permissions": get_role_permissions(role)
    }

    # 운영자인 경우 탭 권한 정보도 반환
    if role == ROLE_OPERATOR:
        try:
            if TAB_PERMISSIONS_FILE.exists():
                with open(TAB_PERMISSIONS_FILE, 'r', encoding='utf-8') as f:
                    response["tab_permissions"] = json.load(f)
            else:
                # 기본값: 모든 탭 허용
                response["tab_permissions"] = {
                    "sms": True, "monitor": True, "market": True, "sales": True,
                    "accounts": True, "marketing": True, "aio": True, "scheduler": True,
                    "bulsaja": True, "tools": True, "calendar": True
                }
        except Exception as e:
            print(f"[탭 권한 로드 오류] {e}")
            response["tab_permissions"] = None

    return response

# 계정 목록
@app.get("/api/accounts")
async def get_accounts(request: Request, platform: str = None):
    get_current_user(request)
    accounts = gsheet.get_accounts(platform)
    
    # 플랫폼별 수량 계산
    all_accounts = gsheet.get_accounts(None)
    platform_counts = {}
    for acc in all_accounts:
        p = acc.get("platform", "")
        platform_counts[p] = platform_counts.get(p, 0) + 1
    
    # 비밀번호/시크릿 마스킹
    for acc in accounts:
        if acc.get("password"):
            acc["password_masked"] = "●" * min(len(acc["password"]), 8)
        if acc.get("ss_app_secret"):
            acc["ss_app_secret_masked"] = acc["ss_app_secret"][:4] + "●●●●" if len(acc["ss_app_secret"]) > 4 else "●●●●"
        if acc.get("cp_secret_key"):
            acc["cp_secret_key_masked"] = acc["cp_secret_key"][:4] + "●●●●" if len(acc["cp_secret_key"]) > 4 else "●●●●"
    
    return {
        "accounts": accounts, 
        "platforms": list(PLATFORM_CONFIG.keys()),
        "platform_counts": platform_counts,
        "total_count": len(all_accounts)
    }

# 계정 상세 (비밀번호 포함)
@app.get("/api/accounts/{platform}/{account_id}")
async def get_account_detail(request: Request, platform: str, account_id: str):
    get_current_user(request)
    accounts = gsheet.get_accounts(platform)
    for acc in accounts:
        login_id = acc.get("아이디") or acc.get("login_id") or ""
        if login_id == account_id:
            return acc
    raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다")

@app.get("/api/accounts/search")
async def search_account(request: Request, shop_alias: str = None, store_name: str = None, platform: str = None, login_id: str = None):
    """계정 검색 - store_name 또는 login_id로 검색"""
    get_current_user(request)
    
    # store_name이 없으면 shop_alias 사용 (하위 호환)
    search_name = store_name or shop_alias
    
    # 모든 플랫폼에서 검색
    platforms_to_search = [platform] if platform else ["스마트스토어", "쿠팡", "11번가", "지마켓", "옥션", "ESM통합"]
    
    for p in platforms_to_search:
        accounts = gsheet.get_accounts(p)
        for acc in accounts:
            # store_name으로 검색
            acc_name = acc.get("스토어명") or acc.get("스토어명", "")
            if search_name and acc_name == search_name:
                return acc
            # login_id로 검색
            if login_id and acc.get("login_id") == login_id:
                return acc
    
    return {"login_id": None, "message": "계정을 찾을 수 없습니다"}

# 계정 추가
@app.post("/api/accounts")
async def add_account(request: Request, account: AccountModel):
    require_permission(request, "edit")  # 운영자 이상
    if gsheet.add_account(account.dict()):
        await ws_manager.broadcast({"type": "account_update"})
        return {"success": True}
    raise HTTPException(status_code=500, detail="추가 실패")

# 계정 수정
@app.put("/api/accounts/{platform}/{account_id}")
async def update_account(request: Request, platform: str, account_id: str):
    require_permission(request, "edit")  # 운영자 이상
    
    # 요청 본문에서 실제 전달된 필드만 가져오기
    body = await request.json()
    
    if gsheet.update_account(account_id, platform, body):
        await ws_manager.broadcast({"type": "account_update"})
        return {"success": True}
    raise HTTPException(status_code=500, detail="수정 실패")

# 계정 삭제
@app.delete("/api/accounts/{platform}/{account_id}")
async def delete_account(request: Request, platform: str, account_id: str):
    require_permission(request, "delete")  # 관리자만
    if gsheet.delete_account(account_id, platform):
        await ws_manager.broadcast({"type": "account_update"})
        return {"success": True}
    raise HTTPException(status_code=500, detail="삭제 실패")

# ========== 관제센터 API ==========

@app.get("/api/monitor/daily-status")
async def get_daily_status(request: Request):
    """마켓별 상태 조회 - 새로운 전용 데이터 시트(1r-ROJ...) 참조"""
    get_current_user(request)
    
    try:
        # 1. 외부 전용 시트에서 등록갯수/11번가 데이터 가져오기 (전용 인증 파일 사용)
        ss_counts = {}
        st_counts = {}
        ss_reg_map = {}
        st_reg_map = {}
        today = datetime.now().date()
        
        # 스마트스토어 (등록갯수 탭)
        ws_counts = gsheet.open_worksheet_with_creds(COUNT_CREDENTIALS_FILE, SPREADSHEET_KEY, "등록갯수")
        if ws_counts:
            data = ws_counts.get_all_values()
            if len(data) > 1:
                h = data[0]
                n_idx = next((i for i, v in enumerate(h) if v in ["store_name", "스토어명"]), None)
                c_idx = next((i for i, v in enumerate(h) if v == "판매중"), None)
                r_idx = next((i for i, v in enumerate(h) if "마지막" in v and "등록" in v), None)
                
                if n_idx is not None:
                    for row in data[1:]:
                        if len(row) > n_idx:
                            store = row[n_idx].strip()
                            if not store: continue
                            # 상품수
                            if c_idx is not None and len(row) > c_idx:
                                try: ss_counts[store] = int(row[c_idx]) if row[c_idx] else 0
                                except: ss_counts[store] = 0
                            # 마지막 등록일
                            if r_idx is not None and len(row) > r_idx and row[r_idx]:
                                try:
                                    d_str = row[r_idx][:10]
                                    d_val = datetime.strptime(d_str, "%Y-%m-%d").date()
                                    ss_reg_map[store] = {"date": d_str, "days": (today - d_val).days}
                                except: pass

        # 11번가 (11번가 탭)
        ws_11st = gsheet.open_worksheet_with_creds(COUNT_CREDENTIALS_FILE, SPREADSHEET_KEY, "11번가")
        if ws_11st:
            data = ws_11st.get_all_values()
            if len(data) > 1:
                h = data[0]
                n_idx = next((i for i, v in enumerate(h) if v in ["store_name", "쇼핑몰 별칭", "스토어명"]), None)
                c_idx = next((i for i, v in enumerate(h) if v == "판매중"), None)
                r_idx = next((i for i, v in enumerate(h) if "마지막" in v and "등록" in v), None)
                
                if n_idx is not None:
                    for row in data[1:]:
                        if len(row) > n_idx:
                            store = row[n_idx].strip()
                            if not store: continue
                            # 상품수
                            if c_idx is not None and len(row) > c_idx:
                                try: st_counts[store] = int(row[c_idx]) if row[c_idx] else 0
                                except: st_counts[store] = 0
                            # 마지막 등록일
                            if r_idx is not None and len(row) > r_idx and row[r_idx]:
                                try:
                                    d_str = row[r_idx][:10]
                                    d_val = datetime.strptime(d_str, "%Y-%m-%d").date()
                                    st_reg_map[store] = {"date": d_str, "days": (today - d_val).days}
                                except: pass

        # 2. 계정 정보 가져오기
        all_accounts = gsheet.get_accounts()
        
        # 3. 작업로그 (삭제 작업 등) - 기존 시트 참조
        last_work_map = {}
        try:
            ws_worklog = gsheet.sheet.worksheet("작업로그")
            worklog_data = ws_worklog.get_all_values()
            if len(worklog_data) > 1:
                h = worklog_data[0]
                d_idx = next((i for i, v in enumerate(h) if '일시' in v or '날짜' in v), 0)
                a_idx = next((i for i, v in enumerate(h) if '계정' in v or '스토어' in v), 2)
                for row in worklog_data[1:]:
                    if len(row) > max(d_idx, a_idx):
                        date_str = row[d_idx].strip()
                        acc_name = row[a_idx].strip()
                        if not date_str or not acc_name: continue
                        try:
                            w_date = datetime.strptime(date_str.split()[0].replace('/', '-'), "%Y-%m-%d").date()
                            if acc_name not in last_work_map or w_date > datetime.strptime(last_work_map[acc_name]["date"], "%Y-%m-%d").date():
                                last_work_map[acc_name] = {"date": w_date.strftime("%Y-%m-%d"), "days": (today - w_date).days}
                        except: pass
        except: pass

        result_data = []
        markets_set = set()
        usages_set = set()
        
        for idx, acc in enumerate(all_accounts):
            platform = acc.get("플랫폼") or acc.get("platform") or ""
            store_name = (acc.get("스토어명") or "").strip()
            login_id = (acc.get("아이디") or acc.get("login_id") or "").strip()
            usage = (acc.get("용도") or acc.get("usage") or "").strip()
            owner = (acc.get("소유자") or acc.get("owner") or "").strip()
            if not platform: continue
            
            market = platform
            if "스마트" in platform or "네이버" in platform: market = "스마트스토어"
            elif "11" in platform: market = "11번가"
            elif "쿠팡" in platform: market = "쿠팡"
            elif "지마켓" in platform: market = "지마켓"
            elif "옥션" in platform: market = "옥션"
            elif "ESM" in platform: market = "ESM"
            markets_set.add(market)
            if usage: usages_set.add(usage)
            
            # 매칭용 이름 정규화
            account_name = store_name if store_name else login_id
            
            # 상품수 매칭
            product_count = 0
            if market == "스마트스토어":
                product_count = ss_counts.get(account_name, 0)
                if product_count == 0 and "_" in account_name:
                    product_count = ss_counts.get(account_name.split("_", 1)[1], 0)
            elif market == "11번가":
                product_count = st_counts.get(account_name, 0)
                if product_count == 0: product_count = st_counts.get(login_id, 0)
            
            # 마지막 등록일 매칭
            last_cleanup_date = datetime.now().strftime("%Y-%m-%d")
            days_since_cleanup = 0
            
            # 플랫폼별 전용 시트 매칭 시도
            match_name = account_name
            found = False
            target_reg_map = ss_reg_map if market == "스마트스토어" else (st_reg_map if market == "11번가" else {})
            
            if match_name in target_reg_map: 
                found = True
            elif "_" in match_name and match_name.split("_", 1)[1] in target_reg_map:
                match_name = match_name.split("_", 1)[1]
                found = True
            
            if found:
                last_cleanup_date = target_reg_map[match_name]['date']
                days_since_cleanup = target_reg_map[match_name]['days']
            elif account_name in last_work_map:
                last_cleanup_date = last_work_map[account_name]['date']
                days_since_cleanup = last_work_map[account_name]['days']

            # 상태 (20일/30일 기준 유지하되 주 단위 필터는 프론트엔드에서 처리)
            cleanup_status = 'normal'
            if days_since_cleanup > 30: cleanup_status = 'urgent'
            elif days_since_cleanup > 20: cleanup_status = 'warning'

            result_data.append({
                "row": idx + 2,
                "account": account_name,
                "login_id": login_id,
                "market": market,
                "platform": platform,
                "usage": usage,
                "owner": owner,
                "count": product_count,
                "status": "normal",
                "last_cleanup_date": last_cleanup_date,
                "days_since_cleanup": days_since_cleanup,
                "cleanup_status": cleanup_status
            })
        
        # 5. 마켓상태현황 시트에서 상태 정보 가져오기
        try:
            ws_status = gsheet.sheet.worksheet(MARKET_STATUS_TAB)
            status_records = ws_status.get_all_records()
            status_map = {}
            for row in status_records:
                store = row.get("스토어명", "")
                plat = row.get("플랫폼", "")
                if store and plat:
                    status_map[f"{store}_{plat}"] = {
                        "status": row.get("상태", "정상"),
                        "note": row.get("비고", "")
                    }
            
            # 상태 적용
            for item in result_data:
                key = f"{item['account']}_{item['market']}"
                if key in status_map:
                    status_info = status_map[key]
                    status = status_info["status"]
                    item["note"] = status_info["note"]
                    if status == "정지": item["status"] = "stopped"
                    elif status == "일시정지": item["status"] = "suspended"
                    elif status == "경고": item["status"] = "warning"
                    elif status == "주의": item["status"] = "caution"
        except Exception as e:
            print(f"[관제센터] 마켓상태현황 조회 오류: {e}")
        
        return {
            "success": True,
            "data": result_data,
            "markets": sorted(list(markets_set)),
            "usages": sorted(list(usages_set))
        }
        
    except Exception as e:
        print(f"[관제센터] 조회 오류: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "message": str(e), "data": [], "markets": [], "usages": []}


# ========== 마켓상태현황 API ==========
MARKET_STATUS_TAB = "마켓상태현황"
MARKET_STATUS_HEADERS = ["스토어명", "플랫폼", "상태", "변경일시", "비고"]

def get_or_create_market_status_sheet():
    """마켓상태현황 시트 가져오기 (없으면 생성)"""
    try:
        ws = gsheet.sheet.worksheet(MARKET_STATUS_TAB)
        return ws
    except:
        # 시트 생성
        ws = gsheet.sheet.add_worksheet(title=MARKET_STATUS_TAB, rows=500, cols=len(MARKET_STATUS_HEADERS))
        ws.update('A1:E1', [MARKET_STATUS_HEADERS])
        # 헤더 서식 (굵게)
        ws.format('A1:E1', {'textFormat': {'bold': True}})
        print(f"✅ '{MARKET_STATUS_TAB}' 시트 생성됨")
        return ws

@app.get("/api/market-status")
async def get_market_status(request: Request):
    """마켓상태현황 조회"""
    get_current_user(request)
    
    try:
        ws = get_or_create_market_status_sheet()
        records = ws.get_all_records()
        
        # {스토어명_플랫폼: 상태} 맵 생성
        status_map = {}
        for row in records:
            store = row.get("스토어명", "")
            platform = row.get("플랫폼", "")
            status = row.get("상태", "정상")
            if store and platform:
                key = f"{store}_{platform}"
                status_map[key] = {
                    "status": status,
                    "updated_at": row.get("변경일시", ""),
                    "note": row.get("비고", "")
                }
        
        return {"success": True, "data": status_map}
    except Exception as e:
        print(f"[마켓상태] 조회 오류: {e}")
        return {"success": False, "message": str(e), "data": {}}


class MarketStatusUpdateRequest(BaseModel):
    store_name: str
    platform: str
    status: str
    note: Optional[str] = ""

@app.post("/api/market-status/update")
async def update_market_status(request: Request, req: MarketStatusUpdateRequest):
    """마켓상태 업데이트 (추가 또는 수정)"""
    require_permission(request, "edit")
    
    try:
        ws = get_or_create_market_status_sheet()
        records = ws.get_all_records()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # 기존 행 찾기
        row_idx = None
        for idx, row in enumerate(records):
            if row.get("스토어명") == req.store_name and row.get("플랫폼") == req.platform:
                row_idx = idx + 2  # 헤더 + 0-based index
                break
        
        if req.status == "정상":
            # 정상이면 행 삭제 (저장할 필요 없음)
            if row_idx:
                ws.delete_rows(row_idx)
                print(f"[마켓상태] 삭제: {req.store_name} ({req.platform})")
            return {"success": True, "action": "deleted"}
        else:
            if row_idx:
                # 기존 행 업데이트
                ws.update(f'C{row_idx}:E{row_idx}', [[req.status, now, req.note or ""]])
                print(f"[마켓상태] 업데이트: {req.store_name} ({req.platform}) → {req.status}")
            else:
                # 새 행 추가
                ws.append_row([req.store_name, req.platform, req.status, now, req.note or ""])
                print(f"[마켓상태] 추가: {req.store_name} ({req.platform}) → {req.status}")
            return {"success": True, "action": "updated"}
            
    except Exception as e:
        print(f"[마켓상태] 업데이트 오류: {e}")
        return {"success": False, "message": str(e)}


@app.post("/api/market-status/bulk-update")
async def bulk_update_market_status(request: Request, items: List[MarketStatusUpdateRequest]):
    """마켓상태 일괄 업데이트"""
    require_permission(request, "edit")
    
    try:
        ws = get_or_create_market_status_sheet()
        records = ws.get_all_records()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # 기존 데이터 맵
        existing = {}
        for idx, row in enumerate(records):
            key = f"{row.get('스토어명')}_{row.get('플랫폼')}"
            existing[key] = idx + 2
        
        updates = 0
        for item in items:
            key = f"{item.store_name}_{item.platform}"
            row_idx = existing.get(key)
            
            if item.status == "정상":
                if row_idx:
                    ws.delete_rows(row_idx)
                    # 인덱스 재조정
                    existing = {k: v-1 if v > row_idx else v for k, v in existing.items()}
                    updates += 1
            else:
                if row_idx:
                    ws.update(f'C{row_idx}:E{row_idx}', [[item.status, now, item.note or ""]])
                else:
                    ws.append_row([item.store_name, item.platform, item.status, now, item.note or ""])
                updates += 1
        
        return {"success": True, "updated": updates}
    except Exception as e:
        print(f"[마켓상태] 일괄 업데이트 오류: {e}")
        return {"success": False, "message": str(e)}


# 일일장부 상태 업데이트
class DailyStatusUpdateRequest(BaseModel):
    row: int
    column: str
    value: str

@app.post("/api/monitor/daily-status/update")
async def update_daily_status(request: Request, req: DailyStatusUpdateRequest):
    """일일장부 셀 값 업데이트"""
    require_permission(request, "edit")
    
    try:
        # 반대량 업로드 현황 시트의 12월 탭
        upload_sheet = gsheet.client.open_by_key("1MHhu1GdvV1OGS8Wy3NxWOKuqFvgZpqgwn08kG70EDsY")
        ws = upload_sheet.worksheet("12월")
        headers = ws.row_values(1)
        
        # 컬럼 인덱스 찾기
        col_idx = None
        for idx, h in enumerate(headers):
            if h.strip() == req.column:
                col_idx = idx + 1
                break
        
        if col_idx is None:
            return {"success": False, "message": f"컬럼 '{req.column}' 없음"}
        
        ws.update_cell(req.row, col_idx, req.value)
        return {"success": True}
        
    except Exception as e:
        print(f"[관제센터] 상태 업데이트 오류: {e}")
        return {"success": False, "message": str(e)}


class MarketExportRequest(BaseModel):
    headers: List[str]
    data: List[List[Any]]

@app.post("/api/market-table/export")
async def export_market_table(request: Request, req: MarketExportRequest):
    """마켓현황 데이터를 엑셀로 내보내기"""
    get_current_user(request) # 로그인 체크
    
    try:
        # 데이터프레임 생성
        df = pd.DataFrame(req.data, columns=req.headers)
        
        # 메모리 버퍼에 엑셀 쓰기
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='마켓현황')
        
        output.seek(0)
        
        headers = {
            'Content-Disposition': 'attachment; filename="market_status.xlsx"'
        }
        
        return StreamingResponse(
            output, 
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers=headers
        )
        
    except Exception as e:
        print(f"[마켓상태] 엑셀 내보내기 오류: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@app.get("/api/monitor/accounts")
async def get_monitor_accounts(request: Request):
    """관제센터용 계정 목록 (상태 정보 포함)"""
    get_current_user(request)

    try:
        accounts = gsheet.get_accounts()

        # monitor 시트에서 상태 정보 가져오기
        try:
            ws_monitor = gsheet.sheet.worksheet("monitor")
            monitor_data = ws_monitor.get_all_records()
            # 한글/영어 키 모두 지원
            monitor_map = {}
            for m in monitor_data:
                platform = m.get('플랫폼') or m.get('platform') or ''
                login_id = m.get('아이디') or m.get('login_id') or ''
                key = f"{platform}_{login_id}"
                monitor_map[key] = m
        except:
            monitor_map = {}

        # 작업로그에서 계정별 마지막 작업일 집계
        last_work_map = {}  # "스토어명": {"date": "2026-01-13", "days": 5}
        try:
            ws_worklog = gsheet.sheet.worksheet("작업로그")
            worklog_data = ws_worklog.get_all_values()
            if worklog_data and len(worklog_data) > 1:
                headers = worklog_data[0]
                date_idx = next((i for i, h in enumerate(headers) if '일시' in h or '날짜' in h), 0)
                type_idx = next((i for i, h in enumerate(headers) if '작업' in h and '유형' in h), 1)
                account_idx = next((i for i, h in enumerate(headers) if '계정' in h or '스토어' in h), 2)

                today = datetime.now().date()
                for row in worklog_data[1:]:
                    if len(row) > max(date_idx, account_idx):
                        work_type = row[type_idx] if len(row) > type_idx else ""
                        # 삭제 작업만 추적 (필요시 다른 작업도 추가 가능)
                        if "삭제" not in work_type:
                            continue

                        date_str = row[date_idx].strip()
                        account_name = row[account_idx].strip()
                        if not date_str or not account_name:
                            continue

                        # 날짜 파싱 (여러 형식 지원)
                        work_date = None
                        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"]:
                            try:
                                work_date = datetime.strptime(date_str.split()[0], fmt.split()[0]).date()
                                break
                            except:
                                continue

                        if work_date:
                            # 기존 기록보다 최신이면 업데이트
                            if account_name not in last_work_map or work_date > datetime.strptime(last_work_map[account_name]["date"], "%Y-%m-%d").date():
                                days_ago = (today - work_date).days
                                last_work_map[account_name] = {
                                    "date": work_date.strftime("%Y-%m-%d"),
                                    "days": days_ago
                                }
        except Exception as e:
            print(f"[관제센터] 작업로그 조회 오류: {e}")

        # 마지막등록일 데이터 조회 (등록갯수 시트 - 스마트스토어)
        last_reg_map = {}  # "스토어명": {"date": "2026-01-13", "days": 5}
        today = datetime.now().date()
        try:
            ws_counts = gsheet.sheet.worksheet("등록갯수")
            counts_data = ws_counts.get_all_values()
            if counts_data and len(counts_data) > 1:
                headers = counts_data[0]
                name_idx = None
                reg_idx = None
                print(f"[관제센터] 등록갯수 시트 헤더: {headers}")
                for i, h in enumerate(headers):
                    hl = h.strip().replace(" ", "")
                    if h in ["store_name", "스토어명"]:
                        name_idx = i
                    if "마지막" in hl and "등록" in hl:
                        reg_idx = i
                        print(f"[관제센터] 등록갯수 마지막등록일 컬럼: idx={i}, name='{h}'")

                if name_idx is not None and reg_idx is not None:
                    num_headers = len(headers)
                    for row in counts_data[1:]:
                        while len(row) < num_headers:
                            row.append('')
                        store_name = row[name_idx].strip()
                        reg_date_str = row[reg_idx].strip()
                        if store_name and reg_date_str:
                            try:
                                reg_date = datetime.strptime(reg_date_str[:10], "%Y-%m-%d").date()
                                days_ago = (today - reg_date).days
                                last_reg_map[f"스마트스토어_{store_name}"] = {"date": reg_date_str[:10], "days": days_ago}
                            except:
                                pass
                    print(f"[관제센터] 등록갯수 시트에서 마지막등록일 {len(last_reg_map)}개 로드")
                else:
                    print(f"[관제센터] 등록갯수 시트 컬럼 못찾음: name_idx={name_idx}, reg_idx={reg_idx}")
        except Exception as e:
            print(f"[관제센터] 등록갯수 시트 마지막등록일 조회 오류: {e}")

        # 마지막등록일 데이터 조회 (11번가 시트)
        try:
            ws_11st = gsheet.sheet.worksheet("11번가")
            st_data = ws_11st.get_all_values()
            if st_data and len(st_data) > 1:
                headers = st_data[0]
                name_idx = None
                reg_idx = None
                for i, h in enumerate(headers):
                    hl = h.strip().replace(" ", "")
                    if h in ["store_name", "쇼핑몰 별칭", "스토어명"]:
                        name_idx = i
                    if "마지막" in hl and "등록" in hl:
                        reg_idx = i

                if name_idx is not None and reg_idx is not None:
                    num_headers = len(headers)
                    for row in st_data[1:]:
                        while len(row) < num_headers:
                            row.append('')
                        store_name = row[name_idx].strip()
                        reg_date_str = row[reg_idx].strip()
                        if store_name and reg_date_str:
                            try:
                                reg_date = datetime.strptime(reg_date_str[:10], "%Y-%m-%d").date()
                                days_ago = (today - reg_date).days
                                last_reg_map[f"11번가_{store_name}"] = {"date": reg_date_str[:10], "days": days_ago}
                            except:
                                pass
                    print(f"[관제센터] 11번가 시트 포함 마지막등록일 총 {len(last_reg_map)}개 로드")
        except Exception as e:
            print(f"[관제센터] 11번가 시트 마지막등록일 조회 오류: {e}")

        # 계정에 상태 정보 병합
        for acc in accounts:
            platform = acc.get('플랫폼') or acc.get('platform') or ''
            login_id = acc.get('아이디') or acc.get('login_id') or ''
            key = f"{platform}_{login_id}"
            if key in monitor_map:
                acc['monitor_status'] = monitor_map[key].get('status', 'green')
                acc['warning_count'] = monitor_map[key].get('warning_count', 0)
                acc['caution_count'] = monitor_map[key].get('caution_count', 0)
                acc['suspend_count'] = monitor_map[key].get('suspend_count', 0)
                acc['memo'] = monitor_map[key].get('memo', '')
            else:
                acc['monitor_status'] = 'green'
                acc['warning_count'] = 0
                acc['caution_count'] = 0
                acc['suspend_count'] = 0
                acc['memo'] = ''
            
            # owner, optype 기본값 (시트에 없으면)
            if 'owner' not in acc or not acc['owner']:
                acc['owner'] = acc.get('owner', '')
            if 'optype' not in acc or not acc['optype']:
                acc['optype'] = acc.get('optype', '대량')
            
            # 통계 필드 (추후 연동)
            acc['product_count'] = acc.get('product_count', 0)
            acc['total_sales'] = acc.get('total_sales', 0)
            acc['order_count'] = acc.get('order_count', 0)

            # 마지막등록일 정보 병합 (등록갯수/11번가 시트 기준) - 플랫폼+스토어명 AND 조건
            store_name = acc.get('스토어명') or acc.get('store_name') or ''
            reg_key = f"{platform}_{store_name}"
            if store_name == "모음상사":
                print(f"[DEBUG] 모음상사: platform={platform}, reg_key={reg_key}, in_map={reg_key in last_reg_map}")
                print(f"[DEBUG] last_reg_map keys sample: {list(last_reg_map.keys())[:10]}")
            if reg_key in last_reg_map:
                # 마지막등록일 기준 경과일
                acc['last_cleanup_date'] = last_reg_map[reg_key]['date']
                acc['days_since_cleanup'] = last_reg_map[reg_key]['days']
            elif store_name in last_work_map:
                # 마지막등록일이 없으면 작업로그 기준 (fallback)
                acc['last_cleanup_date'] = last_work_map[store_name]['date']
                acc['days_since_cleanup'] = last_work_map[store_name]['days']
            else:
                # 둘 다 없으면 오늘 날짜로 (신규 계정 취급)
                acc['last_cleanup_date'] = datetime.now().strftime("%Y-%m-%d")
                acc['days_since_cleanup'] = 0

            # 경과일 상태 (30일 초과: urgent, 20~30일: warning, 20일 이내: normal)
            days = acc['days_since_cleanup']
            if days > 30:
                acc['cleanup_status'] = 'urgent'
            elif days > 20:
                acc['cleanup_status'] = 'warning'
            else:
                acc['cleanup_status'] = 'normal'

        return {"accounts": accounts}
    except Exception as e:
        print(f"[관제센터] 오류: {e}")
        return {"accounts": []}

# 마켓현황용 판매중 수량 API
@app.get("/api/monitor/product-counts")
async def get_product_counts(request: Request):
    """등록갯수/11번가/ESM판매중 시트에서 판매중 수량 + 마지막등록일 조회"""
    get_current_user(request)

    try:
        result = {}  # "스토어명_플랫폼": {"count": 수량, "last_reg": "YYYY-MM-DD"}

        # 1. 등록갯수 시트 (스마트스토어)
        try:
            ws_counts = gsheet.sheet.worksheet("등록갯수")
            counts_data = ws_counts.get_all_values()
            if counts_data and len(counts_data) > 1:
                headers = counts_data[0]
                name_idx = None
                count_idx = None
                last_reg_idx = None
                print(f"[product-counts] 등록갯수 시트 전체 헤더: {headers}")
                for i, h in enumerate(headers):
                    hl = h.strip().lower().replace(" ", "")
                    if h == "스토어명":
                        name_idx = i
                    elif h == "판매중":
                        count_idx = i
                    elif "마지막" in hl and "등록" in hl:
                        last_reg_idx = i
                        print(f"[product-counts] 마지막등록일 컬럼 발견: idx={i}, name='{h}'")

                print(f"[product-counts] 등록갯수 헤더: name_idx={name_idx}, count_idx={count_idx}, last_reg_idx={last_reg_idx}")

                # 시트 데이터 샘플 출력 (첫 3행)
                if len(counts_data) > 1:
                    for i, row in enumerate(counts_data[1:4]):
                        last_val = row[last_reg_idx] if last_reg_idx is not None and last_reg_idx < len(row) else "N/A"
                        print(f"[product-counts] 등록갯수 샘플행{i+1}: 행길이={len(row)}, last_reg_idx={last_reg_idx}, last_reg값='{last_val}'")

                if name_idx is not None and count_idx is not None:
                    sample_count = 0
                    num_headers = len(headers)
                    for row in counts_data[1:]:
                        # 행 길이를 헤더 길이에 맞춤 (빈 셀 패딩)
                        while len(row) < num_headers:
                            row.append('')

                        if len(row) > max(name_idx, count_idx):
                            store = row[name_idx].strip()
                            try:
                                cnt = int(row[count_idx]) if row[count_idx] else 0
                            except:
                                cnt = 0
                            last_reg = ""
                            if last_reg_idx is not None:
                                last_reg = row[last_reg_idx].strip()
                            if store:
                                result[f"{store}_스마트스토어"] = {"count": cnt, "last_reg": last_reg}
                                if sample_count < 3:
                                    print(f"[product-counts] 샘플: {store} -> count={cnt}, last_reg={last_reg}")
                                    sample_count += 1
        except Exception as e:
            print(f"[product-counts] 등록갯수 시트 오류: {e}")

        # 2. 11번가 시트
        try:
            ws_11st = gsheet.sheet.worksheet("11번가")
            st_data = ws_11st.get_all_values()
            if st_data and len(st_data) > 1:
                headers = st_data[0]
                print(f"[product-counts] 11번가 시트 전체 헤더: {headers}")
                name_idx = None
                count_idx = None
                last_reg_idx = None
                for i, h in enumerate(headers):
                    hl = h.strip().lower().replace(" ", "")
                    if h in ["store_name", "쇼핑몰 별칭", "스토어명"]:
                        name_idx = i
                    elif h == "판매중":
                        count_idx = i
                    elif "마지막" in hl and "등록" in hl:
                        last_reg_idx = i
                        print(f"[product-counts] 11번가 마지막등록일 컬럼 발견: idx={i}, name='{h}'")

                print(f"[product-counts] 11번가 인덱스: name={name_idx}, count={count_idx}, last_reg={last_reg_idx}")
                if name_idx is not None and count_idx is not None:
                    num_headers = len(headers)
                    for row in st_data[1:]:
                        # 행 길이를 헤더 길이에 맞춤 (빈 셀 패딩)
                        while len(row) < num_headers:
                            row.append('')

                        if len(row) > max(name_idx, count_idx):
                            store = row[name_idx].strip()
                            try:
                                cnt = int(row[count_idx]) if row[count_idx] else 0
                            except:
                                cnt = 0
                            last_reg = ""
                            if last_reg_idx is not None:
                                last_reg = row[last_reg_idx].strip()
                            if store:
                                result[f"{store}_11번가"] = {"count": cnt, "last_reg": last_reg}
        except Exception as e:
            print(f"[product-counts] 11번가 시트 오류: {e}")
        
        # 3. ESM판매중 시트 (지마켓/옥션)
        try:
            ws_esm = gsheet.sheet.worksheet("ESM판매중")
            esm_data = ws_esm.get_all_values()
            if esm_data and len(esm_data) > 1:
                headers = esm_data[0]
                name_idx = None
                platform_idx = None
                count_idx = None
                for i, h in enumerate(headers):
                    if h == "스토어명":
                        name_idx = i
                    elif h == "platform":
                        platform_idx = i
                    elif h == "product_count":
                        count_idx = i
                
                if name_idx is not None and count_idx is not None:
                    for row in esm_data[1:]:
                        if len(row) > max(name_idx, count_idx):
                            store = row[name_idx].strip()
                            platform = row[platform_idx].strip() if platform_idx is not None and platform_idx < len(row) else ""
                            try:
                                cnt = int(row[count_idx]) if row[count_idx] else 0
                            except:
                                cnt = 0
                            if store and platform:
                                result[f"{store}_{platform}"] = cnt
        except Exception as e:
            print(f"[product-counts] ESM판매중 시트 오류 (시트 없을 수 있음): {e}")
        
        # 디버그: last_reg 있는 데이터 개수 출력
        with_last_reg = [k for k, v in result.items() if isinstance(v, dict) and v.get('last_reg')]
        print(f"[product-counts] 총 {len(result)}개 중 last_reg 있음: {len(with_last_reg)}개")
        if with_last_reg[:5]:
            print(f"[product-counts] last_reg 샘플: {[(k, result[k]) for k in with_last_reg[:5]]}")

        return {
            "success": True,
            "data": result,
            "debug": {
                "total": len(result),
                "with_last_reg": len(with_last_reg),
                "samples": [(k, result[k]) for k in with_last_reg[:3]] if with_last_reg else []
            }
        }
    except Exception as e:
        print(f"[product-counts] 오류: {e}")
        return {"success": False, "data": {}, "message": str(e)}


class ProductCountUpdateRequest(BaseModel):
    store_name: str
    platform: str
    count: int


@app.post("/api/market/update-product-count")
async def update_product_count(request: Request, req: ProductCountUpdateRequest):
    """지마켓/옥션 판매중 수량 업데이트"""
    require_permission(request, "edit")
    
    if req.platform not in ["지마켓", "옥션"]:
        return {"success": False, "message": "지마켓/옥션만 수정 가능합니다"}
    
    try:
        # ESM판매중 시트 가져오기 (없으면 생성)
        try:
            ws_esm = gsheet.sheet.worksheet("ESM판매중")
        except:
            # 시트 생성
            ws_esm = gsheet.sheet.add_worksheet(title="ESM판매중", rows=500, cols=5)
            ws_esm.append_row(["store_name", "platform", "product_count", "updated_at"])
            print("[ESM판매중] 시트 생성됨")
        
        # 기존 데이터 확인
        all_data = ws_esm.get_all_values()
        headers = all_data[0] if all_data else ["store_name", "platform", "product_count", "updated_at"]
        
        # 컬럼 인덱스
        name_idx = headers.index("store_name") if "store_name" in headers else 0
        platform_idx = headers.index("platform") if "platform" in headers else 1
        count_idx = headers.index("product_count") if "product_count" in headers else 2
        
        # 기존 행 찾기
        found_row = None
        for i, row in enumerate(all_data[1:], start=2):
            if len(row) > max(name_idx, platform_idx):
                if row[name_idx].strip() == req.store_name and row[platform_idx].strip() == req.platform:
                    found_row = i
                    break
        
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if found_row:
            # 기존 행 업데이트
            ws_esm.update_cell(found_row, count_idx + 1, req.count)
            if "updated_at" in headers:
                ws_esm.update_cell(found_row, headers.index("updated_at") + 1, now)
            print(f"[ESM판매중] {req.store_name}({req.platform}) 업데이트: {req.count}")
        else:
            # 새 행 추가
            ws_esm.append_row([req.store_name, req.platform, req.count, now])
            print(f"[ESM판매중] {req.store_name}({req.platform}) 추가: {req.count}")
        
        return {"success": True, "message": "저장 완료"}
        
    except Exception as e:
        print(f"[ESM판매중] 저장 오류: {e}")
        return {"success": False, "message": str(e)}

class MonitorUpdateRequest(BaseModel):
    platform: str
    login_id: str
    monitor_status: str = "green"
    warning_count: int = 0
    memo: str = ""

@app.post("/api/monitor/update")
async def update_monitor_status(request: Request, req: MonitorUpdateRequest):
    """계정 상태 업데이트"""
    require_permission(request, "edit")
    
    try:
        # monitor 시트 가져오기 (없으면 생성)
        try:
            ws_monitor = gsheet.sheet.worksheet("monitor")
        except:
            ws_monitor = gsheet.sheet.add_worksheet(title="monitor", rows=1000, cols=10)
            ws_monitor.append_row(["platform", "login_id", "status", "warning_count", "memo", "updated_at"])
        
        # 기존 데이터 확인
        all_data = ws_monitor.get_all_records()
        target_row = None
        for idx, row in enumerate(all_data):
            if row.get("platform") == req.platform and row.get("login_id") == req.login_id:
                target_row = idx + 2
                break
        
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if target_row:
            # 업데이트
            ws_monitor.update(f"C{target_row}:F{target_row}", 
                            [[req.monitor_status, req.warning_count, req.memo, now]])
        else:
            # 새로 추가
            ws_monitor.append_row([req.platform, req.login_id, req.monitor_status, 
                                  req.warning_count, req.memo, now])
        
        return {"success": True}
    except Exception as e:
        print(f"[관제센터] 업데이트 오류: {e}")
        return {"success": False, "message": str(e)}

# 비밀번호 업데이트 API (확장프로그램에서 자동 변경 시 호출)
class UpdatePasswordRequest(BaseModel):
    platform: str
    login_id: str
    new_password: str

@app.post("/api/update-password")
async def update_password(request: Request, req: UpdatePasswordRequest):
    """크롬 확장에서 비밀번호 변경 시 호출"""
    # API 키 인증 또는 세션 인증
    api_key = request.headers.get("X-API-Key")
    if api_key != "pkonomiautokey2024":
        try:
            get_current_user(request)
        except:
            raise HTTPException(status_code=401, detail="인증 필요")
    
    try:
        # 계정 시트에서 해당 계정 찾기
        ws = gsheet.sheet.worksheet(ACCOUNTS_TAB)  # "계정목록" 사용
        all_data = ws.get_all_records()
        
        target_row = None
        for idx, row in enumerate(all_data):
            # 플랫폼과 아이디로 찾기
            row_platform = row.get("플랫폼") or row.get("platform", "")
            row_login_id = row.get("아이디") or row.get("login_id", "")
            if row_platform == req.platform and row_login_id == req.login_id:
                target_row = idx + 2  # 헤더 + 0-indexed
                break
        
        if not target_row:
            return {"success": False, "message": "계정을 찾을 수 없습니다"}
        
        # 패스워드 열 찾기
        headers = ws.row_values(1)
        pw_col = None
        for i, h in enumerate(headers):
            if h in ["패스워드", "password", "비밀번호"]:
                pw_col = i + 1
                break
        
        if not pw_col:
            return {"success": False, "message": "패스워드 열을 찾을 수 없습니다"}
        
        # 비밀번호 업데이트
        ws.update_cell(target_row, pw_col, req.new_password)
        
        print(f"[비밀번호변경] {req.platform}/{req.login_id} → {req.new_password}")
        
        return {"success": True, "message": "비밀번호가 업데이트되었습니다"}
        
    except Exception as e:
        print(f"[비밀번호변경] 오류: {e}")
        return {"success": False, "message": str(e)}

@app.post("/api/accounts/update-password")
async def update_account_password(request: Request, req: UpdatePasswordRequest):
    """비밀번호 자동 변경 후 구글시트 업데이트"""
    get_current_user(request)
    
    try:
        # 계정 시트에서 해당 계정 찾기
        ws = gsheet.sheet.worksheet("accounts")
        all_data = ws.get_all_records()
        
        target_row = None
        for idx, row in enumerate(all_data):
            if row.get("platform") == req.platform and row.get("login_id") == req.login_id:
                target_row = idx + 2  # 헤더 + 0-indexed
                break
        
        if not target_row:
            return {"success": False, "message": "계정을 찾을 수 없습니다"}
        
        # password 열 찾기
        headers = ws.row_values(1)
        pw_col = None
        for i, h in enumerate(headers):
            if h.lower() == "password":
                pw_col = i + 1
                break
        
        if not pw_col:
            return {"success": False, "message": "password 열을 찾을 수 없습니다"}
        
        # 비밀번호 업데이트
        ws.update_cell(target_row, pw_col, req.new_password)
        
        print(f"[비밀번호변경] {req.platform}/{req.login_id} 비밀번호 업데이트 완료")
        
        await ws_manager.broadcast({"type": "account_update"})
        return {"success": True, "message": "비밀번호 업데이트 완료"}
        
    except Exception as e:
        print(f"[비밀번호변경] 오류: {e}")
        return {"success": False, "message": str(e)}

# 자동 로그인 API (클라이언트 프로그램에서 처리)
class AutoLoginRequest(BaseModel):
    platform: str
    login_id: str

@app.post("/api/auto-login")
async def auto_login(request: Request, req: AutoLoginRequest):
    """자동 로그인 요청 - 클라이언트 프로그램이 처리"""
    get_current_user(request)
    
    # 계정 정보 가져오기
    accounts = gsheet.get_accounts(req.platform)
    account = None
    for acc in accounts:
        login_id = acc.get("아이디") or acc.get("login_id") or ""
        if login_id == req.login_id:
            account = acc
            break
    
    if not account:
        return {"success": False, "message": "계정을 찾을 수 없습니다"}
    
    platform_config = PLATFORM_CONFIG.get(req.platform)
    if not platform_config:
        return {"success": False, "message": "플랫폼 설정 없음"}
    
    # 클라이언트 연결 확인
    if not client_status.get("connected"):
        return {"success": False, "message": "클라이언트 프로그램이 연결되지 않았습니다. 클라이언트를 실행해주세요."}
    
    # 클라이언트가 읽어갈 pending 정보 저장
    global pending_login_info
    pending_login_info = {
        "platform": req.platform,
        "login_id": account["login_id"],
        "password": account["password"],
        "url": platform_config["login_url"],
        "timestamp": datetime.now().isoformat()
    }
    
    return {"pending": True, "message": "클라이언트에서 로그인 진행 중..."}

# 자동 로그인 대기 정보 (클라이언트 프로그램용)
pending_login_info = {}

# 클라이언트 상태 (앞에서 정의)
client_status = {"connected": False, "last_ping": None}

class PendingLoginRequest(BaseModel):
    platform: str
    login_id: str
    password: str
    url: str

@app.post("/api/auto-login/pending")
async def set_pending_login(request: Request, req: PendingLoginRequest):
    """클라이언트 프로그램이 읽어갈 로그인 정보 저장"""
    get_current_user(request)
    
    global pending_login_info
    pending_login_info = {
        "platform": req.platform,
        "login_id": req.login_id,
        "password": req.password,
        "url": req.url,
        "timestamp": datetime.now().isoformat()
    }
    
    return {"success": True}

@app.get("/api/auto-login/pending")
async def get_pending_login(request: Request):
    """클라이언트 프로그램이 읽어갈 로그인 정보 조회"""
    # API 키 인증 또는 세션 인증
    api_key = request.headers.get("X-API-Key")
    if api_key != "pkonomiautokey2024":
        try:
            get_current_user(request)
        except:
            raise HTTPException(status_code=401, detail="인증 필요")
    
    # 클라이언트 상태 업데이트
    client_status["connected"] = True
    client_status["last_ping"] = datetime.now()
    
    global pending_login_info
    if pending_login_info:
        result = pending_login_info.copy()
        result["pending"] = True
        # 읽은 후 삭제 (1회용)
        pending_login_info = {}
        return result
    
    return {"platform": None, "pending": False}

# 플랫폼 설정
@app.get("/api/platforms")
async def get_platforms(request: Request):
    get_current_user(request)
    return {"platforms": PLATFORM_CONFIG}

# SMS 브라우저 상태
@app.get("/api/sms/status")
async def get_sms_status(request: Request):
    get_current_user(request)
    return {
        "profiles": PHONE_PROFILES,
        "ready": sms_manager.ready,
        "auth_codes": sms_manager.auth_codes
    }

# 인증코드 조회 (확장프로그램용 - API 키 인증)
@app.get("/api/sms/auth-code")
async def get_auth_code(request: Request, refresh: bool = False):
    """최신 인증코드 반환 - 확장프로그램/수집기에서 사용"""
    # API 키 인증 또는 세션 인증
    api_key = request.headers.get("X-API-Key")
    if api_key != "pkonomiautokey2024":
        try:
            get_current_user(request)
        except:
            raise HTTPException(status_code=401, detail="인증 필요")
    
    # ★ refresh=true이면 강제 새로고침 (실시간 메시지 수집 보장)
    if refresh:
        await sms_manager.refresh_messages()

    # ★ clear_time 가져오기 (없으면 0)
    clear_time = getattr(sms_manager, 'auth_code_clear_time', 0)
    
    # 전체 메시지에서 가장 최근 수신 시간의 인증코드 찾기
    latest_code = None
    latest_time = None
    latest_timestamp = 0  # Unix timestamp
    
    for msg in sms_manager.messages:
        if msg.auth_code and msg.auth_code.isdigit() and len(msg.auth_code) >= 4:
            # timestamp를 Unix timestamp로 변환
            msg_timestamp = sms_manager._parse_relative_time(msg.timestamp)
            
            # ★ clear_time 이후 메시지만 사용
            if msg_timestamp <= clear_time:
                continue
            
            # 가장 최근 메시지 찾기
            if msg_timestamp > latest_timestamp:
                latest_timestamp = msg_timestamp
                latest_code = msg.auth_code
                latest_time = msg.timestamp
    
    return {
        "code": latest_code,
        "time": latest_time,
        "auth_codes": sms_manager.auth_codes  # 전체 인증코드 정보 (시간 포함)
    }

# 인증코드 초기화 (확장프로그램용 - API 키 인증)
@app.post("/api/sms/auth-code/clear")
async def clear_auth_code(request: Request):
    """인증코드 초기화 - 새 인증코드 대기 전 호출"""
    # API 키 인증
    api_key = request.headers.get("X-API-Key")
    if api_key != "pkonomiautokey2024":
        raise HTTPException(status_code=401, detail="API 키 필요")
    
    # ★ clear_time 기록 (이 시점 이후 메시지만 사용)
    sms_manager.auth_code_clear_time = time.time()
    
    # 모든 인증코드 초기화
    sms_manager.auth_codes.clear()
    
    return {"success": True, "message": "인증코드 초기화됨"}

# SMS 브라우저 시작 (운영자 이상)
@app.post("/api/sms/launch/{profile_id}")
async def launch_sms_browser(request: Request, profile_id: str):
    require_permission(request, "sms_control")  # 운영자 이상
    if profile_id not in PHONE_PROFILES:
        raise HTTPException(status_code=400, detail="잘못된 프로필")
    
    await sms_manager.launch_browser(profile_id)
    await ws_manager.broadcast({"type": "sms_status", "ready": sms_manager.ready})
    return {"success": True, "ready": sms_manager.ready.get(profile_id)}

# SMS 브라우저 전체 시작 (운영자 이상)
@app.post("/api/sms/launch-all")
async def launch_all_sms(request: Request):
    require_permission(request, "sms_control")  # 운영자 이상
    await sms_manager.launch_all()
    await ws_manager.broadcast({"type": "sms_status", "ready": sms_manager.ready})
    return {"success": True, "ready": sms_manager.ready}

# SMS 메시지 새로고침 (모든 사용자 - 뷰어도 가능)
# SMS 새로고침 쓰로틀링
_sms_last_refresh = None
_sms_refresh_interval = 3  # 최소 3초 간격

@app.get("/api/sms/messages")
async def get_sms_messages(request: Request, refresh: bool = False):
    """SMS 메시지 목록 - refresh=true일 때만 새로고침 (3초 쓰로틀링)"""
    global _sms_last_refresh
    get_current_user(request)  # 로그인만 확인
    
    # refresh 파라미터가 true일 때만 실제로 새로고침
    if refresh:
        now = datetime.now()
        # 마지막 새로고침 후 3초 이내면 캐시 반환
        if _sms_last_refresh and (now - _sms_last_refresh).total_seconds() < _sms_refresh_interval:
            pass  # 캐시 사용
        else:
            await sms_manager.refresh_messages()
            _sms_last_refresh = now
    
    messages = sms_manager.messages
    
    return {
        "messages": [asdict(m) for m in messages],
        "auth_codes": sms_manager.auth_codes
    }


@app.post("/api/sms/refresh")
async def refresh_sms_messages(request: Request):
    """SMS 메시지 강제 새로고침"""
    get_current_user(request)
    messages = await sms_manager.refresh_messages()
    return {
        "messages": [asdict(m) for m in messages],
        "auth_codes": sms_manager.auth_codes
    }

@app.post("/api/sms/reload-page")
async def reload_sms_pages(request: Request):
    """구글메시지 페이지 F5 새로고침"""
    require_permission(request, "edit")  # 운영자 이상
    reloaded = []
    errors = []
    for profile_id, page in list(sms_manager.pages.items()):
        try:
            if page and not page.is_closed():
                await page.reload(timeout=30000)
                reloaded.append(profile_id)
        except Exception as e:
            errors.append(f"{profile_id}: {str(e)}")
    if reloaded:
        return {"success": True, "message": f"새로고침 완료: {', '.join(reloaded)}"}
    elif errors:
        return {"success": False, "message": f"오류: {', '.join(errors)}"}
    else:
        return {"success": False, "message": "활성화된 브라우저가 없습니다"}

# SMS 전송 (운영자 이상)
@app.post("/api/sms/send")
async def send_sms(request: Request, req: SMSRequest):
    require_permission(request, "sms_send")  # 운영자 이상
    success = await sms_manager.send_message(req.phone_profile, req.to_number, req.message)
    if success:
        # 작업 로그 기록
        log_work("SMS전송", req.phone_profile, 1, f"수신: {req.to_number}", "웹")
        await ws_manager.broadcast({"type": "sms_sent", "profile": req.phone_profile})
        return {"success": True}
    raise HTTPException(status_code=500, detail="전송 실패")

# SMS 전송 with 파일 첨부 (운영자 이상)
@app.post("/api/sms/send-with-file")
async def send_sms_with_file(
    request: Request,
    phone_profile: str = Form(...),
    to_number: str = Form(...),
    message: str = Form(""),
    file: UploadFile = File(None)
):
    require_permission(request, "sms_send")  # 운영자 이상

    file_path = None
    try:
        # 파일이 있으면 임시 저장
        if file and file.filename:
            upload_dir = APP_DIR / "uploads"
            upload_dir.mkdir(exist_ok=True)

            # 파일명 안전하게 처리
            import uuid
            ext = os.path.splitext(file.filename)[1]
            safe_filename = f"{uuid.uuid4().hex}{ext}"
            file_path = str(upload_dir / safe_filename)

            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)
            print(f"[SMS] 파일 업로드됨: {file_path} ({len(content)} bytes)")

        # 메시지 전송
        success = await sms_manager.send_message(phone_profile, to_number, message, file_path)

        if success:
            # 작업 로그 기록
            log_work("SMS전송", phone_profile, 1, f"수신: {to_number}" + (" (파일첨부)" if file_path else ""), "웹")
            await ws_manager.broadcast({"type": "sms_sent", "profile": phone_profile})
            return {"success": True, "message": "전송 완료"}
        raise HTTPException(status_code=500, detail="전송 실패")

    finally:
        # 임시 파일 삭제
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass

# SMS 대화 상세 가져오기
class ConversationDetailRequest(BaseModel):
    profile_id: str
    sender: str
    offset: int = 0  # 0: 최근 20개, 20: 이전 20개, 40: 더 이전...
    limit: int = 20

@app.post("/api/sms/conversation")
async def get_conversation_detail(request: Request, req: ConversationDetailRequest):
    get_current_user(request)
    # print(f"[대화상세] 요청: profile={req.profile_id}, sender={req.sender}, offset={req.offset}")
    result = await sms_manager.get_conversation_detail(req.profile_id, req.sender, req.offset, req.limit)
    # print(f"[대화상세] 결과: messages={len(result.get('messages', []))} 개, error={result.get('error', 'None')}")
    return result

# 전화번호로 대화 검색
class SearchByPhoneRequest(BaseModel):
    profile_id: str
    phone_number: str

@app.post("/api/sms/search")
async def search_by_phone(request: Request, req: SearchByPhoneRequest):
    get_current_user(request)
    result = await sms_manager.search_by_phone(req.profile_id, req.phone_number)
    return result

# 미디어 다운로드
class MediaDownloadRequest(BaseModel):
    profile_id: str
    sender: str
    media_type: str  # image, video, file
    element_idx: str
    get_thumbnail: bool = False  # True면 썸네일, False면 원본

@app.post("/api/sms/download")
async def download_media(request: Request, req: MediaDownloadRequest):
    get_current_user(request)
    try:
        filepath = await sms_manager.download_media(req.profile_id, req.sender, req.media_type, req.element_idx, req.get_thumbnail)
        if filepath:
            return {"success": True, "filepath": filepath}
        return {"success": False, "message": "다운로드 실패 또는 이미지 없음"}
    except Exception as e:
        print(f"[다운로드 오류] {e}")
        return {"success": False, "message": str(e)}

# 다운로드 파일 서빙
from fastapi.responses import FileResponse

@app.get("/downloads/{profile_id}/{filename}")
async def serve_download(request: Request, profile_id: str, filename: str):
    get_current_user(request)
    filepath = APP_DIR / "downloads" / profile_id / filename
    if filepath.exists():
        return FileResponse(str(filepath))
    raise HTTPException(status_code=404, detail="파일 없음")

# WebSocket
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # 클라이언트로부터 메시지 처리 (필요시)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

# ========== 불사자 API ==========
class BulsajaRunRequest(BaseModel):
    groups: str
    max_concurrent: int = 3
    group_gap: int = 60
    # 설정값
    program: str = ""
    uploadMarket: str = ""
    uploadCount: str = ""
    deleteCount: str = ""
    copySourceMarket: str = ""
    copyCount: str = ""

@app.post("/api/bulsaja/run")
async def run_bulsaja(request: Request, req: BulsajaRunRequest):
    get_current_user(request)
    print(f"[API] /api/bulsaja/run 호출: groups={req.groups}, program={req.program}")

    # 작업 로그 기록
    group_names = ", ".join([str(g) for g in req.groups[:5]]) + ("..." if len(req.groups) > 5 else "")
    log_work(f"불사자-{req.program}", "불사자", len(req.groups), f"그룹: {group_names}", "웹")

    # 설정값을 딕셔너리로 전달
    settings = {
        "program": req.program,
        "uploadMarket": req.uploadMarket,
        "uploadCount": req.uploadCount,
        "deleteCount": req.deleteCount,
        "copySourceMarket": req.copySourceMarket,
        "copyCount": req.copyCount
    }

    result = bulsaja_manager.start(req.groups, req.max_concurrent, req.group_gap, settings)
    print(f"[API] /api/bulsaja/run 결과: {result}")
    return result

@app.post("/api/bulsaja/stop")
async def stop_bulsaja(request: Request):
    get_current_user(request)
    result = bulsaja_manager.stop()
    return result

@app.get("/api/bulsaja/status")
async def get_bulsaja_status(request: Request):
    get_current_user(request)
    return bulsaja_manager.get_status()

@app.get("/api/bulsaja/logs")
async def get_bulsaja_logs(request: Request):
    get_current_user(request)
    return {"logs": getattr(bulsaja_manager, 'logs', [])}

# 작업 로그 모델
class WorkLogRequest(BaseModel):
    work_type: str  # 상품삭제, 상품등록, 상품수정, 마케팅수집, 예약작업
    account: str    # 계정명 또는 그룹명
    count: int = 0  # 처리 상품/계정 수
    detail: str = ""  # 상세 내용
    method: str = ""  # 실행 방법
    datetime: str = ""  # 날짜/시간 (YYYY-MM-DD HH:MM:SS) - 비어있으면 현재 시간

class BulsajaFolderRequest(BaseModel):
    folder: str

@app.post("/api/bulsaja/folder")
async def set_bulsaja_folder(request: Request, req: BulsajaFolderRequest):
    get_current_user(request)
    return bulsaja_manager.set_folder(req.folder)

# ========== 작업 로그 API ==========
WORK_LOG_SHEET = "작업로그"

def log_work(work_type: str, account: str, count: int = 0, detail: str = "", method: str = "", datetime_str: str = ""):
    """작업 로그 기록"""
    try:
        from datetime import datetime
        
        # Google Sheets에 기록
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        wb = gc.open_by_key(SPREADSHEET_KEY)
        
        # 작업로그 시트 가져오기 (없으면 생성)
        try:
            ws = wb.worksheet(WORK_LOG_SHEET)
        except:
            ws = wb.add_worksheet(title=WORK_LOG_SHEET, rows=1000, cols=10)
            ws.update('A1', [['일시', '작업유형', '계정명', '상품수', '상세내용', '실행방법']])
        
        # 날짜/시간 결정 (제공되면 사용, 아니면 현재 시간)
        if datetime_str:
            timestamp = datetime_str
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 새 행 추가
        ws.append_row([timestamp, work_type, account, count, detail, method])
        
        print(f"[작업로그] {timestamp} | {work_type} | {account} | {count}개 | {detail}")
        
    except Exception as e:
        print(f"[작업로그 오류] {e}")

@app.post("/api/work-log/add")
async def add_work_log(request: Request, req: WorkLogRequest):
    """작업 로그 추가 (수동)"""
    get_current_user(request)
    log_work(req.work_type, req.account, req.count, req.detail, req.method, req.datetime)
    return {"success": True}

@app.get("/api/work-log/calendar")
async def get_work_calendar(request: Request, year: int, month: int):
    """월별 작업 로그 조회 (작업 유형별 그룹화)"""
    get_current_user(request)
    
    try:
        from datetime import datetime
        from collections import defaultdict
        
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        wb = gc.open_by_key(SPREADSHEET_KEY)
        ws = wb.worksheet(WORK_LOG_SHEET)
        
        # 모든 데이터 가져오기
        data = ws.get_all_values()[1:]  # 헤더 제외
        
        # 해당 월 필터링 및 그룹화 준비
        # 구조: {날짜: {작업유형: [로그들]}}
        grouped_data = defaultdict(lambda: defaultdict(list))
        
        for row in data:
            if len(row) >= 6 and row[0]:
                datetime_str = row[0].strip()
                row_year = None
                row_month = None
                row_day = None
                
                # 다양한 날짜 형식 파싱
                try:
                    # YYYY-MM-DD HH:MM:SS
                    dt = datetime.strptime(datetime_str.split()[0], "%Y-%m-%d")
                    row_year = dt.year
                    row_month = dt.month
                    row_day = dt.day
                except:
                    try:
                        # M/D/YYYY 또는 MM/DD/YYYY
                        parts = datetime_str.split()[0].split('/')
                        if len(parts) == 3:
                            row_month = int(parts[0])
                            row_day = int(parts[1])
                            row_year = int(parts[2])
                    except:
                        pass
                
                if row_year == year and row_month == month:
                    # 날짜 키 생성 (YYYY-MM-DD)
                    date_key = f"{row_year:04d}-{row_month:02d}-{row_day:02d}"
                    work_type = row[1].strip()
                    account = row[2].strip()
                    count = int(row[3]) if row[3].isdigit() else 0
                    detail = row[4].strip()
                    method = row[5].strip()
                    
                    # 그룹에 추가
                    grouped_data[date_key][work_type].append({
                        "datetime": datetime_str,
                        "account": account,
                        "count": count,
                        "detail": detail,
                        "method": method
                    })
        
        # 그룹화된 데이터를 최종 형식으로 변환
        month_data = []
        for date_key, work_types in grouped_data.items():
            for work_type, logs in work_types.items():
                # 계정 목록 및 총 개수 계산
                accounts = [log["account"] for log in logs]
                total_count = sum(log["count"] for log in logs)
                
                month_data.append({
                    "datetime": f"{date_key} 00:00:00",  # 날짜만 사용
                    "work_type": work_type,
                    "account": f"{len(accounts)}개 스토어",  # "2개 스토어" 형식
                    "count": total_count,
                    "detail": f"{', '.join(accounts[:3])}{'...' if len(accounts) > 3 else ''}",  # 처음 3개만 표시
                    "method": logs[0]["method"] if logs else "",
                    "store_count": len(accounts)  # 프론트엔드에서 사용할 수 있도록
                })
        
        print(f"[월별 조회] {year}년 {month}월: {len(month_data)}개 그룹")
        return {"logs": month_data}
        
    except Exception as e:
        print(f"[작업로그 조회 오류] {e}")
        import traceback
        traceback.print_exc()
        return {"logs": []}

@app.get("/api/work-log/day")
async def get_work_day(request: Request, date: str):
    """특정 날짜 작업 로그 조회"""
    get_current_user(request)
    
    print(f"[디버그] 조회 요청 날짜: {date}")
    
    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        wb = gc.open_by_key(SPREADSHEET_KEY)
        ws = wb.worksheet(WORK_LOG_SHEET)
        
        data = ws.get_all_values()[1:]
        print(f"[디버그] 전체 로그 수: {len(data)}개")
        
        # 날짜 파싱 (YYYY-MM-DD)
        from datetime import datetime
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
            print(f"[디버그] 파싱된 날짜: {target_date}")
        except:
            print(f"[디버그] 날짜 파싱 실패: {date}")
            return {"logs": []}
        
        day_data = []
        for row in data:
            if len(row) >= 6 and row[0]:
                # 다양한 날짜 형식 시도
                row_date = None
                datetime_str = row[0].strip()
                
                # 시도1: YYYY-MM-DD HH:MM:SS
                try:
                    row_date = datetime.strptime(datetime_str.split()[0], "%Y-%m-%d").date()
                except:
                    pass
                
                # 시도2: MM/DD/YYYY 또는 M/D/YYYY
                if not row_date:
                    try:
                        # "1/2/2026" 형식
                        parts = datetime_str.split()[0].split('/')
                        if len(parts) == 3:
                            row_date = datetime(int(parts[2]), int(parts[0]), int(parts[1])).date()
                    except:
                        pass
                
                # 시도3: DD/MM/YYYY
                if not row_date:
                    try:
                        parts = datetime_str.split()[0].split('/')
                        if len(parts) == 3:
                            row_date = datetime(int(parts[2]), int(parts[1]), int(parts[0])).date()
                    except:
                        pass
                
                print(f"[디버그] '{datetime_str}' → {row_date} vs {target_date} → 일치={row_date == target_date if row_date else False}")
                
                if row_date == target_date:
                    # datetime을 YYYY-MM-DD HH:MM:SS 형식으로 표준화
                    normalized_datetime = datetime_str
                    try:
                        if '-' in datetime_str.split()[0]:
                            normalized_datetime = datetime_str  # 이미 표준 형식
                        elif '/' in datetime_str.split()[0]:
                            parts = datetime_str.split()
                            date_parts = parts[0].split('/')
                            if len(date_parts) == 3:
                                m, d, y = int(date_parts[0]), int(date_parts[1]), int(date_parts[2])
                                time_part = parts[1] if len(parts) > 1 else "00:00:00"
                                normalized_datetime = f"{y:04d}-{m:02d}-{d:02d} {time_part}"
                    except:
                        pass
                    
                    day_data.append({
                        "datetime": normalized_datetime,
                        "work_type": row[1],
                        "account": row[2],
                        "count": int(row[3]) if row[3].isdigit() else 0,
                        "detail": row[4],
                        "method": row[5]
                    })
        
        print(f"[디버그] 찾은 작업: {len(day_data)}개")
        return {"logs": day_data}
        
    except Exception as e:
        print(f"[일별 로그 조회 오류] {e}")
        import traceback
        traceback.print_exc()
        return {"logs": []}

@app.get("/api/work-log/stats")
async def get_work_stats(request: Request, year: int, month: int):
    """월간 통계"""
    get_current_user(request)
    
    try:
        from datetime import datetime
        
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        wb = gc.open_by_key(SPREADSHEET_KEY)
        ws = wb.worksheet(WORK_LOG_SHEET)
        
        data = ws.get_all_values()[1:]
        
        stats = {
            "total_works": 0,
            "deleted_products": 0,
            "uploaded_products": 0,
            "processed_accounts": set()
        }
        
        for row in data:
            if len(row) >= 6 and row[0]:
                datetime_str = row[0].strip()
                row_year = None
                row_month = None
                
                # 날짜 파싱
                try:
                    # YYYY-MM-DD HH:MM:SS
                    dt = datetime.strptime(datetime_str.split()[0], "%Y-%m-%d")
                    row_year = dt.year
                    row_month = dt.month
                except:
                    try:
                        # M/D/YYYY
                        parts = datetime_str.split()[0].split('/')
                        if len(parts) == 3:
                            row_month = int(parts[0])
                            row_year = int(parts[2])
                    except:
                        pass
                
                if row_year == year and row_month == month:
                    stats["total_works"] += 1
                    count = int(row[3]) if row[3].isdigit() else 0
                    
                    if row[1] == "상품삭제":
                        stats["deleted_products"] += count
                    elif row[1] == "상품등록":
                        stats["uploaded_products"] += count
                    
                    if row[2]:
                        stats["processed_accounts"].add(row[2])
        
        stats["processed_accounts"] = len(stats["processed_accounts"])
        
        print(f"[통계] {year}년 {month}월: 작업 {stats['total_works']}개")
        return stats
        
    except Exception as e:
        print(f"[통계 조회 오류] {e}")
        return {
            "total_works": 0,
            "deleted_products": 0,
            "uploaded_products": 0,
            "processed_accounts": 0
        }

class WorkLogUpdateRequest(BaseModel):
    datetime: str  # 원본 일시 (고유 식별자)
    work_type: str = None
    account: str = None
    count: int = None
    detail: str = None
    method: str = None
    new_datetime: str = None  # 날짜/시간 변경 시

@app.put("/api/work-log/update")
async def update_work_log(request: Request, req: WorkLogUpdateRequest):
    """작업 로그 수정"""
    get_current_user(request)
    
    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        wb = gc.open_by_key(SPREADSHEET_KEY)
        ws = wb.worksheet(WORK_LOG_SHEET)
        
        # 모든 데이터 가져오기
        all_data = ws.get_all_values()
        
        # 원본 일시로 행 찾기
        row_index = None
        for i, row in enumerate(all_data):
            if i == 0:  # 헤더 스킵
                continue
            if row[0] == req.datetime:
                row_index = i + 1  # gspread는 1-indexed
                break
        
        if row_index is None:
            return {"success": False, "message": "작업을 찾을 수 없습니다"}
        
        # 현재 값 가져오기
        current = all_data[row_index - 1]
        
        # 업데이트할 값 준비
        new_datetime = req.new_datetime if req.new_datetime else current[0]
        new_work_type = req.work_type if req.work_type is not None else current[1]
        new_account = req.account if req.account is not None else current[2]
        new_count = req.count if req.count is not None else current[3]
        new_detail = req.detail if req.detail is not None else current[4]
        new_method = req.method if req.method is not None else current[5]
        
        # 행 업데이트
        ws.update(values=[[new_datetime, new_work_type, new_account, str(new_count), new_detail, new_method]], range_name=f'A{row_index}:F{row_index}')
        
        print(f"[작업로그 수정] {req.datetime} → {new_datetime}")
        return {"success": True}
        
    except Exception as e:
        print(f"[작업로그 수정 오류] {e}")
        return {"success": False, "message": str(e)}

class WorkLogDeleteRequest(BaseModel):
    datetime: str  # 일시 (고유 식별자)

@app.delete("/api/work-log/delete")
async def delete_work_log(request: Request, req: WorkLogDeleteRequest):
    """작업 로그 삭제"""
    get_current_user(request)
    
    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        wb = gc.open_by_key(SPREADSHEET_KEY)
        ws = wb.worksheet(WORK_LOG_SHEET)
        
        # 모든 데이터 가져오기
        all_data = ws.get_all_values()
        
        # 원본 일시로 행 찾기
        row_index = None
        for i, row in enumerate(all_data):
            if i == 0:  # 헤더 스킵
                continue
            if row[0] == req.datetime:
                row_index = i + 1  # gspread는 1-indexed
                break
        
        if row_index is None:
            return {"success": False, "message": "작업을 찾을 수 없습니다"}
        
        # 행 삭제
        ws.delete_rows(row_index)
        
        print(f"[작업로그 삭제] {req.datetime}")
        return {"success": True}
        
    except Exception as e:
        print(f"[작업로그 삭제 오류] {e}")
        return {"success": False, "message": str(e)}

@app.get("/api/bulsaja/folder")
async def get_bulsaja_folder(request: Request):
    get_current_user(request)
    return {"folder": bulsaja_manager.get_folder()}

# 불사자 시트 설정 API
class BulsajaSettingsRequest(BaseModel):
    program: str
    # 상품업로드용
    uploadMarket: str = ""
    uploadCount: str = ""
    # 상품삭제용 (C29는 실행 시 그룹별로 변경)
    deleteCount: str = ""
    # 상품복사용 (C35는 실행 시 그룹별로 변경)
    copySourceMarket: str = ""
    copyCount: str = ""

@app.post("/api/bulsaja/settings")
async def save_bulsaja_settings(request: Request, req: BulsajaSettingsRequest):
    """불사자 구글시트 설정 저장"""
    get_current_user(request)
    
    try:
        from dotenv import dotenv_values
        
        # 자동화시스템 폴더의 .env 읽기
        env_path = Path(bulsaja_manager.base_folder) / ".env"
        if env_path.exists():
            env_config = dotenv_values(env_path)
            creds_file = env_config.get("SERVICE_ACCOUNT_JSON", CREDENTIALS_FILE)
            sheet_key = env_config.get("SPREADSHEET_KEY", BULSAJA_SHEET_KEY)
        else:
            creds_file = CREDENTIALS_FILE
            sheet_key = BULSAJA_SHEET_KEY
        
        # 상대경로면 base_folder 기준으로 변환
        creds_path = Path(creds_file)
        if not creds_path.is_absolute():
            creds_path = Path(bulsaja_manager.base_folder) / creds_file
        
        # 불사자 시트 열기
        creds = Credentials.from_service_account_file(
            str(creds_path),
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)
        ws = gc.open_by_key(sheet_key).worksheet(BULSAJA_TAB_NAME)
        
        # C10: 사용할프로그램
        ws.update_acell("C10", req.program)
        
        # 프로그램별 설정
        if req.program == "2. 상품업로드":
            # C17: 업로드마켓설정, C18: 업로드수
            if req.uploadMarket:
                ws.update_acell("C17", req.uploadMarket)
            if req.uploadCount:
                ws.update_acell("C18", req.uploadCount)
                
        elif req.program == "4. 상품삭제":
            # C32: 삭제수량만 (C29는 실행 시 그룹별로 변경)
            if req.deleteCount:
                ws.update_acell("C32", req.deleteCount)
                
        elif req.program == "4-3. 불사자상품복사":
            # C29: 소스마켓, C37: 복사수량 (C35는 실행 시 그룹별로 변경)
            if req.copySourceMarket:
                ws.update_acell("C29", req.copySourceMarket)
            if req.copyCount:
                ws.update_acell("C37", req.copyCount)
        
        return {"success": True}
    except Exception as e:
        print(f"[불사자] 시트 설정 저장 오류: {e}")
        return {"success": False, "message": str(e)}

@app.get("/api/bulsaja/settings")
async def get_bulsaja_settings(request: Request):
    """불사자 구글시트 설정 조회"""
    get_current_user(request)
    
    try:
        from dotenv import dotenv_values
        
        # 자동화시스템 폴더의 .env 읽기
        env_path = Path(bulsaja_manager.base_folder) / ".env"
        if env_path.exists():
            env_config = dotenv_values(env_path)
            creds_file = env_config.get("SERVICE_ACCOUNT_JSON", CREDENTIALS_FILE)
            sheet_key = env_config.get("SPREADSHEET_KEY", BULSAJA_SHEET_KEY)
        else:
            creds_file = CREDENTIALS_FILE
            sheet_key = BULSAJA_SHEET_KEY
        
        # 상대경로면 base_folder 기준으로 변환
        creds_path = Path(creds_file)
        if not creds_path.is_absolute():
            creds_path = Path(bulsaja_manager.base_folder) / creds_file
        
        # 불사자 시트 열기
        creds = Credentials.from_service_account_file(
            str(creds_path),
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)
        ws = gc.open_by_key(sheet_key).worksheet(BULSAJA_TAB_NAME)
        
        # 기본 설정값 읽기
        program = ws.acell("C10").value or ""
        # 상품업로드용
        uploadMarket = ws.acell("C17").value or ""
        uploadCount = ws.acell("C18").value or ""
        # 상품삭제용 (C32: 수량)
        deleteCount = ws.acell("C32").value or ""
        # 상품복사용 (C29: 소스마켓, C37: 수량)
        copySourceMarket = ws.acell("C29").value or ""
        copyCount = ws.acell("C37").value or ""
        
        # ========== 추가 설정값 (표시용) ==========
        # 마진설정 (행 9~11)
        margin = {
            "exchangeRate": ws.acell("E9").value or "",       # 기준 환율(위안)
            "cardFee": ws.acell("E10").value or "",           # 카드수수료(%)
            "marketDiscount": ws.acell("E11").value or "",    # 마켓 할인율(%)
            "priceRounding": ws.acell("G9").value or "",      # 가격단위올림(원)
            "percentMargin": ws.acell("G10").value or "",     # 퍼센트마진(%)
            "addMargin": ws.acell("G11").value or ""          # 더하기 마진(원)
        }
        
        # 상품업로드 설정 (행 15~25)
        upload = {
            "productName": ws.acell("C19").value or "",       # 상품명
            "uploadCount": uploadCount,                        # 업로드수 (C18)
            "optionSort": ws.acell("C21").value or "",        # 옵션설정
            "uploadCondition": ws.acell("C23").value or "",   # 업로드조건
            "minPrice": ws.acell("C24").value or "",          # 옵션 최저 가격
            "maxPrice": ws.acell("C25").value or ""           # 옵션 최대 가격
        }
        
        # 상품삭제/복사 설정 (행 29~38)
        deleteCopy = {
            "deleteScope": ws.acell("C31").value or "",       # 상품삭제설정 (업로드한 마켓에서만)
            "deleteOrder": ws.acell("C33").value or "",       # 삭제방식 (과거순)
            "baseMarket": ws.acell("C34").value or "",        # 기준마켓설정 (스마트스토어)
            "copyCondition": ws.acell("C38").value or ""      # 복사조건 (전체상품복사)
        }
        
        return {
            "success": True,
            "program": program,
            "uploadMarket": uploadMarket,
            "uploadCount": uploadCount,
            "deleteCount": deleteCount,
            "copySourceMarket": copySourceMarket,
            "copyCount": copyCount,
            # 추가 설정 (표시용)
            "margin": margin,
            "upload": upload,
            "deleteCopy": deleteCopy
        }
    except Exception as e:
        print(f"[불사자] 시트 설정 조회 오류: {e}")
        return {"success": False, "message": str(e)}

# ========== 탭 권한 설정 API ==========

TAB_PERMISSIONS_FILE = APP_DIR / "tab_permissions.json"

@app.get("/api/settings/tab-permissions")
async def get_tab_permissions(request: Request):
    """운영자 탭 권한 설정 조회 (관리자 전용)"""
    user = get_current_user(request)
    if user.get("role") not in ("admin", "관리자"):
        raise HTTPException(status_code=403, detail="관리자만 접근 가능합니다")
    
    try:
        if TAB_PERMISSIONS_FILE.exists():
            with open(TAB_PERMISSIONS_FILE, 'r', encoding='utf-8') as f:
                permissions = json.load(f)
        else:
            # 기본값: 모든 탭 허용
            permissions = {
                "accounts": True,
                "sms": True,
                "monitor": True,
                "aio": True,
                "bulsaja": True,
                "tools": True,
                "marketing": True,
                "calendar": True
            }

        return {"success": True, "permissions": permissions}
    except Exception as e:
        print(f"[탭 권한 조회 오류] {e}")
        return {"success": False, "message": str(e)}

@app.post("/api/settings/tab-permissions")
async def save_tab_permissions(request: Request):
    """운영자 탭 권한 설정 저장 (관리자 전용)"""
    user = get_current_user(request)
    print(f"[탭 권한 저장 시도] user={user}, role={user.get('role')}")
    
    if user.get("role") not in ("admin", "관리자"):
        print(f"[탭 권한 저장 거부] role '{user.get('role')}'는 admin/관리자가 아님")
        raise HTTPException(status_code=403, detail="관리자만 접근 가능합니다")
    
    try:
        data = await request.json()
        
        # JSON 파일로 저장
        with open(TAB_PERMISSIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"[탭 권한 설정 저장] {data}")
        return {"success": True}
    except Exception as e:
        print(f"[탭 권한 저장 오류] {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "message": str(e)}

# ========== All-in-One API ==========
import bcrypt
import base64

class AioRunRequest(BaseModel):
    platform: str
    task: str
    options: dict = {}  # 작업 옵션 (mode, count, date, delete_count 등)
    stores: List[str] = []  # 선택된 스토어 목록

class AioUpdateActiveRequest(BaseModel):
    platform: str
    task: str
    active_stores: List[str]
    all_stores: List[str]

# 올인원 상태 저장
def create_aio_status():
    return {
        "running": False,
        "progress": 0,
        "status": "idle",  # idle, running, completed, stopped
        "results": [],
        "process": None,
        "options": {},  # 현재 실행 옵션
        "current_store": "",  # 현재 처리 중인 스토어
        "current_action": "",  # 현재 작업 내용
        "total": 0,  # 전체 스토어 수
        "completed": 0,  # 완료된 스토어 수
        "logs": [],  # 실시간 로그 (최근 50개)
        "log_file": None,
        "log_pos": 0
    }

# 플랫폼별 상태 관리
aio_status_by_platform = {
    "스마트스토어": create_aio_status(),
    "11번가": create_aio_status(),
    "쿠팡": create_aio_status(),
    "ESM": create_aio_status(),
}

# 기존 호환성을 위한 기본 상태 (플랫폼 미지정시 사용)
aio_status = create_aio_status()

def get_aio_status(platform: str = None):
    """플랫폼별 상태 반환"""
    if platform and platform in aio_status_by_platform:
        return aio_status_by_platform[platform]
    return aio_status

# 스마트스토어 API 인증
def ss_sign_client_secret(client_id: str, client_secret: str, ts_ms: int) -> str:
    pwd = f"{client_id}_{ts_ms}".encode("utf-8")
    hashed = bcrypt.hashpw(pwd, client_secret.strip().encode("utf-8"))
    return base64.b64encode(hashed).decode("utf-8")

def ss_get_access_token(client_id: str, client_secret: str) -> str:
    ts = int(time.time() * 1000)
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "timestamp": ts,
        "client_secret_sign": ss_sign_client_secret(client_id, client_secret, ts),
        "type": "SELF",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    r = requests.post("https://api.commerce.naver.com/external/v1/oauth2/token", data=data, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

# 스마트스토어 상품 수량 조회 (상세)
def ss_get_product_count(access_token: str) -> Dict[str, int]:
    headers = {
        "Authorization": f"Bearer {access_token}", 
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    def total_elements(body: dict) -> int:
        base = {"page": 1, "size": 1}
        base.update(body)
        r = requests.post("https://api.commerce.naver.com/external/v1/products/search", 
                          headers=headers, json=base, timeout=30)
        r.raise_for_status()
        data = r.json()
        return int(data.get("totalElements") or data.get("total") or 0)
    
    def count_by_status(status_code: str) -> int:
        return total_elements({"productStatusTypes": [status_code]})
    
    total_all = total_elements({})
    on_sale = count_by_status("SALE")
    stop_selling = count_by_status("SUSPENSION")
    approval_wait = count_by_status("WAIT")
    
    return {
        "전체": total_all,
        "판매중": on_sale,
        "판매중지": stop_selling,
        "승인대기": approval_wait
    }

# 스마트스토어 마지막 등록일 조회
def ss_get_last_registration_date(access_token: str) -> str:
    """판매중 상품 중 가장 최근 등록일 조회"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    try:
        # 판매중 상품을 등록일 최신순으로 1개만 조회
        body = {
            "page": 1,
            "size": 1,
            "productStatusTypes": ["SALE"],
            "sortType": "RECENTLY_REGISTERED"  # 최근 등록순
        }

        r = requests.post(
            "https://api.commerce.naver.com/external/v1/products/search",
            headers=headers,
            json=body,
            timeout=30
        )
        r.raise_for_status()
        data = r.json()

        contents = data.get("contents", [])
        if contents and len(contents) > 0:
            product = contents[0]
            # 등록일 필드: regDate 또는 createdDate
            reg_date = product.get("regDate") or product.get("createdDate") or product.get("registrationDate")
            if reg_date:
                # ISO format을 YYYY-MM-DD로 변환
                if "T" in str(reg_date):
                    return str(reg_date).split("T")[0]
                return str(reg_date)[:10]

        return ""
    except Exception as e:
        print(f"[스마트스토어] 마지막 등록일 조회 오류: {e}")
        return ""

# 상품수량 구글시트 기록
def ss_save_product_count_to_sheet(store_name: str, counts: Dict[str, int], last_reg_date: str = ""):
    """상품수량을 구글시트 '등록갯수' 탭에 기록 (마지막등록일 포함)"""
    SHEET_NAME = "등록갯수"
    HEADERS = ["스토어명", "전체", "판매중", "판매중지", "승인대기", "마지막등록일", "updated_at"]

    try:
        # 시트 가져오기 또는 생성
        try:
            ws = gsheet.sheet.worksheet(SHEET_NAME)
        except:
            ws = gsheet.sheet.add_worksheet(title=SHEET_NAME, rows=200, cols=len(HEADERS))
            ws.update(range_name="1:1", values=[HEADERS], value_input_option="RAW")

        # 헤더 확인 및 마지막등록일 컬럼 추가
        all_vals = ws.get_all_values() or []
        if not all_vals:
            ws.update(range_name="1:1", values=[HEADERS], value_input_option="RAW")
            all_vals = [HEADERS]

        headers = [h.strip() for h in all_vals[0]] if all_vals else HEADERS

        # 마지막등록일 컬럼이 없으면 추가
        if "마지막등록일" not in headers:
            # updated_at 앞에 추가
            try:
                updated_idx = headers.index("updated_at")
                headers.insert(updated_idx, "마지막등록일")
            except ValueError:
                headers.append("마지막등록일")
            ws.update(range_name="1:1", values=[headers], value_input_option="RAW")
            print(f"[등록갯수] 마지막등록일 컬럼 추가됨")

        # store_name/스토어명 열 인덱스
        store_col_idx = 0
        for i, h in enumerate(headers):
            if h in ["store_name", "스토어명"]:
                store_col_idx = i
                break

        # 기존 행 찾기
        row_map = {}
        for i, row in enumerate(all_vals[1:], start=2):
            if len(row) > store_col_idx and row[store_col_idx]:
                row_map[row[store_col_idx]] = i

        # 데이터 준비
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row_values = {
            "스토어명": store_name,
            "store_name": store_name,
            "전체": counts.get("전체", 0),
            "판매중": counts.get("판매중", 0),
            "판매중지": counts.get("판매중지", 0),
            "승인대기": counts.get("승인대기", 0),
            "마지막등록일": last_reg_date,
            "updated_at": now_str
        }
        row_to_write = [row_values.get(h, "") for h in headers]

        # 기존 행 업데이트 또는 새 행 추가
        target_row = row_map.get(store_name)
        if target_row is None:
            ws.append_row(row_to_write, value_input_option="RAW")
        else:
            def col_letter(n):
                result = ""
                while n > 0:
                    n, remainder = divmod(n - 1, 26)
                    result = chr(65 + remainder) + result
                return result

            end_col = col_letter(len(headers))
            rng = f"A{target_row}:{end_col}{target_row}"
            ws.update(range_name=rng, values=[row_to_write], value_input_option="RAW")

        print(f"[등록갯수] {store_name} 시트 기록 완료 (마지막등록일: {last_reg_date})")
        return True
    except Exception as e:
        print(f"[등록갯수] {store_name} 시트 기록 오류: {e}")
        return False

@app.get("/api/allinone/stores")
async def get_allinone_stores(request: Request, platform: str, task: str):
    """작업별 스토어 목록 조회 - 상품수 정보 포함"""
    require_permission(request, "edit")
    
    # 작업-탭 매핑 (각 작업별 시트 사용)
    task_to_sheet = {
        # 스마트스토어 - 각 작업별 시트
        "등록갯수": "stores",
        "배송코드": "stores",
        "배송변경": "배송변경",
        "상품삭제": "상품삭제",
        "혜택설정": "혜택설정",
        "중복삭제": "중복삭제",
        "KC인증": "KC인증",
        "기타기능": "기타기능",
        "매출조회": "stores",
        # 11번가
        "판매중지": "11번가",
        "판매재개": "11번가",
        "11st매출": "11번가"
    }
    
    # 11번가 플랫폼은 11번가 시트 사용
    if platform == "11번가":
        sheet_name = "11번가"
    else:
        sheet_name = task_to_sheet.get(task, "stores")
    
    try:
        # 계정목록 탭에서 소유자/용도 정보 로드 (플랫폼별로 구분)
        # 계정목록의 쇼핑몰 별칭에서 언더바 앞부분 제거 후 매칭
        account_info = {}
        try:
            ws_accounts = gsheet.sheet.worksheet("계정목록")
            acc_data = ws_accounts.get_all_values()
            if acc_data and len(acc_data) > 1:
                acc_headers = acc_data[0]
                acc_name_idx = None
                owner_idx = None
                usage_idx = None
                platform_idx = None
                
                for i, h in enumerate(acc_headers):
                    if h in ["쇼핑몰 별칭", "계정명", "account_name", "스토어명", "shop_alias"]:
                        acc_name_idx = i
                    elif h in ["소유자", "owner"]:
                        owner_idx = i
                    elif h in ["용도", "usage"]:
                        usage_idx = i
                    elif h in ["플랫폼", "platform"]:
                        platform_idx = i
                
                print(f"[올인원] 계정목록 헤더: acc_name_idx={acc_name_idx}, owner_idx={owner_idx}, usage_idx={usage_idx}, platform_idx={platform_idx}")
                
                if acc_name_idx is not None and platform_idx is not None:
                    for row in acc_data[1:]:
                        if len(row) > acc_name_idx and len(row) > platform_idx:
                            acc_name_raw = row[acc_name_idx].strip()
                            acc_platform = row[platform_idx].strip()
                            
                            # 플랫폼 매칭 (스마트스토어/11번가 등)
                            platform_match = False
                            if platform == "스마트스토어" and ("스마트" in acc_platform or "네이버" in acc_platform):
                                platform_match = True
                            elif platform == "11번가" and "11" in acc_platform:
                                platform_match = True
                            elif platform == acc_platform:
                                platform_match = True
                            
                            if acc_name_raw and platform_match:
                                owner = row[owner_idx].strip() if owner_idx is not None and len(row) > owner_idx else ""
                                usage = row[usage_idx].strip() if usage_idx is not None and len(row) > usage_idx else ""
                                
                                # 쇼핑몰 별칭에서 언더바 있으면 앞부분 제거 (01_푸로테카 -> 푸로테카)
                                if "_" in acc_name_raw:
                                    match_name = acc_name_raw.split("_", 1)[1]
                                else:
                                    match_name = acc_name_raw
                                
                                account_info[match_name] = {"owner": owner, "usage": usage}
                                        
                    print(f"[올인원] 계정목록 로드 완료 ({platform}): {len(account_info)}개, 예시: {list(account_info.items())[:5]}")
        except Exception as e:
            print(f"[올인원] 계정목록 시트 로드 오류: {e}")
        
        # 배송코드 시트 데이터 로드 (출고지 코드)
        shipping_codes = {}
        if task in ["배송코드", "배송변경"]:
            try:
                ws_shipping = gsheet.sheet.worksheet("배송코드")
                ship_data = ws_shipping.get_all_values()
                if ship_data and len(ship_data) > 1:
                    ship_headers = ship_data[0]
                    ship_cols = {h: i for i, h in enumerate(ship_headers)}
                    
                    for row in ship_data[1:]:
                        store = row[ship_cols.get("스토어명", 0)].strip() if len(row) > ship_cols.get("스토어명", 0) else ""
                        if store:
                            shipping_codes[store] = {
                                "국내출고지": row[ship_cols["국내출고지"]] if "국내출고지" in ship_cols and len(row) > ship_cols["국내출고지"] else "",
                                "해외출고지": row[ship_cols["해외출고지"]] if "해외출고지" in ship_cols and len(row) > ship_cols["해외출고지"] else "",
                                "반품지": row[ship_cols["반품지"]] if "반품지" in ship_cols and len(row) > ship_cols["반품지"] else "",
                                "updated_at": row[ship_cols["updated_at"]] if "updated_at" in ship_cols and len(row) > ship_cols["updated_at"] else ""
                            }
                    print(f"[올인원] 배송코드 시트 로드: {len(shipping_codes)}개")
            except Exception as e:
                print(f"[올인원] 배송코드 시트 로드 오류: {e}")
        
        # 배송변경 시트 데이터 로드
        delivery_info = {}
        if task == "배송변경":
            try:
                ws_delivery = gsheet.sheet.worksheet("배송변경")
                del_data = ws_delivery.get_all_values()
                if del_data and len(del_data) > 1:
                    del_headers = del_data[0]
                    del_cols = {h: i for i, h in enumerate(del_headers)}
                    
                    # 스토어명 컬럼 찾기 (한글/영어 둘 다 지원)
                    store_name_idx = None
                    for i, h in enumerate(del_headers):
                        if h in ["스토어명", "store_name", "계정명"]:
                            store_name_idx = i
                            break
                    if store_name_idx is None:
                        store_name_idx = 1  # fallback
                    
                    for row in del_data[1:]:
                        store = row[store_name_idx].strip() if len(row) > store_name_idx else ""
                        if store:
                            delivery_info[store] = {
                                "target_limit": row[del_cols["target_limit"]] if "target_limit" in del_cols and len(row) > del_cols["target_limit"] else "",
                                "shippingAddressId": row[del_cols["shippingAddressId"]] if "shippingAddressId" in del_cols and len(row) > del_cols["shippingAddressId"] else "",
                                "differentialFeeByArea": row[del_cols["differentialFeeByArea"]] if "differentialFeeByArea" in del_cols and len(row) > del_cols["differentialFeeByArea"] else "",
                                "cutofftime": row[del_cols["cutofftime"]] if "cutofftime" in del_cols and len(row) > del_cols["cutofftime"] else "",
                                "updated_at": row[del_cols["updated_at"]] if "updated_at" in del_cols and len(row) > del_cols["updated_at"] else ""
                            }
                    print(f"[올인원] 배송변경 시트 로드: {len(delivery_info)}개")
            except Exception as e:
                print(f"[올인원] 배송변경 시트 로드 오류: {e}")
        
        # 혜택설정 시트 데이터 로드
        benefit_info = {}
        if task == "혜택설정":
            try:
                ws_benefit = gsheet.sheet.worksheet("혜택설정")
                ben_data = ws_benefit.get_all_values()
                if ben_data and len(ben_data) > 1:
                    ben_headers = ben_data[0]
                    ben_cols = {h: i for i, h in enumerate(ben_headers)}
                    
                    # 스토어명 컬럼 찾기 (한글/영어 둘 다 지원)
                    store_name_idx = None
                    for i, h in enumerate(ben_headers):
                        if h in ["스토어명", "store_name", "계정명"]:
                            store_name_idx = i
                            break
                    if store_name_idx is None:
                        store_name_idx = 0  # fallback
                    
                    for row in ben_data[1:]:
                        store = row[store_name_idx].strip() if len(row) > store_name_idx else ""
                        if store:
                            benefit_info[store] = {
                                "후기포인트": row[ben_cols["후기포인트"]] if "후기포인트" in ben_cols and len(row) > ben_cols["후기포인트"] else "",
                                "포토후기포인트": row[ben_cols["포토후기포인트"]] if "포토후기포인트" in ben_cols and len(row) > ben_cols["포토후기포인트"] else "",
                                "한달후기포인트": row[ben_cols["한달후기포인트"]] if "한달후기포인트" in ben_cols and len(row) > ben_cols["한달후기포인트"] else "",
                                "한달포토후기포인트": row[ben_cols["한달포토후기포인트"]] if "한달포토후기포인트" in ben_cols and len(row) > ben_cols["한달포토후기포인트"] else "",
                                "이벤트문구": row[ben_cols["이벤트문구"]] if "이벤트문구" in ben_cols and len(row) > ben_cols["이벤트문구"] else "",
                                "사은품": row[ben_cols["사은품"]] if "사은품" in ben_cols and len(row) > ben_cols["사은품"] else "",
                                "최소판매가": row[ben_cols["최소판매가"]] if "최소판매가" in ben_cols and len(row) > ben_cols["최소판매가"] else "",
                                "복수구매": row[ben_cols["복수구매"]] if "복수구매" in ben_cols and len(row) > ben_cols["복수구매"] else "",
                                "복수구매할인": row[ben_cols["복수구매할인"]] if "복수구매할인" in ben_cols and len(row) > ben_cols["복수구매할인"] else "",
                                "결과": row[ben_cols["결과"]] if "결과" in ben_cols and len(row) > ben_cols["결과"] else "",
                                "updated_at": row[ben_cols["updated_at"]] if "updated_at" in ben_cols and len(row) > ben_cols["updated_at"] else ""
                            }
                    print(f"[올인원] 혜택설정 시트 로드: {len(benefit_info)}개")
            except Exception as e:
                print(f"[올인원] 혜택설정 시트 로드 오류: {e}")
        
        # 등록갯수 시트에서 상품수 정보 로드
        product_counts = {}
        store_order = []  # 구글시트 순서 유지
        try:
            ws_counts = gsheet.sheet.worksheet("등록갯수")
            counts_data = ws_counts.get_all_values()
            if counts_data and len(counts_data) > 1:
                headers = counts_data[0]
                name_idx = None
                total_idx = None
                on_sale_idx = None
                suspended_idx = None
                pending_idx = None  # 승인대기
                updated_idx = None
                
                for i, h in enumerate(headers):
                    if h == "스토어명":
                        name_idx = i
                    elif h == "전체":
                        total_idx = i
                    elif h == "판매중":
                        on_sale_idx = i
                    elif h == "판매중지":
                        suspended_idx = i
                    elif h == "승인대기":
                        pending_idx = i
                    elif h == "updated_at":
                        updated_idx = i
                
                if name_idx is not None:
                    for row_idx, row in enumerate(counts_data[1:], start=1):
                        if len(row) > name_idx:
                            store = row[name_idx].strip()
                            if store:
                                store_order.append(store)
                                product_counts[store] = {
                                    "row_num": row_idx,
                                    "total": int(row[total_idx]) if total_idx and len(row) > total_idx and row[total_idx].isdigit() else 0,
                                    "on_sale": int(row[on_sale_idx]) if on_sale_idx and len(row) > on_sale_idx and row[on_sale_idx].isdigit() else 0,
                                    "suspended": int(row[suspended_idx]) if suspended_idx and len(row) > suspended_idx and row[suspended_idx].isdigit() else 0,
                                    "pending": int(row[pending_idx]) if pending_idx and len(row) > pending_idx and row[pending_idx].isdigit() else 0,
                                    "updated_at": row[updated_idx] if updated_idx and len(row) > updated_idx else ""
                                }
        except Exception as e:
            print(f"[올인원] 등록갯수 시트 로드 오류: {e}")
        
        # 11번가도 같은 스프레드시트, 탭만 다름
        if sheet_name == "11번가":
            ws = gsheet.sheet.worksheet("11번가")
            
            all_values = ws.get_all_values()
            
            if not all_values or len(all_values) < 2:
                return {"stores": []}
            
            headers = all_values[0]
            print(f"[올인원] 11번가 헤더: {headers[:15]}")
            
            # 컬럼 인덱스 찾기
            col_idx = {}
            for i, h in enumerate(headers):
                if h in ["store_name", "쇼핑몰 별칭", "스토어명"]:
                    col_idx["스토어명"] = i
                elif h in ["active", "활성", "사용"]:
                    col_idx["active"] = i
                elif h == "전체":
                    col_idx["total"] = i
                elif h == "판매중":
                    col_idx["on_sale"] = i
                elif h == "판매중지":
                    col_idx["suspended"] = i
                elif h == "승인대기":
                    col_idx["pending"] = i
                elif h == "updated_at":
                    col_idx["updated_at"] = i
            
            # active 열이 없으면 첫 번째 열
            if "active" not in col_idx:
                col_idx["active"] = 0
            
            if "스토어명" not in col_idx:
                print(f"[올인원] 스토어명 열을 찾을 수 없음")
                return {"stores": [], "error": "스토어명 열 없음"}
            
            stores = []
            for row_idx, row in enumerate(all_values[1:], start=1):
                if len(row) <= col_idx["스토어명"]:
                    continue
                
                store_name = row[col_idx["스토어명"]].strip() if len(row) > col_idx["스토어명"] else ""
                active = row[col_idx["active"]].strip() if len(row) > col_idx["active"] else ""
                
                if not store_name:
                    continue
                
                is_active = str(active).upper() in ["TRUE", "ON", "Y", "1", "사용"]
                
                # 11번가 시트에서 직접 수량 읽기
                def get_int(key):
                    if key in col_idx and len(row) > col_idx[key]:
                        val = row[col_idx[key]]
                        return int(val) if val.isdigit() else 0
                    return 0
                
                # 계정목록에서 소유자/용도 매칭
                # store_name에서 언더바 앞부분 제거 후 매칭 (01_루미켓1 -> 루미켓1)
                match_name = store_name
                if "_" in store_name:
                    match_name = store_name.split("_", 1)[1]
                acc_info = account_info.get(match_name, {})
                
                stores.append({
                    "row_num": row_idx,
                    "스토어명": store_name,
                    "active": is_active,
                    "total": get_int("total"),
                    "on_sale": get_int("on_sale"),
                    "suspended": get_int("suspended"),
                    "pending": get_int("pending"),
                    "owner": acc_info.get("owner", ""),
                    "usage": acc_info.get("usage", ""),
                    "updated_at": row[col_idx["updated_at"]] if "updated_at" in col_idx and len(row) > col_idx["updated_at"] else ""
                })
            
            print(f"[올인원] 11번가 스토어 {len(stores)}개 로드")
            return {"stores": stores}
        
        # 스마트스토어 (기존 로직)
        ws = gsheet.sheet.worksheet(sheet_name)
        
        # stores 탭은 A1이 작업선택 칸이므로 get_all_values 사용
        all_values = ws.get_all_values()
        
        if not all_values or len(all_values) < 2:
            return {"stores": []}
        
        # 첫 번째 행은 헤더 (A1은 작업선택 드롭다운)
        headers = all_values[0]
        print(f"[올인원] {sheet_name} 헤더: {headers[:5]}")
        
        # 스토어명 열 인덱스 찾기
        store_col = None
        for i, h in enumerate(headers):
            if h in ["store_name", "쇼핑몰 별칭", "스토어명", "계정명"]:
                store_col = i
                break
        
        if store_col is None:
            print(f"[올인원] 스토어명 열을 찾을 수 없음")
            return {"stores": [], "error": "스토어명 열 없음"}
        
        # 구글시트 순서대로 스토어 목록 생성
        stores = []
        for row_idx, row in enumerate(all_values[1:], start=1):  # 헤더 제외
            if len(row) <= store_col:
                continue
            
            # A열(인덱스 0)이 active
            active = row[0] if len(row) > 0 else ""
            store_name = row[store_col] if len(row) > store_col else ""
            
            if not store_name:
                continue
            
            is_active = str(active).upper() == "TRUE"
            counts = product_counts.get(store_name, {})
            
            # 계정목록에서 소유자/용도 매칭
            # stores의 store_name과 계정목록의 (언더바 제거된) 쇼핑몰 별칭 매칭
            acc_info = account_info.get(store_name, {})
            
            # 기본 데이터
            store_data = {
                "row_num": counts.get("row_num", row_idx),
                "스토어명": store_name,
                "active": is_active,
                "total": counts.get("total", 0),
                "on_sale": counts.get("on_sale", 0),
                "suspended": counts.get("suspended", 0),
                "pending": counts.get("pending", 0),
                "owner": acc_info.get("owner", ""),
                "usage": acc_info.get("usage", ""),
                "updated_at": counts.get("updated_at", "")
            }
            
            # 언더바 뒤 이름 추출 (매칭용)
            match_name = store_name
            if "_" in store_name:
                match_name = store_name.split("_", 1)[1]
            
            # 배송코드 데이터 추가
            if task == "배송코드":
                ship_info = shipping_codes.get(store_name) or shipping_codes.get(match_name) or {}
                store_data["국내출고지"] = ship_info.get("국내출고지", "")
                store_data["해외출고지"] = ship_info.get("해외출고지", "")
                store_data["반품지"] = ship_info.get("반품지", "")
                store_data["shipping_updated_at"] = ship_info.get("updated_at", "")
            
            # 배송변경 데이터 추가 (store_name 또는 언더바 뒤 이름으로 매칭)
            if task == "배송변경":
                del_info = delivery_info.get(store_name) or delivery_info.get(match_name) or {}
                ship_info = shipping_codes.get(store_name) or shipping_codes.get(match_name) or {}
                store_data["target_limit"] = del_info.get("target_limit", "")
                store_data["shippingAddressId"] = del_info.get("shippingAddressId", "")
                store_data["differentialFeeByArea"] = del_info.get("differentialFeeByArea", "")
                store_data["cutofftime"] = del_info.get("cutofftime", "")
                store_data["delivery_updated_at"] = del_info.get("updated_at", "")
                # 배송코드에서 출고지 코드 (드롭다운 변환용)
                store_data["국내출고지코드"] = ship_info.get("국내출고지", "")
                store_data["해외출고지코드"] = ship_info.get("해외출고지", "")
            
            # 혜택설정 데이터 추가 (store_name 또는 언더바 뒤 이름으로 매칭)
            if task == "혜택설정":
                ben_info = benefit_info.get(store_name) or benefit_info.get(match_name) or {}
                store_data["후기포인트"] = ben_info.get("후기포인트", "")
                store_data["포토후기포인트"] = ben_info.get("포토후기포인트", "")
                store_data["한달후기포인트"] = ben_info.get("한달후기포인트", "")
                store_data["한달포토후기포인트"] = ben_info.get("한달포토후기포인트", "")
                store_data["이벤트문구"] = ben_info.get("이벤트문구", "")
                store_data["사은품"] = ben_info.get("사은품", "")
                store_data["최소판매가"] = ben_info.get("최소판매가", "")
                store_data["복수구매"] = ben_info.get("복수구매", "")
                store_data["복수구매할인"] = ben_info.get("복수구매할인", "")
                store_data["benefit_result"] = ben_info.get("결과", "")
                store_data["benefit_updated_at"] = ben_info.get("updated_at", "")
            
            stores.append(store_data)
        
        print(f"[올인원] {platform}/{task} 스토어 {len(stores)}개 로드")
        return {"stores": stores}
    except Exception as e:
        print(f"[올인원] 스토어 목록 조회 오류: {e}")
        import traceback
        traceback.print_exc()
        return {"stores": [], "error": str(e)}

@app.post("/api/allinone/update-active")
async def update_allinone_active(request: Request, req: AioUpdateActiveRequest):
    """구글시트 active 열 업데이트"""
    require_permission(request, "edit")
    
    # 작업별 시트 매핑 (각 작업별 시트 사용)
    task_to_sheet = {
        "등록갯수": "stores",
        "배송코드": "stores",
        "배송변경": "배송변경",
        "상품삭제": "상품삭제",
        "혜택설정": "혜택설정",
        "중복삭제": "중복삭제",
        "KC인증": "KC인증",
        "기타기능": "기타기능",
        "판매중지": "11번가",
        "판매재개": "11번가"
    }
    
    # 11번가 플랫폼의 등록갯수는 11번가 시트 사용
    if req.platform == "11번가" and req.task == "등록갯수":
        sheet_name = "11번가"
    else:
        sheet_name = task_to_sheet.get(req.task, "stores")
    
    try:
        # 11번가도 같은 스프레드시트
        if sheet_name == "11번가":
            ws = gsheet.sheet.worksheet("11번가")
        else:
            ws = gsheet.sheet.worksheet(sheet_name)
        
        all_data = ws.get_all_values()
        
        if not all_data:
            return {"success": False, "message": "시트가 비어있습니다"}
        
        headers = all_data[0]
        
        # active/store_name 열 인덱스 찾기
        active_col = 0  # 기본값
        store_col = None
        
        for i, h in enumerate(headers):
            if h in ["active", "활성", "사용"]:
                active_col = i
            if h in ["store_name", "쇼핑몰 별칭", "스토어명"]:
                store_col = i
        
        if store_col is None:
            return {"success": False, "message": "스토어명 열을 찾을 수 없습니다"}
        
        # 업데이트할 셀 목록 생성
        updates = []
        active_col_letter = chr(65 + active_col) if active_col < 26 else f"{chr(64 + active_col // 26)}{chr(65 + active_col % 26)}"
        
        for row_idx, row in enumerate(all_data[1:], start=2):
            if len(row) <= store_col:
                continue
            
            store_name = row[store_col].strip()
            if not store_name:
                continue
            
            new_value = "TRUE" if store_name in req.active_stores else "FALSE"
            cell = f"{active_col_letter}{row_idx}"
            updates.append({"range": cell, "values": [[new_value]]})
        
        # 일괄 업데이트
        if updates:
            ws.batch_update(updates)
        
        # A1에 작업명 설정 (stores 탭인 경우)
        if sheet_name == "stores":
            ws.update_acell("A1", req.task)
            print(f"[올인원] A1 셀에 작업 설정: {req.task}")
        
        print(f"[올인원] {len(req.active_stores)}개 스토어 활성화 완료")
        return {"success": True, "message": f"{len(req.active_stores)}개 스토어 활성화"}
    except Exception as e:
        print(f"[올인원] active 업데이트 오류: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "message": str(e)}

@app.post("/api/allinone/run")
async def run_allinone_task(request: Request, req: AioRunRequest):
    """올인원 프로그램 실행"""
    require_permission(request, "edit")

    # 플랫폼별 상태 가져오기
    platform_status = get_aio_status(req.platform)

    if platform_status["running"]:
        return {"success": False, "message": f"{req.platform} 작업이 이미 실행 중입니다"}

    print(f"[올인원] 실행 요청: {req.platform} / {req.task}, 옵션: {req.options}")

    # 작업 로그 기록
    store_count = len(req.stores) if req.stores else 0
    store_names = ", ".join(req.stores[:5]) + ("..." if len(req.stores) > 5 else "") if req.stores else "전체"
    log_work(f"올인원-{req.task}", f"{req.platform}", store_count, f"대상: {store_names}", "웹")
    
    # 프로그램 경로
    if req.platform == "스마트스토어":
        script_path = r"C:\autosystem\smartstore_all_in_one_v1_1.py"

        try:
            # 배송변경 옵션 설정
            if req.task == "배송변경" and req.options:
                ws = gsheet.sheet.worksheet("배송변경")
                
                # 선택된 스토어 목록
                selected_stores = set(req.stores) if req.stores else set()
                
                # 배송변경 시트에서 직접 active 확인
                delivery_data = ws.get_all_values()
                delivery_headers = delivery_data[0] if delivery_data else []
                
                # active, store_name 컬럼 찾기
                active_col_idx = None
                store_name_col_idx = None
                for i, h in enumerate(delivery_headers):
                    if h in ["active", "활성"]:
                        active_col_idx = i
                    if h in ["store_name", "스토어명"]:
                        store_name_col_idx = i
                
                if active_col_idx is not None and store_name_col_idx is not None:
                    if req.options.get('mode') == 'count':
                        count = req.options.get('count', 100)
                        processed = []
                        for row_idx, row in enumerate(delivery_data[1:], start=2):
                            if len(row) > max(active_col_idx, store_name_col_idx):
                                is_active = str(row[active_col_idx]).upper() == "TRUE"
                                store_name = row[store_name_col_idx]
                                
                                if is_active and (not selected_stores or store_name in selected_stores):
                                    ws.update_acell(f"F{row_idx}", str(count))
                                    ws.update_acell(f"Y{row_idx}", "")
                                    processed.append(store_name)
                        print(f"[올인원] 배송변경 수량 {count}개: {', '.join(processed) if processed else '없음'}")
                    
                    elif req.options.get('mode') == 'date':
                        date_val = req.options.get('date', '')
                        processed = []
                        for row_idx, row in enumerate(delivery_data[1:], start=2):
                            if len(row) > max(active_col_idx, store_name_col_idx):
                                is_active = str(row[active_col_idx]).upper() == "TRUE"
                                store_name = row[store_name_col_idx]
                                
                                if is_active and (not selected_stores or store_name in selected_stores):
                                    ws.update_acell(f"F{row_idx}", "")
                                    ws.update_acell(f"Y{row_idx}", date_val)
                                    processed.append(store_name)
                        print(f"[올인원] 배송변경 날짜 {date_val}: {', '.join(processed) if processed else '없음'}")
            
            # 혜택설정 옵션 설정
            elif req.task == "혜택설정" and req.options:
                ws = gsheet.sheet.worksheet("혜택설정")
                
                # 선택된 스토어 목록
                selected_stores = set(req.stores) if req.stores else set()
                
                # 혜택설정 시트에서 직접 active 확인
                benefit_data = ws.get_all_values()
                benefit_headers = benefit_data[0] if benefit_data else []
                
                # active, store_name 컬럼 찾기
                active_col_idx = None
                store_name_col_idx = None
                for i, h in enumerate(benefit_headers):
                    if h in ["active", "활성"]:
                        active_col_idx = i
                    if h in ["store_name", "스토어명"]:
                        store_name_col_idx = i
                
                if active_col_idx is not None and store_name_col_idx is not None:
                    if req.options.get('date'):
                        date_val = req.options.get('date', '')
                        processed = []
                        for row_idx, row in enumerate(benefit_data[1:], start=2):
                            if len(row) > max(active_col_idx, store_name_col_idx):
                                is_active = str(row[active_col_idx]).upper() == "TRUE"
                                store_name = row[store_name_col_idx]
                                
                                if is_active and (not selected_stores or store_name in selected_stores):
                                    ws.update_acell(f"M{row_idx}", date_val)
                                    processed.append(store_name)
                        print(f"[올인원] 혜택설정 날짜 {date_val}: {', '.join(processed) if processed else '없음'}")
            
            elif req.task == "상품삭제" and req.options:
                ws_delete = gsheet.sheet.worksheet("상품삭제")
                
                # 선택된 스토어 목록
                selected_stores = set(req.stores) if req.stores else set()
                
                # 상품삭제 시트에서 직접 active 확인
                delete_data = ws_delete.get_all_values()
                delete_headers = delete_data[0] if delete_data else []
                
                # active, store_name 컬럼 찾기
                active_col_idx = None
                store_name_col_idx = None
                for i, h in enumerate(delete_headers):
                    if h in ["active", "활성"]:
                        active_col_idx = i
                    if h in ["store_name", "스토어명"]:
                        store_name_col_idx = i
                
                if active_col_idx is None or store_name_col_idx is None:
                    print(f"[올인원] 상품삭제 시트에서 active 또는 store_name 열을 찾을 수 없음")
                else:
                    if req.options.get('delete_excess_only'):
                        # 초과분만 삭제
                        delete_limit = req.options.get('delete_limit', 9500)
                        print(f"[올인원] 초과분만 삭제 모드: 기준={delete_limit}개")
                        
                        try:
                            ws_counts = gsheet.sheet.worksheet("등록갯수")
                            counts_data = ws_counts.get_all_records()
                            store_sales = {}
                            for row in counts_data:
                                store_name = row.get("스토어명", "")
                                sales_count = int(row.get("판매중", 0) or 0)
                                if store_name:
                                    store_sales[store_name] = sales_count
                            
                            processed_stores = []
                            for row_idx, row in enumerate(delete_data[1:], start=2):
                                if len(row) > max(active_col_idx, store_name_col_idx):
                                    is_active = str(row[active_col_idx]).upper() == "TRUE"
                                    store_name = row[store_name_col_idx]
                                    
                                    # active=TRUE이고, 선택된 스토어인 경우만
                                    if is_active and (not selected_stores or store_name in selected_stores):
                                        sales = store_sales.get(store_name, 0)
                                        excess = max(0, sales - delete_limit)
                                        ws_delete.update_acell(f"C{row_idx}", str(excess))
                                        processed_stores.append(store_name)
                                        print(f"[올인원] {store_name}: 판매중={sales}, 기준={delete_limit}, 삭제={excess}")
                            
                            if processed_stores:
                                print(f"[올인원] 초과분 삭제 대상: {', '.join(processed_stores)}")
                        except Exception as e:
                            print(f"[올인원] 초과분 계산 오류: {e}")
                    
                    elif req.options.get('delete_count'):
                        delete_count = req.options.get('delete_count', 50)
                        processed_stores = []
                        
                        for row_idx, row in enumerate(delete_data[1:], start=2):
                            if len(row) > max(active_col_idx, store_name_col_idx):
                                is_active = str(row[active_col_idx]).upper() == "TRUE"
                                store_name = row[store_name_col_idx]
                                
                                # active=TRUE이고, 선택된 스토어인 경우만
                                if is_active and (not selected_stores or store_name in selected_stores):
                                    ws_delete.update_acell(f"C{row_idx}", str(delete_count))
                                    processed_stores.append(store_name)
                        
                        if processed_stores:
                            print(f"[올인원] 상품삭제 {delete_count}개: {', '.join(processed_stores)}")
                        else:
                            print(f"[올인원] 상품삭제: 대상 스토어 없음 (active=TRUE인 선택 스토어 확인)")
                    
        except Exception as e:
            print(f"[올인원] 작업 설정 오류: {e}")
        
        # 로그 파일 경로 (플랫폼별)
        log_file = os.path.join(os.path.dirname(__file__), "logs", "allinone_smartstore.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        # 플랫폼별 상태 초기화
        aio_status_by_platform["스마트스토어"] = {
            "running": True,
            "progress": 0,
            "status": "running",
            "results": [],
            "process": None,
            "options": req.options,
            "current_store": "",
            "current_action": "프로세스 시작 중...",
            "total": 0,
            "completed": 0,
            "logs": [],
            "log_file": log_file,
            "log_pos": 0  # 로그 파일 읽기 위치
        }
        platform_status = aio_status_by_platform["스마트스토어"]
        
        # 환경변수 설정
        env = os.environ.copy()
        env["SERVICE_ACCOUNT_JSON"] = os.environ.get("SERVICE_ACCOUNT_JSON", "")
        env["SPREADSHEET_KEY"] = os.environ.get("SPREADSHEET_KEY", "")
        env["PARALLEL_STORES"] = "true"
        env["PARALLEL_WORKERS"] = "4"
        env["PYTHONIOENCODING"] = "utf-8"  # UTF-8 출력 강제
        env["AIO_TASK"] = req.task  # 작업명 전달 (대상 스토어는 시트의 '활성화' 컬럼 참조)
        
        # subprocess로 별도 프로세스 실행
        module_path = os.path.join(os.path.dirname(__file__), "modules", "smartstore_allinone.py")
        
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] 스마트스토어 {req.task} 시작\n")
        
        process = subprocess.Popen(
            [sys.executable, module_path],
            stdout=open(log_file, "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            env=env,
            cwd=os.path.dirname(__file__)
        )
        platform_status["process"] = process
        
        return {"success": True, "message": f"{req.platform} {req.task} 실행 시작 (PID: {process.pid})"}
    
    elif req.platform == "11번가":
        # 11번가 작업 처리
        
        # 로그 파일 경로 (플랫폼별)
        log_file = os.path.join(os.path.dirname(__file__), "logs", "allinone_11st.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        # 플랫폼별 상태 초기화
        aio_status_by_platform["11번가"] = {
            "running": True,
            "progress": 0,
            "status": "running",
            "results": [],
            "process": None,
            "options": req.options,
            "current_store": "",
            "current_action": "프로세스 시작 중...",
            "total": 0,
            "completed": 0,
            "logs": [],
            "log_file": log_file,
            "log_pos": 0
        }
        platform_status = aio_status_by_platform["11번가"]
        
        if req.task == "등록갯수":
            # 등록갯수(판매중) 조회 - 인라인 처리
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] 11번가 판매중 조회 시작\n")
            
            # 백그라운드에서 실행
            import asyncio
            asyncio.create_task(run_11st_product_count_task(log_file, "11번가"))
            
            return {"success": True, "message": f"11번가 판매중 조회 시작"}
        else:
            # 판매중지/판매재개 등 - subprocess로 실행
            env = os.environ.copy()
            env["GOOGLE_SERVICE_ACCOUNT_FILE"] = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", os.environ.get("SERVICE_ACCOUNT_JSON", ""))
            env["SPREADSHEET_KEY"] = os.environ.get("SPREADSHEET_KEY", "")
            env["ELEVENST_TASK"] = req.task  # 작업 종류 전달
            env["PYTHONIOENCODING"] = "utf-8"  # UTF-8 출력 강제
            
            # subprocess로 별도 프로세스 실행
            module_path = os.path.join(os.path.dirname(__file__), "modules", "elevenst.py")
            
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] 11번가 {req.task} 시작\n")
            
            process = subprocess.Popen(
                [sys.executable, module_path],
                stdout=open(log_file, "a", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                env=env,
                cwd=os.path.dirname(__file__)
            )
            platform_status["process"] = process
            
            return {"success": True, "message": f"{req.platform} {req.task} 실행 시작 (PID: {process.pid})"}
    
    else:
        return {"success": False, "message": f"지원하지 않는 플랫폼: {req.platform}"}

@app.get("/api/allinone/progress")
async def get_allinone_progress(request: Request, platform: str = None):
    """올인원 진행상황 조회 (플랫폼별)"""
    require_permission(request, "edit")
    
    # 플랫폼별 상태 가져오기
    status = get_aio_status(platform)
    
    # 프로세스 상태 확인
    if status.get("process"):
        poll = status["process"].poll()
        if poll is not None:
            # 프로세스 종료됨
            status["running"] = False
            status["status"] = "completed"
            status["progress"] = 100
            status["current_store"] = ""
            status["current_action"] = "완료"
    
    # 로그 파일에서 새 로그 읽기
    log_file = status.get("log_file")
    if log_file and os.path.exists(log_file):
        try:
            # Windows CP949 또는 UTF-8 인코딩 시도
            for enc in ["utf-8", "cp949", "euc-kr"]:
                try:
                    with open(log_file, "r", encoding=enc, errors="replace") as f:
                        f.seek(status.get("log_pos", 0))
                        new_lines = f.readlines()
                        new_pos = f.tell()
                    break
                except UnicodeDecodeError:
                    continue
            else:
                new_lines = []
                new_pos = status.get("log_pos", 0)
            
            if new_lines:
                status["log_pos"] = new_pos
                for line in new_lines:
                    line = line.strip()
                    if line:
                        # 로그에서 시간 추출 시도 (예: [23:36:04] 또는 [11번가] 형태)
                        import re
                        time_match = re.match(r'\[(\d{2}:\d{2}:\d{2})\]', line)
                        if time_match:
                            log_time = time_match.group(1)
                        else:
                            log_time = datetime.now().strftime("%H:%M:%S")
                        
                        status["logs"].append({
                            "time": log_time,
                            "msg": line
                        })
                # 최근 100개만 유지
                if len(status["logs"]) > 100:
                    status["logs"] = status["logs"][-100:]
                
                # 로그에서 진행 상황 파싱
                for line in new_lines:
                    line = line.strip()
                    import re
                    
                    # [RUN] 대상 계정: N개 형태에서 total 추출
                    total_match = re.search(r'대상 계정:\s*(\d+)개', line)
                    if total_match:
                        status["total"] = int(total_match.group(1))
                    
                    # [1/5] 스토어명: 형태에서 현재 진행상황 추출
                    progress_match = re.search(r'\[(\d+)/(\d+)\]\s*([^:]+):', line)
                    if progress_match:
                        completed = int(progress_match.group(1))
                        total = int(progress_match.group(2))
                        store_name = progress_match.group(3).strip()
                        status["completed"] = completed
                        status["total"] = total
                        status["current_store"] = store_name
                        status["current_action"] = line
                        if total > 0:
                            status["progress"] = int((completed / total) * 100)
        except Exception as e:
            print(f"로그 읽기 오류: {e}")
    
    return {
        "running": status.get("running", False),
        "progress": status.get("progress", 0),
        "status": status.get("status", "idle"),
        "results": status.get("results", []),
        "current_store": status.get("current_store", ""),
        "current_action": status.get("current_action", ""),
        "total": status.get("total", 0),
        "completed": status.get("completed", 0),
        "logs": status.get("logs", [])
    }

@app.post("/api/allinone/stop")
async def stop_allinone_task(request: Request, platform: str = None):
    """올인원 작업 중지 (플랫폼별)"""
    require_permission(request, "edit")
    
    # 플랫폼별 상태 가져오기
    status = get_aio_status(platform)
    
    if status.get("process"):
        try:
            status["process"].terminate()
        except:
            pass
    
    # 11번가 모듈 중지
    if platform == "11번가" or platform is None:
        try:
            from modules import elevenst
            elevenst.stop_all()
        except:
            pass
    
    status["running"] = False
    status["status"] = "stopped"
    
    return {"success": True, "message": f"{platform or '전체'} 중지 요청됨"}


# ========== KC 인증 수정 API ==========
class KCModifyRequest(BaseModel):
    stores: List[str]  # store_name 목록
    product_limit: int = 2000  # 마켓당 처리할 상품 수
    mode: str = "count"  # count 또는 date
    target_date: str = ""  # mode=date일 때 기준 날짜 (YYYY-MM-DD)

# KC 수정 상태 저장
kc_modify_status = {
    "running": False,
    "progress": {},  # store_name -> {progress, total, success, fail, status}
    "logs": [],
    "stop_requested": False
}

def get_naver_token(client_id: str, client_secret: str) -> str:
    """네이버 커머스 API 토큰 발급"""
    import bcrypt
    timestamp = int(time.time() * 1000)
    password = f"{client_id}_{timestamp}"
    hashed = bcrypt.hashpw(password.encode('utf-8'), client_secret.encode('utf-8'))
    signature = base64.b64encode(hashed).decode('utf-8')
    
    url = "https://api.commerce.naver.com/external/v1/oauth2/token"
    data = {
        "client_id": client_id,
        "timestamp": timestamp,
        "client_secret_sign": signature,
        "grant_type": "client_credentials",
        "type": "SELF"
    }
    
    response = requests.post(url, data=data)
    if response.status_code == 200:
        return response.json().get("access_token")
    raise Exception(f"토큰 발급 실패: {response.text}")

def modify_kc_for_store(store_name: str, client_id: str, client_secret: str, product_limit: int, mode: str = "count", target_date: str = ""):
    """단일 스토어 KC 인증 수정
    mode: count - 최신 N개 상품
    mode: date - 지정 날짜 이후 등록 상품
    """
    global kc_modify_status
    
    def add_log(msg, status="info"):
        log_entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "store": store_name,
            "msg": msg,
            "status": status
        }
        kc_modify_status["logs"].append(log_entry)
        if len(kc_modify_status["logs"]) > 500:
            kc_modify_status["logs"] = kc_modify_status["logs"][-500:]
        print(f"[KC-{store_name}] {msg}")
    
    try:
        kc_modify_status["progress"][store_name] = {
            "progress": 0, "total": 0, "success": 0, "fail": 0, "status": "토큰 발급 중..."
        }
        
        # 토큰 발급
        token = get_naver_token(client_id, client_secret)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        add_log("토큰 발급 완료")
        kc_modify_status["progress"][store_name]["status"] = "상품 조회 중..."
        
        # 상품 목록 조회 (최신 등록순)
        products = []
        page = 1
        base_url = "https://api.commerce.naver.com/external"
        
        # 날짜 모드일 때 기준 날짜 파싱
        filter_date = None
        if mode == "date" and target_date:
            try:
                filter_date = datetime.strptime(target_date, "%Y-%m-%d")
                add_log(f"날짜 기준: {target_date} 이후 등록 상품")
            except:
                add_log(f"날짜 파싱 실패: {target_date}", "error")
        
        max_pages = 100 if mode == "date" else 20  # 날짜 모드는 더 많이 조회
        
        while (mode == "count" and len(products) < product_limit) or (mode == "date" and page <= max_pages):
            if kc_modify_status["stop_requested"]:
                add_log("중지 요청됨", "warning")
                break
            
            body = {"page": page, "size": 500, "sortType": "RECENTLY_REGISTERED"}
            resp = requests.post(f"{base_url}/v1/products/search", headers=headers, json=body)
            
            if resp.status_code != 200:
                add_log(f"상품 조회 실패: {resp.text}", "error")
                break
            
            data = resp.json()
            contents = data.get("contents", [])
            
            if not contents:
                break
            
            stop_fetching = False
            for item in contents:
                if mode == "count" and len(products) >= product_limit:
                    stop_fetching = True
                    break
                
                origin_no = item.get("originProductNo")
                reg_date_str = item.get("registrationDate", "")
                channel_products = item.get("channelProducts", [])
                
                # 날짜 모드일 때 필터링
                if mode == "date" and filter_date and reg_date_str:
                    try:
                        # 등록일 파싱 (ISO 형식)
                        reg_date = datetime.fromisoformat(reg_date_str.replace('Z', '+00:00').split('+')[0])
                        if reg_date < filter_date:
                            stop_fetching = True  # 더 이전 상품은 조회 중지
                            break
                    except:
                        pass
                
                if channel_products:
                    products.append({
                        "originProductNo": origin_no,
                        "name": channel_products[0].get("name", "")[:30],
                        "registrationDate": reg_date_str
                    })
            
            if stop_fetching:
                break
            
            if page >= data.get("totalPages", 1):
                break
            page += 1
            time.sleep(0.3)
        
        total = len(products)
        add_log(f"상품 {total}개 조회 완료")
        kc_modify_status["progress"][store_name]["total"] = total
        kc_modify_status["progress"][store_name]["status"] = "KC 수정 중..."
        
        if total == 0:
            kc_modify_status["progress"][store_name]["status"] = "완료 (상품 없음)"
            return {"success": 0, "fail": 0}
        
        # 상품별 KC 인증 수정
        success = 0
        fail = 0
        
        for idx, product in enumerate(products):
            if kc_modify_status["stop_requested"]:
                add_log("중지됨", "warning")
                break
            
            product_no = product["originProductNo"]
            
            try:
                # 상세 조회
                detail_resp = requests.get(
                    f"{base_url}/v2/products/origin-products/{product_no}",
                    headers=headers
                )
                
                if detail_resp.status_code != 200:
                    fail += 1
                    continue
                
                detail = detail_resp.json()
                origin_product = detail.get("originProduct", {})
                
                # KC 인증 제외 설정
                if "detailAttribute" not in origin_product:
                    origin_product["detailAttribute"] = {}
                
                origin_product["detailAttribute"]["certificationTargetExcludeContent"] = {
                    "kcCertifiedProductExclusionYn": "TRUE",
                    "childCertifiedProductExclusionYn": True,
                    "greenCertifiedProductExclusionYn": True
                }
                
                # 업데이트
                update_data = {"originProduct": origin_product}
                if "smartstoreChannelProduct" in detail:
                    update_data["smartstoreChannelProduct"] = detail["smartstoreChannelProduct"]
                
                update_resp = requests.put(
                    f"{base_url}/v2/products/origin-products/{product_no}",
                    headers=headers,
                    json=update_data
                )
                
                if update_resp.status_code == 200:
                    success += 1
                else:
                    fail += 1
                
                # 10개마다 로그
                if success % 10 == 0 and success > 0:
                    add_log(f"{success}개 완료...")
                
            except Exception as e:
                fail += 1
                if fail <= 3:  # 처음 3개만 로그
                    add_log(f"[{product_no}] 오류: {str(e)[:50]}", "error")
            
            kc_modify_status["progress"][store_name]["progress"] = idx + 1
            kc_modify_status["progress"][store_name]["success"] = success
            kc_modify_status["progress"][store_name]["fail"] = fail
            
            time.sleep(1)  # API 제한
        
        status_text = f"완료 (성공:{success}, 실패:{fail})"
        kc_modify_status["progress"][store_name]["status"] = status_text
        add_log(status_text, "success")
        
        return {"success": success, "fail": fail}
        
    except Exception as e:
        add_log(f"오류: {str(e)}", "error")
        kc_modify_status["progress"][store_name]["status"] = f"오류: {str(e)[:30]}"
        return {"success": 0, "fail": 0, "error": str(e)}

@app.post("/api/allinone/kc-modify")
async def run_kc_modify(request: Request, req: KCModifyRequest):
    """KC 인증 일괄 수정 실행"""
    require_permission(request, "edit")

    global kc_modify_status

    if kc_modify_status["running"]:
        return {"success": False, "message": "이미 실행 중입니다"}

    if not req.stores:
        return {"success": False, "message": "스토어를 선택하세요"}

    # 작업 로그 기록
    store_names = ", ".join(req.stores[:5]) + ("..." if len(req.stores) > 5 else "")
    log_work("KC인증수정", "스마트스토어", len(req.stores), f"대상: {store_names}", "웹")
    
    # 계정목록 시트에서 API 정보 가져오기
    try:
        ws = gsheet.sheet.worksheet(ACCOUNTS_TAB)  # 계정목록
        data = ws.get_all_values()
        headers = data[0]

        # 컬럼 인덱스 찾기 (계정목록 컬럼명)
        name_idx = None
        id_idx = None
        secret_idx = None
        platform_idx = None
        for i, h in enumerate(headers):
            if h in ["스토어명", "store_name"]:
                name_idx = i
            elif h in ["스마트스토어 애플리케이션 ID", "client_id"]:
                id_idx = i
            elif h in ["스마트스토어 애플리케이션 시크릿", "client_secret"]:
                secret_idx = i
            elif h in ["플랫폼", "platform"]:
                platform_idx = i

        if None in [name_idx, id_idx, secret_idx]:
            return {"success": False, "message": "시트에 필요한 컬럼이 없습니다 (스토어명, 스마트스토어 애플리케이션 ID/시크릿)"}

        # 선택된 스토어 정보 추출 (스마트스토어만)
        store_info = {}
        for row in data[1:]:
            if len(row) > max(name_idx, id_idx, secret_idx):
                # 플랫폼 체크 (스마트스토어만)
                platform = row[platform_idx].lower() if platform_idx and len(row) > platform_idx else ""
                if platform and platform not in ["스마트스토어", "smartstore", "네이버", "naver"]:
                    continue
                name = row[name_idx]
                if name in req.stores:
                    store_info[name] = {
                        "client_id": row[id_idx],
                        "client_secret": row[secret_idx]
                    }

        if not store_info:
            return {"success": False, "message": "선택된 스토어 정보를 찾을 수 없습니다"}

    except Exception as e:
        return {"success": False, "message": f"시트 조회 오류: {str(e)}"}
    
    # 상태 초기화
    kc_modify_status = {
        "running": True,
        "progress": {},
        "logs": [],
        "stop_requested": False
    }
    
    def run_parallel():
        global kc_modify_status
        
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            with ThreadPoolExecutor(max_workers=min(5, len(store_info))) as executor:
                futures = {}
                for store_name, info in store_info.items():
                    future = executor.submit(
                        modify_kc_for_store,
                        store_name,
                        info["client_id"],
                        info["client_secret"],
                        req.product_limit,
                        req.mode,
                        req.target_date
                    )
                    futures[future] = store_name
                
                for future in as_completed(futures):
                    store_name = futures[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        print(f"[KC] {store_name} 스레드 오류: {e}")
        
        finally:
            kc_modify_status["running"] = False
    
    # 백그라운드 실행
    import threading
    threading.Thread(target=run_parallel, daemon=True).start()
    
    return {"success": True, "message": f"{len(store_info)}개 스토어 KC 수정 시작"}

@app.get("/api/allinone/kc-progress")
async def get_kc_progress(request: Request):
    """KC 수정 진행상황 조회"""
    require_permission(request, "edit")
    return kc_modify_status

@app.post("/api/allinone/kc-stop")
async def stop_kc_modify(request: Request):
    """KC 수정 중지"""
    require_permission(request, "edit")
    global kc_modify_status
    kc_modify_status["stop_requested"] = True
    return {"success": True, "message": "중지 요청됨"}


# ========== 구글시트 매출 집계 API ==========
# 매출 시트 ID
SALES_SHEET_ID = "1MHhu1GdvV1OGS8Wy3NxWOKuqFvgZpqgwn08kG70EDsY"

# 매출 캐시 (메모리)
sales_cache = {
    "data": {},  # {마켓ID: {today_sales, today_orders, month_sales, month_orders}}
    "updated_at": None,
    "daily": [],  # 일자별 집계
    "by_owner": {},  # 소유자별 집계
    "raw_data": []  # 원본 데이터
}

@app.get("/api/sales/from-sheet")
async def get_sales_from_sheet(request: Request, force: bool = False):
    """구글시트에서 마켓별 매출 집계"""
    get_current_user(request)
    
    from datetime import datetime
    
    # 캐시 확인 (5분 이내면 캐시 사용)
    if not force and sales_cache["updated_at"]:
        cache_age = (datetime.now() - sales_cache["updated_at"]).total_seconds()
        if cache_age < 300:  # 5분
            return {"success": True, "data": sales_cache["data"], "daily": sales_cache.get("daily", []), "total": sales_cache.get("total", {}), "cached": True}
    
    try:
        # 현재 월 탭 이름 (예: "12월")
        current_month = datetime.now().month
        current_tab = f"{current_month}월"
        prev_month = current_month - 1 if current_month > 1 else 12
        prev_tab = f"{prev_month}월"
        today = datetime.now().date()
        days_30_ago = today - timedelta(days=30)
        
        # 계정목록 시트에서 계정 목록 로드
        all_store_keys = set()  # "store_name(플랫폼)" 형태
        account_usage = {}  # {"store_name(플랫폼)": "대량" or "반대량"}
        account_owner = {}  # {"store_name(플랫폼)": "소유자(JSM, JJI 등)"}
        # 사업자번호로 매칭하기 위한 추가 딕셔너리
        biz_to_owner = {}  # {"사업자번호": "소유자"}
        biz_to_usage = {}  # {"사업자번호": "용도"}
        biz_to_stores = {}  # {"사업자번호": set(스토어명들)} - 매출 유무와 관계없이 모든 스토어
        try:
            accounts = gsheet.get_accounts()
            for acc in accounts:
                # store_name = 쇼핑몰 별칭 = 매출 시트의 "사업자"(F열)
                store_name = acc.get("스토어명", "") or acc.get("스토어명", "")
                store_name = store_name.strip()
                platform = acc.get("platform", "").strip()
                usage = acc.get("usage", "").strip()
                owner = acc.get("owner", "").strip()  # 실제 소유자 (JSM, JJI 등)
                biz_number = acc.get("business_number", "").strip()  # 사업자번호
                
                # store_name(플랫폼) 키로 매칭
                if store_name and platform:
                    key = f"{store_name}({platform})"
                    all_store_keys.add(key)
                    account_usage[key] = usage
                    account_owner[key] = owner
                
                # 사업자번호로도 매칭 (사업자번호가 있으면)
                if biz_number and owner:
                    biz_to_owner[biz_number] = owner
                if biz_number and usage:
                    biz_to_usage[biz_number] = usage
                
                # 사업자번호별 모든 스토어 매핑 (매출 유무와 관계없이)
                if biz_number and store_name:
                    if biz_number not in biz_to_stores:
                        biz_to_stores[biz_number] = set()
                    biz_to_stores[biz_number].add(store_name)
                    
            print(f"[매출집계] 계정목록에서 {len(all_store_keys)}개 계정 로드")
            print(f"[매출집계] 사업자번호 매핑: {len(biz_to_owner)}개 owner, {len(biz_to_usage)}개 usage")
            if all_store_keys:
                sample_keys = list(all_store_keys)[:5]
                print(f"[매출집계] 계정목록 키 샘플: {sample_keys}")
                # owner, usage 샘플 출력
                for k in sample_keys:
                    print(f"[매출집계]   {k} → owner='{account_owner.get(k, '')}', usage='{account_usage.get(k, '')}'")
                # 썬이마켓 찾기
                for k in all_store_keys:
                    if "썬이마켓" in k:
                        print(f"[매출집계] ★ 계정목록 썬이마켓: key='{k}', owner='{account_owner.get(k, '')}'")
        except Exception as e:
            print(f"[매출집계] 계정 목록 로드 실패: {e}")
        
        # 시트 열기
        sales_sheet = gsheet.client.open_by_key(SALES_SHEET_ID)
        
        # 이번달 + 지난달 데이터 합치기
        all_data = []
        headers = None
        
        for tab_name in [current_tab, prev_tab]:
            try:
                ws = sales_sheet.worksheet(tab_name)
                tab_data = ws.get_all_values()
                if len(tab_data) >= 3:
                    if headers is None:
                        headers = tab_data[1]  # 2행이 헤더
                        all_data = tab_data[2:]  # 3행부터 데이터
                    else:
                        all_data.extend(tab_data[2:])
                    print(f"[매출집계] {tab_name} 탭에서 {len(tab_data)-2}건 로드")
            except Exception as e:
                print(f"[매출집계] {tab_name} 탭 로드 실패: {e}")
        
        if not headers or len(all_data) < 1:
            return {"success": False, "message": "데이터 없음"}
        
        # 컬럼 인덱스 찾기 (이름으로) - 줄바꿈 제거
        def find_col(names):
            for name in names:
                for idx, h in enumerate(headers):
                    # 헤더에서 줄바꿈, 공백 제거 후 비교
                    h_clean = h.replace('\n', '').replace('\r', '').replace(' ', '')
                    name_clean = name.replace(' ', '')
                    if name_clean in h_clean:
                        return idx
            return -1
        
        # 열 문자를 인덱스로 변환 (A=0, B=1, ..., Z=25, AA=26, ...)
        def col_letter_to_idx(letter):
            letter = letter.upper()
            result = 0
            for char in letter:
                result = result * 26 + (ord(char) - ord('A') + 1)
            return result - 1
        
        # 이름으로 먼저 찾고, 못 찾으면 직접 열 인덱스 사용
        col_market = find_col(["마켓"])  # E열: 스마트스토어, 11번가, 쿠팡 등
        col_owner = find_col(["사업자"])
        col_order_date = find_col(["주문일자"])
        col_payment = find_col(["실결제금액(배송비포함)", "실결제금액"])
        col_settlement = find_col(["정산금액(배송비포함)", "정산금액"])
        col_profit = find_col(["수익금"])
        col_profit_rate = find_col(["수익률"])
        col_order_status = find_col(["주문현황"])
        col_purchase = find_col(["구매금액(원화)", "구매금액"])
        col_int_shipping = find_col(["국제배송비"])
        col_cargo_shipping = find_col(["화물택배비"])
        col_biz_number = find_col(["사업자번호", "사업자 번호"])  # AN열: 사업자번호
        
        # 못 찾은 컬럼은 직접 열 인덱스 지정 (이미지 기준)
        if col_order_status < 0: col_order_status = col_letter_to_idx('D')   # D열: 주문현황
        if col_market < 0: col_market = col_letter_to_idx('E')               # E열: 마켓
        if col_owner < 0: col_owner = col_letter_to_idx('F')                 # F열: 사업자
        if col_order_date < 0: col_order_date = col_letter_to_idx('G')       # G열: 주문일자
        if col_payment < 0: col_payment = col_letter_to_idx('X')             # X열: 실결제금액
        if col_settlement < 0: col_settlement = col_letter_to_idx('AA')      # AA열: 정산금액
        if col_purchase < 0: col_purchase = col_letter_to_idx('AL')          # AL열: 구매금액(원화)
        if col_biz_number < 0: col_biz_number = col_letter_to_idx('AN')      # AN열: 사업자번호
        if col_int_shipping < 0: col_int_shipping = col_letter_to_idx('AR')  # AR열: 국제배송비
        if col_profit < 0: col_profit = col_letter_to_idx('AY')              # AY열: 수익금
        if col_profit_rate < 0: col_profit_rate = col_letter_to_idx('AZ')    # AZ열: 수익률
        if col_cargo_shipping < 0: col_cargo_shipping = col_letter_to_idx('AU')  # AU열: 화물택배비
        
        print(f"[매출집계] 컬럼 - 마켓:{col_market}, 주문일자:{col_order_date}, 실결제:{col_payment}, 정산:{col_settlement}, 수익금:{col_profit}, 사업자번호:{col_biz_number}")
        
        if col_market < 0 or col_order_date < 0:
            return {"success": False, "message": "필수 컬럼 없음 (마켓, 주문일자)"}
        
        # 마켓별 집계
        market_sales = {}
        daily_sales = {}  # 일자별 집계
        skip_cancel = 0
        skip_return = 0
        skip_old = 0  # 30일 이전 데이터
        
        # 2주 기준일
        days_14_ago = (datetime.now() - timedelta(days=14)).date()
        
        # stores 시트의 모든 계정을 0으로 초기화
        for store_key in all_store_keys:
            market_sales[store_key] = {
                "today_sales": 0,
                "today_orders": 0,
                "month_sales": 0,
                "month_orders": 0,
                "orders_2w": 0,  # 2주 주문
                "month_profit": 0,
                "month_settlement": 0,
                "month_purchase": 0,
                "month_shipping": 0,
                "usage": account_usage.get(store_key, ""),
                "owner": account_owner.get(store_key, "")  # 실제 소유자
            }
        
        # 금액 파싱 함수
        def parse_amount(row, idx):
            if idx < 0 or idx >= len(row):
                return 0
            val = row[idx].replace(",", "").replace("원", "").replace("₩", "").replace("%", "").strip()
            try:
                return int(float(val)) if val else 0
            except:
                return 0
        
        # 날짜 파싱 함수
        def parse_date(date_str):
            try:
                # 2025-06-01 10:08 형식
                return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
            except:
                return None
        
        # 데이터 집계
        biz_sales = {}  # 사업자번호별 집계
        
        for row in all_data:
            if len(row) <= col_order_date:
                continue
            
            # 사업자 + 마켓 조합
            owner_raw = row[col_owner].strip() if col_owner >= 0 and col_owner < len(row) else ""
            market_raw = row[col_market].strip() if col_market >= 0 and col_market < len(row) else ""
            order_date_str = row[col_order_date].strip() if col_order_date < len(row) else ""
            order_status = row[col_order_status].strip() if col_order_status >= 0 and col_order_status < len(row) else ""
            biz_number = row[col_biz_number].strip() if col_biz_number >= 0 and col_biz_number < len(row) else ""
            
            # 마켓명 정규화 (매출 시트 → 계정목록 플랫폼명)
            market_normalized = market_raw
            if "스마트" in market_raw or "네이버" in market_raw or market_raw.upper() == "SS":
                market_normalized = "스마트스토어"
            elif "11" in market_raw or market_raw.upper() == "ST":
                market_normalized = "11번가"
            elif "쿠팡" in market_raw or market_raw.upper() == "CP":
                market_normalized = "쿠팡"
            elif "지마켓" in market_raw or market_raw.upper() == "GM":
                market_normalized = "지마켓"
            elif "옥션" in market_raw or market_raw.upper() == "AC":
                market_normalized = "옥션"
            
            if not owner_raw or not order_date_str:
                continue
            
            # 30일 이내 데이터만 집계
            order_date = parse_date(order_date_str)
            if not order_date or order_date < days_30_ago:
                skip_old += 1
                continue
            
            # 취소완료: 집계에서 완전 제외
            if "취소완료" in order_status:
                skip_cancel += 1
                continue
            
            # 소유자(마켓) 키 생성 - 정규화된 마켓명 사용
            store_key = f"{owner_raw}({market_normalized})"
            
            # 디버그: 처음 10개 행의 키와 매칭 결과
            if len(market_sales) < 10:
                matched_owner = account_owner.get(store_key, "")
                matched_usage = account_usage.get(store_key, "")
                in_account_list = store_key in all_store_keys
                print(f"[매출집계] 매출시트 키: '{store_key}' → 계정목록 매칭={in_account_list}, owner='{matched_owner}', usage='{matched_usage}'")
            
            # 썬이마켓 디버그
            if "썬이마켓" in owner_raw:
                matched_owner = account_owner.get(store_key, "")
                in_account_list = store_key in all_store_keys
                print(f"[매출집계] ★ 썬이마켓 발견: key='{store_key}', 매칭={in_account_list}, owner='{matched_owner}', 원본마켓='{market_raw}'")
            
            # 반품완료: 매출에서 제외
            is_return = "반품완료" in order_status
            if is_return:
                skip_return += 1
                payment = 0
                settlement = 0
                profit = 0
                purchase = parse_amount(row, col_purchase)  # 매입은 유지
                int_shipping = parse_amount(row, col_int_shipping)
                cargo_shipping = parse_amount(row, col_cargo_shipping)
            else:
                payment = parse_amount(row, col_payment)
                settlement = parse_amount(row, col_settlement)
                profit = parse_amount(row, col_profit)
                purchase = parse_amount(row, col_purchase)
                int_shipping = parse_amount(row, col_int_shipping)
                cargo_shipping = parse_amount(row, col_cargo_shipping)
            
            # 스토어 키 초기화 (목록에 없는 경우)
            if store_key not in market_sales:
                # 먼저 store_key로 매칭 시도, 없으면 사업자번호로 매칭
                matched_owner = account_owner.get(store_key, "") or biz_to_owner.get(biz_number, "")
                matched_usage = account_usage.get(store_key, "") or biz_to_usage.get(biz_number, "")
                market_sales[store_key] = {
                    "today_sales": 0,
                    "today_orders": 0,
                    "month_sales": 0,
                    "month_orders": 0,
                    "orders_2w": 0,  # 2주 주문
                    "month_profit": 0,
                    "month_settlement": 0,
                    "month_purchase": 0,
                    "month_shipping": 0,
                    "usage": matched_usage,
                    "owner": matched_owner,
                    "biz_number": biz_number
                }
            # 기존 항목도 owner/usage가 없으면 사업자번호로 매칭 시도
            elif biz_number:
                if not market_sales[store_key].get("owner"):
                    market_sales[store_key]["owner"] = biz_to_owner.get(biz_number, "")
                if not market_sales[store_key].get("usage"):
                    market_sales[store_key]["usage"] = biz_to_usage.get(biz_number, "")
            
            # 사업자번호별 집계
            if biz_number and not is_return:
                if biz_number not in biz_sales:
                    biz_sales[biz_number] = {
                        "sales": 0, "settlement": 0, "profit": 0, 
                        "purchase": 0, "shipping": 0, "orders": 0,
                        "stores": set()
                    }
                biz_sales[biz_number]["sales"] += payment
                biz_sales[biz_number]["settlement"] += settlement
                biz_sales[biz_number]["profit"] += profit
                biz_sales[biz_number]["purchase"] += purchase
                biz_sales[biz_number]["shipping"] += int_shipping + cargo_shipping
                biz_sales[biz_number]["orders"] += 1
                biz_sales[biz_number]["stores"].add(owner_raw)
            
            # 일자 키
            date_key = order_date_str[:10]
            
            # 일자별 초기화
            if date_key not in daily_sales:
                daily_sales[date_key] = {
                    "date": date_key,
                    "sales": 0,
                    "settlement": 0,
                    "purchase": 0,
                    "shipping": 0,
                    "profit": 0,
                    "orders": 0
                }
            
            # 월 매출/순익 집계
            if not is_return:
                market_sales[store_key]["month_sales"] += payment
                market_sales[store_key]["month_orders"] += 1
                market_sales[store_key]["month_profit"] += profit
                market_sales[store_key]["month_settlement"] += settlement
                market_sales[store_key]["month_purchase"] += purchase
                market_sales[store_key]["month_shipping"] += int_shipping + cargo_shipping
                
                # 2주 이내 주문
                if order_date >= days_14_ago:
                    market_sales[store_key]["orders_2w"] = market_sales[store_key].get("orders_2w", 0) + 1
                
                # 일자별 집계
                daily_sales[date_key]["sales"] += payment
                daily_sales[date_key]["settlement"] += settlement
                daily_sales[date_key]["purchase"] += purchase
                daily_sales[date_key]["shipping"] += int_shipping + cargo_shipping
                daily_sales[date_key]["profit"] += profit
                daily_sales[date_key]["orders"] += 1
            
            # 오늘 매출 집계
            if order_date == today and not is_return:
                market_sales[store_key]["today_sales"] += payment
                market_sales[store_key]["today_orders"] += 1
        
        # 일자별 데이터 정렬
        daily_list = sorted(daily_sales.values(), key=lambda x: x["date"])
        
        # 캐시 업데이트
        sales_cache["data"] = market_sales
        sales_cache["daily"] = daily_list
        sales_cache["updated_at"] = datetime.now()
        
        print(f"[매출집계] {len(market_sales)}개 계정 집계 완료 (취소:{skip_cancel}, 반품:{skip_return}, 30일이전:{skip_old} 제외)")
        
        # 전체 합계 계산
        total = {
            "sales": sum(m["month_sales"] for m in market_sales.values()),
            "settlement": sum(m["month_settlement"] for m in market_sales.values()),
            "purchase": sum(m["month_purchase"] for m in market_sales.values()),
            "shipping": sum(m["month_shipping"] for m in market_sales.values()),
            "profit": sum(m["month_profit"] for m in market_sales.values()),
            "orders": sum(m["month_orders"] for m in market_sales.values())
        }
        if total["sales"] > 0:
            total["profit_rate"] = round(total["profit"] / total["sales"] * 100, 2)
        else:
            total["profit_rate"] = 0
        
        # 사업자번호별 집계 데이터 변환 (set -> list)
        biz_sales_result = {}
        for biz_num, data in biz_sales.items():
            biz_sales_result[biz_num] = {
                **{k: v for k, v in data.items() if k != 'stores'},
                "stores": sorted(list(biz_to_stores.get(biz_num, data["stores"])))  # 계정목록의 모든 스토어 (없으면 매출 있는 스토어)
            }
        
        # 매출은 없지만 계정목록에 있는 사업자번호도 추가
        for biz_num, stores in biz_to_stores.items():
            if biz_num not in biz_sales_result:
                biz_sales_result[biz_num] = {
                    "sales": 0, "settlement": 0, "profit": 0,
                    "purchase": 0, "shipping": 0, "orders": 0,
                    "stores": sorted(list(stores))
                }
        
        return {
            "success": True, 
            "data": market_sales,
            "daily": daily_list,
            "total": total,
            "biz_sales": biz_sales_result,  # 사업자번호별 집계
            "count": len(market_sales),
            "tab": current_tab
        }
        
    except Exception as e:
        print(f"[매출집계] 오류: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "message": str(e)}


@app.get("/api/sales/top-products")
async def get_top_products(request: Request, limit: int = 40):
    """월간 TOP 판매 상품 조회"""
    get_current_user(request)
    
    from datetime import datetime
    from collections import defaultdict
    
    try:
        # 현재 월 탭 이름
        current_month = datetime.now().month
        current_tab = f"{current_month}월"
        today = datetime.now().date()
        days_30_ago = today - timedelta(days=30)
        
        # 시트 열기
        sales_sheet = gsheet.client.open_by_key(SALES_SHEET_ID)
        
        all_data = []
        headers = None
        
        # 이번달 데이터 로드
        try:
            ws = sales_sheet.worksheet(current_tab)
            tab_data = ws.get_all_values()
            if len(tab_data) >= 3:
                headers = tab_data[1]  # 2행이 헤더
                all_data = tab_data[2:]  # 3행부터 데이터
        except Exception as e:
            print(f"[TOP상품] {current_tab} 탭 로드 실패: {e}")
            return {"success": False, "message": f"탭 로드 실패: {e}"}
        
        if not headers or len(all_data) < 1:
            return {"success": True, "data": [], "message": "데이터 없음"}
        
        # 컬럼 인덱스 찾기
        def find_col(names):
            for name in names:
                for idx, h in enumerate(headers):
                    h_clean = h.replace('\n', '').replace('\r', '').replace(' ', '')
                    name_clean = name.replace(' ', '')
                    if name_clean in h_clean:
                        return idx
            return -1
        
        def col_letter_to_idx(letter):
            letter = letter.upper()
            result = 0
            for char in letter:
                result = result * 26 + (ord(char) - ord('A') + 1)
            return result - 1
        
        col_market = find_col(["마켓"])
        col_owner = find_col(["사업자"])  # 스토어명으로 사용
        col_order_date = find_col(["주문일자"])
        col_order_status = find_col(["주문현황"])
        col_product_name = find_col(["상품명", "품명", "제품명"])
        col_quantity = find_col(["수량", "주문수량"])
        col_payment = find_col(["실결제금액(배송비포함)", "실결제금액"])
        col_seller_code = find_col(["판매자상품코드", "상품코드", "판매자 상품코드"])
        
        # 못 찾은 컬럼 직접 지정
        if col_order_status < 0: col_order_status = col_letter_to_idx('D')
        if col_market < 0: col_market = col_letter_to_idx('E')
        if col_owner < 0: col_owner = col_letter_to_idx('F')
        if col_order_date < 0: col_order_date = col_letter_to_idx('G')
        if col_product_name < 0: col_product_name = col_letter_to_idx('K')  # K열: 상품명
        if col_seller_code < 0: col_seller_code = col_letter_to_idx('J')  # J열: 판매자상품코드
        if col_quantity < 0: col_quantity = col_letter_to_idx('T')  # T열: 수량
        if col_payment < 0: col_payment = col_letter_to_idx('X')
        
        # 플랫폼 스펠링 변환
        def get_platform_short(platform):
            platform = platform.strip()
            if '스마트스토어' in platform or '네이버' in platform:
                return 'N'
            elif '쿠팡' in platform:
                return 'C'
            elif '11번가' in platform:
                return '11'
            elif '지마켓' in platform:
                return 'G'
            elif '옥션' in platform:
                return 'A'
            return platform[:2] if platform else '-'
        
        print(f"[TOP상품] 컬럼 - 마켓:{col_market}, 스토어:{col_owner}, 상품명:{col_product_name}, 판매자코드:{col_seller_code}")
        
        # 상품별 집계 (판매자상품코드 + 스토어 기준)
        product_sales = defaultdict(lambda: {"order_count": 0, "total_quantity": 0, "total_sales": 0, "스토어명": "", "platform": "", "product_name": "", "seller_code": ""})
        
        for row in all_data:
            if len(row) <= max(col_market, col_order_date, col_payment, col_product_name):
                continue
            
            # 주문현황 체크 (취소/반품 제외)
            order_status = row[col_order_status] if col_order_status < len(row) else ""
            if any(x in order_status for x in ["취소", "반품", "환불"]):
                continue
            
            # 주문일자 체크 (30일 이내)
            try:
                date_str = row[col_order_date].strip()
                if len(date_str) >= 10:
                    order_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                    if order_date < days_30_ago:
                        continue
            except:
                continue
            
            # 데이터 추출
            platform = row[col_market].strip() if col_market < len(row) else ""
            store_name = row[col_owner].strip() if col_owner < len(row) else ""
            product_name = row[col_product_name].strip() if col_product_name < len(row) else ""
            seller_code = row[col_seller_code].strip() if col_seller_code < len(row) else ""
            
            if not product_name:
                continue
            
            # 수량 파싱
            quantity = 1
            if col_quantity < len(row):
                try:
                    qty_str = row[col_quantity].replace(",", "").strip()
                    if qty_str:
                        quantity = int(float(qty_str))
                except:
                    pass
            
            # 금액 파싱
            payment = 0
            if col_payment < len(row):
                try:
                    pay_str = row[col_payment].replace(",", "").replace("원", "").strip()
                    if pay_str:
                        payment = int(float(pay_str))
                except:
                    pass
            
            # 상품 키 생성 (스토어명 + 판매자상품코드 또는 상품명)
            key = f"{store_name}||{seller_code or product_name}"
            product_sales[key]["order_count"] += 1  # 주문 건수 (수량과 상관없이 1건)
            product_sales[key]["total_quantity"] += quantity  # 총 수량
            product_sales[key]["total_sales"] += payment
            product_sales[key]["스토어명"] = store_name
            product_sales[key]["platform"] = get_platform_short(platform)
            product_sales[key]["product_name"] = product_name
            product_sales[key]["seller_code"] = seller_code
        
        # TOP N 정렬 (주문 건수 기준)
        sorted_products = sorted(
            product_sales.values(),
            key=lambda x: x["order_count"],
            reverse=True
        )[:limit]
        
        print(f"[TOP상품] {len(product_sales)}개 상품 중 TOP {limit} 반환")
        
        return {
            "success": True,
            "data": sorted_products,
            "total_products": len(product_sales)
        }
        
    except Exception as e:
        print(f"[TOP상품] 오류: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "message": str(e)}


# ========== 매출 조회 API ==========
class SalesQueryRequest(BaseModel):
    stores: List[str]  # store_name 목록
    platform: str = "스마트스토어"

# 매출 조회 상태
sales_query_status = {
    "running": False,
    "progress": {},
    "logs": [],
    "stop_requested": False
}

def query_smartstore_sales(store_name: str, client_id: str, client_secret: str):
    """스마트스토어 매출 조회"""
    global sales_query_status
    
    def add_log(msg, status="info"):
        log_entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "store": store_name,
            "msg": msg,
            "status": status
        }
        sales_query_status["logs"].append(log_entry)
        print(f"[매출-{store_name}] {msg}")
    
    try:
        sales_query_status["progress"][store_name] = {"status": "토큰 발급 중...", "today": 0, "month": 0}
        
        # 토큰 발급 (기존 함수 사용)
        token = get_naver_token(client_id, client_secret)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        add_log("토큰 발급 완료")
        sales_query_status["progress"][store_name]["status"] = "매출 조회 중..."
        
        base_url = "https://api.commerce.naver.com/external"
        
        # 오늘 날짜
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")
        month_start = today.replace(day=1).strftime("%Y-%m-%d")
        
        # 주문 조회 (오늘)
        today_sales = 0
        today_orders = 0
        
        body = {
            "productOrderStatuses": ["PAYED", "DELIVERING", "DELIVERED", "PURCHASE_DECIDED"],
            "startPayedDate": f"{today_str}T00:00:00",
            "endPayedDate": f"{today_str}T23:59:59"
        }
        
        try:
            resp = requests.post(f"{base_url}/v1/pay-order/seller/product-orders/search", 
                               headers=headers, json=body)
            if resp.status_code == 200:
                orders = resp.json().get("data", [])
                today_orders = len(orders)
                for order in orders:
                    today_sales += int(order.get("totalPaymentAmount", 0))
        except Exception as e:
            add_log(f"오늘 매출 조회 오류: {e}", "error")
        
        # 이달 매출
        month_sales = 0
        month_orders = 0
        
        body["startPayedDate"] = f"{month_start}T00:00:00"
        body["endPayedDate"] = f"{today_str}T23:59:59"
        
        try:
            resp = requests.post(f"{base_url}/v1/pay-order/seller/product-orders/search", 
                               headers=headers, json=body)
            if resp.status_code == 200:
                orders = resp.json().get("data", [])
                month_orders = len(orders)
                for order in orders:
                    month_sales += int(order.get("totalPaymentAmount", 0))
        except Exception as e:
            add_log(f"이달 매출 조회 오류: {e}", "error")
        
        today_sales_str = format(today_sales, ',')
        month_sales_str = format(month_sales, ',')
        
        sales_query_status["progress"][store_name] = {
            "status": f"완료 (오늘 {today_sales_str}원)",
            "today_sales": today_sales,
            "today_orders": today_orders,
            "month_sales": month_sales,
            "month_orders": month_orders
        }
        
        add_log(f"오늘 {today_sales_str}원 ({today_orders}건) / 이달 {month_sales_str}원 ({month_orders}건)", "success")
        
        return {
            "today_sales": today_sales,
            "today_orders": today_orders,
            "month_sales": month_sales,
            "month_orders": month_orders
        }
        
    except Exception as e:
        add_log(f"오류: {str(e)}", "error")
        sales_query_status["progress"][store_name]["status"] = f"오류: {str(e)[:30]}"
        return None

@app.post("/api/allinone/sales-query")
async def run_sales_query(request: Request, req: SalesQueryRequest):
    """매출 조회 실행"""
    require_permission(request, "edit")

    global sales_query_status

    if sales_query_status["running"]:
        return {"success": False, "message": "이미 실행 중입니다"}

    if not req.stores:
        return {"success": False, "message": "스토어를 선택하세요"}

    # 작업 로그 기록
    store_names = ", ".join(req.stores[:5]) + ("..." if len(req.stores) > 5 else "")
    log_work("매출조회", "스마트스토어", len(req.stores), f"대상: {store_names}", "웹")
    
    # 계정목록 시트에서 API 정보 가져오기
    try:
        ws = gsheet.sheet.worksheet(ACCOUNTS_TAB)  # 계정목록
        data = ws.get_all_values()
        headers = data[0]

        # 컬럼 인덱스 찾기 (계정목록 컬럼명)
        name_idx = None
        id_idx = None
        secret_idx = None
        platform_idx = None
        for i, h in enumerate(headers):
            if h in ["스토어명", "store_name"]:
                name_idx = i
            elif h in ["스마트스토어 애플리케이션 ID", "client_id"]:
                id_idx = i
            elif h in ["스마트스토어 애플리케이션 시크릿", "client_secret"]:
                secret_idx = i
            elif h in ["플랫폼", "platform"]:
                platform_idx = i

        if None in [name_idx, id_idx, secret_idx]:
            return {"success": False, "message": "시트에 필요한 컬럼이 없습니다 (스토어명, 스마트스토어 애플리케이션 ID/시크릿)"}

        store_info = {}
        for row in data[1:]:
            if len(row) > max(name_idx, id_idx, secret_idx):
                # 플랫폼 체크 (스마트스토어만)
                platform = row[platform_idx].lower() if platform_idx and len(row) > platform_idx else ""
                if platform and platform not in ["스마트스토어", "smartstore", "네이버", "naver"]:
                    continue
                name = row[name_idx]
                if name in req.stores:
                    store_info[name] = {
                        "client_id": row[id_idx],
                        "client_secret": row[secret_idx]
                    }

        if not store_info:
            return {"success": False, "message": "선택된 스토어 정보를 찾을 수 없습니다"}

    except Exception as e:
        return {"success": False, "message": f"시트 조회 오류: {str(e)}"}

    # 상태 초기화
    sales_query_status = {
        "running": True,
        "progress": {},
        "logs": [],
        "stop_requested": False
    }
    
    def run_parallel():
        global sales_query_status
        
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            with ThreadPoolExecutor(max_workers=min(5, len(store_info))) as executor:
                futures = {}
                for store_name, info in store_info.items():
                    future = executor.submit(
                        query_smartstore_sales,
                        store_name,
                        info["client_id"],
                        info["client_secret"]
                    )
                    futures[future] = store_name
                
                for future in as_completed(futures):
                    store_name = futures[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        print(f"[매출] {store_name} 스레드 오류: {e}")
        
        finally:
            sales_query_status["running"] = False
    
    import threading
    threading.Thread(target=run_parallel, daemon=True).start()
    
    return {"success": True, "message": f"{len(store_info)}개 스토어 매출 조회 시작"}

@app.get("/api/allinone/sales-progress")
async def get_sales_progress(request: Request):
    """매출 조회 진행상황"""
    require_permission(request, "edit")
    return sales_query_status

@app.post("/api/allinone/sales-stop")
async def stop_sales_query(request: Request):
    """매출 조회 중지"""
    require_permission(request, "edit")
    global sales_query_status
    sales_query_status["stop_requested"] = True
    return {"success": True, "message": "중지 요청됨"}


class AioSingleRunRequest(BaseModel):
    platform: str
    login_id: str
    task: str

@app.post("/api/allinone/run-single")
async def run_single_allinone_task(request: Request, req: AioSingleRunRequest):
    """개별 계정 올인원 작업 실행"""
    require_permission(request, "edit")

    # 플랫폼별 상태 가져오기
    platform_status = get_aio_status(req.platform)

    if platform_status["running"]:
        return {"success": False, "message": f"{req.platform} 작업이 실행 중입니다"}

    print(f"[올인원] 개별 실행: {req.platform} / {req.login_id} / {req.task}")

    # 작업 로그 기록
    log_work(f"올인원-{req.task}", req.platform, 1, f"계정: {req.login_id}", "웹")
    
    try:
        if req.platform == "스마트스토어":
            # stores 시트에서 해당 계정만 active 설정
            ws_stores = gsheet.sheet.worksheet("stores")
            data = ws_stores.get_all_values()
            headers = data[0]
            
            # active와 shop_alias 컬럼 찾기
            active_col = headers.index("active") + 1 if "active" in headers else 1
            shop_col = headers.index("shop_alias") + 1 if "shop_alias" in headers else 2
            
            # 모든 계정 비활성화 후 대상 계정만 활성화
            updates = []
            target_row = None
            for i, row in enumerate(data[1:], start=2):
                shop_alias = row[shop_col - 1] if len(row) >= shop_col else ""
                if shop_alias == req.login_id:
                    updates.append({"range": f"{chr(64+active_col)}{i}", "values": [["TRUE"]]})
                    target_row = i
                else:
                    updates.append({"range": f"{chr(64+active_col)}{i}", "values": [["FALSE"]]})
            
            if not target_row:
                return {"success": False, "message": "계정을 찾을 수 없습니다"}
            
            # 일괄 업데이트
            ws_stores.batch_update(updates)
            
            # 작업 설정
            ws_stores.update_acell("A1", req.task)
            
            # 로그 파일 경로
            log_file = os.path.join(os.path.dirname(__file__), "logs", "allinone.log")
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            
            # 상태 초기화
            aio_status = {
                "running": True,
                "process": None,
                "status": "running",
                "progress": 0,
                "results": [],
                "current_store": req.login_id,
                "current_action": f"{req.task} 준비 중...",
                "total": 1,
                "completed": 0,
                "logs": [],
                "log_file": log_file,
                "log_pos": 0
            }
            
            # 로그 파일 초기화
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {req.login_id} - {req.task} 시작\n")
            
            # subprocess로 실행
            script_path = r"C:\autosystem\smartstore_all_in_one_v1_1.py"
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            
            with open(log_file, "a", encoding="utf-8") as log_f:
                process = subprocess.Popen(
                    ["python", script_path],
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    env=env,
                    cwd=os.path.dirname(script_path)
                )
            
            aio_status["process"] = process
            
            return {"success": True, "message": f"{req.login_id} - {req.task} 시작됨"}
            
        elif req.platform == "11번가":
            # 11번가 시트에서 해당 계정만 active 설정
            ws = gsheet.sheet.worksheet("11번가")
            data = ws.get_all_values()
            headers = data[0]
            
            active_col = headers.index("active") + 1 if "active" in headers else 1
            store_col = headers.index("store_name") + 1 if "store_name" in headers else 2
            
            updates = []
            target_row = None
            for i, row in enumerate(data[1:], start=2):
                store_name = row[store_col - 1] if len(row) >= store_col else ""
                if store_name == req.login_id:
                    updates.append({"range": f"{chr(64+active_col)}{i}", "values": [["TRUE"]]})
                    target_row = i
                else:
                    updates.append({"range": f"{chr(64+active_col)}{i}", "values": [["FALSE"]]})
            
            if not target_row:
                return {"success": False, "message": "계정을 찾을 수 없습니다"}
            
            ws.batch_update(updates)
            
            # 로그 파일 경로
            log_file = os.path.join(os.path.dirname(__file__), "logs", "allinone.log")
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            
            aio_status = {
                "running": True,
                "process": None,
                "status": "running",
                "progress": 0,
                "results": [],
                "current_store": req.login_id,
                "current_action": f"{req.task} 준비 중...",
                "total": 1,
                "completed": 0,
                "logs": [],
                "log_file": log_file,
                "log_pos": 0
            }
            
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {req.login_id} - {req.task} 시작\n")
            
            module_path = os.path.join(os.path.dirname(__file__), "modules", "elevenst.py")
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["ELEVENST_TASK"] = req.task
            
            service_account_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
            if service_account_path:
                env["SERVICE_ACCOUNT_JSON"] = service_account_path
                env["GOOGLE_SERVICE_ACCOUNT_FILE"] = service_account_path
            spreadsheet_key = os.getenv("SPREADSHEET_KEY", "")
            if spreadsheet_key:
                env["SPREADSHEET_KEY"] = spreadsheet_key
            
            with open(log_file, "a", encoding="utf-8") as log_f:
                process = subprocess.Popen(
                    ["python", module_path],
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    env=env,
                    cwd=os.path.dirname(module_path)
                )
            
            aio_status["process"] = process
            
            return {"success": True, "message": f"{req.login_id} - {req.task} 시작됨"}
        
        else:
            return {"success": False, "message": f"{req.platform}은 아직 지원하지 않습니다"}
            
    except Exception as e:
        print(f"[올인원] 개별 실행 오류: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "message": str(e)}

# ========== 일일장부 주문/배송 동기화 API ==========

sync_state = {
    "status": "ready",  # ready, running, completed, error
    "logs": [],
    "last_check_index": 0
}

def add_sync_log(message: str, type: str = "info"):
    sync_state["logs"].append({
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "message": message,
        "type": type
    })
    if len(sync_state["logs"]) > 200:
        sync_state["logs"] = sync_state["logs"][-200:]
    print(f"[동기화] {message}")

@app.post("/api/sync/daily-journal")
async def start_sync_daily_journal(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    sheet_url: str = Form(...),
    month: str = Form(...),
    sync_order_info: str = Form("false"),
    sync_logistics: str = Form("false")
):
    try:
        require_permission(request, "edit")

        if sync_state["status"] == "running":
            return {"success": False, "message": "이미 동기화가 진행 중입니다."}

        # 작업 로그 기록
        log_work("일일장부동기화", month, 0, f"파일: {file.filename}", "웹")
        
        # 상태 초기화
        sync_state["status"] = "running"
        sync_state["logs"] = []
        sync_state["last_check_index"] = 0
        
        # 파일 읽기
        try:
            content = await file.read()
            # pandas로 읽기 가능한 형태로 전환
            if file.filename.endswith('.csv'):
                df_source = pd.read_csv(io.BytesIO(content))
            else:
                # xlsx, xls 등 처리
                df_source = pd.read_excel(io.BytesIO(content))
                
            add_sync_log(f"파일 업로드 성공: {file.filename} ({len(df_source)}행)")
        except Exception as e:
            sync_state["status"] = "error"
            print(f"[동기화] 파일 읽기 오류: {e}")
            return {"success": False, "message": f"파일 읽기 실패: {e}"}
        
        # 작업 데이터 구성
        job_data = {
            "df_source": df_source,
            "sheet_url": sheet_url,
            "month": month,
            "sync_order_info": sync_order_info.lower() == "true",
            "sync_logistics": sync_logistics.lower() == "true"
        }
        
        background_tasks.add_task(run_daily_journal_sync, job_data)
        return {"success": True}
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        sync_state["status"] = "error"
        return {"success": False, "message": f"서버 오류: {str(e)}"}

@app.get("/api/sync/status")
async def get_sync_status():
    # 마지막 확인 이후의 로그만 반환
    logs = sync_state["logs"][sync_state["last_check_index"]:]
    sync_state["last_check_index"] = len(sync_state["logs"])
    
    return {
        "status": sync_state["status"],
        "logs": logs
    }

async def run_daily_journal_sync(data: dict):
    """일일장부 동기화 백그라운드 작업 (엑셀 기반) - 별도 모듈 분리됨"""
    global sync_state
    
    sync_state["status"] = "running"
    sync_state["logs"] = []

    def update_state(key, value):
        sync_state[key] = value

    try:
        month = data["month"]
        sheet_url = data["sheet_url"]
        df_source = data["df_source"]
        
        add_sync_log(f"동기화 작업 시작: {month} (데이터 {len(df_source)}건)")
        
        # 인증 파일 경로
        sync_credentials_path = str(APP_DIR / "autosms-466614-951e91617c69.json")
        
        # 모듈 실행
        syncer = DailyJournalSyncer(sync_credentials_path)
        syncer.run_sync(sheet_url, month, df_source, add_sync_log, update_state)

    except Exception as e:
        import traceback
        traceback.print_exc()
        add_sync_log(f"실행 중 예외 발생: {e}", "error")
        sync_state["status"] = "error"

# ========== 알리 송장 수집 API ==========

ali_collect_status = {
    "running": False,
    "connected": False,
    "progress": 0,
    "total": 0,
    "current": "",
    "logs": [],
    "collected": []  # 수집된 송장 데이터
}

ali_browser = None  # playwright browser instance (async)
ali_playwright = None  # playwright instance (async)
ali_sync_browser = None  # playwright sync browser for collection
ali_sync_playwright = None  # playwright sync instance
ali_debug_port = None  # 연결된 Chrome 디버그 포트

def find_available_port(start: int = 9300, end: int = 9320) -> int:
    """사용 가능한 포트 자동 찾기"""
    import socket
    
    for port in range(start, end):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            
            if result != 0:  # 포트 사용 안 함
                print(f"[알리] 사용 가능한 포트 발견: {port}")
                return port
            else:
                print(f"[알리] 포트 {port} 사용 중, 다음 포트 확인...")
        except:
            continue
    
    print(f"[알리] 사용 가능한 포트 없음, 기본값 {start} 사용")
    return start

def find_existing_ali_chrome() -> int:
    """기존 실행 중인 알리 Chrome 포트 찾기 (9300~9320 범위)"""
    import socket
    
    for port in range(9300, 9320):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            
            if result == 0:  # 포트 사용 중
                print(f"[알리] 기존 Chrome 감지: 포트 {port}")
                return port
        except:
            continue
    
    return None

@app.post("/api/ali/connect")
async def connect_ali_browser(request: Request):
    """알리 브라우저 연결 (기존 Chrome 연결 또는 새로 실행)"""
    get_current_user(request)
    
    data = await request.json()
    requested_port = int(data.get("debug_port", 9300))
    
    global ali_browser, ali_playwright, ali_collect_status, ali_debug_port
    
    try:
        from playwright.async_api import async_playwright
        import subprocess
        import shutil
        
        # 1. 기존 알리 Chrome이 있는지 확인 (9300~9320 범위)
        existing_port = find_existing_ali_chrome()
        
        if existing_port:
            # 기존 Chrome에 연결 시도
            try:
                ali_playwright = await async_playwright().start()
                ali_browser = await ali_playwright.chromium.connect_over_cdp(f"http://localhost:{existing_port}")
                
                ali_debug_port = existing_port  # 포트 저장
                ali_collect_status["connected"] = True
                ali_collect_status["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] 기존 Chrome 연결 성공 (포트: {existing_port})")
                
                return {"success": True, "message": f"기존 Chrome 연결 성공 (포트: {existing_port})"}
            except Exception as e:
                print(f"[알리] 기존 Chrome 연결 실패: {e}")
        
        # 2. 새로운 Chrome 실행
        available_port = find_available_port(9300, 9320)
        
        # Chrome 경로 찾기
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        
        chrome_path = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_path = path
                break
        
        if not chrome_path:
            chrome_path = shutil.which("chrome") or shutil.which("google-chrome")
        
        if not chrome_path:
            return {"success": False, "message": "Chrome을 찾을 수 없습니다"}
        
        # 알리 전용 프로필 디렉토리
        ali_profile_dir = os.path.join(APP_DIR, "chrome_ali_profile")
        
        # Chrome 디버그 모드로 실행
        cmd = [
            chrome_path,
            f"--remote-debugging-port={available_port}",
            f"--user-data-dir={ali_profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "https://www.aliexpress.com"
        ]
        
        print(f"[알리] Chrome 실행 (포트 {available_port}): {' '.join(cmd)}")
        subprocess.Popen(cmd)
        
        # Chrome 시작 대기
        await asyncio.sleep(4)
        
        # Playwright로 연결 (재시도)
        ali_playwright = await async_playwright().start()
        
        for retry in range(5):
            try:
                ali_browser = await ali_playwright.chromium.connect_over_cdp(f"http://localhost:{available_port}")
                break
            except Exception as e:
                if retry < 4:
                    print(f"[알리] 연결 대기중... ({retry+1}/5)")
                    await asyncio.sleep(2)
                else:
                    raise e
        
        ali_collect_status["connected"] = True
        ali_collect_status["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] 브라우저 연결 성공 (포트: {available_port})")
        ali_debug_port = available_port  # 포트 저장
        
        return {"success": True, "message": f"브라우저 실행 및 연결 성공 (포트: {available_port}). 알리익스프레스 로그인 후 '수집 시작' 클릭"}
        
    except Exception as e:
        ali_collect_status["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] 연결 실패: {e}")
        return {"success": False, "message": f"연결 실패: {e}"}

class AliCollectRequest(BaseModel):
    sheet_url: str
    month: str

@app.post("/api/tools/ali/collect")
async def ali_collect(request: Request, req: AliCollectRequest):
    require_permission(request, "edit")

    global ali_collect_status, ali_browser

    if not ali_browser or not ali_collect_status.get("connected"):
        return {"success": False, "message": "브라우저가 연결되지 않았습니다. '브라우저 연결'을 먼저 클릭하세요."}

    # 이미 실행 중이면 거부
    if ali_collect_status["running"]:
        return {"success": False, "message": "이미 수집 중입니다."}

    # 작업 로그 기록
    log_work("알리송장수집", "알리익스프레스", 0, f"월: {req.month}", "웹")
    
    # 시트 ID 추출
    import re
    sheet_id = req.sheet_url
    if 'docs.google.com' in sheet_id:
        match = re.search(r'/d/([a-zA-Z0-9_-]+)', sheet_id)
        if match:
            sheet_id = match.group(1)
    
    # 상태 초기화
    ali_collect_status = {
        "running": True,
        "progress": 0,
        "total": 0,
        "completed": 0,
        "logs": [],
        "message": "시작 중...",
        "collected": []  # 수집된 데이터
    }
    
    def add_ali_log(msg, status="info"):
        ali_collect_status["logs"].append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "msg": msg,
            "status": status
        })
        if len(ali_collect_status["logs"]) > 100:
            ali_collect_status["logs"] = ali_collect_status["logs"][-100:]
        print(f"[알리] {msg}")
    
    def run_collection():
        global ali_collect_status
        try:
            add_ali_log(f"시트 ID: {sheet_id}, 월: {req.month}")
            
            # 알리 수집용 별도 JSON 파일 (APP_DIR 기준)
            ALI_CREDENTIALS = str(APP_DIR / "autosms-466614-951e91617c69.json")
            add_ali_log(f"인증 파일: {ALI_CREDENTIALS}")
            add_ali_log(f"인증 파일 존재: {os.path.exists(ALI_CREDENTIALS)}")
            
            if not os.path.exists(ALI_CREDENTIALS):
                add_ali_log(f"인증 파일 없음: {ALI_CREDENTIALS}", "error")
                ali_collect_status["running"] = False
                return
            
            # 시트 연결
            from google.oauth2.service_account import Credentials
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            creds = Credentials.from_service_account_file(ALI_CREDENTIALS, scopes=scopes)
            ali_client = gspread.authorize(creds)
            
            spreadsheet = ali_client.open_by_key(sheet_id)
            sheet = spreadsheet.worksheet(req.month)
            add_ali_log(f"시트 연결 성공: {spreadsheet.title} / {req.month}")
            
            # 열 위치
            COL_PLATFORM = 30  # AD
            COL_ORDER_ID = 31  # AE
            COL_CARRIER = 43   # AQ
            COL_TRACKING = 44  # AR
            START_ROW = 3
            
            all_data = sheet.get_all_values()
            add_ali_log(f"전체 데이터 행 수: {len(all_data)}")
            
            # 대상 찾기
            targets = []
            for idx, row in enumerate(all_data):
                row_num = idx + 1
                if row_num < START_ROW:
                    continue
                
                platform = row[COL_PLATFORM - 1] if len(row) >= COL_PLATFORM else ""
                order_id = row[COL_ORDER_ID - 1] if len(row) >= COL_ORDER_ID else ""
                tracking = row[COL_TRACKING - 1] if len(row) >= COL_TRACKING else ""
                
                if platform.strip() == "알리" and order_id.strip() and not tracking.strip():
                    targets.append({'row': row_num, 'order_id': order_id.strip()})
            
            add_ali_log(f"조회 대상: {len(targets)}건")
            ali_collect_status["total"] = len(targets)
            
            if not targets:
                add_ali_log("조회할 건이 없습니다", "success")
                ali_collect_status["running"] = False
                return
            
            # 수집 - sync_playwright 사용 (스레드에서 동기 방식으로)
            updated = 0
            
            # 택배사 구분 함수
            def get_carrier_name(tracking_no):
                tracking_no = str(tracking_no).strip()
                # CJ대한통운: 30, 50, 52, 56
                if tracking_no.startswith('30') or tracking_no.startswith('50') or tracking_no.startswith('52') or tracking_no.startswith('56'):
                    return 'CJ대한통운'
                # 한진택배: 51, 55, 58
                elif tracking_no.startswith('51') or tracking_no.startswith('55') or tracking_no.startswith('58'):
                    return '한진택배'
                # 경동택배: 68
                elif tracking_no.startswith('68'):
                    return '경동'
                # 로젠택배: 54
                elif tracking_no.startswith('54'):
                    return '로젠'
                # 투데이: 9
                elif tracking_no.startswith('9'):
                    return '투데이'
                return '확인필요'
            
            # sync_playwright로 Chrome에 연결
            from playwright.sync_api import sync_playwright
            
            if not ali_debug_port:
                add_ali_log("Chrome 디버그 포트를 찾을 수 없습니다. 브라우저를 다시 연결하세요.", "error")
                ali_collect_status["running"] = False
                return
            
            add_ali_log(f"Chrome 연결 중 (포트: {ali_debug_port})...")
            
            with sync_playwright() as p:
                try:
                    sync_browser = p.chromium.connect_over_cdp(f"http://localhost:{ali_debug_port}")
                    add_ali_log("sync_playwright 연결 성공")
                except Exception as e:
                    add_ali_log(f"Chrome 연결 실패: {e}", "error")
                    ali_collect_status["running"] = False
                    return
                
                contexts = sync_browser.contexts
                if not contexts:
                    add_ali_log("브라우저 컨텍스트가 없습니다", "error")
                    ali_collect_status["running"] = False
                    return
                
                context = contexts[0]
                pages = context.pages
                if not pages:
                    add_ali_log("열린 페이지가 없습니다", "error")
                    ali_collect_status["running"] = False
                    return
                
                ali_page = pages[0]
                add_ali_log(f"페이지 연결 완료: {ali_page.url[:50]}...")
                
                for i, target in enumerate(targets):
                    if not ali_collect_status["running"]:
                        add_ali_log("사용자에 의해 중단됨", "info")
                        break
                    
                    ali_collect_status["completed"] = i
                    ali_collect_status["progress"] = int((i / len(targets)) * 100)
                    
                    add_ali_log(f"[{i+1}/{len(targets)}] 주문번호 {target['order_id']} 조회 중...")
                    
                    # 송장번호 조회
                    tracking_no = None
                    try:
                        url = f"https://www.aliexpress.com/p/tracking/index.html?_addShare=no&_login=yes&tradeOrderId={target['order_id']}"
                        
                        ali_page.goto(url, timeout=20000, wait_until="domcontentloaded")
                        time.sleep(2)
                        
                        page_text = ali_page.inner_text("body", timeout=10000)
                        
                        # 송장번호 추출
                        import re
                        match = re.search(r'운송장\s*번호[:\s]*(\d+)', page_text)
                        if match:
                            tracking_no = match.group(1)
                        else:
                            match = re.search(r'Tracking\s*(?:number|no)[:\s]*(\d+)', page_text, re.IGNORECASE)
                            if match:
                                tracking_no = match.group(1)
                            else:
                                # 국내 배송 송장번호 패턴
                                match = re.search(r'(\d{10,14})', page_text)
                                if match:
                                    potential = match.group(1)
                                    if potential[:2] in ['50', '51', '52', '54', '56'] or potential.startswith('9'):
                                        tracking_no = potential
                    except Exception as e:
                        add_ali_log(f"조회 오류: {e}", "error")
                    
                    if tracking_no:
                        carrier = get_carrier_name(tracking_no)
                        
                        # 투데이 택배인 경우 배송완료 체크
                        delivery_completed = False
                        if carrier == '투데이':
                            try:
                                # 배송완료 텍스트 확인
                                completed_el = ali_page.locator('.logistic-info-v2--nodeTitle--2rejjVx:has-text("배송 완료"), .logistic-info-v2--nodeTitle--2rejjVx:has-text("배송완료")')
                                if completed_el.count() > 0:
                                    delivery_completed = True
                                    add_ali_log(f"→ 송장번호: {tracking_no} ({carrier}) [배송완료]", "success")
                                else:
                                    add_ali_log(f"→ 송장번호: {tracking_no} ({carrier})", "success")
                            except:
                                add_ali_log(f"→ 송장번호: {tracking_no} ({carrier})", "success")
                        else:
                            add_ali_log(f"→ 송장번호: {tracking_no} ({carrier})", "success")
                        
                        # 수집 데이터 저장
                        ali_collect_status["collected"].append({
                            "customer_order": target.get('customer_order', ''),
                            "order_id": target['order_id'],
                            "carrier": carrier,
                            "tracking_no": tracking_no,
                            "delivery_completed": delivery_completed
                        })
                        
                        try:
                            sheet.update_cell(target['row'], COL_CARRIER, carrier)
                            sheet.update_cell(target['row'], COL_TRACKING, tracking_no)
                            updated += 1
                            add_ali_log(f"→ 행 {target['row']} 업데이트 완료")
                            
                            # 투데이 배송완료면 노란색 색칠
                            if delivery_completed:
                                try:
                                    # AQ, AR 컬럼 (43, 44)
                                    ws.format(f"AQ{target['row']}:AR{target['row']}", {
                                        "backgroundColor": {"red": 1, "green": 1, "blue": 0}
                                    })
                                    add_ali_log(f"→ 행 {target['row']} 노란색 색칠 (배송완료)")
                                except Exception as e:
                                    add_ali_log(f"→ 색칠 오류: {e}", "error")
                            
                            time.sleep(1)
                        except Exception as e:
                            add_ali_log(f"→ 시트 업데이트 오류: {e}", "error")
                    else:
                        add_ali_log("→ 송장번호 없음")
                    
                    time.sleep(2)
                
                # for 루프 끝 (with 블록 안)
                add_ali_log(f"완료! {updated}건 업데이트", "success")
                ali_collect_status["completed"] = len(targets)
                ali_collect_status["progress"] = 100
            
        except Exception as e:
            import traceback
            add_ali_log(f"오류: {e}", "error")
            traceback.print_exc()
        finally:
            ali_collect_status["running"] = False
    
    # 백그라운드 스레드로 실행
    import threading
    thread = threading.Thread(target=run_collection, daemon=True)
    thread.start()
    
    return {"success": True, "message": "수집 시작됨"}

@app.get("/api/tools/ali/progress")
async def ali_progress(request: Request):
    """알리 수집 진행상황 조회"""
    require_permission(request, "edit")
    return ali_collect_status

@app.get("/api/tools/ali/progress-stream")
async def ali_progress_stream(request: Request):
    """알리 수집 진행상황 SSE 스트림"""
    from fastapi.responses import StreamingResponse

    async def event_generator():
        last_log_count = 0
        last_completed = 0
        while True:
            current_log_count = len(ali_collect_status.get("logs", []))
            current_completed = ali_collect_status.get("completed", 0)

            # 변경사항이 있을 때만 전송
            if current_log_count != last_log_count or current_completed != last_completed or not ali_collect_status.get("running"):
                yield f"data: {json.dumps(ali_collect_status, ensure_ascii=False, default=str)}\n\n"
                last_log_count = current_log_count
                last_completed = current_completed

            # 수집 완료 또는 중지 (running=False면 종료)
            if ali_collect_status.get("running") == False:
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )

@app.post("/api/tools/ali/stop")
async def ali_stop(request: Request):
    require_permission(request, "edit")
    global ali_collect_status
    ali_collect_status["running"] = False
    return {"success": True}

@app.get("/api/tools/ali/download")
async def ali_download_excel(request: Request):
    """수집된 알리 송장 엑셀 다운로드"""
    require_permission(request, "edit")
    
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment
    from fastapi.responses import FileResponse
    import tempfile
    
    # 수집된 데이터 가져오기
    collected = ali_collect_status.get("collected", [])
    
    if not collected:
        raise HTTPException(status_code=400, detail="수집된 데이터가 없습니다")
    
    # 엑셀 생성
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    
    # 헤더 (양식에 맞춤)
    headers = ['고객 주문일', '고객 주문 번호', '해외 주문일', '해외 주문 번호', 
               '해외 택배사', '해외 운송장번호', '국내 택배사', '국내 운송장번호']
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')
    
    # 데이터 입력
    for row_idx, item in enumerate(collected, 2):
        ws.cell(row=row_idx, column=2, value=item.get("customer_order", ""))  # 고객 주문 번호
        ws.cell(row=row_idx, column=4, value=item.get("order_id", ""))  # 해외 주문 번호 (알리 주문번호)
        ws.cell(row=row_idx, column=7, value=item.get("carrier", ""))  # 국내 택배사
        ws.cell(row=row_idx, column=8, value=item.get("tracking_no", ""))  # 국내 운송장번호
    
    # 컬럼 너비 조정
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['D'].width = 20
    ws.column_dimensions['E'].width = 25
    ws.column_dimensions['F'].width = 20
    
    # 임시 파일로 저장
    today = datetime.now().strftime('%y%m%d')
    filename = f"송장_번호_다운로드_{today}.xlsx"
    filepath = Path(tempfile.gettempdir()) / filename
    wb.save(filepath)
    
    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ========== 클라이언트 프로그램 연동 API ==========
client_status = {"connected": False, "last_ping": None}

@app.get("/api/client/status")
async def get_client_status(request: Request):
    """클라이언트 연결 상태 확인"""
    # 마지막 ping이 10초 이내면 연결된 것으로 판단
    if client_status["last_ping"]:
        if datetime.now() - client_status["last_ping"] < timedelta(seconds=10):
            return {"connected": True}
    return {"connected": False}

@app.post("/api/client/ping")
async def client_ping(request: Request):
    """클라이언트에서 주기적으로 호출 (연결 유지)"""
    client_status["connected"] = True
    client_status["last_ping"] = datetime.now()
    return {"success": True}

@app.post("/api/auto-login/complete")
async def complete_login(request: Request):
    """로그인 완료 알림"""
    api_key = request.headers.get("X-API-Key")
    if api_key != "pkonomiautokey2024":
        raise HTTPException(status_code=401, detail="API 키 필요")
    data = await request.json()
    await ws_manager.broadcast({
        "type": "login_complete",
        "platform": data.get("platform"),
        "login_id": data.get("login_id"),
        "success": data.get("success", False)
    })
    return {"success": True}

@app.get("/download/PkonomyClient.exe")
async def download_client():
    """클라이언트 프로그램 다운로드"""
    from fastapi.responses import FileResponse
    client_path = APP_DIR / "PkonomyClient.exe"
    if not client_path.exists():
        client_path = Path(r"C:\autosystem\PkonomyClient.exe")
    if client_path.exists():
        return FileResponse(path=str(client_path), filename="PkonomyClient.exe", media_type="application/octet-stream")
    raise HTTPException(status_code=404, detail="클라이언트 파일 없음. 관리자에게 문의하세요.")


# ========== 11번가 API 상품수 조회 ==========
import xml.etree.ElementTree as ET

ST_API_BASE = "http://api.11st.co.kr"
ST_SEARCH_PATH = "/rest/prodmarketservice/prodmarket"


async def run_11st_product_count_task(log_file: str, platform: str = "11번가"):
    """11번가 판매중 조회 백그라운드 작업"""
    status = get_aio_status(platform)
    
    def write_log(msg):
        timestamp = datetime.now().strftime('%H:%M:%S')
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {msg}\n")
    
    try:
        # 11번가 시트에서 active인 스토어 조회
        ws = gsheet.sheet.worksheet("11번가")
        all_values = ws.get_all_values()
        
        if not all_values or len(all_values) < 2:
            write_log("11번가 시트가 비어있습니다")
            status["running"] = False
            status["status"] = "completed"
            return
        
        headers = all_values[0]
        
        # 컬럼 인덱스 찾기
        store_col = None
        active_col = None
        api_key_col = None
        on_sale_col = None
        last_reg_col = None
        result_col = None
        updated_col = None

        for i, h in enumerate(headers):
            if h in ["store_name", "쇼핑몰 별칭", "스토어명"]:
                store_col = i
            if h in ["active", "활성", "사용"]:
                active_col = i
            if h in ["api_key", "API KEY", "11번가 API KEY"]:
                api_key_col = i
            if h in ["on_sale", "판매중"]:
                on_sale_col = i
            if h in ["마지막등록일"]:
                last_reg_col = i
            if h in ["결과"]:
                result_col = i
            if h in ["updated_at"]:
                updated_col = i

        # 필수 헤더가 없으면 추가
        headers_modified = False
        if on_sale_col is None:
            headers.append("판매중")
            on_sale_col = len(headers) - 1
            headers_modified = True
        if last_reg_col is None:
            headers.append("마지막등록일")
            last_reg_col = len(headers) - 1
            headers_modified = True
        if updated_col is None:
            headers.append("updated_at")
            updated_col = len(headers) - 1
            headers_modified = True

        if headers_modified:
            ws.update(range_name="1:1", values=[headers], value_input_option="RAW")
            write_log(f"헤더 추가됨: 판매중={on_sale_col}, 마지막등록일={last_reg_col}, updated_at={updated_col}")

        if store_col is None or api_key_col is None:
            write_log(f"필수 열을 찾을 수 없음: store_col={store_col}, api_key_col={api_key_col}")
            status["running"] = False
            status["status"] = "completed"
            return
        
        # active인 스토어 필터링
        active_stores = []
        for row_idx, row in enumerate(all_values[1:], start=2):
            if len(row) <= max(store_col, active_col or 0, api_key_col):
                continue
            
            store_name = row[store_col].strip() if len(row) > store_col else ""
            active = row[active_col].strip() if active_col and len(row) > active_col else "TRUE"
            api_key = row[api_key_col].strip() if len(row) > api_key_col else ""
            
            if not store_name or not api_key:
                continue
            
            is_active = str(active).upper() in ["TRUE", "ON", "Y", "1", "사용", ""]
            if is_active:
                active_stores.append({
                    "row": row_idx,
                    "스토어명": store_name,
                    "api_key": api_key
                })
        
        write_log(f"조회 대상: {len(active_stores)}개 스토어")
        status["total"] = len(active_stores)
        
        # 병렬로 판매중 수량 조회 (5개씩 동시 처리)
        total_done = 0
        batch_size = 5

        def get_col_letter(idx):
            if idx < 26:
                return chr(65 + idx)
            return f"{chr(64 + idx // 26)}{chr(65 + idx % 26)}"

        for batch_start in range(0, len(active_stores), batch_size):
            if not status["running"]:
                write_log("작업 중지됨")
                break

            batch = active_stores[batch_start:batch_start + batch_size]
            batch_names = [s["스토어명"] for s in batch]

            status["current_store"] = ", ".join(batch_names)
            status["current_action"] = "판매중 조회 중..."
            status["completed"] = batch_start
            status["progress"] = int((batch_start / len(active_stores)) * 100)

            write_log(f"배치 조회: {batch_names}")

            # 배치 내 병렬 조회
            async def fetch_store_count(store):
                try:
                    count, last_reg = await get_11st_product_count_and_last_reg(store["api_key"])
                    return {
                        "row": store["row"],
                        "스토어명": store["스토어명"],
                        "count": count,
                        "last_reg": last_reg
                    }
                except Exception as e:
                    return {
                        "row": store["row"],
                        "스토어명": store["스토어명"],
                        "count": 0,
                        "last_reg": ""
                    }

            batch_results = await asyncio.gather(*[fetch_store_count(s) for s in batch])

            # 배치별로 바로 시트에 기록
            updates = []
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            for r in batch_results:
                write_log(f"[{r['스토어명']}] 판매중: {r['count']}개, 마지막등록: {r['last_reg'] or '-'}")

                # 판매중 수량
                if on_sale_col is not None:
                    cell = f"{get_col_letter(on_sale_col)}{r['row']}"
                    updates.append({"range": cell, "values": [[r["count"]]]})

                # 마지막등록일
                if last_reg_col is not None and r.get("last_reg"):
                    cell = f"{get_col_letter(last_reg_col)}{r['row']}"
                    updates.append({"range": cell, "values": [[r["last_reg"]]]})

                # 결과
                if result_col is not None:
                    cell = f"{get_col_letter(result_col)}{r['row']}"
                    result_text = f"판매중 {r['count']}개"
                    updates.append({"range": cell, "values": [[result_text]]})

                # 날짜
                if updated_col is not None:
                    cell = f"{get_col_letter(updated_col)}{r['row']}"
                    updates.append({"range": cell, "values": [[now_str]]})

            if updates:
                ws.batch_update(updates)
                write_log(f"배치 {len(batch_results)}개 시트 저장 완료")

            total_done += len(batch_results)
            await asyncio.sleep(0.3)  # 배치 간 간격

        write_log(f"완료: 총 {total_done}개 스토어 조회")
        
        status["running"] = False
        status["status"] = "completed"
        status["progress"] = 100
        status["current_store"] = ""
        status["current_action"] = "완료"
        
    except Exception as e:
        write_log(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()
        status["running"] = False
        status["status"] = "error"


async def get_11st_product_count_and_last_reg(api_key: str) -> tuple:
    """11번가 판매중 상품수 + 최신 등록일 조회 - 병렬 페이징"""
    if not api_key:
        return 0, ""

    import re

    def fetch_page(page: int) -> tuple:
        """한 페이지 상품번호 + 날짜 조회"""
        limit = 500
        parts = ["<SearchProduct>"]
        parts.append("    <selStatCd>103</selStatCd>")
        parts.append(f"    <limit>{limit}</limit>")
        if page > 0:
            start = page * limit + 1
            parts.append(f"    <start>{start}</start>")
        parts.append("</SearchProduct>")
        xml_body = "\n".join(parts)

        headers = {
            "openapikey": api_key,
            "Content-Type": "text/xml;charset=euc-kr",
            "Accept": "application/xml",
        }

        try:
            data = xml_body.encode("euc-kr", errors="ignore")
            res = requests.post(
                f"{ST_API_BASE}{ST_SEARCH_PATH}",
                headers=headers,
                data=data,
                timeout=30
            )

            if res.status_code != 200:
                return [], []

            raw = res.content.decode("euc-kr", errors="ignore")

            # prdNo + aplBgnDy 파싱
            prd_list = []
            date_list = []
            try:
                root = ET.fromstring(raw)
                for prod in root.iter():
                    if prod.tag.endswith("product"):
                        prd_no = ""
                        apl_bgn = ""
                        for child in prod:
                            if child.tag.endswith("prdNo"):
                                prd_no = (child.text or "").strip()
                            elif "aplBgnDy" in child.tag:
                                apl_bgn = (child.text or "").strip()[:10]
                        if prd_no:
                            prd_list.append(prd_no)
                            if apl_bgn:
                                date_list.append(apl_bgn)
            except Exception as e:
                print(f"[11번가] XML 파싱 오류: {e}")

            return prd_list, date_list
        except:
            return [], []

    def fetch_all():
        from concurrent.futures import ThreadPoolExecutor, as_completed

        all_prd = set()
        all_dates = []
        limit = 500

        # 첫 페이지 조회
        first_page, first_dates = fetch_page(0)
        if not first_page:
            return 0, ""

        for p in first_page:
            all_prd.add(p)
        all_dates.extend(first_dates)

        print(f"[11번가] 첫 페이지: {len(first_page)}개")

        # 첫 페이지가 가득 찼으면 추가 페이지 병렬 조회
        if len(first_page) >= limit:
            max_pages = 20
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(fetch_page, p): p for p in range(1, max_pages)}

                for future in as_completed(futures):
                    page_result, page_dates = future.result()
                    if not page_result:
                        continue

                    for p in page_result:
                        all_prd.add(p)
                    all_dates.extend(page_dates)

        # 가장 최신 날짜 찾기
        latest_date = ""
        print(f"[11번가] 수집된 날짜 수: {len(all_dates)}개")
        if all_dates:
            print(f"[11번가] 날짜 샘플: {all_dates[:5]}")
            # 날짜 형식 통일 후 정렬
            normalized_dates = []
            for d in all_dates:
                if len(d) == 8 and d.isdigit():
                    # YYYYMMDD -> YYYY-MM-DD
                    normalized_dates.append(f"{d[:4]}-{d[4:6]}-{d[6:8]}")
                elif "-" in d:
                    normalized_dates.append(d[:10])
                elif "/" in d:
                    # YYYY/MM/DD 형식
                    normalized_dates.append(d[:10].replace("/", "-"))
            if normalized_dates:
                normalized_dates.sort(reverse=True)
                latest_date = normalized_dates[0]
                print(f"[11번가] 최신 날짜: {latest_date}")

        print(f"[11번가] 총 상품수: {len(all_prd)}개, 최신등록일: {latest_date}")
        return len(all_prd), latest_date

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_all)


async def get_11st_product_count(api_key: str) -> int:
    """11번가 판매중 상품수 조회 (하위호환용)"""
    count, _ = await get_11st_product_count_and_last_reg(api_key)
    return count


def get_11st_last_registration_date(api_key: str) -> str:
    """11번가 최신 등록일 조회 (동기 버전 - 하위호환용)"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        _, last_reg = loop.run_until_complete(get_11st_product_count_and_last_reg(api_key))
        return last_reg
    except:
        return ""


# 11번가 상품수 캐시
st_product_cache: Dict[str, dict] = {}  # {login_id: {"count": 1234, "time": datetime}}
ST_CACHE_TTL = 300  # 5분 캐시

@app.get("/api/11st/product-count/{login_id}")
async def get_11st_count(request: Request, login_id: str):
    """11번가 개별 계정 상품수 조회"""
    get_current_user(request)
    
    # 캐시 확인
    cached = st_product_cache.get(login_id)
    if cached:
        elapsed = (datetime.now() - cached["time"]).total_seconds()
        if elapsed < ST_CACHE_TTL:
            return {"success": True, "count": cached["count"], "cached": True}
    
    # 계정 찾기
    accounts = gsheet.get_accounts("11번가")
    acc = None
    for a in accounts:
        if a.get("login_id") == login_id:
            acc = a
            break
    
    if not acc:
        return {"success": False, "error": "계정을 찾을 수 없음"}
    
    api_key = acc.get("st_api_key", "")
    if not api_key:
        return {"success": False, "error": "API KEY 없음"}
    
    count = await get_11st_product_count(api_key)
    
    # 캐시 저장
    st_product_cache[login_id] = {"count": count, "time": datetime.now()}
    
    return {"success": True, "count": count, "cached": False}


@app.get("/api/market-summary")
async def get_market_summary(request: Request):
    """마켓별 현황 요약 (표 형식용)"""
    get_current_user(request)
    
    try:
        # 1. 등록갯수 시트에서 스마트스토어 상품수 가져오기
        ss_counts = {}
        try:
            ws_counts = gsheet.sheet.worksheet("등록갯수")
            counts_data = ws_counts.get_all_values()
            if counts_data and len(counts_data) > 1:
                headers = counts_data[0]
                name_idx = None
                count_idx = None
                for i, h in enumerate(headers):
                    if h == "스토어명":
                        name_idx = i
                    elif h == "판매중":
                        count_idx = i
                
                if name_idx is not None and count_idx is not None:
                    for row in counts_data[1:]:
                        if len(row) > max(name_idx, count_idx):
                            store = row[name_idx].strip()
                            try:
                                cnt = int(row[count_idx]) if row[count_idx] else 0
                            except:
                                cnt = 0
                            if store:
                                ss_counts[store] = cnt
        except Exception as e:
            print(f"[마켓현황] 등록갯수 시트 오류: {e}")
        
        # 1-2. 11번가 시트에서 상품수 가져오기 (store_name -> 판매중 매핑)
        st_counts = {}
        try:
            ws_11st = gsheet.sheet.worksheet("11번가")
            st_data = ws_11st.get_all_values()
            if st_data and len(st_data) > 1:
                headers = st_data[0]
                name_idx = None
                count_idx = None
                for i, h in enumerate(headers):
                    if h in ["store_name", "쇼핑몰 별칭", "스토어명"]:
                        name_idx = i
                    elif h in ["on_sale", "판매중"]:
                        count_idx = i
                
                if name_idx is not None and count_idx is not None:
                    for row in st_data[1:]:
                        if len(row) > max(name_idx, count_idx):
                            store = row[name_idx].strip()
                            try:
                                cnt = int(row[count_idx]) if row[count_idx] else 0
                            except:
                                cnt = 0
                            if store:
                                st_counts[store] = cnt
        except Exception as e:
            print(f"[마켓현황] 11번가 시트 오류: {e}")
        
        # 2. 마켓상태현황 시트에서 상태/페널티 정보 가져오기
        status_map = {}
        try:
            ws_status = gsheet.sheet.worksheet(MARKET_STATUS_TAB)
            status_records = ws_status.get_all_records()
            for row in status_records:
                store = row.get("스토어명", "")
                plat = row.get("플랫폼", "")
                if store and plat:
                    status_map[f"{store}_{plat}"] = {
                        "status": row.get("상태", "정상"),
                        "caution_count": int(row.get("주의", 0) or 0),
                        "warning_count": int(row.get("경고", 0) or 0),
                        "suspend_count": int(row.get("정지", 0) or 0),
                    }
        except Exception as e:
            print(f"[마켓현황] 마켓상태현황 시트 오류: {e}")
        
        # 3. 계정 정보 가져오기
        accounts = gsheet.get_accounts(None)
        
        # 플랫폼별 그룹화
        summary = {}
        for acc in accounts:
            platform = acc.get("platform", "기타")
            if platform not in summary:
                summary[platform] = []
            
            store_name = acc.get("스토어명") or acc.get("스토어명", "")
            login_id = acc.get("login_id", "")
            account_name = store_name if store_name else login_id
            
            # 마켓명 정규화
            market = platform
            if "스마트" in platform or "네이버" in platform:
                market = "스마트스토어"
            elif "11" in platform:
                market = "11번가"
            elif "쿠팡" in platform:
                market = "쿠팡"
            elif "지마켓" in platform:
                market = "지마켓"
            elif "옥션" in platform:
                market = "옥션"
            
            # 상품수
            product_count = 0
            if market == "스마트스토어":
                product_count = ss_counts.get(account_name, 0)
                if product_count == 0 and "_" in account_name:
                    name_after_underscore = account_name.split("_", 1)[1]
                    product_count = ss_counts.get(name_after_underscore, 0)
            elif market == "11번가":
                # 11번가 시트에서 읽기
                product_count = st_counts.get(account_name, 0)
                if product_count == 0:
                    product_count = st_counts.get(login_id, 0)
            
            # 상태/페널티 정보
            key = f"{account_name}_{market}"
            status_info = status_map.get(key, {})
            status = status_info.get("status", "정상")
            caution_count = status_info.get("caution_count", 0)
            warning_count = status_info.get("warning_count", 0)
            suspend_count = status_info.get("suspend_count", 0)
            
            summary[platform].append({
                "스토어명": account_name,
                "스토어명": account_name,  # 하위 호환
                "login_id": login_id,
                "status": status,
                "product_count": product_count,
                "caution_count": caution_count,
                "warning_count": warning_count,
                "suspend_count": suspend_count,
                "owner": acc.get("owner", ""),
                "usage": acc.get("usage", ""),
            })
        
        # 정렬 (상품수 내림차순)
        for platform in summary:
            summary[platform].sort(key=lambda x: x["product_count"], reverse=True)
        
        return {"success": True, "data": summary}
        
    except Exception as e:
        print(f"[마켓현황] 오류: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/11st/refresh-all-counts")
async def refresh_all_11st_counts(request: Request):
    """모든 11번가 계정 상품수 일괄 조회"""
    get_current_user(request)
    
    accounts = gsheet.get_accounts("11번가")  # 11번가만
    results = []
    
    for acc in accounts:
        api_key = acc.get("st_api_key", "")
        if not api_key:
            continue
        
        login_id = acc.get("login_id", "")
        store_name = acc.get("스토어명") or acc.get("스토어명", login_id)
        
        try:
            count = await get_11st_product_count(api_key)
            st_product_cache[login_id] = {"count": count, "time": datetime.now()}
            results.append({"shop": store_name, "count": count, "success": True})
        except Exception as e:
            results.append({"shop": store_name, "count": 0, "success": False, "error": str(e)})
    
    return {"success": True, "results": results}


# ========== 배송조회 API (모듈 사용) ==========
from modules.delivery_check import DeliveryChecker

# 배송조회용 별도 인증 파일 (레거시 호환)
DELIVERY_CREDENTIALS = r"C:\autosystem\autosms-466614-951e91617c69.json"
# 배송조회 인스턴스 초기화
delivery_checker = DeliveryChecker(DELIVERY_CREDENTIALS)

@app.post("/api/delivery/check")
async def start_delivery_check(request: Request):
    """배송조회 시작"""
    get_current_user(request)

    data = await request.json()
    sheet_id = data.get("sheet_id", "")
    sheet_name = data.get("sheet_name", "")
    carrier_col = int(data.get("carrier_col", 43))
    tracking_col = int(data.get("tracking_col", 44))
    start_row = int(data.get("start_row", 4))

    # 작업 로그 기록
    log_work("배송조회", sheet_name, 0, f"시트: {sheet_name}", "웹")

    # 모듈의 비동기 메서드 호출 (create_task는 모듈 내부에서 처리함)
    return await delivery_checker.start_check(sheet_id, sheet_name, carrier_col, tracking_col, start_row)

@app.post("/api/delivery/stop")
async def stop_delivery_check(request: Request):
    """배송조회 중지"""
    get_current_user(request)
    return delivery_checker.stop_check()

@app.get("/api/delivery/status")
async def get_delivery_status(request: Request):
    """배송조회 상태 조회"""
    get_current_user(request)
    return delivery_checker.get_status()


# ========== 스케줄러 API ==========
class ScheduleRequest(BaseModel):
    name: str
    platform: str = "스마트스토어"
    task: str = "등록갯수"
    stores: List[str] = []
    schedule_type: str = "cron"  # cron 또는 interval
    cron: str = "0 9 * * *"  # 분 시 일 월 요일
    interval_minutes: int = 60
    options: Dict = {}
    enabled: bool = True

@app.get("/api/schedules")
async def get_schedules(request: Request):
    """스케줄 목록 조회"""
    get_current_user(request)
    schedules = load_schedules()
    
    # 다음 실행 시간 추가
    for s in schedules:
        job = scheduler.get_job(s['id'])
        if job and job.next_run_time:
            s['next_run'] = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')
        else:
            s['next_run'] = None
    
    return {"schedules": schedules}

@app.post("/api/schedules")
async def create_schedule(request: Request, req: ScheduleRequest):
    """스케줄 생성"""
    require_permission(request, "edit")
    
    schedules = load_schedules()
    
    # 새 ID 생성
    schedule_id = f"schedule_{int(time.time()*1000)}"
    
    new_schedule = {
        "id": schedule_id,
        "name": req.name,
        "platform": req.platform,
        "task": req.task,
        "stores": req.stores,
        "schedule_type": req.schedule_type,
        "cron": req.cron,
        "interval_minutes": req.interval_minutes,
        "options": req.options,
        "enabled": req.enabled,
        "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "last_run": None,
        "run_count": 0
    }
    
    schedules.append(new_schedule)
    save_schedules(schedules)
    
    # 활성화된 경우 작업 등록
    if req.enabled:
        add_schedule_job(new_schedule)
    
    return {"success": True, "schedule": new_schedule}

@app.put("/api/schedules/{schedule_id}")
async def update_schedule(request: Request, schedule_id: str, req: ScheduleRequest):
    """스케줄 수정"""
    require_permission(request, "edit")
    
    schedules = load_schedules()
    
    for i, s in enumerate(schedules):
        if s['id'] == schedule_id:
            schedules[i].update({
                "name": req.name,
                "platform": req.platform,
                "task": req.task,
                "stores": req.stores,
                "schedule_type": req.schedule_type,
                "cron": req.cron,
                "interval_minutes": req.interval_minutes,
                "options": req.options,
                "enabled": req.enabled,
                "updated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
            save_schedules(schedules)
            
            # 작업 갱신
            if scheduler.get_job(schedule_id):
                scheduler.remove_job(schedule_id)
            if req.enabled:
                add_schedule_job(schedules[i])
            
            return {"success": True, "schedule": schedules[i]}
    
    raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(request: Request, schedule_id: str):
    """스케줄 삭제"""
    require_permission(request, "edit")
    
    schedules = load_schedules()
    schedules = [s for s in schedules if s['id'] != schedule_id]
    save_schedules(schedules)
    
    # 작업 제거
    if scheduler.get_job(schedule_id):
        scheduler.remove_job(schedule_id)
    
    return {"success": True}

@app.post("/api/schedules/{schedule_id}/toggle")
async def toggle_schedule(request: Request, schedule_id: str):
    """스케줄 활성화/비활성화"""
    require_permission(request, "edit")
    
    schedules = load_schedules()
    
    for s in schedules:
        if s['id'] == schedule_id:
            s['enabled'] = not s.get('enabled', True)
            save_schedules(schedules)
            
            if s['enabled']:
                add_schedule_job(s)
            else:
                if scheduler.get_job(schedule_id):
                    scheduler.remove_job(schedule_id)
            
            return {"success": True, "enabled": s['enabled']}
    
    raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

@app.post("/api/schedules/{schedule_id}/run")
async def run_schedule_now(request: Request, schedule_id: str):
    """스케줄 즉시 실행"""
    require_permission(request, "edit")
    
    schedules = load_schedules()
    
    for s in schedules:
        if s['id'] == schedule_id:
            # 비동기로 즉시 실행
            asyncio.create_task(execute_scheduled_task(
                schedule_id,
                s.get('platform', '스마트스토어'),
                s.get('task', '등록갯수'),
                s.get('stores', []),
                s.get('options', {})
            ))
            return {"success": True, "message": "작업이 시작되었습니다"}
    
    raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다")

@app.get("/api/schedules/{schedule_id}/log")
async def get_schedule_log(request: Request, schedule_id: str, lines: int = 100):
    """스케줄 실행 로그 조회"""
    require_permission(request, "view")
    
    log_file = os.path.join(os.path.dirname(__file__), "logs", f"schedule_{schedule_id}.log")
    
    if not os.path.exists(log_file):
        return {"success": False, "log": "", "message": "로그 파일이 없습니다 (아직 실행된 적 없음)"}
    
    try:
        # 파일 크기 확인
        file_size = os.path.getsize(log_file)
        
        # 마지막 N줄 읽기
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            log_content = "".join(last_lines)
        
        # 파일 수정 시간
        mtime = os.path.getmtime(log_file)
        modified_at = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        
        return {
            "success": True, 
            "log": log_content,
            "total_lines": len(all_lines),
            "file_size": file_size,
            "modified_at": modified_at
        }
    except Exception as e:
        return {"success": False, "log": "", "message": str(e)}


# ========== 마케팅 데이터 수집 ==========
marketing_tasks = {}  # {task_id: {"status": "running"|"completed"|"error", "current": 0, "total": 0, "logs": []}}
marketing_processes = {}

class MarketingCollectRequest(BaseModel):
    account_ids: List[str]

@app.post("/api/marketing/collect")
async def start_marketing_collection(request: Request, req: MarketingCollectRequest):
    """마케팅 데이터 수집 시작"""
    require_permission(request, "edit")

    if not req.account_ids or len(req.account_ids) == 0:
        return {"error": "계정을 선택하세요"}

    # 작업 로그 기록
    account_names = ", ".join(req.account_ids[:5]) + ("..." if len(req.account_ids) > 5 else "")
    log_work("마케팅수집", "스마트스토어", len(req.account_ids), f"대상: {account_names}", "웹")

    task_id = f"marketing_{int(time.time())}"

    # 태스크 초기화
    marketing_tasks[task_id] = {
        "status": "running",
        "current": 0,
        "total": len(req.account_ids),
        "logs": [f"[{datetime.now().strftime('%H:%M:%S')}] 마케팅 데이터 수집 시작 ({len(req.account_ids)}개 계정)"]
    }
    
    # 백그라운드에서 실행
    async def run_collection():
        try:
            # marketing_collector 실행
            env = os.environ.copy()
            env["MARKETING_ACCOUNT_IDS"] = ",".join(req.account_ids)
            env["MARKETING_SPREADSHEET_KEY"] = MARKETING_SPREADSHEET_KEY
            env["SPREADSHEET_KEY"] = SPREADSHEET_KEY
            env["SERVICE_ACCOUNT_JSON"] = str(CREDENTIALS_FILE)
            env["API_KEY"] = API_KEY
            env["SERVER_URL"] = f"http://localhost:{PORT}"
            
            collector_path = os.path.join(os.path.dirname(__file__), "modules", "marketing_collector.py")
            
            # 비동기 서브프로세스 생성 (블로킹 방지)
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-u", collector_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=os.path.dirname(__file__)
            )
            
            marketing_processes[task_id] = proc
            
            print(f"[마케팅수집] 프로세스 시작 - PID: {proc.pid}")
            
            # 비동기로 로그 읽기
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                
                line = line_bytes.decode('utf-8', errors='replace').strip()
                if line:
                    # print(f"[마케팅수집] {line}")
                    marketing_tasks[task_id]["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {line}")

                    # 진행률 추출
                    if "/" in line:
                        try:
                            parts = line.split("/")
                            if len(parts) == 2 and parts[0].split()[-1].isdigit():
                                current = int(parts[0].split()[-1])
                                marketing_tasks[task_id]["current"] = current
                        except:
                            pass

            await proc.wait()
            print(f"[마케팅수집] 프로세스 종료 - exit code: {proc.returncode}")
            
            if proc.returncode == 0:
                marketing_tasks[task_id]["status"] = "completed"
                marketing_tasks[task_id]["current"] = marketing_tasks[task_id]["total"]
                marketing_tasks[task_id]["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 수집 완료!")
            elif proc.returncode is None or proc.returncode == -15 or proc.returncode == 1:
                if marketing_tasks[task_id]["status"] == "running":
                    marketing_tasks[task_id]["status"] = "stopped"
                    marketing_tasks[task_id]["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ⏹ 사용자에 의해 중지됨")
            else:
                marketing_tasks[task_id]["status"] = "error"
                marketing_tasks[task_id]["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ 오류 발생 (exit code: {proc.returncode})")
            
            if task_id in marketing_processes:
                del marketing_processes[task_id]
                
        except Exception as e:
            marketing_tasks[task_id]["status"] = "error"
            marketing_tasks[task_id]["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ 오류: {str(e)}")
            if task_id in marketing_processes:
                del marketing_processes[task_id]
    
    # 비동기 실행
    asyncio.create_task(run_collection())
    
    return {"task_id": task_id, "total": len(req.account_ids)}

@app.post("/api/marketing/stop")
async def stop_marketing_collection(request: Request):
    """실행 중인 마케팅 수집 중지"""
    require_permission(request, "edit")
    
    data = await request.json()
    task_id = data.get("task_id")
    
    if not task_id:
        # 가장 최근의 running 태스크 중지
        for tid, t in marketing_tasks.items():
            if t["status"] == "running":
                task_id = tid
                break
    
    if not task_id or task_id not in marketing_processes:
        return {"success": False, "message": "실행 중인 작업을 찾을 수 없습니다."}
    
    try:
        proc = marketing_processes[task_id]
        import signal
        if sys.platform == "win32":
            proc.terminate() # Windows에서는 terminate()가 잘 작동함
        else:
            proc.send_signal(signal.SIGTERM)
            
        marketing_tasks[task_id]["status"] = "stopped"
        marketing_tasks[task_id]["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ⏹ 중지 요청됨")
        
        return {"success": True, "message": "작업이 중지되었습니다."}
    except Exception as e:
        return {"success": False, "message": f"중지 중 오류: {str(e)}"}

@app.get("/api/marketing/progress/{task_id}")
async def get_marketing_progress(request: Request, task_id: str):
    """마케팅 데이터 수집 진행 상황 조회"""
    require_permission(request, "view")

    if task_id not in marketing_tasks:
        return {"error": "작업을 찾을 수 없습니다"}

    return marketing_tasks[task_id]

@app.get("/api/marketing/progress-stream/{task_id}")
async def get_marketing_progress_stream(request: Request, task_id: str):
    """마케팅 데이터 수집 진행 상황 SSE 스트림"""
    from fastapi.responses import StreamingResponse

    async def event_generator():
        last_log_count = 0
        while True:
            if task_id not in marketing_tasks:
                yield f"data: {json.dumps({'error': '작업 없음'})}\n\n"
                break

            task = marketing_tasks[task_id]
            current_log_count = len(task.get("logs", []))

            # 변경사항이 있을 때만 전송
            if current_log_count != last_log_count or task.get("status") in ["completed", "error"]:
                yield f"data: {json.dumps(task, ensure_ascii=False)}\n\n"
                last_log_count = current_log_count

            if task.get("status") in ["completed", "error"]:
                break

            await asyncio.sleep(0.5)  # 0.5초마다 체크

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )

@app.post("/api/marketing/create-sheets")
async def create_marketing_sheets(request: Request):
    """마케팅 스프레드시트 초기화"""
    require_permission(request, "edit")

    try:
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(MARKETING_SPREADSHEET_KEY)

        results = []
        system_sheets = {"전체데이터", "쇼핑몰정보", "템플릿", "설정"}

        # 개별 마켓 시트 데이터 초기화 (삭제하지 않고 내용만 비움)
        all_worksheets = sheet.worksheets()
        for ws in all_worksheets:
            if ws.title not in system_sheets:
                try:
                    ws.clear()
                    results.append({"sheet": ws.title, "status": "데이터 초기화됨"})
                except Exception as e:
                    results.append({"sheet": ws.title, "status": f"초기화 실패: {str(e)[:20]}"})

        # "전체데이터" 시트 생성/초기화
        try:
            ws_data = sheet.worksheet("전체데이터")
            ws_data.clear()
            ws_data.update('A1', [[
                "수집일시", "스토어명", "상품번호", "상품명",
                "방문횟수", "유입수", "클릭수", "전환수", "판매액"
            ]])
            results.append({"sheet": "전체데이터", "status": "초기화됨"})
        except:
            ws_data = sheet.add_worksheet(title="전체데이터", rows=50000, cols=10)
            ws_data.update('A1', [[
                "수집일시", "스토어명", "상품번호", "상품명",
                "방문횟수", "유입수", "클릭수", "전환수", "판매액"
            ]])
            results.append({"sheet": "전체데이터", "status": "새로 생성됨"})

        # "쇼핑몰정보" 시트 생성/초기화
        try:
            ws_mall = sheet.worksheet("쇼핑몰정보")
            ws_mall.clear()
            ws_mall.update('A1', [[
                "수집일시", "스토어명", "총방문자수", "재방문자수", "신규방문자수",
                "총페이지뷰", "평균체류시간", "이탈률", "구매전환율"
            ]])
            results.append({"sheet": "쇼핑몰정보", "status": "초기화됨"})
        except:
            ws_mall = sheet.add_worksheet(title="쇼핑몰정보", rows=1000, cols=10)
            ws_mall.update('A1', [[
                "수집일시", "스토어명", "총방문자수", "재방문자수", "신규방문자수",
                "총페이지뷰", "평균체류시간", "이탈률", "구매전환율"
            ]])
            results.append({"sheet": "쇼핑몰정보", "status": "새로 생성됨"})

        spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{MARKETING_SPREADSHEET_KEY}"
        return {"success": True, "results": results, "spreadsheet_url": spreadsheet_url}

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/marketing/data")
async def get_marketing_data(request: Request, store: str = None):
    """마케팅 수집 데이터 조회
    - store: 특정 스토어명 (없으면 전체)
    """
    require_permission(request, "view")

    try:
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(MARKETING_SPREADSHEET_KEY)

        result = {
            "stores": [],
            "data": {}
        }

        # 모든 워크시트 조회
        worksheets = sheet.worksheets()
        store_names = [ws.title for ws in worksheets if ws.title not in ["템플릿", "설정", "전체데이터"]]
        result["stores"] = store_names

        if store:
            # 특정 스토어 데이터만
            try:
                ws = sheet.worksheet(store)
                all_values = ws.get_all_values()

                # 데이터 파싱 (열 위치 기반 - data111.py 구조)
                # A~G(0-6): 마케팅분석, I~O(8-14): 상품클릭리포트, Q~R(16-17): 쇼핑몰정보, S~T(18-19): 전체채널
                biz_data = []       # 마케팅분석 (상품노출성과)
                partner_data = []   # 상품클릭리포트
                mall_info = {}      # 쇼핑몰정보
                channel_data = []   # 전체채널

                # 헤더 키워드 목록 (필터링용)
                header_keywords = {"상품명", "상품ID", "상품 ID", "채널그룹", "채널명", "키워드",
                                   "평균노출순위", "유입수", "노출수", "클릭수", "클릭율", "클릭률",
                                   "적용수수료", "클릭당수수료", "항목", "노출", "성과"}

                for i, row in enumerate(all_values):
                    if i == 0:  # 헤더 행 스킵
                        continue

                    # 마케팅분석 (A~G열, index 0-6)
                    if len(row) > 6 and row[0]:
                        product_name = row[0].strip()
                        # 헤더 키워드가 아닌 경우만 추가
                        if product_name and product_name not in header_keywords:
                            inflow = row[6].strip() if len(row) > 6 else "0"
                            biz_data.append({
                                "상품명": product_name,
                                "상품ID": row[1].strip() if len(row) > 1 else "",
                                "채널그룹": row[2].strip() if len(row) > 2 else "",
                                "채널명": row[3].strip() if len(row) > 3 else "",
                                "키워드": row[4].strip() if len(row) > 4 else "",
                                "평균노출순위": row[5].strip() if len(row) > 5 else "",
                                "유입수": inflow
                            })

                    # 상품클릭리포트 (I~O열, index 8-14)
                    if len(row) > 14 and row[8]:
                        product_id = row[8].strip()
                        # 헤더 키워드가 아니고 숫자로 시작하는 경우만 (상품ID는 숫자)
                        if product_id and product_id not in header_keywords and product_id[0].isdigit():
                            partner_data.append({
                                "상품ID": product_id,
                                "상품명": row[9].strip() if len(row) > 9 else "",
                                "노출수": row[10].strip() if len(row) > 10 else "0",
                                "클릭수": row[11].strip() if len(row) > 11 else "0",
                                "클릭율": row[12].strip() if len(row) > 12 else "",
                                "적용수수료": row[13].strip() if len(row) > 13 else "",
                                "클릭당수수료": row[14].strip() if len(row) > 14 else ""
                            })

                    # 쇼핑몰정보 (Q~R열, index 16-17)
                    if len(row) > 17 and row[16]:
                        key = row[16].strip()
                        if key and key not in header_keywords:
                            mall_info[key] = row[17].strip() if len(row) > 17 else ""

                    # 전체채널 (S~T열, index 18-19)
                    if len(row) > 19 and row[18]:
                        channel_name = row[18].strip()
                        if channel_name and channel_name not in header_keywords:
                            channel_data.append({
                                "채널명": channel_name,
                                "유입수": row[19].strip() if len(row) > 19 else "0"
                            })

                result["data"][store] = {
                    "biz_advisor": biz_data,
                    "shopping_partner": partner_data,
                    "mall_info": mall_info,
                    "channel_data": channel_data
                }

            except Exception as e:
                result["data"][store] = {"error": str(e)}
        else:
            # 모든 스토어의 요약 정보
            for store_name in store_names[:50]:  # 최대 50개
                try:
                    ws = sheet.worksheet(store_name)
                    all_values = ws.get_all_values()

                    # 간단한 요약 (행 수)
                    biz_count = 0
                    partner_count = 0
                    collect_time = ""

                    for row in all_values:
                        if row and "수집일시" in str(row[0]):
                            collect_time = row[1] if len(row) > 1 else ""
                        elif row and row[0] and row[0] != "상품명" and row[0] != "상품ID":
                            if "상품ID" in str(row):
                                continue
                            biz_count += 1

                    result["data"][store_name] = {
                        "collect_time": collect_time,
                        "biz_count": biz_count,
                        "partner_count": partner_count
                    }
                except:
                    pass

        return {"success": True, **result}

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/marketing/summary")
async def get_marketing_summary(request: Request):
    """마케팅 데이터 요약 (대시보드용)"""
    require_permission(request, "view")

    try:
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(MARKETING_SPREADSHEET_KEY)

        # 전체데이터 시트에서 요약
        try:
            all_data_ws = sheet.worksheet("전체데이터")
            all_values = all_data_ws.get_all_values()

            if len(all_values) < 2:
                return {"success": True, "data": [], "total": 0}

            headers = all_values[0]
            data = []

            for row in all_values[1:]:
                if not any(row):
                    continue

                row_dict = {}
                for i, header in enumerate(headers):
                    row_dict[header] = row[i] if i < len(row) else ""
                data.append(row_dict)

            return {"success": True, "data": data, "total": len(data)}

        except Exception as e:
            # 전체데이터 시트가 없으면 개별 시트에서 수집
            worksheets = sheet.worksheets()
            store_names = [ws.title for ws in worksheets if ws.title not in ["템플릿", "설정", "전체데이터"]]

            return {
                "success": True,
                "stores": store_names,
                "message": "전체데이터 시트 없음. 개별 스토어 조회 필요"
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ========== 다운로드 API ==========
@app.get("/api/downloads/client")
async def download_client():
    """클라이언트 프로그램 다운로드 (exe)"""
    import zipfile
    from io import BytesIO

    # exe 파일 경로
    exe_path = APP_DIR / "pkonomy_client" / "dist" / "PkonomyClient.exe"

    if not exe_path.exists():
        # exe가 없으면 py 파일 제공
        py_path = APP_DIR.parent / "client_v1.5.py"
        if py_path.exists():
            return FileResponse(
                path=str(py_path),
                filename="client_v1.5.py",
                media_type="application/octet-stream"
            )
        return {"error": "클라이언트 파일을 찾을 수 없습니다"}

    return FileResponse(
        path=str(exe_path),
        filename="PkonomyClient.exe",
        media_type="application/octet-stream"
    )


@app.get("/api/downloads/extension")
async def download_extension():
    """크롬 익스텐션 다운로드 (zip)"""
    import zipfile
    from io import BytesIO

    ext_dir = APP_DIR.parent / "chrome_extension"

    if not ext_dir.exists():
        return {"error": "크롬 익스텐션 폴더를 찾을 수 없습니다"}

    # 메모리에 ZIP 생성
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in ext_dir.rglob('*'):
            if file_path.is_file():
                arcname = file_path.relative_to(ext_dir)
                zf.write(file_path, arcname)

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=pkonomy_chrome_extension.zip"}
    )


@app.get("/api/downloads/info")
async def get_download_info():
    """다운로드 가능 파일 정보"""
    exe_path = APP_DIR / "pkonomy_client" / "dist" / "PkonomyClient.exe"
    ext_dir = APP_DIR.parent / "chrome_extension"

    info = {
        "client": {
            "available": exe_path.exists(),
            "filename": "PkonomyClient.exe",
            "path": str(exe_path) if exe_path.exists() else None
        },
        "extension": {
            "available": ext_dir.exists(),
            "filename": "pkonomy_chrome_extension.zip",
            "path": str(ext_dir) if ext_dir.exists() else None
        }
    }

    # 파일 크기 및 수정일
    if exe_path.exists():
        stat = exe_path.stat()
        info["client"]["size"] = stat.st_size
        info["client"]["modified"] = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")

    if ext_dir.exists():
        manifest_path = ext_dir / "manifest.json"
        if manifest_path.exists():
            import json
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
                info["extension"]["version"] = manifest.get("version", "1.0")

    return info


# ========== 실행 ==========
if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  🏢 구매대행 통합관리 시스템                                   ║
║  ──────────────────────────────────────────────────────────  ║
║  서버 주소: http://localhost:{PORT}                            ║
║  내부망 접속: http://<서버IP>:{PORT}                           ║
║                                                              ║
║  기본 계정: admin / admin (담당자 시트 없을 경우)              ║
╚══════════════════════════════════════════════════════════════╝
    """)
    uvicorn.run(app, host=HOST, port=PORT)
