
import re
import json

def analyze_pid2(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"[{filename}] PID 2 값 분석")
    
    # 1. PID 2의 정의 찾기
    # subOption 내에서 pid: 2 인 것 찾기
    # 간단히 pid: 2 주변의 values: [...] 찾기
    
    # 정규식 흐름: { ... pid: 2, ... values: [ ... ] ... }
    # 하지만 순서가 보장되지 않으므로, pid: 2 가 포함된 {...} 블록을 찾아야 함.
    
    # 간편한 방법: "pid" : 2 또는 pid: 2 가 있는 줄 확인
    # 그리고 그 주변의 values 확인
    
    # 정규식으로 'subOption' 리스트 전체 추출 후 파싱 시도
    sub_opt_match = re.search(r'subOption\s*:\s*\[(.*?)\]', content, re.DOTALL)
    if sub_opt_match:
        sub_block = sub_opt_match.group(1)
        # 객체 분리
        objs = re.findall(r'\{[^{}]+\}', sub_block)
        
        target_obj = None
        for obj in objs:
            if 'pid: 2' in obj or 'pid: "2"' in obj or '"pid": 2' in obj or '"pid": "2"' in obj:
                target_obj = obj
                break
        
        if target_obj:
            print(f"PID 2 정의 발견: {target_obj}")
            # values 추출
            val_match = re.search(r'values\s*:\s*\[(.*?)\]', target_obj)
            if val_match:
                vals = val_match.group(1)
                # vid 또는 name 개수 세기
                vid_count = len(re.findall(r'vid', vals))
                print(f"👉 PID 2의 값 개수: {vid_count}개")
                
                if vid_count <= 1:
                    print("✅ 결론: PID 2는 값이 1개뿐인 '단일 옵션'입니다. (제거 대상)")
                else:
                    print("⚠️ 결론: PID 2는 값이 여러 개입니다. (유효 옵션일 가능성)")
            else:
                print("values 필드를 찾을 수 없습니다.")
        else:
            print("PID 2 정의를 subOption 내에서 찾을 수 없습니다.")
    else:
        print("subOption 블록을 찾을 수 없습니다.")

analyze_pid2('중복옵션상세업로드필드.txt')
