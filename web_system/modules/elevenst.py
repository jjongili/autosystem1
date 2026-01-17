"""
11번가 올인원 모듈
- 스마트스토어 올인원과 동일한 구조
- 11번가 시트에서 active=TRUE인 계정만 처리
- 작업: 판매중지, 판매재개
"""

import os
import time
import threading
from typing import Any, Dict, List, Optional, Tuple, Callable
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import xml.etree.ElementTree as ET
import gspread
from google.oauth2.service_account import Credentials

# ================= 11번가 API 설정 =================
BASE_URL = "http://api.11st.co.kr"
MULTI_SEARCH_PATH = "/rest/prodmarketservice/prodmarket"
STOP_PATH = "/rest/prodstatservice/stat/stopdisplay"
START_PATH = "/rest/prodstatservice/stat/startdisplay"

SEARCH_LIMIT = 500
STATUS_FILTER = "103"  # 판매중인 상품만

PRODUCT_WORKERS = 5  # 상품 병렬 처리 수

SHEET_NAME = "11번가"

# 중단 이벤트
STOP_EVENT = threading.Event()


def now_kr() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def plog(msg: str):
    """로그 출력"""
    print(f"[11번가] {msg}")


# ====== 웹 UI 진행 상황 업데이트 ======
def update_aio_status(current_store: str = "", current_action: str = "", 
                      completed: int = 0, total: int = 0, progress: int = 0):
    """server.py의 aio_status 업데이트 (웹 UI에서 진행 상황 표시용)"""
    try:
        import server
        if hasattr(server, 'aio_status'):
            if current_store:
                server.aio_status["current_store"] = current_store
            if current_action:
                server.aio_status["current_action"] = current_action
            if total > 0:
                server.aio_status["total"] = total
            if completed >= 0:
                server.aio_status["completed"] = completed
            if progress >= 0:
                server.aio_status["progress"] = progress
    except:
        pass


# ================= 11번가 API 요청 =================
def post_xml_prodmarket(url: str, api_key: str, body_xml: str) -> Tuple[str, int]:
    """다중상품조회 전용 요청"""
    headers = {
        "openapikey": api_key,
        "Content-Type": "text/xml;charset=euc-kr",
        "Accept": "application/xml",
    }
    data = body_xml.encode("euc-kr", errors="ignore")
    res = requests.post(url, headers=headers, data=data, timeout=30)
    raw = res.content.decode("euc-kr", errors="ignore")
    return raw, res.status_code


def put_simple(url: str, api_key: str) -> Tuple[str, int]:
    """전시중지/재개 전용 요청"""
    headers = {
        "openapikey": api_key,
        "Accept": "application/xml",
    }
    res = requests.put(url, headers=headers, timeout=30)
    raw = res.content.decode("euc-kr", errors="ignore")
    return raw, res.status_code


# ================= 상품 조회 =================
def build_search_xml(limit: int, start: Optional[int] = None) -> str:
    """다중 상품 조회용 XML 생성"""
    parts = ["<SearchProduct>"]
    if STATUS_FILTER:
        parts.append(f"    <selStatCd>{STATUS_FILTER}</selStatCd>")
    parts.append(f"    <limit>{limit}</limit>")
    if start is not None:
        parts.append(f"    <start>{start}</start>")
    parts.append("</SearchProduct>")
    return "\n".join(parts)


def parse_prdno_list(raw_xml: str) -> List[str]:
    """XML에서 prdNo 리스트 추출"""
    result = []
    try:
        root = ET.fromstring(raw_xml)
        for prod in root.iter():
            if prod.tag.endswith("product"):
                for child in prod:
                    if child.tag.endswith("prdNo"):
                        prd_no = (child.text or "").strip()
                        if prd_no:
                            result.append(prd_no)
                        break
    except Exception:
        pass
    return result


def fetch_all_products(api_key: str, log_callback: Optional[Callable] = None) -> List[str]:
    """전체 상품 prdNo 조회"""
    def log(msg):
        if log_callback:
            log_callback(msg)
        print(msg)
    
    all_prd = []
    seen = set()
    page = 0
    
    while True:
        if STOP_EVENT.is_set():
            break
        
        start = page * SEARCH_LIMIT + 1 if page > 0 else None
        xml_body = build_search_xml(SEARCH_LIMIT, start=start)
        url = f"{BASE_URL}{MULTI_SEARCH_PATH}"
        
        raw, status = post_xml_prodmarket(url, api_key, xml_body)
        
        if status != 200:
            log(f"[상품조회] HTTP {status} → 중단")
            break
        
        prd_list = parse_prdno_list(raw)
        if not prd_list:
            break
        
        new_cnt = 0
        for p in prd_list:
            if p not in seen:
                seen.add(p)
                all_prd.append(p)
                new_cnt += 1
        
        log(f"[상품조회] 페이지 {page+1}: {len(prd_list)}개 (누적 {len(all_prd)}개)")
        
        if len(prd_list) < SEARCH_LIMIT:
            break
        
        page += 1
        time.sleep(0.3)
    
    return all_prd


# ================= 전시중지/재개 =================
def stop_display(prd_no: str, api_key: str) -> Tuple[bool, str]:
    """전시중지"""
    url = f"{BASE_URL}{STOP_PATH}/{prd_no}"
    raw, status = put_simple(url, api_key)
    
    if status != 200:
        return False, f"HTTP {status}"
    
    try:
        root = ET.fromstring(raw)
        result_code = (root.findtext("resultCode") or "").strip()
        message = (root.findtext("message") or "").strip()
        return result_code == "200", message or raw[:100]
    except Exception as e:
        return False, f"XML 파싱 오류: {e}"


def start_display(prd_no: str, api_key: str) -> Tuple[bool, str]:
    """전시재개"""
    url = f"{BASE_URL}{START_PATH}/{prd_no}"
    raw, status = put_simple(url, api_key)
    
    if status != 200:
        return False, f"HTTP {status}"
    
    try:
        root = ET.fromstring(raw)
        result_code = (root.findtext("resultCode") or "").strip()
        message = (root.findtext("message") or "").strip()
        return result_code == "200", message or raw[:100]
    except Exception as e:
        return False, f"XML 파싱 오류: {e}"


# ================= 시트 결과 업데이트 =================
def update_sheet_result(ws, row_idx: int, result_msg: str, headers: List[str]):
    """시트의 결과 열 업데이트"""
    try:
        # 결과 열 찾기
        result_col = None
        updated_col = None
        for i, h in enumerate(headers):
            if h == "결과":
                result_col = i + 1  # 1-indexed
            if h == "updated_at":
                updated_col = i + 1
        
        if result_col:
            ws.update_cell(row_idx, result_col, result_msg)
            plog(f"결과 업데이트: row={row_idx}, col={result_col}")
        
        if updated_col:
            ws.update_cell(row_idx, updated_col, now_kr())
            
    except Exception as e:
        plog(f"시트 업데이트 오류: {e}")


# ================= 개별 스토어 작업 실행 =================
def run_task(
    task: str,
    store_name: str,
    api_key: str,
    log_callback: Optional[Callable] = None,
    progress_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    작업 실행
    - task: 판매중지, 판매재개
    """
    def log(msg):
        if log_callback:
            log_callback(msg)
        plog(f"[{store_name}] {msg}")
    
    def progress(current, total):
        if progress_callback:
            progress_callback(current, total)
    
    if task not in ("판매중지", "판매재개"):
        return {"success": False, "message": f"알 수 없는 작업: {task}"}
    
    try:
        # 1) 상품 조회
        log("상품 조회 중...")
        prd_list = fetch_all_products(api_key, log)
        total = len(prd_list)
        
        if total == 0:
            return {"success": True, "message": "상품 없음", "success_count": 0, "fail_count": 0, "total": 0}
        
        log(f"대상 상품: {total}개")
        
        # 2) 작업 함수 선택
        worker_fn = stop_display if task == "판매중지" else start_display
        
        # 3) 병렬 처리
        success_count = 0
        fail_count = 0
        
        def worker(prd_no: str) -> Tuple[str, bool, str]:
            ok, message = worker_fn(prd_no, api_key)
            return prd_no, ok, message
        
        with ThreadPoolExecutor(max_workers=PRODUCT_WORKERS) as executor:
            future_to_prd = {
                executor.submit(worker, prd): prd for prd in prd_list
            }
            
            for i, future in enumerate(as_completed(future_to_prd), start=1):
                if STOP_EVENT.is_set():
                    log("작업 중단됨")
                    break
                
                prd_no = future_to_prd[future]
                try:
                    prd_no, ok, message = future.result()
                except Exception as e:
                    ok = False
                    message = str(e)
                
                if ok:
                    success_count += 1
                else:
                    fail_count += 1
                
                # 진행률 업데이트 (매 아이템마다)
                progress(i, total)
                
                # 로그는 10개마다 또는 마지막에만
                if i % 10 == 0 or i == total:
                    log(f"진행: {i}/{total} (성공 {success_count}, 실패 {fail_count})")
        
        summary = f"{task} 성공 {success_count} / 실패 {fail_count} (총 {total}개)"
        log(f"완료: {summary}")
        
        return {
            "success": True,
            "message": summary,
            "success_count": success_count,
            "fail_count": fail_count,
            "total": total
        }
    
    except Exception as e:
        log(f"오류: {e}")
        return {"success": False, "message": str(e)}


# ================= 메인 실행 함수 (스마트스토어와 동일 구조) =================
def run_main(task: str = None, sheet=None):
    """
    메인 실행 함수
    - 11번가 시트에서 active=TRUE인 계정만 실행
    - task: 판매중지 또는 판매재개 (None이면 jobs 열에서 읽음)
    - sheet: gspread 스프레드시트 객체 (server.py에서 전달)
    """
    reset_stop()
    
    # 시트 객체가 없으면 직접 연결 시도
    if sheet is None:
        from dotenv import load_dotenv
        
        # .env 파일 경로 - 여러 위치 시도
        env_paths = [
            os.path.join(os.path.dirname(__file__), '..', '..', '.env'),
            os.path.join(os.path.dirname(__file__), '..', '.env'),
            r'C:\autosystem\.env',
        ]
        for env_path in env_paths:
            if os.path.exists(env_path):
                load_dotenv(env_path)
                plog(f"[INFO] .env 로드: {env_path}")
                break
        
        spreadsheet_key = os.getenv("SPREADSHEET_KEY")
        service_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or os.getenv("SERVICE_ACCOUNT_JSON")
        
        if not spreadsheet_key:
            plog("[ERROR] SPREADSHEET_KEY 환경변수 필요")
            return
        
        if not service_json or not os.path.exists(service_json):
            plog(f"[ERROR] GOOGLE_SERVICE_ACCOUNT_FILE 없음: {service_json}")
            return
        
        # 구글 시트 연결
        try:
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            creds = Credentials.from_service_account_file(service_json, scopes=scopes)
            gc = gspread.authorize(creds)
            sheet = gc.open_by_key(spreadsheet_key)
        except Exception as e:
            plog(f"[ERROR] 구글 시트 연결 실패: {e}")
            return
    
    try:
        ws = sheet.worksheet(SHEET_NAME)
    except Exception as e:
        plog(f"[ERROR] 11번가 시트 열기 실패: {e}")
        return
    
    # 시트 데이터 읽기
    all_data = ws.get_all_records()
    a_col = ws.col_values(1)  # active 열
    
    # 헤더 가져오기
    headers = ws.row_values(1)
    plog(f"[INFO] 11번가 헤더: {headers}")
    
    plog(f"[INFO] 11번가 시트: {len(all_data)}개 계정")
    
    # active=TRUE인 계정만 필터
    enabled_stores = []
    for idx, row in enumerate(all_data):
        flag = a_col[idx + 1] if len(a_col) > idx + 1 else ""
        if str(flag).upper() == "TRUE":
            enabled_stores.append((idx + 2, row))  # (행번호, 데이터)
    
    total_stores = len(enabled_stores)
    plog(f"[RUN] 대상 계정: {total_stores}개 (active=TRUE)")
    
    if not enabled_stores:
        plog("[INFO] TRUE로 설정된 계정이 없어 종료합니다.")
        return
    
    # 웹 UI 진행 상황 초기화
    update_aio_status(current_action="11번가 작업 준비 중...", total=total_stores, completed=0, progress=0)
    
    # 각 스토어 실행
    for i, (row_idx, row) in enumerate(enabled_stores):
        if STOP_EVENT.is_set():
            plog("[INFO] 작업 중단됨")
            break
        
        store_name = row.get("스토어명") or row.get("store_name", "")
        api_key = row.get("API KEY", "")
        store_task = task or row.get("jobs", "판매중지")  # task가 없으면 jobs 열에서
        
        if not store_name or not api_key:
            plog(f"[WARN] {store_name or '(이름없음)'}: API KEY 누락 → 스킵")
            continue
        
        plog(f"[{i+1}/{total_stores}] {store_name}: {store_task} 시작")
        
        # 웹 UI 업데이트 (스토어 시작 시)
        store_progress = int((i / total_stores) * 100)
        update_aio_status(current_store=store_name, current_action=f"{store_task} 진행 중...", 
                         completed=i, progress=store_progress)
        
        # 상품별 진행률 콜백 정의
        def product_progress_callback(current, total_products):
            # 현재 스토어 내 상품 진행률 계산
            product_pct = int((current / total_products) * 100) if total_products > 0 else 0
            # 전체 스토어 진행률에 현재 스토어 진행률 반영
            overall_pct = int(((i + (current / total_products)) / total_stores) * 100) if total_stores > 0 else 0
            update_aio_status(
                current_store=store_name,
                current_action=f"{store_task} 진행 중... ({current}/{total_products} 상품, {product_pct}%)",
                completed=i,
                progress=overall_pct
            )
        
        # 작업 실행 (progress_callback 전달)
        result = run_task(store_task, store_name, api_key, progress_callback=product_progress_callback)
        
        # 결과 시트에 기록
        result_msg = f"{store_task} 성공 {result.get('success_count', 0)} / 실패 {result.get('fail_count', 0)} (총 {result.get('total', 0)}개)"
        update_sheet_result(ws, row_idx, result_msg, headers)
        
        plog(f"[{i+1}/{total_stores}] {store_name}: {result_msg}")
    
    # 완료
    update_aio_status(current_store="", current_action="완료", completed=total_stores, progress=100)
    plog("[INFO] 모든 작업 완료")


def stop_all():
    """모든 작업 중단"""
    STOP_EVENT.set()


def reset_stop():
    """중단 플래그 리셋"""
    STOP_EVENT.clear()


# 직접 실행 시
if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    
    # .env 파일 로드
    load_dotenv()
    
    # 환경변수 또는 인자로 작업 받기
    task_arg = os.environ.get("ELEVENST_TASK") or (sys.argv[1] if len(sys.argv) > 1 else None)
    
    plog(f"[START] 11번가 독립 실행 - task: {task_arg}")
    run_main(task_arg)
