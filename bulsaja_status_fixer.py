# -*- coding: utf-8 -*-
"""
불사자 상태 수정 도구
- "판매중"인데 실제 스마트스토어에 없는 상품 찾아서 상태 초기화
- 스마트스토어 버튼 누르는 것과 동일한 효과

by 프코노미
"""

import os
import sys
import json
import time
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# 공통 모듈
sys.path.insert(0, str(Path(__file__).parent))
from bulsaja_common import BulsajaAPIClient, extract_tokens_from_browser


def open_chrome_debug(port: int = 9222):
    """크롬을 디버그 모드로 열고 불사자 접속"""
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]

    chrome_path = None
    for p in chrome_paths:
        if os.path.exists(p):
            chrome_path = p
            break

    if not chrome_path:
        return False, "크롬을 찾을 수 없습니다"

    try:
        cmd = [
            chrome_path,
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            "--user-data-dir=" + os.path.expandvars(r"%TEMP%\chrome_debug_bulsaja"),
            "https://bulsaja.com"
        ]
        subprocess.Popen(cmd)
        return True, "크롬 실행됨"
    except Exception as e:
        return False, str(e)


class StatusFixerGUI(tk.Tk):
    """판매중 상태 확인 및 수정 도구"""

    def __init__(self):
        super().__init__()

        self.title("🔧 불사자 상태 수정 도구")
        self.geometry("700x600")

        # API 클라이언트
        self.api_client = None
        self.is_running = False
        self.group_id_map = {}  # 그룹명 → ID 매핑

        # 결과 저장
        self.fake_uploaded = []  # 가짜 업로드 상품 목록

        self._build_ui()
        self._init_api()

    def _build_ui(self):
        """UI 구성"""
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # === 설명 ===
        desc_frame = ttk.LabelFrame(main_frame, text="📋 설명", padding="10")
        desc_frame.pack(fill=tk.X, pady=(0, 10))

        desc_text = """이 도구는 "판매중" 상태인데 실제 스마트스토어에 상품이 없는 경우를 찾아서 상태를 초기화합니다.

동작 방식:
1. 선택한 그룹에서 "판매중(업로드완료)" 상태 상품 조회
2. 각 상품의 스마트스토어 상품번호 확인
3. 상품번호가 없거나 유효하지 않으면 → 상태 초기화 (수정중으로 변경)"""

        ttk.Label(desc_frame, text=desc_text, justify=tk.LEFT).pack(anchor=tk.W)

        # === API 연결 ===
        token_frame = ttk.LabelFrame(main_frame, text="🔑 불사자 연결", padding="10")
        token_frame.pack(fill=tk.X, pady=(0, 10))

        token_row = ttk.Frame(token_frame)
        token_row.pack(fill=tk.X)

        ttk.Label(token_row, text="포트:").pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value="9222")
        ttk.Entry(token_row, textvariable=self.port_var, width=8).pack(side=tk.LEFT, padx=(5, 10))

        ttk.Button(token_row, text="🌐 크롬 열기", command=self.open_chrome).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(token_row, text="🔗 연결", command=self.connect_api).pack(side=tk.LEFT)

        # 연결 상태
        self.conn_status_var = tk.StringVar(value="⚫ 미연결")
        ttk.Label(token_row, textvariable=self.conn_status_var).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Label(token_frame, text="💡 불사자 웹이 열린 크롬 브라우저가 디버그 모드(--remote-debugging-port=9222)로 실행되어 있어야 합니다",
                  foreground="gray", font=('', 8)).pack(anchor=tk.W, pady=(5, 0))

        # === 그룹 선택 ===
        group_frame = ttk.LabelFrame(main_frame, text="📁 그룹 선택", padding="10")
        group_frame.pack(fill=tk.X, pady=(0, 10))

        group_row = ttk.Frame(group_frame)
        group_row.pack(fill=tk.X)

        ttk.Label(group_row, text="그룹:").pack(side=tk.LEFT)
        self.group_var = tk.StringVar()
        self.group_combo = ttk.Combobox(group_row, textvariable=self.group_var, width=40)
        self.group_combo.pack(side=tk.LEFT, padx=(5, 10))

        ttk.Button(group_row, text="📥 그룹 불러오기", command=self.load_groups).pack(side=tk.LEFT)

        # 전체 그룹 체크
        self.all_groups_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(group_row, text="전체 그룹", variable=self.all_groups_var).pack(side=tk.LEFT, padx=(10, 0))

        # === 옵션 ===
        opt_frame = ttk.LabelFrame(main_frame, text="⚙️ 옵션", padding="10")
        opt_frame.pack(fill=tk.X, pady=(0, 10))

        opt_row = ttk.Frame(opt_frame)
        opt_row.pack(fill=tk.X)

        # 자동 수정 여부
        self.auto_fix_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_row, text="자동 수정 (체크 해제 시 확인만)", variable=self.auto_fix_var).pack(side=tk.LEFT)

        ttk.Label(opt_row, text="  |  ", foreground="gray").pack(side=tk.LEFT)

        ttk.Label(opt_row, text="최대 처리 수:").pack(side=tk.LEFT)
        self.limit_var = tk.StringVar(value="100")
        ttk.Entry(opt_row, textvariable=self.limit_var, width=8).pack(side=tk.LEFT, padx=(5, 0))

        # === 버튼 ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        self.btn_start = ttk.Button(btn_frame, text="🔍 확인 시작", command=self.start_check)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_stop = ttk.Button(btn_frame, text="🛑 중지", command=self.stop_check, state="disabled")
        self.btn_stop.pack(side=tk.LEFT)

        # 진행 상황
        self.progress_var = tk.StringVar(value="대기 중...")
        ttk.Label(btn_frame, textvariable=self.progress_var).pack(side=tk.RIGHT)

        # === 로그 ===
        log_frame = ttk.LabelFrame(main_frame, text="📋 로그", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, state='disabled',
                                                   font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 로그 색상 태그
        self.log_text.tag_configure("error", foreground="red")
        self.log_text.tag_configure("success", foreground="green")
        self.log_text.tag_configure("warning", foreground="orange")
        self.log_text.tag_configure("info", foreground="blue")

    def _init_api(self):
        """초기화"""
        self.log("💡 '크롬 열기' → 로그인 → '연결' 버튼을 눌러 불사자에 연결하세요.")

    def open_chrome(self):
        """크롬을 디버그 모드로 열기"""
        port = int(self.port_var.get())
        self.log(f"🌐 크롬 열기 (포트: {port})...")
        success, msg = open_chrome_debug(port)
        if success:
            self.log("✅ 크롬 실행됨 - 불사자 로그인 후 '연결' 버튼을 누르세요")
        else:
            self.log(f"❌ 크롬 실행 실패: {msg}")

    def connect_api(self):
        """브라우저에서 토큰 추출 후 API 연결"""
        try:
            port = int(self.port_var.get())
            self.log(f"🔗 브라우저에서 토큰 추출 중... (포트: {port})")

            # 브라우저에서 토큰 추출 (success, access_token, refresh_token, msg)
            success, access_token, refresh_token, msg = extract_tokens_from_browser(port)
            if not success or not access_token:
                self.conn_status_var.set("🔴 연결 실패")
                self.log(f"❌ 토큰 추출 실패: {msg}")
                return

            self.log("✅ 토큰 추출 성공")

            # API 클라이언트 생성
            self.api_client = BulsajaAPIClient(access_token, refresh_token)

            # 그룹 목록 조회
            groups = self.api_client.get_market_groups()
            if groups:
                # 그룹 ID 매핑 로드
                self.group_id_map = self._load_group_ids()

                self.conn_status_var.set(f"🟢 연결됨 ({len(groups)}개 그룹)")
                self.log(f"✅ API 연결 성공! {len(groups)}개 그룹")

                # 콤보박스에 그룹 목록 설정
                self.group_combo['values'] = groups
                if groups:
                    self.group_combo.current(0)
            else:
                self.conn_status_var.set("🔴 연결 실패")
                self.log("❌ 그룹을 가져올 수 없습니다.")
        except Exception as e:
            self.conn_status_var.set("🔴 연결 실패")
            self.log(f"❌ API 연결 실패: {e}")

    def _load_group_ids(self) -> Dict[str, int]:
        """그룹명 → 그룹ID 매핑 로드"""
        try:
            url = f"{self.api_client.BASE_URL}/market/groups/"
            response = self.api_client.session.post(url, json={})
            data = response.json()

            group_map = {}
            if isinstance(data, list):
                for group in data:
                    name = group.get('name', '')
                    gid = group.get('id')
                    if name and gid:
                        group_map[name] = gid
            return group_map
        except:
            return {}

    def log(self, message: str):
        """로그 출력"""
        def _log():
            self.log_text.config(state='normal')
            timestamp = datetime.now().strftime("%H:%M:%S")

            tag = None
            if "❌" in message or "실패" in message:
                tag = "error"
            elif "✅" in message or "성공" in message:
                tag = "success"
            elif "⚠️" in message:
                tag = "warning"
            elif "🔍" in message or "📤" in message:
                tag = "info"

            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n", tag)
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')
        self.after(0, _log)

    def load_groups(self):
        """그룹 목록 불러오기"""
        if not self.api_client:
            messagebox.showerror("오류", "먼저 브라우저에서 연결하세요.")
            return

        try:
            self.log("📥 그룹 목록 불러오는 중...")
            groups = self.api_client.get_market_groups()
            self.group_id_map = self._load_group_ids()

            if groups:
                self.group_combo['values'] = groups
                if groups:
                    self.group_combo.current(0)
                self.log(f"✅ {len(groups)}개 그룹 로드 완료")
            else:
                self.log("⚠️ 그룹이 없습니다.")
        except Exception as e:
            self.log(f"❌ 그룹 로드 실패: {e}")

    def start_check(self):
        """확인 시작"""
        if not self.api_client:
            messagebox.showerror("오류", "API 클라이언트가 초기화되지 않았습니다.")
            return

        if not self.all_groups_var.get() and not self.group_var.get():
            messagebox.showerror("오류", "그룹을 선택하세요.")
            return

        self.is_running = True
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.fake_uploaded = []

        threading.Thread(target=self._run_check, daemon=True).start()

    def stop_check(self):
        """확인 중지"""
        self.is_running = False
        self.log("🛑 중지 요청됨...")

    def _run_check(self):
        """확인 실행 (백그라운드)"""
        try:
            limit = int(self.limit_var.get())

            # 그룹 목록
            if self.all_groups_var.get():
                groups = list(self.group_id_map.keys())
            else:
                groups = [self.group_var.get()]

            self.log(f"🔍 확인 시작: {len(groups)}개 그룹, 최대 {limit}개")
            self.log("💡 API 호출 시 자동으로 상태가 초기화됩니다")

            total_checked = 0
            total_fake = 0
            total_fixed = 0

            for group_name in groups:
                if not self.is_running:
                    break

                self.log(f"\n📁 그룹: {group_name}")
                self.after(0, lambda g=group_name: self.progress_var.set(f"처리 중: {g}"))

                # 그룹 상품 조회 (필터 없이 전체)
                try:
                    filter_model = {
                        "marketGroupName": {
                            "filterType": "text",
                            "type": "equals",
                            "filter": group_name
                        }
                    }
                    products, total = self.api_client.get_products(0, limit, filter_model)
                    self.log(f"   전체 상품: {len(products) if products else 0}개 (총 {total}개)")

                    # 첫 상품 필드 확인
                    if products:
                        p = products[0]
                        # 스마트스토어 상품번호 필드 찾기
                        ss_fields = [k for k in p.keys() if 'smart' in k.lower() or 'product' in k.lower() or 'upload' in k.lower()]
                        self.log(f"   [필드] {ss_fields}")
                        for f in ss_fields[:5]:
                            self.log(f"   {f}={p.get(f)}")
                except Exception as e:
                    self.log(f"   ❌ 상품 조회 실패: {e}")
                    continue

                if not products:
                    self.log(f"   상품 없음")
                    continue

                # 스마트스토어 업로드된 상품만 필터링 (소문자 smartstore)
                ss_products = [p for p in products if 'smartstore' in str(p.get('uploadedMarkets', '')).lower()]
                self.log(f"   스마트스토어 업로드: {len(ss_products)}개")

                if not ss_products:
                    self.log(f"   스마트스토어 업로드 상품 없음")
                    continue

                # 그룹 내 스마트스토어 마켓 ID 조회
                group_id = self.group_id_map.get(group_name)
                if not group_id:
                    self.log(f"   ❌ 그룹 ID를 찾을 수 없음")
                    continue

                # 그룹 내 마켓 목록에서 스마트스토어 ID 찾기
                market_id = None
                try:
                    markets_url = f"{self.api_client.BASE_URL}/market/group/{group_id}/markets"
                    markets_res = self.api_client.session.get(markets_url)
                    if markets_res.status_code == 200:
                        markets = markets_res.json()
                        for m in markets:
                            if m.get('type') == 'SMARTSTORE':
                                market_id = m.get('id')
                                break
                except Exception as e:
                    self.log(f"   ❌ 마켓 조회 실패: {e}")
                    continue

                if not market_id:
                    self.log(f"   ❌ 스마트스토어 마켓 ID를 찾을 수 없음")
                    continue

                self.log(f"   그룹 ID: {group_id}, 마켓 ID: {market_id}")

                for idx, product in enumerate(ss_products, 1):
                    if not self.is_running:
                        break

                    product_id = product.get('ID', '')
                    product_name = product.get('uploadCommonProductName', '')[:30]
                    total_checked += 1

                    # 상품에서 스마트스토어 상품번호 조회 (uploadedSuccessUrl.smartstore)
                    try:
                        uploaded_url = product.get('uploadedSuccessUrl', {}) or {}
                        ss_product_no = uploaded_url.get('smartstore')

                        if not ss_product_no:
                            # 상세에서 시도
                            detail = self.api_client.get_product_detail(product_id)
                            uploaded_url = detail.get('uploadedSuccessUrl', {}) or {}
                            ss_product_no = uploaded_url.get('smartstore')

                        if not ss_product_no:
                            self.log(f"   ⏭️ [{idx}] {product_id} - 스마트스토어 상품번호 없음")
                            continue

                        # POST /api/market/group/{그룹ID}/smartstore/uploaded-products/{스마트스토어상품번호}/
                        check_url = f"{self.api_client.BASE_URL}/market/group/{group_id}/smartstore/uploaded-products/{ss_product_no}/"
                        if idx == 1:
                            self.log(f"   [URL] {check_url}")
                        response = self.api_client.session.post(check_url, json={"targetMarket": "SMARTSTORE"})

                        if response.status_code == 200:
                            result = response.json()

                            # 처음 3개 전체 응답 출력
                            if idx <= 3:
                                self.log(f"   [응답 전체] {json.dumps(result, ensure_ascii=False)[:300]}")

                            # data 안에 productName이 있고 값이 있으면 존재
                            data = result.get('data', {}) or {}
                            product_exists = bool(data.get('productName'))

                            if product_exists:
                                if idx % 100 == 0:
                                    self.log(f"   ✅ {idx}개 확인 완료...")
                            else:
                                # 상품 없음 - 가짜 업로드
                                total_fake += 1
                                total_fixed += 1
                                self.fake_uploaded.append({
                                    'id': product_id,
                                    'name': product_name,
                                    'group': group_name
                                })
                                self.log(f"   ⚠️ [{idx}] {product_id} - 가짜 (data={data})")
                        else:
                            # 에러 응답 내용 출력
                            self.log(f"   ❌ [{idx}] {product_id} - {response.status_code}: {response.text[:100]}")

                    except Exception as e:
                        self.log(f"   ❌ [{idx}] {product_id} - 오류: {e}")

                    # API 호출 간격
                    time.sleep(0.3)

                    # 진행률 업데이트
                    self.after(0, lambda c=total_checked: self.progress_var.set(f"확인: {c}개"))

            # 결과 요약
            self.log(f"\n{'='*50}")
            self.log(f"📊 결과 요약")
            self.log(f"   확인: {total_checked}개")
            self.log(f"   가짜 업로드 (초기화됨): {total_fake}개")
            self.log(f"{'='*50}")

        except Exception as e:
            self.log(f"❌ 오류 발생: {e}")
        finally:
            self.is_running = False
            self.after(0, self._on_finished)

    def _on_finished(self):
        """완료 콜백"""
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.progress_var.set("완료")


def main():
    app = StatusFixerGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
