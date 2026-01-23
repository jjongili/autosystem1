# -*- coding: utf-8 -*-
"""
불사자 배송비 확인/수정 도구
- 1단계: 배송비 6720 → 7000 올림 (해외마켓ID+배송비 저장)
- 2단계: 저장된 해외마켓ID로 매칭하여 배송비 적용

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
from typing import List, Dict

import tkinter as tk
from tkinter import ttk, messagebox

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


class ShippingFixerGUI(tk.Tk):
    """배송비 확인/수정 도구"""

    SAVE_FILE = Path(__file__).parent / "shipping_fixed_log.json"

    def __init__(self):
        super().__init__()

        self.title("📦 불사자 배송비 수정 도구")
        self.geometry("950x750")

        # API 클라이언트
        self.api_client = None
        self.group_id_map = {}

        # 상품 데이터
        self.products = []
        self.products2 = []  # 2단계용
        self.selected_items = set()
        self.selected_items2 = set()

        # 수정 완료 기록 (해외마켓ID → 배송비)
        self.fixed_records = self._load_fixed_records()

        self._build_ui()

    def _load_fixed_records(self) -> Dict[str, int]:
        """수정 완료 기록 로드"""
        try:
            if self.SAVE_FILE.exists():
                with open(self.SAVE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except:
            pass
        return {}

    def _save_fixed_records(self):
        """수정 완료 기록 저장"""
        try:
            with open(self.SAVE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.fixed_records, f, ensure_ascii=False, indent=2)
            self.log(f"💾 기록 저장됨 ({len(self.fixed_records)}개)")
        except Exception as e:
            self.log(f"⚠️ 기록 저장 실패: {e}")

    def _build_ui(self):
        """UI 구성"""
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # === API 연결 (공통) ===
        conn_frame = ttk.LabelFrame(main_frame, text="🔑 불사자 연결", padding="10")
        conn_frame.pack(fill=tk.X, pady=(0, 10))

        conn_row = ttk.Frame(conn_frame)
        conn_row.pack(fill=tk.X)

        ttk.Label(conn_row, text="포트:").pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value="9222")
        ttk.Entry(conn_row, textvariable=self.port_var, width=8).pack(side=tk.LEFT, padx=(5, 10))

        ttk.Button(conn_row, text="🌐 크롬 열기", command=self.open_chrome).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(conn_row, text="🔗 연결", command=self.connect_api).pack(side=tk.LEFT)

        self.conn_status_var = tk.StringVar(value="⚫ 미연결")
        ttk.Label(conn_row, textvariable=self.conn_status_var).pack(side=tk.LEFT, padx=(10, 0))

        # 저장된 기록 수
        ttk.Label(conn_row, text=f"  |  저장된 기록: {len(self.fixed_records)}개").pack(side=tk.RIGHT)

        # === 탭 ===
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # 탭1: 배송비 수정
        self.tab1 = ttk.Frame(self.notebook)
        self.notebook.add(self.tab1, text="1단계: 배송비 수정 (6720→7000)")
        self._build_tab1()

        # 탭2: 저장된 배송비 적용
        self.tab2 = ttk.Frame(self.notebook)
        self.notebook.add(self.tab2, text="2단계: 저장된 배송비 적용")
        self._build_tab2()

        # === 로그 (공통) ===
        log_frame = ttk.LabelFrame(main_frame, text="📋 로그", padding="5")
        log_frame.pack(fill=tk.X, pady=(10, 0))

        self.log_text = tk.Text(log_frame, height=6, state='disabled', font=('Consolas', 9))
        self.log_text.pack(fill=tk.X)

    def _build_tab1(self):
        """탭1: 배송비 수정"""
        # 그룹 선택
        group_frame = ttk.LabelFrame(self.tab1, text="📁 그룹 선택", padding="10")
        group_frame.pack(fill=tk.X, pady=(10, 10), padx=5)

        group_row = ttk.Frame(group_frame)
        group_row.pack(fill=tk.X)

        ttk.Label(group_row, text="그룹:").pack(side=tk.LEFT)
        self.group_var = tk.StringVar()
        self.group_combo = ttk.Combobox(group_row, textvariable=self.group_var, width=30)
        self.group_combo.pack(side=tk.LEFT, padx=(5, 10))

        ttk.Label(group_row, text="최대:").pack(side=tk.LEFT)
        self.limit_var = tk.StringVar(value="500")
        ttk.Entry(group_row, textvariable=self.limit_var, width=8).pack(side=tk.LEFT, padx=(5, 10))

        ttk.Button(group_row, text="📥 상품 불러오기", command=self.load_products).pack(side=tk.LEFT)

        # 상품 목록
        list_frame = ttk.LabelFrame(self.tab1, text="📋 상품 목록 (배송비 낮은 순, 이미 처리된 해외마켓ID 제외)", padding="5")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 10))

        columns = ("check", "product_no", "name", "shipping", "weight")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=12)

        self.tree.heading("check", text="✓")
        self.tree.heading("product_no", text="해외마켓ID")
        self.tree.heading("name", text="상품명")
        self.tree.heading("shipping", text="배송비")
        self.tree.heading("weight", text="무게")

        self.tree.column("check", width=30, anchor="center")
        self.tree.column("product_no", width=150)
        self.tree.column("name", width=400)
        self.tree.column("shipping", width=80, anchor="right")
        self.tree.column("weight", width=80, anchor="right")

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Button-1>", self.on_tree_click)

        # 버튼
        btn_frame = ttk.Frame(self.tab1)
        btn_frame.pack(fill=tk.X, padx=5)

        ttk.Button(btn_frame, text="☑️ 전체 선택", command=self.select_all).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="☐ 전체 해제", command=self.deselect_all).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="🔍 6720원만 선택", command=self.select_6720).pack(side=tk.LEFT, padx=(0, 5))

        ttk.Label(btn_frame, text="  |  ").pack(side=tk.LEFT)

        ttk.Button(btn_frame, text="🔧 6720→7000 수정 (저장)", command=self.fix_6720).pack(side=tk.LEFT, padx=(0, 5))

        self.select_count_var = tk.StringVar(value="선택: 0개")
        ttk.Label(btn_frame, textvariable=self.select_count_var).pack(side=tk.RIGHT)

    def _build_tab2(self):
        """탭2: 저장된 배송비 적용"""
        # 그룹 선택
        group_frame = ttk.LabelFrame(self.tab2, text="📁 그룹 선택 (배송비 적용할 그룹)", padding="10")
        group_frame.pack(fill=tk.X, pady=(10, 10), padx=5)

        group_row = ttk.Frame(group_frame)
        group_row.pack(fill=tk.X)

        ttk.Label(group_row, text="그룹:").pack(side=tk.LEFT)
        self.group_var2 = tk.StringVar()
        self.group_combo2 = ttk.Combobox(group_row, textvariable=self.group_var2, width=30)
        self.group_combo2.pack(side=tk.LEFT, padx=(5, 10))

        ttk.Label(group_row, text="최대:").pack(side=tk.LEFT)
        self.limit_var2 = tk.StringVar(value="1000")
        ttk.Entry(group_row, textvariable=self.limit_var2, width=8).pack(side=tk.LEFT, padx=(5, 10))

        ttk.Button(group_row, text="📥 매칭 상품 불러오기", command=self.load_products_tab2).pack(side=tk.LEFT)

        # 상품 목록
        list_frame = ttk.LabelFrame(self.tab2, text="📋 저장된 해외마켓ID와 매칭되는 상품 (배송비 다른 것만)", padding="5")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 10))

        columns = ("check", "product_no", "name", "current", "saved")
        self.tree2 = ttk.Treeview(list_frame, columns=columns, show="headings", height=12)

        self.tree2.heading("check", text="✓")
        self.tree2.heading("product_no", text="해외마켓ID")
        self.tree2.heading("name", text="상품명")
        self.tree2.heading("current", text="현재 배송비")
        self.tree2.heading("saved", text="저장된 배송비")

        self.tree2.column("check", width=30, anchor="center")
        self.tree2.column("product_no", width=150)
        self.tree2.column("name", width=350)
        self.tree2.column("current", width=100, anchor="right")
        self.tree2.column("saved", width=100, anchor="right")

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree2.yview)
        self.tree2.configure(yscrollcommand=scrollbar.set)

        self.tree2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree2.bind("<Button-1>", self.on_tree2_click)

        # 버튼
        btn_frame = ttk.Frame(self.tab2)
        btn_frame.pack(fill=tk.X, padx=5)

        ttk.Button(btn_frame, text="☑️ 전체 선택", command=self.select_all2).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="☐ 전체 해제", command=self.deselect_all2).pack(side=tk.LEFT, padx=(0, 5))

        ttk.Label(btn_frame, text="  |  ").pack(side=tk.LEFT)

        ttk.Button(btn_frame, text="🔧 저장된 배송비로 수정", command=self.apply_saved_shipping).pack(side=tk.LEFT, padx=(0, 5))

        self.select_count_var2 = tk.StringVar(value="선택: 0개")
        ttk.Label(btn_frame, textvariable=self.select_count_var2).pack(side=tk.RIGHT)

    def log(self, message: str):
        """로그 출력"""
        def _log():
            self.log_text.config(state='normal')
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')
        self.after(0, _log)

    def open_chrome(self):
        """크롬 열기"""
        port = int(self.port_var.get())
        self.log(f"🌐 크롬 열기 (포트: {port})...")
        success, msg = open_chrome_debug(port)
        if success:
            self.log("✅ 크롬 실행됨 - 불사자 로그인 후 '연결' 버튼 클릭")
        else:
            self.log(f"❌ 크롬 실행 실패: {msg}")

    def connect_api(self):
        """API 연결"""
        try:
            port = int(self.port_var.get())
            self.log(f"🔗 토큰 추출 중...")

            success, access_token, refresh_token, msg = extract_tokens_from_browser(port)
            if not success or not access_token:
                self.conn_status_var.set("🔴 연결 실패")
                self.log(f"❌ 토큰 추출 실패: {msg}")
                return

            self.api_client = BulsajaAPIClient(access_token, refresh_token)

            groups = self.api_client.get_market_groups()
            if groups:
                self.group_id_map = self._load_group_ids()
                self.conn_status_var.set(f"🟢 연결됨 ({len(groups)}개 그룹)")
                self.log(f"✅ API 연결 성공! {len(groups)}개 그룹")
                self.group_combo['values'] = groups
                self.group_combo2['values'] = groups
                if groups:
                    self.group_combo.current(0)
                    self.group_combo2.current(0)
            else:
                self.conn_status_var.set("🔴 연결 실패")
                self.log("❌ 그룹을 가져올 수 없습니다.")
        except Exception as e:
            self.conn_status_var.set("🔴 연결 실패")
            self.log(f"❌ API 연결 실패: {e}")

    def _load_group_ids(self) -> Dict[str, int]:
        """그룹명 → 그룹ID 매핑"""
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

    # ========== 탭1: 배송비 수정 ==========

    def load_products(self):
        """상품 불러오기 (배송비 낮은 순)"""
        if not self.api_client:
            messagebox.showerror("오류", "먼저 API에 연결하세요.")
            return

        group_name = self.group_var.get()
        if not group_name:
            messagebox.showerror("오류", "그룹을 선택하세요.")
            return

        try:
            limit = int(self.limit_var.get())
            self.log(f"📥 상품 불러오는 중... (그룹: {group_name})")

            filter_model = {
                "marketGroupName": {
                    "filterType": "text",
                    "type": "equals",
                    "filter": group_name
                }
            }

            sort_model = [{"colId": "uploadOverseaDeliveryFee", "sort": "asc"}]

            products, total = self.api_client.get_products(0, limit, filter_model, sort_model)

            if not products:
                self.log("⚠️ 상품이 없습니다.")
                return

            # 이미 처리된 해외마켓ID 제외
            filtered = []
            skipped = 0
            for p in products:
                product_no = p.get('productNo', '')
                if product_no and product_no in self.fixed_records:
                    skipped += 1
                    continue
                filtered.append(p)

            self.products = filtered
            self.selected_items.clear()

            self.tree.delete(*self.tree.get_children())

            for p in filtered:
                pid = p.get('ID', '')
                product_no = p.get('productNo', '') or ''
                name = (p.get('uploadCommonProductName', '') or '')[:40]
                shipping = p.get('uploadOverseaDeliveryFee', 0) or 0
                weight = p.get('uploadWeight', 0) or 0

                self.tree.insert("", tk.END, iid=pid, values=(
                    "☐", product_no, name, f"{shipping:,}원", f"{weight}g"
                ))

            self.log(f"✅ {len(filtered)}개 로드 (이미 처리: {skipped}개 스킵)")
            self._update_select_count()

        except Exception as e:
            self.log(f"❌ 상품 로드 실패: {e}")

    def on_tree_click(self, event):
        """Treeview 클릭"""
        region = self.tree.identify("region", event.x, event.y)
        if region == "cell":
            col = self.tree.identify_column(event.x)
            item = self.tree.identify_row(event.y)

            if col == "#1" and item:
                if item in self.selected_items:
                    self.selected_items.remove(item)
                    values = list(self.tree.item(item, "values"))
                    values[0] = "☐"
                    self.tree.item(item, values=values)
                else:
                    self.selected_items.add(item)
                    values = list(self.tree.item(item, "values"))
                    values[0] = "☑"
                    self.tree.item(item, values=values)

                self._update_select_count()

    def _update_select_count(self):
        self.select_count_var.set(f"선택: {len(self.selected_items)}개")

    def select_all(self):
        for item in self.tree.get_children():
            self.selected_items.add(item)
            values = list(self.tree.item(item, "values"))
            values[0] = "☑"
            self.tree.item(item, values=values)
        self._update_select_count()

    def deselect_all(self):
        for item in self.tree.get_children():
            if item in self.selected_items:
                self.selected_items.remove(item)
            values = list(self.tree.item(item, "values"))
            values[0] = "☐"
            self.tree.item(item, values=values)
        self._update_select_count()

    def select_6720(self):
        self.deselect_all()
        for item in self.tree.get_children():
            values = self.tree.item(item, "values")
            shipping_str = values[3].replace(",", "").replace("원", "")
            try:
                if int(shipping_str) == 6720:
                    self.selected_items.add(item)
                    values = list(values)
                    values[0] = "☑"
                    self.tree.item(item, values=values)
            except:
                pass
        self._update_select_count()
        self.log(f"✅ 6720원 상품 {len(self.selected_items)}개 선택됨")

    def fix_6720(self):
        """6720원 → 7000 수정 + 저장"""
        if not self.selected_items:
            messagebox.showinfo("알림", "상품을 선택하세요.")
            return

        if not self.api_client:
            messagebox.showerror("오류", "API에 연결하세요.")
            return

        items_to_fix = list(self.selected_items)

        if not messagebox.askyesno("확인", f"{len(items_to_fix)}개 상품을 수정하시겠습니까?\n(6720 → 7000, 해외마켓ID+배송비 저장)"):
            return

        threading.Thread(target=self._fix_6720_thread, args=(items_to_fix,), daemon=True).start()

    def _fix_6720_thread(self, items: List[str]):
        try:
            self.log(f"🔧 {len(items)}개 상품 수정 중...")

            success_count = 0
            for idx, pid in enumerate(items, 1):
                try:
                    product = next((p for p in self.products if p.get('ID') == pid), None)
                    if not product:
                        continue

                    product_no = product.get('productNo', '')
                    current_fee = product.get('uploadOverseaDeliveryFee', 0) or 0

                    if current_fee == 6720:
                        new_fee = 7000

                        update_data = {"uploadOverseaDeliveryFee": new_fee}
                        success, msg = self.api_client.update_product_fields(pid, update_data)

                        if success:
                            self.log(f"   ✅ [{idx}] {product_no} - {current_fee} → {new_fee}")
                            success_count += 1

                            # 기록 저장 (해외마켓ID → 배송비)
                            if product_no:
                                self.fixed_records[product_no] = new_fee

                            self.after(0, lambda p=pid: self._remove_from_tree(p))
                        else:
                            self.log(f"   ❌ [{idx}] {product_no} - 실패: {msg}")
                    else:
                        self.log(f"   ⏭️ [{idx}] {product_no} - {current_fee}원 (6720 아님)")

                except Exception as e:
                    self.log(f"   ❌ [{idx}] 오류: {e}")

                time.sleep(0.3)

            # 기록 파일 저장
            self._save_fixed_records()

            self.log(f"✅ 수정 완료: {success_count}/{len(items)}개")

        except Exception as e:
            self.log(f"❌ 오류: {e}")

    def _remove_from_tree(self, pid: str):
        """트리에서 제거"""
        try:
            self.tree.delete(pid)
            if pid in self.selected_items:
                self.selected_items.remove(pid)
            self._update_select_count()
        except:
            pass

    # ========== 탭2: 저장된 배송비 적용 ==========

    def load_products_tab2(self):
        """저장된 해외마켓ID와 매칭되는 상품 불러오기"""
        if not self.api_client:
            messagebox.showerror("오류", "먼저 API에 연결하세요.")
            return

        if not self.fixed_records:
            messagebox.showinfo("알림", "저장된 기록이 없습니다.\n1단계에서 먼저 배송비를 수정하세요.")
            return

        group_name = self.group_var2.get()
        if not group_name:
            messagebox.showerror("오류", "그룹을 선택하세요.")
            return

        try:
            limit = int(self.limit_var2.get())
            self.log(f"📥 매칭 상품 검색 중... (그룹: {group_name})")

            filter_model = {
                "marketGroupName": {
                    "filterType": "text",
                    "type": "equals",
                    "filter": group_name
                }
            }

            products, total = self.api_client.get_products(0, limit, filter_model)

            if not products:
                self.log("⚠️ 상품이 없습니다.")
                return

            # 저장된 해외마켓ID와 매칭 + 배송비 다른 것만
            matched = []
            for p in products:
                product_no = p.get('productNo', '')
                if product_no and product_no in self.fixed_records:
                    saved_fee = self.fixed_records[product_no]
                    current_fee = p.get('uploadOverseaDeliveryFee', 0) or 0
                    if current_fee != saved_fee:
                        p['_saved_fee'] = saved_fee
                        matched.append(p)

            self.products2 = matched
            self.selected_items2.clear()

            self.tree2.delete(*self.tree2.get_children())

            for p in matched:
                pid = p.get('ID', '')
                product_no = p.get('productNo', '') or ''
                name = (p.get('uploadCommonProductName', '') or '')[:35]
                current_fee = p.get('uploadOverseaDeliveryFee', 0) or 0
                saved_fee = p.get('_saved_fee', 0)

                self.tree2.insert("", tk.END, iid=pid, values=(
                    "☐", product_no, name, f"{current_fee:,}원", f"{saved_fee:,}원"
                ))

            self.log(f"✅ {len(matched)}개 매칭됨 (배송비 다른 상품)")
            self._update_select_count2()

        except Exception as e:
            self.log(f"❌ 로드 실패: {e}")

    def on_tree2_click(self, event):
        """탭2 Treeview 클릭"""
        region = self.tree2.identify("region", event.x, event.y)
        if region == "cell":
            col = self.tree2.identify_column(event.x)
            item = self.tree2.identify_row(event.y)

            if col == "#1" and item:
                if item in self.selected_items2:
                    self.selected_items2.remove(item)
                    values = list(self.tree2.item(item, "values"))
                    values[0] = "☐"
                    self.tree2.item(item, values=values)
                else:
                    self.selected_items2.add(item)
                    values = list(self.tree2.item(item, "values"))
                    values[0] = "☑"
                    self.tree2.item(item, values=values)

                self._update_select_count2()

    def _update_select_count2(self):
        self.select_count_var2.set(f"선택: {len(self.selected_items2)}개")

    def select_all2(self):
        for item in self.tree2.get_children():
            self.selected_items2.add(item)
            values = list(self.tree2.item(item, "values"))
            values[0] = "☑"
            self.tree2.item(item, values=values)
        self._update_select_count2()

    def deselect_all2(self):
        for item in self.tree2.get_children():
            if item in self.selected_items2:
                self.selected_items2.remove(item)
            values = list(self.tree2.item(item, "values"))
            values[0] = "☐"
            self.tree2.item(item, values=values)
        self._update_select_count2()

    def apply_saved_shipping(self):
        """저장된 배송비 적용"""
        if not self.selected_items2:
            messagebox.showinfo("알림", "상품을 선택하세요.")
            return

        if not self.api_client:
            messagebox.showerror("오류", "API에 연결하세요.")
            return

        items = list(self.selected_items2)

        if not messagebox.askyesno("확인", f"{len(items)}개 상품에 저장된 배송비를 적용하시겠습니까?"):
            return

        threading.Thread(target=self._apply_saved_shipping_thread, args=(items,), daemon=True).start()

    def _apply_saved_shipping_thread(self, items: List[str]):
        try:
            self.log(f"🔧 {len(items)}개 상품 배송비 적용 중...")

            success_count = 0
            for idx, pid in enumerate(items, 1):
                try:
                    product = next((p for p in self.products2 if p.get('ID') == pid), None)
                    if not product:
                        continue

                    product_no = product.get('productNo', '')
                    saved_fee = product.get('_saved_fee', 0)

                    if saved_fee > 0:
                        update_data = {"uploadOverseaDeliveryFee": saved_fee}
                        success, msg = self.api_client.update_product_fields(pid, update_data)

                        if success:
                            self.log(f"   ✅ [{idx}] {product_no} → {saved_fee}원")
                            success_count += 1
                            self.after(0, lambda p=pid: self._remove_from_tree2(p))
                        else:
                            self.log(f"   ❌ [{idx}] {product_no} - 실패: {msg}")

                except Exception as e:
                    self.log(f"   ❌ [{idx}] 오류: {e}")

                time.sleep(0.3)

            self.log(f"✅ 적용 완료: {success_count}/{len(items)}개")

        except Exception as e:
            self.log(f"❌ 오류: {e}")

    def _remove_from_tree2(self, pid: str):
        """탭2 트리에서 제거"""
        try:
            self.tree2.delete(pid)
            if pid in self.selected_items2:
                self.selected_items2.remove(pid)
            self._update_select_count2()
        except:
            pass


def main():
    app = ShippingFixerGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
