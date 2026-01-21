
import json

def analyze_duplicates(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 1. 반품지 주소 (inbound_address / return_address)
    inbound_map = {}
    
    # 2. 출고지 주소 (outbound_address / outbound_shipping_address)
    outbound_map = {}

    # 3. 연락처
    phone_map = {}

    for group in data:
        name = group['name']
        
        for detail in group['detailRowData']:
            m_type = detail['type']
            opt = detail['opt']
            
            # 주소 표준화 (간단히)
            in_addr = opt.get('inbound_address') or opt.get('return_address')
            out_addr = opt.get('outbound_address') or opt.get('outbound_shipping_address')
            phone = opt.get('phone_number') or opt.get('company_contact_number')
            
            if in_addr:
                in_addr = in_addr.strip()
                if in_addr not in inbound_map: inbound_map[in_addr] = []
                inbound_map[in_addr].append(f"{name}({m_type})")
                
            if out_addr:
                out_addr = out_addr.strip()
                if out_addr not in outbound_map: outbound_map[out_addr] = []
                outbound_map[out_addr].append(f"{name}({m_type})")

            if phone:
                phone = phone.strip()
                if phone not in phone_map: phone_map[phone] = []
                phone_map[phone].append(f"{name}({m_type})")

    print("=== [중복 분석 결과] ===")
    
    print("\n1. 반품지 주소 중복:")
    for addr, groups in inbound_map.items():
        if len(groups) > 1:
            # 같은 그룹 내 중복은 제외 (스마트스토어/쿠팡 간 중복은 자연스러움)
            # 다른 그룹 간 중복만 체크
            group_names = set([g.split('(')[0] for g in groups])
            if len(group_names) > 1:
                print(f"  📍 주소: {addr}")
                print(f"     사용 그룹: {', '.join(sorted(list(group_names)))}")

    print("\n2. 출고지 주소 중복 (국내 출고지 등):")
    for addr, groups in outbound_map.items():
        if len(groups) > 1:
            group_names = set([g.split('(')[0] for g in groups])
            if len(group_names) > 1:
                # 해외 배대지 주소는 제외 (너무 김)
                if "WEIHAI" in addr or "SHANDONG" in addr:
                    continue
                print(f"  🚚 주소: {addr}")
                print(f"     사용 그룹: {', '.join(sorted(list(group_names)))}")

    print("\n3. 연락처 중복:")
    for ph, groups in phone_map.items():
         if len(groups) > 1:
            group_names = set([g.split('(')[0] for g in groups])
            if len(group_names) > 1:
                print(f"  📞 번호: {ph}")
                print(f"     사용 그룹: {', '.join(sorted(list(group_names)))}")

analyze_duplicates('market_groups_subset.json')
