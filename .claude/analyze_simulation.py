# -*- coding: utf-8 -*-
"""시뮬레이션 결과 AI 정밀 검증용 데이터 추출"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd

# 엑셀 파일 읽기
file_path = r"C:\Users\PCONOMY64\OneDrive\autosystem1\simulation_20260114_1746.xlsx"

try:
    # 상세정보 시트 읽기
    df = pd.read_excel(file_path, sheet_name="상세정보")
    print(f"=== 시뮬레이션 결과 분석 ===")
    print(f"전체 상품 수: {len(df)}")

    # 안전/위험 분류
    if '안전여부' in df.columns:
        safe_count = len(df[df['안전여부'] == '안전'])
        unsafe_count = len(df[df['안전여부'] == '위험'])
        print(f"안전: {safe_count}, 위험: {unsafe_count}")

    print("\n" + "="*60)
    print("=== 1. 안전으로 통과된 상품 (미탐지 위험 체크) ===")
    print("="*60)

    safe_df = df[df['안전여부'] == '안전']
    print(f"안전 상품 수: {len(safe_df)}")
    print("\n[안전 통과 상품명 샘플 (처음 100개)]:")
    for i, row in safe_df.head(100).iterrows():
        name = str(row.get('상품명', ''))[:60]
        print(f"  {i+1}. {name}")

    print("\n" + "="*60)
    print("=== 2. 위험으로 분류된 상품 (오탐 체크) ===")
    print("="*60)

    unsafe_df = df[df['안전여부'] == '위험']
    print(f"위험 상품 수: {len(unsafe_df)}")
    print("\n[위험 분류 상품 (위험사유 포함)]:")
    for i, row in unsafe_df.head(100).iterrows():
        name = str(row.get('상품명', ''))[:40]
        reason = str(row.get('위험사유', ''))[:30]
        print(f"  {i+1}. {name} | 사유: {reason}")

    print("\n" + "="*60)
    print("=== 3. 미끼옵션 분석 ===")
    print("="*60)

    # 미끼옵션이 있는 상품
    if '미끼옵션' in df.columns:
        bait_df = df[df['미끼옵션'] > 0]
        print(f"미끼옵션 있는 상품 수: {len(bait_df)}")

        print("\n[미끼옵션 상품 샘플 (처음 50개)]:")
        for i, row in bait_df.head(50).iterrows():
            name = str(row.get('상품명', ''))[:35]
            bait_count = row.get('미끼옵션', 0)
            bait_list = str(row.get('미끼옵션목록', ''))[:50]
            print(f"  {i+1}. {name} | 미끼:{bait_count}개 | {bait_list}")

    print("\n" + "="*60)
    print("=== 4. 위험사유별 통계 ===")
    print("="*60)

    if '위험사유' in df.columns:
        reason_counts = unsafe_df['위험사유'].value_counts()
        print("\n[위험사유별 상품 수]:")
        for reason, count in reason_counts.head(30).items():
            print(f"  {reason}: {count}개")

except Exception as e:
    print(f"오류: {e}")
    import traceback
    traceback.print_exc()
