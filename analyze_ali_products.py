#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
알리 상품 수집 및 분석 예제
"""

from ali_products_collector import collect_ali_products, save_to_json, save_to_csv
from collections import Counter, defaultdict

def analyze_ali_products():
    """알리 상품 수집 및 분석"""
    
    print("="*80)
    print("🛒 알리 상품 수집 및 분석 시작")
    print("="*80 + "\n")
    
    # 1. 현재 월 데이터 수집
    print("📊 Step 1: 데이터 수집 중...")
    products = collect_ali_products(month=None)  # None = 현재 월
    
    if not products:
        print("⚠️ 수집된 데이터가 없습니다")
        return
    
    # 2. 기본 통계
    print("\n" + "="*80)
    print("📈 Step 2: 기본 통계")
    print("="*80)
    
    total_orders = len(products)
    total_quantity = sum(p['수량'] for p in products)
    total_amount = sum(p['총주문금액'] for p in products)
    avg_amount = total_amount / total_orders if total_orders > 0 else 0
    
    print(f"  총 주문 건수: {total_orders:,}건")
    print(f"  총 수량: {total_quantity:,}개")
    print(f"  총 주문금액: {total_amount:,}원")
    print(f"  평균 주문금액: {avg_amount:,.0f}원")
    
    # 3. 상품명 TOP 10
    print("\n" + "="*80)
    print("🏆 Step 3: 인기 상품 TOP 10 (주문 건수)")
    print("="*80)
    
    product_names = [p['상품명'] for p in products if p['상품명']]
    top_products = Counter(product_names).most_common(10)
    
    for rank, (name, count) in enumerate(top_products, 1):
        print(f"  {rank:2d}. {name[:50]:50s} : {count:3d}건")
    
    # 4. 판매자 상품코드별 집계
    print("\n" + "="*80)
    print("💰 Step 4: 판매자 상품코드별 매출 TOP 10")
    print("="*80)
    
    code_summary = defaultdict(lambda: {
        "상품명": "",
        "수량": 0,
        "금액": 0,
        "주문건수": 0
    })
    
    for product in products:
        code = product['판매자상품코드']
        if not code:
            continue
        
        code_summary[code]['상품명'] = product['상품명']
        code_summary[code]['수량'] += product['수량']
        code_summary[code]['금액'] += product['총주문금액']
        code_summary[code]['주문건수'] += 1
    
    sorted_codes = sorted(
        code_summary.items(),
        key=lambda x: x[1]['금액'],
        reverse=True
    )
    
    for rank, (code, data) in enumerate(sorted_codes[:10], 1):
        print(f"  {rank:2d}. [{code}] {data['상품명'][:40]:40s}")
        print(f"      → {data['주문건수']:3d}건, {data['수량']:4d}개, {data['금액']:,}원")
    
    # 5. 옵션명 분석
    print("\n" + "="*80)
    print("🔧 Step 5: 인기 옵션 TOP 10")
    print("="*80)
    
    options = [p['옵션명'] for p in products if p['옵션명']]
    top_options = Counter(options).most_common(10)
    
    for rank, (option, count) in enumerate(top_options, 1):
        print(f"  {rank:2d}. {option[:60]:60s} : {count:3d}건")
    
    # 6. 해외구매처 상세 분석
    print("\n" + "="*80)
    print("🌏 Step 6: 해외구매처 상세")
    print("="*80)
    
    overseas_sellers = Counter([p['해외구매처'] for p in products if p['해외구매처']])
    
    for seller, count in overseas_sellers.most_common():
        seller_products = [p for p in products if p['해외구매처'] == seller]
        seller_amount = sum(p['총주문금액'] for p in seller_products)
        seller_quantity = sum(p['수량'] for p in seller_products)
        
        print(f"  {seller}")
        print(f"    - 주문: {count:,}건, 수량: {seller_quantity:,}개, 금액: {seller_amount:,}원")
    
    # 7. 주문현황별 통계 (취소/반품 포함 분석)
    print("\n" + "="*80)
    print("📋 Step 7: 주문현황별 통계")
    print("="*80)
    
    status_stats = defaultdict(lambda: {"건수": 0, "수량": 0, "금액": 0})
    
    for product in products:
        status = product.get('주문현황', '').strip()
        if not status:
            status = "미확인"
        
        status_stats[status]['건수'] += 1
        status_stats[status]['수량'] += product['수량']
        status_stats[status]['금액'] += product['총주문금액']
    
    # 취소/반품 여부로 그룹핑
    normal_count = 0
    normal_amount = 0
    cancel_count = 0
    cancel_amount = 0
    
    for status, data in sorted(status_stats.items(), key=lambda x: x[1]['금액'], reverse=True):
        is_cancel = any(x in status for x in ["취소", "반품", "환불"])
        
        if is_cancel:
            cancel_count += data['건수']
            cancel_amount += data['금액']
            mark = "❌"
        else:
            normal_count += data['건수']
            normal_amount += data['금액']
            mark = "✅"
        
        print(f"  {mark} {status:20s}: {data['건수']:4d}건, {data['수량']:5d}개, {data['금액']:,}원")
    
    print(f"\n  📊 요약:")
    print(f"     정상 주문: {normal_count:,}건 ({normal_amount:,}원)")
    print(f"     취소/반품: {cancel_count:,}건 ({cancel_amount:,}원)")
    
    # 8. 파일 저장
    print("\n" + "="*80)
    print("💾 Step 8: 파일 저장")
    print("="*80)
    
    json_file = save_to_json(products)
    csv_file = save_to_csv(products)
    
    print(f"  ✅ JSON: {json_file}")
    print(f"  ✅ CSV: {csv_file}")
    
    # 9. 요약 리포트
    print("\n" + "="*80)
    print("📋 최종 요약")
    print("="*80)
    print(f"""
  수집 기간: {products[0].get('주문일자', '현재 월')} ~ 현재
  총 주문 건수: {total_orders:,}건
  총 수량: {total_quantity:,}개
  총 주문금액: {total_amount:,}원
  평균 주문금액: {avg_amount:,.0f}원
  
  상품 종류: {len(set(p['상품명'] for p in products)):,}개
  판매자 코드: {len(set(p['판매자상품코드'] for p in products if p['판매자상품코드'])):,}개
  옵션 종류: {len(set(p['옵션명'] for p in products if p['옵션명'])):,}개
    """)
    
    print("="*80)
    print("✅ 분석 완료!")
    print("="*80)

if __name__ == "__main__":
    analyze_ali_products()
