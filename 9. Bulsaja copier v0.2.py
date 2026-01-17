#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
불사자 상품 복사 프로그램
- 브라우저 로그인 후 토큰 추출
- 중복 체크 후 복사
- 통합그룹 단위 복사 지원
"""

import sys
import json
import requests
import websocket
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QSpinBox, QCheckBox, QGroupBox,
    QTextEdit, QProgressBar, QListWidget, QListWidgetItem, QTabWidget,
    QLineEdit, QMessageBox, QAbstractItemView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

# 그룹 매핑 데이터
GROUPS = {
    "01_푸로테카": 9662,
    "02_스트롬브린": 9663,
    "03_코드리크": 9664,
    "04_루플리스": 9665,
    "05_호비크": 9666,
    "06_브릭스턴": 9667,
    "07_툴앤박스": 9668,
    "08_툴앤퍼니": 9669,
    "09_모음상사": 9670,
    "10_테크인홈": 9671,
    "11_썬이마켓": 11251,
    "12_브리코레스": 11252,
    "13_클락시": 11253,
    "14_코르빈스": 11254,
    "15_블러앤데이": 11255,
    "16_루미아스": 11256,
    "17_코아트스": 11257,
    "18_루미베르": 11258,
    "19_플로엔스": 11259,
    "20_레이브릭": 11260,
    "21_루미켓": 7561,
    "22_리코즈": 7538,
    "23_쿠비엔": 7539,
    "24_핀제르": 7540,
    "25_델카스": 7541,
    "26_테비온": 7542,
    "27_바론트": 7543,
    "28_룬베르": 7544,
    "29_스딘트": 7545,
    "30_비르노": 7562,
    "31_하인정": 8907,
    "32_하정상사": 8908,
    "33_엘리크": 8909,
    "34_포니카": 8910,
    "35_라모핀": 8911,
    "36_후모나": 8912,
    "37_아트레야": 8913,
    "38_폴레노": 8914,
    "39_루센코": 8915,
    "40_루피넬": 8916,
    "41_반수동(수집)": 11261,
}

# 통합그룹 정의 (4개씩)
INTEGRATED_GROUPS = {
    "통합1 (01~04)": ["01_푸로테카", "02_스트롬브린", "03_코드리크", "04_루플리스"],
    "통합2 (05~08)": ["05_호비크", "06_브릭스턴", "07_툴앤박스", "08_툴앤퍼니"],
    "통합3 (09~12)": ["09_모음상사", "10_테크인홈", "11_썬이마켓", "12_브리코레스"],
    "통합4 (13~16)": ["13_클락시", "14_코르빈스", "15_블러앤데이", "16_루미아스"],
    "통합5 (17~20)": ["17_코아트스", "18_루미베르", "19_플로엔스", "20_레이브릭"],
    "통합6 (21~24)": ["21_루미켓", "22_리코즈", "23_쿠비엔", "24_핀제르"],
    "통합7 (25~28)": ["25_델카스", "26_테비온", "27_바론트", "28_룬베르"],
    "통합8 (29~32)": ["29_스딘트", "30_비르노", "31_하인정", "32_하정상사"],
    "통합9 (33~36)": ["33_엘리크", "34_포니카", "35_라모핀", "36_후모나"],
    "통합10 (37~40)": ["37_아트레야", "38_폴레노", "39_루센코", "40_루피넬"],
}

class BulsajaAPI:
    """불사자 API 클래스"""
    
    BASE_URL = "https://api.bulsaja.com"
    
    def __init__(self, access_token, refresh_token):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Accesstoken": access_token,
            "Refreshtoken": refresh_token,
            "Origin": "https://www.bulsaja.com",
            "Referer": "https://www.bulsaja.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        })
    
    @staticmethod
    def extract_token_from_browser(port=9222):
        """Chrome Debug 모드에서 토큰 추출"""
        try:
            # 탭 목록 조회
            resp = requests.get(f"http://127.0.0.1:{port}/json", timeout=5)
            tabs = resp.json()
            
            # 불사자 탭 찾기
            bulsaja_tab = None
            for tab in tabs:
                url = tab.get("url", "")
                tab_type = tab.get("type", "")
                if "bulsaja.com" in url and tab_type == "page":
                    bulsaja_tab = tab
                    break
            
            if not bulsaja_tab:
                return None, "불사자 탭을 찾을 수 없습니다. 브라우저에서 bulsaja.com에 로그인해주세요."
            
            # WebSocket 연결
            ws_url = bulsaja_tab.get("webSocketDebuggerUrl")
            if not ws_url:
                return None, "WebSocket URL을 찾을 수 없습니다."
            
            ws = websocket.create_connection(ws_url, timeout=10)
            
            # localStorage에서 토큰 추출
            js_code = """
            (function() {
                var tokenData = localStorage.getItem('token');
                if (tokenData) {
                    try {
                        var parsed = JSON.parse(tokenData);
                        if (parsed.state) {
                            return JSON.stringify({
                                accessToken: parsed.state.accessToken,
                                refreshToken: parsed.state.refreshToken
                            });
                        }
                    } catch(e) {}
                }
                // 기존 방식도 시도
                var accessToken = localStorage.getItem('accessToken');
                var refreshToken = localStorage.getItem('refreshToken');
                return JSON.stringify({accessToken: accessToken, refreshToken: refreshToken});
            })()
            """
            
            ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": js_code, "returnByValue": True}
            }))
            
            result = json.loads(ws.recv())
            ws.close()
            
            if "result" in result and "result" in result["result"]:
                value = result["result"]["result"].get("value")
                if value:
                    tokens = json.loads(value)
                    access_token = tokens.get("accessToken")
                    refresh_token = tokens.get("refreshToken")
                    
                    if access_token and refresh_token:
                        return {"access": access_token, "refresh": refresh_token}, None
                    else:
                        return None, "토큰이 없습니다. 불사자 웹에 로그인해주세요."
            
            return None, "토큰 추출 실패"
            
        except requests.exceptions.ConnectionError:
            return None, f"Chrome Debug 연결 실패 (포트 {port}). Chrome을 Debug 모드로 실행해주세요."
        except Exception as e:
            return None, f"오류: {str(e)}"
    
    def get_products(self, group_name, start_row=0, end_row=1000, status_filter=None, tag_filter=None):
        """상품 목록 조회"""
        import time
        
        url = f"{self.BASE_URL}/api/manage/list/serverside"
        
        filter_model = {
            "marketGroupName": {
                "filterType": "text",
                "type": "equals",
                "filter": group_name
            }
        }
        
        # 상태 필터 추가
        if status_filter:
            filter_model["status"] = {
                "filterType": "text",
                "type": "equals",
                "filter": status_filter
            }
        
        # 태그 필터 추가
        if tag_filter:
            filter_model["groupFile"] = {
                "filterType": "text",
                "type": "equals",
                "filter": tag_filter
            }
        
        payload = {
            "request": {
                "startRow": start_row,
                "endRow": end_row,
                "sortModel": [],
                "filterModel": filter_model
            }
        }
        
        # 재시도 로직 (최대 3회)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"[DEBUG] 상품 조회: {group_name}, {start_row}~{end_row}")
                response = self.session.post(url, json=payload, timeout=120)
                print(f"[DEBUG] 응답: {response.status_code}, 길이: {len(response.text)}")
                
                if response.status_code == 200:
                    try:
                        return response.json()
                    except Exception as e:
                        print(f"[DEBUG] JSON 파싱 오류: {e}")
                        raise Exception(f"JSON 파싱 오류: {e}")
                elif response.status_code in [502, 503, 504]:
                    # 서버 과부하 - 대기 후 재시도
                    wait_time = (attempt + 1) * 5  # 5초, 10초, 15초
                    print(f"[DEBUG] 서버 오류 {response.status_code}, {wait_time}초 후 재시도...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise Exception(f"API 오류: {response.status_code} - {response.text[:500]}")
            except requests.exceptions.Timeout:
                wait_time = (attempt + 1) * 5
                print(f"[DEBUG] 타임아웃, {wait_time}초 후 재시도...")
                time.sleep(wait_time)
                continue
        
        raise Exception(f"API 호출 실패 (재시도 {max_retries}회 초과)")
    
    def get_all_products(self, group_name, status_filter=None, tag_filter=None, batch_size=1000, log_callback=None, stop_check=None):
        """상품 전체 조회 (배치)"""
        import time
        
        all_rows = []
        start_row = 0
        
        while True:
            # 중지 체크
            if stop_check and stop_check():
                return all_rows
            
            if log_callback:
                log_callback(f"  조회 중... {start_row}~{start_row + batch_size}")
            
            data = self.get_products(
                group_name, 
                start_row=start_row, 
                end_row=start_row + batch_size,
                status_filter=status_filter,
                tag_filter=tag_filter
            )
            
            rows = data.get("rowData", [])
            all_rows.extend(rows)
            
            # 더 이상 데이터가 없으면 종료
            if len(rows) < batch_size:
                break
            
            start_row += batch_size
            
            # 서버 부하 방지를 위한 딜레이 (0.3초)
            time.sleep(0.3)
        
        return all_rows
    
    def copy_products(self, product_ids, target_group_id):
        """상품 복사"""
        import time
        
        url = f"{self.BASE_URL}/api/sourcing/bulk-copy-market-group"
        
        payload = {
            "selectedIds": product_ids,
            "targetMarketGroupId": target_group_id
        }
        
        # 재시도 로직 (최대 3회)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.post(url, json=payload, timeout=60)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code in [502, 503, 504]:
                    wait_time = (attempt + 1) * 5
                    print(f"[DEBUG] 복사 서버 오류 {response.status_code}, {wait_time}초 후 재시도...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise Exception(f"복사 오류: {response.status_code} - {response.text[:300]}")
            except requests.exceptions.Timeout:
                wait_time = (attempt + 1) * 5
                print(f"[DEBUG] 복사 타임아웃, {wait_time}초 후 재시도...")
                time.sleep(wait_time)
                continue
        
        raise Exception(f"복사 API 호출 실패 (재시도 {max_retries}회 초과)")
    
    def get_groups(self):
        """그룹 목록 조회"""
        url = f"{self.BASE_URL}/api/market/groups/"
        response = self.session.post(url, json={})
        print(f"[DEBUG] groups URL: {url}")
        print(f"[DEBUG] groups status: {response.status_code}")
        print(f"[DEBUG] groups response: {response.text[:500] if response.text else 'empty'}")
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"그룹 조회 오류: {response.status_code} - {response.text[:200]}")


class CopyWorker(QThread):
    """복사 작업 스레드"""
    progress = pyqtSignal(int, int)  # current, total
    log = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)
    
    def __init__(self, api, source_group, target_groups, copy_count, 
                 check_duplicate, check_all_groups, duplicate_field, status_filter, tag_filter, batch_size=100):
        super().__init__()
        self.api = api
        self.source_group = source_group
        self.target_groups = target_groups
        self.copy_count = copy_count
        self.check_duplicate = check_duplicate
        self.check_all_groups = check_all_groups
        self.duplicate_field = duplicate_field  # "productNo" 또는 "uploadBulsajaCode"
        self.status_filter = status_filter
        self.tag_filter = tag_filter
        self.batch_size = batch_size
        self.is_running = True
    
    def stop(self):
        self.is_running = False
    
    def run(self):
        try:
            field_names = {"productNo": "해외마켓ID", "uploadTrackcopyCode": "불사자코드", "uploadCommonProductName": "상품명"}
            field_name = field_names.get(self.duplicate_field, self.duplicate_field)
            
            self.log.emit(f"=== 복사 시작 ===")
            self.log.emit(f"소스: {self.source_group}")
            self.log.emit(f"대상: {', '.join(self.target_groups)}")
            self.log.emit(f"복사 수량: {self.copy_count}개")
            if self.check_duplicate:
                self.log.emit(f"중복 체크: {field_name}")
            
            # 1. 소스 그룹 상품 조회
            self.log.emit(f"\n[1] 소스 그룹 상품 조회 중... (1000개씩 배치 조회)")
            source_products = self.api.get_all_products(
                self.source_group,
                status_filter=self.status_filter,
                tag_filter=self.tag_filter,
                log_callback=lambda msg: self.log.emit(msg),
                stop_check=lambda: not self.is_running
            )
            
            if not self.is_running:
                self.finished_signal.emit(False, "사용자 중지")
                return
            
            # 소스 상품 정보 저장: {duplicate_field값: ID}
            source_map = {}  # {productNo 또는 uploadTrackcopyCode 또는 uploadCommonProductName: ID}
            for p in source_products:
                dup_key = p.get(self.duplicate_field)
                if dup_key:
                    # 상품명의 경우 공백 제거하여 비교 정확도 향상
                    if self.duplicate_field == "uploadCommonProductName":
                        dup_key = str(dup_key).strip()
                    source_map[dup_key] = p["ID"]
            
            self.log.emit(f"소스 상품 수: {len(source_map)}개")
            
            if not source_map:
                self.finished_signal.emit(False, "소스 그룹에 상품이 없습니다.")
                return
            
            # 2. 중복 체크
            existing_keys = set()
            if self.check_duplicate:
                # 중복 체크할 그룹 결정
                if self.check_all_groups:
                    check_groups = [g for g in GROUPS.keys() if g != self.source_group and g != "41_반수동(수집)"]
                    self.log.emit(f"\n[2] 전체 그룹 중복 체크 중... ({field_name} 기준, {len(check_groups)}개 그룹)")
                else:
                    check_groups = self.target_groups
                    self.log.emit(f"\n[2] 대상 그룹 중복 체크 중... ({field_name} 기준)")
                
                for group_name in check_groups:
                    if not self.is_running:
                        self.finished_signal.emit(False, "사용자 중지")
                        return
                    
                    try:
                        self.log.emit(f"  - {group_name} 조회 중...")
                        rows = self.api.get_all_products(
                            group_name,
                            stop_check=lambda: not self.is_running
                        )
                        if not self.is_running:
                            self.finished_signal.emit(False, "사용자 중지")
                            return
                        for row in rows:
                            dup_key = row.get(self.duplicate_field)
                            if dup_key:
                                # 상품명의 경우 공백 제거하여 비교
                                if self.duplicate_field == "uploadCommonProductName":
                                    dup_key = str(dup_key).strip()
                                existing_keys.add(dup_key)
                        self.log.emit(f"  - {group_name}: {len(rows)}개")
                    except Exception as e:
                        self.log.emit(f"  - {group_name}: 조회 실패 ({e})")
                
                self.log.emit(f"기존 {field_name} 총: {len(existing_keys)}개")
            
            # 3. 복사할 상품 필터링
            if self.check_duplicate:
                # 중복 아닌 것만 필터링
                copy_ids = [source_map[key] for key in source_map if key not in existing_keys]
                self.log.emit(f"\n중복 제외 후 복사 가능: {len(copy_ids)}개")
            else:
                copy_ids = list(source_map.values())
            
            # 복사 수량 제한
            copy_ids = copy_ids[:self.copy_count]
            self.log.emit(f"실제 복사 대상: {len(copy_ids)}개")
            
            if not copy_ids:
                self.finished_signal.emit(False, "복사할 상품이 없습니다.")
                return
            
            # 4. 복사 실행
            self.log.emit(f"\n[3] 복사 실행 중...")
            total_copied = 0
            
            for group_name in self.target_groups:
                if not self.is_running:
                    self.finished_signal.emit(False, "사용자 중지")
                    return
                
                target_id = GROUPS.get(group_name)
                if not target_id:
                    self.log.emit(f"  - {group_name}: ID를 찾을 수 없음")
                    continue
                
                self.log.emit(f"\n  → {group_name} ({target_id}) 복사 중...")
                
                # 배치 단위로 복사
                for i in range(0, len(copy_ids), self.batch_size):
                    if not self.is_running:
                        self.finished_signal.emit(False, "사용자 중지")
                        return
                    
                    batch = copy_ids[i:i + self.batch_size]
                    try:
                        result = self.api.copy_products(batch, target_id)
                        total_copied += len(batch)
                        self.progress.emit(total_copied, len(copy_ids) * len(self.target_groups))
                        self.log.emit(f"    배치 {i//self.batch_size + 1}: {len(batch)}개 완료")
                    except Exception as e:
                        self.log.emit(f"    배치 {i//self.batch_size + 1}: 실패 - {e}")
            
            self.log.emit(f"\n=== 복사 완료 ===")
            self.log.emit(f"총 {total_copied}개 복사됨")
            self.finished_signal.emit(True, f"복사 완료: {total_copied}개")
            
        except Exception as e:
            self.log.emit(f"\n오류 발생: {e}")
            self.finished_signal.emit(False, str(e))


class IntegratedCopyWorker(QThread):
    """통합그룹 복사 작업 스레드"""
    progress = pyqtSignal(int, int)
    log = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)
    
    def __init__(self, api, step, target_groups=None, count_per_group=10000, 
                 duplicate_field="productNo", ig_info=None):
        super().__init__()
        self.api = api
        self.step = step  # 1 또는 2
        self.target_groups = target_groups or []
        self.count_per_group = count_per_group
        self.duplicate_field = duplicate_field
        self.ig_info = ig_info or []  # [(대표그룹, [나머지그룹들]), ...]
        self.is_running = True
    
    def stop(self):
        self.is_running = False
    
    def run(self):
        try:
            if self.step == 1:
                self.run_step1()
            else:
                self.run_step2()
        except Exception as e:
            self.log.emit(f"\n오류 발생: {e}")
            self.finished_signal.emit(False, str(e))
    
    def run_step1(self):
        """1단계: 41_반수동 → 대표그룹들 분배"""
        field_names = {"productNo": "해외마켓ID", "uploadTrackcopyCode": "불사자코드", "uploadCommonProductName": "상품명"}
        field_name = field_names.get(self.duplicate_field, self.duplicate_field)
        
        # 1. 41_반수동 상품 조회
        self.log.emit(f"\n[1] 41_반수동(수집) 상품 조회 중...")
        source_products = self.api.get_all_products(
            "41_반수동(수집)",
            log_callback=lambda msg: self.log.emit(msg),
            stop_check=lambda: not self.is_running
        )
        
        if not self.is_running:
            self.finished_signal.emit(False, "사용자 중지")
            return
        
        # 소스 상품 정보 저장
        source_map = {}  # {duplicate_field값: ID}
        for p in source_products:
            dup_key = p.get(self.duplicate_field)
            if dup_key:
                # 상품명의 경우 공백 제거하여 비교 정확도 향상
                if self.duplicate_field == "uploadCommonProductName":
                    dup_key = str(dup_key).strip()
                source_map[dup_key] = p["ID"]
        
        self.log.emit(f"소스 상품 수: {len(source_map)}개")
        
        # 2. 전체 그룹 중복 체크
        self.log.emit(f"\n[2] 전체 그룹 중복 체크 중... ({field_name} 기준)")
        existing_keys = set()
        check_groups = [g for g in GROUPS.keys() if g != "41_반수동(수집)"]
        
        for group_name in check_groups:
            if not self.is_running:
                self.finished_signal.emit(False, "사용자 중지")
                return
            
            try:
                self.log.emit(f"  - {group_name} 조회 중...")
                rows = self.api.get_all_products(
                    group_name,
                    stop_check=lambda: not self.is_running
                )
                if not self.is_running:
                    self.finished_signal.emit(False, "사용자 중지")
                    return
                for row in rows:
                    dup_key = row.get(self.duplicate_field)
                    if dup_key:
                        # 상품명의 경우 공백 제거하여 비교
                        if self.duplicate_field == "uploadCommonProductName":
                            dup_key = str(dup_key).strip()
                        existing_keys.add(dup_key)
                self.log.emit(f"  - {group_name}: {len(rows)}개")
            except Exception as e:
                self.log.emit(f"  - {group_name}: 조회 실패 ({e})")
        
        self.log.emit(f"기존 {field_name} 총: {len(existing_keys)}개")
        
        # 3. 중복 제외한 복사 가능 ID 목록
        available_keys = [key for key in source_map if key not in existing_keys]
        self.log.emit(f"\n중복 제외 후 복사 가능: {len(available_keys)}개")
        
        # 4. 각 대표그룹에 분배
        self.log.emit(f"\n[3] 대표그룹에 분배 중...")
        total_needed = len(self.target_groups) * self.count_per_group
        
        if len(available_keys) < total_needed:
            self.log.emit(f"⚠️ 경고: 필요 {total_needed}개, 가용 {len(available_keys)}개")
        
        total_copied = 0
        key_index = 0
        
        for group_name in self.target_groups:
            if not self.is_running:
                self.finished_signal.emit(False, "사용자 중지")
                return
            
            target_id = GROUPS.get(group_name)
            if not target_id:
                self.log.emit(f"  - {group_name}: ID를 찾을 수 없음")
                continue
            
            # 이 그룹에 복사할 ID 추출
            copy_keys = available_keys[key_index:key_index + self.count_per_group]
            key_index += self.count_per_group
            
            if not copy_keys:
                self.log.emit(f"  - {group_name}: 복사할 상품 없음")
                continue
            
            copy_ids = [source_map[key] for key in copy_keys]
            
            self.log.emit(f"\n  → {group_name} ({target_id}) 복사 중... ({len(copy_ids)}개)")
            
            # 배치 단위로 복사
            batch_size = 100
            for i in range(0, len(copy_ids), batch_size):
                if not self.is_running:
                    self.finished_signal.emit(False, "사용자 중지")
                    return
                
                batch = copy_ids[i:i + batch_size]
                try:
                    self.api.copy_products(batch, target_id)
                    total_copied += len(batch)
                    self.log.emit(f"    배치 {i//batch_size + 1}: {len(batch)}개 완료")
                    self.progress.emit(total_copied, total_needed)
                except Exception as e:
                    self.log.emit(f"    배치 {i//batch_size + 1}: 실패 - {e}")
        
        self.log.emit(f"\n=== 1단계 완료 ===")
        self.log.emit(f"총 {total_copied}개 복사됨")
        self.finished_signal.emit(True, f"1단계 완료: {total_copied}개")
    
    def run_step2(self):
        """2단계: 대표그룹 → 나머지 그룹 복사"""
        total_copied = 0
        
        for src_group, target_groups in self.ig_info:
            if not self.is_running:
                self.finished_signal.emit(False, "사용자 중지")
                return
            
            self.log.emit(f"\n[{src_group}] 상품 조회 중...")
            
            # 대표그룹 상품 조회
            try:
                source_products = self.api.get_all_products(
                    src_group,
                    log_callback=lambda msg: self.log.emit(msg),
                    stop_check=lambda: not self.is_running
                )
            except Exception as e:
                self.log.emit(f"  조회 실패: {e}")
                continue
            
            if not self.is_running:
                self.finished_signal.emit(False, "사용자 중지")
                return
            
            source_ids = [p["ID"] for p in source_products]
            self.log.emit(f"  상품 수: {len(source_ids)}개")
            
            if not source_ids:
                continue
            
            # 나머지 그룹들에 복사
            for target_group in target_groups:
                if not self.is_running:
                    self.finished_signal.emit(False, "사용자 중지")
                    return
                
                target_id = GROUPS.get(target_group)
                if not target_id:
                    self.log.emit(f"  - {target_group}: ID를 찾을 수 없음")
                    continue
                
                self.log.emit(f"\n  → {target_group} ({target_id}) 복사 중...")
                
                # 배치 단위로 복사
                batch_size = 100
                for i in range(0, len(source_ids), batch_size):
                    if not self.is_running:
                        self.finished_signal.emit(False, "사용자 중지")
                        return
                    
                    batch = source_ids[i:i + batch_size]
                    try:
                        self.api.copy_products(batch, target_id)
                        total_copied += len(batch)
                        self.log.emit(f"    배치 {i//batch_size + 1}: {len(batch)}개 완료")
                    except Exception as e:
                        self.log.emit(f"    배치 {i//batch_size + 1}: 실패 - {e}")
        
        self.log.emit(f"\n=== 2단계 완료 ===")
        self.log.emit(f"총 {total_copied}개 복사됨")
        self.finished_signal.emit(True, f"2단계 완료: {total_copied}개")


class MainWindow(QMainWindow):
    """메인 윈도우"""
    
    def __init__(self):
        super().__init__()
        self.api = None
        self.worker = None
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("불사자 상품 복사 프로그램 v1.0")
        self.setMinimumSize(900, 700)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # === 토큰 설정 ===
        token_group = QGroupBox("🔑 토큰 설정")
        token_layout = QVBoxLayout(token_group)
        
        # Chrome Debug 포트 + 버튼들
        h0 = QHBoxLayout()
        h0.addWidget(QLabel("Chrome 포트:"))
        self.port_input = QSpinBox()
        self.port_input.setRange(1000, 65535)
        self.port_input.setValue(9222)
        h0.addWidget(self.port_input)
        
        self.chrome_launch_btn = QPushButton("🌐 Chrome Debug 실행")
        self.chrome_launch_btn.clicked.connect(self.launch_chrome_debug)
        self.chrome_launch_btn.setStyleSheet("background-color: #607D8B; color: white;")
        h0.addWidget(self.chrome_launch_btn)
        
        self.auto_extract_btn = QPushButton("🔄 토큰 추출")
        self.auto_extract_btn.clicked.connect(self.auto_extract_token)
        self.auto_extract_btn.setStyleSheet("background-color: #2196F3; color: white;")
        h0.addWidget(self.auto_extract_btn)
        token_layout.addLayout(h0)
        
        # Access Token
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("Access Token:"))
        self.access_token_input = QLineEdit()
        self.access_token_input.setPlaceholderText("자동 추출 또는 수동 입력")
        h1.addWidget(self.access_token_input)
        token_layout.addLayout(h1)
        
        # Refresh Token
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("Refresh Token:"))
        self.refresh_token_input = QLineEdit()
        self.refresh_token_input.setPlaceholderText("자동 추출 또는 수동 입력")
        h2.addWidget(self.refresh_token_input)
        token_layout.addLayout(h2)
        
        # 연결 버튼
        self.connect_btn = QPushButton("🔗 연결 테스트")
        self.connect_btn.clicked.connect(self.test_connection)
        token_layout.addWidget(self.connect_btn)
        
        layout.addWidget(token_group)
        
        # === 탭 위젯 ===
        tabs = QTabWidget()
        
        # 탭1: 일반 복사
        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)
        
        # 소스 그룹
        source_group = QGroupBox("📦 소스 그룹")
        source_layout = QHBoxLayout(source_group)
        source_layout.addWidget(QLabel("소스:"))
        self.source_combo = QComboBox()
        self.source_combo.addItems(sorted(GROUPS.keys()))
        self.source_combo.setCurrentText("41_반수동(수집)")
        source_layout.addWidget(self.source_combo)
        
        source_layout.addWidget(QLabel("수량:"))
        self.copy_count_spin = QSpinBox()
        self.copy_count_spin.setRange(1, 100000)
        self.copy_count_spin.setValue(10000)
        source_layout.addWidget(self.copy_count_spin)
        
        tab1_layout.addWidget(source_group)
        
        # 필터 옵션
        filter_group = QGroupBox("🔍 필터 옵션")
        filter_layout = QHBoxLayout(filter_group)
        
        filter_layout.addWidget(QLabel("상태:"))
        self.status_combo = QComboBox()
        self.status_combo.addItems(["전체", "수집완료", "수정중", "검토완료", "수집중", "판매중"])
        filter_layout.addWidget(self.status_combo)
        
        filter_layout.addWidget(QLabel("태그:"))
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("태그 입력 (선택사항)")
        filter_layout.addWidget(self.tag_input)
        
        self.duplicate_check = QCheckBox("중복 체크")
        self.duplicate_check.setChecked(True)
        filter_layout.addWidget(self.duplicate_check)
        
        filter_layout.addWidget(QLabel("기준:"))
        self.duplicate_field_combo = QComboBox()
        self.duplicate_field_combo.addItems(["해외마켓ID", "불사자코드", "상품명"])
        filter_layout.addWidget(self.duplicate_field_combo)
        
        self.check_all_groups = QCheckBox("전체그룹")
        self.check_all_groups.setChecked(True)
        self.check_all_groups.setToolTip("체크: 40개 전체 그룹에서 중복 확인\n해제: 복사 대상 그룹만 중복 확인")
        filter_layout.addWidget(self.check_all_groups)
        
        tab1_layout.addWidget(filter_group)
        
        # 대상 그룹 선택 (왼쪽 → 오른쪽 이동 방식)
        target_group = QGroupBox("🎯 대상 그룹 선택")
        target_layout = QVBoxLayout(target_group)
        
        # 프리셋 버튼 (2줄로)
        preset_layout1 = QHBoxLayout()
        preset_layout2 = QHBoxLayout()
        ig_names = list(INTEGRATED_GROUPS.keys())
        for i, name in enumerate(ig_names):
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, n=name: self.select_integrated_group(n))
            if i < 5:
                preset_layout1.addWidget(btn)
            else:
                preset_layout2.addWidget(btn)
        target_layout.addLayout(preset_layout1)
        target_layout.addLayout(preset_layout2)
        
        # 왼쪽(전체) / 버튼 / 오른쪽(선택됨) 레이아웃
        list_layout = QHBoxLayout()
        
        # 왼쪽: 선택 가능한 그룹
        left_box = QVBoxLayout()
        left_box.addWidget(QLabel("📋 선택 가능"))
        self.available_list = QListWidget()
        self.available_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.available_list.itemDoubleClicked.connect(self.on_available_double_click)
        for name in sorted(GROUPS.keys()):
            if name != "41_반수동(수집)":
                self.available_list.addItem(name)
        left_box.addWidget(self.available_list)
        list_layout.addLayout(left_box)
        
        # 가운데: 이동 버튼
        btn_box = QVBoxLayout()
        btn_box.addStretch()
        
        add_btn = QPushButton("▶")
        add_btn.setFixedWidth(40)
        add_btn.clicked.connect(self.move_to_selected)
        btn_box.addWidget(add_btn)
        
        add_all_btn = QPushButton("▶▶")
        add_all_btn.setFixedWidth(40)
        add_all_btn.clicked.connect(self.move_all_to_selected)
        btn_box.addWidget(add_all_btn)
        
        remove_btn = QPushButton("◀")
        remove_btn.setFixedWidth(40)
        remove_btn.clicked.connect(self.move_to_available)
        btn_box.addWidget(remove_btn)
        
        remove_all_btn = QPushButton("◀◀")
        remove_all_btn.setFixedWidth(40)
        remove_all_btn.clicked.connect(self.move_all_to_available)
        btn_box.addWidget(remove_all_btn)
        
        btn_box.addStretch()
        list_layout.addLayout(btn_box)
        
        # 오른쪽: 선택된 그룹
        right_box = QVBoxLayout()
        right_box.addWidget(QLabel("✅ 선택됨"))
        self.selected_list = QListWidget()
        self.selected_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.selected_list.itemDoubleClicked.connect(self.on_selected_double_click)
        right_box.addWidget(self.selected_list)
        list_layout.addLayout(right_box)
        
        target_layout.addLayout(list_layout)
        
        tab1_layout.addWidget(target_group)
        tabs.addTab(tab1, "일반 복사")
        
        # 탭2: 통합그룹 복사
        tab2 = QWidget()
        tab2_layout = QVBoxLayout(tab2)
        
        # 설명
        desc_group = QGroupBox("📖 설명")
        desc_layout = QVBoxLayout(desc_group)
        desc_layout.addWidget(QLabel("1단계: 41_반수동 → 각 통합그룹 대표그룹에 분배 (중복 없이)"))
        desc_layout.addWidget(QLabel("2단계: 대표그룹 → 나머지 3개 그룹에 동일 상품 복사"))
        desc_layout.addWidget(QLabel("예: 통합1 선택 시 → 41번→01번(1단계) → 01번→02,03,04번(2단계)"))
        tab2_layout.addWidget(desc_group)
        
        # 설정
        setting_group = QGroupBox("⚙️ 설정")
        setting_layout = QHBoxLayout(setting_group)
        
        setting_layout.addWidget(QLabel("그룹당 수량:"))
        self.ig_count_spin = QSpinBox()
        self.ig_count_spin.setRange(100, 100000)
        self.ig_count_spin.setValue(10000)
        setting_layout.addWidget(self.ig_count_spin)
        
        setting_layout.addWidget(QLabel("중복체크:"))
        self.ig_dup_field_combo = QComboBox()
        self.ig_dup_field_combo.addItems(["해외마켓ID", "불사자코드", "상품명"])
        setting_layout.addWidget(self.ig_dup_field_combo)
        
        setting_layout.addStretch()
        tab2_layout.addWidget(setting_group)
        
        # 통합그룹 선택
        ig_group = QGroupBox("🎯 통합그룹 선택")
        ig_layout = QHBoxLayout(ig_group)
        
        self.ig_list = QListWidget()
        self.ig_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for name in INTEGRATED_GROUPS.keys():
            item = QListWidgetItem(name)
            self.ig_list.addItem(item)
        ig_layout.addWidget(self.ig_list)
        
        # 전체 선택/해제 버튼
        ig_btn_box = QVBoxLayout()
        ig_select_all = QPushButton("전체 선택")
        ig_select_all.clicked.connect(lambda: [self.ig_list.item(i).setSelected(True) for i in range(self.ig_list.count())])
        ig_btn_box.addWidget(ig_select_all)
        
        ig_deselect_all = QPushButton("전체 해제")
        ig_deselect_all.clicked.connect(lambda: [self.ig_list.item(i).setSelected(False) for i in range(self.ig_list.count())])
        ig_btn_box.addWidget(ig_deselect_all)
        ig_btn_box.addStretch()
        ig_layout.addLayout(ig_btn_box)
        
        tab2_layout.addWidget(ig_group)
        
        # 실행 버튼
        btn_group = QGroupBox("🚀 실행")
        btn_layout2 = QHBoxLayout(btn_group)
        
        self.ig_step1_btn = QPushButton("1단계: 소스→대표그룹 분배")
        self.ig_step1_btn.setFixedHeight(35)
        self.ig_step1_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #42A5F5, stop:1 #1976D2);
                color: white; 
                font-weight: bold; 
                font-size: 11px;
                border: 1px solid #1565C0;
                border-radius: 3px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #64B5F6, stop:1 #2196F3);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1976D2, stop:1 #0D47A1);
            }
        """)
        self.ig_step1_btn.clicked.connect(self.start_integrated_step1)
        btn_layout2.addWidget(self.ig_step1_btn)
        
        self.ig_step2_btn = QPushButton("2단계: 대표→나머지 복사")
        self.ig_step2_btn.setFixedHeight(35)
        self.ig_step2_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FFB74D, stop:1 #F57C00);
                color: white; 
                font-weight: bold; 
                font-size: 11px;
                border: 1px solid #E65100;
                border-radius: 3px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FFCC80, stop:1 #FF9800);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F57C00, stop:1 #BF360C);
            }
        """)
        self.ig_step2_btn.clicked.connect(self.start_integrated_step2)
        btn_layout2.addWidget(self.ig_step2_btn)
        
        tab2_layout.addWidget(btn_group)
        
        tabs.addTab(tab2, "통합그룹 복사")
        
        layout.addWidget(tabs)
        
        # === 실행 버튼 ===
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("🚀 복사 시작")
        self.start_btn.clicked.connect(self.start_copy)
        self.start_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 10px;")
        btn_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("⏹️ 중지")
        self.stop_btn.clicked.connect(self.stop_copy)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; padding: 10px;")
        btn_layout.addWidget(self.stop_btn)
        
        layout.addLayout(btn_layout)
        
        # === 진행 상황 ===
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        
        # === 로그 ===
        log_group = QGroupBox("📋 로그")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_group)
    
    def launch_chrome_debug(self):
        """Chrome Debug 모드 실행"""
        import subprocess
        import os
        
        port = self.port_input.value()
        
        # Chrome 경로 후보
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        ]
        
        chrome_path = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_path = path
                break
        
        if not chrome_path:
            QMessageBox.warning(self, "오류", "Chrome을 찾을 수 없습니다.")
            return
        
        # 사용자 데이터 디렉토리
        user_data_dir = os.path.expanduser(r"~\ChromeDebug")
        
        cmd = [
            chrome_path,
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={user_data_dir}",
            "https://www.bulsaja.com/products/manage/list"
        ]
        
        try:
            subprocess.Popen(cmd)
            self.log_text.append(f"🌐 Chrome Debug 모드 실행 (포트: {port})")
            self.log_text.append("   불사자 로그인 후 '토큰 추출' 버튼을 클릭하세요.")
        except Exception as e:
            QMessageBox.warning(self, "오류", f"Chrome 실행 실패: {e}")
    
    def auto_extract_token(self):
        """브라우저에서 토큰 자동 추출"""
        port = self.port_input.value()
        self.log_text.append(f"🔄 포트 {port}에서 토큰 추출 중...")
        
        tokens, error = BulsajaAPI.extract_token_from_browser(port)
        
        if tokens:
            self.access_token_input.setText(tokens["access"])
            self.refresh_token_input.setText(tokens["refresh"])
            self.log_text.append("✅ 토큰 추출 성공!")
            
            # 자동으로 연결 테스트
            self.test_connection()
        else:
            self.log_text.append(f"❌ {error}")
            QMessageBox.warning(self, "추출 실패", error)
    
    def test_connection(self):
        """연결 테스트"""
        access_token = self.access_token_input.text().strip()
        refresh_token = self.refresh_token_input.text().strip()
        
        if not access_token or not refresh_token:
            QMessageBox.warning(self, "경고", "토큰을 입력해주세요.")
            return
        
        try:
            self.api = BulsajaAPI(access_token, refresh_token)
            groups = self.api.get_groups()
            self.log_text.append(f"✅ 연결 성공! 그룹 수: {len(groups)}개")
            QMessageBox.information(self, "성공", f"연결 성공!\n그룹 수: {len(groups)}개")
        except Exception as e:
            self.log_text.append(f"❌ 연결 실패: {e}")
            QMessageBox.critical(self, "오류", f"연결 실패:\n{e}")
    
    def select_integrated_group(self, ig_name):
        """통합그룹 선택 - 해당 그룹을 오른쪽으로 이동"""
        groups = INTEGRATED_GROUPS.get(ig_name, [])
        
        # 왼쪽에서 해당 그룹들을 찾아 오른쪽으로 이동
        items_to_move = []
        for i in range(self.available_list.count()):
            item = self.available_list.item(i)
            if item.text() in groups:
                items_to_move.append(item.text())
        
        for text in items_to_move:
            # 왼쪽에서 제거
            for i in range(self.available_list.count()):
                if self.available_list.item(i).text() == text:
                    self.available_list.takeItem(i)
                    break
            # 오른쪽에 추가 (중복 체크)
            exists = False
            for i in range(self.selected_list.count()):
                if self.selected_list.item(i).text() == text:
                    exists = True
                    break
            if not exists:
                self.selected_list.addItem(text)
        
        # 오른쪽 정렬
        self.sort_selected_list()
    
    def on_available_double_click(self, item):
        """왼쪽 리스트 더블클릭 → 오른쪽으로 이동"""
        text = item.text()
        row = self.available_list.row(item)
        self.available_list.takeItem(row)
        self.selected_list.addItem(text)
        self.sort_selected_list()
    
    def on_selected_double_click(self, item):
        """오른쪽 리스트 더블클릭 → 왼쪽으로 이동"""
        text = item.text()
        row = self.selected_list.row(item)
        self.selected_list.takeItem(row)
        self.available_list.addItem(text)
        self.sort_available_list()
    
    def move_to_selected(self):
        """선택한 항목을 오른쪽으로 이동"""
        selected = self.available_list.selectedItems()
        for item in selected:
            text = item.text()
            row = self.available_list.row(item)
            self.available_list.takeItem(row)
            self.selected_list.addItem(text)
        self.sort_selected_list()
    
    def move_all_to_selected(self):
        """전체를 오른쪽으로 이동"""
        while self.available_list.count() > 0:
            item = self.available_list.takeItem(0)
            self.selected_list.addItem(item.text())
        self.sort_selected_list()
    
    def move_to_available(self):
        """선택한 항목을 왼쪽으로 이동"""
        selected = self.selected_list.selectedItems()
        for item in selected:
            text = item.text()
            row = self.selected_list.row(item)
            self.selected_list.takeItem(row)
            self.available_list.addItem(text)
        self.sort_available_list()
    
    def move_all_to_available(self):
        """전체를 왼쪽으로 이동"""
        while self.selected_list.count() > 0:
            item = self.selected_list.takeItem(0)
            self.available_list.addItem(item.text())
        self.sort_available_list()
    
    def sort_selected_list(self):
        """선택된 목록 정렬"""
        items = []
        while self.selected_list.count() > 0:
            items.append(self.selected_list.takeItem(0).text())
        for text in sorted(items):
            self.selected_list.addItem(text)
    
    def sort_available_list(self):
        """선택 가능 목록 정렬"""
        items = []
        while self.available_list.count() > 0:
            items.append(self.available_list.takeItem(0).text())
        for text in sorted(items):
            self.available_list.addItem(text)
    
    def start_copy(self):
        """복사 시작"""
        if not self.api:
            QMessageBox.warning(self, "경고", "먼저 토큰을 입력하고 연결 테스트를 해주세요.")
            return
        
        # 선택된 대상 그룹 (오른쪽 목록)
        if self.selected_list.count() == 0:
            QMessageBox.warning(self, "경고", "대상 그룹을 선택해주세요.")
            return
        
        target_groups = []
        for i in range(self.selected_list.count()):
            target_groups.append(self.selected_list.item(i).text())
        
        source_group = self.source_combo.currentText()
        copy_count = self.copy_count_spin.value()
        check_duplicate = self.duplicate_check.isChecked()
        
        status_filter = self.status_combo.currentText()
        if status_filter == "전체":
            status_filter = None
        else:
            # 상태 텍스트 → 코드 변환
            status_map = {
                "수집완료": "0",
                "수정중": "1",
                "검토완료": "2",
                "수집중": "3",
                "판매중": "4"
            }
            status_filter = status_map.get(status_filter)
        
        tag_filter = self.tag_input.text().strip() or None
        
        # 중복 체크 기준 필드
        dup_field_text = self.duplicate_field_combo.currentText()
        dup_field_map = {"해외마켓ID": "productNo", "불사자코드": "uploadTrackcopyCode", "상품명": "uploadCommonProductName"}
        duplicate_field = dup_field_map.get(dup_field_text, "productNo")
        
        # 전체 그룹 중복 체크 여부
        check_all_groups = self.check_all_groups.isChecked()
        
        # 작업 시작
        self.worker = CopyWorker(
            self.api, source_group, target_groups, copy_count,
            check_duplicate, check_all_groups, duplicate_field, status_filter, tag_filter
        )
        self.worker.progress.connect(self.update_progress)
        self.worker.log.connect(self.append_log)
        self.worker.finished_signal.connect(self.on_copy_finished)
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        
        self.worker.start()
    
    def start_integrated_step1(self):
        """1단계: 41_반수동 → 대표그룹 분배"""
        if not self.api:
            QMessageBox.warning(self, "경고", "먼저 토큰을 입력하고 연결 테스트를 해주세요.")
            return
        
        selected_items = self.ig_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "경고", "통합그룹을 선택해주세요.")
            return
        
        # 선택된 통합그룹의 대표그룹(첫번째) 추출
        target_groups = []
        for item in selected_items:
            ig_name = item.text()
            groups = INTEGRATED_GROUPS.get(ig_name, [])
            if groups:
                target_groups.append(groups[0])  # 대표그룹 (첫번째)
        
        count_per_group = self.ig_count_spin.value()
        dup_field_text = self.ig_dup_field_combo.currentText()
        dup_field_map = {"해외마켓ID": "productNo", "불사자코드": "uploadTrackcopyCode", "상품명": "uploadCommonProductName"}
        duplicate_field = dup_field_map.get(dup_field_text, "productNo")
        
        self.log_text.append(f"\n{'='*50}")
        self.log_text.append(f"🚀 1단계: 41_반수동 → 대표그룹 분배")
        self.log_text.append(f"대상 그룹: {', '.join(target_groups)}")
        self.log_text.append(f"그룹당 수량: {count_per_group}개")
        self.log_text.append(f"{'='*50}")
        
        # Worker 생성 - 1단계 모드
        self.worker = IntegratedCopyWorker(
            self.api, 
            step=1,
            target_groups=target_groups,
            count_per_group=count_per_group,
            duplicate_field=duplicate_field
        )
        self.worker.progress.connect(self.update_progress)
        self.worker.log.connect(self.append_log)
        self.worker.finished_signal.connect(self.on_copy_finished)
        
        self.ig_step1_btn.setEnabled(False)
        self.ig_step2_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        
        self.worker.start()
    
    def start_integrated_step2(self):
        """2단계: 대표그룹 → 나머지 그룹 복사"""
        if not self.api:
            QMessageBox.warning(self, "경고", "먼저 토큰을 입력하고 연결 테스트를 해주세요.")
            return
        
        selected_items = self.ig_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "경고", "통합그룹을 선택해주세요.")
            return
        
        # 선택된 통합그룹 정보 추출
        ig_info = []  # [(대표그룹, [나머지그룹들]), ...]
        for item in selected_items:
            ig_name = item.text()
            groups = INTEGRATED_GROUPS.get(ig_name, [])
            if len(groups) >= 2:
                ig_info.append((groups[0], groups[1:]))
        
        self.log_text.append(f"\n{'='*50}")
        self.log_text.append(f"🚀 2단계: 대표그룹 → 나머지 그룹 복사")
        for src, targets in ig_info:
            self.log_text.append(f"  {src} → {', '.join(targets)}")
        self.log_text.append(f"{'='*50}")
        
        # Worker 생성 - 2단계 모드
        self.worker = IntegratedCopyWorker(
            self.api,
            step=2,
            ig_info=ig_info
        )
        self.worker.progress.connect(self.update_progress)
        self.worker.log.connect(self.append_log)
        self.worker.finished_signal.connect(self.on_copy_finished)
        
        self.ig_step1_btn.setEnabled(False)
        self.ig_step2_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        
        self.worker.start()
    
    def start_integrated_copy(self):
        """통합그룹 복사 (미사용)"""
        pass
    
    def stop_copy(self):
        """복사 중지"""
        if self.worker:
            self.worker.stop()
            self.log_text.append("⏹️ 중지 요청됨...")
    
    def update_progress(self, current, total):
        """진행률 업데이트"""
        if total > 0:
            self.progress_bar.setValue(int(current / total * 100))
    
    def append_log(self, message):
        """로그 추가"""
        self.log_text.append(message)
        # 스크롤 맨 아래로
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
    
    def on_copy_finished(self, success, message):
        """복사 완료"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.ig_step1_btn.setEnabled(True)
        self.ig_step2_btn.setEnabled(True)
        
        if success:
            QMessageBox.information(self, "완료", message)
        else:
            QMessageBox.warning(self, "알림", message)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
