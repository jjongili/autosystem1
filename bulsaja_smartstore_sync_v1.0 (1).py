#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
불사자 스마트스토어 동기화 프로그램 v1.0
- 불사자 '업로드됨' 상품 중 실제 스마트스토어에 없는 상품 찾기
- 자동으로 미업로드 + 수정중 상태로 변경
- 불사자 내장 API 활용 (네이버 API 불필요)
"""

import sys
import json
import requests
import websocket
import time
import re
import csv
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QSpinBox, QCheckBox, QGroupBox,
    QTextEdit, QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QMessageBox, QFileDialog, QDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

# 그룹 매핑 데이터 (API에서 동적으로 로드)
GROUPS = {}  # {group_name: group_id}

# 세트별 그룹 정의 (UI용 - 하드코딩)
SET_GROUPS = {
    "플로": [
        "1번_복지3", "2번_복지1", "3번_복지2", "4번_태도1", "5번_태도2",
        "6번_태도3", "7번_파이2", "8번_파이3", "9번_파이4", "10번_검은1",
        "11번_오키1", "12번_오키2", "13번_오키3", "14번_오키4", "15번_오키5",
        "16번_오키6", "17번_오키7", "18번_오키8", "19번_오키9", "20번_오키10",
    ],
    "흑곰": [
        "1번_검은2", "2번_검은3", "3번_윤미9", "4번_차키1", "5번_더팔린1",
        "6번_더팔린2", "7번_더팔린3", "8번_더팔린4", "9번_더팔린5", "10번_차키2",
        "11번_흑곰1", "12번_흑곰2", "13번_흑곰3", "14번_흑곰4", "15번_흑곰5",
        "16번_흑곰6", "17번_흑곰7", "18번_차키3", "19번_차키4", "20번_직구5",
    ],
    "검은곰": [
        "1번_대량1", "2번_대량2", "3번_대량3", "4번_대량4", "5번_대량5",
        "6번_대량6", "7번_차키5다시", "8번_차키6", "9번_직구3", "50번_수집",
        "11번_재만1", "12번_오팔린2", "13번_오팔린4", "14번_퍼티2", "15번_직구2",
        "16번_구대6", "17번_구대7", "18번_구대8", "19번_구대9", "20번_구대10",
    ],
}


def is_connection_error(error_msg):
    """연결 오류인지 확인"""
    error_lower = error_msg.lower()
    connection_errors = [
        "timed out", "timeout", "connection aborted", "remotedisconnected",
        "connectionerror", "connection reset", "broken pipe", "connection refused",
    ]
    return any(err in error_lower for err in connection_errors)


class BulsajaAPI:
    """불사자 API 클래스"""
    
    BASE_URL = "https://api.bulsaja.com"
    
    def __init__(self, access_token, refresh_token):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._create_session()
    
    def _create_session(self):
        """새 세션 생성"""
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Accesstoken": self.access_token,
            "Refreshtoken": self.refresh_token,
            "Origin": "https://www.bulsaja.com",
            "Referer": "https://www.bulsaja.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
    
    def reset_session(self):
        """세션 리셋"""
        if self.session:
            self.session.close()
        self._create_session()
    
    @staticmethod
    def extract_token_from_browser(port=9222):
        """Chrome Debug 모드에서 토큰 추출"""
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/json", timeout=5)
            tabs = resp.json()
            
            bulsaja_tab = None
            for tab in tabs:
                if "bulsaja.com" in tab.get("url", "") and tab.get("type") == "page":
                    bulsaja_tab = tab
                    break
            
            if not bulsaja_tab:
                return None, "불사자 탭을 찾을 수 없습니다."
            
            ws_url = bulsaja_tab.get("webSocketDebuggerUrl")
            if not ws_url:
                return None, "WebSocket URL을 찾을 수 없습니다."
            
            ws = websocket.create_connection(ws_url, timeout=10)
            
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
                return JSON.stringify({accessToken: null, refreshToken: null});
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
                    if tokens.get("accessToken") and tokens.get("refreshToken"):
                        return {"access": tokens["accessToken"], "refresh": tokens["refreshToken"]}, None
            
            return None, "토큰 추출 실패"
            
        except requests.exceptions.ConnectionError:
            return None, f"Chrome Debug 연결 실패 (포트 {port})"
        except Exception as e:
            return None, f"오류: {str(e)}"
    
    def get_products(self, group_name, start_row=0, end_row=10000, market_type_filter=None):
        """상품 목록 조회"""
        url = f"{self.BASE_URL}/api/manage/list/serverside"
        
        filter_model = {
            "marketGroupName": {
                "filterType": "text",
                "type": "equals",
                "filter": group_name
            }
        }
        
        if market_type_filter:
            filter_model["marketType"] = {
                "filterType": "text",
                "type": "equals",
                "filter": market_type_filter
            }
        
        payload = {
            "request": {
                "startRow": start_row,
                "endRow": end_row,
                "sortModel": [],
                "filterModel": filter_model
            }
        }
        
        response = self.session.post(url, json=payload, timeout=60)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"API 오류: {response.status_code}")
    
    def get_all_products(self, group_name, market_type_filter=None, batch_size=1000, 
                         log_callback=None, stop_check=None):
        """상품 전체 조회"""
        all_rows = []
        start_row = 0
        
        while True:
            if stop_check and stop_check():
                return all_rows
            
            if log_callback:
                log_callback(f"  조회 중... {start_row}~{start_row + batch_size}")
            
            data = self.get_products(
                group_name, 
                start_row=start_row, 
                end_row=start_row + batch_size,
                market_type_filter=market_type_filter
            )
            
            rows = data.get("rowData", [])
            all_rows.extend(rows)
            
            if len(rows) < batch_size:
                break
            
            start_row += batch_size
        
        return all_rows
    
    def check_smartstore_product(self, group_id, channel_product_no):
        """
        스마트스토어 상품 확인 API
        - 상품이 있으면: {"message": "OK", "data": {...}}
        - 상품이 없으면: {"fixed": true, "reason": "MARKET_PRODUCT_NOT_FOUND_AND_FIXED", ...}
          → 자동으로 미업로드 + 수정중 처리됨
        """
        url = f"{self.BASE_URL}/api/market/group/{group_id}/smartstore/uploaded-products/{channel_product_no}/"
        payload = {"targetMarket": "SMARTSTORE"}

        response = self.session.post(url, json=payload, timeout=30)

        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"API 오류: {response.status_code}")
    
    def get_groups(self):
        """그룹 목록 조회 - {name: id} 딕셔너리와 그룹명 리스트 반환 (오름차순 정렬)"""
        url = f"{self.BASE_URL}/api/market/groups/"
        response = self.session.post(url, json={})
        if response.status_code == 200:
            data = response.json()
            # 그룹 데이터 파싱
            groups_dict = {}
            if isinstance(data, list):
                for g in data:
                    name = g.get('name', '')
                    gid = g.get('id')
                    if name and gid:
                        groups_dict[name] = gid
            # 그룹명 번호순 정렬 (앞의 숫자 기준)
            def sort_by_number(name):
                match = re.match(r'^(\d+)', name)
                return int(match.group(1)) if match else 9999
            group_names = sorted(groups_dict.keys(), key=sort_by_number)
            return groups_dict, group_names
        else:
            raise Exception(f"그룹 조회 오류: {response.status_code}")


class SyncWorker(QThread):
    """동기화 작업 스레드 (단일 그룹)"""
    progress = pyqtSignal(int, int)  # current, total
    log = pyqtSignal(str)
    product_checked = pyqtSignal(dict)  # 체크 결과
    finished_signal = pyqtSignal(bool, str, object)

    PARALLEL_COUNT = 2  # 동시 요청 수 (500 오류 방지를 위해 줄임)
    
    def __init__(self, api, group_name, group_id, check_only=False):
        super().__init__()
        self.api = api
        self.group_name = group_name
        self.group_id = group_id
        self.check_only = check_only  # True: 확인만, False: 자동 수정
        self.is_running = True
    
    def stop(self):
        self.is_running = False
    
    def check_single_product(self, product_info):
        """단일 상품 체크"""
        try:
            channel_no = product_info.get("channel_product_no")
            if not channel_no:
                return None

            result = self.api.check_smartstore_product(self.group_id, channel_no)

            # 상품이 없으면 fixed=true, 있으면 message="OK"
            is_fixed = result.get("fixed", False)
            is_exists = result.get("message") == "OK" or ("data" in result and result.get("data"))

            return {
                "product": product_info,
                "result": result,
                "fixed": is_fixed,
                "reason": result.get("reason", ""),
                "exists": is_exists and not is_fixed,
            }
        except Exception as e:
            return {
                "product": product_info,
                "error": str(e),
                "fixed": False,
                "exists": None,
            }
    
    def run(self):
        try:
            self.log.emit(f"\n{'='*60}")
            self.log.emit(f"🔄 스마트스토어 동기화 시작: {self.group_name}")
            self.log.emit(f"{'='*60}")
            
            # 1. 업로드됨 상품 조회
            self.log.emit(f"\n📦 [1단계] 업로드됨 상품 조회 중...")
            products = self.api.get_all_products(
                self.group_name,
                market_type_filter="uploaded",
                log_callback=lambda msg: self.log.emit(msg),
                stop_check=lambda: not self.is_running
            )
            
            if not self.is_running:
                self.finished_signal.emit(False, "사용자 중지", None)
                return
            
            self.log.emit(f"  ✅ 업로드됨 상품: {len(products)}개")
            
            if not products:
                self.finished_signal.emit(False, "업로드됨 상품이 없습니다.", None)
                return

            # 2. 채널상품번호 추출
            self.log.emit(f"\n🔍 [2단계] 스마트스토어 상품 확인 중...")

            # 첫 번째 상품의 모든 필드 출력 (디버깅용)
            if products:
                self.log.emit(f"\n  📋 [디버그] 첫 번째 상품 필드들:")
                first_product = products[0]
                for key, value in first_product.items():
                    if value:  # 값이 있는 필드만 출력
                        self.log.emit(f"     • {key}: {str(value)[:100]}")

            # 채널상품번호가 있는 상품만 필터링
            products_to_check = []
            for p in products:
                # 채널상품번호는 uploadedSuccessUrl.smartstore에 있음
                uploaded_success_url = p.get("uploadedSuccessUrl") or {}
                channel_no = uploaded_success_url.get("smartstore") or ""

                if channel_no:
                    products_to_check.append({
                        "sourcingId": p.get("sourcingId") or p.get("ID"),
                        "productName": p.get("uploadCommonProductName") or p.get("productName") or "",
                        "channel_product_no": str(channel_no),
                        "bulsajaCode": p.get("uploadBulsajaCode") or "",
                        "group_name": self.group_name,
                    })
            
            self.log.emit(f"  채널상품번호 있는 상품: {len(products_to_check)}개")
            
            if not products_to_check:
                self.finished_signal.emit(False, "채널상품번호가 있는 상품이 없습니다.", None)
                return
            
            # 3. 병렬로 상품 확인
            total = len(products_to_check)
            checked = 0
            fixed_products = []  # 수정된 상품
            exists_products = []  # 존재하는 상품
            error_products = []  # 에러 상품
            
            # 배치 처리 (연결 오류 대응)
            remaining = list(products_to_check)
            
            while self.is_running and remaining:
                batch_size = min(100, len(remaining))
                batch = remaining[:batch_size]
                remaining = remaining[batch_size:]
                
                self.log.emit(f"\n  배치 처리: {len(batch)}개 (남은: {len(remaining)}개)")
                
                has_error = False
                
                with ThreadPoolExecutor(max_workers=self.PARALLEL_COUNT) as executor:
                    futures = {executor.submit(self.check_single_product, p): p for p in batch}
                    
                    for future in as_completed(futures):
                        if not self.is_running:
                            self.finished_signal.emit(False, "사용자 중지", None)
                            return
                        
                        result = future.result()
                        if result is None:
                            continue
                        
                        checked += 1
                        self.progress.emit(checked, total)
                        
                        if "error" in result:
                            error_msg = result["error"]
                            if is_connection_error(error_msg):
                                self.log.emit(f"  ⚠️ 연결 오류! 재시도 예정...")
                                has_error = True
                                # 남은 상품 + 현재 배치의 미처리 상품 다시 시도
                                remaining = batch[batch.index(futures[future]):] + remaining
                                for f in futures:
                                    f.cancel()
                                break
                            else:
                                error_products.append(result)
                                self.log.emit(f"  ❌ 오류: {result['product']['productName'][:30]}... ({error_msg[:50]})")
                        elif result["fixed"]:
                            fixed_products.append(result)
                            self.product_checked.emit(result)
                            self.log.emit(f"  🔧 수정됨: {result['product']['productName'][:40]}...")
                        elif result["exists"]:
                            exists_products.append(result)
                        else:
                            # 알 수 없는 응답
                            error_products.append(result)
                
                if has_error:
                    self.log.emit(f"  🔄 세션 리셋 중...")
                    self.api.reset_session()
                    time.sleep(2)
                    continue
                
                # 배치 간 딜레이
                if remaining:
                    time.sleep(0.5)
            
            # 4. 결과 요약
            self.log.emit(f"\n{'='*60}")
            self.log.emit(f"📊 동기화 결과")
            self.log.emit(f"{'='*60}")
            self.log.emit(f"  • 전체 확인: {checked}개")
            self.log.emit(f"  • 정상 (마켓에 존재): {len(exists_products)}개")
            self.log.emit(f"  • 🔧 수정됨 (미업로드로 변경): {len(fixed_products)}개")
            self.log.emit(f"  • 오류: {len(error_products)}개")
            
            result = {
                "fixed": fixed_products,
                "exists": exists_products,
                "errors": error_products,
                "total_checked": checked,
            }
            
            self.finished_signal.emit(True, f"완료: {len(fixed_products)}개 수정됨", result)
            
        except Exception as e:
            self.log.emit(f"\n❌ 오류: {e}")
            self.finished_signal.emit(False, str(e), None)


class MultiGroupSyncWorker(QThread):
    """다중 그룹 동기화 작업 스레드"""
    progress = pyqtSignal(int, int)  # current, total
    group_progress = pyqtSignal(int, int, str)  # group_current, group_total, group_name
    log = pyqtSignal(str)
    product_checked = pyqtSignal(dict)
    finished_signal = pyqtSignal(bool, str, object)

    PARALLEL_COUNT = 2  # 동시 요청 수 (500 오류 방지를 위해 줄임)
    
    def __init__(self, api, groups):
        """
        groups: [(group_name, group_id), ...]
        """
        super().__init__()
        self.api = api
        self.groups = groups
        self.is_running = True
    
    def stop(self):
        self.is_running = False
    
    def check_single_product(self, product_info):
        """단일 상품 체크"""
        try:
            channel_no = product_info.get("channel_product_no")
            group_id = product_info.get("group_id")
            if not channel_no or not group_id:
                return None

            result = self.api.check_smartstore_product(group_id, channel_no)

            # 상품이 없으면 fixed=true, 있으면 message="OK"
            is_fixed = result.get("fixed", False)
            is_exists = result.get("message") == "OK" or ("data" in result and result.get("data"))

            return {
                "product": product_info,
                "result": result,
                "fixed": is_fixed,
                "reason": result.get("reason", ""),
                "exists": is_exists and not is_fixed,
            }
        except Exception as e:
            return {
                "product": product_info,
                "error": str(e),
                "fixed": False,
                "exists": None,
            }
    
    def run(self):
        try:
            total_groups = len(self.groups)
            self.log.emit(f"\n{'='*60}")
            self.log.emit(f"🌐 다중 그룹 스마트스토어 동기화 시작")
            self.log.emit(f"   대상 그룹: {total_groups}개")
            self.log.emit(f"{'='*60}")
            
            all_fixed = []
            all_exists = []
            all_errors = []
            total_checked = 0
            
            for group_idx, (group_name, group_id) in enumerate(self.groups):
                if not self.is_running:
                    break
                
                self.log.emit(f"\n{'─'*60}")
                self.log.emit(f"📁 [{group_idx + 1}/{total_groups}] {group_name} 처리 중...")
                self.log.emit(f"{'─'*60}")
                self.group_progress.emit(group_idx + 1, total_groups, group_name)
                
                # 1. 업로드됨 상품 조회
                self.log.emit(f"  📦 업로드됨 상품 조회...")
                try:
                    products = self.api.get_all_products(
                        group_name,
                        market_type_filter="uploaded",
                        log_callback=lambda msg: self.log.emit(msg),
                        stop_check=lambda: not self.is_running
                    )
                except Exception as e:
                    self.log.emit(f"  ❌ 조회 실패: {e}")
                    continue
                
                if not self.is_running:
                    break
                
                self.log.emit(f"  ✅ 업로드됨 상품: {len(products)}개")
                
                if not products:
                    self.log.emit(f"  ⏭️ 업로드됨 상품 없음, 다음 그룹으로...")
                    continue
                
                # 2. 채널상품번호 추출
                products_to_check = []
                for p in products:
                    # 채널상품번호는 uploadedSuccessUrl.smartstore에 있음
                    uploaded_success_url = p.get("uploadedSuccessUrl") or {}
                    channel_no = uploaded_success_url.get("smartstore") or ""

                    if channel_no:
                        products_to_check.append({
                            "sourcingId": p.get("sourcingId") or p.get("ID"),
                            "productName": p.get("uploadCommonProductName") or p.get("productName") or "",
                            "channel_product_no": str(channel_no),
                            "bulsajaCode": p.get("uploadBulsajaCode") or "",
                            "group_name": group_name,
                            "group_id": group_id,
                        })
                
                self.log.emit(f"  🔍 채널상품번호 있는 상품: {len(products_to_check)}개")
                
                if not products_to_check:
                    self.log.emit(f"  ⏭️ 채널상품번호 없음, 다음 그룹으로...")
                    continue
                
                # 3. 병렬로 상품 확인
                total = len(products_to_check)
                checked = 0
                fixed_products = []
                exists_products = []
                error_products = []
                
                remaining = list(products_to_check)
                
                while self.is_running and remaining:
                    batch_size = min(100, len(remaining))
                    batch = remaining[:batch_size]
                    remaining = remaining[batch_size:]
                    
                    has_error = False
                    
                    with ThreadPoolExecutor(max_workers=self.PARALLEL_COUNT) as executor:
                        futures = {executor.submit(self.check_single_product, p): p for p in batch}
                        
                        for future in as_completed(futures):
                            if not self.is_running:
                                break
                            
                            result = future.result()
                            if result is None:
                                continue
                            
                            checked += 1
                            total_checked += 1
                            self.progress.emit(checked, total)
                            
                            if "error" in result:
                                error_msg = result["error"]
                                if is_connection_error(error_msg):
                                    self.log.emit(f"  ⚠️ 연결 오류! 재시도...")
                                    has_error = True
                                    remaining = batch[batch.index(futures[future]):] + remaining
                                    for f in futures:
                                        f.cancel()
                                    break
                                else:
                                    error_products.append(result)
                                    self.log.emit(f"  ❌ 오류: {result['product']['productName'][:30]}... ({error_msg[:50]})")
                            elif result["fixed"]:
                                fixed_products.append(result)
                                self.product_checked.emit(result)
                                self.log.emit(f"  🔧 수정됨: {result['product']['productName'][:35]}...")
                            elif result["exists"]:
                                exists_products.append(result)
                            else:
                                error_products.append(result)
                    
                    if has_error:
                        self.log.emit(f"  🔄 세션 리셋...")
                        self.api.reset_session()
                        time.sleep(2)
                        continue
                    
                    if remaining:
                        time.sleep(0.3)
                
                # 그룹 결과 요약
                self.log.emit(f"\n  📊 {group_name} 결과: 정상 {len(exists_products)}개, 수정 {len(fixed_products)}개, 오류 {len(error_products)}개")
                
                all_fixed.extend(fixed_products)
                all_exists.extend(exists_products)
                all_errors.extend(error_products)
                
                # 그룹 간 딜레이
                if group_idx < total_groups - 1:
                    time.sleep(1)
            
            # 전체 결과 요약
            self.log.emit(f"\n{'='*60}")
            self.log.emit(f"🏁 전체 동기화 완료!")
            self.log.emit(f"{'='*60}")
            self.log.emit(f"  • 처리 그룹: {total_groups}개")
            self.log.emit(f"  • 전체 확인: {total_checked}개")
            self.log.emit(f"  • 정상 (마켓에 존재): {len(all_exists)}개")
            self.log.emit(f"  • 🔧 수정됨 (미업로드로 변경): {len(all_fixed)}개")
            self.log.emit(f"  • 오류: {len(all_errors)}개")
            
            result = {
                "fixed": all_fixed,
                "exists": all_exists,
                "errors": all_errors,
                "total_checked": total_checked,
                "total_groups": total_groups,
            }
            
            self.finished_signal.emit(True, f"완료: {len(all_fixed)}개 수정됨 ({total_groups}개 그룹)", result)
            
        except Exception as e:
            self.log.emit(f"\n❌ 오류: {e}")
            self.finished_signal.emit(False, str(e), None)


class ResultDialog(QDialog):
    """결과 팝업"""
    
    def __init__(self, fixed_products, title, parent=None):
        super().__init__(parent)
        self.fixed_products = fixed_products
        self.title = title
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle(f"{self.title} ({len(self.fixed_products)}개)")
        self.setMinimumSize(1000, 500)
        
        layout = QVBoxLayout(self)
        
        # 요약
        summary = QLabel(f"🔧 총 {len(self.fixed_products)}개 상품이 미업로드+수정중 상태로 변경되었습니다.")
        summary.setStyleSheet("font-size: 13px; font-weight: bold; color: #E65100; margin: 10px;")
        layout.addWidget(summary)
        
        # 테이블
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["그룹", "상품명", "채널상품번호", "불사자코드"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setRowCount(len(self.fixed_products))
        
        for i, item in enumerate(self.fixed_products):
            p = item.get("product", {})
            self.table.setItem(i, 0, QTableWidgetItem(p.get("group_name", "")))
            self.table.setItem(i, 1, QTableWidgetItem(p.get("productName", "")))
            self.table.setItem(i, 2, QTableWidgetItem(p.get("channel_product_no", "")))
            self.table.setItem(i, 3, QTableWidgetItem(p.get("bulsajaCode", "")))
        
        layout.addWidget(self.table)
        
        # 버튼
        btn_layout = QHBoxLayout()
        
        copy_btn = QPushButton("📋 상품명 복사")
        copy_btn.clicked.connect(self.copy_names)
        btn_layout.addWidget(copy_btn)
        
        save_btn = QPushButton("💾 CSV 저장")
        save_btn.clicked.connect(self.save_csv)
        btn_layout.addWidget(save_btn)
        
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
    
    def copy_names(self):
        names = [item.get("product", {}).get("productName", "") for item in self.fixed_products]
        QApplication.clipboard().setText("\n".join(names))
        QMessageBox.information(self, "복사 완료", f"{len(names)}개 복사됨")
    
    def save_csv(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "CSV 저장",
            f"fixed_products_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV Files (*.csv)"
        )
        if filename:
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(["그룹", "상품명", "채널상품번호", "불사자코드"])
                for item in self.fixed_products:
                    p = item.get("product", {})
                    writer.writerow([
                        p.get("group_name", ""),
                        p.get("productName", ""),
                        p.get("channel_product_no", ""),
                        p.get("bulsajaCode", "")
                    ])
            QMessageBox.information(self, "저장 완료", f"저장됨: {filename}")


class MainWindow(QMainWindow):
    """메인 윈도우"""
    
    def __init__(self):
        super().__init__()
        self.api = None
        self.sync_worker = None
        self.selected_group = None
        self.selected_groups = None  # 전체 그룹 선택용
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("불사자 스마트스토어 동기화 프로그램 v1.0")
        self.setMinimumSize(900, 750)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # === 토큰 설정 ===
        token_group = QGroupBox("🔑 토큰 설정")
        token_layout = QVBoxLayout(token_group)
        
        h0 = QHBoxLayout()
        h0.addWidget(QLabel("Chrome 포트:"))
        self.port_input = QSpinBox()
        self.port_input.setRange(1000, 65535)
        self.port_input.setValue(9222)
        h0.addWidget(self.port_input)
        
        self.chrome_btn = QPushButton("🌐 Chrome 실행")
        self.chrome_btn.clicked.connect(self.launch_chrome)
        self.chrome_btn.setStyleSheet("background-color: #607D8B; color: white;")
        h0.addWidget(self.chrome_btn)
        
        self.extract_btn = QPushButton("🔄 토큰 추출")
        self.extract_btn.clicked.connect(self.extract_token)
        self.extract_btn.setStyleSheet("background-color: #2196F3; color: white;")
        h0.addWidget(self.extract_btn)
        
        self.connect_btn = QPushButton("🔗 연결 테스트")
        self.connect_btn.clicked.connect(self.test_connection)
        h0.addWidget(self.connect_btn)
        
        token_layout.addLayout(h0)
        
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("Access:"))
        self.access_input = QLineEdit()
        self.access_input.setPlaceholderText("토큰 추출 또는 수동 입력")
        h1.addWidget(self.access_input)
        h1.addWidget(QLabel("Refresh:"))
        self.refresh_input = QLineEdit()
        h1.addWidget(self.refresh_input)
        token_layout.addLayout(h1)
        
        layout.addWidget(token_group)
        
        # === 그룹 선택 ===
        group_box = QGroupBox("📁 그룹 선택")
        group_layout = QVBoxLayout(group_box)

        # 세트별 콤보박스
        combo_row = QHBoxLayout()
        for set_name in ["플로", "흑곰", "검은곰"]:
            combo = QComboBox()
            combo.addItem(f"▼ {set_name}")
            combo.addItems(SET_GROUPS[set_name])
            combo.setFixedWidth(140)
            combo.currentIndexChanged.connect(
                lambda idx, c=combo, s=set_name: self.on_group_selected(idx, c, s)
            )
            combo_row.addWidget(combo)
            setattr(self, f"combo_{set_name}", combo)

        self.selected_group_label = QLabel("선택: 없음")
        self.selected_group_label.setStyleSheet("font-weight: bold; color: #1976D2;")
        combo_row.addWidget(self.selected_group_label)
        combo_row.addStretch()
        group_layout.addLayout(combo_row)

        # 시작 번호 설정
        start_row = QHBoxLayout()
        start_row.addWidget(QLabel("시작 번호:"))
        self.start_index_spin = QSpinBox()
        self.start_index_spin.setRange(1, 60)
        self.start_index_spin.setValue(1)
        self.start_index_spin.setToolTip("전체 선택 시 이 번호부터 시작합니다")
        self.start_index_spin.setFixedWidth(60)
        start_row.addWidget(self.start_index_spin)
        start_row.addWidget(QLabel("번째 그룹부터"))
        start_row.addStretch()
        group_layout.addLayout(start_row)

        # 전체 선택 버튼
        all_select_row = QHBoxLayout()

        self.select_all_plo_btn = QPushButton("플로 전체 (20개)")
        self.select_all_plo_btn.clicked.connect(lambda: self.select_all_groups("플로"))
        self.select_all_plo_btn.setStyleSheet("background-color: #E3F2FD;")
        all_select_row.addWidget(self.select_all_plo_btn)

        self.select_all_hukgom_btn = QPushButton("흑곰 전체 (20개)")
        self.select_all_hukgom_btn.clicked.connect(lambda: self.select_all_groups("흑곰"))
        self.select_all_hukgom_btn.setStyleSheet("background-color: #FFF3E0;")
        all_select_row.addWidget(self.select_all_hukgom_btn)

        self.select_all_blackgom_btn = QPushButton("검은곰 전체 (20개)")
        self.select_all_blackgom_btn.clicked.connect(lambda: self.select_all_groups("검은곰"))
        self.select_all_blackgom_btn.setStyleSheet("background-color: #F3E5F5;")
        all_select_row.addWidget(self.select_all_blackgom_btn)

        self.select_all_btn = QPushButton("🌐 전체 그룹 (60개)")
        self.select_all_btn.clicked.connect(lambda: self.select_all_groups("전체"))
        self.select_all_btn.setStyleSheet("background-color: #E8F5E9; font-weight: bold;")
        all_select_row.addWidget(self.select_all_btn)

        all_select_row.addStretch()
        group_layout.addLayout(all_select_row)

        layout.addWidget(group_box)
        
        # === 실행 ===
        action_box = QGroupBox("🚀 실행")
        action_layout = QVBoxLayout(action_box)
        
        info_label = QLabel(
            "📌 '업로드됨' 상품 중 실제 스마트스토어에 없는 상품을 찾아\n"
            "   자동으로 '미업로드 + 수정중' 상태로 변경합니다."
        )
        info_label.setStyleSheet("color: #666; margin: 5px;")
        action_layout.addWidget(info_label)
        
        self.sync_btn = QPushButton("🔄 스마트스토어 동기화 시작")
        self.sync_btn.setFixedHeight(45)
        self.sync_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #66BB6A, stop:1 #43A047);
                color: white; 
                font-weight: bold; 
                font-size: 13px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #81C784, stop:1 #66BB6A);
            }
        """)
        self.sync_btn.clicked.connect(self.start_sync)
        action_layout.addWidget(self.sync_btn)
        
        layout.addWidget(action_box)
        
        # === 진행 상황 ===
        progress_box = QGroupBox("📊 진행 상황")
        progress_layout = QVBoxLayout(progress_box)
        
        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("대기 중...")
        self.status_label.setStyleSheet("font-size: 12px;")
        progress_layout.addWidget(self.status_label)
        
        layout.addWidget(progress_box)
        
        # === 로그 ===
        log_box = QGroupBox("📋 로그")
        log_layout = QVBoxLayout(log_box)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_box)
        
        # 중지 버튼
        self.stop_btn = QPushButton("⏹️ 중지")
        self.stop_btn.clicked.connect(self.stop_sync)
        self.stop_btn.setEnabled(False)
        layout.addWidget(self.stop_btn)
        
        # 프로그램 설명 출력
        self.show_welcome_message()
    
    def show_welcome_message(self):
        """프로그램 설명 출력"""
        welcome = """
╔══════════════════════════════════════════════════════════════════╗
║       🔄 불사자 스마트스토어 동기화 프로그램 v1.0                ║
╚══════════════════════════════════════════════════════════════════╝

📌 프로그램 목적:
   불사자에서 '업로드됨(판매중)'으로 표시되지만 
   실제 스마트스토어에는 없는 상품을 자동으로 찾아서
   '미업로드 + 수정중' 상태로 변경

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 사용 방법:

   1️⃣ 토큰 설정
      • Chrome Debug 실행 → 불사자 로그인 → 토큰 추출
      • 연결 테스트로 확인

   2️⃣ 그룹 선택
      • 연결 후 자동으로 그룹 목록 로드
      • 단일 그룹 선택 또는 범위 지정 가능

   3️⃣ 동기화 실행
      • 🔄 동기화 시작 버튼 클릭
      • 업로드됨 상품 조회 → 스마트스토어 확인 → 자동 수정

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚡ 동작 원리:
   • 불사자 내장 API 사용 (스마트스토어 배지 클릭과 동일)
   • 네이버 API 키 불필요!
   • 상품이 없으면 자동으로 미업로드 + 수정중으로 변경

⚠️ 주의사항:
   • 서버 부하 방지를 위해 동시 요청 2개로 제한
   • 상품이 많으면 시간이 걸릴 수 있음

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        self.log_text.append(welcome)
    
    def launch_chrome(self):
        """Chrome Debug 실행"""
        import subprocess
        import os
        
        port = self.port_input.value()
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
            self.log_text.append(f"🌐 Chrome Debug 실행 (포트: {port})")
        except Exception as e:
            QMessageBox.warning(self, "오류", f"Chrome 실행 실패: {e}")
    
    def extract_token(self):
        """토큰 추출"""
        port = self.port_input.value()
        self.log_text.append(f"🔄 토큰 추출 중...")
        
        tokens, error = BulsajaAPI.extract_token_from_browser(port)
        
        if tokens:
            self.access_input.setText(tokens["access"])
            self.refresh_input.setText(tokens["refresh"])
            self.log_text.append("✅ 토큰 추출 성공!")
            self.test_connection()
        else:
            self.log_text.append(f"❌ {error}")
            QMessageBox.warning(self, "실패", error)
    
    def test_connection(self):
        """연결 테스트 및 그룹 로드"""
        global GROUPS
        access = self.access_input.text().strip()
        refresh = self.refresh_input.text().strip()

        if not access or not refresh:
            QMessageBox.warning(self, "경고", "토큰을 입력해주세요.")
            return

        try:
            self.api = BulsajaAPI(access, refresh)
            groups_dict, group_names = self.api.get_groups()

            # 전역 변수에 저장 (API에서 로드)
            GROUPS = groups_dict

            self.log_text.append(f"✅ 연결 성공! 그룹 {len(groups_dict)}개 로드됨")
            QMessageBox.information(self, "성공", f"연결 성공!\n그룹 {len(groups_dict)}개 로드됨")
        except Exception as e:
            self.log_text.append(f"❌ 연결 실패: {e}")
            QMessageBox.critical(self, "오류", f"연결 실패:\n{e}")

    def on_group_selected(self, index, combo, set_name):
        """그룹 선택"""
        if index == 0:
            return

        # 다른 콤보박스 초기화
        for name in ["플로", "흑곰", "검은곰"]:
            c = getattr(self, f"combo_{name}")
            if c != combo:
                c.blockSignals(True)
                c.setCurrentIndex(0)
                c.blockSignals(False)

        self.selected_group = combo.currentText()
        self.selected_groups = None  # 단일 그룹 선택 시 전체 선택 해제
        self.selected_group_label.setText(f"선택: {self.selected_group}")

    def select_all_groups(self, set_name):
        """전체 그룹 선택"""
        # 콤보박스 초기화
        for name in ["플로", "흑곰", "검은곰"]:
            c = getattr(self, f"combo_{name}")
            c.blockSignals(True)
            c.setCurrentIndex(0)
            c.blockSignals(False)

        start_idx = self.start_index_spin.value() - 1  # 0-based index

        if set_name == "전체":
            # 50번_수집 제외
            all_groups = [g for g in GROUPS.keys() if g != "50번_수집"]
            self.selected_groups = sorted(all_groups)[start_idx:]
            if start_idx > 0:
                self.selected_group_label.setText(f"선택: 전체 {start_idx + 1}번~끝 ({len(self.selected_groups)}개 그룹)")
            else:
                self.selected_group_label.setText(f"선택: 전체 ({len(self.selected_groups)}개 그룹)")
        else:
            all_groups = SET_GROUPS.get(set_name, [])
            self.selected_groups = all_groups[start_idx:]
            if start_idx > 0:
                self.selected_group_label.setText(f"선택: {set_name} {start_idx + 1}번~끝 ({len(self.selected_groups)}개 그룹)")
            else:
                self.selected_group_label.setText(f"선택: {set_name} 전체 ({len(self.selected_groups)}개 그룹)")

        self.selected_group = None  # 단일 선택 해제
    
    def start_sync(self):
        """동기화 시작"""
        if not self.api:
            QMessageBox.warning(self, "경고", "먼저 연결 테스트를 해주세요.")
            return
        
        # 단일 그룹 또는 다중 그룹 확인
        if self.selected_groups:
            # 다중 그룹
            groups = []
            for group_name in self.selected_groups:
                group_id = GROUPS.get(group_name)
                if group_id:
                    groups.append((group_name, group_id))
            
            if not groups:
                QMessageBox.warning(self, "경고", "유효한 그룹이 없습니다.")
                return
            
            reply = QMessageBox.question(
                self, "동기화 시작",
                f"{len(groups)}개 그룹의 스마트스토어 동기화를 시작하시겠습니까?\n\n"
                "• 각 그룹의 업로드됨 상품을 순차적으로 확인합니다.\n"
                "• 스마트스토어에 없는 상품은 자동으로 미업로드+수정중으로 변경됩니다.\n\n"
                f"대상 그룹 수: {len(groups)}개",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
            
            self.sync_worker = MultiGroupSyncWorker(self.api, groups)
            self.sync_worker.group_progress.connect(self.update_group_progress)
            
        elif self.selected_group:
            # 단일 그룹
            group_id = GROUPS.get(self.selected_group)
            if not group_id:
                QMessageBox.warning(self, "경고", "그룹 ID를 찾을 수 없습니다.")
                return
            
            reply = QMessageBox.question(
                self, "동기화 시작",
                f"'{self.selected_group}' 그룹의 스마트스토어 동기화를 시작하시겠습니까?\n\n"
                "• 업로드됨 상품 중 스마트스토어에 없는 상품을 찾습니다.\n"
                "• 없는 상품은 자동으로 미업로드+수정중으로 변경됩니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
            
            self.sync_worker = SyncWorker(self.api, self.selected_group, group_id)
        else:
            QMessageBox.warning(self, "경고", "그룹을 선택해주세요.")
            return
        
        self.sync_worker.progress.connect(self.update_progress)
        self.sync_worker.log.connect(self.append_log)
        self.sync_worker.finished_signal.connect(self.on_sync_finished)
        
        self.sync_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("동기화 진행 중...")
        
        self.sync_worker.start()
    
    def update_group_progress(self, current, total, group_name):
        """그룹 진행 상황 업데이트"""
        self.status_label.setText(f"그룹 {current}/{total}: {group_name}")
    
    def stop_sync(self):
        """동기화 중지"""
        if self.sync_worker:
            self.sync_worker.stop()
            self.log_text.append("⏹️ 중지 요청됨...")
    
    def update_progress(self, current, total):
        """진행률 업데이트"""
        if total > 0:
            percent = int(current / total * 100)
            self.progress_bar.setValue(percent)
            self.status_label.setText(f"진행 중... {current}/{total} ({percent}%)")
    
    def append_log(self, message):
        """로그 추가"""
        self.log_text.append(message)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
    
    def on_sync_finished(self, success, message, result):
        """동기화 완료"""
        self.sync_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("완료")
        
        if not success:
            QMessageBox.warning(self, "알림", message)
            return
        
        if result and result.get("fixed"):
            # 수정된 상품 목록 팝업
            dialog = ResultDialog(result["fixed"], "🔧 수정된 상품 목록", self)
            dialog.exec()
        
        QMessageBox.information(self, "완료", message)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
