# -*- coding: utf-8 -*-
"""순서 변경 후 테스트 - 디버그"""
import sys
sys.path.insert(0, r'C:\Users\PCONOMY64\OneDrive\autosystem1')

# 모듈 리로드
import importlib
import bulsaja_common
importlib.reload(bulsaja_common)

from bulsaja_common import filter_bait_options, DEFAULT_BAIT_KEYWORDS

print('=== Debug Test ===')
print(f'Total bait keywords: {len(DEFAULT_BAIT_KEYWORDS)}')

# "샘플" 키워드 확인
has_sample = any('샘플' in kw for kw in DEFAULT_BAIT_KEYWORDS)
print(f'"샘플" in keywords: {has_sample}')

# 실제 키워드 목록에서 샘플 관련 확인
sample_kws = [kw for kw in DEFAULT_BAIT_KEYWORDS if '샘플' in kw or 'sample' in kw.lower()]
print(f'Sample-related keywords: {sample_kws}')

# 테스트 케이스: 키워드만 있고 가격 정상
test_skus = [
    {'sku': '001', 'name': '샘플', 'text': '샘플', 'text_ko': '샘플', 'price': 50},
    {'sku': '002', 'name': '일반', 'text': '일반', 'text_ko': '일반', 'price': 50},
]

print('\nTest: Keyword only ("샘플"), normal price (50 CNY)')
valid, bait = filter_bait_options(test_skus, DEFAULT_BAIT_KEYWORDS)
print(f'Valid: {len(valid)}, Bait: {len(bait)}')

for v in valid:
    print(f'  Valid: {v.get("name")}')
for b in bait:
    print(f'  Bait: {b.get("name")} - {b.get("_bait_keyword", "no reason")}')

# 강제로 샘플 키워드 추가 테스트
print('\nTest with explicit "샘플" keyword:')
test_keywords = ['샘플', '미리보기', '링크']
valid2, bait2 = filter_bait_options(test_skus, test_keywords)
print(f'Valid: {len(valid2)}, Bait: {len(bait2)}')
for b in bait2:
    print(f'  Bait: {b.get("name")} - {b.get("_bait_keyword", "no reason")}')
