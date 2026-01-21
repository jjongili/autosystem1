
import re
from collections import Counter

def analyze_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. skuRef 추출
    sku_refs = re.findall(r'skuRef\s*:\s*"([^"]+)"', content)
    sku_counts = Counter(sku_refs)
    
    # 2. text 추출 (옵션명 조합)
    texts = re.findall(r'text\s*:\s*"([^"]+)"', content)
    text_counts = Counter(texts)

    # 3. vid/pid 조합 확인 (옵션 ID)
    ids = re.findall(r'id\s*:\s*"([\d:]+)"', content)
    id_counts = Counter(ids)

    print(f"=== 파일 분석 결과: {filename} ===")
    print(f"총 발견된 SKU 개수: {len(sku_refs)}")
    
    print("\n[1] skuRef 중복 확인:")
    dupe_skus = {k:v for k,v in sku_counts.items() if v > 1}
    if dupe_skus:
        for ref, count in dupe_skus.items():
            print(f"  - {ref}: {count}회 중복")
    else:
        print("  ✅ 중복된 skuRef 없음")

    print("\n[2] 옵션명(text) 중복 확인:")
    dupe_texts = {k:v for k,v in text_counts.items() if v > 1}
    if dupe_texts:
        for txt, count in dupe_texts.items():
            print(f"  - {txt}: {count}회 중복")
    else:
        print("  ✅ 중복된 옵션명(text) 없음")

    print("\n[3] ID(id) 중복 확인:")
    dupe_ids = {k:v for k,v in id_counts.items() if v > 1}
    if dupe_ids:
        for i, count in dupe_ids.items():
            print(f"  - {i}: {count}회 중복")
    else:
        print("  ✅ 중복된 ID 없음")

analyze_file('중복옵션상세업로드필드.txt')
