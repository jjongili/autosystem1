#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
배송상태 조회 모듈
- 구글 시트 연동
- 택배사 API 조회
- 배경색 업데이트
"""

import os
from pathlib import Path
import asyncio
from datetime import datetime
from typing import Dict, List

import gspread
import requests
from google.oauth2.service_account import Credentials


print("\n📦 [MODULE] delivery_check module IMPORTED/RELOADED 📦\n")

# 택배사 코드 매핑
CARRIER_CODES = {
    'CJ대한통운': 'kr.cjlogistics',
    'CJ': 'kr.cjlogistics',
    '대한통운': 'kr.cjlogistics',
    '한진': 'kr.hanjin',
    '한진택배': 'kr.hanjin',
    '우체국': 'kr.epost',
    '우체국택배': 'kr.epost',
    '투데이': 'kr.todaypickup',
    '투데이익스프레스': 'kr.todaypickup',
    '경동': 'kr.kdexp',
    '경동택배': 'kr.kdexp',
    '로젠': 'kr.logen',
    '롯데': 'kr.lotte',
    '롯데택배': 'kr.lotte'
}


class DeliveryChecker:
    """배송상태 조회기"""
    
    def __init__(self, credentials_path: str = None):
        # 기본 경로: 상위 폴더(web_system)의 JSON 파일
        default_path = str(Path(__file__).resolve().parent.parent / "autosms-466614-951e91617c69.json")
        self.credentials_path = credentials_path or default_path
        
        self.status = {
            "running": False,
            "progress": 0,
            "total": 0,
            "current": "",
            "logs": [],
            "updated": 0
        }
    
    def add_log(self, msg: str):
        """로그 추가"""
        self.status["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        if len(self.status["logs"]) > 100:
            self.status["logs"] = self.status["logs"][-100:]
        print(f"[배송] {msg}")
    
    def get_tracking_info(self, carrier_name: str, tracking_no: str) -> Dict:
        """배송 조회 API 호출"""
        if not carrier_name or not str(carrier_name).strip():
            carrier_name = 'CJ대한통운'
        
        carrier_code = CARRIER_CODES.get(carrier_name)
        if not carrier_code:
            return {"success": False, "error": f"지원하지 않는 택배사: {carrier_name}"}
        
        tracking_no = str(tracking_no).replace(" ", "").replace("-", "")
        url = f"https://apis.tracker.delivery/carriers/{carrier_code}/tracks/{tracking_no}"
        
        try:
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                return {"success": False, "error": f"API 오류: {response.status_code}"}
            
            data = response.json()
            
            # [수정] ID 및 텍스트 교차 검증
            state_id = data.get("state", {}).get("id", "")
            
            # 텍스트 정보 추출
            progresses = data.get("progresses", [])
            full_text = ""
            if progresses:
                last_step = progresses[-1]
                status_text = str(last_step.get("status", {}).get("text", "") or "")
                desc = str(last_step.get("description", "") or "")
                full_text = (status_text + desc).replace(" ", "")

                last_time = last_step.get("time")

                # [디버그 추가] 서버 코드 갱신 확인용
                if "519170617545" in str(tracking_no):
                    msg = f"🕵️ [TIME_CHECK] ID:{state_id} Time:{last_time}"
                    self.add_log(msg)
                    print(msg, flush=True)

            # [수정] 중요: 타임스탬프(시간)가 없으면 실제 이동 내역이 아님 (가송장 등)
            if not last_time:
                return {"success": False, "error": f"이동 내역 시간 없음 ({state_id})"}

            # 유효 상태 ID
            valid_states = ["at_pickup", "in_transit", "out_for_delivery", "delivered"]
            
            # 제외 키워드 (단순 접수/준비 단계)
            exclude_keywords = ["예정", "신청", "출력", "등록", "준비", "대기", "미등록", "접수"]
            # 배송 확실 키워드
            confirm_keywords = ["집화", "인수", "이동", "간선", "상차", "하차", "도착", "출발", "배달", "배송", "입고", "출고"]

            # 1. 상태 ID가 유효한 경우
            if state_id in valid_states:
                # 2. 텍스트가 '준비중'스럽다면 무효화
                if any(e in full_text for e in exclude_keywords):
                    if not any(c in full_text for c in confirm_keywords):
                        return {"success": False, "error": f"상태({state_id})이나 내용이 준비중임: {full_text}"}
                
                return {"success": True, "data": data}
                
            # 3. 상태 ID는 애매하지만 텍스트에 확실한 배송 키워드가 있는 경우
            if any(c in full_text for c in confirm_keywords) and not any(e in full_text for e in exclude_keywords):
                return {"success": True, "data": data}

            return {"success": False, "error": f"배송 시작 전 (필터링됨) State: {state_id}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def run_check(self, sheet_id: str, sheet_name: str, carrier_col: int, tracking_col: int, start_row: int):
        """배송조회 실행"""
        self.status = {
            "running": True,
            "progress": 0,
            "total": 0,
            "current": "",
            "logs": [],
            "updated": 0
        }
        
        try:
            self.add_log(f"시트 연결 중: {sheet_name}")
            
            if not os.path.exists(self.credentials_path):
                self.add_log(f"인증 파일 없음: {self.credentials_path}")
                self.status["running"] = False
                return
            
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            creds = Credentials.from_service_account_file(self.credentials_path, scopes=scopes)
            gc = gspread.authorize(creds)
            
            spreadsheet = gc.open_by_key(sheet_id)
            ws = spreadsheet.worksheet(sheet_name)
            self.add_log(f"시트 연결 성공: {spreadsheet.title}")
            
            all_values = ws.get_all_values()
            if len(all_values) < start_row:
                self.add_log("조회할 데이터가 없습니다")
                self.status["running"] = False
                return
            
            # 배경색 가져오기 (노란색이면 스킵)
            yellow_rows = set()
            try:
                if tracking_col <= 26:
                    col_letter = chr(64 + tracking_col)
                else:
                    col_letter = chr(64 + (tracking_col - 1) // 26) + chr(65 + (tracking_col - 1) % 26)
                
                bg_range = f"{col_letter}{start_row}:{col_letter}{len(all_values)}"
                
                from google.auth.transport.requests import Request
                
                if creds.expired:
                    creds.refresh(Request())
                
                url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}?ranges={sheet_name}!{bg_range}&fields=sheets.data.rowData.values.effectiveFormat.backgroundColor"
                headers = {"Authorization": f"Bearer {creds.token}"}
                
                resp = requests.get(url, headers=headers, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    sheets_data = data.get("sheets", [])
                    if sheets_data:
                        row_data = sheets_data[0].get("data", [{}])[0].get("rowData", [])
                        for idx, row in enumerate(row_data):
                            values = row.get("values", [{}])
                            if values:
                                bg = values[0].get("effectiveFormat", {}).get("backgroundColor", {})
                                r = bg.get("red", 0)
                                g = bg.get("green", 0)
                                b = bg.get("blue", 0)
                                if r >= 0.9 and g >= 0.9 and b <= 0.1:
                                    yellow_rows.add(start_row + idx)
                    
                    self.add_log(f"이미 노란색: {len(yellow_rows)}건 스킵")
            except Exception as e:
                self.add_log(f"배경색 조회 실패: {e}")
            
            # 조회 대상 찾기
            targets = []
            skipped = 0
            au_yellow_rows = []
            AU_COL = 47
            
            for i in range(start_row - 1, len(all_values)):
                row_num = i + 1
                
                if row_num in yellow_rows:
                    skipped += 1
                    continue
                
                row = all_values[i]
                
                if len(row) >= AU_COL:
                    au_value = row[AU_COL - 1] if len(row) >= AU_COL else ""
                    if au_value and str(au_value).strip():
                        au_yellow_rows.append(row_num)
                
                if len(row) >= tracking_col:
                    carrier = row[carrier_col - 1] if len(row) >= carrier_col else ""
                    tracking_no = row[tracking_col - 1] if len(row) >= tracking_col else ""
                    
                    if tracking_no and str(tracking_no).strip():
                        targets.append({
                            "row": row_num,
                            "carrier": carrier,
                            "tracking_no": str(tracking_no).strip()
                        })
            
            # AU열 값 있는 행 노란색 색칠 (사용자 분노로 비활성화 - 원인 가능성 차단)
            if au_yellow_rows:
                self.add_log(f"AU열 값 있는 행 {len(au_yellow_rows)}건 발견 (색칠 스킵)")
                # for row_num in au_yellow_rows:
                #     try:
                #         ws.format(f"AQ{row_num}:AR{row_num}", {
                #             "backgroundColor": {"red": 1, "green": 1, "blue": 0}
                #         })
                #     except Exception as e:
                #         self.add_log(f"AQ,AR 색칠 오류 (행 {row_num}): {e}")
                #     await asyncio.sleep(0.05)
            
            self.add_log(f"총 {len(targets)}건 조회 (스킵: {skipped}건)")
            self.status["total"] = len(targets)
            
            if len(targets) == 0:
                self.add_log("조회할 송장이 없습니다")
                self.status["running"] = False
                return
            
            # 배송 조회
            updates = []
            clears = [] # [추가] 초기화
            for i, target in enumerate(targets):
                if not self.status["running"]:
                    self.add_log("사용자에 의해 중지됨")
                    break
                
                self.status["progress"] = i + 1
                self.status["current"] = f"{target['tracking_no']} ({target['carrier'] or 'CJ대한통운'})"
                
                result = self.get_tracking_info(target["carrier"], target["tracking_no"])
                
                if result["success"]:
                    updates.append(target["row"])
                    self.status["updated"] += 1
                    self.add_log(f"✅ {target['tracking_no']} - 배송중(CodeActive)")
                else:
                    # [추가] 시간이 없어서 실패한 경우(가송장) -> 기존 색상을 지워야 함(흰색으로 변경)
                    if "시간 없음" in result.get("error", ""):
                        clears.append(target["row"])
                
                await asyncio.sleep(0.3)
            
            # 1. 배경색 업데이트 (배송중 -> 노란색 복구)
            if updates:
                self.add_log(f"배송중 색상 적용 중: {len(updates)}건")
                carrier_col_letter = chr(64 + carrier_col) if carrier_col <= 26 else f"{chr(64 + carrier_col // 26)}{chr(65 + (carrier_col - 1) % 26)}"
                tracking_col_letter = chr(64 + tracking_col) if tracking_col <= 26 else f"{chr(64 + tracking_col // 26)}{chr(65 + (tracking_col - 1) % 26)}"
                
                for row_num in updates:
                    try:
                        # 노란색: {"red": 1, "green": 1, "blue": 0}
                        ws.format(f"{carrier_col_letter}{row_num}:{tracking_col_letter}{row_num}", {
                            "backgroundColor": {"red": 1, "green": 1, "blue": 0}
                        })
                    except Exception as e:
                        self.add_log(f"배경색 설정 오류 (행 {row_num}): {e}")
                    await asyncio.sleep(0.1)

            # 2. 배경색 지우기 (가송장 -> 흰색)
            if clears:
                self.add_log(f"가송장 색상 초기화 중(흰색): {len(clears)}건")
                carrier_col_letter = chr(64 + carrier_col) if carrier_col <= 26 else f"{chr(64 + carrier_col // 26)}{chr(65 + (carrier_col - 1) % 26)}"
                tracking_col_letter = chr(64 + tracking_col) if tracking_col <= 26 else f"{chr(64 + tracking_col // 26)}{chr(65 + (tracking_col - 1) % 26)}"
                
                for row_num in clears:
                    try:
                        # 흰색: {"red": 1, "green": 1, "blue": 1}
                        ws.format(f"{carrier_col_letter}{row_num}:{tracking_col_letter}{row_num}", {
                            "backgroundColor": {"red": 1, "green": 1, "blue": 1}
                        })
                    except Exception as e:
                        self.add_log(f"배경색 초기화 오류 (행 {row_num}): {e}")
                    await asyncio.sleep(0.1)
            
            self.add_log(f"완료! 배송중(노란색): {len(updates)}건, 초기화(흰색): {len(clears)}건")
            
        except Exception as e:
            self.add_log(f"오류: {e}")
            import traceback
            traceback.print_exc()
        
        self.status["running"] = False
        self.status["current"] = ""
    
    async def start_check(self, sheet_id: str, sheet_name: str, carrier_col: int = 43, tracking_col: int = 44, start_row: int = 4) -> Dict:
        """배송조회 시작"""
        if not sheet_id or not sheet_name:
            return {"success": False, "message": "시트 정보가 필요합니다"}
        
        if self.status["running"]:
            return {"success": False, "message": "이미 실행 중입니다"}
        
        # 백그라운드로 실행
        asyncio.create_task(self.run_check(sheet_id, sheet_name, carrier_col, tracking_col, start_row))
        
        return {"success": True, "message": "배송조회 시작"}
    
    def stop_check(self) -> Dict:
        """배송조회 중지"""
        self.status["running"] = False
        return {"success": True}
    
    def get_status(self) -> Dict:
        """상태 조회"""
        return self.status


# 전역 인스턴스
delivery_checker = DeliveryChecker()
