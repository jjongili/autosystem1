# -*- coding: utf-8 -*-
"""
AI 배송비 자동 업데이트 마스터 GUI (ai_shipping_gui.py)

버전: v1.3 (2026-01-22)
핵심 개선: 
1. [대량 ID 모드] 수백 개의 ID를 불러와서 자동 순회 처리 (불사자 일일이 클릭 NO!)
2. [스마트 필터] 배송비 "0원"인 상품만 골라서 처리하는 옵션 추가
3. [전체 그룹 순회] 모든 창고를 하나하나 자동으로 돌며 업데이트
4. [통합 파일] 단일 파일 실행으로 의존성 문제 해결

by Antigravity
"""

import os
import json
import time
import re
import threading
import subprocess
import webbrowser
import requests
import websocket
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import builtins
from typing import List, Dict, Optional, Tuple
import csv

# 공통 모듈
from bulsaja_common import BulsajaAPIClient, extract_tokens_from_browser

# ==================== 설정 필드 ====================
CONFIG_FILE = "bulsaja_config.json"
PROCESSED_LOG = "processed_ai_shipping.json"
REPORTS_DIR = "reports"
AI_API_URL = "https://api.bulsaja.com/api/vertex/shipping-cost"

if not os.path.exists(REPORTS_DIR):
    os.makedirs(REPORTS_DIR)

# ==================== 핵심 로직 클래스 ====================
class BulsajaAIShippingUpdater(BulsajaAPIClient):
    def __init__(self, access_token: str = "", refresh_token: str = ""):
        super().__init__(access_token, refresh_token)
        self.stop_requested = False
        self.smart_filter = True # 0원인 것만 처리할지 여부
        self.config = self.load_local_config()
        
        # 브라우저 토큰 갱신 시도
        success, b_access, b_refresh, err = extract_tokens_from_browser(port=9222)
        if success:
            print(f"✅ 브라우저 세션에서 최신 토큰을 동기화했습니다.")
            self.access_token = b_access
            self.refresh_token = b_refresh
            self.config["access_token"] = b_access
            self.config["refresh_token"] = b_refresh
            self.save_local_config()
        
        self.processed_ids = self.load_processed_log()
        self.report_data = []

    def load_local_config(self) -> dict:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_local_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e: print(f"⚠️ 설정 저장 실패: {e}")

    def load_processed_log(self) -> set:
        if os.path.exists(PROCESSED_LOG):
            with open(PROCESSED_LOG, "r", encoding="utf-8") as f:
                try: return set(json.load(f))
                except: return set()
        return set()

    def save_processed_log(self):
        with open(PROCESSED_LOG, "w", encoding="utf-8") as f:
            json.dump(list(self.processed_ids), f, ensure_ascii=False, indent=2)

    def write_report(self):
        if not self.report_data: return
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(REPORTS_DIR, f"shipping_update_{timestamp}.csv")
        try:
            with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.report_data[0].keys())
                writer.writeheader()
                writer.writerows(self.report_data)
            print(f"📊 작업 리포트 저장 완료: {filepath}")
        except Exception as e:
            print(f"⚠️ 리포트 저장 실패: {e}")

    # --- 그룹(태그) 관리 API ---
    def get_existing_tags(self) -> List[str]:
        url = f"{self.BASE_URL}/manage/groups"
        try:
            response = self.session.get(url)
            data = response.json()
            return [g.get('name', '') for g in data if g.get('name')] if isinstance(data, list) else []
        except: return []

    def apply_tag_to_products(self, product_ids: List[str], tag_name: str) -> bool:
        if not product_ids: return False
        url = f"{self.BASE_URL}/sourcing/bulk-update-groups"
        try:
            self.session.post(url, json={"productIds": product_ids, "groupName": tag_name})
            return True
        except: return False

    # --- 핵심 처리 로직 ---
    def find_all_grouped_products(self, original_product_url: str) -> List[dict]:
        id_match = re.search(r'id=(\d+)', original_product_url)
        product_no = id_match.group(1) if id_match else ""
        if not product_no: return []
        filter_model = {"product_url": {"filterType": "text", "type": "contains", "filter": product_no}}
        try:
            products, _ = self.get_products(start_row=0, end_row=50, filter_model=filter_model)
            return products
        except: return []

    def measure_shipping_cost(self, thumbnails: List[str], product_name: str) -> Optional[int]:
        print(f"🧠 AI 분석 중... ({product_name[:20]})")
        payload = {"imageUrl": "\n".join(thumbnails), "keywords": f"상품명: {product_name}"}
        try:
            response = self.session.post(AI_API_URL, json=payload)
            data = response.json()
            if data.get("success"):
                cost_val = data.get("data", {}).get("cost_calculation", {}).get("base_shipping_cost", "0")
                return int(re.sub(r'[^0-9]', '', str(cost_val)))
            return None
        except: return None

    def update_shipping_fee_via_api(self, product_id: str, detail_data: dict, new_fee: int):
        url = f"{self.BASE_URL}/sourcing/uploadfields/{product_id}"
        detail_data["uploadOverseaDeliveryFee"] = new_fee
        try:
            self.session.put(url, json=detail_data).raise_for_status()
            return True
        except: return False

    def process_single_product(self, product_id: str, product_name: str, force_update_fee: int = None) -> Optional[int]:
        if product_id in self.processed_ids and force_update_fee is None: return None
        try:
            detail_res = self.get_product_detail(product_id)
            if not detail_res or not detail_res.get("success"): return None
            p_data = detail_res["data"]
            
            # 스마트 필터: 0원인 것만 처리
            current_fee = p_data.get("uploadOverseaDeliveryFee", 0)
            if self.smart_filter and current_fee > 0 and force_update_fee is None:
                print(f"⏭️ 배송비가 이미 설정됨({current_fee}원) -> 건너뜀")
                return None

            new_fee = force_update_fee
            if new_fee is None:
                thumbnails = p_data.get("uploadThumbnails", [])
                if not thumbnails: return None
                new_fee = self.measure_shipping_cost(thumbnails, product_name)
                if new_fee is None: return None
            
            if self.update_shipping_fee_via_api(product_id, p_data, new_fee):
                print(f"✅ {'일괄 ' if force_update_fee else ''}업데이트: {product_id} ({current_fee}원 -> {new_fee}원)")
                self.processed_ids.add(product_id)
                self.save_processed_log()
                
                # 리포트 데이터 추가
                self.report_data.append({
                    "product_id": product_id,
                    "product_name": product_name,
                    "before_fee": current_fee,
                    "after_fee": new_fee,
                    "mode": "Bulk" if force_update_fee else "Single/Auto"
                })

                if force_update_fee is None:
                    product_url = p_data.get("product_url", "")
                    if product_url:
                        grouped = self.find_all_grouped_products(product_url)
                        for gp in grouped:
                            gp_id = gp.get("ID") or gp.get("id")
                            if gp_id and gp_id != product_id and gp_id not in self.processed_ids:
                                self.process_single_product(gp_id, product_name, force_update_fee=new_fee)
                return new_fee
        except Exception as e: print(f"❌ 오류 ({product_id}): {e}")
        return None

    def run_bulk_ids(self, id_list: List[str]):
        """입력된 대량의 ID 리스트를 순차 처리"""
        print(f"🚀 대량 ID 처리 작업 시작 (총 {len(id_list)}개)")
        count = 0
        for pid in id_list:
            if self.stop_requested: break
            if pid in self.processed_ids: continue
            
            # 간이 이름으로 처리 시도
            if self.process_single_product(pid, "대량입력상품"):
                count += 1
            time.sleep(1)
        self.write_report()
        print(f"\n🏁 대량 처리 종료 (총 {count}개 완료)")

    def run_sequential(self, group_names: List[str], max_per_group: int, auto_tag: str = ""):
        print(f"🚀 그룹 순차 작업 시작: 선택 {len(group_names)}개")
        for gname in group_names:
            if self.stop_requested: break
            print(f"\n📂 [그룹] {gname}")
            filter_model = {"marketGroupName": {"filterType": "text", "type": "equals", "filter": gname}}
            products, _ = self.get_products(start_row=0, end_row=max_per_group * 5, filter_model=filter_model)
            
            processed_in_group = []
            count = 0
            for p in products:
                if self.stop_requested or count >= max_per_group: break
                pid = p.get("ID") or p.get("id")
                pname = p.get("productName") or p.get("name", "Unknown")
                if not pid or pid in self.processed_ids: continue
                
                print(f"📦 [{count+1}] 분석: {pname[:20]}")
                if self.process_single_product(pid, pname):
                    processed_in_group.append(pid)
                    count += 1
                time.sleep(1)
            
            if auto_tag and processed_in_group:
                self.apply_tag_to_products(processed_in_group, auto_tag)
                
        self.write_report()
        print("\n🏁 전 그룹 순차 작업 종료")

# ==================== GUI 클래스 (대량 자동화 특화) ====================
class AIShippingGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("불사자 AI 배송비 마스터 v1.3 (Bulk Automation)")
        self.root.geometry("1000x850")
        self.root.configure(bg="#f0f2f5")
        
        self.is_running = False
        self.updater = None
        self.setup_ui()
        
    def setup_ui(self):
        # 헤더
        header = tk.Frame(self.root, bg="#2c3e50", height=60)
        header.pack(fill=tk.X)
        tk.Label(header, text="BULSAJA AI SHIPPING MASTER", fg="white", bg="#2c3e50", 
                 font=("Pretendard", 16, "bold")).pack(pady=15)

        # 메인 컨테이너
        main_body = tk.Frame(self.root, bg="#f0f2f5")
        main_body.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # 좌측: 설정 및 입력
        left_panel = tk.Frame(main_body, bg="#f0f2f5", width=380)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        # [1] 스마트 필터 설정
        filter_frame = tk.LabelFrame(left_panel, text=" 스마트 필터 ", font=("Malgun Gothic", 10, "bold"), bg="white", padx=10, pady=10)
        filter_frame.pack(fill=tk.X, pady=(0, 10))
        self.smart_filter_var = tk.BooleanVar(value=True)
        tk.Checkbutton(filter_frame, text="기존 배송비가 0원인 상품만 처리 (권장)", 
                       variable=self.smart_filter_var, bg="white").pack(anchor=tk.W)

        # [2] 대량 ID 입력 모드 (핵심 기능)
        bulk_frame = tk.LabelFrame(left_panel, text=" [모드1] 대량 ID 리스트 입력 ", font=("Malgun Gothic", 10, "bold"), bg="white", padx=10, pady=10)
        bulk_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        tk.Label(bulk_frame, text="처리할 불사자 상품 ID들을 붙여넣으세요:", bg="white", fg="#666").pack(anchor=tk.W)
        self.id_text_area = scrolledtext.ScrolledText(bulk_frame, height=15, font=("Consolas", 10), borderwidth=1, relief="solid")
        self.id_text_area.pack(fill=tk.BOTH, expand=True, pady=5)
        self.bulk_start_btn = tk.Button(bulk_frame, text="대량 입력 작업 시작", bg="#3498db", fg="white", 
                                      font=("Malgun Gothic", 11, "bold"), command=self.start_bulk)
        self.bulk_start_btn.pack(fill=tk.X, pady=5, ipady=8)

        # [3] 그룹 순차 모드
        group_frame = tk.LabelFrame(left_panel, text=" [모드2] 전체 그룹 순회 ", font=("Malgun Gothic", 10, "bold"), bg="white", padx=10, pady=10)
        group_frame.pack(fill=tk.X, pady=10)
        self.group_listbox = tk.Listbox(group_frame, height=5, selectmode=tk.MULTIPLE)
        self.group_listbox.pack(fill=tk.X, pady=5)
        ttk.Button(group_frame, text="그룹 리스트 새로고침", command=self.refresh_groups).pack(fill=tk.X)
        self.group_start_btn = tk.Button(group_frame, text="선택 그룹 전체 순회 시작", bg="#2ecc71", fg="white",
                                       font=("Malgun Gothic", 11, "bold"), command=self.start_sequential)
        self.group_start_btn.pack(fill=tk.X, pady=5, ipady=8)

        # 우측: 로그 및 조작
        right_panel = tk.Frame(main_body, bg="#f0f2f5")
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # 조작 버튼 (크롬 실행, 중지)
        top_ctrl = tk.Frame(right_panel, bg="#f0f2f5")
        top_ctrl.pack(fill=tk.X, pady=(0, 10))
        tk.Button(top_ctrl, text="🌐 크롬 디버그 실행", bg="#95a5a6", fg="white", command=self.open_chrome_debug, width=20).pack(side=tk.LEFT, padx=5)
        self.stop_btn = tk.Button(top_ctrl, text="🛑 작업 강제 중단", bg="#e74c3c", fg="white", state=tk.DISABLED, command=self.stop_task, width=20)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.log_area = scrolledtext.ScrolledText(right_panel, bg="#1e1e1e", fg="#00FF41", font=("Consolas", 10))
        self.log_area.pack(fill=tk.BOTH, expand=True)

        self.log("🚀 대량 자동화 전용 v1.3 버전이 준비되었습니다.")
        self.log("💡 [모드1]에 수백 개의 ID를 붙여넣고 시작을 눌러보세요.")

    def log(self, message: str):
        ts = time.strftime("[%H:%M] ")
        self.log_area.insert(tk.END, ts + message + "\n")
        self.log_area.see(tk.END)

    def open_chrome_debug(self):
        paths = [r"C:\Program Files\Google\Chrome\Application\chrome.exe", 
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]
        chrome_path = next((p for p in paths if os.path.exists(p)), None)
        if not chrome_path: return messagebox.showerror("오류", "크롬을 찾을 수 없습니다.")
        subprocess.Popen(f'"{chrome_path}" --remote-debugging-port=9222 --user-data-dir="C:/temp/chrome_debug"', shell=True)
        webbrowser.open("https://www.bulsaja.com")
        self.log("🌐 크롬 디버그 모드 실행 완료.")

    def refresh_groups(self):
        threading.Thread(target=self._refresh_groups_thread, daemon=True).start()

    def _refresh_groups_thread(self):
        self.log("🔄 그룹 목록 로딩 중...")
        try:
            temp = BulsajaAIShippingUpdater()
            tags = temp.get_existing_tags()
            self.group_listbox.delete(0, tk.END)
            for t in tags: self.group_listbox.insert(tk.END, t)
            self.log(f"✅ {len(tags)}개 그룹 발견")
        except: self.log("❌ 그룹 로딩 실패 (크롬 포트를 확인하세요)")

    def start_bulk(self):
        raw_text = self.id_text_area.get(1.0, tk.END).strip()
        ids = [i.strip() for i in re.split(r'[\s,]+', raw_text) if i.strip()]
        if not ids: return messagebox.showwarning("주의", "상품 ID들을 입력해주세요.")
        
        self._toggle_ui(True)
        threading.Thread(target=lambda: self.run_wrapper(lambda: self.updater.run_bulk_ids(ids)), daemon=True).start()

    def start_sequential(self):
        indices = self.group_listbox.curselection()
        if not indices: return messagebox.showwarning("주의", "그룹을 선택하세요.")
        selected = [self.group_listbox.get(i) for i in indices]
        
        self._toggle_ui(True)
        threading.Thread(target=lambda: self.run_wrapper(
            lambda: self.updater.run_sequential(selected, 100, "배송비완료")
        ), daemon=True).start()

    def stop_task(self):
        if self.updater: self.updater.stop_requested = True
        self.log("🛑 중단 요청 중...")

    def run_wrapper(self, action):
        original_print = builtins.print
        try:
            self.updater = BulsajaAIShippingUpdater()
            self.updater.smart_filter = self.smart_filter_var.get()
            builtins.print = lambda *a, **k: self.log(" ".join(map(str, a)))
            action()
        except Exception as e: self.log(f"❌ 오류: {e}")
        finally:
            builtins.print = original_print
            self.is_running = False
            self.root.after(0, lambda: self._toggle_ui(False))
            self.log("🏁 모든 프로세스 종료.")

    def _toggle_ui(self, running: bool):
        state = tk.DISABLED if running else tk.NORMAL
        self.bulk_start_btn.config(state=state)
        self.group_start_btn.config(state=state)
        self.stop_btn.config(state=tk.NORMAL if running else tk.DISABLED)
        self.is_running = running

if __name__ == "__main__":
    root = tk.Tk()
    app = AIShippingGUI(root)
    root.mainloop()
