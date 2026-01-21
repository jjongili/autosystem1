
def find_id_lines(filename, target_id):
    print(f"[{filename}]에서 ID '{target_id}' 검색 중...")
    found_lines = []
    with open(filename, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            # "id" : "1:1:1:1" 또는 id: "1:1:1:1" 등 다양한 공백 패턴 고려
            # 간단히 target_id가 포함되고 "id"가 포함된 줄 확인
            if target_id in line and "id" in line:
                found_lines.append((i + 1, line.strip()))
    
    if found_lines:
        print(f"🚨 ID '{target_id}'가 총 {len(found_lines)}번 발견되었습니다.")
        for ln, content in found_lines:
            print(f"  Line {ln}: {content}")
        
        if len(found_lines) > 1:
            print("\n👉 결론: 완전히 동일한 ID가 여러 줄에 걸쳐 존재합니다. (물리적 중복)")
    else:
        print(f"❌ ID '{target_id}'를 찾지 못했습니다.")

find_id_lines('중복옵션상세업로드필드.txt', '1:1:1:1')
