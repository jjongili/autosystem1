#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
구매대행 매출 일일장부에서 해외구매처가 "알리"인 상품 정보 수집
- 판매자 상품코드, 상품명, 옵션명, 수량, 총주문금액을 가져옴
"""

import os
import json
from datetime import datetime
from dotenv import load_dotenv

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials

# ========== 설정 ==========
# .env 파일 로드
load_dotenv()

# 구글 시트 인증 정보
CREDENTIALS_FILE = os.environ.get("SERVICE_ACCOUNT_JSON", r"C:\autosystem\web_system\autosms-466614-951e91617c69.json")
SALES_SHEET_ID = "1MHhu1GdvV1OGS8Wy3NxWOKuqFvgZpqgwn08kG70EDsY"  # 구매대행 매출 일일장부

# ========== 구글 시트 연결 ==========
def connect_google_sheets():
    """구글 시트 연결"""
    print("📊 구글 시트 연결 중...")
    
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scope)
    client = gspread.authorize(creds)
    
    print("✅ 구글 시트 연결 완료")
    return client

# ========== 컬럼 찾기 함수 ==========
def find_col(headers, names):
    """헤더에서 컬럼 인덱스 찾기"""
    for name in names:
        for idx, h in enumerate(headers):
            # 헤더에서 줄바꿈, 공백 제거 후 비교
            h_clean = h.replace('\n', '').replace('\r', '').replace(' ', '')
            name_clean = name.replace(' ', '')
            if name_clean in h_clean:
                return idx
    return -1

def col_letter_to_idx(letter):
    """열 문자를 인덱스로 변환 (A=0, B=1, ..., Z=25, AA=26, ...)"""
    letter = letter.upper()
    result = 0
    for char in letter:
        result = result * 26 + (ord(char) - ord('A') + 1)
    return result - 1

# ========== 메인 수집 함수 ==========
def collect_ali_products(month=None):
    """
    해외구매처가 "알리"인 상품 정보 수집
    
    Args:
        month: 수집할 월 (None이면 현재 월, 예: 1, 12)
    
    Returns:
        list: 수집된 상품 정보 리스트
    """
    client = connect_google_sheets()
    
    # 현재 월 탭 이름 (예: "12월")
    if month is None:
        current_month = datetime.now().month
    else:
        current_month = month
    current_tab = f"{current_month}월"
    
    print(f"📅 {current_tab} 데이터 수집 시작...")
    
    # 시트 열기
    sales_sheet = client.open_by_key(SALES_SHEET_ID)
    
    try:
        ws = sales_sheet.worksheet(current_tab)
        all_data = ws.get_all_values()
        
        if len(all_data) < 3:
            print("❌ 데이터가 없습니다")
            return []
        
        headers = all_data[1]  # 2행이 헤더
        data_rows = all_data[2:]  # 3행부터 데이터
        
        print(f"✅ {len(data_rows)}건의 데이터 로드 완료")
        
    except Exception as e:
        print(f"❌ {current_tab} 탭 로드 실패: {e}")
        return []
    
    # ========== 컬럼 인덱스 찾기 ==========
    print("🔍 컬럼 매핑 중...")
    
    # 컬럼 찾기 (이름으로 먼저 시도)
    col_seller_code = find_col(headers, ["판매자상품코드", "상품코드", "판매자 상품코드"])
    col_product_name = find_col(headers, ["상품명", "품명", "제품명"])
    col_option_name = find_col(headers, ["옵션명", "옵션"])
    col_quantity = find_col(headers, ["수량", "주문수량"])
    col_payment = find_col(headers, ["실결제금액(배송비포함)", "실결제금액"])
    col_overseas_seller = find_col(headers, ["해외구매처", "구매처", "해외 구매처"])
    col_order_status = find_col(headers, ["주문현황", "상태"])
    
    # 못 찾은 컬럼은 직접 열 인덱스 지정 (기존 매출 시트 구조 기준)
    if col_order_status < 0: 
        col_order_status = col_letter_to_idx('D')  # D열: 주문현황
    if col_seller_code < 0: 
        col_seller_code = col_letter_to_idx('J')  # J열: 판매자상품코드
    if col_product_name < 0: 
        col_product_name = col_letter_to_idx('K')  # K열: 상품명
    if col_option_name < 0: 
        col_option_name = col_letter_to_idx('L')  # L열: 옵션명 (추정)
    if col_quantity < 0: 
        col_quantity = col_letter_to_idx('T')  # T열: 수량
    if col_payment < 0: 
        col_payment = col_letter_to_idx('X')  # X열: 실결제금액
    if col_overseas_seller < 0:
        col_overseas_seller = col_letter_to_idx('AK')  # AK열: 해외구매처 (추정)
    
    print(f"📌 컬럼 매핑:")
    print(f"   - 판매자상품코드: {col_seller_code}열 ({chr(65 + col_seller_code)})")
    print(f"   - 상품명: {col_product_name}열 ({chr(65 + col_product_name)})")
    print(f"   - 옵션명: {col_option_name}열 ({chr(65 + col_option_name) if col_option_name < 26 else 'A' + chr(65 + col_option_name - 26)})")
    print(f"   - 수량: {col_quantity}열 ({chr(65 + col_quantity)})")
    print(f"   - 실결제금액: {col_payment}열 ({chr(65 + col_payment)})")
    print(f"   - 해외구매처: {col_overseas_seller}열")
    
    # ========== 알리 상품 필터링 및 수집 ==========
    print("🔍 해외구매처가 '알리'인 상품 필터링 중...")
    
    ali_products = []
    skip_count = 0
    
    for row in data_rows:
        if len(row) <= max(col_seller_code, col_product_name, col_quantity, col_payment, col_overseas_seller):
            skip_count += 1
            continue
        
        # 해외구매처 체크
        overseas_seller = row[col_overseas_seller].strip() if col_overseas_seller < len(row) else ""
        
        # "알리" 포함 여부 체크 (대소문자 무시)
        if "알리" not in overseas_seller:
            continue
        
        # 데이터 추출
        seller_code = row[col_seller_code].strip() if col_seller_code < len(row) else ""
        product_name = row[col_product_name].strip() if col_product_name < len(row) else ""
        option_name = row[col_option_name].strip() if col_option_name < len(row) else ""
        
        # 수량 파싱
        quantity = 0
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
                pay_str = row[col_payment].replace(",", "").replace("원", "").replace("₩", "").strip()
                if pay_str:
                    payment = int(float(pay_str))
            except:
                pass
        
        # 주문현황 정보
        order_status = row[col_order_status].strip() if col_order_status < len(row) else ""
        
        # 상품 정보 추가
        ali_products.append({
            "판매자상품코드": seller_code,
            "상품명": product_name,
            "옵션명": option_name,
            "수량": quantity,
            "총주문금액": payment,
            "해외구매처": overseas_seller,
            "주문현황": order_status  # 취소/반품 여부 확인용
        })
    
    # ========== 결과 출력 ==========
    print(f"\n{'='*60}")
    print(f"📊 수집 결과:")
    print(f"   - 전체 데이터: {len(data_rows):,}건")
    print(f"   - 스킵된 행: {skip_count:,}건")
    print(f"   - 알리 상품: {len(ali_products):,}건 (취소/반품 포함)")
    print(f"{'='*60}\n")
    
    return ali_products

# ========== 결과 저장 함수 ==========
def save_to_json(data, filename=None):
    """수집된 데이터를 JSON 파일로 저장"""
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"ali_products_{timestamp}.json"
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"💾 데이터 저장 완료: {filename}")
    return filename

def save_to_csv(data, filename=None):
    """수집된 데이터를 CSV 파일로 저장"""
    import csv
    
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"ali_products_{timestamp}.csv"
    
    if not data:
        print("⚠️ 저장할 데이터가 없습니다")
        return None
    
    # CSV 저장
    with open(filename, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    
    print(f"💾 CSV 저장 완료: {filename}")
    return filename

# ========== 메인 실행 ==========
if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════╗
║  🛒 알리 상품 수집기                                           ║
║  ──────────────────────────────────────────────────────────  ║
║  구매대행 매출 일일장부에서 해외구매처가 '알리'인 상품 수집     ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    # 수집할 월 선택 (None = 현재 월)
    target_month = None  # 또는 1, 2, 3, ... 12
    
    # 데이터 수집
    products = collect_ali_products(month=target_month)
    
    if products:
        # 결과 미리보기 (상위 5개)
        print("📋 수집된 데이터 미리보기 (상위 5개):")
        print("-" * 80)
        for i, product in enumerate(products[:5], 1):
            print(f"\n[{i}]")
            for key, value in product.items():
                print(f"  {key}: {value}")
        print("-" * 80)
        
        # 전체 통계
        total_quantity = sum(p["수량"] for p in products)
        total_amount = sum(p["총주문금액"] for p in products)
        
        print(f"\n💰 전체 통계:")
        print(f"   - 총 주문 건수: {len(products):,}건")
        print(f"   - 총 수량: {total_quantity:,}개")
        print(f"   - 총 주문금액: {total_amount:,}원")
        
        # 파일 저장
        print(f"\n💾 파일 저장 중...")
        json_file = save_to_json(products)
        csv_file = save_to_csv(products)
        
        print(f"\n✅ 완료! 저장된 파일:")
        print(f"   - JSON: {json_file}")
        print(f"   - CSV: {csv_file}")
    else:
        print("⚠️ 수집된 데이터가 없습니다")
