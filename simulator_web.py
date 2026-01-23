# -*- coding: utf-8 -*-
"""
시뮬레이터 웹 버전 - Flask + HTML
실행: python simulator_web.py
브라우저: http://localhost:5000
"""

from flask import Flask, render_template_string, jsonify, request, send_from_directory
import json
import os
from pathlib import Path

# 불사자 API 클라이언트
try:
    from bulsaja_common import (
        BulsajaAPIClient, extract_tokens_from_browser,
        filter_bait_options, select_main_option,
        load_bait_keywords, check_product_safety,
        load_banned_words, load_excluded_words
    )
    BULSAJA_AVAILABLE = True
except ImportError:
    BULSAJA_AVAILABLE = False
    print("[WARNING] bulsaja_common 모듈 없음")

app = Flask(__name__)

# 전역 API 클라이언트
api_client = None
CONFIG_FILE = Path(__file__).parent / "bulsaja_uploader_config.json"


def load_tokens():
    """저장된 토큰 로드"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('access_token', ''), data.get('refresh_token', '')
    return '', ''


def init_api_client():
    """API 클라이언트 초기화"""
    global api_client
    access_token, refresh_token = load_tokens()
    if access_token and BULSAJA_AVAILABLE:
        api_client = BulsajaAPIClient(access_token, refresh_token)
        return True
    return False


# HTML 템플릿 (AG-Grid 사용)
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>불사자 시뮬레이터 (웹)</title>
    <script src="https://cdn.jsdelivr.net/npm/ag-grid-community/dist/ag-grid-community.min.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: '맑은 고딕', sans-serif; background: #1a1a2e; color: #eee; }

        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 15px 20px;
            display: flex;
            align-items: center;
            gap: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
        }
        .header h1 { font-size: 20px; }
        .header select, .header input, .header button {
            padding: 8px 12px;
            border: none;
            border-radius: 5px;
            font-size: 14px;
        }
        .header select { background: #fff; min-width: 200px; }
        .header input { background: #fff; width: 80px; text-align: center; }
        .header button {
            background: #4CAF50;
            color: white;
            cursor: pointer;
            font-weight: bold;
        }
        .header button:hover { background: #45a049; }
        .header button.danger { background: #f44336; }
        .header button.danger:hover { background: #d32f2f; }
        .header button.primary { background: #2196F3; }
        .header button.primary:hover { background: #1976D2; }

        .stats {
            background: #16213e;
            padding: 10px 20px;
            display: flex;
            gap: 30px;
            font-size: 14px;
            border-bottom: 1px solid #333;
        }
        .stats span { color: #888; }
        .stats .value { color: #4CAF50; font-weight: bold; margin-left: 5px; }

        #grid-container {
            height: calc(100vh - 120px);
            width: 100%;
        }

        .ag-theme-alpine-dark {
            --ag-background-color: #1a1a2e;
            --ag-header-background-color: #16213e;
            --ag-odd-row-background-color: #1f1f3a;
            --ag-row-hover-color: #2a2a4a;
        }

        /* 옵션 버튼 스타일 */
        .option-btn {
            display: inline-block;
            padding: 4px 10px;
            margin: 2px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            font-weight: bold;
            transition: all 0.2s;
        }
        .option-btn.selected {
            background: #2196F3;
            color: white;
        }
        .option-btn.unselected {
            background: #444;
            color: #aaa;
        }
        .option-btn:hover {
            transform: scale(1.05);
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        }
        .option-btn.more {
            background: #FF9800;
            color: white;
        }

        /* 이미지 셀 */
        .thumb-img {
            width: 60px;
            height: 60px;
            object-fit: cover;
            border-radius: 4px;
            cursor: pointer;
        }
        .thumb-img:hover {
            transform: scale(2);
            position: relative;
            z-index: 100;
            box-shadow: 0 4px 20px rgba(0,0,0,0.5);
        }

        /* 안전/위험 배지 */
        .badge-safe { background: #4CAF50; color: white; padding: 2px 8px; border-radius: 10px; }
        .badge-danger { background: #f44336; color: white; padding: 2px 8px; border-radius: 10px; }

        /* 링크 스타일 */
        .bulsaja-link {
            color: #64B5F6;
            text-decoration: underline;
            cursor: pointer;
        }
        .bulsaja-link:hover { color: #90CAF9; }

        /* 로딩 오버레이 */
        .loading-overlay {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.7);
            display: none;
            justify-content: center;
            align-items: center;
            z-index: 1000;
        }
        .loading-overlay.show { display: flex; }
        .loading-spinner {
            width: 50px;
            height: 50px;
            border: 5px solid #333;
            border-top-color: #2196F3;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        /* 토스트 메시지 */
        .toast {
            position: fixed;
            bottom: 20px;
            right: 20px;
            padding: 15px 25px;
            background: #333;
            color: white;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
            transform: translateX(150%);
            transition: transform 0.3s;
            z-index: 1001;
        }
        .toast.show { transform: translateX(0); }
        .toast.success { background: #4CAF50; }
        .toast.error { background: #f44336; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔥 불사자 시뮬레이터</h1>
        <select id="groupSelect">
            <option value="">-- 그룹 선택 --</option>
        </select>
        <input type="number" id="limitInput" value="100" min="1" max="500">
        <button onclick="loadProducts()">📥 상품 로드</button>
        <button class="primary" onclick="applyChanges()">✅ 변경사항 적용</button>
        <button class="danger" onclick="resetChanges()">🔄 초기화</button>
        <span style="margin-left: auto; color: #aaa;" id="statusText">준비됨</span>
    </div>

    <div class="stats">
        <div>전체: <span class="value" id="totalCount">0</span>개</div>
        <div>안전: <span class="value" style="color:#4CAF50" id="safeCount">0</span>개</div>
        <div>위험: <span class="value" style="color:#f44336" id="dangerCount">0</span>개</div>
        <div>변경됨: <span class="value" style="color:#FF9800" id="changedCount">0</span>개</div>
    </div>

    <div id="grid-container" class="ag-theme-alpine-dark"></div>

    <div class="loading-overlay" id="loadingOverlay">
        <div class="loading-spinner"></div>
    </div>

    <div class="toast" id="toast"></div>

<script>
// 전역 데이터
let gridApi = null;
let rowData = [];
let originalSelections = {};  // 원래 선택된 옵션 저장

// 컬럼 정의
const columnDefs = [
    {
        headerName: '불사자ID',
        field: 'product_id',
        width: 140,
        cellRenderer: params => {
            if (!params.value) return '';
            const short = params.value.length > 12 ? params.value.slice(0, 12) + '..' : params.value;
            return `<span class="bulsaja-link" onclick="openBulsaja('${params.value}')">${short}</span>`;
        }
    },
    {
        headerName: '썸네일',
        field: 'thumbnail_url',
        width: 80,
        cellRenderer: params => {
            if (!params.value) return '';
            return `<img src="${params.value}" class="thumb-img" onerror="this.style.display='none'">`;
        }
    },
    {
        headerName: '옵션 선택',
        field: 'options',
        width: 400,
        autoHeight: true,
        cellRenderer: params => {
            if (!params.value || !params.value.length) return '-';
            const rowIndex = params.node.rowIndex;
            const selected = params.data.selected || 'A';
            const maxShow = 6;

            let html = '';
            const showOptions = params.value.slice(0, maxShow);
            const moreCount = params.value.length - maxShow;

            showOptions.forEach(opt => {
                const isSelected = opt.label === selected;
                const cls = isSelected ? 'selected' : 'unselected';
                const name = opt.name.length > 8 ? opt.name.slice(0, 8) + '..' : opt.name;
                html += `<span class="option-btn ${cls}" onclick="selectOption(${rowIndex}, '${opt.label}')" title="${opt.name}">${opt.label}. ${name}</span>`;
            });

            if (moreCount > 0) {
                html += `<span class="option-btn more" onclick="showMoreOptions(${rowIndex})">+${moreCount}</span>`;
            }

            return html;
        }
    },
    {
        headerName: '상품명',
        field: 'product_name',
        width: 250,
        tooltipField: 'product_name'
    },
    {
        headerName: '안전',
        field: 'is_safe',
        width: 70,
        cellRenderer: params => {
            return params.value
                ? '<span class="badge-safe">O</span>'
                : '<span class="badge-danger">X</span>';
        }
    },
    {
        headerName: '위험사유',
        field: 'unsafe_reason',
        width: 150,
        tooltipField: 'unsafe_reason'
    },
    {
        headerName: '옵션수',
        field: 'option_count',
        width: 80,
        valueGetter: params => {
            const opts = params.data.options || [];
            return `${opts.length}개`;
        }
    },
    {
        headerName: '그룹',
        field: 'group_name',
        width: 120
    }
];

// 그리드 옵션
const gridOptions = {
    columnDefs: columnDefs,
    rowData: [],
    defaultColDef: {
        sortable: true,
        filter: true,
        resizable: true
    },
    rowHeight: 70,
    headerHeight: 40,
    animateRows: true,
    rowSelection: 'multiple',
    suppressRowClickSelection: true,
    getRowStyle: params => {
        if (!params.data.is_safe) {
            return { background: 'rgba(244, 67, 54, 0.15)' };
        }
        // 변경된 행 하이라이트
        const orig = originalSelections[params.data.product_id];
        if (orig && orig !== params.data.selected) {
            return { background: 'rgba(255, 152, 0, 0.2)' };
        }
        return null;
    }
};

// 초기화
document.addEventListener('DOMContentLoaded', () => {
    const gridDiv = document.getElementById('grid-container');
    gridApi = agGrid.createGrid(gridDiv, gridOptions);
    loadGroups();
});

// 그룹 목록 로드
async function loadGroups() {
    try {
        const resp = await fetch('/api/groups');
        const data = await resp.json();

        const select = document.getElementById('groupSelect');
        select.innerHTML = '<option value="">-- 그룹 선택 --</option>';

        data.groups.forEach(g => {
            const opt = document.createElement('option');
            opt.value = g;
            opt.textContent = g;
            select.appendChild(opt);
        });
    } catch (e) {
        showToast('그룹 로드 실패: ' + e.message, 'error');
    }
}

// 상품 로드
async function loadProducts() {
    const group = document.getElementById('groupSelect').value;
    const limit = document.getElementById('limitInput').value || 100;

    if (!group) {
        showToast('그룹을 선택하세요', 'error');
        return;
    }

    showLoading(true);
    setStatus('상품 로드 중...');

    try {
        const resp = await fetch(`/api/products?group=${encodeURIComponent(group)}&limit=${limit}`);
        const data = await resp.json();

        if (data.error) {
            throw new Error(data.error);
        }

        rowData = data.products;

        // 원래 선택 저장
        originalSelections = {};
        rowData.forEach(p => {
            originalSelections[p.product_id] = p.selected;
        });

        gridApi.setGridOption('rowData', rowData);
        updateStats();

        showToast(`${rowData.length}개 상품 로드 완료`, 'success');
        setStatus(`${rowData.length}개 로드됨`);
    } catch (e) {
        showToast('로드 실패: ' + e.message, 'error');
        setStatus('로드 실패');
    } finally {
        showLoading(false);
    }
}

// 옵션 선택
function selectOption(rowIndex, label) {
    const rowNode = gridApi.getDisplayedRowAtIndex(rowIndex);
    if (rowNode) {
        rowNode.data.selected = label;
        gridApi.refreshCells({ rowNodes: [rowNode], force: true });
        updateStats();
    }
}

// 더보기 (모달로 전체 옵션 표시)
function showMoreOptions(rowIndex) {
    const rowNode = gridApi.getDisplayedRowAtIndex(rowIndex);
    if (!rowNode) return;

    const options = rowNode.data.options || [];
    const selected = rowNode.data.selected;

    let html = '<div style="max-height:400px;overflow-y:auto;padding:10px;">';
    options.forEach(opt => {
        const isSelected = opt.label === selected;
        const cls = isSelected ? 'selected' : 'unselected';
        html += `<div class="option-btn ${cls}" style="display:block;margin:5px 0;padding:10px;" onclick="selectOption(${rowIndex}, '${opt.label}');this.closest('.modal').remove();">${opt.label}. ${opt.name}</div>`;
    });
    html += '</div>';

    // 간단한 모달
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.8);display:flex;justify-content:center;align-items:center;z-index:1000;';
    modal.innerHTML = `<div style="background:#2a2a4a;padding:20px;border-radius:10px;min-width:300px;"><h3 style="margin-bottom:15px;">전체 옵션 (${options.length}개)</h3>${html}<button onclick="this.closest('.modal').remove()" style="margin-top:15px;padding:10px 20px;background:#666;border:none;color:white;border-radius:5px;cursor:pointer;">닫기</button></div>`;
    modal.onclick = e => { if (e.target === modal) modal.remove(); };
    document.body.appendChild(modal);
}

// 불사자 페이지 열기
function openBulsaja(productId) {
    window.open(`https://www.bulsaja.com/sourcing/${productId}?tab=option`, '_blank');
}

// 변경사항 적용
async function applyChanges() {
    const changes = [];
    rowData.forEach(p => {
        const orig = originalSelections[p.product_id];
        if (orig && orig !== p.selected) {
            changes.push({
                product_id: p.product_id,
                old_option: orig,
                new_option: p.selected
            });
        }
    });

    if (changes.length === 0) {
        showToast('변경된 항목이 없습니다', 'error');
        return;
    }

    if (!confirm(`${changes.length}개 상품의 대표옵션을 변경하시겠습니까?`)) {
        return;
    }

    showLoading(true);
    setStatus('적용 중...');

    try {
        const resp = await fetch('/api/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ changes })
        });
        const data = await resp.json();

        if (data.error) {
            throw new Error(data.error);
        }

        // 성공한 항목은 원래 선택 업데이트
        data.results.forEach(r => {
            if (r.success) {
                originalSelections[r.product_id] = r.new_option;
            }
        });

        gridApi.refreshCells({ force: true });
        updateStats();

        showToast(`성공: ${data.success_count}, 실패: ${data.fail_count}`,
                  data.fail_count > 0 ? 'error' : 'success');
        setStatus(`적용 완료: ${data.success_count}/${changes.length}`);
    } catch (e) {
        showToast('적용 실패: ' + e.message, 'error');
        setStatus('적용 실패');
    } finally {
        showLoading(false);
    }
}

// 초기화
function resetChanges() {
    rowData.forEach(p => {
        const orig = originalSelections[p.product_id];
        if (orig) {
            p.selected = orig;
        }
    });
    gridApi.refreshCells({ force: true });
    updateStats();
    showToast('초기화 완료', 'success');
}

// 통계 업데이트
function updateStats() {
    const total = rowData.length;
    const safe = rowData.filter(p => p.is_safe).length;
    const danger = total - safe;

    let changed = 0;
    rowData.forEach(p => {
        const orig = originalSelections[p.product_id];
        if (orig && orig !== p.selected) changed++;
    });

    document.getElementById('totalCount').textContent = total;
    document.getElementById('safeCount').textContent = safe;
    document.getElementById('dangerCount').textContent = danger;
    document.getElementById('changedCount').textContent = changed;
}

// UI 헬퍼
function showLoading(show) {
    document.getElementById('loadingOverlay').classList.toggle('show', show);
}

function setStatus(text) {
    document.getElementById('statusText').textContent = text;
}

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast show ' + type;
    setTimeout(() => toast.classList.remove('show'), 3000);
}
</script>
</body>
</html>
'''


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/groups')
def get_groups():
    """그룹 목록 조회"""
    if not api_client:
        if not init_api_client():
            return jsonify({'error': '토큰 없음. bulsaja_uploader_config.json 확인', 'groups': []})

    try:
        groups = api_client.get_market_groups()
        group_names = [g.get('marketGroupName', '') for g in groups if g.get('marketGroupName')]
        return jsonify({'groups': sorted(group_names)})
    except Exception as e:
        return jsonify({'error': str(e), 'groups': []})


@app.route('/api/products')
def get_products():
    """상품 목록 조회"""
    if not api_client:
        if not init_api_client():
            return jsonify({'error': '토큰 없음', 'products': []})

    group = request.args.get('group', '')
    limit = int(request.args.get('limit', 100))

    if not group:
        return jsonify({'error': '그룹 필수', 'products': []})

    try:
        # 상품 목록 조회
        products, total = api_client.get_products_by_group(group, 0, limit, ['0', '1', '2'])

        # 미끼 키워드 로드
        bait_keywords = load_bait_keywords()
        banned_words = load_banned_words()
        excluded_words = load_excluded_words()

        result = []
        for p in products:
            product_id = p.get('ID', '')
            product_name = p.get('uploadCommonProductName', '') or p.get('name', '')

            # 안전 검사
            is_safe, reason, _ = check_product_safety(product_name, banned_words, excluded_words)

            # 옵션 정보
            upload_skus = p.get('uploadSkus', [])
            options = []
            selected = 'A'

            for i, sku in enumerate(upload_skus):
                if sku.get('exclude'):
                    continue
                label = chr(65 + len(options))  # A, B, C, ...
                options.append({
                    'label': label,
                    'name': sku.get('text', ''),
                    'price': sku.get('sale_price', 0),
                    'id': sku.get('id', '')
                })
                if sku.get('main_product'):
                    selected = label

            # 썸네일
            thumbnails = p.get('uploadThumbnails', [])
            thumb_url = thumbnails[0] if thumbnails else ''

            result.append({
                'product_id': product_id,
                'product_name': product_name,
                'is_safe': is_safe,
                'unsafe_reason': reason if not is_safe else '',
                'options': options,
                'selected': selected,
                'thumbnail_url': thumb_url,
                'group_name': group
            })

        return jsonify({'products': result, 'total': total})
    except Exception as e:
        return jsonify({'error': str(e), 'products': []})


@app.route('/api/apply', methods=['POST'])
def apply_changes():
    """변경사항 적용"""
    if not api_client:
        return jsonify({'error': '토큰 없음'})

    data = request.json
    changes = data.get('changes', [])

    results = []
    success_count = 0
    fail_count = 0

    for change in changes:
        product_id = change['product_id']
        new_option = change['new_option']

        try:
            # 상품 상세 조회
            detail = api_client.get_product_detail(product_id)
            upload_skus = detail.get('uploadSkus', [])

            # 옵션 인덱스 찾기
            option_index = ord(new_option) - 65  # A=0, B=1, ...

            # 유효 옵션만 필터링
            valid_skus = [s for s in upload_skus if not s.get('exclude')]

            if option_index < 0 or option_index >= len(valid_skus):
                raise ValueError(f'잘못된 옵션: {new_option}')

            target_id = valid_skus[option_index].get('id')

            # main_product 변경
            for sku in upload_skus:
                sku['main_product'] = (sku.get('id') == target_id)

            # API 업데이트
            success, msg = api_client.update_product_fields(product_id, {'uploadSkus': upload_skus})

            if success:
                success_count += 1
                results.append({'product_id': product_id, 'success': True, 'new_option': new_option})
            else:
                fail_count += 1
                results.append({'product_id': product_id, 'success': False, 'error': msg})

        except Exception as e:
            fail_count += 1
            results.append({'product_id': product_id, 'success': False, 'error': str(e)})

    return jsonify({
        'success_count': success_count,
        'fail_count': fail_count,
        'results': results
    })


if __name__ == '__main__':
    print("=" * 50)
    print("불사자 시뮬레이터 (웹 버전)")
    print("=" * 50)
    print("브라우저에서 열기: http://localhost:5000")
    print("종료: Ctrl+C")
    print("=" * 50)

    # API 클라이언트 초기화
    if init_api_client():
        print("✅ 불사자 API 연결됨")
    else:
        print("⚠️ 토큰 없음 - bulsaja_uploader_config.json 필요")

    app.run(host='0.0.0.0', port=5000, debug=False)
