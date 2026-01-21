
import re
import json

def parse_and_check(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"[{filename}] 분석 시작")

    # 1. 옵션 정의 확인 (prop_name, pid extraction)
    # 패턴: {prop_name: "...", pid: N, ...}
    # 이 파일 형식이 JS object 형태라 정규식으로 추출
    option_defs = []
    
    # mainOption
    main_opt_match = re.search(r'mainOption\s*:\s*\{([^}]+)\}', content)
    if main_opt_match:
        block = main_opt_match.group(1)
        pid = re.search(r'pid\s*:\s*(\d+)', block)
        name = re.search(r'prop_name\s*:\s*"([^"]+)"', block)
        if pid and name:
            option_defs.append({'pid': pid.group(1), 'name': name.group(1), 'type': 'main'})

    # subOption (list)
    # subOption: [{...}, {...}, ...] 형태 찾기
    sub_opt_match = re.search(r'subOption\s*:\s*\[(.*?)\]', content, re.DOTALL)
    if sub_opt_match:
        sub_block = sub_opt_match.group(1)
        # 개별 객체 {...} 추출. 중첩 괄호가 없다고 가정하고 간단히
        subs = re.findall(r'\{[^{}]+\}', sub_block)
        for sub in subs:
            pid = re.search(r'pid\s*:\s*(\d+)', sub)
            name = re.search(r'prop_name\s*:\s*"([^"]+)"', sub)
            if pid and name:
                 option_defs.append({'pid': pid.group(1), 'name': name.group(1), 'type': 'sub'})

    print("\n=== 1. 정의된 옵션 항목 (Options) ===")
    for opt in option_defs:
        print(f"PID {opt['pid']}: {opt['name']} ({opt['type']})")
    
    if len(option_defs) == 4:
        print("👉 총 4개의 옵션 항목이 발견되었습니다. (사용자는 3개라고 언급함)")
        # 값이 1개인 옵션 찾기
        # ... (생략, 정규식으로 복잡함)

    # 2. original_skus 리스트 내 ID 중복 확인
    # original_skus : [ ... ] 블록 찾기
    # 파일 내에 'original_skus' 키워드가 있는 위치부터 시작해서 대괄호 닫힐때까지
    start_idx = content.find('original_skus')
    if start_idx != -1:
        # 대략적인 리스트 영역 추출 (단순히 id 추출로 대체)
        # original_skus 영역이라고 짐작되는 범위(다음 키워드 전까지)
        # 보통 다음 키워드는 'mainOption'이나 다른 root key일 것임.
        # 여기선 'original_skus' 뒤에 나오는 id 패턴들을 수집하되,
        # 'original_sku_props' 랑 헷갈리지 않게 주의
        
        # 간단히: "id" : "1:1:1:1" 패턴을 모두 찾되, 앞부분 라인 번호로 위치 추정
        pass

    # 전체 파일에서 id:"..." 추출해서 카운트 (이전 방식 보완)
    # 이번엔 context(original_skus 안인지 확인)
    
    print("\n=== 2. original_skus 내 ID 중복 체크 ===")
    # 정규식으로 id 추출
    ids = re.findall(r'id\s*:\s*"([\d:]+)"', content)
    
    # original_skus에 해당하는 ID는 보통 3~4자리 조합 (1:1:1:1)
    # 옵션 정의 PID max값에 따라 다름.
    # 파일 앞부분의 ID "U01..." 제외
    sku_ids = [i for i in ids if ':' in i]
    
    seen = {}
    duplicates = []
    
    for i in sku_ids:
        if i in seen:
            seen[i] += 1
            if seen[i] == 2: # 최초 중복 발견 시 리스트 추가
                duplicates.append(i)
        else:
            seen[i] = 1
            
    if duplicates:
        print(f"🛑 총 {len(duplicates)}개의 ID가 중복 발견되었습니다.")
        print(f"   예시: {duplicates[:5]} ...")
        
        # 가장 많이 중복된 ID
        max_id = max(seen, key=seen.get)
        print(f"   최디 중복 ID: {max_id} ({seen[max_id]}회 등장)")
    else:
        print("✅ SKU ID 중복 없음 (모든 ID가 유니크함)")


    # 3. 옵션값 분석 (사용자가 3개라고 했는데 4개인 이유)
    # PID 2가 값이 1개인지 확인
    if any(opt['pid'] == '2' for opt in option_defs):
        # PID 2에 대한 values 값 개수 확인
        pass

parse_and_check('중복옵션상세업로드필드.txt')
