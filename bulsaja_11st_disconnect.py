#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
불사자 11번가 마켓 끊기 프로그램 v1.1
- 플로/흑곰/검은곰 그룹용
- 미리보기 후 진행 (제외 상품 확인)
- 병렬 처리 10개 동시 실행
- 연결 오류 시 세션 리셋 및 재시도
"""

import sys
import json
import requests
import websocket
import time
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QSpinBox, QCheckBox, QGroupBox,
    QTextEdit, QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QMessageBox, QFileDialog, QDialog, QRadioButton, QButtonGroup,
    QTabWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
import csv

# 그룹 매핑 데이터 (API에서 동적으로 로드)
GROUPS = {}  # {group_name: group_id}
ALL_GROUP_NAMES = []  # 전체 그룹명 리스트 (순서 유지)


def normalize_name(name):
    """상품명 정규화 (공백 정리, strip)"""
    if not name:
        return ""
    return re.sub(r'\s+', ' ', name.strip())


def is_connection_error(error_msg):
    """연결 오류인지 확인"""
    error_lower = error_msg.lower()
    connection_errors = [
        "timed out", "timeout", "connection aborted", "remotedisconnected",
        "connectionerror", "connection reset", "broken pipe", "connection refused",
        "remote end closed", "read timed out",
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

    def delete_market_products(self, sourcing_ids, market_type="ST11", delete_type=3):
        """
        마켓 상품 끊기 API
        - marketType: "ST11" (11번가)
        - deleteType: 3 (마켓 연결 해제)
        - deleteAnalytics: false
        """
        url = f"{self.BASE_URL}/api/market/delete/market-products"

        payload = {
            "data": {
                "sourcingIds": sourcing_ids,
                "marketType": market_type,
                "deleteType": delete_type,
                "deleteAnalytics": False
            }
        }

        response = self.session.post(url, json=payload, timeout=60)

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


class PreviewWorker(QThread):
    """미리보기 작업 스레드 - 상품 조회 및 제외 대상 매칭"""
    progress = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str, object)  # success, message, data

    def __init__(self, api, target_group, exclude_names, disconnect_count, is_all):
        super().__init__()
        self.api = api
        self.target_group = target_group
        self.exclude_names = exclude_names
        self.disconnect_count = disconnect_count
        self.is_all = is_all
        self.is_running = True

    def stop(self):
        self.is_running = False

    def run(self):
        try:
            self.progress.emit("📋 상품 조회 중... (업로드됨만)")

            # 상품 조회
            products = self.api.get_all_products(
                self.target_group,
                market_type_filter="uploaded",
                log_callback=lambda msg: self.progress.emit(msg),
                stop_check=lambda: not self.is_running
            )

            if not self.is_running:
                self.finished_signal.emit(False, "사용자 중지", None)
                return

            self.progress.emit(f"총 {len(products)}개 상품 조회됨")

            # 11번가 상품만 필터링 (uploadedSuccessUrl.st11 값이 있는 것)
            st11_products = []
            for p in products:
                uploaded_url = p.get("uploadedSuccessUrl") or {}
                if uploaded_url.get("st11"):
                    sourcing_id = p.get("sourcingId") or p.get("ID")
                    product_name = p.get("uploadCommonProductName") or p.get("productName") or ""
                    if sourcing_id:
                        st11_products.append({
                            "sourcingId": sourcing_id,
                            "productName": product_name,
                            "st11_product_no": uploaded_url.get("st11"),
                        })

            self.progress.emit(f"11번가 상품: {len(st11_products)}개")

            # 제외 목록 정규화
            exclude_set = set()
            for name in self.exclude_names:
                normalized = normalize_name(name)
                if normalized:
                    exclude_set.add(normalized)

            self.progress.emit(f"제외 목록: {len(exclude_set)}개 (정규화 후)")

            # 상품 분류
            matched_products = []  # 제외될 상품 (매칭됨)
            disconnect_products = []  # 연결 끊을 상품

            for p in st11_products:
                product_name = p.get("productName", "")
                normalized_name = normalize_name(product_name)
                sourcing_id = p.get("sourcingId")

                if normalized_name in exclude_set:
                    matched_products.append({
                        "name": product_name,
                        "id": sourcing_id
                    })
                else:
                    disconnect_products.append({
                        "name": product_name,
                        "id": sourcing_id
                    })

            # 수량 제한 적용
            if not self.is_all:
                disconnect_products = disconnect_products[:self.disconnect_count]

            self.progress.emit(f"매칭된 제외 상품: {len(matched_products)}개")
            self.progress.emit(f"연결 끊을 상품: {len(disconnect_products)}개")

            result = {
                "matched": matched_products,
                "disconnect": disconnect_products,
                "total_products": len(st11_products)
            }

            self.finished_signal.emit(True, "조회 완료", result)

        except Exception as e:
            self.finished_signal.emit(False, str(e), None)


class PreviewDialog(QDialog):
    """미리보기 팝업 - 제외될 상품과 연결 끊을 상품 확인"""

    def __init__(self, matched_products, disconnect_products, total_products, parent=None):
        super().__init__(parent)
        self.matched_products = matched_products
        self.disconnect_products = disconnect_products
        self.total_products = total_products
        self.result_action = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("🔍 11번가 마켓 끊기 미리보기")
        self.setMinimumSize(900, 600)

        layout = QVBoxLayout(self)

        # 요약 정보
        summary_group = QGroupBox("📊 요약")
        summary_layout = QVBoxLayout(summary_group)

        summary_text = f"""
        • 11번가 상품: {self.total_products:,}개
        • 🚫 제외될 상품 (매칭됨): {len(self.matched_products):,}개
        • ✅ 연결 끊을 상품: {len(self.disconnect_products):,}개
        """
        summary_label = QLabel(summary_text)
        summary_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        summary_layout.addWidget(summary_label)
        layout.addWidget(summary_group)

        # 탭 위젯
        tabs = QTabWidget()

        # 탭1: 제외될 상품 (매칭됨)
        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)

        matched_label = QLabel(f"🚫 제외될 상품 ({len(self.matched_products)}개) - 이 상품들은 마켓 연결 끊기에서 제외됩니다")
        matched_label.setStyleSheet("color: #D32F2F; font-weight: bold;")
        tab1_layout.addWidget(matched_label)

        self.matched_text = QTextEdit()
        self.matched_text.setReadOnly(True)
        self.matched_text.setFont(QFont("Consolas", 9))

        if self.matched_products:
            lines = []
            for i, p in enumerate(self.matched_products, 1):
                name = p["name"][:80] + "..." if len(p["name"]) > 80 else p["name"]
                lines.append(f"{i}. {name}")
            self.matched_text.setPlainText("\n".join(lines))
        else:
            self.matched_text.setPlainText("(매칭된 상품 없음 - 제외 목록과 일치하는 상품이 없습니다)")

        tab1_layout.addWidget(self.matched_text)

        # 복사 버튼
        copy_matched_btn = QPushButton("📋 제외 상품명 복사")
        copy_matched_btn.clicked.connect(self.copy_matched)
        tab1_layout.addWidget(copy_matched_btn)

        tabs.addTab(tab1, f"🚫 제외될 상품 ({len(self.matched_products)})")

        # 탭2: 연결 끊을 상품
        tab2 = QWidget()
        tab2_layout = QVBoxLayout(tab2)

        disconnect_label = QLabel(f"✅ 연결 끊을 상품 ({len(self.disconnect_products)}개) - 이 상품들의 11번가 연결이 끊어집니다")
        disconnect_label.setStyleSheet("color: #1976D2; font-weight: bold;")
        tab2_layout.addWidget(disconnect_label)

        self.disconnect_text = QTextEdit()
        self.disconnect_text.setReadOnly(True)
        self.disconnect_text.setFont(QFont("Consolas", 9))

        if self.disconnect_products:
            lines = []
            show_count = min(500, len(self.disconnect_products))
            for i, p in enumerate(self.disconnect_products[:show_count], 1):
                name = p["name"][:80] + "..." if len(p["name"]) > 80 else p["name"]
                lines.append(f"{i}. {name}")
            if len(self.disconnect_products) > show_count:
                lines.append(f"\n... 외 {len(self.disconnect_products) - show_count}개 더")
            self.disconnect_text.setPlainText("\n".join(lines))
        else:
            self.disconnect_text.setPlainText("(연결 끊을 상품 없음)")

        tab2_layout.addWidget(self.disconnect_text)

        tabs.addTab(tab2, f"✅ 연결 끊을 상품 ({len(self.disconnect_products)})")

        layout.addWidget(tabs)

        # 버튼 영역
        btn_layout = QHBoxLayout()

        # 진행 버튼
        proceed_btn = QPushButton(f"🔌 11번가 끊기 진행 ({len(self.disconnect_products)}개)")
        proceed_btn.setStyleSheet("""
            QPushButton {
                background-color: #D32F2F;
                color: white;
                font-weight: bold;
                padding: 12px 24px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #B71C1C;
            }
        """)
        proceed_btn.clicked.connect(self.on_proceed)
        proceed_btn.setEnabled(len(self.disconnect_products) > 0)
        btn_layout.addWidget(proceed_btn)

        # 취소 버튼
        cancel_btn = QPushButton("취소")
        cancel_btn.setStyleSheet("padding: 12px 24px;")
        cancel_btn.clicked.connect(self.on_cancel)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def copy_matched(self):
        """제외 상품명 복사"""
        if self.matched_products:
            names = [p["name"] for p in self.matched_products]
            QApplication.clipboard().setText("\n".join(names))
            QMessageBox.information(self, "복사 완료", f"{len(names)}개 상품명이 복사되었습니다.")

    def on_proceed(self):
        """진행"""
        self.result_action = "proceed"
        self.accept()

    def on_cancel(self):
        """취소"""
        self.result_action = "cancel"
        self.reject()


class DisconnectWorker(QThread):
    """마켓 끊기 작업 스레드 (병렬 처리)"""
    progress = pyqtSignal(int, int)
    log = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str, object)

    PARALLEL_COUNT = 10  # 병렬 처리 수
    BATCH_SIZE = 50  # 한 번에 끊기 요청할 상품 수

    def __init__(self, api, sourcing_ids, market_type="ST11"):
        super().__init__()
        self.api = api
        self.sourcing_ids = sourcing_ids
        self.market_type = market_type
        self.is_running = True
        self.total_disconnected = 0
        self.all_results = []

    def stop(self):
        self.is_running = False

    def disconnect_batch(self, batch_info):
        """단일 배치 처리 (병렬 실행용)"""
        batch_num, batch = batch_info
        try:
            result = self.api.delete_market_products(
                sourcing_ids=batch,
                market_type=self.market_type,
                delete_type=3
            )
            return (batch_num, batch, result, None)
        except Exception as e:
            return (batch_num, batch, None, str(e))

    def run(self):
        try:
            total_count = len(self.sourcing_ids)
            market_name = "11번가"

            self.log.emit(f"\n{'='*60}")
            self.log.emit(f"🔌 {market_name} 마켓 끊기 시작")
            self.log.emit(f"   대상 상품: {total_count}개")
            self.log.emit(f"   배치 사이즈: {self.BATCH_SIZE}개")
            self.log.emit(f"   🚀 병렬 처리: {self.PARALLEL_COUNT}개 동시 실행")
            self.log.emit(f"{'='*60}")

            if total_count == 0:
                self.log.emit("처리할 상품이 없습니다.")
                self.finished_signal.emit(True, "처리할 상품 없음", {"results": []})
                return

            # 메인 루프 - 연결 오류 시 재시작
            remaining_ids = list(self.sourcing_ids)

            while self.is_running and remaining_ids:
                # 배치 목록 생성
                batches = []
                for i in range(0, len(remaining_ids), self.BATCH_SIZE):
                    batch = remaining_ids[i:i + self.BATCH_SIZE]
                    batch_num = i // self.BATCH_SIZE + 1
                    batches.append((batch_num, batch))

                total_batches = len(batches)
                self.log.emit(f"\n남은 상품: {len(remaining_ids)}개, 배치: {total_batches}개")

                # 병렬 처리
                completed_ids = set()
                has_error = False

                with ThreadPoolExecutor(max_workers=self.PARALLEL_COUNT) as executor:
                    futures = {executor.submit(self.disconnect_batch, batch_info): batch_info for batch_info in batches}

                    for future in as_completed(futures):
                        if not self.is_running:
                            self.finished_signal.emit(False, "사용자 중지", {"results": self.all_results})
                            return

                        batch_num, batch, result, error = future.result()

                        if error:
                            if is_connection_error(error):
                                self.log.emit(f"\n⚠️ 배치 {batch_num}: 연결 오류 발생!")
                                has_error = True
                                # 나머지 작업 취소
                                for f in futures:
                                    f.cancel()
                                break
                            else:
                                self.log.emit(f"  배치 {batch_num}: 오류 - {error}")
                        else:
                            # 결과 처리
                            results = result.get("results", [])
                            for r in results:
                                if r.get("code") == 0:
                                    self.total_disconnected += 1
                                    completed_ids.add(r.get("id"))
                                    self.all_results.append({
                                        "sourcingId": r.get("id"),
                                        "status": r.get("status"),
                                        "success": True
                                    })
                                else:
                                    completed_ids.add(r.get("id"))
                                    self.all_results.append({
                                        "sourcingId": r.get("id"),
                                        "status": r.get("status"),
                                        "success": False
                                    })

                            self.log.emit(f"  배치 {batch_num}/{total_batches}: 완료 (총 {self.total_disconnected}개)")
                            self.progress.emit(self.total_disconnected, total_count)

                # 연결 오류 발생 시 세션 리셋 후 재시작
                if has_error:
                    # 완료된 ID 제거
                    remaining_ids = [sid for sid in remaining_ids if sid not in completed_ids]
                    self.log.emit(f"\n🔄 세션 리셋 중... (남은 상품: {len(remaining_ids)}개)")
                    self.api.reset_session()
                    time.sleep(3)
                    self.log.emit(f"🔄 세션 리셋 완료! 재시작...")
                    continue

                # 정상 완료
                break

            # 전체 결과 요약
            self.log.emit(f"\n{'='*60}")
            self.log.emit(f"🏁 {market_name} 마켓 끊기 완료!")
            self.log.emit(f"{'='*60}")
            self.log.emit(f"  • 🔌 끊기 완료: {self.total_disconnected}개")

            result = {
                "total_disconnected": self.total_disconnected,
                "results": self.all_results,
            }

            self.finished_signal.emit(True, f"완료: {self.total_disconnected}개 끊기 완료", result)

        except Exception as e:
            self.log.emit(f"\n❌ 오류: {e}")
            self.finished_signal.emit(False, str(e), {"results": self.all_results})


class MultiGroupDisconnectWorker(QThread):
    """다중 그룹 마켓 끊기 작업 스레드"""
    progress = pyqtSignal(int, int)
    group_progress = pyqtSignal(int, int, str)
    log = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str, object)

    PARALLEL_COUNT = 10
    BATCH_SIZE = 50

    def __init__(self, api, groups, exclude_names, market_type="ST11"):
        super().__init__()
        self.api = api
        self.groups = groups  # [(group_name, group_id), ...]
        self.exclude_names = exclude_names
        self.market_type = market_type
        self.is_running = True

    def stop(self):
        self.is_running = False

    def disconnect_batch(self, batch_info):
        """단일 배치 처리"""
        batch_num, batch = batch_info
        try:
            result = self.api.delete_market_products(
                sourcing_ids=batch,
                market_type=self.market_type,
                delete_type=3
            )
            return (batch_num, batch, result, None)
        except Exception as e:
            return (batch_num, batch, None, str(e))

    def run(self):
        try:
            total_groups = len(self.groups)
            market_name = "11번가"

            self.log.emit(f"\n{'='*60}")
            self.log.emit(f"🔌 {market_name} 마켓 끊기 시작 (다중 그룹)")
            self.log.emit(f"   대상 그룹: {total_groups}개")
            self.log.emit(f"   🚀 병렬 처리: {self.PARALLEL_COUNT}개 동시 실행")
            self.log.emit(f"{'='*60}")

            # 제외 목록 정규화
            exclude_set = set()
            for name in self.exclude_names:
                normalized = normalize_name(name)
                if normalized:
                    exclude_set.add(normalized)

            if exclude_set:
                self.log.emit(f"제외 목록: {len(exclude_set)}개")

            total_disconnected = 0
            all_results = []

            for group_idx, (group_name, group_id) in enumerate(self.groups):
                if not self.is_running:
                    break

                self.log.emit(f"\n{'─'*60}")
                self.log.emit(f"📁 [{group_idx + 1}/{total_groups}] {group_name} 처리 중...")
                self.log.emit(f"{'─'*60}")
                self.group_progress.emit(group_idx + 1, total_groups, group_name)

                # 1. 업로드됨 상품 조회
                self.log.emit(f"  📦 {market_name} 업로드됨 상품 조회...")
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

                # 11번가 상품만 필터링
                st11_products = []
                for p in products:
                    uploaded_url = p.get("uploadedSuccessUrl") or {}
                    if uploaded_url.get("st11"):
                        sourcing_id = p.get("sourcingId") or p.get("ID")
                        product_name = p.get("uploadCommonProductName") or p.get("productName") or ""
                        if sourcing_id:
                            st11_products.append({
                                "sourcingId": sourcing_id,
                                "productName": product_name,
                            })

                self.log.emit(f"  ✅ {market_name} 상품: {len(st11_products)}개")

                if not st11_products:
                    self.log.emit(f"  ⏭️ {market_name} 상품 없음, 다음 그룹으로...")
                    continue

                # 제외 상품 필터링
                disconnect_ids = []
                excluded_count = 0
                for p in st11_products:
                    normalized_name = normalize_name(p["productName"])
                    if normalized_name in exclude_set:
                        excluded_count += 1
                    else:
                        disconnect_ids.append(p["sourcingId"])

                if excluded_count > 0:
                    self.log.emit(f"  🚫 제외됨: {excluded_count}개")

                self.log.emit(f"  🔌 끊기 대상: {len(disconnect_ids)}개")

                if not disconnect_ids:
                    continue

                # 배치 처리
                remaining_ids = list(disconnect_ids)
                group_disconnected = 0

                while self.is_running and remaining_ids:
                    batches = []
                    for i in range(0, len(remaining_ids), self.BATCH_SIZE):
                        batch = remaining_ids[i:i + self.BATCH_SIZE]
                        batch_num = i // self.BATCH_SIZE + 1
                        batches.append((batch_num, batch))

                    completed_ids = set()
                    has_error = False

                    with ThreadPoolExecutor(max_workers=self.PARALLEL_COUNT) as executor:
                        futures = {executor.submit(self.disconnect_batch, bi): bi for bi in batches}

                        for future in as_completed(futures):
                            if not self.is_running:
                                break

                            batch_num, batch, result, error = future.result()

                            if error:
                                if is_connection_error(error):
                                    self.log.emit(f"  ⚠️ 연결 오류! 재시도 예정...")
                                    has_error = True
                                    for f in futures:
                                        f.cancel()
                                    break
                                else:
                                    self.log.emit(f"  ❌ 배치 {batch_num}: {error}")
                            else:
                                results = result.get("results", [])
                                for r in results:
                                    completed_ids.add(r.get("id"))
                                    if r.get("code") == 0:
                                        group_disconnected += 1
                                        all_results.append({
                                            "group_name": group_name,
                                            "sourcingId": r.get("id"),
                                            "status": r.get("status"),
                                            "success": True
                                        })

                                self.progress.emit(group_disconnected, len(disconnect_ids))

                    if has_error:
                        remaining_ids = [sid for sid in remaining_ids if sid not in completed_ids]
                        self.log.emit(f"  🔄 세션 리셋...")
                        self.api.reset_session()
                        time.sleep(3)
                        continue

                    break

                self.log.emit(f"\n  📊 {group_name} 결과: 끊기 완료 {group_disconnected}개")
                total_disconnected += group_disconnected

                # 그룹 간 딜레이
                if group_idx < total_groups - 1:
                    time.sleep(1)

            # 전체 결과 요약
            self.log.emit(f"\n{'='*60}")
            self.log.emit(f"🏁 {market_name} 마켓 끊기 완료!")
            self.log.emit(f"{'='*60}")
            self.log.emit(f"  • 처리 그룹: {total_groups}개")
            self.log.emit(f"  • 🔌 끊기 완료: {total_disconnected}개")

            result = {
                "total_disconnected": total_disconnected,
                "total_groups": total_groups,
                "results": all_results,
            }

            self.finished_signal.emit(True, f"완료: {total_disconnected}개 끊기 완료 ({total_groups}개 그룹)", result)

        except Exception as e:
            self.log.emit(f"\n❌ 오류: {e}")
            self.finished_signal.emit(False, str(e), None)


class ResultDialog(QDialog):
    """결과 팝업"""

    def __init__(self, results, title, parent=None):
        super().__init__(parent)
        self.results = results
        self.title = title
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(f"{self.title}")
        self.setMinimumSize(800, 500)

        layout = QVBoxLayout(self)

        # 요약
        success_count = len([r for r in self.results if r.get("success")])
        error_count = len([r for r in self.results if not r.get("success")])

        summary = QLabel(f"🔌 총 {success_count}개 끊기 완료, {error_count}개 오류")
        summary.setStyleSheet("font-size: 13px; font-weight: bold; color: #1565C0; margin: 10px;")
        layout.addWidget(summary)

        # 테이블
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["그룹", "상품ID", "상태", "결과"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setRowCount(len(self.results))

        for i, item in enumerate(self.results):
            self.table.setItem(i, 0, QTableWidgetItem(item.get("group_name", "")))
            self.table.setItem(i, 1, QTableWidgetItem(item.get("sourcingId", "")))
            self.table.setItem(i, 2, QTableWidgetItem(item.get("status", "")))
            result_text = "성공" if item.get("success") else "실패"
            self.table.setItem(i, 3, QTableWidgetItem(result_text))

        layout.addWidget(self.table)

        # 버튼
        btn_layout = QHBoxLayout()

        save_btn = QPushButton("💾 CSV 저장")
        save_btn.clicked.connect(self.save_csv)
        btn_layout.addWidget(save_btn)

        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def save_csv(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "CSV 저장",
            f"11st_disconnect_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV Files (*.csv)"
        )
        if filename:
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(["그룹", "상품ID", "상태", "결과"])
                for item in self.results:
                    writer.writerow([
                        item.get("group_name", ""),
                        item.get("sourcingId", ""),
                        item.get("status", ""),
                        "성공" if item.get("success") else "실패"
                    ])
            QMessageBox.information(self, "저장 완료", f"저장됨: {filename}")


class MainWindow(QMainWindow):
    """메인 윈도우"""

    def __init__(self):
        super().__init__()
        self.api = None
        self.worker = None
        self.preview_worker = None
        self.selected_group = None
        self.selected_groups = None
        self.pending_disconnect_ids = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("불사자 11번가 마켓 끊기 v1.1 (플로/흑곰/검은곰)")
        self.setMinimumSize(900, 850)

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
        group_box = QGroupBox("📁 그룹 선택 (연결 후 자동 로드)")
        group_layout = QVBoxLayout(group_box)

        # 그룹 콤보박스 (API에서 동적 로드)
        combo_row = QHBoxLayout()
        combo_row.addWidget(QLabel("그룹:"))
        self.group_combo = QComboBox()
        self.group_combo.addItem("▼ 연결 후 선택")
        self.group_combo.setMinimumWidth(300)
        self.group_combo.currentIndexChanged.connect(self.on_group_selected)
        combo_row.addWidget(self.group_combo)

        self.selected_group_label = QLabel("선택: 없음")
        self.selected_group_label.setStyleSheet("font-weight: bold; color: #1976D2;")
        combo_row.addWidget(self.selected_group_label)
        combo_row.addStretch()
        group_layout.addLayout(combo_row)

        # 시작/끝 번호 설정
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("시작:"))
        self.start_index_spin = QSpinBox()
        self.start_index_spin.setRange(1, 1000)
        self.start_index_spin.setValue(1)
        self.start_index_spin.setFixedWidth(70)
        range_row.addWidget(self.start_index_spin)
        range_row.addWidget(QLabel("끝:"))
        self.end_index_spin = QSpinBox()
        self.end_index_spin.setRange(1, 1000)
        self.end_index_spin.setValue(1000)
        self.end_index_spin.setFixedWidth(70)
        range_row.addWidget(self.end_index_spin)
        range_row.addWidget(QLabel("번째 그룹까지"))
        range_row.addStretch()
        group_layout.addLayout(range_row)

        # 전체 선택 버튼
        all_select_row = QHBoxLayout()

        self.select_all_btn = QPushButton("🌐 전체 그룹 선택")
        self.select_all_btn.clicked.connect(self.select_all_groups)
        self.select_all_btn.setStyleSheet("background-color: #E8F5E9; font-weight: bold;")
        all_select_row.addWidget(self.select_all_btn)

        self.group_count_label = QLabel("(0개)")
        all_select_row.addWidget(self.group_count_label)

        all_select_row.addStretch()
        group_layout.addLayout(all_select_row)

        layout.addWidget(group_box)

        # === 수량 설정 ===
        count_group = QGroupBox("📊 수량 설정 (단일 그룹 선택 시)")
        count_layout = QHBoxLayout(count_group)

        self.disconnect_all_radio = QRadioButton("전체")
        self.disconnect_all_radio.setChecked(True)
        self.disconnect_count_radio = QRadioButton("수량 지정:")

        self.disconnect_btn_group = QButtonGroup()
        self.disconnect_btn_group.addButton(self.disconnect_all_radio)
        self.disconnect_btn_group.addButton(self.disconnect_count_radio)

        count_layout.addWidget(self.disconnect_all_radio)
        count_layout.addWidget(self.disconnect_count_radio)

        self.disconnect_count_spin = QSpinBox()
        self.disconnect_count_spin.setRange(1, 100000)
        self.disconnect_count_spin.setValue(1000)
        self.disconnect_count_spin.setEnabled(False)
        count_layout.addWidget(self.disconnect_count_spin)
        count_layout.addStretch()

        self.disconnect_count_radio.toggled.connect(self.disconnect_count_spin.setEnabled)

        layout.addWidget(count_group)

        # === 필터 옵션 ===
        filter_group = QGroupBox("🔍 필터 옵션")
        filter_layout = QVBoxLayout(filter_group)

        exclude_label = QLabel("📌 제외할 상품명 (한 줄에 하나씩, 정확히 일치하는 상품 제외):")
        filter_layout.addWidget(exclude_label)

        self.exclude_names_input = QTextEdit()
        self.exclude_names_input.setPlaceholderText("제외할 상품명1\n제외할 상품명2\n제외할 상품명3")
        self.exclude_names_input.setMaximumHeight(100)
        filter_layout.addWidget(self.exclude_names_input)

        layout.addWidget(filter_group)

        # === 실행 ===
        action_box = QGroupBox("🔌 11번가 마켓 끊기")
        action_layout = QVBoxLayout(action_box)

        info_label = QLabel(
            "📌 선택한 그룹의 11번가 업로드됨 상품을 마켓에서 끊습니다.\n"
            "   • 단일 그룹: 미리보기 후 진행\n"
            "   • 다중 그룹: 바로 진행 (제외 목록 적용)\n"
            "   • 🚀 병렬 10개 동시 처리"
        )
        info_label.setStyleSheet("color: #666; margin: 5px;")
        action_layout.addWidget(info_label)

        self.disconnect_btn = QPushButton("🔌 11번가 마켓 끊기 시작")
        self.disconnect_btn.setFixedHeight(45)
        self.disconnect_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #EF5350, stop:1 #E53935);
                color: white;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F44336, stop:1 #EF5350);
            }
        """)
        self.disconnect_btn.clicked.connect(self.start_disconnect)
        action_layout.addWidget(self.disconnect_btn)

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
        self.stop_btn.clicked.connect(self.stop_disconnect)
        self.stop_btn.setEnabled(False)
        layout.addWidget(self.stop_btn)

        # 프로그램 설명 출력
        self.show_welcome_message()

    def show_welcome_message(self):
        """프로그램 설명 출력"""
        welcome = """
╔══════════════════════════════════════════════════════════════════╗
║       🔌 불사자 11번가 마켓 끊기 v1.1 (플로/흑곰/검은곰)          ║
╚══════════════════════════════════════════════════════════════════╝

📌 프로그램 목적:
   선택한 그룹의 11번가 업로드됨 상품을 마켓에서 끊기
   (불사자 상품은 유지, 11번가 연결만 해제)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📁 그룹 목록:
   • 연결 후 자동으로 그룹 목록 로드
   • 단일 그룹 선택 또는 범위 지정 가능

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✨ v1.1 새 기능:
   • 🔍 미리보기 기능 (단일 그룹)
   • 🚫 제외할 상품명 필터링
   • 🚀 병렬 10개 동시 처리
   • 🔄 연결 오류 시 자동 재시도

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ 주의사항:
   • 끊기 후에는 복구할 수 없습니다!
   • 신중하게 그룹을 선택하세요

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
        global GROUPS, ALL_GROUP_NAMES
        access = self.access_input.text().strip()
        refresh = self.refresh_input.text().strip()

        if not access or not refresh:
            QMessageBox.warning(self, "경고", "토큰을 입력해주세요.")
            return

        try:
            self.api = BulsajaAPI(access, refresh)
            groups_dict, group_names = self.api.get_groups()

            # 전역 변수에 저장
            GROUPS = groups_dict
            ALL_GROUP_NAMES = group_names

            # 콤보박스 업데이트
            self.group_combo.blockSignals(True)
            self.group_combo.clear()
            self.group_combo.addItem("▼ 그룹 선택")
            self.group_combo.addItems(group_names)
            self.group_combo.blockSignals(False)

            # 범위 스핀박스 업데이트
            self.start_index_spin.setRange(1, len(group_names))
            self.end_index_spin.setRange(1, len(group_names))
            self.end_index_spin.setValue(len(group_names))

            self.group_count_label.setText(f"({len(group_names)}개)")
            self.log_text.append(f"✅ 연결 성공! 그룹 {len(group_names)}개 로드됨")
            QMessageBox.information(self, "성공", f"연결 성공!\n그룹 {len(group_names)}개 로드됨")
        except Exception as e:
            self.log_text.append(f"❌ 연결 실패: {e}")
            QMessageBox.critical(self, "오류", f"연결 실패:\n{e}")

    def on_group_selected(self, index):
        """그룹 선택"""
        if index == 0:
            self.selected_group = None
            self.selected_groups = None
            self.selected_group_label.setText("선택: 없음")
            return

        self.selected_group = self.group_combo.currentText()
        self.selected_groups = None
        self.selected_group_label.setText(f"선택: {self.selected_group}")

    def select_all_groups(self):
        """전체 그룹 선택 (범위 내)"""
        if not ALL_GROUP_NAMES:
            QMessageBox.warning(self, "경고", "먼저 연결 테스트를 해주세요.")
            return

        # 콤보박스 초기화
        self.group_combo.blockSignals(True)
        self.group_combo.setCurrentIndex(0)
        self.group_combo.blockSignals(False)

        start_idx = self.start_index_spin.value() - 1
        end_idx = self.end_index_spin.value()

        self.selected_groups = ALL_GROUP_NAMES[start_idx:end_idx]
        self.selected_group = None

        if start_idx > 0 or end_idx < len(ALL_GROUP_NAMES):
            self.selected_group_label.setText(f"선택: {start_idx + 1}~{end_idx}번 ({len(self.selected_groups)}개 그룹)")
        else:
            self.selected_group_label.setText(f"선택: 전체 ({len(self.selected_groups)}개 그룹)")

    def start_disconnect(self):
        """마켓 끊기 시작"""
        if not self.api:
            QMessageBox.warning(self, "경고", "먼저 연결 테스트를 해주세요.")
            return

        # 제외할 상품명 파싱
        exclude_text = self.exclude_names_input.toPlainText().strip()
        exclude_names = []
        if exclude_text:
            exclude_names = [name.strip() for name in exclude_text.split("\n") if name.strip()]

        # 다중 그룹 선택
        if self.selected_groups:
            groups = []
            for group_name in self.selected_groups:
                group_id = GROUPS.get(group_name)
                if group_id:
                    groups.append((group_name, group_id))

            if not groups:
                QMessageBox.warning(self, "경고", "유효한 그룹이 없습니다.")
                return

            reply = QMessageBox.warning(
                self, "⚠️ 마켓 끊기 확인",
                f"정말로 {len(groups)}개 그룹의 11번가 상품을 끊으시겠습니까?\n\n"
                f"⚠️ 이 작업은 되돌릴 수 없습니다!\n\n"
                f"대상 그룹 수: {len(groups)}개\n"
                f"제외 상품명: {len(exclude_names)}개",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

            # 다중 그룹 Worker
            self.worker = MultiGroupDisconnectWorker(self.api, groups, exclude_names, market_type="ST11")
            self.worker.progress.connect(self.update_progress)
            self.worker.group_progress.connect(self.update_group_progress)
            self.worker.log.connect(self.append_log)
            self.worker.finished_signal.connect(self.on_finished)

            self.disconnect_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.progress_bar.setValue(0)
            self.status_label.setText("마켓 끊기 진행 중...")

            self.worker.start()

        # 단일 그룹 선택 - 미리보기
        elif self.selected_group:
            group_id = GROUPS.get(self.selected_group)
            if not group_id:
                QMessageBox.warning(self, "경고", "그룹 ID를 찾을 수 없습니다.")
                return

            is_all = self.disconnect_all_radio.isChecked()
            disconnect_count = self.disconnect_count_spin.value()

            self.log_text.append(f"\n{'='*50}")
            self.log_text.append(f"🔍 미리보기 시작: {self.selected_group}")
            if exclude_names:
                self.log_text.append(f"제외 목록: {len(exclude_names)}개")

            # 미리보기 Worker
            self.preview_worker = PreviewWorker(
                self.api, self.selected_group, exclude_names, disconnect_count, is_all
            )
            self.preview_worker.progress.connect(self.append_log)
            self.preview_worker.finished_signal.connect(self.on_preview_finished)

            self.disconnect_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)

            self.preview_worker.start()
        else:
            QMessageBox.warning(self, "경고", "그룹을 선택해주세요.")

    def on_preview_finished(self, success, message, data):
        """미리보기 완료"""
        self.disconnect_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if not success:
            self.log_text.append(f"❌ 미리보기 실패: {message}")
            QMessageBox.warning(self, "오류", f"미리보기 실패:\n{message}")
            return

        if not data:
            self.log_text.append("❌ 데이터 없음")
            return

        matched = data["matched"]
        disconnect = data["disconnect"]
        total = data["total_products"]

        self.log_text.append(f"\n📊 미리보기 결과:")
        self.log_text.append(f"  • 11번가 상품: {total}개")
        self.log_text.append(f"  • 제외될 상품 (매칭됨): {len(matched)}개")
        self.log_text.append(f"  • 연결 끊을 상품: {len(disconnect)}개")

        # 미리보기 팝업 표시
        dialog = PreviewDialog(matched, disconnect, total, self)
        dialog.exec()

        if dialog.result_action == "proceed" and disconnect:
            # 연결 끊기 진행
            self.pending_disconnect_ids = [p["id"] for p in disconnect]
            self.start_disconnect_execute()
        else:
            self.log_text.append("⏹️ 사용자 취소")

    def start_disconnect_execute(self):
        """마켓 연결 끊기 실행 (미리보기 후)"""
        if not self.pending_disconnect_ids:
            QMessageBox.warning(self, "경고", "연결 끊을 상품이 없습니다.")
            return

        self.log_text.append(f"\n🚀 연결 끊기 시작: {len(self.pending_disconnect_ids)}개")

        # DisconnectWorker 시작
        self.worker = DisconnectWorker(
            self.api,
            self.pending_disconnect_ids,
            market_type="ST11"
        )
        self.worker.progress.connect(self.update_progress)
        self.worker.log.connect(self.append_log)
        self.worker.finished_signal.connect(self.on_finished)

        self.disconnect_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)

        self.worker.start()

    def update_group_progress(self, current, total, group_name):
        """그룹 진행 상황 업데이트"""
        self.status_label.setText(f"그룹 {current}/{total}: {group_name}")

    def stop_disconnect(self):
        """마켓 끊기 중지"""
        if self.worker:
            self.worker.stop()
            self.log_text.append("⏹️ 중지 요청됨...")
        if self.preview_worker:
            self.preview_worker.stop()
            self.log_text.append("⏹️ 미리보기 중지 요청됨...")

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

    def on_finished(self, success, message, result):
        """완료"""
        self.disconnect_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("완료")
        self.pending_disconnect_ids = None

        if not success:
            QMessageBox.warning(self, "알림", message)
            return

        if result and result.get("results"):
            dialog = ResultDialog(result["results"], "🔌 마켓 끊기 결과", self)
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
