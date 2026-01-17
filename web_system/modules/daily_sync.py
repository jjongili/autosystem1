import os
import re
import pandas as pd
import gspread
from gspread import Cell
import traceback
import time
from pathlib import Path
from google.oauth2.service_account import Credentials
from collections import defaultdict
import datetime

class DailyJournalSyncer:
    def __init__(self, credentials_path):
        self.credentials_path = credentials_path

    def run_sync(self, sheet_url, month, source_data, log_callback, update_state_callback):
        """
        일일장부 동기화 메인 로직 (날짜 필터링 강화판)
        """
        def add_log(msg, type="info"):
            log_callback(msg, type)

        try:
            # 1. 시트 연결
            sheet_id = sheet_url
            if 'docs.google.com' in sheet_id:
                match = re.search(r'/d/([a-zA-Z0-9_-]+)', sheet_id)
                if match:
                    sheet_id = match.group(1)
            
            if not os.path.exists(self.credentials_path):
                add_log(f"인증 파일 없음: {self.credentials_path}", "error")
                update_state_callback("status", "error")
                return

            scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
            sync_creds = Credentials.from_service_account_file(self.credentials_path, scopes=scopes)
            sync_client = gspread.authorize(sync_creds)
            
            upload_sheet = sync_client.open_by_key(sheet_id)
            ws = upload_sheet.worksheet(month)
            add_log(f"시트 연결 성공: {upload_sheet.title} / {month}")

        except Exception as e:
            add_log(f"시트 연결 실패: {e}", "error")
            update_state_callback("status", "error")
            return

        # 2. 소스 데이터 로드
        df_source = None
        if isinstance(source_data, pd.DataFrame):
            df_source = source_data
        else:
            try:
                df_source = pd.read_excel(source_data)
            except Exception as e:
                add_log(f"엑셀 로드 실패: {e}", "error")
                return

        add_log(f"데이터 로드: {len(df_source)}건")

        # 3. 상수 및 컬럼 정의
        SHEET_KEY_COL = 9    # I열 (주문번호)
        SHEET_STATUS_COL = 4 # D열 (주문현황)
        SHEET_START_COL = 3  # C열 (매핑 시작 위치)
        SHEET_DATA_LIMIT_COL = 59 # BG열
        
        STATUS_KEYWORDS = ["취소", "반품", "배송완료", "구매확정"]

        def find_src_col(names):
            for col in df_source.columns:
                c_clean = str(col).replace('\n', ' ').strip().replace(' ', '')
                for name in names:
                    if name.replace(' ', '') in c_clean:
                        return col
            return None

        src_col_order_id = find_src_col(["주문번호", "고객 주문 번호", "해외오더넘버"])
        if not src_col_order_id:
            add_log("엑셀에서 주문번호 컬럼을 찾을 수 없습니다.", "error")
            update_state_callback("status", "error")
            return

        # 날짜 컬럼 찾기 (더 많은 후보)
        DATE_CANDIDATES = [
            "해외 주문일", "해외주문일", "발주일자", "주문일자", "주문일", "주문날짜", "주문 일자",
            "Date", "Order Date", "OrderDate", "결제일", "결제일자", "구매일", "구매일자", "날짜"
        ]
        src_col_date = find_src_col(DATE_CANDIDATES)

        # 타겟 월 추출
        try:
            target_month_int = int(re.sub(r'[^0-9]', '', month))
            add_log(f"타겟 월: {target_month_int}월")
        except:
            target_month_int = None
            add_log("시트 이름에서 월 정보를 찾을 수 없어 전체 데이터를 처리합니다.", "warning")

        # 날짜 컬럼 필수 체크 (월 필터링을 위해)
        if target_month_int and not src_col_date:
            add_log(f"중단: '{month}' 시트에 맞는 데이터를 걸러내야 하는데, 엑셀에서 날짜 컬럼을 찾을 수 없습니다.", "error")
            add_log(f"확인된 엑셀 컬럼들: {list(df_source.columns)}", "info")
            update_state_callback("status", "error")
            return

        def normalize_order_id(val):
            if pd.isna(val): return ""
            s = str(val).strip()
            if s.endswith('.0'): s = s[:-2]
            return s

        def normalize_date_str(val):
            # 문자열로 반환 (YYYY-MM-DD)
            try:
                dt = pd.to_datetime(val, errors='coerce')
                if pd.notnull(dt):
                    return dt.strftime("%Y-%m-%d")
            except: pass
            return str(val).strip()

        # 소스 맵 생성 (날짜 필터링 적용)
        source_map = {}
        filtered_out_count = 0
        
        for _, row in df_source.iterrows():
            oid = normalize_order_id(row[src_col_order_id])
            if not oid or oid == "-" or "없음" in oid or "정보" in oid: continue
            
            # 날짜 필터링
            if target_month_int and src_col_date:
                val_date = row[src_col_date]
                dt = pd.to_datetime(val_date, errors='coerce')
                if pd.notnull(dt):
                    if dt.month != target_month_int:
                        filtered_out_count += 1
                        continue
                else:
                    # 날짜 파싱 실패 시, 안전하게 제외? 아니면 경고?
                    # 일단 로그 없이 제외 (데이터 품질 이슈)
                    # 하지만 정말 중요한 데이터일 수 있으므로...
                    # '20251215' 같은 문자열 처리 시도
                    s_date = str(val_date).replace('-', '').replace('.', '').strip()
                    if s_date.isdigit() and len(s_date) >= 6:
                        m = -1
                        if len(s_date) == 8: m = int(s_date[4:6])
                        elif len(s_date) == 6: m = int(s_date[2:4])
                        
                        if m != -1 and m != target_month_int:
                            filtered_out_count += 1
                            continue
            
            source_map[oid] = row

        add_log(f"데이터 로드 완료: {len(source_map)}건 (타겟 월 불일치로 {filtered_out_count}건 제외됨)")

        # 4. 시트 데이터 읽기
        try:
            all_rows = ws.get_all_values()
        except:
            add_log("시트 읽기 실패", "error")
            return

        gs_data_rows = all_rows[3:] 
        
        # 5. 기존 데이터 업데이트 (Phase 1)
        cells_to_update = []
        updated_count = 0
        
        # 날짜별 마지막 행 인덱스 맵
        date_last_row_map = {} 
        
        # 시트의 날짜 컬럼 찾기
        gs_headers = ws.row_values(2) if ws.row_count >= 2 else []
        # 헤더 정규화 함수 (줄바꿈, 공백 모두 제거)
        def normalize_header(h):
            return re.sub(r'\s+', '', str(h))

        def find_gs_col_idx(names):
            for i, h in enumerate(gs_headers):
                h_clean = normalize_header(h)
                for n in names:
                    if normalize_header(n) in h_clean:
                        return i + 1
            return 6 # 기본값 F열

        sheet_date_col = find_gs_col_idx(["발주일자", "주문일자"])
        src_columns = list(df_source.columns) 

        for i, row in enumerate(gs_data_rows):
            row_num = i + 4
            
            gs_order_id = ""
            if len(row) >= SHEET_KEY_COL:
                gs_order_id = normalize_order_id(row[SHEET_KEY_COL-1])
            
            if len(row) >= sheet_date_col:
                d_val = normalize_date_str(row[sheet_date_col-1])
                if d_val: date_last_row_map[d_val] = row_num

            if gs_order_id and gs_order_id in source_map:
                src_row = source_map[gs_order_id]
                row_updated = False

                # 현재 구글시트 상태 확인
                current_gs_status = ""
                if len(row) >= SHEET_STATUS_COL:
                    current_gs_status = row[SHEET_STATUS_COL-1].strip()

                # 최종 상태 목록 (이 상태들은 오버라이트 금지)
                FINAL_STATUSES = ["취소완료", "배송완료", "반품요청", "반품완료"]
                is_final_status = current_gs_status in FINAL_STATUSES

                # 1) 상태 오버라이트 (단, 최종 상태인 경우 제외)
                if not is_final_status:
                    src_status = ""
                    status_col_name = find_src_col(["주문현황", "주문상태", "상태"])
                    if status_col_name:
                        src_status = str(src_row[status_col_name]).strip()

                    # [매핑] 반품 -> 취소완료
                    if "반품" in src_status:
                        src_status = "취소완료"
                    # [매핑] 취소 처리 완료 -> 취소완료
                    elif "취소 처리 완료" in src_status:
                        src_status = "취소완료"
                    # [매핑] 구매확정 -> 배송완료로 변경 (사용자 요청)
                    elif "구매확정" in src_status:
                        src_status = "배송완료"

                    if any(kw in src_status for kw in STATUS_KEYWORDS):
                        # 값이 다를 때만 업데이트
                        if src_status != current_gs_status:
                            cells_to_update.append(Cell(row_num, SHEET_STATUS_COL, src_status))
                            row_updated = True

                # 2) 빈 칸 채우기 + 특정 값 오버라이트 (최종 상태면 건너뛰기)
                if is_final_status:
                    # 최종 상태(취소완료/배송완료/반품요청/반품완료)는 오버라이트 금지
                    if row_updated: updated_count += 1
                    continue

                # 먼저 엑셀에서 택배사 값 확인 (경동택배면 전체 오버라이트)
                src_courier_col = find_src_col(["택배사", "배송업체", "배송사"])
                src_courier_val = ""
                if src_courier_col:
                    src_courier_val = str(src_row[src_courier_col]).strip() if pd.notnull(src_row[src_courier_col]) else ""
                is_kyungdong = "경동" in src_courier_val

                for src_idx, src_col in enumerate(src_columns):
                    target_col = SHEET_START_COL + src_idx
                    if target_col > SHEET_DATA_LIMIT_COL: break

                    try:
                        current_val = row[target_col-1].strip() if len(row) >= target_col else ""
                    except: current_val = ""

                    # 컬럼명 정규화 (줄바꿈, 공백 모두 제거)
                    src_col_clean = str(src_col).replace(' ', '').replace('\n', '').strip()

                    # 오버라이트 조건 확인
                    should_overwrite = False

                    # 1) 빈 값이면 무조건 채우기
                    if not current_val:
                        should_overwrite = True

                    # 2) "해외주문 정보 없음"이면 오버라이트
                    elif current_val == "해외주문 정보 없음":
                        should_overwrite = True

                    # 3) 국제배송비 컬럼이고 값이 0이면 오버라이트
                    elif ('국제배송비' in src_col_clean or '해외배송비' in src_col_clean) and current_val == "0":
                        should_overwrite = True

                    # 4) 택배사가 경동택배면 무조건 오버라이트
                    elif is_kyungdong:
                        should_overwrite = True

                    if should_overwrite:
                        new_val = src_row[src_col]
                        if pd.notnull(new_val):
                            val_str = str(new_val).strip()
                            if val_str in ["주문수량", "해외주문 정보 없음", "nan"]: val_str = ""
                            if val_str.endswith('.0') and val_str[:-2].replace('-','').isdigit(): val_str = val_str[:-2]

                            # 값이 있고, 현재 값과 다를 때만 업데이트
                            if val_str and val_str != current_val:
                                cells_to_update.append(Cell(row_num, target_col, val_str))
                                row_updated = True
                
                if row_updated: updated_count += 1
                
                if len(cells_to_update) >= 500:
                    ws.update_cells(cells_to_update, value_input_option='USER_ENTERED')
                    cells_to_update = []
                    time.sleep(1)

        if cells_to_update:
            ws.update_cells(cells_to_update, value_input_option='USER_ENTERED')
            add_log(f"기존 주문 업데이트 완료: {updated_count}건")


        # 6. 신규 주문 추가 (Phase 2)
        existing_ids = set()
        for r in gs_data_rows:
            if len(r) >= SHEET_KEY_COL:
                gid = normalize_order_id(r[SHEET_KEY_COL-1])
                if gid: existing_ids.add(gid)

        new_items = []
        for oid, src_row in source_map.items():
            if oid not in existing_ids:
                new_items.append((oid, src_row))

        if not new_items:
            add_log("신규 추가할 주문이 없습니다.")
            update_state_callback("status", "completed")
            return

        add_log(f"신규 주문 {len(new_items)}건 발견. 마지막 행 계산 중...")

        # [수정] 실제 데이터가 있는 마지막 행 찾기 (빈 행 무시)
        real_last_row = 0
        for i, row in enumerate(all_rows):
            # 행 번호 (1-based)
            row_num = i + 1
            # 데이터 존재 여부 확인 (주문번호(I열) 또는 주문일자(F열) 확인)
            # SHEET_KEY_COL = 9 (I열)
            has_data = False
            if len(row) >= SHEET_KEY_COL and str(row[SHEET_KEY_COL-1]).strip():
                has_data = True
            elif len(row) >= 6 and str(row[5]).strip(): # 6번째(F열, 날짜)
                has_data = True
            
            if has_data:
                real_last_row = row_num
        
        # 헤더가 3행까지 있으므로 최소 3행 보장
        real_last_row = max(real_last_row, 3)
        add_log(f"실제 마지막 데이터 행: {real_last_row}")

        start_row = real_last_row + 1
        
        # 추가할 데이터 구성
        sheet_rows_to_append = []
        for oid, src_row in new_items:
            new_row = [""] * SHEET_DATA_LIMIT_COL # BG열(59)까지
            
            # 컬럼 매핑 채우기
            for idx, col_name in enumerate(src_columns):
                target_c = SHEET_START_COL + idx
                if target_c > SHEET_DATA_LIMIT_COL: break
                
                val = src_row[col_name]
                if pd.notnull(val):
                    val_str = str(val).strip()
                    if val_str in ["주문수량", "해외주문 정보 없음", "nan"]: val_str = ""
                    if val_str.endswith('.0') and val_str[:-2].replace('-','').isdigit(): val_str = val_str[:-2]
                    
                    # 주문현황 컬럼 특별 처리
                    col_name_clean = str(col_name).replace(' ', '').replace('\n', '').strip()
                    if '주문현황' in col_name_clean or '주문상태' in col_name_clean:
                        # 반품 -> 취소완료 매핑
                        if "반품" in val_str:
                            val_str = "취소완료"
                        # 취소 처리 완료 -> 취소완료 매핑
                        elif "취소 처리 완료" in val_str:
                            val_str = "취소완료"
                        # 특정 키워드가 없으면 빈 값으로
                        valid_keywords = ['취소', '반품', '구매확정', '배송완료', '취소완료']
                        if not any(kw in val_str for kw in valid_keywords):
                            val_str = ""  # 의미 없는 상태는 복사 안 함
                    
                    if val_str and target_c <= len(new_row):
                        new_row[target_c-1] = val_str
            
            sheet_rows_to_append.append(new_row)

        if not sheet_rows_to_append:
            add_log("추가할 데이터가 없습니다.")
            update_state_callback("status", "completed")
            return

        # [수정] Cell 기반 업데이트로 변경 (수식 보존)
        # ws.update()는 빈 값도 덮어써서 수식을 지우므로, Cell 단위로 값이 있는 것만 업데이트
        # Cell은 파일 상단에서 이미 import됨
        
        # 시트 헤더 읽기 (2행)
        try:
            headers = ws.row_values(2)
        except:
            headers = []
        
        # 수식이 필요한 컬럼 찾기
        formula_cols = {}
        for idx, header in enumerate(headers):
            h_clean = re.sub(r'\s+', '', str(header))  # 줄바꿈, 공백 모두 제거
            col_num = idx + 1

            if '주문현황' in h_clean:
                formula_cols['주문현황'] = col_num
            elif '수수료율' in h_clean:
                formula_cols['수수료율'] = col_num
            elif '카드번호' in h_clean:
                formula_cols['카드번호'] = col_num
            elif '수수료포함' in h_clean or '해외결제금액' in h_clean:
                formula_cols['수수료포함'] = col_num
            elif '구매금액(원화' in h_clean or '원화' in h_clean:
                formula_cols['구매금액'] = col_num
        
        cells_to_update = []
        for row_idx, new_row in enumerate(sheet_rows_to_append):
            row_num = start_row + row_idx
            
            # 일반 데이터 셀 업데이트
            for col_idx, val in enumerate(new_row):
                if val:  # 값이 있는 셀만 업데이트 (빈 값은 건너뜀 = 수식 보존)
                    col_num = col_idx + 1  # A열 = 1
                    cells_to_update.append(Cell(row_num, col_num, val))
            
            # 수식 셀 추가
            # 주문현황 수식 (빈 값일 때만)
            if '주문현황' in formula_cols:
                col = formula_cols['주문현황']
                # 해당 셀이 비어있는지 확인 (new_row에서)
                status_val = new_row[col-1] if col-1 < len(new_row) else ""
                if not status_val:  # 빈 값이면 수식 추가
                    formula = f'=IF(ISBLANK(H{row_num}), "", IF(AS{row_num}<>0, "배송중", IF(NOT(ISBLANK(AC{row_num})), "주문완료", IF(LEFT(U{row_num},1)="P", "통부회신", IF(ISBLANK(U{row_num}), "확인중", "")))))'
                    cells_to_update.append(Cell(row_num, col, formula))

            if '수수료율' in formula_cols:
                col = formula_cols['수수료율']
                formula = f"=AA{row_num}/Y{row_num}"
                cells_to_update.append(Cell(row_num, col, formula))
            
            if '카드번호' in formula_cols:
                col = formula_cols['카드번호']
                formula = f'=iferror(VLOOKUP(LEFT(AF{row_num}, FIND("(", AF{row_num})-1), \'결제카드\'!$P$2:$Q$11, 2, FALSE),"")'
                cells_to_update.append(Cell(row_num, col, formula))
            
            if '수수료포함' in formula_cols:
                col = formula_cols['수수료포함']
                formula = f'=iferror((AH{row_num}+AI{row_num})*1.03,"")'
                cells_to_update.append(Cell(row_num, col, formula))
            
            if '구매금액' in formula_cols:
                col = formula_cols['구매금액']
                formula = f'=IF(AK{row_num}="CNY",AJ{row_num}*IFERROR(VLOOKUP(INT(H{row_num}),BI:BZ,COLUMN(BZ{row_num})-COLUMN(BI{row_num})+1,FALSE)),IF(AK{row_num}="USD",AJ{row_num}*IFERROR(VLOOKUP(INT(H{row_num}),BI:BY,COLUMN(BY{row_num})-COLUMN(BI{row_num})+1,FALSE)),""))'
                cells_to_update.append(Cell(row_num, col, formula))
        
        if not cells_to_update:
            add_log("업데이트할 셀이 없습니다.")
            update_state_callback("status", "completed")
            return
        
        try:
            # 배치 업데이트 (500개씩)
            batch_size = 500
            total_cells = len(cells_to_update)
            for i in range(0, total_cells, batch_size):
                batch = cells_to_update[i:i+batch_size]
                ws.update_cells(batch, value_input_option='USER_ENTERED')
                add_log(f"셀 업데이트 진행: {min(i+batch_size, total_cells)}/{total_cells}")
                time.sleep(1)
            
            add_log(f"신규 주문 {len(sheet_rows_to_append)}건 추가 완료 (위치: {start_row}행~, 총 {total_cells}개 셀)", "success")
        except Exception as e:
            add_log(f"데이터 추가 실패: {e}", "error")
        update_state_callback("status", "completed")
