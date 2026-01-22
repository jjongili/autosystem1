// 전역 변수
let accounts = [], currentPlatform = '전체', authCodes = {}, autoRefreshInterval = null, smsViewMode = 'list'; // list, search, conversation
let platformCounts = {}, totalCount = 0;
let currentConversation = { profile_id: '', sender: '' };  // 현재 열린 대화
let currentUserRole = '뷰어';  // 현재 사용자 권한
let userPermissions = [];  // 권한 목록
let top40Data = [];  // TOP 40 상품 데이터
let top40SortColumn = 'order_count';  // 정렬 기준 (order_count 또는 total_sales)
let top40SortDesc = true;  // 내림차순

// 다크모드/라이트모드 토글
function toggleTheme() {
    const body = document.body;
    const btn = document.querySelector('.theme-toggle-btn');

    if (body.classList.contains('dark-mode')) {
        // 라이트모드로 전환
        body.classList.remove('dark-mode');
        if (btn) btn.textContent = '🌙';
        localStorage.setItem('theme', 'light');
    } else {
        // 다크모드로 전환
        body.classList.add('dark-mode');
        if (btn) btn.textContent = '☀️';
        localStorage.setItem('theme', 'dark');
    }
}

// 페이지 로드시 저장된 테마 적용
function applyStoredTheme() {
    const savedTheme = localStorage.getItem('theme');
    const btn = document.querySelector('.theme-toggle-btn');

    if (savedTheme === 'dark') {
        document.body.classList.add('dark-mode');
        if (btn) btn.textContent = '☀️';
    } else {
        document.body.classList.remove('dark-mode');
        if (btn) btn.textContent = '🌙';
    }
}

// DOM 로드 시 테마 적용
document.addEventListener('DOMContentLoaded', applyStoredTheme);

// 한글 우선 + 영어 fallback 헬퍼 함수
function get플랫폼(acc) { return acc['플랫폼'] || acc.platform || ''; }
function get아이디(acc) { return acc['아이디'] || acc.login_id || ''; }
function get패스워드(acc) { return acc['패스워드'] || acc.password || ''; }
function get스토어명(acc) { return acc['스토어명'] || acc.스토어명 || ''; }
function get사업자번호(acc) { return acc['사업자번호'] || acc.business_number || ''; }
function get용도(acc) { return acc['용도'] || acc.usage || ''; }
function get소유자(acc) { return acc['소유자'] || acc.owner || ''; }

// textarea 자동 높이 조절
function autoResizeTextarea(el) {
    const minHeight = 40;  // 기본 최소 높이

    // 내용이 비어있으면 최소 높이로 강제 설정
    if (!el.value || el.value.trim() === '') {
        el.style.height = minHeight + 'px';
        return;
    }

    // 내용이 있으면 scrollHeight에 맞춤
    el.style.height = 'auto';
    const newHeight = Math.max(minHeight, Math.min(el.scrollHeight, 150));
    el.style.height = newHeight + 'px';
}

// API 호출 헬퍼 함수
async function fetchAPI(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        }
    });
    if (!response.ok) {
        throw new Error(`API Error: ${response.status}`);
    }
    return response.json();
}

const platformColors = {
    '스마트스토어': '#03C75A',
    '쿠팡': '#00B4D8',
    '11번가': '#E31837',
    'ESM통합': '#6C5CE7',
    '지마켓': '#1A73E8',
    '옥션': '#9C27B0'
};

const platformUrls = {
    '스마트스토어': 'https://accounts.commerce.naver.com/login?url=https%3A%2F%2Fsell.smartstore.naver.com%2F%23%2Flogin-callback',
    '쿠팡': 'https://xauth.coupang.com/auth/realms/seller/protocol/openid-connect/auth?response_type=code&client_id=wing&redirect_uri=https%3A%2F%2Fwing.coupang.com%2Fsso%2Flogin?returnUrl%3D%252F&state=78ad277c-bf25-4992-8f48-c523b37ce667&login=true&ui_locales=ko-KR&scope=openid',
    '11번가': 'https://login.11st.co.kr/auth/front/selleroffice/login.tmall',
    'ESM통합': 'https://signin.esmplus.com/login',
    '지마켓': 'https://signin.esmplus.com/login',
    '옥션': 'https://signin.esmplus.com/login'
};

// 초기화
document.addEventListener('DOMContentLoaded', async () => {
    await loadUserInfo();  // 권한 정보 먼저 로드
    initTabs();
    loadAccounts();
    loadSMSStatus();
    refreshMessages(true);  // 메시지 초기 로드
    initWebSocket();
    initSmsPanelDragDrop();  // SMS 패널 드래그앤드롭 초기화
});

// 사용자 정보 로드 (권한 포함)
async function loadUserInfo() {
    try {
        const r = await fetch('/api/me');
        const d = await r.json();
        currentUserRole = d.role || '뷰어';
        userPermissions = d.permissions || [];
        console.log(`[권한] ${d.name} (${currentUserRole}):`, userPermissions);

        // body에 role 속성 설정 (CSS 권한 제어용)
        document.body.setAttribute('data-role', currentUserRole);

        // 운영자인 경우 탭 권한 적용
        if (currentUserRole === '운영자' && d.tab_permissions) {
            applyTabPermissions(d.tab_permissions);
        }
    } catch (e) {
        console.error('사용자 정보 로드 실패:', e);
    }
}

// 운영자 탭 권한 적용
function applyTabPermissions(permissions) {
    console.log('[탭 권한 적용]', permissions);

    // 탭 ID와 tab_permissions 키 매핑
    const tabMapping = {
        'sms': 'sms',
        'monitor': 'monitor',
        'market-table': 'market',
        'sales': 'sales',
        'accounts': 'accounts',
        'marketing': 'marketing',
        'allinone': 'aio',
        'scheduler': 'scheduler',
        'bulsaja': 'bulsaja',
        'tools': 'tools',
        'work-calendar': 'calendar'
    };

    // 각 탭에 대해 권한 적용
    document.querySelectorAll('.tabs .tab').forEach(tab => {
        const tabName = tab.dataset.tab;

        // 설정 탭은 항상 숨김 (관리자만 접근)
        if (tabName === 'settings') {
            tab.style.display = 'none';
            return;
        }

        const permKey = tabMapping[tabName];
        if (permKey && permissions[permKey] === false) {
            tab.style.display = 'none';
            console.log(`[탭 숨김] ${tabName}`);
        }
    });
}

// 권한 체크
function hasPermission(permission) {
    return userPermissions.includes(permission);
}

// WebSocket
function initWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/ws`);
    ws.onmessage = (e) => {
        const d = JSON.parse(e.data);
        if (d.type === 'sms_status') updatePhoneStatus(d.ready);
        else if (d.type === 'account_update') loadAccounts();
        else if (d.type === 'ali_log') {
            const msg = typeof d.message === 'object' ? JSON.stringify(d.message) : d.message;
            aliLog(msg, d.status || '');
        }
        else if (d.type === 'bulsaja_log') appendBulsajaLog(d.timestamp, d.message);
    };
    ws.onclose = () => setTimeout(initWebSocket, 3000);
}

// 탭
function initTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.dataset.tab;
            activateTab(tabName);
            // URL 해시 변경 (히스토리에 추가)
            history.pushState(null, '', '#' + tabName);
        });
    });

    // 페이지 로드 시 URL 해시에 따라 탭 선택
    handleHashChange();

    // 뒤로가기/앞으로가기 지원
    window.addEventListener('popstate', handleHashChange);
}

// URL 해시 변경 처리
function handleHashChange() {
    const hash = window.location.hash.replace('#', '') || 'sms';  // 기본값 sms
    activateTab(hash);
}

// 탭 활성화
function activateTab(tabName) {
    const tabEl = document.querySelector(`.tab[data-tab="${tabName}"]`);
    const contentEl = document.getElementById('tab-' + tabName);

    if (!tabEl || !contentEl) return;

    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tabEl.classList.add('active');
    contentEl.classList.add('active');

    // 탭 전환 시 확장정보 패널 닫기
    closeExtendedInfo();

    // 마케팅분석 탭 활성화 시 계정 목록 로드
    if (tabName === 'marketing') {
        loadMarketingAccounts();
    }

    // 자동화 대시보드 탭 활성화 시 초기화
    if (tabName === 'bulsaja-dashboard') {
        initBulsajaDashboard();
    }
}

// SMS 기능
async function loadSMSStatus() {
    try {
        const r = await fetch('/api/sms/status');
        const d = await r.json();
        updatePhoneStatus(d.ready);
        authCodes = d.auth_codes || {};
        updateAuthCodes();
    } catch (e) { console.error(e); }
}

function updatePhoneStatus(ready) {
    Object.entries(ready).forEach(([p, r]) => {
        const b = document.querySelector(`.phone-btn[data-phone="${p}"]`);
        if (b) {
            b.classList.toggle('ready', r);
            b.querySelector('.status').textContent = r ? '✓' : '';
        }
    });
}

function updateAuthCodes() {
    const phones = ['8295', '8217', '4682'];
    let latestTimestamp = 0;
    let latestPhone = null;
    let latestCode = null;

    // 가장 최신 인증코드 찾기 (Unix timestamp로 비교)
    phones.forEach(p => {
        const info = authCodes[p];
        if (info && typeof info === 'object' && info.code && info.code !== '------') {
            const ts = info.timestamp || 0;
            if (ts > latestTimestamp) {
                latestTimestamp = ts;
                latestPhone = p;
                latestCode = info.code;
            }
        }
    });

    // 헤더에 최신 인증번호 표시
    const headerAuth = document.getElementById('headerAuthCode');
    const headerAuthValue = document.getElementById('headerAuthCodeValue');
    if (headerAuth && headerAuthValue) {
        if (latestCode) {
            headerAuthValue.textContent = latestCode;
            headerAuth.dataset.code = latestCode;
            headerAuth.style.background = '#4caf50';
        } else {
            headerAuthValue.textContent = '------';
            headerAuth.dataset.code = '';
            headerAuth.style.background = '#999';
        }
    }

    // 각 폰별 인증코드 표시
    phones.forEach(p => {
        const container = document.getElementById(`code-container-${p}`);
        const codeEl = document.getElementById(`code-${p}`);
        const timeEl = document.getElementById(`code-time-${p}`);

        if (codeEl) {
            const info = authCodes[p];
            if (info && typeof info === 'object') {
                codeEl.textContent = info.code || '------';
                if (timeEl) timeEl.textContent = info.time || '';
            } else {
                codeEl.textContent = info || '------';
                if (timeEl) timeEl.textContent = '';
            }
        }

        // 최신 인증코드 강조
        if (container) {
            container.classList.toggle('latest', p === latestPhone);
        }
    });
}

// 헤더 인증번호 복사
function copyHeaderAuthCode() {
    const headerAuth = document.getElementById('headerAuthCode');
    const code = headerAuth?.dataset.code;
    if (code && code !== '') {
        // clipboard API 시도, 실패 시 fallback
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(code).then(() => {
                showToast(`인증번호 ${code} 복사됨`, 'success');
            }).catch(() => {
                fallbackCopy(code);
            });
        } else {
            fallbackCopy(code);
        }
    } else {
        showToast('복사할 인증번호 없음', 'error');
    }
}

// fallback 복사 (textarea 이용)
function fallbackCopy(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
        document.execCommand('copy');
        showToast(`인증번호 ${text} 복사됨`, 'success');
    } catch (e) {
        showToast('복사 실패', 'error');
    }
    document.body.removeChild(textarea);
}

async function launchPhone(phone) {
    const btn = document.querySelector(`.phone-btn[data-phone="${phone}"]`);
    btn.classList.add('launching');
    btn.querySelector('.status').textContent = '...';
    try {
        const r = await fetch(`/api/sms/launch/${phone}`, { method: 'POST' });
        const d = await r.json();
        btn.classList.remove('launching');
        if (d.ready) {
            btn.classList.add('ready');
            btn.querySelector('.status').textContent = '✓';
            showToast(`${phone} 준비됨`, 'success');
        }
    } catch (e) {
        btn.classList.remove('launching');
        btn.querySelector('.status').textContent = '✗';
        showToast(`${phone} 실패`, 'error');
    }
}

async function launchAllPhones() {
    showToast('전체 실행 중...');
    try {
        await fetch('/api/sms/launch-all', { method: 'POST' });
        await loadSMSStatus();
        showToast('전체 실행됨', 'success');
    } catch (e) {
        showToast('실패', 'error');
    }
}

async function refreshMessages(force = false) {
    // 검색 모드나 대화 상세 보는 중이면 자동 새로고침 스킵 (수동은 허용)
    if (!force && smsViewMode !== 'list') {
        console.log('[SMS] 자동새로고침 스킵 - 현재 모드:', smsViewMode);
        return;
    }

    try {
        // force=true면 서버에서 실제로 새로고침, 아니면 캐시 반환
        const url = force ? '/api/sms/messages?refresh=true' : '/api/sms/messages';
        const r = await fetch(url);
        const d = await r.json();
        authCodes = d.auth_codes || {};
        updateAuthCodes();

        // 번호별로 메시지 분리
        const phoneNumbers = ['8295', '8217', '4682'];
        const messagesByPhone = {
            '8295': [],
            '8217': [],
            '4682': []
        };

        d.messages.forEach(m => {
            const phone = m.phone_profile;
            if (messagesByPhone[phone]) {
                messagesByPhone[phone].push(m);
            }
        });

        // 각 패널에 메시지 렌더링 (20개만 표시 + 더보기)
        const DISPLAY_LIMIT = 20;
        phoneNumbers.forEach(phone => {
            const panel = document.getElementById(`messages-${phone}`);
            if (!panel) return;

            const messages = messagesByPhone[phone];
            if (messages.length === 0) {
                panel.innerHTML = '<div class="empty">메시지 없음</div>';
                return;
            }

            // 표시할 메시지 (처음 20개)
            const displayMessages = messages.slice(0, DISPLAY_LIMIT);
            const hasMore = messages.length > DISPLAY_LIMIT;

            let html = displayMessages.map(m => {
                // HTML 이스케이프 처리
                const safeContent = (m.content || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                const safeSender = (m.sender || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                const senderForJs = m.sender.replace(/'/g, "\\'").replace(/"/g, '\\"');
                return `
                <div class="msg-item ${m.unread ? 'unread' : ''}" onclick="openConversation('${m.phone_profile}', '${senderForJs}'); setReplyTarget('${phone}', '${senderForJs}')">
                    <div class="msg-sender">${safeSender}</div>
                    <div class="msg-preview">${safeContent}</div>
                    <div class="msg-time-row" style="display:flex;justify-content:space-between;align-items:center;">
                        <span class="msg-time">${m.timestamp || ''}</span>
                        ${m.unread ? '<span style="background:#4caf50;color:white;font-size:10px;padding:2px 6px;border-radius:3px;">안읽음</span>' : ''}
                    </div>
                    ${m.auth_code ? `<span class="message-code" style="background:#4caf50;color:white;padding:2px 6px;border-radius:3px;font-size:11px;">${m.auth_code}</span>` : ''}
                </div>
            `}).join('');

            // 더보기 버튼 (20개 초과 시)
            if (hasMore) {
                html += `<button class="load-more-panel-btn" onclick="event.stopPropagation(); loadMorePanelMessages('${phone}')" style="width:100%;padding:10px;background:#f0f0f0;border:none;cursor:pointer;font-size:12px;color:#666;">
                    ⬇️ 더보기 (${messages.length - DISPLAY_LIMIT}개 남음)
                </button>`;
            }

            panel.innerHTML = html;

            // 전체 메시지 저장 (더보기용)
            panel.dataset.allMessages = JSON.stringify(messages);
            panel.dataset.displayCount = DISPLAY_LIMIT;
        });

        // 번호별로 20개씩 캐시 (총 60개)
        const messagesToPreload = [];
        phoneNumbers.forEach(phone => {
            const phoneMessages = d.messages.filter(m => m.phone_profile === phone).slice(0, 20);
            messagesToPreload.push(...phoneMessages);
        });
        preloadRecentConversations(messagesToPreload);

    } catch (e) { console.error(e); }
}

// SMS 패널 더보기
function loadMorePanelMessages(phone) {
    const panel = document.getElementById(`messages-${phone}`);
    if (!panel) return;

    const messages = JSON.parse(panel.dataset.allMessages || '[]');
    let displayCount = parseInt(panel.dataset.displayCount || '20');
    displayCount += 20;  // 20개씩 추가

    const displayMessages = messages.slice(0, displayCount);
    const hasMore = messages.length > displayCount;

    let html = displayMessages.map(m => {
        // HTML 이스케이프 처리
        const safeContent = (m.content || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const safeSender = (m.sender || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const senderForJs = m.sender.replace(/'/g, "\\'").replace(/"/g, '\\"');
        return `
        <div class="msg-item ${m.unread ? 'unread' : ''}" onclick="openConversation('${m.phone_profile}', '${senderForJs}'); setReplyTarget('${phone}', '${senderForJs}')">
            <div class="msg-sender">${safeSender}</div>
            <div class="msg-preview">${safeContent}</div>
            <div class="msg-time-row" style="display:flex;justify-content:space-between;align-items:center;">
                <span class="msg-time">${m.timestamp || ''}</span>
                ${m.unread ? '<span style="background:#4caf50;color:white;font-size:10px;padding:2px 6px;border-radius:3px;">안읽음</span>' : ''}
            </div>
            ${m.auth_code ? `<span class="message-code" style="background:#4caf50;color:white;padding:2px 6px;border-radius:3px;font-size:11px;">${m.auth_code}</span>` : ''}
        </div>
    `}).join('');

    if (hasMore) {
        html += `<button class="load-more-panel-btn" onclick="event.stopPropagation(); loadMorePanelMessages('${phone}')" style="width:100%;padding:10px;background:#f0f0f0;border:none;cursor:pointer;font-size:12px;color:#666;">
            ⬇️ 더보기 (${messages.length - displayCount}개 남음)
        </button>`;
    }

    panel.innerHTML = html;
    panel.dataset.displayCount = displayCount;
}

// 메시지 클릭 시 답장 대상 설정
function setReplyTarget(phone, sender) {
    const sendToInput = document.getElementById(`sendTo-${phone}`);
    if (sendToInput) {
        // 번호만 추출 (숫자만)
        const numberOnly = sender.replace(/[^0-9]/g, '');
        sendToInput.value = numberOnly || sender;
    }
}

// 파일 선택 시 미리보기
function onFileSelected(phone) {
    const fileInput = document.getElementById(`sendFile-${phone}`);
    const preview = document.getElementById(`filePreview-${phone}`);

    if (fileInput.files.length > 0) {
        const file = fileInput.files[0];
        preview.querySelector('.file-name').textContent = file.name;
        preview.style.display = 'flex';
    }
}

// 파일 첨부 취소
function clearFileAttachment(phone) {
    const fileInput = document.getElementById(`sendFile-${phone}`);
    const preview = document.getElementById(`filePreview-${phone}`);

    fileInput.value = '';
    preview.style.display = 'none';
}

// 드래그앤드롭으로 파일 첨부
function handleFileDrop(phone, file) {
    const fileInput = document.getElementById(`sendFile-${phone}`);
    const preview = document.getElementById(`filePreview-${phone}`);

    // 허용된 파일 타입 확인
    const allowedTypes = ['image/', 'video/', 'application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'];
    const isAllowed = allowedTypes.some(type => file.type.startsWith(type) || file.type === type);

    if (!isAllowed) {
        showToast('이미지, 동영상, PDF, DOC 파일만 첨부 가능합니다', 'error');
        return;
    }

    // DataTransfer를 사용하여 file input에 파일 설정
    const dt = new DataTransfer();
    dt.items.add(file);
    fileInput.files = dt.files;

    // 미리보기 표시
    preview.querySelector('.file-name').textContent = file.name;
    preview.style.display = 'flex';
}

// SMS 패널에 드래그앤드롭 이벤트 초기화
function initSmsPanelDragDrop() {
    const panels = document.querySelectorAll('.sms-panel');

    panels.forEach(panel => {
        const phone = panel.dataset.phone;
        const sendArea = panel.querySelector('.panel-send');

        if (!sendArea) return;

        // 드래그 오버 (드래그 중 영역 위에 있을 때)
        sendArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.stopPropagation();
            sendArea.classList.add('drag-over');
        });

        // 드래그 떠남 (영역을 벗어날 때)
        sendArea.addEventListener('dragleave', (e) => {
            e.preventDefault();
            e.stopPropagation();
            sendArea.classList.remove('drag-over');
        });

        // 드롭 (파일 놓을 때)
        sendArea.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            sendArea.classList.remove('drag-over');

            const files = e.dataTransfer.files;
            if (files.length > 0) {
                handleFileDrop(phone, files[0]);  // 첫 번째 파일만 처리
            }
        });
    });
}

// 패널에서 SMS 전송 (파일 첨부 지원)
async function sendSMSFromPanel(phone) {
    const sendTo = document.getElementById(`sendTo-${phone}`);
    const sendMsg = document.getElementById(`sendMsg-${phone}`);
    const fileInput = document.getElementById(`sendFile-${phone}`);

    if (!sendTo || !sendMsg) return;

    const to = sendTo.value.trim();
    const message = sendMsg.value.trim();
    const hasFile = fileInput && fileInput.files.length > 0;

    if (!to) {
        showToast('수신번호를 입력하세요', 'error');
        return;
    }
    if (!message && !hasFile) {
        showToast('메시지 또는 파일을 입력하세요', 'error');
        return;
    }

    try {
        let r, d;

        if (hasFile) {
            // 파일 첨부가 있으면 FormData로 전송
            const formData = new FormData();
            formData.append('phone_profile', phone);
            formData.append('to_number', to);
            formData.append('message', message);
            formData.append('file', fileInput.files[0]);

            r = await fetch('/api/sms/send-with-file', {
                method: 'POST',
                body: formData
            });
        } else {
            // 텍스트만 전송
            r = await fetch('/api/sms/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone_profile: phone, to_number: to, message: message })
            });
        }

        d = await r.json();

        if (d.success) {
            showToast(`[${phone}] 메시지 전송 완료`, 'success');
            sendMsg.value = '';
            sendMsg.style.height = 'auto';
            clearFileAttachment(phone);  // 파일 첨부 초기화
            setTimeout(() => refreshMessages(true), 2000);
        } else {
            showToast(`전송 실패: ${d.message || d.detail}`, 'error');
        }
    } catch (e) {
        showToast('전송 오류', 'error');
        console.error(e);
    }
}

// 특정 번호의 검색 모달 열기
function openSearchModalForPhone(phone) {
    // 기존 검색 모달 열기
    openSearchModal();
    // 해당 번호로 프로필 기본 선택
    const profileSelect = document.getElementById('searchProfile');
    if (profileSelect) {
        profileSelect.value = phone;
    }
    // 검색 후 해당 번호 패널에 결과 표시하도록 설정
    window.currentSearchPhone = phone;
}

// 대화 캐시 저장소 (최대 20개 대화 유지)
const conversationCache = {};
const MAX_CONVERSATION_CACHE = 20;

// 캐시 정리 (오래된 것부터 삭제)
function cleanConversationCache() {
    const keys = Object.keys(conversationCache);
    if (keys.length <= MAX_CONVERSATION_CACHE) return;

    // cachedAt 기준 정렬 (오래된 것 먼저)
    keys.sort((a, b) => {
        const aTime = conversationCache[a].cachedAt || 0;
        const bTime = conversationCache[b].cachedAt || 0;
        return aTime - bTime;
    });

    // 초과분 삭제
    const toDelete = keys.length - MAX_CONVERSATION_CACHE;
    for (let i = 0; i < toDelete; i++) {
        delete conversationCache[keys[i]];
        console.log(`[캐시] 삭제: ${keys[i]} (오래된 캐시 정리)`);
    }
}

// 캐시 통계
function getCacheStats() {
    const keys = Object.keys(conversationCache);
    let totalMessages = 0;
    keys.forEach(k => {
        totalMessages += conversationCache[k].messages?.length || 0;
    });
    return { conversations: keys.length, messages: totalMessages, maxConversations: MAX_CONVERSATION_CACHE };
}

// 최근 대화 미리 로드 (캐시 누적)
async function preloadRecentConversations(messages) {
    let newLoaded = 0;
    let skipped = 0;

    for (const m of messages) {
        const cacheKey = `${m.phone_profile}_${m.sender}`;

        // 이미 캐시되어 있으면 스킵
        if (conversationCache[cacheKey]) {
            console.log(`[캐시] ${m.sender} 이미 존재 - 스킵`);
            skipped++;
            continue;
        }

        try {
            console.log(`[미리로드] ${m.sender} 대화 로딩...`);
            const r = await fetch('/api/sms/conversation', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ profile_id: m.phone_profile, sender: m.sender })
            });
            const d = await r.json();

            if (!d.error && d.messages) {
                // 캐시에 저장
                conversationCache[cacheKey] = {
                    profile_id: m.phone_profile,
                    sender: m.sender,
                    messages: d.messages,
                    timestamp: Date.now(),
                    hasMore: d.has_more,
                    totalCount: d.total_count
                };
                console.log(`[미리로드] ${m.sender} 완료 (메시지 ${d.messages.length}개)`);
                newLoaded++;

                // 이미지가 있으면 미리 다운로드
                preloadConversationImages(m.phone_profile, m.sender, d.messages);
            }
        } catch (e) {
            console.log(`[미리로드] ${m.sender} 실패`);
        }

        // 서버 부하 방지 - 0.5초 간격
        await new Promise(resolve => setTimeout(resolve, 500));
    }

    // 캐시 통계 출력
    const stats = getCacheStats();
    console.log(`[캐시] 새로 ${newLoaded}개 로드, ${skipped}개 스킵 | 총 ${stats.conversations}개 대화, ${stats.messages}개 메시지`);
}

// 캐시에서 텍스트 검색
function searchInCache(keyword) {
    const results = [];
    const lowerKeyword = keyword.toLowerCase();

    Object.entries(conversationCache).forEach(([key, data]) => {
        if (!data.messages) return;

        data.messages.forEach((msg, idx) => {
            if (msg.text && msg.text.toLowerCase().includes(lowerKeyword)) {
                results.push({
                    cacheKey: key,
                    profile_id: data.profile_id,
                    sender: data.sender,
                    messageIndex: idx,
                    text: msg.text,
                    timestamp: msg.timestamp,
                    direction: msg.direction
                });
            }
        });
    });

    return results;
}

// 대화 내 이미지 미리 다운로드
async function preloadConversationImages(profileId, sender, messages) {
    for (const msg of messages) {
        if (!msg.images || msg.images.length === 0) continue;

        for (const img of msg.images) {
            try {
                // 썸네일 다운로드
                const thumbRes = await fetch('/api/sms/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        profile_id: profileId,
                        sender: sender,
                        media_type: 'image',
                        element_idx: img.element_idx,
                        get_thumbnail: true
                    })
                });
                const thumbData = await thumbRes.json();

                if (thumbData.success) {
                    // 캐시에 썸네일 경로 저장
                    img.thumbnail = thumbData.filepath;
                    console.log(`[미리로드] 이미지 ${img.element_idx} 썸네일 완료`);

                    // 원본도 미리 다운로드
                    const fullRes = await fetch('/api/sms/download', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            profile_id: profileId,
                            sender: sender,
                            media_type: 'image',
                            element_idx: img.element_idx,
                            get_thumbnail: false
                        })
                    });
                    const fullData = await fullRes.json();

                    if (fullData.success) {
                        img.fullImage = fullData.filepath;
                        console.log(`[미리로드] 이미지 ${img.element_idx} 원본 완료`);
                    }
                }
            } catch (e) {
                console.log(`[미리로드] 이미지 다운로드 실패`);
            }

            // 이미지 간 간격
            await new Promise(resolve => setTimeout(resolve, 300));
        }
    }
}

// 대화 상세 열기 (캐시 우선 사용)
let currentOffset = 0;  // 현재 offset
let hasMoreMessages = true;  // 더 이전 메시지 있는지

async function openConversation(profileId, sender) {
    // 이미 로딩 중이면 무시
    if (window._conversationLoading) {
        console.log('[대화] 이미 로딩 중, 스킵');
        return;
    }
    window._conversationLoading = true;

    smsViewMode = 'conversation';  // 대화 모드로 전환
    currentConversation = { profile_id: profileId, sender: sender };
    currentOffset = 0;
    hasMoreMessages = true;

    document.getElementById('conversationModal').classList.add('show');
    document.getElementById('conversationTitle').textContent = `💬 ${sender} 대화 내역`;
    updateLoadMoreButton();

    // 템플릿 버튼 초기화 (최초 1회)
    initTemplateButton();

    // 캐시 키
    const cacheKey = `${profileId}_${sender}`;

    // 캐시에 있으면 즉시 표시
    if (conversationCache[cacheKey] && conversationCache[cacheKey].messages?.length > 0) {
        console.log(`[대화] 캐시에서 로드: ${cacheKey}`);
        document.getElementById('conversationLoading').style.display = 'none';
        window._conversationLoading = false;

        hasMoreMessages = conversationCache[cacheKey].hasMore !== false;
        updateLoadMoreButton();

        renderConversationMessages(conversationCache[cacheKey].messages, true);
        return;
    }

    // 캐시 없으면 서버에서 로드
    document.getElementById('conversationLoading').style.display = 'block';
    document.getElementById('conversationMessages').innerHTML = '';

    console.log(`[대화] 서버 요청: profile=${profileId}, sender=${sender}`);

    try {
        const r = await fetch('/api/sms/conversation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ profile_id: profileId, sender: sender, offset: 0, limit: 20 })
        });

        console.log(`[대화] 응답 상태: ${r.status}`);

        const d = await r.json();

        console.log(`[대화] 결과:`, d);

        document.getElementById('conversationLoading').style.display = 'none';
        window._conversationLoading = false;

        if (d.error) {
            document.getElementById('conversationMessages').innerHTML = `<div class="empty">${d.error}</div>`;
            return;
        }

        // 메시지가 없으면
        if (!d.messages || d.messages.length === 0) {
            document.getElementById('conversationMessages').innerHTML = '<div class="empty">메시지 없음</div>';
            return;
        }

        // 캐시에 저장
        conversationCache[cacheKey] = {
            messages: d.messages,
            hasMore: d.has_more,
            cachedAt: Date.now()
        };

        // 캐시 정리 (최대 20개 유지)
        cleanConversationCache();

        hasMoreMessages = d.has_more;
        updateLoadMoreButton();

        renderConversationMessages(d.messages, false);

    } catch (e) {
        console.error('[대화] 오류:', e);
        document.getElementById('conversationLoading').style.display = 'none';
        document.getElementById('conversationMessages').innerHTML = '<div class="empty">불러오기 실패</div>';
        window._conversationLoading = false;
    }
}

// 대화 새로고침 (내용 안 나올 때)
async function refreshConversation() {
    if (!currentConversation || !currentConversation.profile_id) {
        showToast('새로고침할 대화가 없습니다', 'error');
        return;
    }

    showToast('대화 새로고침 중...', 'info');

    // 캐시 삭제
    const cacheKey = `${currentConversation.profile_id}_${currentConversation.sender}`;
    delete conversationCache[cacheKey];

    // 로딩 플래그 해제 후 다시 로드
    window._conversationLoading = false;
    await openConversation(currentConversation.profile_id, currentConversation.sender);
}

// 현재 대화 새로고침 (메시지 전송 후 호출)
async function refreshCurrentConversation() {
    if (!currentConversation || !currentConversation.profile_id) return;

    // 캐시 삭제하여 새로운 메시지 가져오기
    const cacheKey = `${currentConversation.profile_id}_${currentConversation.sender}`;
    delete conversationCache[cacheKey];

    window._conversationLoading = false;
    await openConversation(currentConversation.profile_id, currentConversation.sender);
}

// 이전 메시지 더 불러오기
async function loadMoreMessages() {
    if (!currentConversation || !hasMoreMessages) return;

    const btn = document.getElementById('loadMoreBtn');
    btn.disabled = true;
    btn.classList.add('loading');
    btn.textContent = '⏳ 로딩 중...';

    currentOffset += 20;

    try {
        const r = await fetch('/api/sms/conversation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                profile_id: currentConversation.profile_id,
                sender: currentConversation.sender,
                offset: currentOffset,
                limit: 20
            })
        });
        const d = await r.json();

        if (d.error) {
            showToast(d.error, 'error');
            return;
        }

        hasMoreMessages = d.has_more;

        if (d.messages && d.messages.length > 0) {
            // 기존 메시지 앞에 추가
            prependMessages(d.messages);
            showToast(`이전 메시지 ${d.messages.length}개 로드됨`, 'success');

            // 캐시 업데이트
            const cacheKey = `${currentConversation.profile_id}_${currentConversation.sender}`;
            if (conversationCache[cacheKey]) {
                conversationCache[cacheKey].messages = [...d.messages, ...conversationCache[cacheKey].messages];
                conversationCache[cacheKey].hasMore = d.has_more;
            }
        } else {
            hasMoreMessages = false;
            showToast('더 이상 이전 메시지가 없습니다', 'info');
        }

    } catch (e) {
        showToast('불러오기 실패', 'error');
    } finally {
        btn.disabled = false;
        btn.classList.remove('loading');
        updateLoadMoreButton();
    }
}

// 이전 메시지 목록 앞에 추가
function prependMessages(messages) {
    const container = document.getElementById('conversationMessages');
    const scrollTop = container.scrollTop;
    const scrollHeight = container.scrollHeight;

    // 새 메시지 HTML 생성
    const newHtml = messages.map((msg, idx) => {
        return renderSingleMessage(msg);
    }).join('');

    // 앞에 추가
    container.innerHTML = newHtml + container.innerHTML;

    // 스크롤 위치 유지 (새로 추가된 만큼 아래로)
    container.scrollTop = scrollTop + (container.scrollHeight - scrollHeight);

    // 이미지 자동 다운로드
    autoDownloadImages();
}

// 단일 메시지 렌더링
function renderSingleMessage(msg) {
    // 타임스탬프 구분선 처리
    if (msg.type === 'timestamp_divider') {
        return `<div class="conv-timestamp-divider">
            <span>${msg.timestamp}</span>
        </div>`;
    }

    let html = `<div class="conv-msg ${msg.direction}">`;
    html += `<div class="conv-msg-bubble">`;

    if (msg.text) {
        let text = msg.text;
        (msg.urls || []).forEach(url => {
            text = text.replace(url, `<a href="${url}" target="_blank" class="conv-msg-url">${url}</a>`);
        });
        html += `<div>${text}</div>`;
    }

    if (msg.images && msg.images.length > 0) {
        html += `<div class="conv-media">`;
        msg.images.forEach(img => {
            if (img.thumbnail) {
                html += `<div class="conv-img-container" data-element-idx="${img.element_idx}" 
                            data-loaded="true" data-thumbnail="${img.thumbnail}" 
                            ${img.fullImage ? `data-full-image="${img.fullImage}"` : ''}>
                    <img src="${img.thumbnail}" class="conv-img-thumb" 
                        onclick="openImageViewer('${img.element_idx}')" 
                        title="클릭하여 원본 보기">
                </div>`;
            } else {
                html += `<div class="conv-img-container" data-element-idx="${img.element_idx}" data-loaded="false">
                    <div class="conv-img-loading">🔄 다운로드 중...</div>
                </div>`;
            }
        });
        html += `</div>`;
    }

    if (msg.videos && msg.videos.length > 0) {
        html += `<div class="conv-media">`;
        msg.videos.forEach(vid => {
            html += `<button class="conv-video-btn" onclick="downloadMedia('video', '${vid.element_idx}')">
                📹 동영상 <span>💾</span>
            </button>`;
        });
        html += `</div>`;
    }

    if (msg.files && msg.files.length > 0) {
        html += `<div class="conv-media">`;
        msg.files.forEach(file => {
            html += `<button class="conv-file-btn" onclick="downloadMedia('file', '${file.element_idx}')">
                📎 ${file.filename} <span>💾</span>
            </button>`;
        });
        html += `</div>`;
    }

    html += `</div>`;
    if (msg.timestamp) {
        html += `<div class="conv-msg-time">${msg.timestamp}</div>`;
    }
    html += `</div>`;

    return html;
}

// 더보기 버튼 상태 업데이트
function updateLoadMoreButton() {
    const btn = document.getElementById('loadMoreBtn');
    if (hasMoreMessages) {
        btn.style.display = 'inline-block';
        btn.textContent = '⬆️ 이전 20개';
    } else {
        btn.style.display = 'none';
    }
}

// 대화 메시지 렌더링 (fromCache: 캐시에서 불러온 경우)
function renderConversationMessages(messages, fromCache = false) {
    const container = document.getElementById('conversationMessages');

    if (!messages || messages.length === 0) {
        container.innerHTML = '<div class="empty">메시지 없음</div>';
        return;
    }

    container.innerHTML = messages.map((msg, idx) => {
        // 타임스탬프 구분선 처리
        if (msg.type === 'timestamp_divider') {
            return `<div class="conv-timestamp-divider">
                <span>${msg.timestamp}</span>
            </div>`;
        }

        let html = `<div class="conv-msg ${msg.direction}">`;
        html += `<div class="conv-msg-bubble">`;

        // 텍스트 (URL 링크 처리)
        if (msg.text) {
            let text = msg.text;
            // URL을 링크로 변환
            (msg.urls || []).forEach(url => {
                text = text.replace(url, `<a href="${url}" target="_blank" class="conv-msg-url">${url}</a>`);
            });
            html += `<div>${text}</div>`;
        }

        // 이미지 (캐시된 경우 바로 표시, 아니면 로딩)
        if (msg.images && msg.images.length > 0) {
            html += `<div class="conv-media">`;
            msg.images.forEach(img => {
                if (img.thumbnail) {
                    // 캐시된 이미지 - 바로 표시
                    html += `<div class="conv-img-container" data-element-idx="${img.element_idx}" 
                                data-loaded="true" data-thumbnail="${img.thumbnail}" 
                                ${img.fullImage ? `data-full-image="${img.fullImage}"` : ''}>
                        <img src="${img.thumbnail}" class="conv-img-thumb" 
                            onclick="openImageViewer('${img.element_idx}')" 
                            title="클릭하여 원본 보기">
                    </div>`;
                } else {
                    // 캐시 안됨 - 로딩 표시
                    html += `<div class="conv-img-container" data-element-idx="${img.element_idx}" data-loaded="false">
                        <div class="conv-img-loading">🔄 다운로드 중...</div>
                    </div>`;
                }
            });
            html += `</div>`;
        }

        // 동영상
        if (msg.videos && msg.videos.length > 0) {
            html += `<div class="conv-media">`;
            msg.videos.forEach(vid => {
                html += `<button class="conv-video-btn" onclick="downloadMedia('video', '${vid.element_idx}')">
                    📹 동영상 <span>💾</span>
                </button>`;
            });
            html += `</div>`;
        }

        // 파일
        if (msg.files && msg.files.length > 0) {
            html += `<div class="conv-media">`;
            msg.files.forEach(file => {
                html += `<button class="conv-file-btn" onclick="downloadMedia('file', '${file.element_idx}')">
                    📎 ${file.filename} <span>💾</span>
                </button>`;
            });
            html += `</div>`;
        }

        html += `</div>`; // conv-msg-bubble

        // 시간
        if (msg.timestamp) {
            html += `<div class="conv-msg-time">${msg.timestamp}</div>`;
        }

        html += `</div>`; // conv-msg
        return html;
    }).join('');

    // 스크롤 맨 아래로
    container.scrollTop = container.scrollHeight;

    // 이미지 자동 다운로드 시작
    autoDownloadImages();
}

// 이미지 자동 다운로드 (썸네일 + 원본 모두)
async function autoDownloadImages() {
    const containers = document.querySelectorAll('.conv-img-container[data-loaded="false"]');

    for (const container of containers) {
        const elementIdx = container.dataset.elementIdx;
        if (!elementIdx) continue;

        try {
            // 1. 썸네일 다운로드
            const thumbRes = await fetch('/api/sms/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    profile_id: currentConversation.profile_id,
                    sender: currentConversation.sender,
                    media_type: 'image',
                    element_idx: elementIdx,
                    get_thumbnail: true
                })
            });
            const thumbData = await thumbRes.json();

            if (thumbData.success && thumbData.filepath) {
                // 썸네일 표시
                container.dataset.loaded = "true";
                container.dataset.thumbnail = thumbData.filepath;
                container.innerHTML = `<img src="${thumbData.filepath}" class="conv-img-thumb" 
                    onclick="openImageViewer('${elementIdx}')" 
                    title="클릭하여 원본 보기">`;

                // 2. 원본도 백그라운드에서 미리 다운로드
                downloadFullImageInBackground(elementIdx);
            } else {
                container.innerHTML = `<div class="conv-img-error">❌ 이미지 로드 실패</div>`;
            }
        } catch (e) {
            container.innerHTML = `<div class="conv-img-error">❌ 오류</div>`;
        }
    }
}

// 원본 이미지 백그라운드 다운로드
async function downloadFullImageInBackground(elementIdx) {
    const container = document.querySelector(`[data-element-idx="${elementIdx}"]`);
    if (!container) return;

    try {
        const fullRes = await fetch('/api/sms/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                profile_id: currentConversation.profile_id,
                sender: currentConversation.sender,
                media_type: 'image',
                element_idx: elementIdx,
                get_thumbnail: false  // 원본
            })
        });
        const fullData = await fullRes.json();

        if (fullData.success && fullData.filepath) {
            // 원본 경로 저장
            container.dataset.fullImage = fullData.filepath;
            console.log(`[${elementIdx}] 원본 다운로드 완료: ${fullData.filepath}`);
        }
    } catch (e) {
        console.log(`[${elementIdx}] 원본 다운로드 실패`);
    }
}

// 대화 모달 닫기
function closeConversationModal() {
    document.getElementById('conversationModal').classList.remove('show');
    smsViewMode = 'list';  // 목록 모드로 복구
    window._conversationLoading = false;  // 로딩 플래그 해제

    // 템플릿 패널도 함께 닫기
    const panel = document.getElementById('smsTemplatePanel');
    const btn = document.getElementById('templateToggleBtn');
    if (panel) {
        panel.classList.remove('show');
    }
    if (btn) {
        btn.classList.remove('active');
    }
    templatePanelVisible = false;
}

// 이 번호로 전송 선택
function selectSenderFromModal() {
    const sender = currentConversation.sender;
    const profileId = currentConversation.profile_id;

    if (!profileId || !sender) {
        showToast('발신자 정보가 없습니다', 'error');
        return;
    }

    // 번호 정리
    const cleanNumber = sender.replace(/[^0-9]/g, '');

    // 해당 프로필의 수신번호 입력란에 값 설정
    const sendToInput = document.getElementById(`sendTo-${profileId}`);
    const sendMsgInput = document.getElementById(`sendMsg-${profileId}`);

    if (sendToInput) {
        sendToInput.value = cleanNumber;
    }

    closeConversationModal();

    // 해당 입력란에 포커스
    if (sendMsgInput) {
        sendMsgInput.focus();
    }

    showToast(`${profileId} 패널에 ${cleanNumber} 설정됨`, 'success');
}

// 대화 모달에서 바로 전송
async function sendFromConversationModal() {
    const sender = currentConversation.sender;
    const profileId = currentConversation.profile_id;
    const input = document.getElementById('conversationInput');
    const message = input?.value?.trim();
    const sendBtn = document.getElementById('conversationSendBtn');

    if (!profileId || !sender) {
        showToast('발신자 정보가 없습니다', 'error');
        return;
    }

    if (!message) {
        showToast('메시지를 입력하세요', 'error');
        return;
    }

    // 버튼 로딩 상태
    if (sendBtn) {
        sendBtn.disabled = true;
        sendBtn.innerHTML = '⏳ 전송중...';
        sendBtn.style.opacity = '0.6';
    }

    // 번호 정리
    const toNumber = sender.replace(/[^0-9]/g, '');

    try {
        const r = await fetch('/api/sms/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                phone_profile: profileId,
                to_number: toNumber,
                message: message
            })
        });

        const d = await r.json();

        if (d.success) {
            showToast('메시지 전송 완료', 'success');
            input.value = '';
            // 대화 내역 새로고침
            setTimeout(() => {
                refreshCurrentConversation();
                refreshMessages(true);
            }, 2000);
        } else {
            showToast(`전송 실패: ${d.message || d.detail}`, 'error');
        }
    } catch (e) {
        showToast(`전송 오류: ${e.message}`, 'error');
    } finally {
        // 버튼 복구
        if (sendBtn) {
            sendBtn.disabled = false;
            sendBtn.innerHTML = '📤 전송';
            sendBtn.style.opacity = '1';
        }
    }
}

// 이미지 뷰어 열기 (이미 다운로드된 원본 사용)
async function openImageViewer(elementIdx) {
    const container = document.querySelector(`[data-element-idx="${elementIdx}"]`);

    document.getElementById('imageViewerModal').classList.add('show');

    // 이미 원본이 다운로드되어 있으면 바로 표시
    if (container && container.dataset.fullImage) {
        document.getElementById('imageViewerImg').src = container.dataset.fullImage;
        document.getElementById('imageViewerImg').style.display = 'block';
        document.getElementById('imageViewerLoading').style.display = 'none';
        return;
    }

    // 원본이 아직 없으면 썸네일이라도 표시
    if (container && container.dataset.thumbnail) {
        document.getElementById('imageViewerImg').src = container.dataset.thumbnail;
        document.getElementById('imageViewerImg').style.display = 'block';
        document.getElementById('imageViewerLoading').style.display = 'none';
        return;
    }

    // 둘 다 없으면 다운로드 시도
    document.getElementById('imageViewerImg').style.display = 'none';
    document.getElementById('imageViewerLoading').style.display = 'block';

    try {
        const r = await fetch('/api/sms/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                profile_id: currentConversation.profile_id,
                sender: currentConversation.sender,
                media_type: 'image',
                element_idx: elementIdx,
                get_thumbnail: false
            })
        });
        const d = await r.json();

        document.getElementById('imageViewerLoading').style.display = 'none';

        if (d.success && d.filepath) {
            document.getElementById('imageViewerImg').src = d.filepath;
            document.getElementById('imageViewerImg').style.display = 'block';
        } else {
            closeImageViewer();
            showToast('이미지 로드 실패', 'error');
        }
    } catch (e) {
        closeImageViewer();
        showToast('오류 발생', 'error');
    }
}

// 이미지 뷰어 닫기
function closeImageViewer() {
    document.getElementById('imageViewerModal').classList.remove('show');
}

// 미디어 다운로드 (동영상/파일)
async function downloadMedia(mediaType, elementIdx) {
    showToast('다운로드 중...', 'info');

    try {
        const r = await fetch('/api/sms/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                profile_id: currentConversation.profile_id,
                sender: currentConversation.sender,
                media_type: mediaType,
                element_idx: elementIdx
            })
        });
        const d = await r.json();

        if (d.success && d.filepath) {
            // 다운로드 링크 생성
            const a = document.createElement('a');
            a.href = d.filepath;
            a.download = d.filepath.split('/').pop();
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            showToast('다운로드 완료', 'success');
        } else {
            showToast('다운로드 실패', 'error');
        }
    } catch (e) {
        showToast('오류 발생', 'error');
    }
}

function toggleAutoRefresh() {
    const c = document.getElementById('autoRefresh').checked;
    if (c) {
        autoRefreshInterval = setInterval(() => refreshMessages(true), 15000);  // 15초마다 새로고침
        refreshMessages(true);
    } else {
        clearInterval(autoRefreshInterval);
    }
}

// 구글메시지 창 F5 새로고침
async function reloadGoogleMessages() {
    try {
        showToast('구글메시지 창 새로고침 중...', 'info');
        const r = await fetch('/api/sms/reload-page', { method: 'POST' });
        const d = await r.json();
        if (d.success) {
            showToast('구글메시지 창 새로고침 완료', 'success');
            // 잠시 후 메시지 목록도 갱신
            setTimeout(() => refreshMessages(true), 3000);
        } else {
            showToast(d.message || '새로고침 실패', 'error');
        }
    } catch (e) {
        showToast('오류: ' + e.message, 'error');
    }
}

function copyCode(p) {
    const info = authCodes[p];
    const code = (info && typeof info === 'object') ? info.code : info;
    if (code && code !== '------') {
        copyToClipboard(code);
        showToast(`${p} 복사: ${code}`, 'success');
    } else {
        showToast('코드 없음', 'error');
    }
}

async function sendSMS() {
    const from = document.getElementById('sendFrom').value;
    const to = document.getElementById('sendTo').value;
    const msg = document.getElementById('sendMessage').value;
    if (!to || !msg) { showToast('수신번호와 메시지를 입력하세요', 'error'); return; }
    try {
        const r = await fetch('/api/sms/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone_profile: from, to_number: to, message: msg })
        });
        if (r.ok) {
            showToast('전송 완료', 'success');
            document.getElementById('sendMessage').value = '';
            // 전송 후 메시지 새로고침 (2초 후)
            setTimeout(() => refreshMessages(true), 2000);
        } else {
            showToast('전송 실패', 'error');
        }
    } catch (e) {
        showToast('오류', 'error');
    }
}

// 계정 관리
async function loadAccounts() {
    try {
        const r = await fetch('/api/accounts');
        const d = await r.json();
        accounts = d.accounts;
        platformCounts = d.platform_counts || {};
        totalCount = d.total_count || 0;
        renderAccounts();
        renderPlatformCounts();
    } catch (e) { console.error(e); }
}

// 계정관리 복수 선택 지원
let selectedAccountPlatforms = new Set(['전체']);

function renderPlatformCounts() {
    const countDiv = document.getElementById('platformCounts');
    if (!countDiv) return;

    const order = ['전체', '스마트스토어', '쿠팡', '11번가', 'ESM통합', '지마켓', '옥션'];
    let html = '';

    order.forEach(p => {
        let count;
        if (p === '전체') {
            count = totalCount;
        } else if (p === 'ESM통합') {
            // ESM통합은 지마켓+옥션 합산
            count = (platformCounts['ESM통합'] || 0) + (platformCounts['지마켓'] || 0) + (platformCounts['옥션'] || 0);
        } else {
            count = platformCounts[p] || 0;
        }
        const color = platformColors[p] || '#667eea';
        const isActive = selectedAccountPlatforms.has(p) ? 'active' : '';

        html += `<button class="platform-filter-btn ${isActive}"
                    data-platform="${p}"
                    style="--btn-color: ${color}"
                    onclick="filterPlatform('${p}', event)">
                ${p} <span class="pf-count">${count}</span>
            </button>`;
    });

    countDiv.innerHTML = html;
}

function filterPlatform(p, event) {
    const isCtrlKey = event && (event.ctrlKey || event.metaKey);

    if (p === '전체') {
        selectedAccountPlatforms.clear();
        selectedAccountPlatforms.add('전체');
    } else if (isCtrlKey) {
        // Ctrl+클릭: 복수 선택
        selectedAccountPlatforms.delete('전체');
        if (selectedAccountPlatforms.has(p)) {
            selectedAccountPlatforms.delete(p);
            if (selectedAccountPlatforms.size === 0) {
                selectedAccountPlatforms.add('전체');
            }
        } else {
            selectedAccountPlatforms.add(p);
        }
    } else {
        // 일반 클릭: 단일 선택
        selectedAccountPlatforms.clear();
        selectedAccountPlatforms.add(p);
    }

    // 호환성 유지
    currentPlatform = selectedAccountPlatforms.has('전체') ? '전체' : [...selectedAccountPlatforms][0];
    renderPlatformCounts();
    renderAccounts();
}

function getApiSummary(a) {
    if (a.platform === '스마트스토어') return a.ss_app_id ? `앱: ${a.ss_app_id.substring(0, 8)}...` : '-';
    if (a.platform === '쿠팡') return a.cp_vendor_code ? `업체: ${a.cp_vendor_code}` : '-';
    if (a.platform === '11번가') return a.st_api_key ? `API: ${a.st_api_key.substring(0, 8)}...` : '-';
    if (['ESM통합', '지마켓', '옥션'].includes(a.platform)) return a.esm_master ? `통합: ${a.esm_master}` : '-';
    return '-';
}

function renderAccounts() {
    const s = document.getElementById('searchInput').value.toLowerCase();
    const f = accounts.filter(a => {
        // 복수 선택 지원
        if (!selectedAccountPlatforms.has('전체')) {
            let matched = false;
            for (const p of selectedAccountPlatforms) {
                if (p === 'ESM통합') {
                    if (['ESM통합', '지마켓', '옥션'].includes(a.platform)) matched = true;
                } else {
                    if (a.platform === p) matched = true;
                }
            }
            if (!matched) return false;
        }
        if (s && !`${a.스토어명} ${a.login_id} ${a.business_number}`.toLowerCase().includes(s)) return false;
        return true;
    });
    document.getElementById('accountsTable').innerHTML = f.map(a => `
        <tr>
            <td><span class="platform-badge" style="background:${platformColors[a.platform] || '#666'}">${a.platform}</span></td>
            <td>${a.스토어명 || '-'}</td>
            <td>${a.login_id}</td>
            <td style="font-family:monospace;color:#999;">${a.password_masked || '●●●●●●'}</td>
            <td>${a.business_number || '-'}</td>
            <td style="max-width:120px;overflow:hidden;text-overflow:ellipsis;">${getApiSummary(a)}</td>
            <td class="actions">
                <button class="action-btn login" onclick="autoLoginChrome('${a.platform}','${a.login_id}')" title="자동 로그인">🔐</button>
                <button class="action-btn fill" onclick="openLoginPage('${a.platform}','${a.login_id}')" title="ID/PW 복사 (Win+V로 PW)">📋</button>
                <button class="action-btn" onclick="openLoginPageWithPW('${a.platform}','${a.login_id}')" title="로그인 페이지 + PW→ID 복사 (Win+V로 PW)" style="background:#9b59b6;">🔑</button>
                <button class="action-btn edit" onclick="openEditModal('${a.platform}','${a.login_id}')" title="수정">✏️</button>
                <button class="action-btn delete" onclick="deleteAccount('${a.platform}','${a.login_id}')" title="삭제">🗑️</button>
            </td>
        </tr>
    `).join('');
}

function toggleApiFields() {
    const p = document.getElementById('formPlatform').value;
    document.getElementById('ssApiSection').style.display = p === '스마트스토어' ? 'block' : 'none';
    document.getElementById('cpApiSection').style.display = p === '쿠팡' ? 'block' : 'none';
    document.getElementById('stApiSection').style.display = p === '11번가' ? 'block' : 'none';
    document.getElementById('esmApiSection').style.display = ['지마켓', '옥션'].includes(p) ? 'block' : 'none';
}

function openAddModal() {
    document.getElementById('modalTitle').textContent = '계정 추가';
    document.getElementById('editMode').value = 'add';
    document.getElementById('accountForm').reset();
    toggleApiFields();
    document.getElementById('accountModal').classList.add('show');
}

async function openEditModal(platform, loginId) {
    try {
        const r = await fetch(`/api/accounts/${encodeURIComponent(platform)}/${encodeURIComponent(loginId)}`);
        const a = await r.json();
        document.getElementById('modalTitle').textContent = '계정 수정';
        document.getElementById('editMode').value = 'edit';
        document.getElementById('originalId').value = loginId;
        document.getElementById('originalPlatform').value = platform;
        document.getElementById('formPlatform').value = a.platform;
        document.getElementById('formShopAlias').value = a.스토어명 || '';
        document.getElementById('formLoginId').value = a.login_id;
        document.getElementById('formPassword').value = a.password;
        document.getElementById('formBusinessNumber').value = a.business_number || '';
        document.getElementById('formSsSellerId').value = a.ss_seller_id || '';
        document.getElementById('formSsAppId').value = a.ss_app_id || '';
        document.getElementById('formSsAppSecret').value = a.ss_app_secret || '';
        document.getElementById('formCpVendorCode').value = a.cp_vendor_code || '';
        document.getElementById('formCpAccessKey').value = a.cp_access_key || '';
        document.getElementById('formCpSecretKey').value = a.cp_secret_key || '';
        document.getElementById('formStApiKey').value = a.st_api_key || '';
        // ESM ID/PW (지마켓/옥션용) - esm_id, esm_pw 사용
        if (document.getElementById('formEsmMaster')) {
            document.getElementById('formEsmMaster').value = a.esm_id || a.esm_master || '';
        }
        if (document.getElementById('formEsmMasterPw')) {
            document.getElementById('formEsmMasterPw').value = a.esm_pw || a.esm_master_pw || '';
        }
        toggleApiFields();
        document.getElementById('accountModal').classList.add('show');
    } catch (e) {
        showToast('로드 실패', 'error');
    }
}

function closeModal() {
    document.getElementById('accountModal').classList.remove('show');
}

document.getElementById('accountForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const platform = document.getElementById('formPlatform').value;
    const data = {
        platform: platform,
        login_id: document.getElementById('formLoginId').value,
        password: document.getElementById('formPassword').value,
        shop_alias: document.getElementById('formShopAlias').value,
        business_number: document.getElementById('formBusinessNumber').value,
        ss_seller_id: document.getElementById('formSsSellerId').value,
        ss_app_id: document.getElementById('formSsAppId').value,
        ss_app_secret: document.getElementById('formSsAppSecret').value,
        cp_vendor_code: document.getElementById('formCpVendorCode').value,
        cp_access_key: document.getElementById('formCpAccessKey').value,
        cp_secret_key: document.getElementById('formCpSecretKey').value,
        st_api_key: document.getElementById('formStApiKey').value,
        esm_master: document.getElementById('formEsmMaster') ? document.getElementById('formEsmMaster').value : '',
        esm_master_pw: document.getElementById('formEsmMasterPw') ? document.getElementById('formEsmMasterPw').value : ''
    };
    // 지마켓/옥션인 경우 esm_id, esm_pw도 전송 (구글시트 ESM ID/PW 컬럼용)
    if (['지마켓', '옥션'].includes(platform)) {
        data.esm_id = document.getElementById('formEsmMaster') ? document.getElementById('formEsmMaster').value : '';
        data.esm_pw = document.getElementById('formEsmMasterPw') ? document.getElementById('formEsmMasterPw').value : '';
    }
    const mode = document.getElementById('editMode').value;
    try {
        let r;
        if (mode === 'add') {
            r = await fetch('/api/accounts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
        } else {
            const origId = document.getElementById('originalId').value;
            const origPlatform = document.getElementById('originalPlatform').value;
            r = await fetch(`/api/accounts/${encodeURIComponent(origPlatform)}/${encodeURIComponent(origId)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
        }
        if (r.ok) {
            closeModal();
            loadAccounts();
            showToast(mode === 'add' ? '추가됨' : '수정됨', 'success');
        } else {
            showToast('실패', 'error');
        }
    } catch (e) {
        showToast('오류', 'error');
    }
});

async function deleteAccount(platform, loginId) {
    if (!confirm(`'${loginId}' 삭제?`)) return;
    try {
        const r = await fetch(`/api/accounts/${encodeURIComponent(platform)}/${encodeURIComponent(loginId)}`, { method: 'DELETE' });
        if (r.ok) { loadAccounts(); showToast('삭제됨', 'success'); }
        else showToast('실패', 'error');
    } catch (e) { showToast('오류', 'error'); }
}

// ID/PW 입력만 (새창에서 로그인 페이지 열고 클립보드에 복사)
// 로그인 페이지 열고 ID 복사 (두번째 버튼)
async function openLoginPage(platform, loginId) {
    showToast('복사 중...', 'info');

    try {
        const r = await fetch(`/api/accounts/${encodeURIComponent(platform)}/${encodeURIComponent(loginId)}`);
        if (!r.ok) {
            showToast('계정 정보 조회 실패', 'error');
            return;
        }
        const a = await r.json();

        if (!a.password || !a.login_id) {
            showToast('ID 또는 PW 정보 없음', 'error');
            return;
        }

        // 1. PW 먼저 클립보드에 복사 (Win+V 기록에 남음)
        copyToClipboard(a.password);

        // 300ms 대기 후 ID 복사 (클립보드 기록에 PW가 확실히 들어가도록)
        setTimeout(() => {
            // 2. ID 클립보드에 복사 (Ctrl+V로 바로 사용 가능)
            copyToClipboard(a.login_id);
            showToast(`ID복사됨 → Ctrl+V로 ID, Win+V로 PW`, 'success');
        }, 300);
    } catch (e) {
        console.error('openLoginPage 오류:', e);
        showToast('복사 실패', 'error');
    }
}

// 자동 로그인 - 크롬 확장 프로그램 (비활성화됨)
async function autoLoginChrome(platform, loginId) {
    showToast(`${loginId} 자동 로그인 시작...`, 'info');

    try {
        const r = await fetch('/api/auto-login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                platform: platform,
                login_id: loginId
            })
        });
        const d = await r.json();

        if (d.success || d.pending) {
            showToast('자동 로그인 요청 완료 - 클라이언트에서 처리 중', 'success');
        } else {
            showToast('자동 로그인 실패: ' + (d.message || ''), 'error');
        }
    } catch (e) {
        console.error('[자동로그인] 오류:', e);
        showToast('자동 로그인 실패', 'error');
    }
}

async function fillLogin(platform, loginId) {
    try {
        const r = await fetch(`/api/accounts/${encodeURIComponent(platform)}/${encodeURIComponent(loginId)}`);
        const a = await r.json();
        const url = platformUrls[platform];

        if (url) {
            window.open(url, '_blank');
            copyToClipboard(a.login_id);
            sessionStorage.setItem('tempPW', a.password);

            if (['ESM통합', '지마켓', '옥션'].includes(platform)) {
                showToast(`${platform} 탭 선택 → ID붙여넣기 → Ctrl+Shift+V로 PW`, 'success');
            } else {
                showToast(`ID복사됨 → Ctrl+Shift+V로 PW복사`, 'success');
            }
        }
    } catch (e) {
        showToast('실패', 'error');
    }
}

// 자동 로그인 (서버에서 Playwright로 처리) - 레거시
async function autoLogin(platform, loginId) {
    showToast('자동 로그인 시도 중...', 'info');
    try {
        const r = await fetch('/api/auto-login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ platform, login_id: loginId })
        });
        const d = await r.json();
        if (d.success) {
            showToast('로그인 성공!', 'success');
        } else if (d.need_2fa) {
            showToast('2차 인증 필요 - SMS 확인', 'info');
        } else {
            showToast(d.message || '로그인 실패', 'error');
        }
    } catch (e) {
        showToast('오류 발생', 'error');
    }
}

// 유틸
function copyToClipboard(text) {
    // 먼저 textarea 방식 시도 (더 안정적)
    try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        ta.style.top = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        const result = document.execCommand('copy');
        document.body.removeChild(ta);
        if (result) return true;
    } catch (e) {
        console.log('execCommand 실패:', e);
    }

    // fallback: navigator.clipboard
    try {
        navigator.clipboard.writeText(text);
        return true;
    } catch (e) {
        console.log('clipboard API 실패:', e);
        return false;
    }
}

// ID+PW 함께 복사하여 로그인 페이지 열기
async function openLoginPageWithPW(platform, loginId) {
    try {
        const r = await fetch(`/api/accounts/${encodeURIComponent(platform)}/${encodeURIComponent(loginId)}`);
        const a = await r.json();
        const url = platformUrls[platform];

        if (url) {
            // 1. PW 먼저 클립보드에 복사 (Win+V 기록에 남음)
            copyToClipboard(a.password);

            // 300ms 대기 후 ID 복사 및 페이지 열기
            setTimeout(() => {
                // 2. ID 클립보드에 복사 (Ctrl+V로 바로 사용 가능)
                copyToClipboard(a.login_id);

                // 3. 로그인 페이지 새 탭으로 열기
                window.open(url, '_blank');

                showToast(`ID복사됨 → Ctrl+V로 ID, Win+V로 PW 붙여넣기`, 'success');
            }, 300);
        } else {
            showToast('로그인 URL을 찾을 수 없습니다', 'error');
        }
    } catch (e) {
        showToast('실패', 'error');
    }
}

// PW 복사 단축키 (Ctrl+Shift+V)
document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.shiftKey && e.key === 'V') {
        const pw = sessionStorage.getItem('tempPW');
        if (pw) {
            copyToClipboard(pw);
            showToast('비밀번호 복사됨', 'success');
        }
    }
});

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast show ' + type;
    setTimeout(() => toast.classList.remove('show'), 3000);
}

async function logout() {
    await fetch('/api/logout', { method: 'POST' });
    location.href = '/login';
}

// ========== 불사자 기능 ==========
let selectedGroups = new Set();
let bulsajaRunning = false;
let bulsajaStatusInterval = null;

// 폴더 경로 저장
// 불사자 시트 설정 저장
async function saveBulsajaSettings() {
    const program = document.getElementById('bulsajaProgram').value;
    const uploadMarket = document.getElementById('bulsajaUploadMarket').value;
    const uploadCount = document.getElementById('bulsajaUploadCount').value;
    const deleteCount = document.getElementById('bulsajaDeleteCount').value;
    const copySourceMarket = document.getElementById('bulsajaCopySourceMarket').value;
    const copyCount = document.getElementById('bulsajaCopyCount').value;

    try {
        const r = await fetch('/api/bulsaja/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                program,
                uploadMarket, uploadCount,
                deleteCount,
                copySourceMarket, copyCount
            })
        });
        const d = await r.json();
        if (d.success) showToast('시트에 저장됨', 'success');
        else showToast(d.message || '저장 실패', 'error');
    } catch (e) {
        showToast('저장 오류', 'error');
    }
}

// 불사자 시트 설정 불러오기
async function loadBulsajaSettings() {
    try {
        const r = await fetch('/api/bulsaja/settings');
        const d = await r.json();
        if (d.success) {
            if (d.program) document.getElementById('bulsajaProgram').value = d.program;
            // 상품업로드용
            if (d.uploadMarket) document.getElementById('bulsajaUploadMarket').value = d.uploadMarket;
            if (d.uploadCount) document.getElementById('bulsajaUploadCount').value = d.uploadCount;
            // 상품삭제용
            if (d.deleteCount) document.getElementById('bulsajaDeleteCount').value = d.deleteCount;
            // 상품복사용
            if (d.copySourceMarket) document.getElementById('bulsajaCopySourceMarket').value = d.copySourceMarket;
            if (d.copyCount) document.getElementById('bulsajaCopyCount').value = d.copyCount;
            onBulsajaProgramChange();

            // ========== 추가: 시트 설정 표시 ==========
            const infoSection = document.getElementById('bulsajaSheetInfo');
            if (infoSection) {
                infoSection.style.display = 'block';

                // 마진설정: 환율/카드수수료/마켓할인율/가격단위올림/퍼센트마진/더하기마진
                const marginEl = document.getElementById('marginInfo');
                if (marginEl && d.margin) {
                    const m = d.margin;
                    marginEl.innerHTML = `${m.exchangeRate || '-'} / ${m.cardFee || '-'} / ${m.marketDiscount || '-'} / ${m.priceRounding || '-'} / ${m.percentMargin || '-'} / ${m.addMargin || '-'}`;
                }

                // 상품업로드 설정: 상품명/업로드수/옵션설정/업로드조건/최저가격/최대가격
                const uploadEl = document.getElementById('uploadInfo');
                if (uploadEl && d.upload) {
                    const u = d.upload;
                    uploadEl.innerHTML = `${u.productName || '-'} / ${u.uploadCount || '-'} / ${u.optionSort || '-'} / ${u.uploadCondition || '-'} / ${u.minPrice || '-'} / ${u.maxPrice || '-'}`;
                }

                // 상품삭제/복사 설정: 삭제범위/삭제방식/기준마켓/복사조건
                const dcEl = document.getElementById('deleteCopyInfo');
                if (dcEl && d.deleteCopy) {
                    const dc = d.deleteCopy;
                    dcEl.innerHTML = `${dc.deleteScope || '-'} / ${dc.deleteOrder || '-'} / ${dc.baseMarket || '-'} / ${dc.copyCondition || '-'}`;
                }
            }

            showToast('설정 불러옴', 'success');
        }
    } catch (e) {
        showToast('불러오기 오류', 'error');
    }
}

// 프로그램 선택 변경 시 UI 업데이트
function onBulsajaProgramChange() {
    const program = document.getElementById('bulsajaProgram').value;

    // 모든 설정 행 숨기기
    document.getElementById('uploadMarketRow').style.display = 'none';
    document.getElementById('uploadCountRow').style.display = 'none';
    document.getElementById('deleteCountRow').style.display = 'none';
    document.getElementById('copySourceMarketRow').style.display = 'none';
    document.getElementById('copyCountRow').style.display = 'none';

    // 선택된 프로그램에 맞는 행만 표시
    if (program === '2. 상품업로드') {
        document.getElementById('uploadMarketRow').style.display = 'flex';
        document.getElementById('uploadCountRow').style.display = 'flex';
    } else if (program === '4. 상품삭제') {
        document.getElementById('deleteCountRow').style.display = 'flex';
    } else if (program === '4-3. 불사자상품복사') {
        document.getElementById('copySourceMarketRow').style.display = 'flex';
        document.getElementById('copyCountRow').style.display = 'flex';
    }
}

// 초기화 (탭 클릭 시)
function initBulsajaTab() {
    loadBulsajaSettings();

    // 1~40 그룹 버튼 생성
    const container = document.getElementById('groupQuickSelect');
    if (container && !container.hasChildNodes()) {
        for (let i = 1; i <= 40; i++) {
            const btn = document.createElement('button');
            btn.className = 'group-num-btn';
            btn.textContent = i;
            btn.onclick = () => toggleGroupBtn(i, btn);
            container.appendChild(btn);
        }
    }
    loadBulsajaStatus();
}

// 그룹 버튼 토글
function toggleGroupBtn(num, btn) {
    if (selectedGroups.has(num)) {
        selectedGroups.delete(num);
        btn.classList.remove('selected');
    } else {
        selectedGroups.add(num);
        btn.classList.add('selected');
    }
    updateGroupInput();
}

// 그룹 입력창 업데이트
function updateGroupInput() {
    const sorted = Array.from(selectedGroups).sort((a, b) => a - b);
    document.getElementById('bulsajaGroups').value = sorted.join(',');
}

// 프리셋 버튼
function setGroupPreset(preset) {
    document.getElementById('bulsajaGroups').value = preset;
    parseAndSelectGroups(preset);
}

// 그룹 문자열 파싱 및 버튼 선택
function parseAndSelectGroups(text) {
    selectedGroups.clear();
    document.querySelectorAll('.group-num-btn').forEach(btn => btn.classList.remove('selected'));

    const parts = text.replace(/\s/g, '').split(',');
    parts.forEach(part => {
        if (part.includes('-')) {
            const [a, b] = part.split('-').map(Number);
            const start = Math.min(a, b);
            const end = Math.max(a, b);
            for (let i = start; i <= end; i++) {
                if (i >= 1 && i <= 20) {
                    selectedGroups.add(i);
                }
            }
        } else {
            const n = parseInt(part);
            if (n >= 1 && n <= 20) {
                selectedGroups.add(n);
            }
        }
    });

    // 버튼 상태 업데이트
    document.querySelectorAll('.group-num-btn').forEach(btn => {
        const num = parseInt(btn.textContent);
        if (selectedGroups.has(num)) {
            btn.classList.add('selected');
        }
    });
}

// 그룹 입력창 변경 시
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('bulsajaGroups');
    if (input) {
        input.addEventListener('change', () => parseAndSelectGroups(input.value));
    }
});

// 불사자 실행
async function runBulsaja() {
    const groupsInput = document.getElementById('bulsajaGroups');
    const maxConcurrentInput = document.getElementById('maxConcurrent');
    const groupGapInput = document.getElementById('groupGap');

    if (!groupsInput) {
        showToast('그룹 입력 필드를 찾을 수 없습니다', 'error');
        return;
    }

    const groupsText = groupsInput.value.trim();
    if (!groupsText) {
        showToast('그룹을 선택하세요', 'error');
        return;
    }

    const maxConcurrent = maxConcurrentInput ? parseInt(maxConcurrentInput.value) : 3;
    const groupGap = groupGapInput ? parseInt(groupGapInput.value) : 60;

    // 설정값 수집
    const program = document.getElementById('bulsajaProgram').value;
    const uploadMarket = document.getElementById('bulsajaUploadMarket')?.value || '';
    const uploadCount = document.getElementById('bulsajaUploadCount')?.value || '';
    const deleteCount = document.getElementById('bulsajaDeleteCount')?.value || '';
    const copySourceMarket = document.getElementById('bulsajaCopySourceMarket')?.value || '';
    const copyCount = document.getElementById('bulsajaCopyCount')?.value || '';

    // 서버 실행 (설정값 + 실행)
    try {
        const r = await fetch('/api/bulsaja/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
                groups: groupsText,
                max_concurrent: maxConcurrent,
                group_gap: groupGap,
                // 설정값
                program,
                uploadMarket,
                uploadCount,
                deleteCount,
                copySourceMarket,
                copyCount
            })
        });

        console.log('Bulsaja run response status:', r.status);

        if (!r.ok) {
            const text = await r.text();
            console.error('Bulsaja run error:', text);
            showToast(`실행 실패: ${r.status}`, 'error');
            return;
        }

        const d = await r.json();

        if (d.success) {
            bulsajaRunning = true;
            document.getElementById('stopBulsajaBtn').disabled = false;
            showToast('서버에서 실행 시작!', 'success');
            startBulsajaStatusPolling();

            // 로그 섹션 표시 및 초기화
            showBulsajaLogSection();
            clearBulsajaLogs();
            appendBulsajaLog(new Date().toLocaleTimeString(), '🚀 실행 시작...');
        } else {
            showToast(d.message || '실행 실패', 'error');
        }
    } catch (e) {
        console.error('Bulsaja run exception:', e);
        showToast('실행 오류: ' + e.message, 'error');
    }
}

// 불사자 로그 함수들
function showBulsajaLogSection() {
    const section = document.getElementById('bulsajaLogSection');
    if (section) section.style.display = 'block';
}

function clearBulsajaLogs() {
    const container = document.getElementById('bulsajaLogs');
    if (container) container.innerHTML = '';
}

function appendBulsajaLog(time, msg) {
    const container = document.getElementById('bulsajaLogs');
    if (!container) return;

    const line = document.createElement('div');
    line.className = 'log-line';

    // 메시지 타입에 따라 색상 구분
    if (msg.includes('완료') || msg.includes('성공') || msg.includes('✅')) {
        line.classList.add('success');
    } else if (msg.includes('실패') || msg.includes('오류') || msg.includes('❌')) {
        line.classList.add('error');
    } else if (msg.includes('[INFO]') || msg.includes('[WAIT]')) {
        line.classList.add('info');
    }

    line.innerHTML = `<span class="time">[${time}]</span><span class="msg">${escapeHtml(msg)}</span>`;
    container.appendChild(line);

    // 자동 스크롤
    container.scrollTop = container.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 그룹 텍스트 파싱 (클라이언트용)
function parseGroupsText(text) {
    const groups = [];
    const seen = new Set();

    text.replace(/\s/g, '').split(',').forEach(part => {
        if (!part) return;

        if (part.includes('-')) {
            const [a, b] = part.split('-').map(Number);
            const step = a <= b ? 1 : -1;
            for (let n = a; step > 0 ? n <= b : n >= b; n += step) {
                if (n >= 1 && n <= 99 && !seen.has(n)) {
                    groups.push(n);
                    seen.add(n);
                }
            }
        } else {
            const n = parseInt(part);
            if (n >= 1 && n <= 99 && !seen.has(n)) {
                groups.push(n);
                seen.add(n);
            }
        }
    });

    return groups;
}

// 불사자 중지
async function stopBulsaja() {
    if (!confirm('실행 중인 작업을 중지하시겠습니까?')) return;

    try {
        const r = await fetch('/api/bulsaja/stop', { method: 'POST' });
        const d = await r.json();

        if (d.success) {
            bulsajaRunning = false;
            document.getElementById('stopBulsajaBtn').disabled = true;
            showToast('중지됨', 'success');
            stopBulsajaStatusPolling();
        }
    } catch (e) {
        showToast('중지 오류', 'error');
    }
}

// 상태 폴링
function startBulsajaStatusPolling() {
    if (bulsajaStatusInterval) clearInterval(bulsajaStatusInterval);
    bulsajaStatusInterval = setInterval(loadBulsajaStatus, 2000);
    loadBulsajaStatus();
}

function stopBulsajaStatusPolling() {
    if (bulsajaStatusInterval) {
        clearInterval(bulsajaStatusInterval);
        bulsajaStatusInterval = null;
    }
}

// 상태 로드
async function loadBulsajaStatus() {
    try {
        const r = await fetch('/api/bulsaja/status');
        const d = await r.json();

        // 통계 업데이트
        document.getElementById('statPending').textContent = d.pending || 0;
        document.getElementById('statRunning').textContent = d.running || 0;
        document.getElementById('statCompleted').textContent = d.completed || 0;
        document.getElementById('statFailed').textContent = d.failed || 0;

        // 활성 폴더 업데이트
        if (d.active_folder) {
            document.getElementById('activeFolder').textContent = d.active_folder;
        }

        // 진행 목록 업데이트
        const list = document.getElementById('bulsajaProgress');
        if (d.groups && d.groups.length > 0) {
            list.innerHTML = d.groups.map(g => `
                <div class="progress-item ${g.status}">
                    <span class="group-num">그룹 ${g.num}</span>
                    <span class="status">
                        <span class="status-icon">${getStatusIcon(g.status)}</span>
                        ${getStatusText(g.status, g.message)}
                    </span>
                </div>
            `).join('');
        } else if (!bulsajaRunning) {
            list.innerHTML = '<div class="empty">실행할 그룹을 선택하세요</div>';
        }

        // 완료 체크
        if (d.is_running === false && bulsajaRunning) {
            bulsajaRunning = false;
            document.getElementById('stopBulsajaBtn').disabled = true;
            stopBulsajaStatusPolling();
            showToast('모든 작업 완료!', 'success');
        }

    } catch (e) {
        console.error('상태 로드 오류:', e);
    }
}

function getStatusIcon(status) {
    switch (status) {
        case 'pending': return '⏳';
        case 'running': return '🔄';
        case 'completed': return '✅';
        case 'failed': return '❌';
        default: return '○';
    }
}

function getStatusText(status, message) {
    switch (status) {
        case 'pending': return '대기 중';
        case 'running': return '실행 중...';
        case 'completed': return '완료';
        case 'failed': return `실패: ${message || ''}`;
        default: return status;
    }
}

// 탭 변경 시 불사자 초기화
document.addEventListener('DOMContentLoaded', () => {
    const tabs = document.querySelectorAll('.tab');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            if (tab.dataset.tab === 'bulsaja') {
                initBulsajaTab();
            }
            // 자동화 대시보드 탭
            if (tab.dataset.tab === 'bulsaja-dashboard') {
                initBulsajaDashboard();
            }
        });
    });
});

// ========== 자동화 대시보드 기능 ==========
let bulsajaDashboardAccounts = [];
let bulsajaDashboardStageFilter = 'all';
let bulsajaDashboardPlatformFilters = ['all'];  // 복수 선택 지원 (배열)
let bulsajaDashboardUsageFilters = ['all'];     // 복수 선택 지원 (배열)
let bulsajaDashboardSearchQuery = '';
// 구버전 호환용 getter
Object.defineProperty(window, 'bulsajaDashboardPlatformFilter', {
    get: () => bulsajaDashboardPlatformFilters.includes('all') ? 'all' : bulsajaDashboardPlatformFilters[0],
    set: (v) => { bulsajaDashboardPlatformFilters = [v]; }
});
Object.defineProperty(window, 'bulsajaDashboardUsageFilter', {
    get: () => bulsajaDashboardUsageFilters.includes('all') ? 'all' : bulsajaDashboardUsageFilters[0],
    set: (v) => { bulsajaDashboardUsageFilters = [v]; }
});

const bulsajaDashboardStageIcons = ['📤', '🏪', '🔨', '🗑️', '✏️', '📋'];
const bulsajaDashboardStageNames = ['업로드', '운영', '리뉴얼대상', '삭제', '변경', '복사'];
const bulsajaDashboardPlatformLogos = {
    naver: { letter: 'N', class: 'naver' },
    coupang: { letter: 'C', class: 'coupang' },
    '11st': { letter: '11', class: 'st11' },
    gmarket: { letter: 'G', class: 'gmarket' },
    auction: { letter: 'A', class: 'auction' }
};

// 자동화 대시보드 초기화
function initBulsajaDashboard() {
    // 시간 업데이트
    updateBulsajaDashboardTime();
    setInterval(updateBulsajaDashboardTime, 1000);

    // 데이터 로드
    loadBulsajaDashboardData();

    // 이벤트 리스너 설정
    setupBulsajaDashboardEvents();
}

// 시간 업데이트
function updateBulsajaDashboardTime() {
    const timeEl = document.getElementById('currentTimeBulsaja');
    if (timeEl) {
        const now = new Date();
        timeEl.textContent = now.toTimeString().slice(0, 8);
    }
}

// 데이터 로드
async function loadBulsajaDashboardData(refresh = false) {
    try {
        const url = refresh ? '/api/bulsaja/dashboard_data?refresh=true' : '/api/bulsaja/dashboard_data';
        const response = await fetch(url);
        const data = await response.json();

        if (data.accounts) {
            bulsajaDashboardAccounts = data.accounts;
            renderBulsajaDashboard();
        }
    } catch (e) {
        console.error('대시보드 데이터 로드 실패:', e);
    }
}

// 매출 포맷팅
function formatBulsajaRevenue(num) {
    if (!num) return '0';
    if (num >= 100000000) return (num / 100000000).toFixed(1) + '억';
    if (num >= 10000000) return (num / 10000000).toFixed(0) + '천만';
    if (num >= 10000) return (num / 10000).toFixed(0) + '만';
    return num.toLocaleString();
}

// 매출 상태
function getBulsajaRevenueStatus(revenue, target) {
    const percent = (revenue / target) * 100;
    if (percent >= 100) return 'achieved';
    if (percent >= 50) return 'warning';
    return 'danger';
}

// 운영일 클래스
function getBulsajaDaysClass(days) {
    if (days >= 60) return 'danger';
    if (days >= 30) return 'warning';
    return '';
}

// 매출 상태 텍스트 결정 함수
function getRevenueStatusText(revenue, targetRevenue) {
    const percent = (revenue / targetRevenue) * 100;
    if (percent >= 100) return '목표달성';
    if (percent >= 70) return '양호';
    if (percent >= 40) return '주의';
    return '매출부진';
}

// 운영일 클릭시 인라인 수정 가능하게 변환
function makeOpDaysEditable(el, storeName, currentDays) {
    // 이미 input이면 무시
    if (el.querySelector('input')) return;

    const originalHTML = el.innerHTML;
    const daysClass = el.className.replace('operation-days', '').trim();

    el.innerHTML = `<input type="number" class="op-days-inline-input" value="${currentDays}" min="0" max="9999">일`;
    const input = el.querySelector('input');
    input.focus();
    input.select();

    // Enter 또는 포커스 아웃 시 저장
    const save = async () => {
        const newDays = parseInt(input.value) || 0;
        el.innerHTML = `${newDays}일`;
        if (newDays !== currentDays) {
            await updateBulsajaOperationDaysSilent(storeName, newDays);
        }
    };

    input.addEventListener('blur', save);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            input.blur();
        } else if (e.key === 'Escape') {
            el.innerHTML = originalHTML;
        }
    });
}

// 운영일 업데이트 함수 (실제 반영) - 팝업 없이 조용히 업데이트 (이름 변경하여 캐시 회피)
async function updateBulsajaOperationDaysSilent(storeName, days) {
    try {
        const response = await fetch('/api/bulsaja/dashboard_settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                store_name: storeName,
                operationDays: parseInt(days)
            })
        });
        const res = await response.json();
        if (res.success) {
            // 조용히 데이터 새로고침
            loadBulsajaDashboardData();
        } else {
            console.error('불사자 업데이트 실패:', res.message);
            // 실패 시에도 alert 띄우지 않음
        }
    } catch (e) {
        console.error('운영일 수정 오류:', e);
    }
}

// 대시보드 전체 렌더링
function renderBulsajaDashboard() {
    const stageMapReverse = {
        '업로드': 1, '운영': 2, '리뉴얼대상': 3, '삭제': 4, '변경': 5, '복사': 6
    };
    const stageIcons = ['📤', '🏪', '🔨', '🗑️', '✏️', '📋'];

    // 필터 적용
    const filtered = bulsajaDashboardAccounts.filter(acc => {
        // 스테이지 필터
        let matchStage = bulsajaDashboardStageFilter === 'all';
        if (!matchStage) {
            const stageMap = { '1': '업로드', '2': '운영', '3': '리뉴얼대상', '4': '삭제', '5': '변경', '6': '복사' };
            matchStage = acc.stage === stageMap[bulsajaDashboardStageFilter];
        }
        // 플랫폼 필터 (복수 선택 지원)
        let matchPlatform = bulsajaDashboardPlatformFilters.includes('all');
        if (!matchPlatform) {
            const platform = (acc.platform || '').toLowerCase();
            matchPlatform = bulsajaDashboardPlatformFilters.some(f => {
                if (f === 'gmarket') return platform === 'gmarket' || platform === 'auction';
                return platform === f;
            });
        }
        // 용도 필터 (복수 선택 지원)
        let matchUsage = bulsajaDashboardUsageFilters.includes('all');
        if (!matchUsage) {
            const usage = acc.usage || '대량';
            matchUsage = bulsajaDashboardUsageFilters.includes(usage);
        }
        const matchSearch = (acc.name || '').toLowerCase().includes(bulsajaDashboardSearchQuery.toLowerCase());
        return matchStage && matchPlatform && matchUsage && matchSearch;
    });

    // 카운트 업데이트
    const stageCounts = { '업로드': 0, '운영': 0, '리뉴얼대상': 0, '삭제': 0, '변경': 0, '복사': 0 };
    bulsajaDashboardAccounts.forEach(a => {
        if (stageCounts[a.stage] !== undefined) stageCounts[a.stage]++;
    });

    const countAllEl = document.getElementById('countAllBulsaja');
    if (countAllEl) countAllEl.textContent = bulsajaDashboardAccounts.length;
    const count1El = document.getElementById('count1Bulsaja');
    if (count1El) count1El.textContent = stageCounts['업로드'];
    const count2El = document.getElementById('count2Bulsaja');
    if (count2El) count2El.textContent = stageCounts['운영'];
    const count3El = document.getElementById('count3Bulsaja');
    if (count3El) count3El.textContent = stageCounts['리뉴얼대상'];
    const count4El = document.getElementById('count4Bulsaja');
    if (count4El) count4El.textContent = stageCounts['삭제'];
    const count5El = document.getElementById('count5Bulsaja');
    if (count5El) count5El.textContent = stageCounts['변경'];
    const count6El = document.getElementById('count6Bulsaja');
    if (count6El) count6El.textContent = stageCounts['복사'];

    // 테이블 렌더링
    const tableBody = document.getElementById('tableBodyBulsaja');
    if (tableBody) {
        tableBody.innerHTML = filtered.map(acc => {
            const platform = (acc.platform || 'naver').toLowerCase();
            const logo = bulsajaDashboardPlatformLogos[platform] || { letter: platform.charAt(0).toUpperCase(), class: '' };
            const currentStageIdx = stageMapReverse[acc.stage] || 0;
            const targetRevenue = acc.targetRevenue || 2000000;
            const revenuePercent = Math.min((acc.revenue / targetRevenue) * 100, 100);
            const revenueStatus = getBulsajaRevenueStatus(acc.revenue, targetRevenue);
            const operationDays = acc.operationDays || 0;
            const daysClass = getBulsajaDaysClass(operationDays);

            // 공통 데이터 계산
            const maxProducts = acc.targetProducts || 10000;
            const currentProducts = acc.products || 0;
            const uploadPercent = Math.min((currentProducts / maxProducts) * 100, 100);

            // 스테이지 셀 생성
            let stageCells = '';
            for (let i = 1; i <= 6; i++) {
                const isActive = i === currentStageIdx;
                const isCompleted = i < currentStageIdx;

                // active 셀에만 테두리: 리뉴얼=빨강, 그 외=오렌지
                let cellClass = isActive ? (i === 3 ? 'blink-active-red' : 'blink-active') : '';
                let content = '';

                if (i === 1) {
                    // 업로드 열: 항상 업로드 정보 표시 (핵심 요구사항)
                    const indicatorClass = isActive ? 'active' : (isCompleted ? 'completed' : '');
                    content = `
                        <div class="stage-indicator-bulsaja ${indicatorClass}">
                            <div class="value">${currentProducts.toLocaleString()} / ${maxProducts.toLocaleString()}</div>
                            <div class="progress-bar"><div class="progress-bar-fill" style="width:${uploadPercent}%"></div></div>
                            <div class="value">${uploadPercent.toFixed(0)}%</div>
                        </div>`;
                } else if (i === 2) {
                    // 운영 열: 항상 운영일 표시 (핵심 요구사항) - 클릭시 인라인 수정
                    const indicatorClass = isActive ? 'active' : (isCompleted ? 'completed' : '');
                    const safeStoreName = acc.name.replace(/'/g, "\\'");
                    content = `
                        <div class="stage-indicator-bulsaja ${indicatorClass}">
                            <div class="operation-days ${daysClass}" onclick="makeOpDaysEditable(this, '${safeStoreName}', ${operationDays})" style="cursor:pointer;">${operationDays}일</div>
                        </div>`;
                } else if (i === 3) {
                    // 리뉴얼 열
                    if (isActive) {
                        // 리뉴얼 활성: 빨간 강조 + 사유 표시
                        content = `
                            <div class="stage-indicator-bulsaja active renewal-active">
                                <div class="icon">🔨</div>
                                <div class="value renewal-reason">${acc.renewalReason || '매출부진 (0원)'}</div>
                            </div>`;
                    } else if (isCompleted) {
                        content = `<div class="stage-indicator-bulsaja completed"><div class="icon">✓</div></div>`;
                    } else {
                        content = `<div class="stage-indicator-bulsaja inactive"><div class="icon">🔨</div></div>`;
                    }
                } else {
                    // 삭제/변경/복사 열
                    if (isActive) {
                        content = `
                            <div class="stage-indicator-bulsaja active">
                                <div class="icon">${stageIcons[i - 1]}</div>
                            </div>`;
                    } else if (isCompleted) {
                        content = `<div class="stage-indicator-bulsaja completed"><div class="icon">✓</div></div>`;
                    } else {
                        content = `<div class="stage-indicator-bulsaja inactive"><div class="icon">${stageIcons[i - 1]}</div></div>`;
                    }
                }

                stageCells += `<div class="stage-cell-bulsaja ${cellClass}">${content}</div>`;
            }

            // 목표매출 셀: 모든 행에 항상 표시 (핵심 요구사항)
            let revenueCell = `
                <div class="revenue-cell-bulsaja">
                    <div class="revenue-header-row-bulsaja">
                        <span class="revenue-current-bulsaja">${formatBulsajaRevenue(acc.revenue)}</span>
                        <span class="revenue-target-text-bulsaja">${formatBulsajaRevenue(targetRevenue)}</span>
                    </div>
                    <div class="revenue-bar-bulsaja"><div class="revenue-bar-fill-bulsaja ${revenueStatus}" style="width:${revenuePercent}%"></div></div>
                    <div class="revenue-percent-bulsaja ${revenueStatus}">${revenuePercent.toFixed(0)}%</div>
                </div>`;

            return `
                <div class="table-row-bulsaja">
                    <div class="account-cell-bulsaja sticky-account-col">
                        <div class="account-logo-bulsaja ${logo.class}">${logo.letter}</div>
                        <div class="account-info">
                            <span class="name">${acc.name || 'Unknown'}</span>
                        </div>
                    </div>
                    ${stageCells}
                    ${revenueCell}
                </div>
            `;
        }).join('');
    }

    // 모바일 카드뷰 렌더링
    const cardView = document.getElementById('cardViewBulsaja');
    if (cardView) {
        cardView.innerHTML = filtered.map(acc => {
            const platform = (acc.platform || 'naver').toLowerCase();
            const logo = bulsajaDashboardPlatformLogos[platform] || { letter: platform.charAt(0).toUpperCase(), class: '' };
            const currentStageIdx = stageMapReverse[acc.stage] || 0;
            const targetRevenue = acc.targetRevenue || 2000000;
            const revenuePercent = Math.min((acc.revenue / targetRevenue) * 100, 100);
            const revenueStatus = getBulsajaRevenueStatus(acc.revenue, targetRevenue);
            const operationDays = acc.operationDays || 0;
            const daysClass = getBulsajaDaysClass(operationDays);

            // 미니 스테이지 표시
            let miniStages = '';
            for (let i = 1; i <= 6; i++) {
                let cls = '';
                if (i < currentStageIdx) cls = 'completed';
                else if (i === currentStageIdx) cls = 'active';
                miniStages += `<div class="mini-stage ${cls}"></div>`;
            }

            // 스테이지 내용
            let stageContent = '';
            if (acc.stage === '업로드') {
                const maxProducts = acc.targetProducts || 10000;
                const currentProducts = acc.products || 0;
                stageContent = `
                    <div class="card-stage-icon active">📤</div>
                    <div class="card-stage-info">
                        <div class="card-stage-name">업로드</div>
                        <div class="card-stage-value">${currentProducts.toLocaleString()}/${maxProducts.toLocaleString()}</div>
                    </div>
                    <div class="card-progress">
                        <div class="card-progress-bar"><div class="card-progress-bar-fill" style="width:${acc.progress || 0}%"></div></div>
                    </div>`;
            } else if (acc.stage === '운영') {
                stageContent = `
                    <div class="card-stage-icon active">🏪</div>
                    <div class="card-stage-info">
                        <div class="card-stage-name">운영중</div>
                        <div class="card-stage-value days ${daysClass}">${operationDays}일</div>
                    </div>`;
            } else if (acc.stage === '리뉴얼대상') {
                stageContent = `
                    <div class="card-stage-icon active">🔨</div>
                    <div class="card-stage-info">
                        <div class="card-stage-name">리뉴얼대상</div>
                        <div class="card-stage-value" style="color:var(--accent-red);font-size:12px;">${acc.renewalReason || '매출부진'}</div>
                    </div>`;
            } else {
                stageContent = `
                    <div class="card-stage-icon active">${stageIcons[currentStageIdx - 1] || '📤'}</div>
                    <div class="card-stage-info">
                        <div class="card-stage-name">${acc.stage}</div>
                        <div class="card-stage-value">${acc.products?.toLocaleString() || 0}/${(acc.targetProducts || 10000).toLocaleString()}</div>
                    </div>
                    <div class="card-progress">
                        <div class="card-progress-bar"><div class="card-progress-bar-fill" style="width:${acc.progress || 0}%"></div></div>
                    </div>`;
            }

            // 매출 섹션 (운영/리뉴얼만)
            let revenueSection = '';
            if (acc.stage === '운영' || acc.stage === '리뉴얼대상') {
                revenueSection = `
                    <div class="card-revenue">
                        <div class="card-revenue-header">
                            <span class="card-revenue-title">💰 목표매출</span>
                            <span class="card-revenue-value ${revenueStatus}">${revenuePercent.toFixed(0)}%</span>
                        </div>
                        <div class="card-revenue-bar"><div class="card-revenue-bar-fill ${revenueStatus}" style="width:${revenuePercent}%"></div></div>
                        <div class="card-revenue-footer">
                            <span>${formatBulsajaRevenue(acc.revenue)}</span>
                            <span class="card-revenue-target">/ ${formatBulsajaRevenue(targetRevenue)}</span>
                        </div>
                    </div>`;
            }

            return `
                <div class="account-card-bulsaja">
                    <div class="card-header-bulsaja">
                        <div class="account-logo-bulsaja ${logo.class}">${logo.letter}</div>
                        <div class="account-info">
                            <h4>${acc.name || 'Unknown'}</h4>
                        </div>
                    </div>
                    <div class="card-stage-bulsaja">${stageContent}</div>
                    ${revenueSection}
                    <div class="card-stages-mini">${miniStages}</div>
                </div>
            `;
        }).join('');
    }
}

// 운영일 수정
async function updateBulsajaOperationDays(storeName, currentDays) {
    const newDays = prompt(`${storeName}의 운영일을 입력하세요:`, currentDays);
    if (newDays === null) return;

    const days = parseInt(newDays);
    if (isNaN(days)) {
        alert('숫자만 입력 가능합니다.');
        return;
    }

    try {
        const res = await fetch('/api/bulsaja/dashboard_settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                store_name: storeName,
                operationDays: days
            })
        });
        const data = await res.json();
        if (data.success) {
            const acc = bulsajaDashboardAccounts.find(a => a.name === storeName);
            if (acc) {
                acc.operationDays = days;
                renderBulsajaDashboard();
            }
        } else {
            alert('저장 실패: ' + data.message);
        }
    } catch (e) {
        console.error(e);
        alert('통신 오류가 발생했습니다.');
    }
}

// 이벤트 리스너 설정
function setupBulsajaDashboardEvents() {
    // 새로고침 버튼
    const refreshBtn = document.getElementById('refreshBulsaja');
    if (refreshBtn && !refreshBtn._bound) {
        refreshBtn._bound = true;
        refreshBtn.addEventListener('click', () => loadBulsajaDashboardData(true));
    }

    // 검색 입력
    const searchInput = document.getElementById('searchInputBulsaja');
    if (searchInput && !searchInput._bound) {
        searchInput._bound = true;
        searchInput.addEventListener('input', (e) => {
            bulsajaDashboardSearchQuery = e.target.value;
            renderBulsajaDashboard();
        });
    }

    // 스테이지 탭
    document.querySelectorAll('.stage-tab-bulsaja').forEach(tab => {
        if (!tab._bound) {
            tab._bound = true;
            tab.addEventListener('click', () => {
                document.querySelectorAll('.stage-tab-bulsaja').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                bulsajaDashboardStageFilter = tab.dataset.stage;
                renderBulsajaDashboard();
            });
        }
    });

    // 플랫폼 필터 (Ctrl 복수 선택 지원)
    document.querySelectorAll('.filter-pills-bulsaja:not(.usage-filter-bulsaja) .filter-pill-bulsaja').forEach(pill => {
        if (!pill._bound) {
            pill._bound = true;
            pill.addEventListener('click', (e) => {
                const platform = pill.dataset.platform;

                if (e.ctrlKey || e.metaKey) {
                    // Ctrl+클릭: 복수 선택
                    if (platform === 'all') {
                        // 전체 클릭시 다른거 해제
                        bulsajaDashboardPlatformFilters = ['all'];
                        document.querySelectorAll('.filter-pills-bulsaja:not(.usage-filter-bulsaja) .filter-pill-bulsaja').forEach(p => p.classList.remove('active'));
                        pill.classList.add('active');
                    } else {
                        // 개별 필터 토글
                        const allPill = document.querySelector('.filter-pills-bulsaja:not(.usage-filter-bulsaja) .filter-pill-bulsaja[data-platform="all"]');
                        if (allPill) allPill.classList.remove('active');
                        bulsajaDashboardPlatformFilters = bulsajaDashboardPlatformFilters.filter(f => f !== 'all');

                        if (bulsajaDashboardPlatformFilters.includes(platform)) {
                            // 이미 선택됨 -> 해제
                            bulsajaDashboardPlatformFilters = bulsajaDashboardPlatformFilters.filter(f => f !== platform);
                            pill.classList.remove('active');
                        } else {
                            // 선택
                            bulsajaDashboardPlatformFilters.push(platform);
                            pill.classList.add('active');
                        }

                        // 아무것도 선택 안된 경우 전체로
                        if (bulsajaDashboardPlatformFilters.length === 0) {
                            bulsajaDashboardPlatformFilters = ['all'];
                            if (allPill) allPill.classList.add('active');
                        }
                    }
                } else {
                    // 일반 클릭: 단일 선택
                    document.querySelectorAll('.filter-pills-bulsaja:not(.usage-filter-bulsaja) .filter-pill-bulsaja').forEach(p => p.classList.remove('active'));
                    pill.classList.add('active');
                    bulsajaDashboardPlatformFilters = [platform];
                }
                renderBulsajaDashboard();
            });
        }
    });

    // 용도 필터 (Ctrl 복수 선택 지원)
    document.querySelectorAll('.usage-filter-bulsaja .filter-pill-bulsaja').forEach(pill => {
        if (!pill._bound) {
            pill._bound = true;
            pill.addEventListener('click', (e) => {
                const usage = pill.dataset.usage;

                if (e.ctrlKey || e.metaKey) {
                    // Ctrl+클릭: 복수 선택
                    if (usage === 'all') {
                        bulsajaDashboardUsageFilters = ['all'];
                        document.querySelectorAll('.usage-filter-bulsaja .filter-pill-bulsaja').forEach(p => p.classList.remove('active'));
                        pill.classList.add('active');
                    } else {
                        const allPill = document.querySelector('.usage-filter-bulsaja .filter-pill-bulsaja[data-usage="all"]');
                        if (allPill) allPill.classList.remove('active');
                        bulsajaDashboardUsageFilters = bulsajaDashboardUsageFilters.filter(f => f !== 'all');

                        if (bulsajaDashboardUsageFilters.includes(usage)) {
                            bulsajaDashboardUsageFilters = bulsajaDashboardUsageFilters.filter(f => f !== usage);
                            pill.classList.remove('active');
                        } else {
                            bulsajaDashboardUsageFilters.push(usage);
                            pill.classList.add('active');
                        }

                        if (bulsajaDashboardUsageFilters.length === 0) {
                            bulsajaDashboardUsageFilters = ['all'];
                            if (allPill) allPill.classList.add('active');
                        }
                    }
                } else {
                    // 일반 클릭: 단일 선택
                    document.querySelectorAll('.usage-filter-bulsaja .filter-pill-bulsaja').forEach(p => p.classList.remove('active'));
                    pill.classList.add('active');
                    bulsajaDashboardUsageFilters = [usage];
                }
                renderBulsajaDashboard();
            });
        }
    });
}

// ========== 검색 기능 ==========

function openSearchModal() {
    smsViewMode = 'search';  // 검색 모드로 전환
    document.getElementById('searchModal').classList.add('show');
    document.getElementById('searchPhone').value = '';
    document.getElementById('searchText').value = '';
    document.getElementById('searchResult').style.display = 'none';
    document.getElementById('searchLoading').style.display = 'none';

    // 캐시 통계 업데이트
    updateCacheStats();

    // 기본 탭 활성화
    switchSearchTab('phone');
}

function closeSearchModal() {
    document.getElementById('searchModal').classList.remove('show');
    smsViewMode = 'list';  // 목록 모드로 복구
}

function switchSearchTab(tab) {
    // 탭 버튼 활성화
    const tabs = document.querySelectorAll('.search-tabs .search-tab');
    tabs.forEach((t, i) => {
        t.classList.remove('active');
        // 첫번째(index 0) = phone, 두번째(index 1) = text
        if ((tab === 'phone' && i === 0) || (tab === 'text' && i === 1)) {
            t.classList.add('active');
        }
    });

    // 패널 전환
    document.getElementById('searchPanelPhone').style.display = tab === 'phone' ? 'block' : 'none';
    document.getElementById('searchPanelText').style.display = tab === 'text' ? 'block' : 'none';

    // 결과 초기화
    document.getElementById('searchResult').style.display = 'none';

    // 포커스
    if (tab === 'phone') {
        document.getElementById('searchPhone').focus();
    } else {
        document.getElementById('searchText').focus();
        updateCacheStats();
    }
}

function updateCacheStats() {
    const stats = getCacheStats();
    document.getElementById('cacheStats').innerHTML =
        `💾 캐시: <strong>${stats.conversations}개</strong> 대화, <strong>${stats.messages}개</strong> 메시지 저장됨`;
}

async function searchByPhone() {
    const profileId = document.getElementById('searchProfile').value;
    const phoneNumber = document.getElementById('searchPhone').value.trim();

    if (!phoneNumber) {
        showToast('전화번호를 입력하세요', 'error');
        return;
    }

    document.getElementById('searchLoading').style.display = 'block';
    document.getElementById('searchResult').style.display = 'none';

    try {
        // 전체 선택 시 모든 프로필에서 검색
        const profilesToSearch = profileId ? [profileId] : ['8295', '8217', '4682'];
        let foundResults = [];

        for (const pid of profilesToSearch) {
            const r = await fetch('/api/sms/search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    profile_id: pid,
                    phone_number: phoneNumber
                })
            });
            const d = await r.json();

            if (d.found) {
                foundResults.push(d);
                // 특정 프로필 선택 시에만 첫 결과에서 중단
                if (profileId) break;
            }
        }

        document.getElementById('searchLoading').style.display = 'none';
        document.getElementById('searchResult').style.display = 'block';

        if (foundResults.length > 0) {
            // 첫 번째 결과 사용 (또는 메시지가 가장 많은 결과)
            const foundResult = foundResults.sort((a, b) => (b.message_count || 0) - (a.message_count || 0))[0];

            document.getElementById('searchResult').innerHTML = `
                <div class="result-header found">✅ 대화 이력 발견!</div>
                <div>📱 번호: ${foundResult.phone_number}</div>
                <div>📞 프로필: ${foundResult.profile_id}</div>
                <div>💬 메시지: ${foundResult.message_count}개</div>
                <div class="result-action">
                    <button class="modal-btn primary" onclick="openSearchedConversation('${foundResult.profile_id}', '${foundResult.phone_number}')">
                        📖 대화 보기
                    </button>
                </div>
            `;
        } else {
            const searchedProfiles = profilesToSearch.join(', ');
            document.getElementById('searchResult').innerHTML = `
                <div class="result-header not-found">❌ 대화 이력 없음</div>
                <div>검색된 프로필: ${searchedProfiles}</div>
                <div class="result-action" style="margin-top:15px;">
                    <button class="modal-btn secondary" onclick="startNewConversation('${profileId || '8295'}', '${phoneNumber}')">
                        📝 새 대화 시작
                    </button>
                </div>
            `;
        }

    } catch (e) {
        document.getElementById('searchLoading').style.display = 'none';
        document.getElementById('searchResult').style.display = 'block';
        document.getElementById('searchResult').innerHTML = `
            <div class="no-result">❌ 검색 중 오류 발생</div>
        `;
    }
}

// 텍스트 내용으로 검색
function searchByText() {
    const keyword = document.getElementById('searchText').value.trim();

    if (!keyword) {
        showToast('검색어를 입력하세요', 'error');
        return;
    }

    if (keyword.length < 2) {
        showToast('검색어는 2글자 이상 입력하세요', 'error');
        return;
    }

    const results = searchInCache(keyword);

    document.getElementById('searchResult').style.display = 'block';

    if (results.length === 0) {
        document.getElementById('searchResult').innerHTML = `
            <div class="no-result">
                🔍 "${keyword}"에 대한 검색 결과가 없습니다.<br>
                <small style="color:#999;">캐시된 대화에서만 검색됩니다. 새로고침으로 더 많은 대화를 캐시하세요.</small>
            </div>
        `;
        return;
    }

    // 검색 결과 표시
    let html = `<div class="result-header found">✅ ${results.length}개 결과 발견</div>`;

    results.forEach((r, idx) => {
        // 키워드 하이라이트
        const highlightedText = r.text.replace(
            new RegExp(`(${keyword})`, 'gi'),
            '<mark>$1</mark>'
        );

        // 미리보기 (100자)
        let preview = highlightedText;
        if (preview.length > 100) {
            // 키워드 주변 텍스트 추출
            const keywordIdx = r.text.toLowerCase().indexOf(keyword.toLowerCase());
            const start = Math.max(0, keywordIdx - 30);
            const end = Math.min(r.text.length, keywordIdx + keyword.length + 70);
            preview = (start > 0 ? '...' : '') +
                highlightedText.substring(start, end) +
                (end < r.text.length ? '...' : '');
        }

        html += `
            <div class="search-result-item" onclick="openSearchedConversation('${r.profile_id}', '${r.sender.replace(/'/g, "\\'")}')">
                <div class="sender">📱 ${r.profile_id} → ${r.sender}</div>
                <div class="preview">${preview}</div>
                <div class="meta">${r.direction === 'incoming' ? '📥 수신' : '📤 발신'} ${r.timestamp || ''}</div>
            </div>
        `;
    });

    document.getElementById('searchResult').innerHTML = html;
}

function openSearchedConversation(profileId, sender) {
    closeSearchModal();
    openConversation(profileId, sender);
}

function startNewConversation(profileId, phoneNumber) {
    closeSearchModal();
    document.getElementById('sendFrom').value = profileId;
    document.getElementById('sendTo').value = phoneNumber.replace(/[^0-9]/g, '');
    document.getElementById('sendMessage').focus();
    showToast('번호가 입력되었습니다. 메시지를 작성하세요.', 'success');
}

// 검색 모달에서 Enter 키로 검색
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && document.getElementById('searchModal').classList.contains('show')) {
        if (document.activeElement.id === 'searchPhone') {
            searchByPhone();
        } else if (document.activeElement.id === 'searchText') {
            searchByText();
        }
    }
});

// ========== All-in-One 기능 ==========

let currentAioPlatform = '스마트스토어';
let aioSelectedAccounts = new Set();
// 플랫폼별 실행 상태 관리
let aioRunningByPlatform = {
    '스마트스토어': false,
    '11번가': false,
    '쿠팡': false,
    'ESM': false
};
let currentAioTask = '등록갯수';
let aioSelectedStores = new Set();
let aioStoreData = [];  // 전체 스토어 데이터 저장
let aioFilterThreshold = 0;  // 필터 기준값 (예: 9500)
let aioSortColumn = 'row_num';  // 정렬 컬럼 (기본: 구글시트 순서)
let aioSortAsc = true;  // 정렬 방향

// 플랫폼 선택
function selectAioPlatform(platform) {
    currentAioPlatform = platform;

    // 버튼 활성화
    document.querySelectorAll('.aio-platform-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.platform === platform);
    });

    // 작업 버튼 표시/숨김
    document.querySelectorAll('.aio-task-btn').forEach(btn => {
        const btnPlatform = btn.dataset.platform;
        btn.style.display = (btnPlatform === platform) ? '' : 'none';
    });

    // 선택 초기화 (작업 선택 전에 해야 pending selection이 유지됨)
    aioSelectedStores.clear();
    updateAioStoreCount();

    // 첫 번째 작업 선택
    const firstTask = document.querySelector(`.aio-task-btn[data-platform="${platform}"]`);
    if (firstTask) {
        selectAioTask(firstTask.dataset.task);
    }

    // 해당 플랫폼이 실행 중이면 폴링 재개 및 UI 업데이트
    if (aioRunningByPlatform[platform]) {
        document.getElementById('aioStopBtn').disabled = false;
        pollAioProgress(platform);
    } else {
        document.getElementById('aioStopBtn').disabled = true;
        document.getElementById('aioProgressFill').style.width = '0%';
        document.getElementById('aioProgressText').textContent = '0%';
        document.getElementById('aioStatus').innerHTML = '';
        document.getElementById('aioResults').innerHTML = '';
    }
}

// 작업 선택
function selectAioTask(task) {
    currentAioTask = task;

    // 버튼 활성화
    document.querySelectorAll('.aio-task-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.task === task);
    });

    // 작업 옵션 표시/숨김
    updateAioOptions(task);

    // 스토어 목록 로드
    loadAioStores(currentAioPlatform, task);
}

// 작업별 옵션 표시
function updateAioOptions(task) {
    const optionsSection = document.getElementById('aioOptionsSection');
    const optionUpdateMode = document.getElementById('optionUpdateMode');
    const optionDelete = document.getElementById('optionDelete');
    const deleteOptionsEl = document.getElementById('aioDeleteOptions');
    const optionKC = document.getElementById('optionKC');

    // 모든 옵션 숨김
    optionUpdateMode.style.display = 'none';
    optionDelete.style.display = 'none';
    if (deleteOptionsEl) deleteOptionsEl.style.display = 'none';
    if (optionKC) optionKC.style.display = 'none';

    // 기본 날짜 설정 (오늘 - 7일)
    const weekAgo = new Date();
    weekAgo.setDate(weekAgo.getDate() - 7);
    document.getElementById('aioTargetDate').value = weekAgo.toISOString().split('T')[0];

    // 작업별 옵션 표시
    if (task === '배송변경') {
        optionsSection.style.display = 'block';
        optionUpdateMode.style.display = 'block';
        // 수량/날짜 라디오 표시
        document.querySelector('.aio-radio-group').style.display = 'flex';
    } else if (task === '혜택설정') {
        optionsSection.style.display = 'block';
        optionUpdateMode.style.display = 'block';
        // 날짜만 표시 (라디오 숨김)
        document.querySelector('.aio-radio-group').style.display = 'none';
        document.getElementById('optionCount').style.display = 'none';
        document.getElementById('optionDate').style.display = 'block';
    } else if (task === '상품삭제') {
        optionsSection.style.display = 'block';
        optionDelete.style.display = 'block';
        // 삭제 옵션 섹션 표시
        if (deleteOptionsEl) deleteOptionsEl.style.display = 'block';
    } else if (task === 'KC인증') {
        optionsSection.style.display = 'block';
        if (optionKC) optionKC.style.display = 'block';
    } else {
        optionsSection.style.display = 'none';
    }
}

// 수량/날짜 옵션 토글
function toggleUpdateOption() {
    const mode = document.querySelector('input[name="updateMode"]:checked').value;
    document.getElementById('optionCount').style.display = mode === 'count' ? 'block' : 'none';
    document.getElementById('optionDate').style.display = mode === 'date' ? 'block' : 'none';
}

// KC인증 수량/날짜 옵션 토글
function toggleKCOption() {
    const mode = document.querySelector('input[name="kcUpdateMode"]:checked')?.value || 'count';
    document.getElementById('kcOptionCount').style.display = mode === 'count' ? 'block' : 'none';
    document.getElementById('kcOptionDate').style.display = mode === 'date' ? 'block' : 'none';

    // 기본 날짜 설정 (오늘 - 7일)
    if (mode === 'date' && !document.getElementById('aioKCDate').value) {
        const weekAgo = new Date();
        weekAgo.setDate(weekAgo.getDate() - 7);
        document.getElementById('aioKCDate').value = weekAgo.toISOString().split('T')[0];
    }
}

// 스토어 목록 로드 (구글시트에서)
async function loadAioStores(platform, task) {
    const grid = document.getElementById('aioStoreGrid');
    grid.innerHTML = '<div class="empty">로딩 중...</div>';

    try {
        const r = await fetch(`/api/allinone/stores?platform=${encodeURIComponent(platform)}&task=${encodeURIComponent(task)}`);
        const d = await r.json();

        if (!d.stores || d.stores.length === 0) {
            grid.innerHTML = '<div class="empty">스토어가 없습니다</div>';
            return;
        }

        aioStoreData = d.stores;
        aioSelectedStores.clear();

        // 활성화된 스토어 선택
        d.stores.forEach(store => {
            if (store.active === true || store.active === 'TRUE') {
                aioSelectedStores.add(store.스토어명);
            }
        });

        // 관제센터에서 넘어온 선택 적용 (aioPendingSelection)
        if (window.aioPendingSelection && window.aioPendingSelection.size > 0) {
            console.log('[AIO] Pending selection:', Array.from(window.aioPendingSelection));
            // 기존 선택 해제하고 pending만 적용
            aioSelectedStores.clear();
            const matchedStoreNames = new Set(); // 중복 방지

            window.aioPendingSelection.forEach(accountName => {
                // 여러 필드로 매칭 시도: 스토어명, shop_alias, login_id, 쇼핑몰별칭
                const matchedStore = d.stores.find(s =>
                    !matchedStoreNames.has(s.스토어명) && (
                        s.스토어명 === accountName ||
                        s.shop_alias === accountName ||
                        s.login_id === accountName ||
                        s['쇼핑몰 별칭'] === accountName ||
                        s['쇼핑몰별칭'] === accountName
                    )
                );
                if (matchedStore) {
                    console.log('[AIO] Matched:', accountName, '->', matchedStore.스토어명);
                    aioSelectedStores.add(matchedStore.스토어명);
                    matchedStoreNames.add(matchedStore.스토어명);
                } else {
                    console.log('[AIO] No match for:', accountName);
                }
            });
            // pending 초기화
            window.aioPendingSelection = null;

            // 먼저 UI 렌더링 (선택 상태 반영)
            renderAioStoreTable();
            updateAioStoreCount();

            // 선택 완료 후 시트에 자동 적용 (UI는 이미 올바르게 렌더링됨)
            setTimeout(() => {
                if (typeof applyAioSelection === 'function') {
                    applyAioSelection();
                }
            }, 300);
            return; // 이미 렌더링 완료, 아래 렌더링 스킵
        }

        renderAioStoreTable();
        updateAioStoreCount();
    } catch (e) {
        grid.innerHTML = '<div class="empty">스토어 로드 실패</div>';
        console.error(e);
    }
}

// 스토어 테이블 렌더링
function renderAioStoreTable() {
    const grid = document.getElementById('aioStoreGrid');

    // 필터링
    let filtered = [...aioStoreData];  // 복사본 생성
    if (aioFilterThreshold > 0) {
        filtered = filtered.filter(s => s.on_sale >= aioFilterThreshold);
    }

    // 소유자 필터
    const ownerFilter = document.getElementById('aioOwnerFilter')?.value || '';
    if (ownerFilter) {
        filtered = filtered.filter(s => s.owner === ownerFilter);
    }

    // 용도 필터 (AND 조건)
    const usageFilter = document.getElementById('aioUsageFilter')?.value || '';
    if (usageFilter) {
        filtered = filtered.filter(s => s.usage === usageFilter);
    }

    // 정렬 (기본: row_num 순서 = 구글시트 순서)
    if (aioSortColumn === 'row_num' || !aioSortColumn) {
        filtered.sort((a, b) => aioSortAsc ? (a.row_num || 0) - (b.row_num || 0) : (b.row_num || 0) - (a.row_num || 0));
    } else {
        filtered.sort((a, b) => {
            let va = a[aioSortColumn];
            let vb = b[aioSortColumn];
            if (typeof va === 'number' && typeof vb === 'number') {
                return aioSortAsc ? va - vb : vb - va;
            }
            va = String(va || '');
            vb = String(vb || '');
            return aioSortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        });
    }

    // 삭제 기준값 (상품삭제 작업일 때)
    const deleteLimit = parseInt(document.getElementById('aioDeleteLimit')?.value) || 9500;

    // 작업별 테이블 헤더/바디 생성
    let tableHeader = '';
    let tableBody = '';

    if (currentAioTask === '배송변경') {
        // 배송변경: 변경수량, 출고지, 지역배송문구, 오늘출발시간 (편집 가능)
        tableHeader = `
            <th class="col-check"><input type="checkbox" onchange="toggleAllAioStores(this.checked)" ${aioSelectedStores.size === filtered.length && filtered.length > 0 ? 'checked' : ''}></th>
            <th class="col-rownum sortable" onclick="sortAioTable('row_num')"># ${aioSortColumn === 'row_num' ? (aioSortAsc ? '▲' : '▼') : ''}</th>
            <th class="col-name sortable" onclick="sortAioTable('store_name')">스토어명 ${aioSortColumn === 'store_name' ? (aioSortAsc ? '▲' : '▼') : ''}</th>
            <th class="col-input-sm">변경수량</th>
            <th class="col-input-sm">출고지</th>
            <th class="col-input-lg">지역배송문구</th>
            <th class="col-input-sm">오늘출발</th>
            <th class="col-owner">소유자</th>
            <th class="col-usage">용도</th>
            <th class="col-date">updated</th>
        `;
        tableBody = filtered.map(store => {
            const isSelected = aioSelectedStores.has(store.스토어명);
            const sn = store.스토어명.replace(/'/g, "\\'");
            const 국내코드 = store['국내출고지코드'] || '';
            const 해외코드 = store['해외출고지코드'] || '';
            const currentShipId = store.shippingAddressId || '';
            // 현재 출고지가 국내/해외 코드와 일치하는지 확인
            let selectedType = '';
            if (currentShipId === 국내코드 && 국내코드) selectedType = '국내';
            else if (currentShipId === 해외코드 && 해외코드) selectedType = '해외';

            return `
                <tr class="${isSelected ? 'selected' : ''}" data-store="${store.스토어명}">
                    <td class="col-check"><input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleAioStore('${sn}')"></td>
                    <td class="col-rownum">${store.row_num || '-'}</td>
                    <td class="col-name">${store.스토어명}</td>
                    <td class="col-input-sm"><input type="text" class="tbl-input" data-store="${sn}" data-field="target_limit" value="${store.target_limit || ''}" onchange="updateAioField(this)"></td>
                    <td class="col-input-sm">
                        <select class="tbl-select" data-store="${sn}" data-field="shippingAddressId" data-국내="${국내코드}" data-해외="${해외코드}" onchange="updateShippingType(this)">
                            <option value="">선택</option>
                            <option value="국내" ${selectedType === '국내' ? 'selected' : ''} ${!국내코드 ? 'disabled' : ''}>국내${국내코드 ? '' : '(없음)'}</option>
                            <option value="해외" ${selectedType === '해외' ? 'selected' : ''} ${!해외코드 ? 'disabled' : ''}>해외${해외코드 ? '' : '(없음)'}</option>
                        </select>
                    </td>
                    <td class="col-input-lg"><input type="text" class="tbl-input wide" data-store="${sn}" data-field="differentialFeeByArea" value="${(store.differentialFeeByArea || '').replace(/"/g, '&quot;')}" onchange="updateAioField(this)" title="${store.differentialFeeByArea || ''}"></td>
                    <td class="col-input-sm"><input type="text" class="tbl-input" data-store="${sn}" data-field="cutofftime" value="${store.cutofftime || ''}" onchange="updateAioField(this)"></td>
                    <td class="col-owner">${store.owner || '-'}</td>
                    <td class="col-usage">${store.usage || '-'}</td>
                    <td class="col-date">${store.delivery_updated_at ? store.delivery_updated_at.substring(0, 10) : '-'}</td>
                </tr>
            `;
        }).join('');

    } else if (currentAioTask === '배송코드') {
        // 배송코드: 국내출고지, 해외출고지, 반품지 표시
        tableHeader = `
            <th class="col-check"><input type="checkbox" onchange="toggleAllAioStores(this.checked)" ${aioSelectedStores.size === filtered.length && filtered.length > 0 ? 'checked' : ''}></th>
            <th class="col-rownum sortable" onclick="sortAioTable('row_num')"># ${aioSortColumn === 'row_num' ? (aioSortAsc ? '▲' : '▼') : ''}</th>
            <th class="col-name sortable" onclick="sortAioTable('store_name')">스토어명 ${aioSortColumn === 'store_name' ? (aioSortAsc ? '▲' : '▼') : ''}</th>
            <th class="col-num">국내출고지</th>
            <th class="col-num">해외출고지</th>
            <th class="col-num">반품지</th>
            <th class="col-owner">소유자</th>
            <th class="col-usage">용도</th>
            <th class="col-date">updated</th>
        `;
        tableBody = filtered.map(store => {
            const isSelected = aioSelectedStores.has(store.스토어명);
            const sn = store.스토어명.replace(/'/g, "\\'");
            return `
                <tr class="${isSelected ? 'selected' : ''}" data-store="${store.스토어명}">
                    <td class="col-check"><input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleAioStore('${sn}')"></td>
                    <td class="col-rownum">${store.row_num || '-'}</td>
                    <td class="col-name">${store.스토어명}</td>
                    <td class="col-num">${store['국내출고지'] || '-'}</td>
                    <td class="col-num">${store['해외출고지'] || '-'}</td>
                    <td class="col-num">${store['반품지'] || '-'}</td>
                    <td class="col-owner">${store.owner || '-'}</td>
                    <td class="col-usage">${store.usage || '-'}</td>
                    <td class="col-date">${store.shipping_updated_at ? store.shipping_updated_at.substring(0, 10) : '-'}</td>
                </tr>
            `;
        }).join('');

    } else if (currentAioTask === '혜택설정') {
        // 혜택설정: 후기포인트들, 사은품, 최소판매가, 복수구매 (편집 가능, 이벤트문구 제외)
        tableHeader = `
            <th class="col-check"><input type="checkbox" onchange="toggleAllAioStores(this.checked)" ${aioSelectedStores.size === filtered.length && filtered.length > 0 ? 'checked' : ''}></th>
            <th class="col-rownum sortable" onclick="sortAioTable('row_num')"># ${aioSortColumn === 'row_num' ? (aioSortAsc ? '▲' : '▼') : ''}</th>
            <th class="col-name sortable" onclick="sortAioTable('store_name')">스토어명 ${aioSortColumn === 'store_name' ? (aioSortAsc ? '▲' : '▼') : ''}</th>
            <th class="col-input-xs">후기</th>
            <th class="col-input-xs">포토</th>
            <th class="col-input-xs">1달후기</th>
            <th class="col-input-xs">1달포토</th>
            <th class="col-input-sm">사은품</th>
            <th class="col-input-xs">최소가</th>
            <th class="col-input-xs">복수</th>
            <th class="col-input-xs">복수할인</th>
            <th class="col-owner">소유자</th>
            <th class="col-usage">용도</th>
            <th class="col-date">updated</th>
        `;
        tableBody = filtered.map(store => {
            const isSelected = aioSelectedStores.has(store.스토어명);
            const sn = store.스토어명.replace(/'/g, "\\'");
            return `
                <tr class="${isSelected ? 'selected' : ''}" data-store="${store.스토어명}">
                    <td class="col-check"><input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleAioStore('${sn}')"></td>
                    <td class="col-rownum">${store.row_num || '-'}</td>
                    <td class="col-name">${store.스토어명}</td>
                    <td class="col-input-xs"><input type="text" class="tbl-input xs" data-store="${sn}" data-field="후기포인트" value="${store['후기포인트'] || ''}" onchange="updateAioField(this)"></td>
                    <td class="col-input-xs"><input type="text" class="tbl-input xs" data-store="${sn}" data-field="포토후기포인트" value="${store['포토후기포인트'] || ''}" onchange="updateAioField(this)"></td>
                    <td class="col-input-xs"><input type="text" class="tbl-input xs" data-store="${sn}" data-field="한달후기포인트" value="${store['한달후기포인트'] || ''}" onchange="updateAioField(this)"></td>
                    <td class="col-input-xs"><input type="text" class="tbl-input xs" data-store="${sn}" data-field="한달포토후기포인트" value="${store['한달포토후기포인트'] || ''}" onchange="updateAioField(this)"></td>
                    <td class="col-input-sm"><input type="text" class="tbl-input" data-store="${sn}" data-field="사은품" value="${(store['사은품'] || '').replace(/"/g, '&quot;')}" onchange="updateAioField(this)"></td>
                    <td class="col-input-xs"><input type="text" class="tbl-input xs" data-store="${sn}" data-field="최소판매가" value="${store['최소판매가'] || ''}" onchange="updateAioField(this)"></td>
                    <td class="col-input-xs"><input type="text" class="tbl-input xs" data-store="${sn}" data-field="복수구매" value="${store['복수구매'] || ''}" onchange="updateAioField(this)"></td>
                    <td class="col-input-xs"><input type="text" class="tbl-input xs" data-store="${sn}" data-field="복수구매할인" value="${store['복수구매할인'] || ''}" onchange="updateAioField(this)"></td>
                    <td class="col-owner">${store.owner || '-'}</td>
                    <td class="col-usage">${store.usage || '-'}</td>
                    <td class="col-date">${store.benefit_updated_at ? store.benefit_updated_at.substring(0, 10) : '-'}</td>
                </tr>
            `;
        }).join('');

    } else {
        // 기본 (등록갯수, 상품삭제 등): 상품수 정보 표시
        tableHeader = `
            <th class="col-check"><input type="checkbox" onchange="toggleAllAioStores(this.checked)" ${aioSelectedStores.size === filtered.length && filtered.length > 0 ? 'checked' : ''}></th>
            <th class="col-rownum sortable" onclick="sortAioTable('row_num')"># ${aioSortColumn === 'row_num' ? (aioSortAsc ? '▲' : '▼') : ''}</th>
            <th class="col-name sortable" onclick="sortAioTable('store_name')">스토어명 ${aioSortColumn === 'store_name' ? (aioSortAsc ? '▲' : '▼') : ''}</th>
            <th class="col-num sortable" onclick="sortAioTable('total')">전체 ${aioSortColumn === 'total' ? (aioSortAsc ? '▲' : '▼') : ''}</th>
            <th class="col-num sortable" onclick="sortAioTable('on_sale')">판매중 ${aioSortColumn === 'on_sale' ? (aioSortAsc ? '▲' : '▼') : ''}</th>
            <th class="col-num sortable" onclick="sortAioTable('suspended')">판매중지 ${aioSortColumn === 'suspended' ? (aioSortAsc ? '▲' : '▼') : ''}</th>
            <th class="col-num sortable" onclick="sortAioTable('pending')">승인대기 ${aioSortColumn === 'pending' ? (aioSortAsc ? '▲' : '▼') : ''}</th>
            <th class="col-owner">소유자</th>
            <th class="col-usage">용도</th>
            ${currentAioTask === '상품삭제' ? '<th class="col-delete">삭제수량</th>' : ''}
            <th class="col-date">updated</th>
        `;
        tableBody = filtered.map(store => {
            const isSelected = aioSelectedStores.has(store.스토어명);
            const deleteCount = Math.max(0, store.on_sale - deleteLimit);
            const overLimit = store.on_sale >= deleteLimit;
            const hasPending = (store.pending || 0) > 0;

            return `
                <tr class="${isSelected ? 'selected' : ''} ${overLimit ? 'over-limit' : ''}" data-store="${store.스토어명}">
                    <td class="col-check"><input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleAioStore('${store.스토어명}')"></td>
                    <td class="col-rownum">${store.row_num || '-'}</td>
                    <td class="col-name">${store.스토어명}</td>
                    <td class="col-num">${(store.total || 0).toLocaleString()}</td>
                    <td class="col-num ${overLimit ? 'highlight-red' : ''}">${(store.on_sale || 0).toLocaleString()}</td>
                    <td class="col-num">${(store.suspended || 0).toLocaleString()}</td>
                    <td class="col-num ${hasPending ? 'highlight-orange' : ''}">${(store.pending || 0).toLocaleString()}</td>
                    <td class="col-owner">${store.owner || '-'}</td>
                    <td class="col-usage">${store.usage || '-'}</td>
                    ${currentAioTask === '상품삭제' ? `<td class="col-delete">${deleteCount > 0 ? deleteCount.toLocaleString() : '-'}</td>` : ''}
                    <td class="col-date">${store.updated_at ? store.updated_at.substring(5, 16) : '-'}</td>
                </tr>
            `;
        }).join('');
    }

    // 테이블 HTML
    grid.innerHTML = `
        <table class="aio-store-table">
            <thead><tr>${tableHeader}</tr></thead>
            <tbody>${tableBody}</tbody>
        </table>
    `;

    // 삭제 작업일 때 총 삭제 예정 수량 표시
    if (currentAioTask === '상품삭제') {
        const totalDelete = filtered
            .filter(s => aioSelectedStores.has(s.스토어명))
            .reduce((sum, s) => sum + Math.max(0, s.on_sale - deleteLimit), 0);

        const summaryEl = document.getElementById('aioDeleteSummary');
        if (summaryEl) {
            summaryEl.textContent = `선택된 스토어 총 삭제 예정: ${totalDelete.toLocaleString()}개`;
        }
    }

    // 그룹 필터 옵션 업데이트
    updateGroupFilterOptions();
}

// 그룹 필터 옵션 업데이트
function updateGroupFilterOptions() {
    updateFilterDropdown('aioOwnerFilter', 'owner');
    updateFilterDropdown('aioUsageFilter', 'usage');
}

function updateFilterDropdown(elementId, field) {
    const dropdown = document.getElementById(elementId);
    if (!dropdown) return;

    const currentValue = dropdown.value;
    const values = new Set();

    aioStoreData.forEach(s => {
        if (s[field]) values.add(s[field]);
    });

    dropdown.innerHTML = '<option value="">전체</option>' +
        Array.from(values).sort().map(v => `<option value="${v}" ${v === currentValue ? 'selected' : ''}>${v}</option>`).join('');
}

// 테이블 필드 수정 시 데이터 업데이트
let aioEditedFields = {};  // {store_name: {field: value}}

function updateAioField(input) {
    const storeName = input.dataset.store;
    const field = input.dataset.field;
    const value = input.value;

    // aioStoreData 업데이트
    const store = aioStoreData.find(s => s.스토어명 === storeName);
    if (store) {
        store[field] = value;
    }

    // 수정된 필드 추적
    if (!aioEditedFields[storeName]) {
        aioEditedFields[storeName] = {};
    }
    aioEditedFields[storeName][field] = value;

    // 변경 표시
    input.classList.add('edited');
}

// 출고지 드롭다운 선택 시 코드로 변환
function updateShippingType(select) {
    const storeName = select.dataset.store;
    const selectedType = select.value;
    const 국내코드 = select.dataset['국내'];
    const 해외코드 = select.dataset['해외'];

    // 선택된 타입에 따라 코드 설정
    let code = '';
    if (selectedType === '국내') code = 국내코드;
    else if (selectedType === '해외') code = 해외코드;

    // aioStoreData 업데이트
    const store = aioStoreData.find(s => s.스토어명 === storeName);
    if (store) {
        store.shippingAddressId = code;
    }

    // 수정된 필드 추적
    if (!aioEditedFields[storeName]) {
        aioEditedFields[storeName] = {};
    }
    aioEditedFields[storeName].shippingAddressId = code;

    // 변경 표시
    select.classList.add('edited');
}

// 테이블 정렬
function sortAioTable(column) {
    if (aioSortColumn === column) {
        aioSortAsc = !aioSortAsc;
    } else {
        aioSortColumn = column;
        aioSortAsc = true;
    }
    renderAioStoreTable();
}

// 필터 적용
function applyAioFilter() {
    const threshold = parseInt(document.getElementById('aioFilterThreshold')?.value) || 0;
    aioFilterThreshold = threshold;
    renderAioStoreTable();
    updateAioStoreCount();
}

// 필터 초기화
function clearAioFilter() {
    aioFilterThreshold = 0;
    const el = document.getElementById('aioFilterThreshold');
    if (el) el.value = '';
    const ownerEl = document.getElementById('aioOwnerFilter');
    if (ownerEl) ownerEl.value = '';
    const usageEl = document.getElementById('aioUsageFilter');
    if (usageEl) usageEl.value = '';
    renderAioStoreTable();
    updateAioStoreCount();
}

// 기준 이상만 선택
function selectOverLimit() {
    const limit = parseInt(document.getElementById('aioDeleteLimit')?.value) || 9500;
    aioSelectedStores.clear();
    aioStoreData.forEach(store => {
        if (store.on_sale >= limit) {
            aioSelectedStores.add(store.스토어명);
        }
    });
    renderAioStoreTable();
    updateAioStoreCount();
}

// 전체 토글
function toggleAllAioStores(checked) {
    let filtered = aioStoreData;
    if (aioFilterThreshold > 0) {
        filtered = aioStoreData.filter(s => s.on_sale >= aioFilterThreshold);
    }
    const groupFilter = document.getElementById('aioGroupFilter')?.value || '';
    if (groupFilter) {
        filtered = filtered.filter(s => s.group === groupFilter);
    }

    if (checked) {
        filtered.forEach(s => aioSelectedStores.add(s.스토어명));
    } else {
        filtered.forEach(s => aioSelectedStores.delete(s.스토어명));
    }
    renderAioStoreTable();
    updateAioStoreCount();
}

// 스토어 선택 토글
function toggleAioStore(storeName) {
    if (aioSelectedStores.has(storeName)) {
        aioSelectedStores.delete(storeName);
    } else {
        aioSelectedStores.add(storeName);
    }

    // 테이블 행 업데이트
    const row = document.querySelector(`tr[data-store="${storeName}"]`);
    if (row) {
        row.classList.toggle('selected', aioSelectedStores.has(storeName));
        const checkbox = row.querySelector('input[type="checkbox"]');
        if (checkbox) checkbox.checked = aioSelectedStores.has(storeName);
    }

    updateAioStoreCount();
}

// 전체 선택
function selectAllAioStores() {
    aioStoreData.forEach(store => {
        aioSelectedStores.add(store.스토어명);
    });
    renderAioStoreTable();
    updateAioStoreCount();
}

// 전체 해제
function deselectAllAioStores() {
    aioSelectedStores.clear();
    renderAioStoreTable();
    updateAioStoreCount();
}

// 스토어 수 업데이트
function updateAioStoreCount() {
    const count = aioSelectedStores.size;
    document.getElementById('aioStoreCount').textContent = `(${count}개 선택)`;
}

// 선택 적용 (구글시트 active 업데이트)
async function applyAioSelection() {
    const stores = Array.from(aioSelectedStores);
    const allStores = Array.from(document.querySelectorAll('.aio-store-item')).map(item => item.dataset.store);

    showToast('시트 업데이트 중...', 'info');

    try {
        const r = await fetch('/api/allinone/update-active', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                platform: currentAioPlatform,
                task: currentAioTask,
                active_stores: stores,
                all_stores: allStores
            })
        });
        const d = await r.json();

        if (d.success) {
            showToast(`시트 업데이트 완료 (${stores.length}개 활성화)`, 'success');
        } else {
            showToast('업데이트 실패: ' + d.message, 'error');
        }
    } catch (e) {
        showToast('오류 발생', 'error');
    }
}

// All-in-One 작업 실행
async function runAioTask() {
    if (aioSelectedStores.size === 0) {
        showToast('스토어를 선택하세요', 'error');
        return;
    }

    // 먼저 선택 적용
    await applyAioSelection();

    const results = document.getElementById('aioResults');
    results.innerHTML = '<div class="aio-result-item running"><span class="result-icon">🔄</span><span class="result-message">프로그램 실행 중...</span></div>';

    document.getElementById('aioStopBtn').disabled = false;
    document.getElementById('aioProgressFill').style.width = '0%';
    document.getElementById('aioProgressText').textContent = '0%';

    // 현재 플랫폼 실행 상태 설정
    aioRunningByPlatform[currentAioPlatform] = true;

    // 작업 옵션 수집
    const options = {};
    if (currentAioTask === '배송변경') {
        const mode = document.querySelector('input[name="updateMode"]:checked')?.value || 'count';
        options.mode = mode;
        if (mode === 'count') {
            options.count = parseInt(document.getElementById('aioTargetCount').value) || 100;
        } else {
            options.date = document.getElementById('aioTargetDate').value;
        }
    } else if (currentAioTask === '혜택설정') {
        // 혜택설정은 날짜만 사용
        options.date = document.getElementById('aioTargetDate').value;
    } else if (currentAioTask === '상품삭제') {
        const excessOnly = document.getElementById('aioDeleteExcessOnly')?.checked;
        if (excessOnly) {
            // 초과분만 삭제: 삭제 기준 값 사용
            const deleteLimit = parseInt(document.getElementById('aioDeleteLimit').value) || 9500;
            options.delete_excess_only = true;
            options.delete_limit = deleteLimit;
            // delete_count는 각 스토어별로 서버에서 계산
        } else {
            options.delete_count = parseInt(document.getElementById('aioDeleteCount').value) || 50;
        }
    } else if (currentAioTask === 'KC인증') {
        // KC인증은 별도 API 사용
        const kcMode = document.querySelector('input[name="kcUpdateMode"]:checked')?.value || 'count';
        const productLimit = parseInt(document.getElementById('aioKCLimit')?.value) || 2000;
        const targetDate = document.getElementById('aioKCDate')?.value || '';
        const activeStores = Array.from(aioSelectedStores);

        try {
            const r = await fetch('/api/allinone/kc-modify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    stores: activeStores,
                    product_limit: productLimit,
                    mode: kcMode,
                    target_date: targetDate
                })
            });
            const d = await r.json();

            if (d.success) {
                showToast('KC 인증 수정 시작', 'success');
                results.innerHTML = `<div class="aio-result-item running"><span class="result-icon">🔄</span><span class="result-message">${d.message}</span></div>`;
                aioRunningByPlatform[currentAioPlatform] = true;
                pollKCProgress();
            } else {
                showToast('실행 실패: ' + d.message, 'error');
                results.innerHTML = `<div class="aio-result-item error"><span class="result-icon">❌</span><span class="result-message">${d.message}</span></div>`;
            }
        } catch (e) {
            showToast('오류 발생', 'error');
            results.innerHTML = `<div class="aio-result-item error"><span class="result-icon">❌</span><span class="result-message">오류: ${e.message}</span></div>`;
        }
        return;  // KC인증은 여기서 종료
    } else if (currentAioTask === '매출조회') {
        // 매출조회는 별도 API 사용
        const activeStores = Array.from(aioSelectedStores);
        try {
            const r = await fetch('/api/allinone/sales-query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    stores: activeStores,
                    platform: currentAioPlatform
                })
            });
            const d = await r.json();

            if (d.success) {
                showToast('매출 조회 시작', 'success');
                results.innerHTML = `<div class="aio-result-item running"><span class="result-icon">🔄</span><span class="result-message">${d.message}</span></div>`;
                aioRunningByPlatform[currentAioPlatform] = true;
                pollSalesProgress();
            } else {
                showToast('실행 실패: ' + d.message, 'error');
                results.innerHTML = `<div class="aio-result-item error"><span class="result-icon">❌</span><span class="result-message">${d.message}</span></div>`;
            }
        } catch (e) {
            showToast('오류 발생', 'error');
            results.innerHTML = `<div class="aio-result-item error"><span class="result-icon">❌</span><span class="result-message">오류: ${e.message}</span></div>`;
        }
        return;  // 매출조회는 여기서 종료
    }

    const runningPlatform = currentAioPlatform; // 클로저를 위해 저장

    // 선택된 스토어 목록
    const selectedStoresList = Array.from(aioSelectedStores);

    try {
        const r = await fetch('/api/allinone/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                platform: runningPlatform,
                task: currentAioTask,
                options: options,
                stores: selectedStoresList  // 선택된 스토어 전달
            })
        });
        const d = await r.json();

        if (d.success) {
            showToast('프로그램 실행 시작', 'success');
            results.innerHTML = `<div class="aio-result-item running"><span class="result-icon">🔄</span><span class="result-message">${d.message || '실행 중...'}</span></div>`;

            // 진행상황 폴링 시작 (플랫폼 전달)
            pollAioProgress(runningPlatform);
        } else {
            aioRunningByPlatform[runningPlatform] = false;
            showToast('실행 실패: ' + d.message, 'error');
            results.innerHTML = `<div class="aio-result-item error"><span class="result-icon">❌</span><span class="result-message">${d.message}</span></div>`;
        }
    } catch (e) {
        aioRunningByPlatform[runningPlatform] = false;
        showToast('오류 발생', 'error');
        results.innerHTML = `<div class="aio-result-item error"><span class="result-icon">❌</span><span class="result-message">오류: ${e.message}</span></div>`;
        document.getElementById('aioStopBtn').disabled = true;
    }
}

// 진행상황 폴링 (플랫폼별)
async function pollAioProgress(platform) {
    if (!aioRunningByPlatform[platform]) return;

    try {
        const r = await fetch(`/api/allinone/progress?platform=${encodeURIComponent(platform)}`);
        const d = await r.json();

        // 현재 보고 있는 플랫폼일 때만 UI 업데이트
        if (platform === currentAioPlatform) {
            // 프로그레스 바 업데이트
            const percent = d.progress || 0;
            document.getElementById('aioProgressFill').style.width = `${percent}%`;
            document.getElementById('aioProgressText').textContent = `${percent}%`;

            // 진행 상황 텍스트 업데이트
            const statusEl = document.getElementById('aioStatus');
            if (d.current_store) {
                const completed = d.completed || 0;
                const total = d.total || 0;
                statusEl.innerHTML = `
                    <div>📍 현재: <strong>${d.current_store}</strong></div>
                    <div style="color:#888; font-size:12px;">진행: ${completed}/${total} 스토어 ${d.current_action || ''}</div>
                `;
            } else if (d.status === 'completed') {
                statusEl.innerHTML = `<div style="color:#4caf50;">✅ 모든 작업 완료</div>`;
            } else if (d.status === 'stopped') {
                statusEl.innerHTML = `<div style="color:#ff9800;">⏹️ 작업 중지됨</div>`;
            }

            // 로그 표시
            if (d.logs && d.logs.length > 0) {
                const results = document.getElementById('aioResults');
                const logsHtml = d.logs.slice(-20).map(log => {
                    // 메시지에서 [HH:MM:SS] 형태의 시간 제거 (이미 time 필드에 있음)
                    let msg = log.msg.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '');
                    return `
                    <div class="aio-result-item running">
                        <span class="result-time" style="color:#999; min-width:60px;">${log.time}</span>
                        <span class="result-message">${msg}</span>
                    </div>
                `}).join('');
                results.innerHTML = logsHtml;
                // 자동 스크롤
                results.scrollTop = results.scrollHeight;
            }
        }

        // 완료 확인
        if (d.status === 'completed' || d.status === 'stopped') {
            aioRunningByPlatform[platform] = false;
            if (platform === currentAioPlatform) {
                document.getElementById('aioStopBtn').disabled = true;

                // 현재 보고 있는 올인원 화면이면 스토어 데이터 새로고침
                if (currentAioTask) {
                    loadAioStores(platform, currentAioTask);
                }
            }
            showToast(`[${platform}] ${d.status === 'completed' ? '작업 완료' : '작업 중지됨'}`, d.status === 'completed' ? 'success' : 'info');

            // 작업 완료 시 계정 데이터 새로고침 (등록갯수 등 반영)
            loadAccounts();

            // 마켓현황도 새로고침
            if (typeof loadMarketTable === 'function') {
                loadMarketTable();
            }
            return;
        }

        // 계속 폴링
        setTimeout(() => pollAioProgress(platform), 1000);
    } catch (e) {
        console.error('폴링 오류:', e);
        setTimeout(() => pollAioProgress(platform), 2000);
    }
}

// 작업 중지
async function stopAioTask() {
    // KC인증인 경우 별도 중지 API
    if (currentAioTask === 'KC인증') {
        try {
            await fetch('/api/allinone/kc-stop', { method: 'POST' });
            showToast('KC 인증 수정 중지 요청됨', 'info');
        } catch (e) { }
        aioRunningByPlatform[currentAioPlatform] = false;
        document.getElementById('aioStopBtn').disabled = true;
        return;
    }

    // 매출조회인 경우 별도 중지 API
    if (currentAioTask === '매출조회') {
        try {
            await fetch('/api/allinone/sales-stop', { method: 'POST' });
            showToast('매출 조회 중지 요청됨', 'info');
        } catch (e) { }
        aioRunningByPlatform[currentAioPlatform] = false;
        document.getElementById('aioStopBtn').disabled = true;
        return;
    }

    aioRunningByPlatform[currentAioPlatform] = false;

    try {
        await fetch(`/api/allinone/stop?platform=${encodeURIComponent(currentAioPlatform)}`, { method: 'POST' });
        showToast(`[${currentAioPlatform}] 중지 요청됨`, 'info');
    } catch (e) { }

    document.getElementById('aioStopBtn').disabled = true;
}

// KC 인증 수정 진행상황 폴링
async function pollKCProgress() {
    if (!aioRunningByPlatform[currentAioPlatform]) return;

    try {
        const r = await fetch('/api/allinone/kc-progress');
        const d = await r.json();

        const results = document.getElementById('aioResults');

        // 진행상황 표시
        let html = '';
        let totalSuccess = 0;
        let totalFail = 0;
        let allDone = true;

        for (const [store, info] of Object.entries(d.progress || {})) {
            const pct = info.total > 0 ? Math.round(info.progress / info.total * 100) : 0;
            const statusIcon = info.status.includes('완료') ? '✅' :
                info.status.includes('오류') ? '❌' : '🔄';

            html += `<div class="aio-result-item">
                <span class="result-icon">${statusIcon}</span>
                <span class="result-message">${store}: ${info.status} (${info.success}/${info.progress})</span>
                <div style="width:100px;height:4px;background:#ddd;margin-left:auto;border-radius:2px;">
                    <div style="width:${pct}%;height:100%;background:#4caf50;border-radius:2px;"></div>
                </div>
            </div>`;

            totalSuccess += info.success || 0;
            totalFail += info.fail || 0;

            if (!info.status.includes('완료') && !info.status.includes('오류')) {
                allDone = false;
            }
        }

        // 로그 표시
        if (d.logs && d.logs.length > 0) {
            html += '<div style="margin-top:10px;border-top:1px solid #ddd;padding-top:10px;max-height:200px;overflow-y:auto;">';
            const recentLogs = d.logs.slice(-20);
            for (const log of recentLogs) {
                const color = log.status === 'error' ? '#f44336' :
                    log.status === 'success' ? '#4caf50' : '#666';
                html += `<div style="font-size:12px;color:${color};">[${log.time}] ${log.store}: ${log.msg}</div>`;
            }
            html += '</div>';
        }

        results.innerHTML = html;

        // 전체 진행률
        const storeCount = Object.keys(d.progress || {}).length;
        if (storeCount > 0) {
            document.getElementById('aioProgressText').textContent = `성공: ${totalSuccess}, 실패: ${totalFail}`;
        }

        // 완료 확인
        if (!d.running || allDone) {
            aioRunningByPlatform[currentAioPlatform] = false;
            document.getElementById('aioStopBtn').disabled = true;
            showToast(`KC 인증 수정 완료 (성공: ${totalSuccess}, 실패: ${totalFail})`, 'success');

            // 스토어 데이터 새로고침
            if (currentAioTask) {
                loadAioStores(currentAioPlatform, currentAioTask);
            }
            return;
        }

        // 계속 폴링
        setTimeout(pollKCProgress, 1000);
    } catch (e) {
        console.error('KC 폴링 오류:', e);
        setTimeout(pollKCProgress, 2000);
    }
}

// 매출 조회 진행상황 폴링
async function pollSalesProgress() {
    if (!aioRunningByPlatform[currentAioPlatform]) return;

    try {
        const r = await fetch('/api/allinone/sales-progress');
        const d = await r.json();

        const results = document.getElementById('aioResults');

        let html = '';
        let allDone = true;
        let totalTodaySales = 0;
        let totalMonthSales = 0;

        for (const [store, info] of Object.entries(d.progress || {})) {
            const statusIcon = info.status.includes('완료') ? '✅' :
                info.status.includes('오류') ? '❌' : '🔄';

            const todaySales = info.today_sales || 0;
            const monthSales = info.month_sales || 0;

            html += `<div class="aio-result-item">
                <span class="result-icon">${statusIcon}</span>
                <span class="result-message"><strong>${store}</strong>: ${info.status}</span>
            </div>`;

            if (info.today_sales !== undefined) {
                html += `<div style="margin-left:30px;font-size:12px;color:#666;">
                    💰 오늘: ₩${todaySales.toLocaleString()} (${info.today_orders || 0}건) / 
                    📅 이달: ₩${monthSales.toLocaleString()} (${info.month_orders || 0}건)
                </div>`;
            }

            totalTodaySales += todaySales;
            totalMonthSales += monthSales;

            if (!info.status.includes('완료') && !info.status.includes('오류')) {
                allDone = false;
            }
        }

        // 로그 표시
        if (d.logs && d.logs.length > 0) {
            html += '<div style="margin-top:10px;border-top:1px solid #ddd;padding-top:10px;max-height:150px;overflow-y:auto;">';
            const recentLogs = d.logs.slice(-15);
            for (const log of recentLogs) {
                const color = log.status === 'error' ? '#f44336' :
                    log.status === 'success' ? '#4caf50' : '#666';
                html += `<div style="font-size:11px;color:${color};">[${log.time}] ${log.store}: ${log.msg}</div>`;
            }
            html += '</div>';
        }

        results.innerHTML = html;

        // 전체 합계
        document.getElementById('aioProgressText').textContent =
            `오늘 ₩${totalTodaySales.toLocaleString()} / 이달 ₩${totalMonthSales.toLocaleString()}`;

        // 완료 확인
        if (!d.running || allDone) {
            aioRunningByPlatform[currentAioPlatform] = false;
            document.getElementById('aioStopBtn').disabled = true;
            showToast(`매출 조회 완료 (오늘 ₩${totalTodaySales.toLocaleString()})`, 'success');

            // 스토어 데이터 새로고침
            if (currentAioTask) {
                loadAioStores(currentAioPlatform, currentAioTask);
            }
            return;
        }

        setTimeout(pollSalesProgress, 1000);
    } catch (e) {
        console.error('매출 폴링 오류:', e);
        setTimeout(pollSalesProgress, 2000);
    }
}

// 초기화 시 플랫폼 로드
document.addEventListener('DOMContentLoaded', () => {
    // All-in-One 탭이 활성화될 때 스토어 로드
    setTimeout(() => {
        if (document.getElementById('tab-allinone')) {
            selectAioPlatform('스마트스토어');
        }
    }, 500);

    // 현재 월 자동 선택
    const aliMonth = document.getElementById('aliMonth');
    if (aliMonth) {
        aliMonth.value = `${new Date().getMonth() + 1}월`;
    }
});

// ========== 알리 송장번호 수집 ==========
let aliBrowserConnected = false;
let aliRunning = false;

function aliLog(message, type = '') {
    const logContent = document.getElementById('aliLogContent');
    if (!logContent) return;

    const line = document.createElement('div');
    line.className = 'log-line' + (type ? ` ${type}` : '');
    line.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    logContent.appendChild(line);
    logContent.scrollTop = logContent.scrollHeight;
}

function setAliStatus(status, text) {
    const statusEl = document.getElementById('aliStatus');
    if (!statusEl) return;

    statusEl.className = 'tool-status ' + status;
    statusEl.querySelector('.status-text').textContent = text;
}

async function connectAliBrowser() {
    const port = document.getElementById('aliDebugPort').value || '9222';

    aliLog('Chrome 브라우저 연결 중...', 'info');
    setAliStatus('', '브라우저 연결 중...');

    try {
        const r = await fetch('/api/ali/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ debug_port: parseInt(port) })
        });
        const d = await r.json();

        if (d.success) {
            aliBrowserConnected = true;
            setAliStatus('connected', '브라우저 연결됨');
            aliLog('Chrome 연결 성공!', 'success');
            aliLog('알리익스프레스 주문 페이지에서 "수집 시작" 클릭');
            document.getElementById('aliStartBtn').disabled = false;
        } else {
            setAliStatus('error', '연결 실패');
            aliLog(`오류: ${d.message}`, 'error');
            aliLog('Chrome을 --remote-debugging-port=9222 옵션으로 실행하세요', 'info');
        }
    } catch (e) {
        setAliStatus('error', '연결 실패');
        aliLog(`오류: ${e.message}`, 'error');
    }
}

async function startAliCollection() {
    const sheetUrl = document.getElementById('aliSheetUrl').value.trim();
    const month = document.getElementById('aliMonth').value;

    if (!sheetUrl) {
        aliLog('구글 시트 URL을 입력해주세요.', 'error');
        return;
    }

    aliRunning = true;
    document.getElementById('aliStartBtn').disabled = true;
    document.getElementById('aliStopBtn').disabled = false;
    setAliStatus('running', '수집 중...');

    aliLog(`${month} 수집 시작...`, 'info');

    try {
        const r = await fetch('/api/tools/ali/collect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sheet_url: sheetUrl, month: month })
        });
        const d = await r.json();

        if (d.success) {
            // SSE 스트림 시작
            startAliSSE();
        } else {
            aliLog(`오류: ${d.message}`, 'error');
            aliRunning = false;
            document.getElementById('aliStartBtn').disabled = false;
            document.getElementById('aliStopBtn').disabled = true;
            setAliStatus('connected', '오류');
        }
    } catch (e) {
        aliLog(`오류: ${e.message}`, 'error');
        aliRunning = false;
        document.getElementById('aliStartBtn').disabled = false;
        document.getElementById('aliStopBtn').disabled = true;
        setAliStatus('connected', '오류');
    }
}

// 알리 진행상황 SSE
let aliEventSource = null;
let aliPollErrorCount = 0;

function startAliSSE() {
    if (aliEventSource) {
        aliEventSource.close();
    }

    aliEventSource = new EventSource('/api/tools/ali/progress-stream');

    aliEventSource.onmessage = (event) => {
        try {
            const d = JSON.parse(event.data);
            updateAliUI(d);

            // 완료 확인 (running이 명시적으로 false일 때만)
            if (d.running === false) {
                console.log('[SSE] 수집 완료 감지');
                stopAliSSE();
                aliRunning = false;
                document.getElementById('aliStartBtn').disabled = false;
                document.getElementById('aliStopBtn').disabled = true;

                if (d.collected && d.collected.length > 0) {
                    document.getElementById('aliDownloadBtn').disabled = false;
                    setAliStatus('connected', `완료! ${d.collected.length}건 수집`);
                } else {
                    setAliStatus('connected', '완료 (수집 데이터 없음)');
                }
            }
        } catch (e) {
            console.error('SSE 데이터 파싱 오류:', e);
        }
    };

    aliEventSource.onerror = (error) => {
        console.error('알리 SSE 오류:', error);
        stopAliSSE();
        // 폴백으로 기존 폴링 사용
        pollAliProgressFallback();
    };
}

function updateAliUI(d) {
    // 로그 업데이트
    const logContent = document.getElementById('aliLogContent');
    if (d.logs && d.logs.length > 0) {
        logContent.innerHTML = d.logs.map(log => {
            const msg = typeof log === 'object' ? `[${log.time}] ${log.msg}` : log;
            const cls = typeof log === 'object' && log.status ? log.status : '';
            return `<div class="log-line ${cls}">${msg}</div>`;
        }).join('');
        logContent.scrollTop = logContent.scrollHeight;
    }

    // 수집된 건수 표시
    document.getElementById('aliCollectedCount').textContent = `수집: ${d.collected?.length || 0}건`;

    // 테이블 업데이트
    if (d.collected && d.collected.length > 0) {
        updateAliTable(d.collected);
    }

    // 진행상황 표시
    if (d.total > 0) {
        setAliStatus('running', `수집 중... ${d.progress || 0}/${d.total} 페이지`);
    } else if (d.running !== false) {
        setAliStatus('running', '수집 중...');
    }
}

function stopAliSSE() {
    if (aliEventSource) {
        aliEventSource.close();
        aliEventSource = null;
    }
}

// SSE 실패 시 폴백 폴링
async function pollAliProgressFallback() {
    if (!aliRunning) return;

    try {
        const r = await fetch('/api/tools/ali/progress');
        const d = await r.json();
        updateAliUI(d);

        if (d.running === false) {
            aliRunning = false;
            document.getElementById('aliStartBtn').disabled = false;
            document.getElementById('aliStopBtn').disabled = true;

            if (d.collected && d.collected.length > 0) {
                document.getElementById('aliDownloadBtn').disabled = false;
                setAliStatus('connected', `완료! ${d.collected.length}건 수집`);
            } else {
                setAliStatus('connected', '완료 (수집 데이터 없음)');
            }
            return;
        }

        aliPollErrorCount = 0;
        setTimeout(pollAliProgressFallback, 1000);
    } catch (e) {
        console.error('알리 폴링 오류:', e);
        aliPollErrorCount = (aliPollErrorCount || 0) + 1;

        if (aliPollErrorCount >= 5) {
            aliRunning = false;
            document.getElementById('aliStartBtn').disabled = false;
            document.getElementById('aliStopBtn').disabled = true;
            setAliStatus('error', '폴링 오류로 중단됨');
            return;
        }
        setTimeout(pollAliProgressFallback, 2000);
    }
}

function updateAliTable(collected) {
    const tbody = document.getElementById('aliTableBody');
    const tableDiv = document.getElementById('aliCollectedTable');

    if (collected.length > 0) {
        tableDiv.style.display = 'block';
        document.getElementById('aliTableCount').textContent = collected.length;

        tbody.innerHTML = collected.map(item => `
            <tr>
                <td>${item.customer_order || '-'}</td>
                <td>${item.ali_order || '-'}</td>
                <td>${item.carrier || '-'}</td>
                <td>${item.tracking_no || '-'}</td>
            </tr>
        `).join('');
    }
}

async function stopAliCollection() {
    stopAliSSE();  // SSE 연결 종료
    try {
        await fetch('/api/tools/ali/stop', { method: 'POST' });
        aliLog('수집 중단 요청됨', 'info');
    } catch (e) { }

    aliRunning = false;
    document.getElementById('aliStartBtn').disabled = false;
    document.getElementById('aliStopBtn').disabled = true;
    setAliStatus('connected', '중단됨');
}

function downloadAliExcel() {
    window.location.href = '/api/tools/ali/download';
}

// 알리 시트 URL 저장
function saveAliSheetUrl() {
    const url = document.getElementById('aliSheetUrl').value.trim();
    if (!url) {
        showToast('시트 URL을 입력하세요', 'error');
        return;
    }
    localStorage.setItem('aliSheetUrl', url);
    showToast('시트 URL 저장됨', 'success');
}

// 알리 시트 URL 불러오기
function loadAliSheetUrl() {
    const saved = localStorage.getItem('aliSheetUrl');
    if (saved) {
        document.getElementById('aliSheetUrl').value = saved;
    }
}

// 페이지 로드 시 저장된 값 불러오기
document.addEventListener('DOMContentLoaded', () => {
    // 알리 시트 URL 불러오기
    setTimeout(loadAliSheetUrl, 100);
});

// ========== 관제센터 기능 ==========
let monitorData = [];
let filteredData = [];
let selectedAccount = null;
let contextMenuTarget = null;

// 관제센터 데이터 로드
async function loadMonitorData() {
    console.log('[관제센터] loadMonitorData 시작');
    try {
        const r = await fetch('/api/monitor/accounts');
        const d = await r.json();
        monitorData = d.accounts || [];
        console.log('[관제센터] accounts 로드:', monitorData.length, '개');

        // 판매중 수량 및 마지막등록일 가져오기
        console.log('[관제센터] product-counts 호출 시작');
        try {
            const countsR = await fetch('/api/monitor/product-counts');
            console.log('[관제센터] product-counts 응답 상태:', countsR.status);
            const countsD = await countsR.json();
            console.log('[관제센터] product-counts 응답:', countsD);
            console.log('[관제센터] DEBUG:', countsD.debug);
            if (countsD.success && countsD.data) {
                // 스토어명만 추출하는 맵 (플랫폼별)
                const storeMapByPlatform = {};
                Object.keys(countsD.data).forEach(k => {
                    const parts = k.split('_');
                    if (parts.length >= 2) {
                        const platform = parts[parts.length - 1];
                        const store = parts.slice(0, -1).join('_').trim();
                        if (!storeMapByPlatform[platform]) storeMapByPlatform[platform] = {};
                        storeMapByPlatform[platform][store] = countsD.data[k];
                    }
                });

                let matchCount = 0, missCount = 0;
                const debuggedPlatforms = new Set();
                monitorData.forEach(acc => {
                    const storeName = get스토어명(acc).trim();
                    const platform = get플랫폼(acc);

                    // 플랫폼별 맵에서 찾기
                    const platformMap = storeMapByPlatform[platform] || {};
                    const countInfo = platformMap[storeName];

                    // 모음상사 디버그
                    if (storeName === "모음상사") {
                        console.log(`[DEBUG 모음상사] platform="${platform}", countInfo=`, countInfo);
                        console.log(`[DEBUG 모음상사] storeMapByPlatform keys:`, Object.keys(storeMapByPlatform));
                        console.log(`[DEBUG 모음상사] 스마트스토어 map:`, storeMapByPlatform["스마트스토어"]);
                        console.log(`[DEBUG 모음상사] 11번가 map:`, storeMapByPlatform["11번가"]);
                    }

                    if (countInfo) matchCount++;
                    else missCount++;

                    // 플랫폼별 첫 번째만 로그
                    if (!debuggedPlatforms.has(platform)) {
                        console.log(`[관제센터] 매칭 (${platform}): store="${storeName}", found=${!!countInfo}, last_reg="${countInfo?.last_reg || ''}"`, countInfo);
                        debuggedPlatforms.add(platform);
                    }

                    if (countInfo && typeof countInfo === 'object') {
                        acc.product_count = countInfo.count || 0;
                        acc.last_cleanup_date = countInfo.last_reg || '';
                        // 경과일 계산
                        if (countInfo.last_reg) {
                            const lastDate = new Date(countInfo.last_reg);
                            const today = new Date();
                            const diffTime = today - lastDate;
                            const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
                            acc.days_since_cleanup = diffDays >= 0 ? diffDays : 0;
                        } else {
                            acc.days_since_cleanup = 0;
                        }
                    } else {
                        acc.product_count = countInfo || 0;
                        acc.days_since_cleanup = 0;
                    }
                });
                console.log(`[관제센터] 키 매칭 결과: 성공=${matchCount}, 실패=${missCount}`);
                // 첫 5개 계정의 경과일 확인
                monitorData.slice(0, 5).forEach((acc, i) => {
                    console.log(`[관제센터] 계정${i}: ${get스토어명(acc)}, last_cleanup_date=${acc.last_cleanup_date}, days_since_cleanup=${acc.days_since_cleanup}`);
                });
            }
        } catch (e) {
            console.warn('[관제센터] 판매중 수량 로드 실패:', e);
        }

        // 매출 데이터 가져오기
        try {
            const salesR = await fetch('/api/sales/from-sheet');
            const salesD = await salesR.json();
            if (salesD.success && salesD.data) {
                monitorData.forEach(acc => {
                    const storeName = get스토어명(acc);
                    const platform = get플랫폼(acc);
                    const key = `${storeName}(${platform})`;
                    const sales = salesD.data[key];
                    if (sales) {
                        acc.today_sales = sales.today_sales || 0;
                        acc.today_orders = sales.today_orders || 0;
                        acc.month_sales = sales.month_sales || 0;
                        acc.month_orders = sales.month_orders || 0;
                    }
                });
            }
        } catch (e) {
            console.warn('[관제센터] 매출 데이터 로드 실패:', e);
        }

        // 명의자 필터 동적 생성
        buildOwnerFilter();

        // 필터 적용 및 렌더링
        applyMonitorFilters();
    } catch (e) {
        console.error('관제센터 로드 오류:', e);
        showToast('데이터 로드 실패', 'error');
    }
}

// 명의자 필터 동적 생성
function buildOwnerFilter() {
    const container = document.getElementById('filter-owner');
    if (!container) return;  // DOM 요소가 없으면 스킵

    const owners = [...new Set(monitorData.map(a => a.owner || '미지정'))].sort();
    container.innerHTML = owners.map(owner => `
        <label class="filter-item">
            <input type="checkbox" value="${owner}" checked onchange="applyMonitorFilters()">
            <span>${owner}</span>
            <span class="filter-count" id="count-owner-${owner}">0</span>
        </label>
    `).join('');
}

// 필터 그룹 토글
function toggleFilterGroup(group) {
    const items = document.getElementById('filter-' + group);
    const icon = document.getElementById('toggle-' + group);

    items.classList.toggle('collapsed');
    icon.classList.toggle('collapsed');
}

// 필터 초기화
function resetMonitorFilters() {
    document.querySelectorAll('.filter-items input[type="checkbox"]').forEach(cb => {
        cb.checked = true;
    });
    document.getElementById('monitorSearch').value = '';
    applyMonitorFilters();
}

// 필터 적용
function applyMonitorFilters() {
    const searchText = (document.getElementById('monitorSearch')?.value || '').toLowerCase();

    // 체크된 필터값 수집
    const filters = {
        platform: getCheckedValues('filter-platform'),
        optype: getCheckedValues('filter-optype'),
        owner: getCheckedValues('filter-owner'),
        status: getCheckedValues('filter-status')
    };

    console.log('[관제센터] 필터값:', filters);
    console.log('[관제센터] monitorData 길이:', monitorData.length);

    // 필터링 (빈 필터는 전체 허용)
    filteredData = monitorData.filter(acc => {
        // 플랫폼 필터
        const platform = get플랫폼(acc);
        if (filters.platform.length > 0 && !filters.platform.includes(platform)) return false;

        // 운영타입 필터
        const optype = acc.optype || '대량';
        if (filters.optype.length > 0 && !filters.optype.includes(optype)) return false;

        // 명의자 필터
        const owner = get소유자(acc) || '미지정';
        if (filters.owner.length > 0 && !filters.owner.includes(owner)) return false;

        // 상태 필터 (데이터: green/yellow/red/black ↔ 필터: normal/caution/warning/suspended/stopped)
        const status = acc.monitor_status || 'green';
        const statusMap = { 'green': 'normal', 'yellow': 'caution', 'orange': 'warning', 'red': 'stopped', 'black': 'stopped', 'purple': 'suspended' };
        const mappedStatus = statusMap[status] || status;
        if (filters.status.length > 0 && !filters.status.includes(mappedStatus)) return false;

        // 검색 필터
        if (searchText) {
            const shopName = get스토어명(acc).toLowerCase();
            const loginId = get아이디(acc).toLowerCase();
            if (!shopName.includes(searchText) && !loginId.includes(searchText)) return false;
        }

        return true;
    });

    // 가나다순 정렬
    filteredData.sort((a, b) => {
        const nameA = get스토어명(a).toLowerCase();
        const nameB = get스토어명(b).toLowerCase();
        return nameA.localeCompare(nameB, 'ko');
    });

    console.log('[관제센터] 정렬 후 처음 5개:', filteredData.slice(0, 5).map(a => a.스토어명 || a.login_id));

    // 카운트 업데이트
    updateFilterCounts();

    // 통계 업데이트
    updateMonitorStats();

    // 그리드 렌더링
    renderMonitorGrid();
}

function getCheckedValues(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return [];
    return [...container.querySelectorAll('input:checked')].map(cb => cb.value);
}

// 필터 카운트 업데이트
function updateFilterCounts() {
    // 플랫폼별 카운트
    const platformCounts = {};
    const optypeCounts = {};
    const ownerCounts = {};
    const statusCounts = { green: 0, yellow: 0, red: 0, black: 0 };

    monitorData.forEach(acc => {
        const platform = get플랫폼(acc);
        platformCounts[platform] = (platformCounts[platform] || 0) + 1;

        const optype = acc.optype || '대량';
        optypeCounts[optype] = (optypeCounts[optype] || 0) + 1;

        const owner = get소유자(acc) || '미지정';
        ownerCounts[owner] = (ownerCounts[owner] || 0) + 1;

        const status = acc.monitor_status || 'green';
        statusCounts[status] = (statusCounts[status] || 0) + 1;
    });

    // DOM 업데이트
    Object.keys(platformCounts).forEach(p => {
        const el = document.getElementById('count-' + p);
        if (el) el.textContent = platformCounts[p];
    });

    Object.keys(optypeCounts).forEach(o => {
        const el = document.getElementById('count-' + o);
        if (el) el.textContent = optypeCounts[o];
    });

    Object.keys(statusCounts).forEach(s => {
        const el = document.getElementById('count-' + s);
        if (el) el.textContent = statusCounts[s];
    });
}

// 통계 업데이트
function updateMonitorStats() {
    const statTotal = document.getElementById('statTotal');
    if (!statTotal) return;  // DOM 요소가 없으면 스킵

    const counts = { green: 0, yellow: 0, red: 0, black: 0 };
    filteredData.forEach(acc => {
        const status = acc.monitor_status || 'green';
        counts[status]++;
    });

    statTotal.textContent = filteredData.length;
    const statGreen = document.getElementById('statGreen');
    const statYellow = document.getElementById('statYellow');
    const statRed = document.getElementById('statRed');
    const statBlack = document.getElementById('statBlack');
    const accountTotal = document.getElementById('accountTotal');
    if (statGreen) statGreen.textContent = counts.green;
    if (statYellow) statYellow.textContent = counts.yellow;
    if (statRed) statRed.textContent = counts.red;
    if (statBlack) statBlack.textContent = counts.black;
    if (accountTotal) accountTotal.textContent = `${filteredData.length}개`;
}

// 그리드 렌더링
function renderMonitorGrid() {
    const grid = document.getElementById('dailyGrid');
    if (!grid) return;  // DOM 요소가 없으면 스킵

    if (filteredData.length === 0) {
        grid.innerHTML = '<div class="empty-state">조건에 맞는 계정이 없습니다</div>';
        return;
    }

    grid.innerHTML = filteredData.map(acc => {
        const status = acc.monitor_status || 'green';
        const warnings = acc.warning_count || 0;
        const owner = get소유자(acc);
        const platform = get플랫폼(acc);
        const loginId = get아이디(acc);
        const storeName = get스토어명(acc);

        return `
            <div class="monitor-card status-${status}" 
                 data-platform="${platform}" 
                 data-id="${loginId}"
                 onclick="toggleMonitorCard(this)"
                 onmouseenter="showTooltip(event, '${platform}', '${loginId}')"
                 onmouseleave="hideTooltip()"
                 ondblclick="event.stopPropagation(); doAutoLoginMonitor('${platform}', '${loginId}')"
                 oncontextmenu="showContextMenu(event, '${platform}', '${loginId}')">
                <div class="platform-tag ${platform}">${platform.substring(0, 2)}</div>
                <div class="shop-name">${storeName}</div>
                <div class="shop-id">${loginId}</div>
                ${owner ? `<div class="owner-tag">${owner}</div>` : ''}
                ${warnings > 0 ? `<div class="warning-badge">${warnings}</div>` : ''}
                <div class="expand-info">
                    <div class="expand-row">💰 ₩${(acc.today_sales || 0).toLocaleString()} (${acc.today_orders || 0}건)</div>
                    <div class="expand-row">📊 ₩${(acc.month_sales || 0).toLocaleString()} (${acc.month_orders || 0}건)</div>
                    <div class="expand-row cleanup-row ${acc.cleanup_status || 'normal'}">📅 ${acc.last_cleanup_date || '-'} (${acc.days_since_cleanup || 0}일전)</div>
                </div>
            </div>
        `;
    }).join('');
}

// 관제센터 카드 펼치기/접기
let monitorClickTimer = null;
function toggleMonitorCard(card) {
    // 더블클릭 구분 (250ms)
    if (monitorClickTimer) {
        clearTimeout(monitorClickTimer);
        monitorClickTimer = null;
        return;
    }

    monitorClickTimer = setTimeout(() => {
        monitorClickTimer = null;
        card.classList.toggle('expanded');
        // width는 CSS에서 140px로 고정, 클래스만 토글
    }, 200);
}

// 전체 펼치기/접기 토글 (버튼 전용 - 개별 펼침 상태와 무관하게 전체 제어)
let isAllExpanded = false;  // 전체 펼침 상태 추적

function toggleExpandAll() {
    const monitorGrid = document.getElementById('monitorGrid');
    const dailyGrid = document.getElementById('dailyGrid');
    const btn = document.getElementById('expandAllBtn');

    // 버튼 상태만으로 토글 (개별 카드 상태 무시)
    isAllExpanded = !isAllExpanded;

    if (!isAllExpanded) {
        // 접기 - 모든 카드 접기
        if (monitorGrid) monitorGrid.classList.remove('expanded-view');
        if (dailyGrid) dailyGrid.classList.remove('expanded-view');
        if (btn) {
            btn.textContent = '📂 펼치기';
            btn.classList.remove('active');
        }
        // 개별 펼친 카드도 모두 접기
        document.querySelectorAll('.monitor-card.expanded, .market-card.expanded').forEach(card => {
            card.classList.remove('expanded');
        });
    } else {
        // 펼치기 - 모든 카드 펼치기
        if (monitorGrid) monitorGrid.classList.add('expanded-view');
        if (dailyGrid) dailyGrid.classList.add('expanded-view');
        if (btn) {
            btn.textContent = '📁 접기';
            btn.classList.add('active');
        }
        document.querySelectorAll('.monitor-card, .market-card').forEach(card => {
            card.classList.add('expanded');
        });
    }
}

// 더블클릭 - 자동 로그인 (서버 API 사용)
async function doAutoLoginMonitor(platform, loginId) {
    const acc = monitorData.find(a => a.platform === platform && a.login_id === loginId);
    if (!acc) {
        showToast('계정을 찾을 수 없습니다', 'error');
        return;
    }

    showToast(`${acc.스토어명 || loginId} 자동 로그인 시작...`, 'info');

    // 서버 자동 로그인 API 호출
    try {
        const r = await fetch('/api/auto-login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                platform: platform,
                login_id: loginId
            })
        });
        const d = await r.json();

        if (d.success || d.pending) {
            showToast('자동 로그인 요청 완료 - 클라이언트에서 처리 중', 'success');
        } else {
            showToast('자동 로그인 실패: ' + (d.message || ''), 'error');
        }
    } catch (e) {
        console.error('자동 로그인 실패:', e);
        showToast('자동 로그인 실패', 'error');
    }
}

// 툴팁 표시 (호버)
function showTooltip(event, platform, loginId) {
    const acc = monitorData.find(a => a.platform === platform && a.login_id === loginId);
    if (!acc) return;

    const tooltip = document.getElementById('accountTooltip');

    document.getElementById('tooltipPlatform').textContent = platform;
    document.getElementById('tooltipName').textContent = acc.스토어명 || loginId;
    document.getElementById('tooltipProducts').textContent = acc.product_count?.toLocaleString() || '-';
    document.getElementById('tooltipSales').textContent = acc.total_sales ? `₩${acc.total_sales.toLocaleString()}` : '-';
    document.getElementById('tooltipOrders').textContent = acc.order_count?.toLocaleString() || '-';
    document.getElementById('tooltipWarnings').textContent = acc.warning_count || '0';
    document.getElementById('tooltipMemo').textContent = acc.memo || '-';

    // 위치 계산
    const rect = event.target.getBoundingClientRect();
    let left = rect.right + 10;
    let top = rect.top;

    // 화면 밖으로 나가면 왼쪽에 표시
    if (left + 220 > window.innerWidth) {
        left = rect.left - 230;
    }

    tooltip.style.left = left + 'px';
    tooltip.style.top = top + 'px';
    tooltip.style.display = 'block';
}

function hideTooltip() {
    document.getElementById('accountTooltip').style.display = 'none';
}

// 컨텍스트 메뉴 (우클릭) - 올인원 메뉴
function showContextMenu(event, platform, loginId) {
    event.preventDefault();
    event.stopPropagation();

    contextMenuTarget = { platform, loginId };

    const acc = monitorData.find(a => a.platform === platform && a.login_id === loginId);
    const shopName = acc?.스토어명 || loginId;

    // 플랫폼별 올인원 메뉴 구성
    let menuItems = '';

    if (platform === '스마트스토어') {
        menuItems = `
            <div class="ctx-menu-header">${shopName}</div>
            <div class="ctx-menu-section">올인원 작업</div>
            <div class="ctx-menu-item" onclick="runSingleAioTask('${platform}', '${loginId}', '중복삭제')">🗑️ 중복삭제</div>
            <div class="ctx-menu-item" onclick="runSingleAioTask('${platform}', '${loginId}', '상품최적화')">✨ 상품최적화</div>
            <div class="ctx-menu-divider"></div>
            <div class="ctx-menu-section">바로가기</div>
            <div class="ctx-menu-item" onclick="doAutoLoginMonitor('${platform}', '${loginId}')">🔐 자동로그인</div>
            <div class="ctx-menu-item" onclick="openAccountDetail('${platform}', '${loginId}')">📋 계정상세</div>
            <div class="ctx-menu-item" onclick="copyAccountId('${loginId}')">📄 ID복사</div>
        `;
    } else if (platform === '11번가') {
        menuItems = `
            <div class="ctx-menu-header">${shopName}</div>
            <div class="ctx-menu-section">올인원 작업</div>
            <div class="ctx-menu-item" onclick="runSingleAioTask('${platform}', '${loginId}', '판매중지')">⏹️ 판매중지</div>
            <div class="ctx-menu-item" onclick="runSingleAioTask('${platform}', '${loginId}', '판매재개')">▶️ 판매재개</div>
            <div class="ctx-menu-item" onclick="runSingleAioTask('${platform}', '${loginId}', '상품삭제')">🗑️ 상품삭제</div>
            <div class="ctx-menu-divider"></div>
            <div class="ctx-menu-section">바로가기</div>
            <div class="ctx-menu-item" onclick="doAutoLoginMonitor('${platform}', '${loginId}')">🔐 자동로그인</div>
            <div class="ctx-menu-item" onclick="openAccountDetail('${platform}', '${loginId}')">📋 계정상세</div>
            <div class="ctx-menu-item" onclick="copyAccountId('${loginId}')">📄 ID복사</div>
        `;
    } else if (platform === '쿠팡') {
        menuItems = `
            <div class="ctx-menu-header">${shopName}</div>
            <div class="ctx-menu-section">올인원 작업</div>
            <div class="ctx-menu-item" onclick="runSingleAioTask('${platform}', '${loginId}', '가격반영')">💰 가격반영</div>
            <div class="ctx-menu-divider"></div>
            <div class="ctx-menu-section">바로가기</div>
            <div class="ctx-menu-item" onclick="doAutoLoginMonitor('${platform}', '${loginId}')">🔐 자동로그인</div>
            <div class="ctx-menu-item" onclick="openAccountDetail('${platform}', '${loginId}')">📋 계정상세</div>
            <div class="ctx-menu-item" onclick="copyAccountId('${loginId}')">📄 ID복사</div>
        `;
    } else {
        // 기타 플랫폼 (ESM, 지마켓, 옥션)
        menuItems = `
            <div class="ctx-menu-header">${shopName}</div>
            <div class="ctx-menu-section">바로가기</div>
            <div class="ctx-menu-item" onclick="doAutoLoginMonitor('${platform}', '${loginId}')">🔐 자동로그인</div>
            <div class="ctx-menu-item" onclick="openAccountDetail('${platform}', '${loginId}')">📋 계정상세</div>
            <div class="ctx-menu-item" onclick="copyAccountId('${loginId}')">📄 ID복사</div>
        `;
    }

    const menu = document.getElementById('contextMenu');
    menu.innerHTML = menuItems;
    menu.style.left = event.clientX + 'px';
    menu.style.top = event.clientY + 'px';
    menu.style.display = 'block';

    // 메뉴 외부 클릭시 닫기
    setTimeout(() => {
        document.addEventListener('click', closeContextMenu, { once: true });
    }, 10);
}

// ID 복사
function copyAccountId(loginId) {
    closeContextMenu();
    navigator.clipboard.writeText(loginId);
    showToast('ID 복사됨', 'success');
}

// 개별 올인원 작업 실행
async function runSingleAioTask(platform, loginId, task) {
    closeContextMenu();

    const acc = monitorData.find(a => a.platform === platform && a.login_id === loginId);
    const shopName = acc?.스토어명 || loginId;

    showToast(`${shopName} - ${task} 실행 중...`, 'info');

    try {
        const r = await fetch('/api/allinone/run-single', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                platform: platform,
                login_id: loginId,
                task: task
            })
        });

        const d = await r.json();
        if (d.success) {
            showToast(`${shopName} - ${task} 시작됨`, 'success');
        } else {
            showToast(d.message || '실행 실패', 'error');
        }
    } catch (e) {
        showToast('작업 실행 실패', 'error');
    }
}

function closeContextMenu() {
    document.getElementById('contextMenu').style.display = 'none';
}

// 컨텍스트 메뉴 액션
function contextMenuAction(action) {
    closeContextMenu();

    if (!contextMenuTarget) return;

    const { platform, loginId } = contextMenuTarget;
    const acc = monitorData.find(a => a.platform === platform && a.login_id === loginId);

    switch (action) {
        case 'login':
            // 로그인 실행
            doAutoLogin(platform, loginId);
            break;
        case 'allinone':
            // All-in-One 탭으로 이동 + 계정 선택
            document.querySelector('.tab[data-tab="allinone"]').click();
            setTimeout(() => {
                selectAioPlatform(platform);
                // 계정 체크박스 선택
                const checkbox = document.querySelector(`#aioStoreList input[value="${loginId}"]`);
                if (checkbox) checkbox.checked = true;
            }, 100);
            break;
        case 'detail':
            openAccountDetail(platform, loginId);
            break;
        case 'status':
            openAccountDetail(platform, loginId);
            break;
        case 'copy':
            navigator.clipboard.writeText(loginId);
            showToast('ID 복사됨', 'success');
            break;
    }
}

// 계정 상세 모달
function openAccountDetail(platform, loginId) {
    const acc = monitorData.find(a => a.platform === platform && a.login_id === loginId);
    if (!acc) return;

    selectedAccount = acc;

    document.getElementById('detailModalTitle').textContent = `📋 ${acc.스토어명 || loginId}`;
    document.getElementById('detailPlatform').textContent = platform;
    document.getElementById('detailShop').textContent = acc.스토어명 || '-';
    document.getElementById('detailId').textContent = loginId;
    document.getElementById('detailOwner').textContent = acc.owner || '-';
    document.getElementById('detailOptype').textContent = acc.optype || '-';

    document.getElementById('detailProducts').textContent = acc.product_count?.toLocaleString() || '0';
    document.getElementById('detailSales').textContent = acc.total_sales?.toLocaleString() || '0';
    document.getElementById('detailOrders').textContent = acc.order_count?.toLocaleString() || '0';
    document.getElementById('detailWarnings').textContent = acc.warning_count || '0';

    document.getElementById('detailMemo').value = acc.memo || '';

    // 상태 버튼 활성화
    const currentStatus = acc.monitor_status || 'green';
    document.querySelectorAll('#accountDetailModal .status-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.textContent.includes(getStatusEmoji(currentStatus))) {
            btn.classList.add('active');
        }
    });

    document.getElementById('accountDetailModal').style.display = 'flex';
}

function getStatusEmoji(status) {
    const map = { green: '🟢', yellow: '🟡', red: '🔴', black: '⚫' };
    return map[status] || '🟢';
}

function closeAccountDetailModal() {
    document.getElementById('accountDetailModal').style.display = 'none';
    selectedAccount = null;
}

// 상태 설정
function setAccountStatus(status) {
    document.querySelectorAll('#accountDetailModal .status-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    event.target.classList.add('active');
}

// 계정 상세 저장
async function saveAccountDetail() {
    if (!selectedAccount) return;

    const activeBtn = document.querySelector('#accountDetailModal .status-btn.active');
    let status = 'green';
    if (activeBtn) {
        if (activeBtn.textContent.includes('🟢')) status = 'green';
        else if (activeBtn.textContent.includes('🟡')) status = 'yellow';
        else if (activeBtn.textContent.includes('🔴')) status = 'red';
        else if (activeBtn.textContent.includes('⚫')) status = 'black';
    }

    const memo = document.getElementById('detailMemo').value;

    try {
        const r = await fetch('/api/monitor/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                platform: selectedAccount.platform,
                login_id: selectedAccount.login_id,
                monitor_status: status,
                warning_count: selectedAccount.warning_count || 0,
                memo
            })
        });
        const d = await r.json();

        if (d.success) {
            showToast('저장 완료', 'success');
            closeAccountDetailModal();
            loadMonitorData();
        } else {
            showToast(d.message || '저장 실패', 'error');
        }
    } catch (e) {
        showToast('저장 오류', 'error');
    }
}

// 자동 로그인
async function doAutoLogin(platform, loginId) {
    showToast('로그인 준비 중...', 'info');

    const acc = monitorData.find(a => a.platform === platform && a.login_id === loginId);
    if (!acc) {
        showToast('계정 정보를 찾을 수 없습니다', 'error');
        return;
    }

    // 플랫폼별 로그인 URL
    const loginUrls = {
        '스마트스토어': 'https://account.commerce.naver.com/login',
        '쿠팡': 'https://wing.coupang.com/login',
        '11번가': 'https://login.11st.co.kr/auth/front/login.tmall',
        '지마켓': 'https://minishop.gmarket.co.kr/Login',
        '옥션': 'https://minishop.auction.co.kr/Login'
    };

    const url = loginUrls[platform];
    if (url) {
        window.open(url, '_blank');
    }

    // ID/PW 복사
    if (acc.login_id) {
        await navigator.clipboard.writeText(acc.login_id);
        showToast(`ID 복사됨: ${acc.login_id}`, 'success');
    }
}

// ========== 설정 기능 ==========
function loadStatusSettings() {
    const settings = JSON.parse(localStorage.getItem('statusSettings') || '{}');
    if (settings.green) document.getElementById('settingGreen').value = settings.green;
    if (settings.yellow) document.getElementById('settingYellow').value = settings.yellow;
    if (settings.red) document.getElementById('settingRed').value = settings.red;
    if (settings.black) document.getElementById('settingBlack').value = settings.black;
}

// 탭 권한 설정 저장
function saveTabPermissions() {
    const permissions = {
        sms: document.getElementById('tabPerm_sms').checked,
        monitor: document.getElementById('tabPerm_monitor').checked,
        market: document.getElementById('tabPerm_market').checked,
        sales: document.getElementById('tabPerm_sales').checked,
        accounts: document.getElementById('tabPerm_accounts').checked,
        marketing: document.getElementById('tabPerm_marketing').checked,
        aio: document.getElementById('tabPerm_aio').checked,
        scheduler: document.getElementById('tabPerm_scheduler').checked,
        bulsaja: document.getElementById('tabPerm_bulsaja').checked,
        tools: document.getElementById('tabPerm_tools').checked,
        calendar: document.getElementById('tabPerm_calendar').checked
    };

    fetch('/api/settings/tab-permissions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(permissions)
    })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                showToast('탭 권한 설정이 저장되었습니다', 'success');
            } else {
                showToast('저장 실패: ' + (data.message || '알 수 없는 오류'), 'error');
            }
        })
        .catch(err => {
            console.error('탭 권한 저장 오류:', err);
            showToast('저장 중 오류가 발생했습니다', 'error');
        });
}

// 탭 권한 설정 로드
function loadTabPermissions() {
    fetch('/api/settings/tab-permissions')
        .then(r => r.json())
        .then(data => {
            if (data.permissions) {
                const p = data.permissions;
                if (document.getElementById('tabPerm_sms')) document.getElementById('tabPerm_sms').checked = p.sms !== false;
                if (document.getElementById('tabPerm_monitor')) document.getElementById('tabPerm_monitor').checked = p.monitor !== false;
                if (document.getElementById('tabPerm_market')) document.getElementById('tabPerm_market').checked = p.market !== false;
                if (document.getElementById('tabPerm_sales')) document.getElementById('tabPerm_sales').checked = p.sales !== false;
                if (document.getElementById('tabPerm_accounts')) document.getElementById('tabPerm_accounts').checked = p.accounts !== false;
                if (document.getElementById('tabPerm_marketing')) document.getElementById('tabPerm_marketing').checked = p.marketing !== false;
                if (document.getElementById('tabPerm_aio')) document.getElementById('tabPerm_aio').checked = p.aio !== false;
                if (document.getElementById('tabPerm_scheduler')) document.getElementById('tabPerm_scheduler').checked = p.scheduler !== false;
                if (document.getElementById('tabPerm_bulsaja')) document.getElementById('tabPerm_bulsaja').checked = p.bulsaja !== false;
                if (document.getElementById('tabPerm_tools')) document.getElementById('tabPerm_tools').checked = p.tools !== false;
                if (document.getElementById('tabPerm_calendar')) document.getElementById('tabPerm_calendar').checked = p.calendar !== false;
            }
        })
        .catch(err => console.error('탭 권한 로드 오류:', err));
}

// ========== 다운로드 기능 ==========
// 다운로드 정보 로드
async function loadDownloadInfo() {
    try {
        const resp = await fetch('/api/downloads/info');
        const info = await resp.json();

        // 클라이언트 정보
        const clientEl = document.getElementById('clientInfo');
        if (clientEl) {
            if (info.client?.available) {
                const size = (info.client.size / 1024 / 1024).toFixed(1);
                clientEl.innerHTML = `✅ 사용 가능<br>크기: ${size} MB | 수정일: ${info.client.modified}`;
            } else {
                clientEl.innerHTML = '❌ 파일 없음 (빌드 필요)';
            }
        }

        // 익스텐션 정보
        const extEl = document.getElementById('extensionInfo');
        if (extEl) {
            if (info.extension?.available) {
                extEl.innerHTML = `✅ 사용 가능<br>버전: ${info.extension.version || '1.0'}`;
            } else {
                extEl.innerHTML = '❌ 폴더 없음';
            }
        }
    } catch (e) {
        console.error('다운로드 정보 로드 오류:', e);
    }
}

// 클라이언트 다운로드
function downloadClient() {
    window.location.href = '/api/downloads/client';
}

// 익스텐션 다운로드
function downloadExtension() {
    window.location.href = '/api/downloads/extension';
}

// 탭 전환 시 관제센터 데이터 로드
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            if (tab.dataset.tab === 'monitor') {
                // 통합 관제센터 데이터만 로드 (경과일/매출 포함)
                loadDailyStatus();
            } else if (tab.dataset.tab === 'settings') {
                loadTabPermissions();
                loadDownloadInfo();
            }
        });
    });
});

// ========== 일일장부 관제센터 기능 ==========
let dailyData = [];
let dailyMarkets = [];
let dailyUsages = [];
let dailyFiltered = [];
let dailyContextTarget = null;
let dailyStatusTarget = null;
let dailyDataLoaded = false;  // 캐시 플래그
let salesTierEnabled = false;  // 매출 계급 필터 활성화 상태
let orderTierEnabled = false;  // 주문 계급 필터 활성화 상태

// 일일장부 데이터 로드
async function loadDailyStatus(forceReload = false) {
    // 이미 로드된 데이터 있으면 렌더링만
    if (dailyDataLoaded && !forceReload && dailyData.length > 0) {
        applyDailyFilters();
        return;
    }

    const grid = document.getElementById('dailyGrid');
    grid.innerHTML = '<div class="empty-state">데이터를 불러오는 중...</div>';

    // 현재 필터 상태 저장
    const savedFilters = saveCurrentFilters();

    try {
        const r = await fetch(`/api/monitor/daily-status${forceReload ? '?refresh=true' : ''}`);
        console.log('[디버깅] API 응답 상태:', r.status, r.statusText);

        const d = await r.json();
        console.log('[디버깅] API 응답 데이터:', d);
        console.log('[디버깅] success:', d.success);
        console.log('[디버깅] data length:', d.data?.length);

        if (!d.success) {
            console.error('[디버깅] API 실패:', d.message);
            grid.innerHTML = `<div class="empty-state">⚠️ ${d.message || '로드 실패'}</div>`;
            return;
        }

        dailyData = d.data || [];
        dailyMarkets = d.markets || [];
        dailyUsages = d.usages || [];

        // 매출 데이터 병합
        try {
            const salesR = await fetch('/api/sales/from-sheet');
            const salesD = await salesR.json();
            if (salesD.success && salesD.data) {
                dailyData.forEach(item => {
                    const storeName = item.account;
                    const key = `${storeName}(${item.platform || item.market})`;
                    const sales = salesD.data[key];
                    if (sales) {
                        item.today_sales = sales.today_sales || 0;
                        item.today_orders = sales.today_orders || 0;
                        item.month_sales = sales.month_sales || 0;
                        item.month_orders = sales.month_orders || 0;
                        item.orders_2w = sales.orders_2w || 0;
                    }
                });
            }
        } catch (e) {
            console.warn('[관제센터] 매출 데이터 로드 실패:', e);
        }

        // 필터 UI 생성
        buildMarketFilter();
        buildUsageFilter();
        buildAccountFilter();

        // 계급 필터 초기화
        initTierFilters();

        // 저장된 필터 상태 복원
        restoreFilters(savedFilters);

        // 필터 적용 및 렌더링
        applyDailyFilters();

        // 캐시 플래그 설정
        dailyDataLoaded = true;

    } catch (e) {
        console.error('[디버깅] 일일장부 로드 오류:', e);
        console.error('[디버깅] 에러 스택:', e.stack);
        grid.innerHTML = `<div class="empty-state">⚠️ 데이터 로드 실패<br><small>${e.message}</small></div>`;
    }
}

// 현재 필터 상태 저장
function saveCurrentFilters() {
    return {
        marketFilters: [...selectedMarketFilters],
        statuses: getCheckedValues('filter-status'),
        usages: getCheckedValues('filter-usage'),
        owners: getCheckedValues('filter-accounts'),
        search: document.getElementById('dailySearch')?.value || ''
    };
}

// 필터 상태 복원
function restoreFilters(saved) {
    if (!saved) return;

    // 상단 마켓 필터 바 복원
    if (saved.marketFilters?.length) {
        selectedMarketFilters = new Set(saved.marketFilters);
        document.querySelectorAll('.market-filter-btn').forEach(btn => {
            btn.classList.toggle('active', selectedMarketFilters.has(btn.dataset.market));
        });
    }

    // 상태 필터 체크박스 복원
    if (saved.statuses?.length) {
        restoreCheckboxes('filter-status', saved.statuses);
    }

    // 용도 필터 복원
    if (saved.usages?.length) {
        restoreCheckboxes('filter-usage', saved.usages);
    }

    // 소유자 필터 복원
    if (saved.owners?.length) {
        restoreCheckboxes('filter-accounts', saved.owners);
    }

    // 검색어 복원
    if (saved.search) {
        const searchInput = document.getElementById('dailySearch');
        if (searchInput) searchInput.value = saved.search;
    }
}

// 체크박스 상태 복원
function restoreCheckboxes(containerId, checkedValues) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        cb.checked = checkedValues.includes(cb.value);
    });
}

// 마켓 필터 생성 (상단 바만 사용)
function buildMarketFilter() {
    // 상단 마켓 필터 바 생성
    buildMarketFilterBar();
}

// 상단 마켓 필터 바 생성
function buildMarketFilterBar() {
    const bar = document.getElementById('marketFilterBar');
    if (!bar) return;

    const marketColors = {
        '전체': '#667eea',
        '스마트스토어': '#03C75A',
        '쿠팡': '#00B4D8',
        '11번가': '#E31837',
        '지마켓': '#1A73E8',
        '옥션': '#9C27B0'
    };

    const markets = ['전체', ...dailyMarkets];

    bar.innerHTML = markets.map(market => {
        const color = marketColors[market] || '#667eea';
        const isActive = selectedMarketFilters.has(market) ? 'active' : '';
        return `
            <button class="market-filter-btn ${isActive}"
                    data-market="${market}"
                    style="--btn-color: ${color}"
                    onclick="filterByMarket('${market}', event)">
                ${market} <span class="market-count" id="count-bar-${market}">0</span>
            </button>
        `;
    }).join('');
}

// 마켓별 필터링 (Ctrl+클릭으로 복수 선택)
let selectedMarketFilters = new Set(['전체']);

function filterByMarket(market, event) {
    const isCtrlKey = event && (event.ctrlKey || event.metaKey);

    if (market === '전체') {
        // '전체' 클릭 시 - 모든 선택 해제하고 전체만 선택
        selectedMarketFilters.clear();
        selectedMarketFilters.add('전체');
    } else if (isCtrlKey) {
        // Ctrl+클릭: 복수 선택 모드
        selectedMarketFilters.delete('전체');
        if (selectedMarketFilters.has(market)) {
            selectedMarketFilters.delete(market);
            if (selectedMarketFilters.size === 0) {
                selectedMarketFilters.add('전체');
            }
        } else {
            selectedMarketFilters.add(market);
        }
    } else {
        // 일반 클릭: 단일 선택
        selectedMarketFilters.clear();
        selectedMarketFilters.add(market);
    }

    // 버튼 활성화 상태 업데이트
    document.querySelectorAll('.market-filter-btn').forEach(btn => {
        btn.classList.toggle('active', selectedMarketFilters.has(btn.dataset.market));
    });

    // 기존 selectedMarketFilter 호환성 유지
    selectedMarketFilter = selectedMarketFilters.has('전체') ? '전체' : [...selectedMarketFilters][0];

    applyDailyFilters();
}

// 용도 필터 생성
function buildUsageFilter() {
    const container = document.getElementById('filter-usage-list');
    if (!container) return;

    container.innerHTML = dailyUsages.map(usage => `
        <label class="filter-item" data-value="${usage}">
            <input type="checkbox" value="${usage}" checked onchange="applyDailyFilters()">
            <span>${usage}</span>
            <span class="filter-count" id="count-usage-${usage}">0</span>
        </label>
    `).join('');
}

// 소유자 필터 생성
function buildAccountFilter() {
    const container = document.getElementById('filter-accounts-list');
    if (!container) return;

    // 소유자 목록 추출 (owner 필드 사용)
    const owners = [...new Set(dailyData.map(d => d.owner || '미지정').filter(o => o))];
    owners.sort();

    // 소유자별 수량 계산
    const ownerCounts = {};
    dailyData.forEach(d => {
        const owner = d.owner || '미지정';
        ownerCounts[owner] = (ownerCounts[owner] || 0) + 1;
    });

    container.innerHTML = owners.map(owner => `
        <label class="filter-item" data-value="${owner}">
            <input type="checkbox" value="${owner}" checked onchange="applyDailyFilters()">
            <span>${owner}</span>
            <span class="filter-count">${ownerCounts[owner] || 0}</span>
        </label>
    `).join('');
}

// 필터 그룹 토글
function toggleFilterGroup(group) {
    const items = document.getElementById('filter-' + group);
    const icon = document.getElementById('toggle-' + group);

    if (items) items.classList.toggle('collapsed');
    if (icon) icon.classList.toggle('collapsed');
}

// 전체 선택/해제 토글
function toggleAllFilter(group) {
    let container;
    let selectAllCb;

    // 계급 필터는 별도 컨테이너
    if (group === 'sales-tier') {
        container = document.getElementById('salesTierCheckboxes');
        selectAllCb = document.getElementById('salesTierToggle');

        // 매출계급 체크 시 주문계급 해제 (배타적)
        if (selectAllCb && selectAllCb.checked) {
            const orderTierToggle = document.getElementById('orderTierToggle');
            if (orderTierToggle) {
                orderTierToggle.checked = false;
                // 주문계급 체크박스들도 모두 해제
                const orderContainer = document.getElementById('orderTierCheckboxes');
                if (orderContainer) {
                    orderContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                        cb.checked = false;
                    });
                }
            }
        }
    } else if (group === 'order-tier') {
        container = document.getElementById('orderTierCheckboxes');
        selectAllCb = document.getElementById('orderTierToggle');

        // 주문계급 체크 시 매출계급 해제 (배타적)
        if (selectAllCb && selectAllCb.checked) {
            const salesTierToggle = document.getElementById('salesTierToggle');
            if (salesTierToggle) {
                salesTierToggle.checked = false;
                // 매출계급 체크박스들도 모두 해제
                const salesContainer = document.getElementById('salesTierCheckboxes');
                if (salesContainer) {
                    salesContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                        cb.checked = false;
                    });
                }
            }
        }
    } else if (group === 'cleanup-tier') {
        container = document.getElementById('cleanupTierCheckboxes');
        selectAllCb = document.getElementById('cleanupTierToggle');
    } else {
        container = document.getElementById('filter-' + group);
        selectAllCb = container?.parentElement?.querySelector('.select-all-cb');
    }

    if (!container || !selectAllCb) return;

    const checkboxes = container.querySelectorAll('input[type="checkbox"]');
    const isChecked = selectAllCb.checked;

    checkboxes.forEach(cb => {
        cb.checked = isChecked;
    });

    applyDailyFilters();
}

// 필터 리스트 검색 (콤마로 복수 검색)
function filterListItems(group) {
    const searchInput = document.getElementById(group + 'SearchInput');
    const listContainer = document.getElementById('filter-' + group + '-list') || document.getElementById('filter-' + group);

    if (!searchInput || !listContainer) return;

    const searchText = searchInput.value.trim().toLowerCase();
    const searchTerms = searchText.split(',').map(t => t.trim()).filter(t => t);
    const items = listContainer.querySelectorAll('.filter-item');

    items.forEach(item => {
        const text = item.textContent.toLowerCase();
        const value = (item.dataset.value || item.querySelector('input')?.value || '').toLowerCase();

        if (searchTerms.length === 0) {
            // 검색어 없으면 모두 표시
            item.classList.remove('hidden');
        } else {
            // 검색어 중 하나라도 매칭되면 표시
            const match = searchTerms.some(term => text.includes(term) || value.includes(term));
            if (match) {
                item.classList.remove('hidden');
                // 매칭되면 체크도 함께
                const cb = item.querySelector('input[type="checkbox"]');
                if (cb) cb.checked = true;
            } else {
                item.classList.add('hidden');
            }
        }
    });

    // 검색어 입력 시 필터 자동 적용
    if (searchTerms.length > 0) {
        applyDailyFilters();
    }
}

// 필터 초기화
function resetMonitorFilters() {
    document.querySelectorAll('.filter-items input[type="checkbox"]').forEach(cb => {
        cb.checked = true;
    });
    // 검색창 초기화
    document.querySelectorAll('.filter-search-input').forEach(input => {
        input.value = '';
    });
    // 숨김 해제
    document.querySelectorAll('.filter-item.hidden').forEach(item => {
        item.classList.remove('hidden');
    });
    const searchEl = document.getElementById('dailySearch');
    if (searchEl) searchEl.value = '';

    applyDailyFilters();
}

// 뷰 모드 변경
function changeViewMode() {
    applyDailyFilters();
}

// 필터 적용
function applyDailyFilters() {
    const searchText = (document.getElementById('dailySearch')?.value || '').toLowerCase();

    // 체크된 필터값 수집
    const statusFilters = getCheckedValues('filter-status');
    const usageFilters = getCheckedValues('filter-usage');
    const ownerFilters = getCheckedValues('filter-accounts');

    // 체크된 계급 필터 수집
    const checkedSalesTiers = getCheckedTierValues('salesTierCheckboxes');
    const checkedOrderTiers = getCheckedTierValues('orderTierCheckboxes');
    const checkedCleanupTiers = getCheckedTierValues('cleanupTierCheckboxes');

    // 전체 데이터 기준 계급별 카운트 계산 (필터링 전)
    const salesTierCounts = {};
    const orderTierCounts = {};
    const cleanupTierCounts = {};
    dailyData.forEach(item => {
        const monthSales = (item.month_sales || 0) / 10000;
        const salesTierIdx = getTierIndex(monthSales, salesTiers, window.salesTierLabels);
        if (salesTierIdx >= 0) salesTierCounts[salesTierIdx] = (salesTierCounts[salesTierIdx] || 0) + 1;

        const monthOrders = item.month_orders || 0;
        const orderTierIdx = getTierIndex(monthOrders, orderTiers, window.orderTierLabels);
        if (orderTierIdx >= 0) orderTierCounts[orderTierIdx] = (orderTierCounts[orderTierIdx] || 0) + 1;

        const daysSinceCleanup = item.days_since_cleanup || 0;
        const cleanupTierIdx = getTierIndex(daysSinceCleanup, cleanupTiers, window.cleanupTierLabels);
        if (cleanupTierIdx >= 0) cleanupTierCounts[cleanupTierIdx] = (cleanupTierCounts[cleanupTierIdx] || 0) + 1;
    });

    // 필터링
    dailyFiltered = dailyData.filter(item => {
        // 상단 마켓 필터 바 (복수 선택)
        if (!selectedMarketFilters.has('전체') && !selectedMarketFilters.has(item.market)) return false;

        // 상태 필터 (체크박스 존재 시: 아무것도 체크 안 하면 숨김, 일부 체크하면 체크된 것만)
        const statusCheckboxes = document.querySelectorAll('#filter-status input[type="checkbox"]');
        if (statusCheckboxes.length > 0) {
            if (statusFilters.length === 0) return false; // 아무것도 체크 안 함 → 숨김
            const itemStatus = item.status || 'normal';
            if (!statusFilters.includes(itemStatus)) return false;
        }

        // 용도 필터 (체크박스 존재 시: 아무것도 체크 안 하면 숨김, 일부 체크하면 체크된 것만)
        const usageCheckboxes = document.querySelectorAll('#filter-usage input[type="checkbox"]');
        if (usageCheckboxes.length > 0) {
            if (usageFilters.length === 0) return false; // 아무것도 체크 안 함 → 숨김
            const itemUsage = item.usage || '';
            if (!usageFilters.includes(itemUsage)) return false;
        }

        // 소유자 필터 (체크박스 존재 시: 아무것도 체크 안 하면 숨김, 일부 체크하면 체크된 것만)
        const ownerCheckboxes = document.querySelectorAll('#filter-accounts input[type="checkbox"]');
        if (ownerCheckboxes.length > 0) {
            if (ownerFilters.length === 0) return false; // 아무것도 체크 안 함 → 숨김
            const owner = item.owner || '미지정';
            if (!ownerFilters.includes(owner)) return false;
        }

        // 매출 계급 필터 (AND 조건: 전체선택 버튼이 ON일 때만 활성화)
        const salesTierToggle = document.getElementById('salesTierToggle');
        if (salesTierToggle && salesTierToggle.checked) {
            if (checkedSalesTiers.length > 0) {
                const monthSales = (item.month_sales || 0) / 10000;
                const salesTierIdx = getTierIndex(monthSales, salesTiers, window.salesTierLabels);
                if (!checkedSalesTiers.includes(salesTierIdx)) return false;
            }
        }

        // 주문 계급 필터 (AND 조건: 전체선택 버튼이 ON일 때만 활성화)
        const orderTierToggle = document.getElementById('orderTierToggle');
        if (orderTierToggle && orderTierToggle.checked) {
            if (checkedOrderTiers.length > 0) {
                const monthOrders = item.month_orders || 0;
                const orderTierIdx = getTierIndex(monthOrders, orderTiers, window.orderTierLabels);
                if (!checkedOrderTiers.includes(orderTierIdx)) return false;
            }
        }

        // 경과일 계급 필터 (AND 조건: 전체선택 버튼이 ON일 때만 활성화)
        const cleanupTierToggle = document.getElementById('cleanupTierToggle');
        if (cleanupTierToggle && cleanupTierToggle.checked) {
            if (checkedCleanupTiers.length > 0) {
                const daysSinceCleanup = item.days_since_cleanup || 0;
                const cleanupTierIdx = getTierIndex(daysSinceCleanup, cleanupTiers, window.cleanupTierLabels);
                if (!checkedCleanupTiers.includes(cleanupTierIdx)) return false;
            }
        }

        // 검색
        if (searchText && !item.account.toLowerCase().includes(searchText)) return false;
        return true;
    });

    // 계급별 카운트 업데이트 (전체 데이터 기준)
    if (window.salesTierLabels) {
        window.salesTierLabels.forEach((_, idx) => {
            const el = document.getElementById(`count-sales-tier-${idx}`);
            if (el) el.textContent = salesTierCounts[idx] || 0;
        });
    }
    if (window.orderTierLabels) {
        window.orderTierLabels.forEach((_, idx) => {
            const el = document.getElementById(`count-order-tier-${idx}`);
            if (el) el.textContent = orderTierCounts[idx] || 0;
        });
    }
    if (window.cleanupTierLabels) {
        window.cleanupTierLabels.forEach((_, idx) => {
            const el = document.getElementById(`count-cleanup-tier-${idx}`);
            if (el) el.textContent = cleanupTierCounts[idx] || 0;
        });
    }

    // 활성화된 필터에 따라 정렬
    const salesTierToggle = document.getElementById('salesTierToggle');
    const orderTierToggle = document.getElementById('orderTierToggle');
    const cleanupTierToggle = document.getElementById('cleanupTierToggle');

    if (cleanupTierToggle && cleanupTierToggle.checked && checkedCleanupTiers.length > 0) {
        // 경과일 필터 ON → 경과일 많은 순 (오래된 것 우선)
        dailyFiltered.sort((a, b) => (b.days_since_cleanup || 0) - (a.days_since_cleanup || 0));
    } else if (orderTierToggle && orderTierToggle.checked && checkedOrderTiers.length > 0) {
        // 주문 계급 필터 ON → 주문순 정렬
        dailyFiltered.sort((a, b) => (b.month_orders || 0) - (a.month_orders || 0));
    } else if (salesTierToggle && salesTierToggle.checked && checkedSalesTiers.length > 0) {
        // 매출 계급 필터 ON → 매출순 정렬
        dailyFiltered.sort((a, b) => (b.month_sales || 0) - (a.month_sales || 0));
    } else {
        // 기본 매출순 정렬
        dailyFiltered.sort((a, b) => (b.month_sales || 0) - (a.month_sales || 0));
    }

    // 통계 업데이트
    updateDailyStats();

    // 그리드 렌더링
    renderDailyGrid();
}

// 체크된 계급 인덱스 배열 반환
function getCheckedTierValues(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return [];
    return [...container.querySelectorAll('input:checked')].map(cb => parseInt(cb.value));
}

function getCheckedValues(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return [];
    return [...container.querySelectorAll('input:checked')].map(cb => cb.value);
}

// 통계 업데이트
function updateDailyStats() {
    // 전체 데이터 기준 카운트 (필터 바용)
    const totalMarketCounts = {};
    const totalStatusCounts = { normal: 0, caution: 0, warning: 0, suspended: 0, stopped: 0 };

    dailyData.forEach(item => {
        totalMarketCounts[item.market] = (totalMarketCounts[item.market] || 0) + 1;
        const status = item.status || 'normal';
        totalStatusCounts[status] = (totalStatusCounts[status] || 0) + 1;
    });

    // 필터링된 데이터 기준 카운트
    const marketCounts = {};
    const usageCounts = {};
    const ownerCounts = {};
    const statusCounts = { normal: 0, caution: 0, warning: 0, suspended: 0, stopped: 0 };

    dailyFiltered.forEach(item => {
        marketCounts[item.market] = (marketCounts[item.market] || 0) + 1;

        const usage = item.usage || '미지정';
        usageCounts[usage] = (usageCounts[usage] || 0) + 1;

        const owner = item.owner || '미지정';
        ownerCounts[owner] = (ownerCounts[owner] || 0) + 1;

        const status = item.status || 'normal';
        statusCounts[status] = (statusCounts[status] || 0) + 1;
    });

    const total = dailyFiltered.length;
    const totalAll = dailyData.length;

    document.getElementById('dailyTotal').textContent = `${total}개 계정`;

    // 상단 마켓 필터 바 카운트 업데이트
    const barTotal = document.getElementById('count-bar-전체');
    if (barTotal) barTotal.textContent = totalAll;

    dailyMarkets.forEach(market => {
        const barEl = document.getElementById(`count-bar-${market}`);
        if (barEl) barEl.textContent = totalMarketCounts[market] || 0;

        // 사이드 필터도 업데이트
        const el = document.getElementById(`count-market-${market}`);
        if (el) el.textContent = marketCounts[market] || 0;
    });

    // 상태별 카운트 업데이트
    ['normal', 'caution', 'warning', 'suspended', 'stopped'].forEach(status => {
        const el = document.getElementById(`count-${status}`);
        if (el) el.textContent = totalStatusCounts[status] || 0;
    });

    // 용도별 카운트 업데이트
    dailyUsages.forEach(usage => {
        const el = document.getElementById(`count-usage-${usage}`);
        if (el) el.textContent = usageCounts[usage] || 0;
    });
}

// ========== 계급 필터 ==========
let salesTiers = [50, 100, 150, 200];  // 만원 단위
let orderTiers = [1, 3, 5, 10];  // 건수
let cleanupTiers = [14, 28, 42, 56];  // 경과일 (2, 4, 6, 8주)
let selectedSalesTiers = new Set();  // 선택된 매출 계급
let selectedOrderTiers = new Set();  // 선택된 주문 계급
let selectedCleanupTiers = new Set();  // 선택된 경과일 계급

// 계급 필터 초기화
function initTierFilters() {
    updateSalesTierFilter();
    updateOrderTierFilter();
    updateCleanupTierFilter();
}

// 매출 계급 필터 업데이트
function updateSalesTierFilter() {
    const input = document.getElementById('salesTierValues');
    if (!input) return;

    const values = input.value.split(',').map(v => parseInt(v.trim())).filter(v => !isNaN(v)).sort((a, b) => a - b);
    if (values.length > 0) salesTiers = values;

    renderTierCheckboxes('salesTierCheckboxes', salesTiers, '만원', 'sales', selectedSalesTiers);
}

// 주문 계급 필터 업데이트
function updateOrderTierFilter() {
    const input = document.getElementById('orderTierValues');
    if (!input) return;

    const values = input.value.split(',').map(v => parseInt(v.trim())).filter(v => !isNaN(v)).sort((a, b) => a - b);
    if (values.length > 0) orderTiers = values;

    renderTierCheckboxes('orderTierCheckboxes', orderTiers, '건', 'order', selectedOrderTiers);
}

// 경과일 계급 필터 업데이트
function updateCleanupTierFilter() {
    const input = document.getElementById('cleanupTierValues');
    if (!input) return;

    const values = input.value.split(',').map(v => parseInt(v.trim())).filter(v => !isNaN(v)).sort((a, b) => a - b);
    if (values.length > 0) cleanupTiers = values;

    renderTierCheckboxes('cleanupTierCheckboxes', cleanupTiers, '주', 'cleanup', selectedCleanupTiers);
}

// 계급 체크박스 렌더링
function renderTierCheckboxes(containerId, tiers, unit, type, selectedSet) {
    const container = document.getElementById(containerId);
    if (!container) return;

    // 계급 레이블 생성 (높은 순: 200 이상 → 150~200 → 100~150 → 50~100 → 50 이하)
    const labels = [];
    for (let i = tiers.length - 1; i >= 0; i--) {
        if (i === tiers.length - 1) {
            const val = (type === 'cleanup' && unit === '주') ? tiers[i] / 7 : tiers[i];
            labels.push({ label: `${val}${unit} 이상`, min: tiers[i], max: Infinity });
        }
        if (i > 0) {
            const minVal = (type === 'cleanup' && unit === '주') ? tiers[i - 1] / 7 : tiers[i - 1];
            const maxVal = (type === 'cleanup' && unit === '주') ? tiers[i] / 7 : tiers[i];
            labels.push({ label: `${minVal}~${maxVal}${unit}`, min: tiers[i - 1], max: tiers[i] });
        }
        if (i === 0) {
            const val = (type === 'cleanup' && unit === '주') ? tiers[0] / 7 : tiers[0];
            labels.push({ label: `${val}${unit} 이하`, min: 0, max: tiers[0] });
        }
    }

    // 기본 모두 체크
    container.innerHTML = labels.map((tier, idx) => `
        <label class="filter-item">
            <input type="checkbox" value="${idx}" checked onchange="applyDailyFilters()">
            <span>${tier.label}</span>
            <span class="filter-count" id="count-${type}-tier-${idx}">0</span>
        </label>
    `).join('');

    // 저장
    if (type === 'sales') window.salesTierLabels = labels;
    else if (type === 'order') window.orderTierLabels = labels;
    else if (type === 'cleanup') window.cleanupTierLabels = labels;
}

// 값이 어떤 계급에 속하는지 반환
function getTierIndex(value, tiers, labels) {
    if (!labels) return -1;
    for (let i = 0; i < labels.length; i++) {
        if (value >= labels[i].min && value < labels[i].max) return i;
        if (labels[i].max === Infinity && value >= labels[i].min) return i;
    }
    return labels.length - 1;  // 가장 낮은 계급
}

// 마켓별 색상
function getMarketColor(market) {
    if (market.includes('스마트') || market.includes('네이버')) return '#03C75A';
    if (market.includes('11번가')) return '#E31837';
    if (market.includes('쿠팡')) return '#00B4D8';
    if (market.includes('지마켓')) return '#1A73E8';
    if (market.includes('옥션')) return '#9C27B0';
    return '#667eea';
}

// ========== 다중 선택 & 상품삭제 이동 (Monitor Ported) ==========
let dailyMonitorDragInitialized = false;
let monitorSelectionBox = null;
let monitorIsDragging = false;
let monitorSelectionStart = { x: 0, y: 0 };

function initMonitorDragSelection(gridId = 'dailyGrid') {
    if (window.dailyMonitorDragInitialized) return;
    const grid = document.getElementById(gridId);
    if (!grid) return;

    // CSS 주입
    if (!document.getElementById('monitorSelectionStyle')) {
        const style = document.createElement('style');
        style.id = 'monitorSelectionStyle';
        style.textContent = `
            .monitor-card-new.selected {
                border: 2px solid #2196F3 !important;
                background-color: #e3f2fd !important;
                transform: translateY(-2px);
                box-shadow: 0 4px 8px rgba(33, 150, 243, 0.3);
            }
            .monitor-selection-box {
                position: absolute;
                border: 1px solid #2196F3;
                background-color: rgba(33, 150, 243, 0.2);
                z-index: 1000;
                pointer-events: none;
            }
            /* Modal Button Fix */
            .modal-footer { display: flex; justify-content: flex-end; gap: 8px; }
            .modal-footer .modal-btn { margin: 0; }
        `;
        document.head.appendChild(style);
    }

    grid.addEventListener('mousedown', e => {
        if (!e.shiftKey) return;
        monitorIsDragging = true;
        monitorSelectionStart = { x: e.pageX + window.scrollX, y: e.pageY + window.scrollY };

        monitorSelectionBox = document.createElement('div');
        monitorSelectionBox.className = 'monitor-selection-box';
        monitorSelectionBox.style.left = e.pageX + 'px';
        monitorSelectionBox.style.top = e.pageY + 'px';
        document.body.appendChild(monitorSelectionBox);
        e.preventDefault();
    });

    document.addEventListener('mousemove', e => {
        if (!monitorIsDragging || !monitorSelectionBox) return;
        const currentX = e.pageX + window.scrollX;
        const currentY = e.pageY + window.scrollY;

        const width = Math.abs(currentX - monitorSelectionStart.x);
        const height = Math.abs(currentY - monitorSelectionStart.y);
        const left = Math.min(currentX, monitorSelectionStart.x);
        const top = Math.min(currentY, monitorSelectionStart.y);

        monitorSelectionBox.style.width = width + 'px';
        monitorSelectionBox.style.height = height + 'px';
        monitorSelectionBox.style.left = (left - window.scrollX) + 'px'; // Fixed position relative to viewport? 
        // No, absolute is relative to document if body relative? 
        // Actually pageX is relative to document.
        monitorSelectionBox.style.left = left + 'px';
        monitorSelectionBox.style.top = top + 'px';

        highlightCardsInBox(left, top, width, height);
    });

    document.addEventListener('mouseup', e => {
        if (!monitorIsDragging) return;
        monitorIsDragging = false;
        if (monitorSelectionBox) {
            document.body.removeChild(monitorSelectionBox);
            monitorSelectionBox = null;
        }

        // Finalize selection
        const selecting = grid.querySelectorAll('.monitor-card-new.selecting');
        selecting.forEach(card => {
            card.classList.add('selected');
            card.classList.remove('selecting');
            card.style.outline = '';
        });
    });

    window.dailyMonitorDragInitialized = true;
}

function highlightCardsInBox(boxLeft, boxTop, boxWidth, boxHeight) {
    const boxRight = boxLeft + boxWidth;
    const boxBottom = boxTop + boxHeight;
    const cards = document.querySelectorAll('#dailyGrid .monitor-card-new');

    cards.forEach(card => {
        const rect = card.getBoundingClientRect();
        // Compare in document coordinates
        const cardLeft = rect.left + window.scrollX;
        const cardTop = rect.top + window.scrollY;

        // Simple intersection
        if (cardLeft < boxRight && (cardLeft + rect.width) > boxLeft &&
            cardTop < boxBottom && (cardTop + rect.height) > boxTop) {
            card.classList.add('selecting');
            card.style.outline = '2px dashed #2196F3';
        } else {
            card.classList.remove('selecting');
            card.style.outline = '';
        }
    });
}

// Redirect to All-in-One for any task
function goToDailyAioTask(targetMarket, targetAccount, task) {
    let selected = document.querySelectorAll('#dailyGrid .monitor-card-new.selected');
    let accountsToSelect = [];

    // 타겟이 선택된 그룹에 포함되어 있는지 확인
    let targetInSelection = false;
    selected.forEach(card => {
        if (card.dataset.market === targetMarket && card.dataset.account === targetAccount) {
            targetInSelection = true;
        }
    });

    // 포함되어 있다면 선택된 모든 (같은 마켓) 계정 수집
    if (targetInSelection) {
        selected.forEach(card => {
            if (card.dataset.market === targetMarket) {
                accountsToSelect.push(card.dataset.account);
            }
        });
    } else {
        // 포함 안되어 있다면 타겟만
        accountsToSelect.push(targetAccount);
    }

    if (accountsToSelect.length === 0) return;

    // pending 설정 (먼저 설정해야 loadAioStores에서 사용 가능)
    window.aioPendingSelection = new Set(accountsToSelect);
    console.log('[AIO] Set pending selection:', Array.from(window.aioPendingSelection), 'task:', task);

    // Switch Tab
    const aioTab = document.querySelector('.tab[data-tab="allinone"]');
    if (aioTab) aioTab.click();

    // 탭 전환 후 플랫폼/작업 설정 (selectAioPlatform 호출 안 함 - 내부에서 selectAioTask 호출하면 pending 소비됨)
    setTimeout(() => {
        // 수동으로 플랫폼 상태 설정 (selectAioPlatform 내부 로직과 동일하지만 selectAioTask 호출 제외)
        currentAioPlatform = targetMarket;

        // 플랫폼 버튼 활성화
        document.querySelectorAll('.aio-platform-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.platform === targetMarket);
        });

        // 작업 버튼 표시/숨김
        document.querySelectorAll('.aio-task-btn').forEach(btn => {
            const btnPlatform = btn.dataset.platform;
            btn.style.display = (btnPlatform === targetMarket) ? '' : 'none';
        });

        // 선택 초기화
        aioSelectedStores.clear();
        updateAioStoreCount();

        // 지정된 작업 선택 (loadAioStores 호출됨 - pending 사용)
        if (typeof selectAioTask === 'function' && task) {
            selectAioTask(task);
        }

        showToast(`${task}: ${accountsToSelect.length}개 계정 선택됨`, 'info');
    }, 300);
}

// 하위 호환성을 위한 래퍼
function goToDailyAioDelete(targetMarket, targetAccount) {
    goToDailyAioTask(targetMarket, targetAccount, '상품삭제');
}

// 그리드 렌더링
function renderDailyGrid() {
    const grid = document.getElementById('dailyGrid');

    // 드래그 선택 초기화
    if (!window.dailyMonitorDragInitialized) initMonitorDragSelection();

    if (dailyFiltered.length === 0) {
        grid.innerHTML = '<div class="empty-state">조건에 맞는 계정이 없습니다</div>';
        return;
    }

    // 계급 필터 활성화 여부 확인 (전체선택 버튼이 ON이고 체크된 항목이 있으면 활성화)
    const salesChecked = getCheckedTierValues('salesTierCheckboxes');
    const orderChecked = getCheckedTierValues('orderTierCheckboxes');
    const salesTierToggle = document.getElementById('salesTierToggle');
    const orderTierToggle = document.getElementById('orderTierToggle');

    const salesFilterActive = salesTierToggle && salesTierToggle.checked && salesChecked.length > 0;
    const orderFilterActive = orderTierToggle && orderTierToggle.checked && orderChecked.length > 0;

    // 어떤 기준으로 그룹화할지 결정
    let groupBy = null;  // 'sales', 'order', 또는 null
    let tierLabels = null;
    let tiers = null;

    if (orderFilterActive) {
        groupBy = 'order';
        tierLabels = window.orderTierLabels;
        tiers = orderTiers;
    } else if (salesFilterActive) {
        groupBy = 'sales';
        tierLabels = window.salesTierLabels;
        tiers = salesTiers;
    }

    // 계급 필터가 비활성화면 기존 방식으로 렌더링
    if (!groupBy) {
        let html = '<div class="tier-cards">';
        dailyFiltered.forEach((item) => {
            html += renderCard(item);
        });
        html += '</div>';
        grid.innerHTML = html;
        return;
    }

    // 계급별 아이콘 정의 (SVG)
    const tierIcons = {
        0: `<svg class="tier-icon" viewBox="0 0 64 64"><path d="M32 8l6 12 14 2-10 10 2 14-12-6-12 6 2-14L12 22l14-2z" fill="#FFD700" stroke="#B8860B" stroke-width="2"/><rect x="16" y="38" width="32" height="20" rx="2" fill="none" stroke="#B8860B" stroke-width="2"/><circle cx="24" cy="48" r="3" fill="#B8860B"/><circle cx="32" cy="48" r="3" fill="#B8860B"/><circle cx="40" cy="48" r="3" fill="#B8860B"/></svg>`,
        1: `<svg class="tier-icon" viewBox="0 0 64 64"><path d="M32 12l8 16 12-8-4 20H16l-4-20 12 8z" fill="none" stroke="#333" stroke-width="2"/><path d="M12 44h40v4H12z" fill="none" stroke="#333" stroke-width="2"/></svg>`,
        2: `<svg class="tier-icon" viewBox="0 0 64 64"><path d="M32 8l-20 48h40z" fill="none" stroke="#333" stroke-width="2"/><circle cx="24" cy="36" r="4" fill="#333"/><circle cx="32" cy="28" r="4" fill="#333"/><circle cx="40" cy="36" r="4" fill="#333"/></svg>`,
        3: `<svg class="tier-icon" viewBox="0 0 64 64"><circle cx="32" cy="32" r="20" fill="none" stroke="#333" stroke-width="2"/><path d="M32 16v16l12 8" fill="none" stroke="#333" stroke-width="2" stroke-linecap="round"/></svg>`,
        4: `<svg class="tier-icon" viewBox="0 0 64 64"><ellipse cx="32" cy="32" rx="20" ry="12" fill="none" stroke="#333" stroke-width="2"/><ellipse cx="32" cy="24" rx="12" ry="6" fill="none" stroke="#333" stroke-width="2"/></svg>`
    };

    // 계급별 그룹화
    const tierGroups = {};  // {tierIdx: [items]}

    dailyFiltered.forEach((item) => {
        let value, currentTierIdx;

        if (groupBy === 'order') {
            value = item.month_orders || 0;
            currentTierIdx = getTierIndex(value, tiers, tierLabels);
        } else {
            value = (item.month_sales || 0) / 10000;
            currentTierIdx = getTierIndex(value, tiers, tierLabels);
        }

        if (!tierGroups[currentTierIdx]) {
            tierGroups[currentTierIdx] = [];
        }
        tierGroups[currentTierIdx].push(item);
    });

    // 계급 순서대로 렌더링 (높은 계급부터)
    let html = '';
    const sortedTiers = Object.keys(tierGroups).map(Number).sort((a, b) => a - b);

    sortedTiers.forEach((tierIdx) => {
        const items = tierGroups[tierIdx];
        const tierLabel = tierLabels[tierIdx].label;
        const tierIcon = tierIcons[tierIdx] || tierIcons[4];

        html += `
            <div class="tier-section">
                <div class="tier-header">
                    <div class="tier-icon-wrapper">${tierIcon}</div>
                    <span class="tier-label">${tierLabel}</span>
                </div>
                <div class="tier-divider"></div>
            </div>
            <div class="tier-cards">
        `;

        items.forEach(item => {
            html += renderCard(item);
        });

        html += `</div>`;
    });

    grid.innerHTML = html;
}

// 카드 렌더링 헬퍼
function renderCard(item) {
    const count = item.count || 0;
    const status = item.status || 'normal';

    let marketClass = 'smartstore';
    if (item.market === '쿠팡') { marketClass = 'coupang'; }
    else if (item.market === '11번가') { marketClass = 'st11'; }
    else if (item.market === '지마켓') { marketClass = 'gmarket'; }
    else if (item.market === '옥션') { marketClass = 'auction'; }

    const stoppedClass = status === 'stopped' ? 'stopped' : '';

    return `
        <div class="monitor-card-new ${marketClass} ${stoppedClass}"
             data-row="${item.row}"
             data-account="${item.account}"
             data-market="${item.market}"
             data-status="${status}"
             onclick="handleCardSingleClick(event, this)"
             ondblclick="handleCardDoubleClick(event, '${item.market}', '${item.account}')"
             oncontextmenu="showDailyContextMenu(event, ${item.row}, '${item.account}', '${item.market}')">
            <div class="market-label"></div>
            <div class="card-body">
                <div class="card-content">
                    <span class="status-dot ${status}"></span>
                    <span class="account-name">${item.account}</span>
                    <span class="count" style="color: blue !important; font-weight: bold;">(${count.toLocaleString()})</span>
                </div>
                <div class="expand-info">
                    <div class="expand-row">💰 ₩${(item.today_sales || 0).toLocaleString()} (${item.today_orders || 0}건)</div>
                    <div class="expand-row">📊 ₩${(item.month_sales || 0).toLocaleString()}</div>
                    <div class="expand-row">📦 14일: ${item.orders_2w || 0}건 / 월: ${item.month_orders || 0}건</div>
                    <div class="expand-row cleanup-row ${item.cleanup_status || 'normal'}">📅 ${item.last_cleanup_date || '-'} (${item.days_since_cleanup || 0}일전)</div>
                </div>
            </div>
        </div>
    `;
}

// 싱글 클릭 타이머
let singleClickTimer = null;
let selectionAnchor = null; // 범위 선택 기준점

// 싱글 클릭 - 카드 선택
function handleCardSingleClick(event, card) {
    // 더블클릭 대기 (250ms)
    if (singleClickTimer) {
        clearTimeout(singleClickTimer);
        singleClickTimer = null;
        return; // 더블클릭이므로 싱글클릭 무시
    }

    // 이벤트 키 상태 미리 캡처 (setTimeout 내에서 event 객체가 변경될 수 있음)
    const isShiftKey = event.shiftKey;
    const isCtrlKey = event.ctrlKey || event.metaKey;

    singleClickTimer = setTimeout(() => {
        singleClickTimer = null;

        const allCards = Array.from(document.querySelectorAll('#dailyGrid .monitor-card-new'));
        const clickedIndex = allCards.indexOf(card);

        if (isShiftKey && selectionAnchor !== null) {
            // Shift+클릭: 앵커부터 현재 카드까지 범위 선택
            const anchorIndex = allCards.indexOf(selectionAnchor);
            if (anchorIndex !== -1 && clickedIndex !== -1) {
                const start = Math.min(anchorIndex, clickedIndex);
                const end = Math.max(anchorIndex, clickedIndex);

                // 기존 선택 해제
                allCards.forEach(c => c.classList.remove('selected'));

                // 범위 내 모든 카드 선택
                for (let i = start; i <= end; i++) {
                    allCards[i].classList.add('selected');
                }
            }
        } else if (isCtrlKey) {
            // Ctrl+클릭: 개별 토글
            card.classList.toggle('selected');
            if (card.classList.contains('selected')) {
                selectionAnchor = card; // 앵커 업데이트
            }
        } else {
            // 일반 클릭: 다른 선택 해제 후 이 카드만 선택
            allCards.forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            selectionAnchor = card; // 앵커 설정
        }
    }, 250);
}

// 더블 클릭 - 자동 로그인
function handleCardDoubleClick(event, market, account) {
    event.preventDefault();
    event.stopPropagation();

    // 싱글 클릭 타이머 취소
    if (singleClickTimer) {
        clearTimeout(singleClickTimer);
        singleClickTimer = null;
    }

    console.log('[더블클릭] 자동로그인:', market, account);
    doDailyAutoLogin(market, account);
}

// 클릭 타이머 (더블클릭 구분용)
let dailyClickTimer = null;

// 왼쪽 클릭 - 확장정보 표시
function showDailyExtendedInfo(event, row, account, market) {
    event.preventDefault();
    event.stopPropagation();

    // 클릭한 카드 미리 저장 (setTimeout 내에서 event.target 사용 불가)
    const clickedCard = event.target.closest('.market-card-mini');

    // 더블클릭과 구분 (250ms 대기)
    if (dailyClickTimer) {
        clearTimeout(dailyClickTimer);
        dailyClickTimer = null;
        return;
    }

    dailyClickTimer = setTimeout(() => {
        dailyClickTimer = null;

        const item = dailyFiltered.find(d => d.row === row);
        if (!item) return;

        // 확장정보 패널 표시
        showDailyInfoPanel(clickedCard, item);
    }, 250);
}

// 확장정보 패널 표시 (일일장부용 - 컴팩트)
function showDailyInfoPanel(card, item) {
    // 기존 패널 제거
    const existingPanel = document.getElementById('extendedInfoPanel');
    if (existingPanel) existingPanel.remove();

    // card가 없으면 중단
    if (!card) {
        console.error('showDailyInfoPanel: card is null');
        return;
    }

    const panel = document.createElement('div');
    panel.id = 'extendedInfoPanel';
    panel.className = 'extended-info-panel compact';
    panel.innerHTML = `
        <div class="ext-info-header compact">
            <span class="ext-info-title">${item.account}</span>
            <button class="ext-info-close" onclick="closeExtendedInfo()">×</button>
        </div>
        <div class="ext-info-body compact">
            <div class="ext-compact-grid">
                <div class="ext-compact-item">
                    <span class="ext-compact-label">오늘 매출</span>
                    <span class="ext-compact-value">₩${(item.today_sales || 0).toLocaleString()}</span>
                </div>
                <div class="ext-compact-item">
                    <span class="ext-compact-label">오늘 판매</span>
                    <span class="ext-compact-value">${(item.today_orders || 0)}건</span>
                </div>
                <div class="ext-compact-item">
                    <span class="ext-compact-label">이달 매출</span>
                    <span class="ext-compact-value">₩${(item.month_sales || 0).toLocaleString()}</span>
                </div>
                <div class="ext-compact-item">
                    <span class="ext-compact-label">이달 판매</span>
                    <span class="ext-compact-value">${(item.month_orders || 0)}건</span>
                </div>
            </div>
            <div class="ext-penalty-row">
                <span class="penalty-badge yellow">주의 ${item.caution_count || 0}</span>
                <span class="penalty-badge orange">경고 ${item.warning_count || 0}</span>
                <span class="penalty-badge red">정지 ${item.suspend_count || 0}</span>
            </div>
        </div>
        <div class="ext-info-footer compact">
            <button class="ext-btn small" onclick="doDailyAutoLogin('${item.market}', '${item.account}')">🔐 로그인</button>
            <button class="ext-btn small secondary" onclick="showDailyContextMenuDirect('${item.row}', '${item.account}', '${item.market}'); closeExtendedInfo();">⚡ 작업</button>
        </div>
    `;

    document.body.appendChild(panel);

    // 위치 계산 - fixed 포지션으로 뷰포트 기준
    const rect = card.getBoundingClientRect();
    const panelWidth = 220;
    const panelHeight = 180;

    let left = rect.left;
    let top = rect.bottom + 5;

    // 화면 오른쪽 밖으로 나가면 조정
    if (left + panelWidth > window.innerWidth - 10) {
        left = window.innerWidth - panelWidth - 10;
    }

    // 화면 아래로 나가면 카드 위에 표시
    if (top + panelHeight > window.innerHeight - 10) {
        top = rect.top - panelHeight - 5;
    }

    // 여전히 위로 나가면 화면 내에서 조정
    if (top < 10) {
        top = 10;
    }

    panel.style.position = 'fixed';
    panel.style.left = left + 'px';
    panel.style.top = top + 'px';
    panel.style.zIndex = '10000';

    setTimeout(() => {
        document.addEventListener('click', closeExtendedInfoOnOutside);
    }, 10);
}

// 확장정보 패널 닫기
function closeExtendedInfo() {
    const panel = document.querySelector('.daily-extended-info');
    if (panel) {
        panel.remove();
    }
    document.removeEventListener('click', closeExtendedInfoOnOutside);
}

// 외부 클릭 시 확장정보 패널 닫기
function closeExtendedInfoOnOutside(event) {
    const panel = document.querySelector('.daily-extended-info');
    if (panel && !panel.contains(event.target)) {
        closeExtendedInfo();
    }
}

// 작업 메뉴 직접 표시 (확장정보에서 호출)
function showDailyContextMenuDirect(row, account, market) {
    dailyContextTarget = { row: parseInt(row), account, market };

    const menu = document.getElementById('dailyContextMenu');
    const header = document.getElementById('ctxHeader');
    header.textContent = `${account}`;

    // 플랫폼별 메뉴 구성
    updateDailyContextMenuItems(market);

    // 화면 중앙에 표시
    menu.style.left = (window.innerWidth / 2 - 100) + 'px';
    menu.style.top = (window.innerHeight / 2 - 150) + 'px';
    menu.style.display = 'block';

    setTimeout(() => {
        document.addEventListener('click', closeDailyContextMenu, { once: true });
    }, 10);
}

// 더블클릭 - 자동 로그인 (서버 API 사용)
async function doDailyAutoLogin(market, account) {
    console.log('[자동로그인] 시작:', market, account);
    closeExtendedInfo();

    // dailyData에서 login_id 찾기
    const item = dailyData.find(d => d.account === account && d.market === market);
    if (!item || !item.login_id) {
        console.log('[자동로그인] 계정 정보 없음:', account, market);
        showToast('계정 정보를 찾을 수 없습니다', 'error');
        return;
    }

    const loginId = item.login_id;
    const platform = item.platform || market;

    showToast(`${account} 자동 로그인 시작...`, 'info');

    try {
        console.log('[자동로그인] 서버 API 호출:', platform, loginId);
        const r = await fetch('/api/auto-login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                platform: platform,
                login_id: loginId
            })
        });
        const d = await r.json();

        if (d.success || d.pending) {
            console.log('[자동로그인] 요청 완료 - 클라이언트에서 처리 중');
            showToast('자동 로그인 요청 완료 - 클라이언트에서 처리 중', 'success');
        } else {
            console.log('[자동로그인] 실패:', d.message);
            showToast('자동 로그인 실패: ' + (d.message || ''), 'error');
        }
    } catch (e) {
        console.error('[자동로그인] 오류:', e);
        showToast('자동 로그인 실패', 'error');
    }
}

// 컨텍스트 메뉴 (우클릭)
function showDailyContextMenu(event, row, account, market) {
    event.preventDefault();
    event.stopPropagation();

    dailyContextTarget = { row, account, market };

    // 선택 로직 (다중 선택 지원)
    const card = event.target.closest('.monitor-card-new');
    if (card) {
        if (card.classList.contains('selected')) {
            // 이미 선택된 항목 위에서 우클릭: 선택 유지 (그룹 동작)
        } else {
            // 선택되지 않은 항목: 다른 선택 해제하고 이것만 선택
            document.querySelectorAll('.monitor-card-new.selected').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
        }
        // ensure selection set matches UI? 
        // Logic relies on UI class '.selected' for collection later.
    }

    const menu = document.getElementById('dailyContextMenu');
    const header = document.getElementById('ctxHeader');
    header.textContent = `${account}`;

    // 플랫폼별 메뉴 구성
    updateDailyContextMenuItems(market);

    // 메뉴 크기 계산을 위해 먼저 표시
    menu.style.visibility = 'hidden';
    menu.style.display = 'block';

    const menuHeight = menu.offsetHeight;
    const menuWidth = menu.offsetWidth;

    let left = event.clientX;
    let top = event.clientY;

    // 오른쪽 넘침 방지
    if (left + menuWidth > window.innerWidth - 10) {
        left = window.innerWidth - menuWidth - 10;
    }

    // 아래쪽 넘침 방지 - 위로 표시
    if (top + menuHeight > window.innerHeight - 10) {
        top = event.clientY - menuHeight;
        if (top < 10) top = 10;
    }

    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
    menu.style.visibility = 'visible';

    setTimeout(() => {
        document.addEventListener('click', closeDailyContextMenu, { once: true });
    }, 10);
}

// 플랫폼별 메뉴 아이템 업데이트
function updateDailyContextMenuItems(market) {
    const menu = document.getElementById('dailyContextMenu');
    let menuItems = '';

    if (market === '스마트스토어') {
        menuItems = `
            <div class="context-menu-header" id="ctxHeader">${dailyContextTarget?.account || ''}</div>
            <div class="ctx-menu-section">올인원 작업</div>
            <div class="context-menu-item" onclick="dailyContextAction('중복삭제')">🗑️ 중복삭제</div>
            <div class="context-menu-item" onclick="dailyContextAction('KC인증')">🔒 KC인증</div>
            <div class="context-menu-item" onclick="dailyContextAction('배송변경')">📦 배송변경</div>
            <div class="context-menu-item" onclick="dailyContextAction('혜택설정')">🎁 혜택설정</div>
            <div class="context-menu-item" onclick="dailyContextAction('상품삭제')">🗑️ 상품삭제</div>
            <div class="context-menu-divider"></div>
            <div class="ctx-menu-section">바로가기</div>
            <div class="context-menu-item" onclick="dailyContextAction('login')">🔐 자동로그인</div>
            <div class="context-menu-item" onclick="dailyContextAction('edit')">✏️ 계정 수정</div>
            <div class="context-menu-item" onclick="dailyContextAction('status')">🚦 상태 변경</div>
            <div class="context-menu-item" onclick="dailyContextAction('memo')">📝 메모 수정</div>
        `;
    } else if (market === '11번가') {
        menuItems = `
            <div class="context-menu-header" id="ctxHeader">${dailyContextTarget?.account || ''}</div>
            <div class="ctx-menu-section">올인원 작업</div>
            <div class="context-menu-item" onclick="dailyContextAction('판매중')">📊 판매중</div>
            <div class="context-menu-item" onclick="dailyContextAction('판매중지')">⏹️ 판매중지</div>
            <div class="context-menu-item" onclick="dailyContextAction('판매재개')">▶️ 판매재개</div>
            <div class="context-menu-divider"></div>
            <div class="ctx-menu-section">바로가기</div>
            <div class="context-menu-item" onclick="dailyContextAction('login')">🔐 자동로그인</div>
            <div class="context-menu-item" onclick="dailyContextAction('edit')">✏️ 계정 수정</div>
            <div class="context-menu-item" onclick="dailyContextAction('status')">🚦 상태 변경</div>
            <div class="context-menu-item" onclick="dailyContextAction('memo')">📝 메모 수정</div>
        `;
    } else if (market === '쿠팡') {
        menuItems = `
            <div class="context-menu-header" id="ctxHeader">${dailyContextTarget?.account || ''}</div>
            <div class="ctx-menu-section">올인원 작업</div>
            <div class="context-menu-item" onclick="dailyContextAction('가격반영')">💰 가격반영</div>
            <div class="context-menu-divider"></div>
            <div class="ctx-menu-section">바로가기</div>
            <div class="context-menu-item" onclick="dailyContextAction('login')">🔐 자동로그인</div>
            <div class="context-menu-item" onclick="dailyContextAction('edit')">✏️ 계정 수정</div>
            <div class="context-menu-item" onclick="dailyContextAction('status')">🚦 상태 변경</div>
            <div class="context-menu-item" onclick="dailyContextAction('memo')">📝 메모 수정</div>
        `;
    } else {
        menuItems = `
            <div class="context-menu-header" id="ctxHeader">${dailyContextTarget?.account || ''}</div>
            <div class="ctx-menu-section">바로가기</div>
            <div class="context-menu-item" onclick="dailyContextAction('login')">🔐 자동로그인</div>
            <div class="context-menu-item" onclick="dailyContextAction('edit')">✏️ 계정 수정</div>
            <div class="context-menu-item" onclick="dailyContextAction('status')">🚦 상태 변경</div>
            <div class="context-menu-item" onclick="dailyContextAction('memo')">📝 메모 수정</div>
        `;
    }

    menu.innerHTML = menuItems;
}

function closeDailyContextMenu() {
    document.getElementById('dailyContextMenu').style.display = 'none';
}

// 컨텍스트 메뉴 액션
function dailyContextAction(action) {
    closeDailyContextMenu();

    if (!dailyContextTarget) return;

    const { row, account, market } = dailyContextTarget;

    // 올인원 작업 목록
    const aioTasks = ['중복삭제', 'KC인증', '배송변경', '혜택설정', '상품삭제', '판매중', '판매중지', '판매재개', '가격반영'];

    if (aioTasks.includes(action)) {
        // 모든 올인원 작업: 선택된 계정들을 올인원 탭으로 전달
        goToDailyAioTask(market, account, action);
        return;
    }

    switch (action) {
        case 'login':
            // 자동 로그인
            doDailyAutoLogin(market, account);
            break;
        case 'edit':
            // 계정 수정 모달
            openDailyEditModal(market, account);
            break;
        case 'status':
            openStatusModal(row, account, market);
            break;
        case 'memo':
            openStatusModal(row, account, '비고');
            break;
    }
}

// 관제센터에서 개별 올인원 작업 실행
async function runDailyAioTask(market, account, task) {
    showToast(`${account} - ${task} 실행 중...`, 'info');

    try {
        // 계정 정보 조회 (shop_alias로 검색)
        const r = await fetch(`/api/accounts/search?shop_alias=${encodeURIComponent(account)}&platform=${encodeURIComponent(market)}`);
        const accountData = await r.json();

        if (!accountData.login_id) {
            showToast('계정 정보를 찾을 수 없습니다', 'error');
            return;
        }

        // 올인원 작업 실행
        const taskR = await fetch('/api/allinone/run-single', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                platform: market,
                login_id: account,  // shop_alias 사용
                task: task
            })
        });

        const taskD = await taskR.json();
        if (taskD.success) {
            showToast(`${account} - ${task} 시작됨`, 'success');
        } else {
            showToast(taskD.message || '실행 실패', 'error');
        }
    } catch (e) {
        console.error('올인원 작업 실행 실패:', e);
        showToast('작업 실행 실패', 'error');
    }
}

// 마켓 로그인 페이지 열기
function openMarketLogin(market) {
    const loginUrls = {
        '스마트스토어': 'https://account.commerce.naver.com/login',
        '쿠팡': 'https://wing.coupang.com/login',
        '11번가': 'https://login.11st.co.kr/auth/front/login.tmall',
        '11번가2': 'https://login.11st.co.kr/auth/front/login.tmall',
        '11번가3': 'https://login.11st.co.kr/auth/front/login.tmall',
        '11번가4': 'https://login.11st.co.kr/auth/front/login.tmall',
        '지마켓': 'https://minishop.gmarket.co.kr/Login',
        '옥션': 'https://minishop.auction.co.kr/Login'
    };

    const url = loginUrls[market];
    if (url) {
        window.open(url, '_blank');
    } else {
        showToast('로그인 URL 없음', 'error');
    }
}

// 관제센터 계정 수정 모달
let dailyEditTarget = null;

async function openDailyEditModal(market, account) {
    // dailyData에서 login_id 찾기
    const item = dailyData.find(d => d.account === account && d.market === market);
    if (!item || !item.login_id) {
        showToast('계정 정보를 찾을 수 없습니다', 'error');
        return;
    }

    const platform = item.platform || market;
    const loginId = item.login_id;

    try {
        // 계정 전체 정보 조회
        const r = await fetch(`/api/accounts/${encodeURIComponent(platform)}/${encodeURIComponent(loginId)}`);
        const data = await r.json();

        dailyEditTarget = { platform, loginId, account, market };

        // 모달 생성
        const isESM = market === '지마켓' || market === '옥션';

        let modalHtml = `
            <div id="dailyEditModal" class="modal-overlay" style="display:flex">
                <div class="modal-content" style="width:400px">
                    <div class="modal-header">
                        <h3>✏️ 계정 수정 - ${account}</h3>
                        <button class="modal-close" onclick="closeDailyEditModal()">×</button>
                    </div>
                    <div class="modal-body">
                        <div class="form-group">
                            <label>플랫폼</label>
                            <input type="text" value="${platform}" disabled style="background:#f5f5f5">
                        </div>
                        <div class="form-group">
                            <label>로그인 ID</label>
                            <input type="text" id="editLoginId" value="${data.login_id || ''}" disabled style="background:#f5f5f5">
                        </div>
                        <div class="form-group">
                            <label>비밀번호</label>
                            <input type="text" id="editPassword" value="${data.password || ''}">
                        </div>`;

        if (isESM) {
            modalHtml += `
                        <div class="form-group" style="margin-top:15px; padding-top:15px; border-top:1px solid #eee">
                            <label style="color:#1a73e8; font-weight:bold">ESM ID</label>
                            <input type="text" id="editEsmId" value="${data.esm_id || ''}">
                        </div>
                        <div class="form-group">
                            <label style="color:#1a73e8; font-weight:bold">ESM PW</label>
                            <input type="text" id="editEsmPw" value="${data.esm_pw || ''}">
                        </div>`;
        }

        if (market === '11번가') {
            modalHtml += `
                        <div class="form-group" style="margin-top:15px; padding-top:15px; border-top:1px solid #eee">
                            <label style="color:#ea4335; font-weight:bold">11번가 API KEY</label>
                            <input type="text" id="editApiKey" value="${data.api_key || ''}">
                        </div>`;
        }

        modalHtml += `
                    </div>
                    <div class="modal-footer">
                        <button class="btn secondary" onclick="closeDailyEditModal()">취소</button>
                        <button class="btn primary" onclick="saveDailyEdit()">저장</button>
                    </div>
                </div>
            </div>
        `;

        // 기존 모달 제거 후 추가
        const existing = document.getElementById('dailyEditModal');
        if (existing) existing.remove();
        document.body.insertAdjacentHTML('beforeend', modalHtml);

    } catch (e) {
        console.error('계정 정보 조회 실패:', e);
        showToast('계정 정보 조회 실패', 'error');
    }
}

function closeDailyEditModal() {
    const modal = document.getElementById('dailyEditModal');
    if (modal) modal.remove();
    dailyEditTarget = null;
}

async function saveDailyEdit() {
    if (!dailyEditTarget) return;

    const { platform, loginId, market } = dailyEditTarget;
    const isESM = market === '지마켓' || market === '옥션';

    const updateData = {
        platform: platform,
        login_id: loginId,
        password: document.getElementById('editPassword').value
    };

    if (isESM) {
        updateData.esm_id = document.getElementById('editEsmId').value;
        updateData.esm_pw = document.getElementById('editEsmPw').value;
    }

    if (market === '11번가') {
        updateData.api_key = document.getElementById('editApiKey').value;
    }

    try {
        const r = await fetch(`/api/accounts/${encodeURIComponent(platform)}/${encodeURIComponent(loginId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updateData)
        });

        const result = await r.json();
        if (result.success) {
            showToast('계정 정보 저장 완료', 'success');
            closeDailyEditModal();
        } else {
            showToast(result.detail || '저장 실패', 'error');
        }
    } catch (e) {
        console.error('저장 실패:', e);
        showToast('저장 실패', 'error');
    }
}

// 상태 변경 모달
function openStatusModal(row, account, market) {
    dailyStatusTarget = { row, account, market };

    // 현재 상태 가져오기
    const item = dailyData.find(d => d.account === account && d.market === market);
    const currentStatus = item?.status || 'normal';
    const currentNote = item?.note || '';

    document.getElementById('statusModalTarget').textContent = `${account} (${market})`;
    document.getElementById('statusSelect').value = currentStatus;
    document.getElementById('statusNote').value = currentNote;
    document.getElementById('statusModal').style.display = 'flex';
}

function closeStatusModal() {
    document.getElementById('statusModal').style.display = 'none';
    dailyStatusTarget = null;
}

// 상태 저장 (마켓상태현황 API 사용)
async function saveDailyStatus() {
    if (!dailyStatusTarget) return;

    const status = document.getElementById('statusSelect').value;
    const note = document.getElementById('statusNote')?.value?.trim() || '';
    const { account, market } = dailyStatusTarget;

    // 상태값 변환 (영문 → 한글)
    const statusMap = {
        'normal': '정상',
        'caution': '주의',
        'warning': '경고',
        'suspended': '일시정지',
        'stopped': '정지'
    };

    try {
        const r = await fetch('/api/market-status/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                store_name: account,
                platform: market,
                status: statusMap[status] || '정상',
                note: note
            })
        });
        const d = await r.json();

        if (d.success) {
            showToast('상태 저장 완료', 'success');
            closeStatusModal();
            loadDailyStatus(true);  // 강제 새로고침
        } else {
            showToast(d.message || '저장 실패', 'error');
        }
    } catch (e) {
        showToast('저장 오류', 'error');
    }
}

// ========== 클라이언트 프로그램 연동 ==========
let clientConnected = false;

async function checkClientConnection() {
    const statusEl = document.getElementById('clientStatus');
    statusEl.innerHTML = '🔄 연결 확인 중...';
    statusEl.style.background = '#fff3cd';

    try {
        const r = await fetch('/api/client/status', { timeout: 3000 });
        const d = await r.json();

        if (d.connected) {
            clientConnected = true;
            statusEl.innerHTML = '✅ 클라이언트 연결됨';
            statusEl.style.background = '#d4edda';
            statusEl.style.color = '#155724';
            return true;
        } else {
            clientConnected = false;
            statusEl.innerHTML = '❌ 클라이언트 연결 안됨 - 프로그램을 실행하세요';
            statusEl.style.background = '#f8d7da';
            statusEl.style.color = '#721c24';
            return false;
        }
    } catch (e) {
        clientConnected = false;
        statusEl.innerHTML = '❌ 클라이언트 연결 안됨';
        statusEl.style.background = '#f8d7da';
        statusEl.style.color = '#721c24';
        return false;
    }
}

function showClientModal() {
    document.getElementById('clientModal').style.display = 'flex';
    checkClientConnection();
}

function closeClientModal() {
    document.getElementById('clientModal').style.display = 'none';
}

function downloadClient() {
    window.location.href = '/download/PkonomyClient.exe';
}

// PC 제어 기능 실행 전 클라이언트 확인
async function requireClient(callback) {
    // 먼저 연결 확인
    try {
        const r = await fetch('/api/client/status', { timeout: 2000 });
        const d = await r.json();
        if (d.connected) {
            callback();
            return;
        }
    } catch (e) { }

    // 연결 안됨 - 모달 표시
    showClientModal();
}

// ========== 마켓현황 표 ==========
let marketTableData = {};
let currentMarketTab = 'all';

async function loadMarketTable(refresh = false) {
    try {
        // 매출 데이터 로드 (refresh 시 강제 새로고침)
        if (!salesData || refresh) {
            const salesR = await fetch(`/api/sales/from-sheet${refresh ? '?force=true' : ''}`);
            salesData = await salesR.json();
        }

        if (!salesData || !salesData.success || !salesData.data) {
            showToast('매출 데이터 로드 실패', 'error');
            return;
        }

        // 마켓 상태 정보 가져오기 (관제센터와 동일한 데이터)
        let statusMap = {};
        try {
            const statusR = await fetch('/api/market-status');
            const statusD = await statusR.json();
            if (statusD.success && statusD.data) {
                // data는 객체: {"스토어명_플랫폼": {"status": "주의", ...}}
                statusMap = statusD.data;
            }
        } catch (e) {
            console.warn('[마켓현황] 상태 정보 로드 실패:', e);
        }

        // 판매중 수량 + 마지막등록일 가져오기 (등록갯수/11번가 시트)
        let productCounts = {};  // {count, last_reg}
        try {
            const countsR = await fetch(`/api/monitor/product-counts${refresh ? '?refresh=true' : ''}`);
            const countsD = await countsR.json();
            if (countsD.success && countsD.data) {
                productCounts = countsD.data;
                // 디버그: 마지막등록일 있는 항목 확인
                const withLastReg = Object.entries(productCounts).filter(([k, v]) => v && v.last_reg);
                console.log('[마켓현황] productCounts:', Object.keys(productCounts).length, '개, last_reg있음:', withLastReg.length);
                if (withLastReg.length > 0) console.log('[마켓현황] last_reg 샘플:', withLastReg.slice(0, 3));
            }
        } catch (e) {
            console.warn('[마켓현황] 판매중 수량 로드 실패:', e);
        }

        // 경과일 계산 함수
        function calcDaysElapsed(dateStr) {
            if (!dateStr) return null;
            try {
                const regDate = new Date(dateStr);
                const today = new Date();
                const diffTime = today - regDate;
                const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
                return diffDays >= 0 ? diffDays : null;
            } catch {
                return null;
            }
        }

        // salesData.data 그대로 플랫폼별로 그룹화
        // 키: "이모티보이(스마트스토어)" 형식
        marketTableData = {};

        Object.entries(salesData.data).forEach(([key, data]) => {
            // "이모티보이(스마트스토어)" → storeName: 이모티보이, platform: 스마트스토어
            const lastParen = key.lastIndexOf('(');
            if (lastParen === -1) return;

            const storeName = key.substring(0, lastParen);
            const platform = key.substring(lastParen + 1, key.length - 1);

            if (!marketTableData[platform]) {
                marketTableData[platform] = [];
            }

            // 상태 정보 매칭
            const statusKey = `${storeName}_${platform}`;
            const statusInfo = statusMap[statusKey];
            const status = statusInfo ? statusInfo.status : '정상';

            // 판매중 수량 + 마지막등록일 매칭
            const countKey = `${storeName}_${platform}`;
            const countInfo = productCounts[countKey] || {};
            const productCount = typeof countInfo === 'object' ? (countInfo.count || 0) : (countInfo || 0);
            const lastRegDate = typeof countInfo === 'object' ? (countInfo.last_reg || '') : '';
            const daysElapsed = calcDaysElapsed(lastRegDate);

            marketTableData[platform].push({
                스토어명: storeName,  // 한글 키
                platform: platform,
                owner: data.owner || '',
                usage: data.usage || '',
                status: status,
                product_count: productCount,
                last_reg_date: lastRegDate,
                days_since_cleanup: daysElapsed,
                month_sales: data.month_sales || 0,
                month_orders: data.month_orders || 0,
                orders_2w: data.orders_2w || 0,
                month_profit: data.month_profit || 0,
                today_sales: data.today_sales || 0,
                today_orders: data.today_orders || 0
            });
        });

        renderMarketTable();

    } catch (e) {
        console.error('마켓현황 로드 오류:', e);
        showToast('마켓현황 로드 오류', 'error');
    }
}

// 선택된 마켓 플랫폼 목록 (복수 선택)
let selectedMarketPlatforms = new Set(['all']);
let lastClickedMarketIndex = null;  // Shift+클릭용
let marketTabsDragging = false;     // 드래그 선택용

// 마켓탭 플랫폼 순서 (index 기준)
const marketTabOrder = ['all', '11번가', '스마트스토어', '옥션', '지마켓', '쿠팡'];

function toggleMarketTab(platform, event = null) {
    const isCtrl = event && (event.ctrlKey || event.metaKey);
    const isShift = event && event.shiftKey;
    const clickedIndex = marketTabOrder.indexOf(platform);

    if (platform === 'all') {
        // '전체' 클릭 시 - 모든 선택 해제하고 전체만 선택
        selectedMarketPlatforms.clear();
        selectedMarketPlatforms.add('all');
        lastClickedMarketIndex = 0;
    } else if (isShift && lastClickedMarketIndex !== null && lastClickedMarketIndex !== 0) {
        // Shift+클릭: 범위 선택
        const start = Math.min(lastClickedMarketIndex, clickedIndex);
        const end = Math.max(lastClickedMarketIndex, clickedIndex);

        selectedMarketPlatforms.clear();
        for (let i = start; i <= end; i++) {
            if (i > 0) { // 'all' 제외
                selectedMarketPlatforms.add(marketTabOrder[i]);
            }
        }
    } else if (isCtrl) {
        // Ctrl+클릭: 복수 선택 모드
        selectedMarketPlatforms.delete('all');
        if (selectedMarketPlatforms.has(platform)) {
            selectedMarketPlatforms.delete(platform);
            if (selectedMarketPlatforms.size === 0) {
                selectedMarketPlatforms.add('all');
            }
        } else {
            selectedMarketPlatforms.add(platform);
        }
        lastClickedMarketIndex = clickedIndex;
    } else {
        // 일반 클릭: 단일 선택
        selectedMarketPlatforms.clear();
        selectedMarketPlatforms.add(platform);
        lastClickedMarketIndex = clickedIndex;
    }

    updateMarketTabsUI();
    renderMarketTable();
}

// 마켓탭 UI 업데이트 (공통 함수)
function updateMarketTabsUI() {
    document.querySelectorAll('.mt-tab').forEach(tab => {
        const p = tab.dataset.platform;
        tab.classList.toggle('active', selectedMarketPlatforms.has(p));
    });

    // 기존 currentMarketTab 호환성 유지
    if (selectedMarketPlatforms.has('all')) {
        currentMarketTab = 'all';
    } else {
        currentMarketTab = [...selectedMarketPlatforms][0];
    }
}

// 마켓탭 드래그 이벤트 초기화
function initMarketTabEvents() {
    const container = document.getElementById('marketTableTabs');
    if (!container) return;

    const tabs = container.querySelectorAll('.mt-tab');

    // 각 탭에 드래그 이벤트 바인딩
    tabs.forEach(tab => {
        // 드래그 시작
        tab.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return; // 좌클릭만
            marketTabsDragging = true;
            lastClickedMarketIndex = parseInt(tab.dataset.index);
        });

        // 드래그 중 (마우스가 탭 위로 이동)
        tab.addEventListener('mouseenter', (e) => {
            if (!marketTabsDragging) return;

            const platform = tab.dataset.platform;
            if (platform === 'all') return; // 전체는 드래그로 선택 안 함

            selectedMarketPlatforms.delete('all');
            selectedMarketPlatforms.add(platform);
            updateMarketTabsUI();
        });
    });

    // 드래그 종료 (document 레벨)
    document.addEventListener('mouseup', () => {
        if (marketTabsDragging) {
            marketTabsDragging = false;
            if (selectedMarketPlatforms.size === 0) {
                selectedMarketPlatforms.add('all');
                updateMarketTabsUI();
            }
            renderMarketTable();
        }
    });
}

// 페이지 로드 시 초기화 (이미 로드된 경우도 처리)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        initMarketTabEvents();
    });
} else {
    // 이미 DOM이 로드된 경우 바로 실행
    initMarketTabEvents();
}

function switchMarketTab(platform) {
    currentMarketTab = platform;

    // 탭 버튼 활성화
    document.querySelectorAll('.mt-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.platform === platform);
    });

    renderMarketTable();
}

// 마켓현황 필터
function filterMarketTable() {
    renderMarketTable();
}

// 상태 클릭 필터 (정상/주의/경고/정지)
function filterByStatus(status) {
    const filterInput = document.getElementById('filterStatus');
    if (filterInput) {
        filterInput.value = status;
        filterMarketTable();
    }
}

// 필터 드롭다운 표시
function showFilterDropdown(type) {
    // 다른 드롭다운 닫기
    document.querySelectorAll('.filter-dropdown.show').forEach(d => d.classList.remove('show'));

    const dropdown = document.getElementById('dropdown-' + type);
    if (dropdown) {
        dropdown.classList.add('show');
    }
}

// 필터 드롭다운 항목 선택
function selectFilterItem(type, value) {
    const input = document.getElementById('filter' + type.charAt(0).toUpperCase() + type.slice(1));
    if (input) {
        // 기존 값이 있으면 쉼표로 추가, 없으면 새로 설정
        const currentVal = input.value.trim();
        if (currentVal) {
            // 이미 포함되어 있는지 확인
            const terms = currentVal.split(',').map(s => s.trim());
            if (!terms.includes(value)) {
                input.value = currentVal + ',' + value;
            }
        } else {
            input.value = value;
        }
        filterMarketTable();
    }
    // 드롭다운 닫기
    const dropdown = document.getElementById('dropdown-' + type);
    if (dropdown) dropdown.classList.remove('show');
}

// 드롭다운 외부 클릭 시 닫기
document.addEventListener('click', (e) => {
    if (!e.target.closest('.filter-combo')) {
        document.querySelectorAll('.filter-dropdown.show').forEach(d => d.classList.remove('show'));
    }
});

// 마켓현황 정렬 상태
let marketSortField = 'product_count';
let marketSortDir = 'desc';

// 마켓현황 정렬
function sortMarketTable(field) {
    if (marketSortField === field) {
        // 같은 필드 클릭 시 방향 토글
        marketSortDir = marketSortDir === 'desc' ? 'asc' : 'desc';
    } else {
        marketSortField = field;
        marketSortDir = 'desc';
    }
    renderMarketTable();
}

function renderMarketTable() {
    const tbody = document.getElementById('marketTableBody');

    // 데이터 필터링
    let allData = [];

    if (selectedMarketPlatforms.has('all')) {
        // 전체
        for (const platform in marketTableData) {
            marketTableData[platform].forEach(item => {
                allData.push({ ...item, platform });
            });
        }
    } else {
        // 선택된 플랫폼들만
        for (const platform of selectedMarketPlatforms) {
            const items = marketTableData[platform] || [];
            items.forEach(item => {
                allData.push({ ...item, platform });
            });
        }
    }

    // 소유자/용도 드롭다운 동적 생성
    const owners = new Set();
    const usages = new Set();
    allData.forEach(item => {
        if (item.owner) owners.add(item.owner);
        if (item.usage) usages.add(item.usage);
    });

    const ownerDropdown = document.getElementById('dropdown-owner');
    if (ownerDropdown) {
        ownerDropdown.innerHTML = Array.from(owners).sort().map(o =>
            `<div class="filter-dropdown-item" onclick="selectFilterItem('owner','${o}')">${o}</div>`
        ).join('');
    }

    const usageDropdown = document.getElementById('dropdown-usage');
    if (usageDropdown) {
        usageDropdown.innerHTML = Array.from(usages).sort().map(u =>
            `<div class="filter-dropdown-item" onclick="selectFilterItem('usage','${u}')">${u}</div>`
        ).join('');
    }

    // 필터 적용 (쉼표로 복수 검색 지원)
    const searchText = (document.getElementById('filterMarketName')?.value || '').toLowerCase();
    const statusFilter = (document.getElementById('filterStatus')?.value || '').toLowerCase();
    const ownerFilter = (document.getElementById('filterOwner')?.value || '').toLowerCase();
    const usageFilter = (document.getElementById('filterUsage')?.value || '').toLowerCase();
    const daysFilter = (document.getElementById('filterDaysElapsed')?.value || '').trim();

    // 쉼표로 분리하여 배열로 변환
    const statusTerms = statusFilter.split(',').map(s => s.trim()).filter(s => s);
    const ownerTerms = ownerFilter.split(',').map(s => s.trim()).filter(s => s);
    const usageTerms = usageFilter.split(',').map(s => s.trim()).filter(s => s);

    // 경과일 필터 파싱 (예: "30+", "60-", "30")
    let daysFilterFn = null;
    if (daysFilter) {
        if (daysFilter.endsWith('+')) {
            const threshold = parseInt(daysFilter.slice(0, -1));
            if (!isNaN(threshold)) daysFilterFn = (d) => d !== null && d > threshold;
        } else if (daysFilter.endsWith('-')) {
            const threshold = parseInt(daysFilter.slice(0, -1));
            if (!isNaN(threshold)) daysFilterFn = (d) => d !== null && d <= threshold;
        } else {
            const exact = parseInt(daysFilter);
            if (!isNaN(exact)) daysFilterFn = (d) => d !== null && d === exact;
        }
    }

    allData = allData.filter(item => {
        // 마켓명 검색
        if (searchText) {
            const name = (item.스토어명 || item.login_id || '').toLowerCase();
            if (!name.includes(searchText)) {
                return false;
            }
        }
        // 상태 검색 (복수 지원, 정지는 일시정지도 포함)
        if (statusTerms.length > 0) {
            const itemStatus = (item.status || '').toLowerCase();
            const matched = statusTerms.some(term => {
                if (term === '정지') {
                    return itemStatus === '정지' || itemStatus === '일시정지';
                }
                return itemStatus.includes(term);
            });
            if (!matched) return false;
        }
        // 소유자 검색 (복수 지원)
        if (ownerTerms.length > 0) {
            const itemOwner = (item.owner || '').toLowerCase();
            const matched = ownerTerms.some(term => itemOwner.includes(term));
            if (!matched) return false;
        }
        // 용도 검색 (복수 지원)
        if (usageTerms.length > 0) {
            const itemUsage = (item.usage || '').toLowerCase();
            const matched = usageTerms.some(term => itemUsage.includes(term));
            if (!matched) return false;
        }
        // 경과일 필터
        if (daysFilterFn && !daysFilterFn(item.days_since_cleanup)) {
            return false;
        }
        return true;
    });

    // 정렬 적용
    allData.sort((a, b) => {
        const aVal = a[marketSortField] || 0;
        const bVal = b[marketSortField] || 0;
        return marketSortDir === 'desc' ? (bVal - aVal) : (aVal - bVal);
    });

    // 요약 정보 계산
    let sumTotal = allData.length;
    let sumNormal = 0, sumCaution = 0, sumWarning = 0, sumSuspend = 0;
    let sumProducts = 0;

    allData.forEach(item => {
        const status = item.status || '정상';
        if (status === '정상') sumNormal++;
        else if (status === '주의') sumCaution++;
        else if (status === '경고') sumWarning++;
        else if (status === '정지' || status === '일시정지') sumSuspend++;

        sumProducts += (item.product_count || 0);
    });

    // 요약 업데이트
    document.getElementById('sumTotal').textContent = sumTotal;
    document.getElementById('sumNormal').textContent = sumNormal;
    document.getElementById('sumCaution').textContent = sumCaution;
    document.getElementById('sumWarning').textContent = sumWarning;
    document.getElementById('sumSuspend').textContent = sumSuspend;
    document.getElementById('sumProducts').textContent = sumProducts.toLocaleString();

    // 테이블 렌더링
    if (allData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="loading">데이터 없음</td></tr>';
        return;
    }

    tbody.innerHTML = allData.map((item, idx) => {
        const status = item.status || '정상';
        const productCount = item.product_count || 0;
        const monthSales = item.month_sales || 0;
        const monthProfit = item.month_profit || 0;
        const monthOrders = item.month_orders || 0;
        const orders2w = item.orders_2w || 0;
        const usage = item.usage || '';
        const platformColor = platformColors[item.platform] || '#666';

        // 상품갈이 대상 판단
        // 대량: 14일간 주문 0건
        // 반대량: 월 매출 100만원 이하
        let needRefresh = false;
        let refreshReason = '';
        if (usage.includes('대량') && orders2w === 0) {
            needRefresh = true;
            refreshReason = '주문없음';
        } else if (usage.includes('반대량') && monthSales < 1000000) {
            needRefresh = true;
            refreshReason = '100만↓';
        }

        // 플랫폼별 아이콘
        const platformIcons = {
            '스마트스토어': 'N',
            '11번가': '11',
            '쿠팡': 'C',
            '지마켓': 'G',
            '옥션': 'A'
        };
        const platformIcon = platformIcons[item.platform] || 'P';

        // 매출 포맷팅 (만원 단위, 소수점 1자리)
        const formatSales = (v) => {
            if (v >= 10000) return (v / 10000).toFixed(1) + '만';
            if (v > 0) return v.toLocaleString();
            return '-';
        };

        const rowStyle = needRefresh ? 'background: #fff3e0;' : '';

        // 지마켓/옥션은 판매중 수량 수동 입력 가능
        const isGmarketAuction = item.platform === '지마켓' || item.platform === '옥션';
        const productCountCell = isGmarketAuction
            ? `<input type="number" class="product-count-input" value="${productCount}"
                data-store="${item.스토어명}" data-platform="${item.platform}"
                onchange="updateProductCount(this)"
                style="width:60px; text-align:right; border:1px solid #ddd; border-radius:4px; padding:2px 4px;">`
            : `${productCount.toLocaleString()}`;

        // 경과일 표시 (색상: 30일 이하 녹색, 60일 이하 주황, 60일 초과 빨강)
        const daysElapsed = item.days_since_cleanup;
        let daysElapsedCell = '-';
        let daysColor = '';
        if (daysElapsed !== null && daysElapsed !== undefined) {
            if (daysElapsed <= 30) daysColor = 'color:#4caf50;';
            else if (daysElapsed <= 60) daysColor = 'color:#ff9800;';
            else daysColor = 'color:#f44336;font-weight:bold;';
            daysElapsedCell = `<span style="${daysColor}">${daysElapsed}일</span>`;
        }

        return `
            <tr style="${rowStyle}">
                <td><input type="checkbox" class="market-row-cb" data-store="${item.스토어명 || item.login_id}" data-platform="${item.platform}"></td>
                <td>${idx + 1}</td>
                <td><span class="platform-badge" style="background:${platformColor}"><b>${platformIcon}</b></span></td>
                <td><strong>${item.스토어명 || item.login_id}</strong>${needRefresh ? ` <span style="color:#e65100;font-size:11px;">🔄${refreshReason}</span>` : ''}</td>
                <td><span class="status-badge status-${status}">${status}</span></td>
                <td class="count-cell ${productCount > 0 ? 'has-value' : ''}">${productCountCell}</td>
                <td class="count-cell" style="text-align:center;">${daysElapsedCell}</td>
                <td class="count-cell ${monthSales > 0 ? 'has-value' : ''}">${formatSales(monthSales)}</td>
                <td class="count-cell ${monthProfit > 0 ? 'has-value' : ''}">${formatSales(monthProfit)}</td>
                <td class="count-cell ${monthOrders > 0 ? 'has-value' : ''}">${monthOrders || '-'}</td>
                <td class="count-cell ${orders2w > 0 ? 'has-value' : ''}">${orders2w || '-'}</td>
                <td>${item.owner || '-'}</td>
                <td>${usage || '-'}</td>
            </tr>
        `;
    }).join('');

    // 테이블 렌더링 후 복수 선택 이벤트 바인딩
    bindMarketRowSelection();
}

// 마켓 전체 선택
function toggleAllMarketRows(mainCb) {
    const cbs = document.querySelectorAll('.market-row-cb');
    cbs.forEach(cb => cb.checked = mainCb.checked);
}

// 마켓 행 Shift+클릭/드래그 선택
let lastMarketRowIndex = null;
let marketRowDragging = false;
let marketRowDragStartIndex = null;
let marketRowEventsInitialized = false;

function bindMarketRowSelection() {
    const tbody = document.getElementById('marketTableBody');
    if (!tbody) return;

    if (marketRowEventsInitialized) return;
    marketRowEventsInitialized = true;

    // 체크박스 클릭 이벤트 (Shift+클릭 범위 선택)
    tbody.addEventListener('click', (e) => {
        const target = e.target;
        if (target.type !== 'checkbox' || !target.classList.contains('market-row-cb')) return;

        const cbs = Array.from(tbody.querySelectorAll('.market-row-cb'));
        const clickedIndex = cbs.indexOf(target);

        if (e.shiftKey && lastMarketRowIndex !== null && lastMarketRowIndex !== clickedIndex) {
            // Shift+클릭: 범위 선택
            const start = Math.min(lastMarketRowIndex, clickedIndex);
            const end = Math.max(lastMarketRowIndex, clickedIndex);
            const shouldCheck = target.checked;

            for (let i = start; i <= end; i++) {
                cbs[i].checked = shouldCheck;
            }
            // Shift 클릭 시에는 lastIndex 유지 (연속 범위 선택 가능)
        } else {
            // 일반 클릭 시에만 lastIndex 업데이트
            lastMarketRowIndex = clickedIndex;
        }
    });

    // 드래그 선택
    tbody.addEventListener('mousedown', (e) => {
        if (e.target.type !== 'checkbox' || !e.target.classList.contains('market-row-cb')) return;
        if (e.button !== 0) return;

        const cbs = Array.from(tbody.querySelectorAll('.market-row-cb'));
        marketRowDragStartIndex = cbs.indexOf(e.target);
        marketRowDragging = true;
    });

    tbody.addEventListener('mouseover', (e) => {
        if (!marketRowDragging) return;
        if (e.target.type !== 'checkbox' || !e.target.classList.contains('market-row-cb')) return;

        const cbs = Array.from(tbody.querySelectorAll('.market-row-cb'));
        const currentIndex = cbs.indexOf(e.target);
        const shouldCheck = cbs[marketRowDragStartIndex]?.checked ?? true;

        const start = Math.min(marketRowDragStartIndex, currentIndex);
        const end = Math.max(marketRowDragStartIndex, currentIndex);
        for (let i = start; i <= end; i++) {
            cbs[i].checked = shouldCheck;
        }
    });

    document.addEventListener('mouseup', () => {
        marketRowDragging = false;
    });

    console.log('[마켓현황] 복수 선택 이벤트 바인딩 완료');
}

// 선택된 계정을 올인원 탭으로 전달
async function sendSelectedToAio() {
    const selected = [];
    document.querySelectorAll('.market-row-cb:checked').forEach(cb => {
        selected.push({
            store: cb.dataset.store,
            platform: cb.dataset.platform
        });
    });

    if (selected.length === 0) {
        showToast('전달할 마켓을 먼저 선택해주세요.', 'warning');
        return;
    }

    if (!confirm(`${selected.length}개 계정을 올인원으로 전달하시겠습니까?`)) {
        return;
    }

    // 올인원 전역 변수에 선택 정보 설정
    // aioSelectedStores는 Set이거나 배열일 수 있음. updateAioStoreCount가 있는 것으로 보아 관리되는 변수가 있음.
    // 기존 코드 확인 결과 aioSelectedStores = new Set() 임.

    // 플랫폼이 첫 번째 선택 항목의 플랫폼으로 설정되도록 함 (올인원은 한 번에 한 플랫폼만 처리 가능하므로)
    const firstPlatform = selected[0].platform;

    // 플랫폼이 다른 항목이 있는지 확인
    const otherPlatforms = selected.filter(s => s.platform !== firstPlatform);
    if (otherPlatforms.length > 0) {
        if (!confirm(`선택된 계정에 여러 플랫폼이 섞여 있습니다.\n[${firstPlatform}] 계정들만 전달할까요?`)) {
            return;
        }
    }

    const targetStores = selected.filter(s => s.platform === firstPlatform).map(s => s.store);

    // 탭 이동 및 정보 설정
    // app.js의 goToDailyAioTask 로직 참고
    aioPendingSelection = {
        platform: firstPlatform,
        stores: targetStores,
        task: '등록갯수' // 기본 작업
    };

    // 탭 이동
    const aioTab = document.querySelector('.tab[data-tab="aio"]');
    if (aioTab) aioTab.click();

    showToast(`${targetStores.length}개 계정이 전달되었습니다.`, 'success');
}

// 마켓 현황 엑셀 출력
async function exportMarketTable() {
    showToast('엑셀 생성 중...', 'info');

    try {
        // 현재 화면에 보이는(필터링된) 데이터 수집
        const rows = [];
        const table = document.getElementById('marketTable');
        const headers = [];
        table.querySelectorAll('thead th').forEach((th, idx) => {
            if (idx === 0) return; // 체크박스 제외
            headers.push(th.innerText.replace(' ↕', '').replace(' ▼', '').trim());
        });

        const dataRows = [];
        table.querySelectorAll('tbody tr').forEach(tr => {
            const rowData = [];
            tr.querySelectorAll('td').forEach((td, idx) => {
                if (idx === 0) return; // 체크박스 제외
                // input 태그(판매중 수량) 처리
                const input = td.querySelector('input');
                if (input) {
                    rowData.push(input.value);
                } else {
                    rowData.push(td.innerText.split('\n')[0].trim()); // Badge 등 제외
                }
            });
            dataRows.push(rowData);
        });

        const r = await fetch('/api/market-table/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                headers: headers,
                data: dataRows
            })
        });

        if (r.ok) {
            const blob = await r.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            const now = new Date().toISOString().slice(0, 10);
            a.download = `마켓현황_${now}.xlsx`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            showToast('엑셀 다운로드 완료', 'success');
        } else {
            const d = await r.json();
            showToast('엑셀 생성 실패: ' + (d.message || '오류'), 'danger');
        }
    } catch (e) {
        console.error('엑셀 출력 오류:', e);
        showToast('엑셀 출력 오류: ' + e.message, 'danger');
    }
}

async function refresh11stCounts() {
    // 확인 다이얼로그
    if (!confirm('11번가 상품수를 갱신하시겠습니까?\n\nAll-in-One 등록갯수 작업을 실행합니다.')) {
        return;
    }

    showToast('11번가 등록갯수 조회 시작...', 'info');

    try {
        // All-in-One 11번가 등록갯수 API 호출
        const r = await fetch('/api/allinone/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                platform: '11번가',
                task: '등록갯수'
            })
        });
        const d = await r.json();

        if (d.success) {
            showToast('11번가 등록갯수 조회 시작됨 (백그라운드 진행)', 'success');

            // 진행상황 폴링 (30초간)
            let pollCount = 0;
            const pollInterval = setInterval(async () => {
                pollCount++;
                try {
                    const statusR = await fetch('/api/allinone/status?platform=11번가');
                    const statusD = await statusR.json();

                    if (!statusD.running || pollCount >= 30) {
                        clearInterval(pollInterval);
                        if (statusD.status === 'completed') {
                            showToast('11번가 등록갯수 조회 완료', 'success');
                        }
                        // 테이블 새로고침
                        await loadMarketTable();
                    }
                } catch (e) {
                    clearInterval(pollInterval);
                }
            }, 1000);
        } else {
            showToast(d.message || '11번가 등록갯수 시작 실패', 'error');
        }
    } catch (e) {
        console.error('11번가 등록갯수 오류:', e);
        showToast('11번가 등록갯수 오류', 'error');
    }
}

// 탭 전환 시 마켓현황 로드
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            if (tab.dataset.tab === 'market-table') {
                loadMarketTable();
            }
        });
    });

    // 배송조회 월 기본값 설정
    const now = new Date();
    const currentMonth = (now.getMonth() + 1) + '월';
    const deliveryMonthSelect = document.getElementById('deliveryMonth');
    if (deliveryMonthSelect) {
        deliveryMonthSelect.value = currentMonth;
    }
});

// ========== 배송조회 기능 ==========

let deliveryCheckInterval = null;

function saveDeliverySheetUrl() {
    const url = document.getElementById('deliverySheetUrl').value;
    localStorage.setItem('deliverySheetUrl', url);
    showToast('시트 URL 저장됨', 'success');
}

// 페이지 로드 시 저장된 URL 복원
document.addEventListener('DOMContentLoaded', () => {
    const savedUrl = localStorage.getItem('deliverySheetUrl');
    if (savedUrl) {
        const input = document.getElementById('deliverySheetUrl');
        if (input) input.value = savedUrl;
    }
});

function extractSheetId(url) {
    // URL에서 시트 ID 추출
    const match = url.match(/\/d\/([a-zA-Z0-9-_]+)/);
    if (match) return match[1];
    // 이미 ID인 경우
    if (/^[a-zA-Z0-9-_]+$/.test(url)) return url;
    return null;
}

async function startDeliveryCheck() {
    const sheetUrl = document.getElementById('deliverySheetUrl').value;
    const sheetName = document.getElementById('deliveryMonth').value;
    const carrierCol = parseInt(document.getElementById('deliveryCarrierCol').value) || 43;
    const trackingCol = parseInt(document.getElementById('deliveryTrackingCol').value) || 44;

    const sheetId = extractSheetId(sheetUrl);
    if (!sheetId) {
        showToast('올바른 시트 URL을 입력하세요', 'error');
        return;
    }

    try {
        const r = await fetch('/api/delivery/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sheet_id: sheetId,
                sheet_name: sheetName,
                carrier_col: carrierCol,
                tracking_col: trackingCol,
                start_row: 4
            })
        });

        const data = await r.json();
        if (data.success) {
            showToast('배송조회 시작', 'success');
            document.getElementById('deliveryStartBtn').disabled = true;
            document.getElementById('deliveryStopBtn').disabled = false;
            updateDeliveryStatus('running', '조회 중...');

            // 상태 폴링 시작
            deliveryCheckInterval = setInterval(pollDeliveryStatus, 1000);
        } else {
            showToast(data.message || '시작 실패', 'error');
        }
    } catch (e) {
        console.error('배송조회 시작 오류:', e);
        showToast('배송조회 시작 오류', 'error');
    }
}

async function stopDeliveryCheck() {
    try {
        await fetch('/api/delivery/stop', { method: 'POST' });
        showToast('중지 요청됨', 'info');
    } catch (e) {
        console.error('중지 오류:', e);
    }
}

async function pollDeliveryStatus() {
    try {
        const r = await fetch('/api/delivery/status');
        const data = await r.json();

        // 로그 업데이트
        const logContent = document.getElementById('deliveryLogContent');
        if (logContent && data.logs) {
            logContent.innerHTML = data.logs.map(log => `<div>${log}</div>`).join('');
            logContent.scrollTop = logContent.scrollHeight;
        }

        // 진행상황 업데이트
        if (data.total > 0) {
            updateDeliveryStatus('running', `${data.progress} / ${data.total} (배송중: ${data.updated}건)`);
        }

        // 완료 체크
        if (!data.running) {
            clearInterval(deliveryCheckInterval);
            deliveryCheckInterval = null;
            document.getElementById('deliveryStartBtn').disabled = false;
            document.getElementById('deliveryStopBtn').disabled = true;
            updateDeliveryStatus('ready', `완료! 배송중: ${data.updated}건`);
        }
    } catch (e) {
        console.error('상태 조회 오류:', e);
    }
}

function updateDeliveryStatus(status, text) {
    const statusEl = document.getElementById('deliveryStatus');
    if (!statusEl) return;

    const dot = statusEl.querySelector('.status-dot');
    const textEl = statusEl.querySelector('.status-text');

    dot.className = 'status-dot';
    if (status === 'running') dot.classList.add('running');
    else if (status === 'ready') dot.classList.add('ready');

    textEl.textContent = text;
}

// ==================== 스케줄러 ====================
let scheduleList = [];

async function loadSchedules() {
    try {
        const res = await fetchAPI('/api/schedules');
        scheduleList = res.schedules || [];
        renderScheduleTable();
    } catch (e) {
        console.error('스케줄 로드 오류:', e);
    }
}

function renderScheduleTable() {
    const tbody = document.getElementById('scheduleTableBody');
    if (!tbody) return;

    if (scheduleList.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty">등록된 스케줄이 없습니다</td></tr>';
        return;
    }

    tbody.innerHTML = scheduleList.map(s => {
        const statusClass = s.enabled ? 'active' : 'inactive';
        const statusText = s.enabled ? '활성' : '비활성';
        const cronText = s.schedule_type === 'cron' ? s.cron : `${s.interval_minutes}분 간격`;

        return `
            <tr>
                <td><span class="status-badge ${statusClass}">${statusText}</span></td>
                <td><a href="#" onclick="showScheduleDetail('${s.id}'); return false;" style="color: #2196F3; text-decoration: underline; cursor: pointer;">${s.name}</a></td>
                <td>${s.platform}</td>
                <td><a href="#" onclick="showScheduleDetail('${s.id}'); return false;" style="color: #667eea; text-decoration: underline; cursor: pointer;">${s.task}</a></td>
                <td>${cronText}</td>
                <td>${s.next_run || '-'}</td>
                <td>${s.last_run || '-'}</td>
                <td>${s.run_count || 0}</td>
                <td class="action-btns">
                    <button class="action-btn run" onclick="runScheduleNow('${s.id}')" title="즉시 실행">▶️</button>
                    <button class="action-btn" onclick="viewScheduleLog('${s.id}', '${s.name}')" title="로그 보기" style="background:#3498db;">📄</button>
                    <button class="action-btn edit" onclick="openEditScheduleModal('${s.id}')" title="수정" style="background:#f39c12;">✏️</button>
                    <button class="action-btn toggle" onclick="toggleSchedule('${s.id}')" title="${s.enabled ? '비활성화' : '활성화'}">${s.enabled ? '⏸️' : '▶️'}</button>
                    <button class="action-btn delete" onclick="deleteSchedule('${s.id}')" title="삭제">🗑️</button>
                </td>
            </tr>
        `;
    }).join('');
}

function toggleSchedInputs() {
    const type = document.getElementById('schedType').value;
    document.getElementById('schedCronGroup').style.display = type === 'cron' ? '' : 'none';
    document.getElementById('schedIntervalGroup').style.display = type === 'interval' ? '' : 'none';
}

function updateSchedTasks() {
    const platform = document.getElementById('schedPlatform').value;
    const taskSelect = document.getElementById('schedTask');

    if (platform === '스마트스토어') {
        taskSelect.innerHTML = `
            <option value="등록갯수">등록갯수</option>
            <option value="배송코드">배송코드</option>
            <option value="배송변경">배송변경</option>
            <option value="상품삭제">상품삭제</option>
            <option value="혜택설정">혜택설정</option>
            <option value="중복삭제">중복삭제</option>
            <option value="KC인증">KC인증</option>
            <option value="기타기능">기타기능</option>
        `;
    } else {
        taskSelect.innerHTML = `
            <option value="등록갯수">판매중</option>
            <option value="판매중지">판매중지</option>
            <option value="판매재개">판매재개</option>
        `;
    }

    // 계정 목록도 로드
    if (typeof loadSchedAccounts === 'function') {
        loadSchedAccounts();
    }
}

// 스케줄 상세 정보 모달
function showScheduleDetail(scheduleId) {
    const schedule = scheduleList.find(s => s.id === scheduleId);
    if (!schedule) {
        showToast('스케줄 정보를 찾을 수 없습니다.', 'error');
        return;
    }

    const cronText = schedule.schedule_type === 'cron' ? schedule.cron : `${schedule.interval_minutes}분 간격`;
    const stores = schedule.stores || [];
    const options = schedule.options || {};

    let detailHtml = `
        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 15px;">
            <h4 style="margin: 0 0 15px 0; color: #333;">📋 기본 정보</h4>
            <table style="width: 100%; border-collapse: collapse;">
                <tr><td style="padding: 8px; color: #666; width: 120px;">스케줄 이름</td><td style="padding: 8px; font-weight: 600;">${schedule.name}</td></tr>
                <tr><td style="padding: 8px; color: #666;">플랫폼</td><td style="padding: 8px;">${schedule.platform}</td></tr>
                <tr><td style="padding: 8px; color: #666;">작업</td><td style="padding: 8px;">${schedule.task}</td></tr>
                <tr><td style="padding: 8px; color: #666;">실행 주기</td><td style="padding: 8px;">${cronText}</td></tr>
                <tr><td style="padding: 8px; color: #666;">상태</td><td style="padding: 8px;"><span style="color: ${schedule.enabled ? '#4caf50' : '#999'};">${schedule.enabled ? '✅ 활성' : '⏸️ 비활성'}</span></td></tr>
                <tr><td style="padding: 8px; color: #666;">실행 횟수</td><td style="padding: 8px;">${schedule.run_count || 0}회</td></tr>
            </table>
        </div>
        <div style="background: #e3f2fd; padding: 15px; border-radius: 8px; margin-bottom: 15px;">
            <h4 style="margin: 0 0 15px 0; color: #1976d2;">🎯 작업 대상</h4>
            ${stores.length > 0 ? `
                <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                    ${stores.map(store => `<span style="background: white; padding: 5px 12px; border-radius: 15px; font-size: 13px;">${store}</span>`).join('')}
                </div>
            ` : '<p style="color: #666; margin: 0;">전체 스토어 (지정되지 않음)</p>'}
        </div>
        <div style="background: #fff3e0; padding: 15px; border-radius: 8px; margin-bottom: 15px;">
            <h4 style="margin: 0 0 15px 0; color: #e65100;">⚙️ 작업 옵션</h4>
            ${Object.keys(options).length > 0 ? `
                <table style="width: 100%; border-collapse: collapse;">
                    ${Object.entries(options).map(([k, v]) => `<tr><td style="padding: 6px; color: #666;">${k}</td><td style="padding: 6px;">${v}</td></tr>`).join('')}
                </table>
            ` : '<p style="color: #666; margin: 0;">추가 옵션 없음</p>'}
        </div>
        <div style="background: #f5f5f5; padding: 15px; border-radius: 8px;">
            <h4 style="margin: 0 0 15px 0; color: #333;">📅 실행 기록</h4>
            <table style="width: 100%; border-collapse: collapse;">
                <tr><td style="padding: 8px; color: #666;">마지막 실행</td><td style="padding: 8px;">${schedule.last_run || '-'}</td></tr>
                <tr><td style="padding: 8px; color: #666;">다음 실행</td><td style="padding: 8px;">${schedule.next_run || '-'}</td></tr>
            </table>
        </div>
    `;

    showModal(`📅 스케줄 상세: ${schedule.name}`, detailHtml);
}

async function createSchedule() {
    const name = document.getElementById('schedName').value.trim();
    if (!name) {
        alert('스케줄 이름을 입력하세요');
        return;
    }

    const schedType = document.getElementById('schedType').value;
    let cron = '0 9 * * *';
    let intervalMinutes = 60;

    if (schedType === 'cron') {
        const min = document.getElementById('schedCronMin').value || '0';
        const hour = document.getElementById('schedCronHour').value || '9';
        const day = document.getElementById('schedCronDay').value || '*';
        const month = document.getElementById('schedCronMonth').value || '*';
        const dow = document.getElementById('schedCronDow').value || '*';
        cron = `${min} ${hour} ${day} ${month} ${dow}`;
    } else {
        intervalMinutes = parseInt(document.getElementById('schedIntervalMin').value) || 60;
    }

    // 선택된 계정 가져오기
    const selectedStores = typeof getSelectedSchedAccounts === 'function' ? getSelectedSchedAccounts() : [];

    // 작업 옵션 가져오기
    const taskOptions = typeof scheduleTaskOptions !== 'undefined' ? { ...scheduleTaskOptions } : {};

    try {
        const res = await fetchAPI('/api/schedules', {
            method: 'POST',
            body: JSON.stringify({
                name: name,
                platform: document.getElementById('schedPlatform').value,
                task: document.getElementById('schedTask').value,
                stores: selectedStores,
                schedule_type: schedType,
                cron: cron,
                interval_minutes: intervalMinutes,
                options: taskOptions,
                enabled: true
            })
        });

        if (res.success) {
            alert(`스케줄이 추가되었습니다 (대상: ${selectedStores.length}개 계정)`);
            document.getElementById('schedName').value = '';
            // 선택 계정 초기화
            if (typeof schedMoveAllLeft === 'function') {
                schedMoveAllLeft();
            }
            loadSchedules();
        }
    } catch (e) {
        alert('스케줄 추가 실패: ' + e.message);
    }
}

async function runScheduleNow(scheduleId) {
    if (!confirm('이 스케줄을 즉시 실행하시겠습니까?')) return;

    try {
        await fetchAPI(`/api/schedules/${scheduleId}/run`, { method: 'POST' });
        alert('작업이 시작되었습니다');
    } catch (e) {
        alert('실행 실패: ' + e.message);
    }
}

async function viewScheduleLog(scheduleId, scheduleName) {
    try {
        const res = await fetchAPI(`/api/schedules/${scheduleId}/log?lines=200`);

        // 모달 생성
        let modal = document.getElementById('scheduleLogModal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'scheduleLogModal';
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content" style="max-width: 900px; max-height: 80vh;">
                    <div class="modal-header">
                        <span class="modal-title" id="scheduleLogTitle">스케줄 로그</span>
                        <span class="modal-close" onclick="closeScheduleLogModal()">&times;</span>
                    </div>
                    <div class="modal-body" style="padding: 0;">
                        <div id="scheduleLogInfo" style="padding: 10px 15px; background: #f5f5f5; border-bottom: 1px solid #ddd; font-size: 12px; color: #666;"></div>
                        <pre id="scheduleLogContent" style="margin: 0; padding: 15px; max-height: 500px; overflow: auto; background: #1e1e1e; color: #d4d4d4; font-size: 12px; line-height: 1.5;"></pre>
                    </div>
                    <div class="modal-footer">
                        <button class="btn" onclick="refreshScheduleLog('${scheduleId}', '${scheduleName}')">🔄 새로고침</button>
                        <button class="btn secondary" onclick="closeScheduleLogModal()">닫기</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }

        // 제목 업데이트
        document.getElementById('scheduleLogTitle').textContent = `📄 ${scheduleName} 로그`;

        // 로그 내용 표시
        if (res.success) {
            document.getElementById('scheduleLogInfo').innerHTML = `
                총 ${res.total_lines}줄 | 파일 크기: ${(res.file_size / 1024).toFixed(1)}KB | 마지막 수정: ${res.modified_at}
            `;
            document.getElementById('scheduleLogContent').textContent = res.log || '(로그 내용 없음)';
        } else {
            document.getElementById('scheduleLogInfo').textContent = res.message || '로그를 불러올 수 없습니다';
            document.getElementById('scheduleLogContent').textContent = '';
        }

        // 새로고침 버튼 업데이트
        modal.querySelector('.modal-footer .btn').onclick = () => refreshScheduleLog(scheduleId, scheduleName);

        modal.style.display = 'flex';

        // 로그 맨 아래로 스크롤
        const logContent = document.getElementById('scheduleLogContent');
        logContent.scrollTop = logContent.scrollHeight;

    } catch (e) {
        alert('로그 조회 실패: ' + e.message);
    }
}

async function refreshScheduleLog(scheduleId, scheduleName) {
    await viewScheduleLog(scheduleId, scheduleName);
    showToast('로그 새로고침 완료', 'success');
}

function closeScheduleLogModal() {
    const modal = document.getElementById('scheduleLogModal');
    if (modal) modal.style.display = 'none';
}

async function toggleSchedule(scheduleId) {
    try {
        const res = await fetchAPI(`/api/schedules/${scheduleId}/toggle`, { method: 'POST' });
        if (res.success) {
            loadSchedules();
        }
    } catch (e) {
        alert('상태 변경 실패: ' + e.message);
    }
}

async function deleteSchedule(scheduleId) {
    if (!confirm('이 스케줄을 삭제하시겠습니까?')) return;

    try {
        await fetchAPI(`/api/schedules/${scheduleId}`, { method: 'DELETE' });
        loadSchedules();
    } catch (e) {
        alert('삭제 실패: ' + e.message);
    }
}

// ========== 매출현황 ==========
let salesData = null;
let salesSortField = 'profit';
let salesSortDir = 'desc';
let dailySalesChart = null;
let dailyProfitChart = null;

async function loadSalesData(force = false) {
    try {
        const r = await fetch(`/api/sales/from-sheet?force=${force}`);
        const d = await r.json();

        if (!d.success) {
            showToast('매출 데이터 로드 실패', 'error');
            return;
        }

        salesData = d;
        renderSalesSummary();
        renderSalesTable();
        renderDailySalesTable();
        renderSalesCharts();
        renderPlatformStats();
        loadTop20Products();

        showToast('매출 데이터 로드 완료', 'success');
    } catch (e) {
        console.error('매출 데이터 로드 오류:', e);
        showToast('매출 데이터 로드 오류', 'error');
    }
}

function formatMoney(v) {
    if (v >= 100000000) return (v / 100000000).toFixed(1) + '억';
    if (v >= 10000) return (v / 10000).toFixed(1) + '만';
    if (v > 0) return v.toLocaleString();
    return '0';
}

function renderSalesSummary() {
    if (!salesData || !salesData.total) return;

    const t = salesData.total;
    document.getElementById('totalSales').textContent = formatMoney(t.sales) + '원';
    document.getElementById('totalSettlement').textContent = formatMoney(t.settlement) + '원';
    document.getElementById('totalCost').textContent = formatMoney(t.purchase + t.shipping) + '원';
    document.getElementById('totalProfit').textContent = formatMoney(t.profit) + '원';
    document.getElementById('totalProfitRate').textContent = t.profit_rate + '%';
}

function renderSalesTable() {
    if (!salesData || !salesData.data) return;

    const tbody = document.getElementById('salesTableBody');
    const countEl = document.getElementById('marketCount');

    // 데이터 배열로 변환
    let items = Object.entries(salesData.data).map(([id, data]) => ({
        name: id,
        orders: data.month_orders || 0,
        orders_2w: data.orders_2w || 0,
        sales: data.month_sales || 0,
        settlement: data.month_settlement || 0,
        purchase: data.month_purchase || 0,
        shipping: data.month_shipping || 0,
        profit: data.month_profit || 0,
        profit_rate: data.month_sales > 0 ? (data.month_profit / data.month_sales * 100) : 0,
        usage: data.usage || '',
        owner: data.owner || ''
    }));

    // 마켓 카운트 표시
    if (countEl) {
        countEl.textContent = `(총 ${items.length}개 계정)`;
    }

    // 정렬
    items.sort((a, b) => {
        let va = a[salesSortField];
        let vb = b[salesSortField];
        if (typeof va === 'string') {
            return salesSortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
        }
        return salesSortDir === 'asc' ? va - vb : vb - va;
    });

    if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="loading">데이터 없음</td></tr>';
        return;
    }

    tbody.innerHTML = items.map((item, idx) => `
        <tr>
            <td>${idx + 1}</td>
            <td style="text-align:left;"><strong>${item.name}</strong></td>
            <td>${item.orders}</td>
            <td>${item.orders_2w}</td>
            <td>${formatMoney(item.sales)}</td>
            <td>${formatMoney(item.settlement)}</td>
            <td>${formatMoney(item.purchase)}</td>
            <td>${formatMoney(item.shipping)}</td>
            <td class="${item.profit >= 0 ? 'positive' : 'negative'}">${formatMoney(item.profit)}</td>
            <td class="${item.profit_rate >= 30 ? 'positive' : item.profit_rate < 20 ? 'negative' : ''}">${item.profit_rate.toFixed(1)}%</td>
        </tr>
    `).join('');

    // 소유자별/용도별 매출 렌더링
    renderOwnerSalesTable(items);
    renderUsageSalesTable(items);
    renderBizSalesTable();
}

// 사업자번호별 매출 테이블 (부가세 신고용)
function renderBizSalesTable() {
    const tbody = document.getElementById('bizSalesTableBody');
    if (!tbody || !salesData || !salesData.biz_sales) {
        if (tbody) tbody.innerHTML = '<tr><td colspan="7">사업자번호 데이터 없음</td></tr>';
        return;
    }

    const bizData = salesData.biz_sales;
    let items = Object.entries(bizData)
        .map(([bizNum, data]) => ({
            biz_number: bizNum,
            stores: data.stores || [],
            orders: data.orders || 0,
            sales: data.sales || 0,
            settlement: data.settlement || 0,
            profit: data.profit || 0
        }));

    // 정렬 적용
    items.sort((a, b) => {
        let va = a[bizSortField];
        let vb = b[bizSortField];
        if (typeof va === 'string') {
            return bizSortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
        }
        return bizSortDir === 'asc' ? va - vb : vb - va;
    });

    if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7">데이터 없음</td></tr>';
        return;
    }

    tbody.innerHTML = items.map((item, idx) => `
        <tr>
            <td>${idx + 1}</td>
            <td><strong>${item.biz_number}</strong></td>
            <td style="text-align:left;font-size:11px;">${item.stores.slice(0, 5).join(', ')}${item.stores.length > 5 ? '...' : ''}</td>
            <td>${item.orders}</td>
            <td>${formatMoney(item.sales)}</td>
            <td>${formatMoney(item.settlement)}</td>
            <td class="${item.profit >= 0 ? 'positive' : 'negative'}">${formatMoney(item.profit)}</td>
        </tr>
    `).join('');
}

function sortSalesTable(field) {
    console.log('[정렬] 필드:', field, '현재:', salesSortField, salesSortDir);
    if (salesSortField === field) {
        salesSortDir = salesSortDir === 'desc' ? 'asc' : 'desc';
    } else {
        salesSortField = field;
        salesSortDir = 'desc';
    }
    console.log('[정렬] 변경 후:', salesSortField, salesSortDir);
    renderSalesTable();
}
// 전역 등록
window.sortSalesTable = sortSalesTable;

// 사업자번호별 테이블 정렬
let bizSortField = 'sales';
let bizSortDir = 'desc';

function sortBizTable(field) {
    if (bizSortField === field) {
        bizSortDir = bizSortDir === 'desc' ? 'asc' : 'desc';
    } else {
        bizSortField = field;
        bizSortDir = 'desc';
    }
    renderBizSalesTable();
}
window.sortBizTable = sortBizTable;

// 일별 테이블 정렬
let dailySortField = 'date';
let dailySortDir = 'desc';

function sortDailyTable(field) {
    if (dailySortField === field) {
        dailySortDir = dailySortDir === 'desc' ? 'asc' : 'desc';
    } else {
        dailySortField = field;
        dailySortDir = 'desc';
    }
    renderDailySalesTable();
}
window.sortDailyTable = sortDailyTable;

function renderDailySalesTable() {
    if (!salesData || !salesData.daily) return;

    const tbody = document.getElementById('dailySalesTableBody');
    let items = [...salesData.daily]; // 복사본

    if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="loading">데이터 없음</td></tr>';
        return;
    }

    // 정렬 적용
    items.sort((a, b) => {
        let va = dailySortField === 'profit_rate'
            ? (a.sales > 0 ? a.profit / a.sales : 0)
            : a[dailySortField];
        let vb = dailySortField === 'profit_rate'
            ? (b.sales > 0 ? b.profit / b.sales : 0)
            : b[dailySortField];
        if (typeof va === 'string') {
            return dailySortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
        }
        return dailySortDir === 'asc' ? va - vb : vb - va;
    });

    // 합계 행 추가
    const total = {
        orders: items.reduce((s, i) => s + i.orders, 0),
        sales: items.reduce((s, i) => s + i.sales, 0),
        settlement: items.reduce((s, i) => s + i.settlement, 0),
        purchase: items.reduce((s, i) => s + i.purchase, 0),
        shipping: items.reduce((s, i) => s + i.shipping, 0),
        profit: items.reduce((s, i) => s + i.profit, 0)
    };
    total.profit_rate = total.sales > 0 ? (total.profit / total.sales * 100) : 0;

    let html = items.map(item => {
        const profitRate = item.sales > 0 ? (item.profit / item.sales * 100) : 0;
        return `
            <tr>
                <td style="text-align:center;">${item.date}</td>
                <td>${item.orders}</td>
                <td>${formatMoney(item.sales)}</td>
                <td>${formatMoney(item.settlement)}</td>
                <td>${formatMoney(item.purchase)}</td>
                <td>${formatMoney(item.shipping)}</td>
                <td class="${item.profit >= 0 ? 'positive' : 'negative'}">${formatMoney(item.profit)}</td>
                <td>${profitRate.toFixed(1)}%</td>
            </tr>
        `;
    }).join('');

    // 합계 행
    html += `
        <tr style="background:#f0f0f0; font-weight:bold;">
            <td style="text-align:center;">합계</td>
            <td>${total.orders}</td>
            <td>${formatMoney(total.sales)}</td>
            <td>${formatMoney(total.settlement)}</td>
            <td>${formatMoney(total.purchase)}</td>
            <td>${formatMoney(total.shipping)}</td>
            <td class="positive">${formatMoney(total.profit)}</td>
            <td>${total.profit_rate.toFixed(1)}%</td>
        </tr>
    `;

    tbody.innerHTML = html;
}

function renderSalesCharts() {
    if (!salesData || !salesData.daily || salesData.daily.length === 0) return;

    const labels = salesData.daily.map(d => d.date.substring(5)); // MM-DD
    const salesValues = salesData.daily.map(d => d.sales);
    const profitValues = salesData.daily.map(d => d.profit);

    // 평균/최고/최저 일매출 계산
    const validSales = salesValues.filter(v => v > 0);
    const avgSales = validSales.length > 0 ? Math.round(validSales.reduce((a, b) => a + b, 0) / validSales.length) : 0;
    const maxSales = validSales.length > 0 ? Math.max(...validSales) : 0;
    const minSales = validSales.length > 0 ? Math.min(...validSales) : 0;

    // 평균 라인 데이터 (모든 날짜에 동일한 값)
    const avgLineData = salesValues.map(() => avgSales);

    // 통계 표시 업데이트
    const avgEl = document.getElementById('avgDailySales');
    const maxEl = document.getElementById('maxDailySales');
    const minEl = document.getElementById('minDailySales');
    if (avgEl) avgEl.textContent = formatMoney(avgSales);
    if (maxEl) maxEl.textContent = formatMoney(maxSales);
    if (minEl) minEl.textContent = formatMoney(minSales);

    // 매출 + 수익 합친 차트
    const ctx1 = document.getElementById('dailySalesChart');
    if (ctx1) {
        if (dailySalesChart) dailySalesChart.destroy();
        dailySalesChart = new Chart(ctx1, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: '주문금액',
                        data: salesValues,
                        backgroundColor: 'rgba(102, 126, 234, 0.6)',
                        borderColor: 'rgba(102, 126, 234, 1)',
                        borderWidth: 1,
                        order: 3
                    },
                    {
                        label: '평균 일매출',
                        data: avgLineData,
                        type: 'line',
                        borderColor: 'rgba(255, 152, 0, 1)',
                        backgroundColor: 'transparent',
                        borderWidth: 2,
                        borderDash: [10, 5],  // 점선
                        pointRadius: 0,
                        tension: 0,
                        order: 1
                    },
                    {
                        label: '순익',
                        data: profitValues,
                        type: 'line',
                        borderColor: 'rgba(46, 125, 50, 1)',
                        backgroundColor: 'transparent',
                        borderWidth: 2,
                        borderDash: [5, 5],  // 점선
                        pointRadius: 3,
                        pointBackgroundColor: 'rgba(46, 125, 50, 1)',
                        tension: 0.3,
                        order: 2,
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false
                },
                plugins: {
                    legend: { display: true, position: 'top' }
                },
                scales: {
                    y: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        beginAtZero: true,
                        ticks: { callback: v => formatMoney(v) }
                    },
                    y1: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        beginAtZero: true,
                        ticks: { callback: v => formatMoney(v) },
                        grid: { drawOnChartArea: false }
                    }
                }
            }
        });
    }
}

// 소유자별 매출 테이블
function renderOwnerSalesTable(items) {
    const tbody = document.getElementById('ownerSalesTableBody');
    if (!tbody) return;

    // 서버에서 받은 owner 필드만 사용 (없으면 제외)
    const ownerData = {};
    items.forEach(item => {
        let owner = item.owner;

        // owner가 없으면 소유자별 매출에서 제외
        if (!owner || owner.trim() === '') return;

        if (!ownerData[owner]) {
            ownerData[owner] = { orders: 0, sales: 0, profit: 0 };
        }
        ownerData[owner].orders += item.orders;
        ownerData[owner].sales += item.sales;
        ownerData[owner].profit += item.profit;
    });

    // 매출 순 정렬
    const ownerList = Object.entries(ownerData)
        .map(([name, data]) => ({ name, ...data }))
        .sort((a, b) => b.sales - a.sales);

    tbody.innerHTML = ownerList.map(item => `
        <tr>
            <td style="text-align:left;">${item.name}</td>
            <td>${item.orders}</td>
            <td>${formatMoney(item.sales)}</td>
            <td class="${item.profit >= 0 ? 'positive' : 'negative'}">${formatMoney(item.profit)}</td>
        </tr>
    `).join('');
}

// 용도별 매출 테이블
function renderUsageSalesTable(items) {
    const tbody = document.getElementById('usageSalesTableBody');
    if (!tbody) return;

    const usageData = {};

    items.forEach(item => {
        const usage = item.usage || '미분류';

        if (!usageData[usage]) {
            usageData[usage] = { count: 0, orders: 0, sales: 0, profit: 0 };
        }

        usageData[usage].count += 1;
        usageData[usage].orders += item.orders;
        usageData[usage].sales += item.sales;
        usageData[usage].profit += item.profit;
    });

    tbody.innerHTML = Object.entries(usageData)
        .sort((a, b) => b[1].sales - a[1].sales)  // 매출 내림차순
        .map(([name, data]) => `
            <tr>
                <td>${name}</td>
                <td>${data.count}</td>
                <td>${data.orders}</td>
                <td>${formatMoney(data.sales)}</td>
                <td class="${data.profit >= 0 ? 'positive' : 'negative'}">${formatMoney(data.profit)}</td>
            </tr>
        `).join('');
}

// 내부 탭 전환
function switchSalesInnerTab(tabName) {
    // 버튼 활성화 상태 변경
    document.querySelectorAll('.inner-tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelector(`.inner-tab-btn[onclick*="${tabName}"]`).classList.add('active');

    // 탭 컨텐츠 표시/숨김
    document.querySelectorAll('.inner-tab-content').forEach(content => {
        content.style.display = 'none';
        content.classList.remove('active');
    });
    const targetTab = document.getElementById(`salesTab-${tabName}`);
    if (targetTab) {
        targetTab.style.display = 'block';
        targetTab.classList.add('active');
    }
}

// 플랫폼별 통계 렌더링
function renderPlatformStats() {
    if (!salesData || !salesData.data) return;

    const tbody = document.getElementById('platformStatsBody');
    if (!tbody) return;

    // 플랫폼별 데이터 집계
    const platforms = {
        '전체': { sales: 0, settlement: 0, fee: 0, cost: 0, profit: 0 },
        '스마트스토어': { sales: 0, settlement: 0, fee: 0, cost: 0, profit: 0 },
        '11번가': { sales: 0, settlement: 0, fee: 0, cost: 0, profit: 0 },
        '쿠팡': { sales: 0, settlement: 0, fee: 0, cost: 0, profit: 0 },
        '옥션': { sales: 0, settlement: 0, fee: 0, cost: 0, profit: 0 },
        '지마켓': { sales: 0, settlement: 0, fee: 0, cost: 0, profit: 0 }
    };

    Object.entries(salesData.data).forEach(([key, data]) => {
        // "스토어명(플랫폼)" 형식에서 플랫폼 추출
        const match = key.match(/\(([^)]+)\)$/);
        const platform = match ? match[1] : '기타';

        const sales = data.month_sales || 0;
        const settlement = data.month_settlement || sales * 0.9; // 정산금액 (없으면 90% 추정)
        const fee = sales - settlement;
        const cost = (data.month_purchase || 0) + (data.month_shipping || 0);
        const profit = data.month_profit || (settlement - cost);

        // 전체에 합산
        platforms['전체'].sales += sales;
        platforms['전체'].settlement += settlement;
        platforms['전체'].fee += fee;
        platforms['전체'].cost += cost;
        platforms['전체'].profit += profit;

        // 플랫폼별 합산
        if (platforms[platform]) {
            platforms[platform].sales += sales;
            platforms[platform].settlement += settlement;
            platforms[platform].fee += fee;
            platforms[platform].cost += cost;
            platforms[platform].profit += profit;
        }
    });

    // 테이블 렌더링
    const platformOrder = ['전체', '스마트스토어', '11번가', '쿠팡', '옥션', '지마켓'];
    tbody.innerHTML = platformOrder.map((name, idx) => {
        const p = platforms[name];
        const rate = p.sales > 0 ? ((p.profit / p.sales) * 100).toFixed(1) : '0';
        const isTotal = name === '전체';
        return `
            <tr style="${isTotal ? 'background:#f8f9fa; font-weight:bold;' : ''}">
                <td>${idx + 1}</td>
                <td>${name}</td>
                <td>${p.sales.toLocaleString()}</td>
                <td>${Math.round(p.settlement).toLocaleString()}</td>
                <td>${Math.round(p.fee).toLocaleString()}</td>
                <td>${Math.round(p.cost).toLocaleString()}</td>
                <td class="${p.profit >= 0 ? 'positive' : 'negative'}">${Math.round(p.profit).toLocaleString()}</td>
                <td>${rate}%</td>
            </tr>
        `;
    }).join('');
}

// TOP 40 상품 로드
async function loadTop20Products() {
    const tbody = document.getElementById('top20ProductsBody');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="7" class="loading">로딩 중...</td></tr>';

    try {
        const r = await fetch('/api/sales/top-products?limit=40');
        const d = await r.json();

        if (!d.success || !d.data || d.data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:#999;">데이터가 없습니다</td></tr>';
            top40Data = [];
            return;
        }

        top40Data = d.data;
        renderTop40Table();

    } catch (e) {
        console.error('TOP 40 상품 로드 오류:', e);
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:#c62828;">로드 실패</td></tr>';
        top40Data = [];
    }
}

// TOP 40 테이블 렌더링
function renderTop40Table() {
    const tbody = document.getElementById('top20ProductsBody');
    if (!tbody || top40Data.length === 0) return;

    tbody.innerHTML = top40Data.map((item, idx) => `
        <tr>
            <td style="text-align:center; font-weight:bold;">${idx + 1}</td>
            <td style="text-align:center;">
                <span class="platform-badge" style="background:${getPlatformColor(item.platform)}; color:white; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:bold;">${item.platform}</span>
            </td>
            <td style="text-align:left;">${item.스토어명 || '-'}</td>
            <td style="text-align:left; font-size:11px; color:#666;">${item.seller_code || '-'}</td>
            <td style="text-align:left; font-size:12px; word-break:break-word; line-height:1.4;">${item.product_name || '-'}</td>
            <td style="text-align:right; font-weight:bold; white-space:nowrap;">${item.order_count}건</td>
            <td style="text-align:right; white-space:nowrap;">${formatMoney(item.total_sales)}원</td>
        </tr>
    `).join('');

    // 정렬 아이콘 업데이트
    document.getElementById('sortIcon-order_count').textContent =
        top40SortColumn === 'order_count' ? (top40SortDesc ? '▼' : '▲') : '';
    document.getElementById('sortIcon-total_sales').textContent =
        top40SortColumn === 'total_sales' ? (top40SortDesc ? '▼' : '▲') : '';
}

// TOP 40 정렬
function sortTop40(column) {
    if (top40Data.length === 0) return;

    // 같은 컬럼 클릭 시 정렬 방향 토글
    if (top40SortColumn === column) {
        top40SortDesc = !top40SortDesc;
    } else {
        top40SortColumn = column;
        top40SortDesc = true;  // 새로운 컬럼은 기본 내림차순
    }

    // 정렬
    top40Data.sort((a, b) => {
        const aVal = column === 'order_count' ? a.order_count : a.total_sales;
        const bVal = column === 'order_count' ? b.order_count : b.total_sales;
        return top40SortDesc ? (bVal - aVal) : (aVal - bVal);
    });

    renderTop40Table();
}

// 플랫폼 스펠링별 클래스 (마켓현황과 동일)
function getPlatformClass(platform) {
    const classes = {
        'N': 'smartstore',
        '11': 'st11',
        'C': 'coupang',
        'G': 'gmarket',
        'A': 'auction'
    };
    return classes[platform] || '';
}

// 플랫폼 색상
function getPlatformColor(platform) {
    const colors = {
        'N': '#03C75A',
        '11': '#E31837',
        'C': '#00B4D8',
        'G': '#00C73C',
        'A': '#FF6600',
        '스마트스토어': '#03C75A',
        '11번가': '#E31837',
        '쿠팡': '#00B4D8',
        '옥션': '#FF6600',
        '지마켓': '#00C73C'
    };
    return colors[platform] || '#666';
}

// 텍스트 자르기
function truncateText(text, maxLen) {
    if (!text) return '-';
    return text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
}

// 지마켓/옥션 판매중 수량 수동 업데이트
async function updateProductCount(input) {
    const storeName = input.dataset.store;
    const platform = input.dataset.platform;
    const count = parseInt(input.value) || 0;

    try {
        const r = await fetch('/api/market/update-product-count', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                store_name: storeName,
                platform: platform,
                count: count
            })
        });
        const d = await r.json();

        if (d.success) {
            input.style.borderColor = '#4CAF50';
            setTimeout(() => { input.style.borderColor = '#ddd'; }, 1000);
        } else {
            showToast('저장 실패: ' + d.message, 'error');
            input.style.borderColor = '#f44336';
        }
    } catch (e) {
        console.error('판매중 수량 저장 오류:', e);
        showToast('저장 오류', 'error');
        input.style.borderColor = '#f44336';
    }
}

// 탭 전환 시 스케줄러 로드
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            if (tab.dataset.tab === 'scheduler') {
                loadSchedules();
                // 계정 목록도 로드
                if (typeof loadSchedAccounts === 'function') {
                    loadSchedAccounts();
                }
            }
            if (tab.dataset.tab === 'sales') {
                if (!salesData) loadSalesData();
            }
        });
    });
});

// ========== SMS 문자 템플릿 기능 ==========
const smsTemplates = {
    categories: ['전체', '통관요청', '배송', 'CS응대', '리뷰/감사'],
    templates: [
        // === 통관요청 카테고리 ===
        {
            id: 'tongbu_request',
            name: '📋 통관번호 요청',
            category: '통관요청',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

주문해주신 <{상품명}> 상품은 
해외구매대행 제품으로 ✅(성함/개인통관번호/연락처)가 필요합니다.

통관번호 확인 후 본 번호로 회신 부탁드립니다.

배송 관련하여 체크 사항 안내드립니다. (배송기간 휴일제외 7~14일)

✅ 해외배송 상품으로 단순변심 반품이 어렵습니다. 반품 시 해외 리턴 비용이 청구 됩니다.
✅ 150달러 이상 상품은 관부가세가 발생하며 이는 실구매자 부담입니다.
✅ 일부 대형 상품의 경우 국내배송시 일반택배가 불가능하여 착불 택배비가 청구 될수 있습니다.
※ 자세한 내용은 상세페이지 <필독사항> 참조 바랍니다.

취소를 원하시는 경우 회신으로 "이름+취소" 라고 회신 주시기 바랍니다.

*본 번호는 문자 전용으로 PC에 연결되어 있어 통화가 어렵습니다.
문의는 문자 남겨주시면 확인 후 답변드리겠습니다.`
        },
        {
            id: 'tongbu_retry',
            name: '📋 통관번호 재요청',
            category: '통관요청',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

주문해주신 <{상품명}> 상품은 
해외구매대행 제품으로 ✅(성함/개인통관번호/연락처)가 필요합니다.

안내드린 카카오톡으로 회신하지 않으신 경우 빠른 회신 부탁드립니다.

배송 관련하여 체크 사항 안내드립니다. (배송기간 휴일제외 7~14일)

✅ 해외배송 상품으로 단순변심 반품이 어렵습니다. 반품 시 해외 리턴 비용이 청구 됩니다.
✅ 150달러 이상 상품은 관부가세가 발생하며 이는 실구매자 부담입니다.
✅ 일부 대형 상품의 경우 국내배송시 일반택배가 불가능하여 착불 택배비가 청구 될수 있습니다.
※ 자세한 내용은 상세페이지 <필독사항> 참조 바랍니다.

본 안내는 카카오톡 메세지로도 안내되었으며 
카톡 메세지에서 바로 "취소신청"이 가능합니다.

*본 번호는 문자 전용으로 PC에 연결되어 있어 통화가 어렵습니다.
문의는 본 번호(010-8295-6606)로 문자 남겨주시면 확인 후 답변드리겠습니다.`
        },
        {
            id: 'tongbu_error',
            name: '⚠️ 통관번호 오류',
            category: '통관요청',
            content: `{수취인}님 안녕하세요!

(상품명 : {상품명}) 주문하신 {마켓} 판매자센터입니다.

고객님께서 작성하신 ✅통관번호가 일치하지 발송이 지연되고 있습니다.
(성함/통관번호/연락처) 재확인 후 회신 부탁드립니다!

개인통관번호는 네이버 '개인통관고유부호' 검색 후 발급하시거나 하단 관세청 링크에서 발급이 가능하십니다 : )

관세청 : https://unipass.customs.go.kr/csp/persIndex.do

확인 후 문자로 회신 부탁드립니다.
통관번호 확인후 현지 주문이 들어가며 배송일은 약 10~14일 소요됩니다 : )

감사합니다.`
        },
        {
            id: 'tongbu_11st',
            name: '📋 통관요청 (11번가)',
            category: '통관요청',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

주문해주신 <{상품명}> 은 
재고 소진후 판매 부진으로 도매업체 수입이 지연되고 있습니다. 
다른 도매처를 확인하였으나 현재 재고보유처가 없는 상황입니다. 

다만, 시간이 조금 더 소요되더라도 상품 수령을 원하시는 경우,
해외 개별 발주로 배송은 가능합니다. 개별 발주시 통관정보 회신이 필요합니다.
(배송기간 휴일제외 9~14일)

개별 발주 요청 시 아래 내용에 동의하신 것으로 간주됩니다.
취소를 원하실 경우 문자로 "이름+취소" 회신 부탁드립니다.

✅ 개별수입건으로 단순변심 반품 불가. 
✅ 150달러 이상 관부가세 발생시 고객 부담.
✅ 대형 상품의 경우 CJ택배 -> 경동택배 이관 착불배송비 발생시 고객부담.

※ 본 번호는 PC 연동 문자 전용이라 통화가 어렵습니다.
문자로 문의 남겨주시면 확인 후 빠르게 답변드리겠습니다`
        },
        // === 배송 카테고리 ===
        {
            id: 'delivery_confirm',
            name: '🚚 배송안내 (통관접수)',
            category: '배송',
            content: `안녕하세요. {수취인}고객님
{마켓}입니다 
주문해주신 ({상품명}) 상품의 통관번호가 정상 접수 되었습니다.

배송 관련하여 체크 사항 안내드립니다. (배송기간 휴일제외 7~14일)

✅ 배송중 상태에서는 주문 취소가 불가합니다. 주문 취소 시 해외 리턴 비용이 청구됩니다. 
✅ 150달러 이상의 물건 통관비용(관부가세)은 고객님께서 추후에 세관의 안내에 따라 납부해 주셔야 합니다.
✅ 기본 배송비(해외 운송비, 국내 CJ택배비)는 무료이나, 상품이 경동택배(3변의합 160CM이상, 무게 20KG이상 등)로 이관 되면 배송비가 착불로 청구될 수 있습니다.
★ 정성스럽고 긍정적인 리뷰를 남겨주신 고객님께는 커피 쿠폰 또는 화물택배비 50%지원(최대1만원) 혜택을 드립니다.

상세페이지에 <필독사항>으로 안내드리고 있으나 확인하지 않으시는 고객님들이 많아
별도 문자 안내드리니 주문취소를 원하시는 경우 바로 회신 부탁드립니다.`
        },
        {
            id: 'delivery_delay',
            name: '⏳ 배송 지연 안내',
            category: '배송',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

현재 국제운송 중이며 보통 7~14일 내 통관·입고가 완료됩니다. 지속 확인 중입니다.

해외 발송 → 중국 이동 → 배대지 도착 → 한국행 → 통관 → 국내배송 순으로 진행됩니다.

추가 문의사항 있으시면 문자로 남겨주세요.
감사합니다.`
        },
        {
            id: 'delivery_tracking',
            name: '📍 배송 위치 확인',
            category: '배송',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

운송장 번호를 보내주시면 위치 확인 후 바로 안내드리겠습니다.

감사합니다.`
        },
        {
            id: 'delivery_not_received',
            name: '📦 배송완료 미수령',
            category: '배송',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

배송완료로 표시되나 미수령 시 배송사진·택배함·관리실 확인 부탁드립니다.

확인 후에도 찾을 수 없으시면 문자로 알려주세요.
감사합니다.`
        },
        {
            id: 'customs_delay',
            name: '🛃 통관 지연 안내',
            category: '배송',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

현재 통관 절차 중이며 평균 2~3일 소요됩니다.
통관 완료 후 국내 배송이 시작되며, 진행 상황 확인 후 안내드리겠습니다.

감사합니다.`
        },
        // === CS응대 카테고리 ===
        {
            id: 'soldout',
            name: '❌ 품절 안내',
            category: 'CS응대',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

주문하신 ({상품명}) 상품이 소량 남아있던 재고가 소진되어 안내드립니다.

재고 추가 확보를 위해 노력하였으나 재고 확보가 어려워 부득이 취소 안내 문자드리는점 양해부탁드립니다.
재고소진으로 불편드린점 진심으로 사과드립니다.

감사합니다.`
        },
        {
            id: 'customs_tax',
            name: '💰 관부가세 안내',
            category: 'CS응대',
            content: `{수취인}님 안녕하세요!

(상품명 : {상품명}) 주문해주신 {마켓}입니다.

현재 구매하신 상품은 ✅150불 이상 상품으로 세관에서 실구매자에게 ✅관부가세 안내가 된것으로 확인됩니다.
받으신 문자 또는 카톡을 확인하시어 관부가세 ✅납부 요청드립니다.

관부가세가 납부가 되어야 세관 통관이 진행되는점 참고 부탁드립니다.

감사합니다.`
        },
        {
            id: 'auto_cancel',
            name: '🚫 반자동 취소',
            category: 'CS응대',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

고객님 답변이 없으셔서 오늘까지만 기다렸다가 취소처리 하겠습니다.

감사합니다.`
        },
        {
            id: 'wrong_delivery',
            name: '📦 오배송 안내',
            category: 'CS응대',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

오배송으로 불편을 드려 죄송합니다. 
사진 확인 후 교환/반품 도와드리겠습니다.

받으신 상품의 전체 사진을 보내주시면 빠르게 처리해드리겠습니다.

감사합니다.`
        },
        {
            id: 'defect',
            name: '⚠️ 제품 불량 안내',
            category: 'CS응대',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

불량 부분의 사진 또는 영상을 보내주시면 가장 빠른 해결책으로 안내드립니다.

확인 후 교환 또는 부분보상 등 가능한 해결책 안내드리겠습니다.

감사합니다.`
        },
        {
            id: 'refund',
            name: '💳 환불 처리 안내',
            category: 'CS응대',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

환불 접수되었습니다. 영업일 기준 2~3일 내 처리됩니다.

추가 문의사항 있으시면 문자로 남겨주세요.
감사합니다.`
        },
        {
            id: 'exchange',
            name: '🔄 교환 처리 안내',
            category: 'CS응대',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

교환 절차에 따라 회수 후 재발송 예정입니다.

회수 요청 접수되었으며 회수 기사님 방문 시 안내드립니다.
감사합니다.`
        },
        {
            id: 'cs_received',
            name: '✅ CS 접수 완료',
            category: 'CS응대',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

문의 접수되었습니다. 확인 후 빠르게 안내드리겠습니다.

감사합니다.`
        },
        {
            id: 'image_request',
            name: '📷 사진 요청',
            category: 'CS응대',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

정확한 문제 파악을 위해 사진을 보내주세요.
받으신 상품의 전체 사진과 문제 부분을 확인할 수 있도록 보내주시면 빠르게 처리해드리겠습니다.

감사합니다.`
        },
        {
            id: 'no_return',
            name: '🚫 반품 불가 안내',
            category: 'CS응대',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

해외 구매대행 특성상 단순 변심 반품은 어렵습니다.
부분보상 또는 재판매 팁 안내 가능합니다.

불편을 드려 죄송합니다.
감사합니다.`
        },
        // === 리뷰/감사 카테고리 ===
        {
            id: 'review_request',
            name: '⭐ 리뷰 요청',
            category: '리뷰/감사',
            content: `{수취인}님 안녕하세요!

(상품명 : {상품명}) 주문해주신 {마켓}입니다.

주문하신 상품은 잘 받으셨을까요? 오랫동안 기다리신 만큼 마음에 드셨기를 바랍니다.

✅현재 구매 후기 이벤트를 진행하고 있습니다. 
구매하신 쇼핑몰에서 후기 작성해주시면 
✅100% 커피쿠폰을 제공해드리고 있으니 많은 참여 부탁드립니다!!

바쁘시겠지만 잠깐만 시간내시어 간단한 후기 남겨주시면 판매자에 정말 큰 힘이 됩니다.

감사합니다!`
        },
        {
            id: 'thank_you',
            name: '🙏 감사 메시지',
            category: '리뷰/감사',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

이용해주셔서 감사합니다. 더 좋은 서비스로 보답하겠습니다.

추가 문의사항 있으시면 언제든 문자로 남겨주세요.
감사합니다 😊`
        },
        {
            id: 'complete',
            name: '✅ 완료 처리 안내',
            category: '리뷰/감사',
            content: `{수취인}님 안녕하세요. {마켓}입니다.

요청하신 처리가 모두 완료되었습니다. 
추가 문의 있으시면 언제든지 말씀해주세요.

감사합니다.`
        }
    ]
};

// 현재 선택된 템플릿
let currentTemplateIdx = 0;
let templatePanelVisible = false;
let templateTargetPhone = null;  // 템플릿 적용 대상 패널 (null이면 대화 모달)

// 템플릿 모달 초기화 (HTML에 정의된 모달 사용)
function initTemplateModal() {
    const tabsContainer = document.getElementById('templateTabs');
    if (!tabsContainer || tabsContainer.children.length > 0) return;

    // 탭 버튼 생성
    tabsContainer.innerHTML = smsTemplates.categories.map((cat, i) =>
        `<button class="template-tab ${i === 0 ? 'active' : ''}" onclick="filterTemplates('${cat}')" style="flex:1; min-width:60px; padding:8px 4px; border:none; background:white; font-size:11px; cursor:pointer; color:#666;">${cat}</button>`
    ).join('');

    // 스타일 추가
    addTemplateStyles();
}

// 템플릿 목록 렌더링
function renderTemplateList(category = '전체') {
    const list = document.getElementById('templateList');
    if (!list) return;

    const filtered = category === '전체'
        ? smsTemplates.templates
        : smsTemplates.templates.filter(t => t.category === category);

    list.innerHTML = filtered.map((t, idx) => {
        const realIdx = smsTemplates.templates.indexOf(t);
        return `
            <div class="template-item ${realIdx === currentTemplateIdx ? 'selected' : ''}" 
                 onclick="selectTemplate(${realIdx})">
                <div class="template-name">${t.name}</div>
                <div class="template-preview-text">${t.content.substring(0, 50)}...</div>
            </div>
        `;
    }).join('');
}

// 템플릿 필터
function filterTemplates(category) {
    document.querySelectorAll('.template-tab').forEach(tab => {
        tab.classList.toggle('active', tab.textContent === category);
    });
    renderTemplateList(category);
}

// 템플릿 선택
function selectTemplate(idx) {
    currentTemplateIdx = idx;
    document.querySelectorAll('.template-item').forEach((el, i) => {
        const realIdx = parseInt(el.getAttribute('onclick').match(/\d+/)[0]);
        el.classList.toggle('selected', realIdx === idx);
    });
    updateTemplatePreview();
}

// 미리보기 업데이트
function updateTemplatePreview() {
    const template = smsTemplates.templates[currentTemplateIdx];
    if (!template) return;

    const customer = document.getElementById('tplVarCustomer')?.value || '';
    const market = document.getElementById('tplVarMarket')?.value || '';
    const product = document.getElementById('tplVarProduct')?.value || '';

    let content = template.content;

    // 변수 치환 (입력값 없으면 빈칸 처리)
    content = content.replace(/{수취인}/g, customer);
    content = content.replace(/{마켓}/g, market);
    content = content.replace(/{상품명}/g, product);

    const previewEl = document.getElementById('templatePreviewContent');
    if (previewEl) {
        // 변수 하이라이트 (입력된 값만)
        let highlighted = content;
        if (customer) highlighted = highlighted.split(customer).join(`<span class="tpl-highlight">${customer}</span>`);
        if (market) highlighted = highlighted.split(market).join(`<span class="tpl-highlight">${market}</span>`);
        if (product) highlighted = highlighted.split(product).join(`<span class="tpl-highlight">${product}</span>`);
        previewEl.innerHTML = highlighted.replace(/\n/g, '<br>');
    }

    // 글자 수 및 SMS/LMS 구분
    const countEl = document.getElementById('tplCharCount');
    if (countEl) {
        const len = content.length;
        let typeText = '';
        if (len <= 90) {
            typeText = `${len}자 (SMS)`;
        } else if (len <= 2000) {
            typeText = `${len}자 (LMS)`;
        } else {
            typeText = `${len}자 (MMS)`;
        }
        countEl.textContent = typeText;
        countEl.className = 'char-count' + (len > 1000 ? ' warning' : '') + (len > 2000 ? ' danger' : '');
    }
}

// 템플릿 패널 열기
function openTemplateModal() {
    initTemplateModal();
    const panel = document.getElementById('smsTemplateModal');
    if (panel) {
        panel.style.display = 'flex';
        renderTemplateList();
        updateTemplatePreview();
    }
}

// 템플릿 패널 닫기
function closeTemplateModal() {
    const panel = document.getElementById('smsTemplateModal');
    if (panel) {
        panel.style.display = 'none';
    }
    templateTargetPhone = null;
}

// 템플릿 패널 토글
function toggleTemplatePanel() {
    const panel = document.getElementById('smsTemplateModal');
    if (panel && panel.style.display === 'flex') {
        closeTemplateModal();
    } else {
        openTemplateModal();
    }
}

// 클립보드 복사
function copyTemplateToClipboard() {
    const template = smsTemplates.templates[currentTemplateIdx];
    if (!template) return;

    const customer = document.getElementById('tplVarCustomer')?.value || '';
    const market = document.getElementById('tplVarMarket')?.value || '';
    const product = document.getElementById('tplVarProduct')?.value || '';

    let content = template.content;
    content = content.replace(/{수취인}/g, customer || '');
    content = content.replace(/{마켓}/g, market || '');
    content = content.replace(/{상품명}/g, product || '');

    // 클립보드 복사 (fallback 포함)
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(content).then(() => {
            showToast('클립보드에 복사되었습니다', 'success');
        }).catch(() => {
            fallbackCopyToClipboard(content);
        });
    } else {
        fallbackCopyToClipboard(content);
    }
}

// 클립보드 복사 fallback (HTTP 환경용)
function fallbackCopyToClipboard(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    try {
        document.execCommand('copy');
        showToast('클립보드에 복사되었습니다', 'success');
    } catch (e) {
        showToast('복사 실패 - 직접 선택하여 복사하세요', 'error');
    }
    document.body.removeChild(textarea);
}

// 입력창에 적용
function applyTemplateToInput() {
    const template = smsTemplates.templates[currentTemplateIdx];
    if (!template) return;

    const customer = document.getElementById('tplVarCustomer')?.value || '';
    const market = document.getElementById('tplVarMarket')?.value || '';
    const product = document.getElementById('tplVarProduct')?.value || '';

    let content = template.content;
    content = content.replace(/{수취인}/g, customer || '');
    content = content.replace(/{마켓}/g, market || '');
    content = content.replace(/{상품명}/g, product || '');

    let input = null;

    // 1. 대상 패널이 지정된 경우 (SMS 3등분 패널에서 호출)
    if (templateTargetPhone) {
        input = document.getElementById(`sendMsg-${templateTargetPhone}`);
    }

    // 2. 대화 모달 내 입력창 시도
    if (!input) {
        input = document.getElementById('conversationInput');
    }

    // 3. 메인 SMS 패널 입력창 시도 (현재 선택된 프로필)
    if (!input && currentConversation?.profile_id) {
        input = document.getElementById(`sendMsg-${currentConversation.profile_id}`);
    }

    // 4. 아무 입력창이나 찾기
    if (!input) {
        input = document.querySelector('.sms-panel textarea[id^="sendMsg-"]');
    }

    if (input) {
        input.value = content;
        input.focus();
        showToast('템플릿이 적용되었습니다', 'success');
    } else {
        // 입력창을 못 찾으면 클립보드 복사
        navigator.clipboard.writeText(content);
        showToast('클립보드에 복사되었습니다 (입력창에 붙여넣기 하세요)', 'info');
    }

    // 템플릿 패널 닫기
    toggleTemplatePanel();
    templateTargetPhone = null;  // 대상 패널 초기화
}

// SMS 패널에서 템플릿 열기
function openPanelTemplate(phone) {
    console.log('[템플릿] openPanelTemplate 호출:', phone);
    templateTargetPhone = phone;
    openTemplateModal();
}

// 대화 모달에 템플릿 버튼 추가 (DOM 로드 후)
function initTemplateButton() {
    initTemplateModal();
    console.log('[템플릿] 초기화 완료');
}

// 템플릿 스타일 추가
function addTemplateStyles() {
    if (document.getElementById('smsTemplateStyles')) return;

    const style = document.createElement('style');
    style.id = 'smsTemplateStyles';
    style.textContent = `
        /* 템플릿 목록 아이템 스타일 */
        .template-item {
            padding: 10px 12px;
            border-bottom: 1px solid #f0f0f0;
            cursor: pointer;
        }
        .template-item:hover { background: #f8f9ff; }
        .template-item.selected { background: #e8ebff; border-left: 3px solid #667eea; }
        .template-name { font-size: 13px; font-weight: bold; color: #333; }
        .template-preview-text { font-size: 11px; color: #888; margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

        /* 탭 active 상태 */
        #templateTabs button.active {
            color: #667eea !important;
            border-bottom: 2px solid #667eea;
            font-weight: bold;
        }

        .template-panel-header {
            padding: 12px 15px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-weight: bold;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-radius: 12px 12px 0 0;
        }
        .template-close-btn {
            background: none;
            border: none;
            color: white;
            font-size: 20px;
            cursor: pointer;
        }
        
        .template-tabs {
            display: flex;
            border-bottom: 1px solid #e0e0e0;
            flex-wrap: wrap;
        }
        .template-tab {
            flex: 1;
            min-width: 60px;
            padding: 8px 4px;
            border: none;
            background: white;
            font-size: 11px;
            cursor: pointer;
            color: #666;
        }
        .template-tab.active {
            color: #667eea;
            border-bottom: 2px solid #667eea;
            font-weight: bold;
        }
        
        .template-list {
            flex: 0 0 auto;
            overflow-y: auto;
            max-height: 200px;
        }
        .template-item {
            padding: 10px 12px;
            border-bottom: 1px solid #f0f0f0;
            cursor: pointer;
        }
        .template-item:hover { background: #f8f9ff; }
        .template-item.selected { background: #e8ebff; border-left: 3px solid #667eea; }
        .template-name { font-size: 13px; font-weight: bold; color: #333; }
        .template-preview-text { font-size: 11px; color: #888; margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        
        .template-vars {
            padding: 10px 12px;
            background: #f8f9ff;
            border-top: 1px solid #e0e0e0;
            flex: 0 0 auto;
        }
        .vars-title { font-size: 12px; font-weight: bold; color: #667eea; margin-bottom: 8px; }
        .var-row { display: flex; align-items: center; margin-bottom: 6px; }
        .var-row label { width: 60px; font-size: 11px; color: #666; }
        .var-row input { flex: 1; padding: 5px 8px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px; }
        .var-row input:focus { outline: none; border-color: #667eea; }
        
        .template-preview-section {
            padding: 10px 12px;
            border-top: 1px solid #e0e0e0;
            flex: 1 1 auto;
            display: flex;
            flex-direction: column;
            min-height: 0;
        }
        .preview-title { font-size: 12px; font-weight: bold; color: #333; margin-bottom: 6px; flex: 0 0 auto; }
        .template-preview-content {
            background: #fffde7;
            border: 1px solid #fff59d;
            border-radius: 6px;
            padding: 10px;
            font-size: 12px;
            line-height: 1.6;
            flex: 1 1 auto;
            overflow-y: auto;
            min-height: 100px;
            max-height: 40vh;
        }
        .tpl-highlight { background: #ffeb3b; padding: 0 2px; border-radius: 2px; }
        .char-count { font-size: 10px; color: #888; text-align: right; margin-top: 4px; }
        .char-count.warning { color: #ff9800; }
        .char-count.danger { color: #f44336; }
        
        .template-actions {
            padding: 10px 12px;
            border-top: 1px solid #e0e0e0;
            display: flex;
            gap: 8px;
        }
        .tpl-btn-copy {
            padding: 8px 12px;
            background: #f0f0f0;
            border: none;
            border-radius: 5px;
            font-size: 12px;
            cursor: pointer;
        }
        .tpl-btn-apply {
            flex: 1;
            padding: 8px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 12px;
            font-weight: bold;
            cursor: pointer;
        }
        
        .template-toggle-btn {
            padding: 8px 12px;
            background: #f0f0f0;
            border: none;
            border-radius: 6px;
            font-size: 13px;
            cursor: pointer;
            margin-right: 10px;
        }
        .template-toggle-btn.active {
            background: #667eea;
            color: white;
        }
        
        /* SMS 패널 메시지 입력창 자동 확장 */
        .sms-panel textarea[id^="sendMsg-"],
        .sms-panel textarea[id^="sendTo-"] {
            transition: height 0.2s ease;
        }
        .sms-panel textarea[id^="sendMsg-"]:focus {
            height: 120px !important;
            min-height: 120px;
        }
    `;
    document.head.appendChild(style);
}

// 초기화
document.addEventListener('DOMContentLoaded', () => {
    addTemplateStyles();
});
// app.js에 추가할 코드

// ========== 마케팅분석 탭 ==========

let marketingTaskId = null;
let marketingPollingInterval = null;

// ========== 마케팅 분석 결과 탭 ==========

// 서브탭 전환
function switchMarketingSubTab(subtab) {
    // 탭 버튼 스타일 변경
    document.querySelectorAll('.mkt-sub-tab').forEach(btn => {
        if (btn.dataset.subtab === subtab) {
            btn.style.background = '#667eea';
            btn.style.color = 'white';
            btn.style.fontWeight = '600';
        } else {
            btn.style.background = '#f0f0f0';
            btn.style.color = '#666';
            btn.style.fontWeight = '500';
        }
    });

    // 컨텐츠 표시/숨김
    document.querySelectorAll('.mkt-sub-content').forEach(content => {
        content.style.display = 'none';
    });

    const targetContent = document.getElementById(`mkt-subtab-${subtab}`);
    if (targetContent) {
        targetContent.style.display = 'block';
    }

    // 결과 탭으로 전환시 스토어 목록 로드
    if (subtab === 'results') {
        loadMarketingStores();
    }
}

// 마케팅 스토어 목록 로드
async function loadMarketingStores() {
    try {
        console.log('[마케팅] 스토어 목록 로드 시작');
        const r = await fetch('/api/marketing/data');
        const d = await r.json();
        console.log('[마케팅] 스토어 목록 응답:', d);

        if (!d.success) {
            showToast(d.error || '마케팅 데이터 로드 실패', 'error');
            return;
        }

        const select = document.getElementById('mktStoreSelect');
        if (!select) return;

        const currentValue = select.value;
        select.innerHTML = '<option value="">-- 스토어 선택 --</option>';

        if (d.stores && d.stores.length > 0) {
            d.stores.forEach(store => {
                const opt = document.createElement('option');
                opt.value = store;
                opt.textContent = store;
                select.appendChild(opt);
            });

            // 이전 선택값 복원
            if (currentValue && d.stores.includes(currentValue)) {
                select.value = currentValue;
            }
        }

    } catch (e) {
        console.error('마케팅 스토어 로드 오류:', e);
        showToast('마케팅 스토어 로드 오류', 'error');
    }
}

// 선택한 스토어의 마케팅 데이터 로드
async function loadMarketingStoreData() {
    const select = document.getElementById('mktStoreSelect');
    const store = select?.value;
    console.log('[마케팅] 스토어 선택:', store);

    if (!store) {
        // 초기화
        document.getElementById('mktTotalProducts').textContent = '-';
        document.getElementById('mktTotalExposure').textContent = '-';
        document.getElementById('mktTotalClicks').textContent = '-';
        document.getElementById('mktAvgCtr').textContent = '-';
        document.getElementById('mktBizTable').innerHTML = '<tr><td colspan="5" style="padding: 30px; text-align: center; color: #999;">스토어를 선택하세요</td></tr>';
        document.getElementById('mktPartnerTable').innerHTML = '<tr><td colspan="5" style="padding: 30px; text-align: center; color: #999;">스토어를 선택하세요</td></tr>';
        return;
    }

    try {
        showToast('데이터 로딩 중...', 'info');

        const r = await fetch(`/api/marketing/data?store=${encodeURIComponent(store)}`);
        const d = await r.json();
        console.log('[마케팅] API 응답:', d);

        if (!d.success) {
            showToast(d.error || '데이터 로드 실패', 'error');
            return;
        }

        const storeData = d.data[store];
        if (!storeData || storeData.error) {
            showToast(storeData?.error || '데이터 없음', 'error');
            return;
        }

        const bizData = storeData.biz_advisor || [];
        const partnerData = storeData.shopping_partner || [];

        // 요약 카드 업데이트
        document.getElementById('mktTotalProducts').textContent = (bizData.length + partnerData.length).toLocaleString();

        let totalExposure = 0;
        let totalClicks = 0;
        partnerData.forEach(item => {
            totalExposure += parseInt(item.노출수?.replace(/,/g, '') || 0);
            totalClicks += parseInt(item.클릭수?.replace(/,/g, '') || 0);
        });

        document.getElementById('mktTotalExposure').textContent = totalExposure.toLocaleString();
        document.getElementById('mktTotalClicks').textContent = totalClicks.toLocaleString();

        const avgCtr = totalExposure > 0 ? ((totalClicks / totalExposure) * 100).toFixed(2) + '%' : '-';
        document.getElementById('mktAvgCtr').textContent = avgCtr;

        // 비즈어드바이저 테이블
        const bizTbody = document.getElementById('mktBizTable');
        if (bizData.length > 0) {
            bizTbody.innerHTML = bizData.map(item => `
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 10px; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${item.상품명 || ''}">${item.상품명 || '-'}</td>
                    <td style="padding: 10px;">${item.채널명 || '-'}</td>
                    <td style="padding: 10px; max-width: 200px; overflow: hidden; text-overflow: ellipsis;" title="${item.키워드 || ''}">${item.키워드 || '-'}</td>
                    <td style="padding: 10px; text-align: right;">${item.평균노출순위 || '-'}</td>
                    <td style="padding: 10px; text-align: right; font-weight: 600; color: #667eea;">${item.유입수 || '0'}</td>
                </tr>
            `).join('');
        } else {
            bizTbody.innerHTML = '<tr><td colspan="5" style="padding: 30px; text-align: center; color: #999;">데이터 없음</td></tr>';
        }

        // 쇼핑파트너 테이블
        const partnerTbody = document.getElementById('mktPartnerTable');
        if (partnerData.length > 0) {
            partnerTbody.innerHTML = partnerData.map(item => `
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 10px; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${item.상품명 || ''}">${item.상품명 || '-'}</td>
                    <td style="padding: 10px; text-align: right;">${item.노출수 || '0'}</td>
                    <td style="padding: 10px; text-align: right; font-weight: 600; color: #ee0979;">${item.클릭수 || '0'}</td>
                    <td style="padding: 10px; text-align: right;">${item.클릭율 || '-'}</td>
                    <td style="padding: 10px; text-align: right;">${item.클릭당수수료 || '-'}</td>
                </tr>
            `).join('');
        } else {
            partnerTbody.innerHTML = '<tr><td colspan="5" style="padding: 30px; text-align: center; color: #999;">데이터 없음</td></tr>';
        }

        // 전체채널 테이블
        const channelData = storeData.channel_data || [];
        const channelTbody = document.getElementById('mktChannelTable');
        if (channelData.length > 0) {
            channelTbody.innerHTML = channelData.map(item => `
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px 10px;">${item.채널명 || '-'}</td>
                    <td style="padding: 8px 10px; text-align: right; font-weight: 600; color: #4caf50;">${item.유입수 || '0'}</td>
                </tr>
            `).join('');
        } else {
            channelTbody.innerHTML = '<tr><td colspan="2" style="padding: 30px; text-align: center; color: #999;">데이터 없음</td></tr>';
        }

        // 쇼핑몰정보
        const mallInfo = storeData.mall_info || {};
        const mallInfoDiv = document.getElementById('mktMallInfo');
        const mallKeys = Object.keys(mallInfo);
        if (mallKeys.length > 0) {
            mallInfoDiv.innerHTML = mallKeys.map(key => `
                <div style="display: flex; justify-content: space-between; padding: 10px; background: #f8f9fa; border-radius: 6px;">
                    <span style="color: #666;">${key}</span>
                    <span style="font-weight: 600;">${mallInfo[key] || '-'}</span>
                </div>
            `).join('');
        } else {
            mallInfoDiv.innerHTML = '<div style="padding: 30px; text-align: center; color: #999;">데이터 없음</div>';
        }

        showToast(`${store} 데이터 로드 완료`, 'success');

    } catch (e) {
        console.error('마케팅 데이터 로드 오류:', e);
        showToast('마케팅 데이터 로드 오류', 'error');
    }
}

// 마케팅 탭 전환 시 스토어 로드
document.addEventListener('DOMContentLoaded', () => {
    // 탭 전환 감지
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            if (tab.dataset.tab === 'marketing') {
                setTimeout(loadMarketingStores, 100);
            }
        });
    });
});

// ========== 마케팅 데이터 수집 ==========

// 마케팅 데이터 수집 시작
async function startMarketingCollection() {
    const selectedAccounts = getSelectedAccountsForMarketing();

    if (selectedAccounts.length === 0) {
        showToast('계정을 선택하세요', 'error');
        return;
    }

    if (!confirm(`선택한 ${selectedAccounts.length}개 계정의 마케팅 데이터를 수집하시겠습니까?`)) {
        return;
    }

    try {
        document.getElementById('marketingStartBtn').disabled = true;
        document.getElementById('marketingStopBtn').disabled = false;

        const resp = await fetch('/api/marketing/collect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_ids: selectedAccounts })
        });

        const data = await resp.json();

        if (data.error) {
            showToast(data.error, 'error');
            return;
        }

        marketingTaskId = data.task_id;
        showToast(`마케팅 데이터 수집 시작 (${data.total}개 계정)`, 'info');

        // 로그 초기화
        document.getElementById('marketingLogArea').value = '';

        // SSE 스트림 시작
        startMarketingSSE(marketingTaskId);

    } catch (e) {
        console.error('마케팅 수집 시작 오류:', e);
        showToast('수집 시작 실패', 'error');
        document.getElementById('marketingStartBtn').disabled = false;
        document.getElementById('marketingStopBtn').disabled = true;
    }
}

// SSE 스트림 시작
let marketingEventSource = null;

function startMarketingSSE(taskId) {
    if (marketingEventSource) {
        marketingEventSource.close();
    }

    marketingEventSource = new EventSource(`/api/marketing/progress-stream/${taskId}`);

    marketingEventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            updateMarketingUI(data);

            // 완료 또는 오류 시 SSE 종료
            if (data.status === 'completed' || data.status === 'error') {
                stopMarketingSSE();
                document.getElementById('marketingStartBtn').disabled = false;
                document.getElementById('marketingStopBtn').disabled = true;

                if (data.status === 'completed') {
                    showToast('마케팅 데이터 수집 완료!', 'success');
                } else {
                    showToast('오류가 발생했습니다', 'error');
                }
            }
        } catch (e) {
            console.error('SSE 데이터 파싱 오류:', e);
        }
    };

    marketingEventSource.onerror = (error) => {
        console.error('마케팅 SSE 오류:', error);
        // 오류 시 폴백으로 기존 폴링 사용
        stopMarketingSSE();
        marketingPollingInterval = setInterval(pollMarketingProgressFallback, 2000);
    };
}

function updateMarketingUI(data) {
    // 진행률 업데이트
    const percent = data.total > 0 ? (data.current / data.total * 100) : 0;
    document.getElementById('marketingProgressBar').style.width = `${percent}%`;
    document.getElementById('marketingProgressBar').textContent = `${data.current} / ${data.total}`;

    // 상태 업데이트
    let statusText = '';
    if (data.status === 'running') {
        statusText = `🔄 진행 중 (${data.current}/${data.total})`;
    } else if (data.status === 'completed') {
        statusText = `✅ 완료 (${data.total}/${data.total})`;
    } else if (data.status === 'error') {
        statusText = `❌ 오류 발생`;
    }
    document.getElementById('marketingStatus').textContent = statusText;

    // 로그 업데이트
    if (data.logs && data.logs.length > 0) {
        const logArea = document.getElementById('marketingLogArea');
        logArea.value = data.logs.join('\n');
        logArea.scrollTop = logArea.scrollHeight;
    }
}

// SSE 실패 시 폴백 폴링
async function pollMarketingProgressFallback() {
    if (!marketingTaskId) return;

    try {
        const resp = await fetch(`/api/marketing/progress/${marketingTaskId}`);
        const data = await resp.json();

        if (data.error) {
            stopMarketingPolling();
            return;
        }

        updateMarketingUI(data);

        if (data.status === 'completed' || data.status === 'error') {
            stopMarketingPolling();
            document.getElementById('marketingStartBtn').disabled = false;
            document.getElementById('marketingStopBtn').disabled = true;

            if (data.status === 'completed') {
                showToast('마케팅 데이터 수집 완료!', 'success');
            } else {
                showToast('오류가 발생했습니다', 'error');
            }
        }
    } catch (e) {
        console.error('진행 상황 조회 오류:', e);
    }
}

function stopMarketingSSE() {
    if (marketingEventSource) {
        marketingEventSource.close();
        marketingEventSource = null;
    }
}

// 폴링 중지
function stopMarketingPolling() {
    if (marketingPollingInterval) {
        clearInterval(marketingPollingInterval);
        marketingPollingInterval = null;
    }
}

// 수집 중지
async function stopMarketingCollection() {
    if (!marketingTaskId) {
        showToast('중지할 작업이 없습니다', 'warning');
        return;
    }

    if (!confirm('현재 진행 중인 수집 작업을 중지하시겠습니까?')) {
        return;
    }

    try {
        const resp = await fetch('/api/marketing/stop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_id: marketingTaskId })
        });
        const data = await resp.json();

        if (data.success) {
            showToast('수집 중지 요청 완료', 'success');
            stopMarketingSSE();
            stopMarketingPolling();
            marketingTaskId = null;
            document.getElementById('marketingStartBtn').disabled = false;
            document.getElementById('marketingStopBtn').disabled = true;
            document.getElementById('marketingStatus').textContent = '⏹ 중지됨';
        } else {
            showToast('중지 실패: ' + (data.message || '오류'), 'error');
        }
    } catch (e) {
        console.error('마케팅 중지 오류:', e);
        showToast('중지 중 오류 발생', 'error');
    }
}

// 선택된 계정 가져오기
function getSelectedAccountsForMarketing() {
    const checkboxes = document.querySelectorAll('.marketing-account-cb:checked');
    return Array.from(checkboxes).map(cb => cb.value);
}

// 시트 초기화 (통합 시트 생성)
async function initializeMarketingSheets() {
    if (!confirm('마케팅 데이터 스프레드시트를 초기화하시겠습니까?\n\n"전체데이터", "쇼핑몰정보" 시트가 생성됩니다.')) {
        return;
    }

    try {
        const resp = await fetch('/api/marketing/create-sheets', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        const data = await resp.json();

        if (data.error) {
            showToast(data.error, 'error');
            return;
        }

        let message = '스프레드시트 초기화 완료!\n\n';
        data.results.forEach(r => {
            message += `${r.sheet}: ${r.status}\n`;
        });
        message += `\n📊 스프레드시트 보기:\n${data.spreadsheet_url}`;

        alert(message);
        showToast('스프레드시트 초기화 완료', 'success');

    } catch (e) {
        console.error('시트 초기화 오류:', e);
        showToast('시트 초기화 실패', 'error');
    }
}

// 계정 목록 로드 (기존 API 활용)
let marketingAccountsData = []; // 원본 데이터 저장

// 마케팅 수집 상태 저장
let marketingCollectionStatus = {};

async function loadMarketingAccounts() {
    try {
        // 기존 계정 목록 API 활용 - 플랫폼명은 한글!
        const resp = await fetch('/api/accounts?platform=스마트스토어');
        const data = await resp.json();

        const accounts = data.accounts || [];

        if (accounts.length === 0) {
            const accountList = document.getElementById('marketingAccountList');
            accountList.innerHTML = '<div class="empty">등록된 스마트스토어 계정이 없습니다</div>';
            return;
        }

        // 원본 데이터 저장
        marketingAccountsData = accounts;

        // 수집 상태 로드
        await loadMarketingCollectionStatus();

        // 필터 UI 생성
        createMarketingFilters();

        // 계정 목록 렌더링
        renderMarketingAccounts();

    } catch (e) {
        console.error('계정 목록 로드 오류:', e);
        showToast('계정 목록 로드 실패', 'error');
    }
}

// 마케팅 수집 상태 로드
async function loadMarketingCollectionStatus() {
    try {
        const resp = await fetch('/api/marketing/accounts-status');
        const data = await resp.json();
        if (data.success && data.status) {
            marketingCollectionStatus = data.status;
        }
    } catch (e) {
        console.error('마케팅 수집 상태 로드 오류:', e);
    }
}

// 필터 UI 생성
function createMarketingFilters() {
    const filterContainer = document.getElementById('marketingFilters');
    if (!filterContainer) return;

    // 소유자/용도 추출
    const owners = [...new Set(marketingAccountsData.map(a => a.소유자).filter(Boolean))];
    const usages = [...new Set(marketingAccountsData.map(a => a.용도).filter(Boolean))];

    let html = '<div class="filter-section">';

    // 소유자 필터
    if (owners.length > 0) {
        html += '<div class="filter-group"><label>소유자:</label>';
        owners.forEach(owner => {
            html += `<label><input type="checkbox" value="${owner}" checked onchange="applyMarketingFilters()"> ${owner}</label>`;
        });
        html += '</div>';
    }

    // 용도 필터
    if (usages.length > 0) {
        html += '<div class="filter-group"><label>용도:</label>';
        usages.forEach(usage => {
            html += `<label><input type="checkbox" value="${usage}" checked onchange="applyMarketingFilters()"> ${usage}</label>`;
        });
        html += '</div>';
    }

    html += '</div>';
    filterContainer.innerHTML = html;
}

// 필터 적용
function applyMarketingFilters() {
    // 선택된 소유자/용도
    const selectedOwners = Array.from(document.querySelectorAll('#marketingFilters .filter-group:nth-child(1) input:checked')).map(cb => cb.value);
    const selectedUsages = Array.from(document.querySelectorAll('#marketingFilters .filter-group:nth-child(2) input:checked')).map(cb => cb.value);
    const sortBy = document.getElementById('marketingSortBy')?.value || 'store_name';

    // 필터링
    let filtered = marketingAccountsData.filter(acc => {
        const ownerMatch = selectedOwners.length === 0 || selectedOwners.includes(acc.소유자);
        const usageMatch = selectedUsages.length === 0 || selectedUsages.includes(acc.용도);
        return ownerMatch && usageMatch;
    });

    // 정렬
    filtered.sort((a, b) => {
        if (sortBy === 'store_name') {
            return (a.스토어명 || '').localeCompare(b.스토어명 || '');
        } else if (sortBy === 'owner') {
            return (a.소유자 || '').localeCompare(b.소유자 || '');
        } else if (sortBy === 'usage') {
            return (a.용도 || '').localeCompare(b.용도 || '');
        }
        return 0;
    });

    renderMarketingAccounts(filtered);
}

// 계정 목록 렌더링
function renderMarketingAccounts(accounts = null) {
    const accountList = document.getElementById('marketingAccountList');
    const data = accounts || marketingAccountsData;

    if (data.length === 0) {
        accountList.innerHTML = '<div class="empty">필터 조건에 맞는 계정이 없습니다</div>';
        return;
    }

    // 테이블 형식으로 표시
    let html = `
        <div style="margin-bottom: 10px;">
            <input type="text" id="marketingSearchInput" placeholder="🔍 스토어명, 소유자, 용도 검색..."
                   style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px;"
                   onkeyup="searchMarketingAccounts()">
        </div>
        <table class="marketing-account-table">
            <thead>
                <tr>
                    <th><input type="checkbox" id="marketingSelectAllCb" onchange="toggleAllMarketingAccounts()"></th>
                    <th onclick="sortMarketingAccounts('스토어명')" style="cursor: pointer;">
                        스토어명 <span class="sort-arrow">↕</span>
                    </th>
                    <th onclick="sortMarketingAccounts('소유자')" style="cursor: pointer;">
                        소유자 <span class="sort-arrow">↕</span>
                    </th>
                    <th onclick="sortMarketingAccounts('용도')" style="cursor: pointer;">
                        용도 <span class="sort-arrow">↕</span>
                    </th>
                    <th>수집상태</th>
                    <th>로그인ID</th>
                </tr>
            </thead>
            <tbody id="marketingTableBody">
    `;

    data.forEach(acc => {
        const storeName = acc.스토어명 || '';
        const status = marketingCollectionStatus[storeName] || {};
        const isCollected = status.collected;
        const lastDate = status.last_date;

        let statusHtml = '';
        if (isCollected && lastDate) {
            statusHtml = `<span style="color: #4caf50;">✅ ${lastDate}</span>`;
        } else {
            statusHtml = `<span style="color: #f44336;">❌ 미수집</span>`;
        }

        html += `
            <tr>
                <td><input type="checkbox" value="${acc.login_id}" class="marketing-account-cb"></td>
                <td>${acc.스토어명 || '-'}</td>
                <td>${acc.소유자 || '-'}</td>
                <td>${acc.용도 || '-'}</td>
                <td>${statusHtml}</td>
                <td><small>${acc.login_id}</small></td>
            </tr>
        `;
    });

    html += '</tbody></table>';
    accountList.innerHTML = html;
}

// 검색 기능
let marketingSearchTerm = '';
function searchMarketingAccounts() {
    marketingSearchTerm = document.getElementById('marketingSearchInput').value.toLowerCase();
    applyMarketingFilters();
}

// 정렬 기능
let marketingSortColumn = '';
let marketingSortOrder = 'asc';

function sortMarketingAccounts(column) {
    if (marketingSortColumn === column) {
        marketingSortOrder = marketingSortOrder === 'asc' ? 'desc' : 'asc';
    } else {
        marketingSortColumn = column;
        marketingSortOrder = 'asc';
    }
    applyMarketingFilters();
}

// 필터 적용 (검색 + 정렬 통합)
function applyMarketingFilters() {
    // 선택된 소유자/용도
    const ownerCheckboxes = document.querySelectorAll('#marketingFilters .filter-group:nth-child(1) input[type="checkbox"]');
    const usageCheckboxes = document.querySelectorAll('#marketingFilters .filter-group:nth-child(2) input[type="checkbox"]');

    const selectedOwners = ownerCheckboxes.length > 0 ?
        Array.from(ownerCheckboxes).filter(cb => cb.checked).map(cb => cb.value) : [];
    const selectedUsages = usageCheckboxes.length > 0 ?
        Array.from(usageCheckboxes).filter(cb => cb.checked).map(cb => cb.value) : [];

    // 필터링
    let filtered = marketingAccountsData.filter(acc => {
        // 소유자/용도 필터
        const ownerMatch = selectedOwners.length === 0 || selectedOwners.includes(acc.소유자);
        const usageMatch = selectedUsages.length === 0 || selectedUsages.includes(acc.용도);

        // 검색어 필터
        let searchMatch = true;
        if (marketingSearchTerm) {
            const storeName = (acc.스토어명 || '').toLowerCase();
            const owner = (acc.소유자 || '').toLowerCase();
            const usage = (acc.용도 || '').toLowerCase();
            const loginId = (acc.login_id || '').toLowerCase();
            searchMatch = storeName.includes(marketingSearchTerm) ||
                owner.includes(marketingSearchTerm) ||
                usage.includes(marketingSearchTerm) ||
                loginId.includes(marketingSearchTerm);
        }

        return ownerMatch && usageMatch && searchMatch;
    });

    // 정렬
    if (marketingSortColumn) {
        filtered.sort((a, b) => {
            const aVal = (a[marketingSortColumn] || '').toString();
            const bVal = (b[marketingSortColumn] || '').toString();
            const compareResult = aVal.localeCompare(bVal);
            return marketingSortOrder === 'asc' ? compareResult : -compareResult;
        });
    }

    renderMarketingAccounts(filtered);
}

// 전체 선택/해제
function toggleAllMarketingAccounts() {
    const selectAll = document.getElementById('marketingSelectAllCb');
    const checkboxes = document.querySelectorAll('.marketing-account-cb');
    checkboxes.forEach(cb => cb.checked = selectAll.checked);
}

// 탭 전환 시 계정 로드
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            if (tab.dataset.tab === 'marketing') {
                loadMarketingAccounts();
            }
        });
    });
});


// ========== HTML 마크업 (index.html에 추가) ==========
/*
<div id="tab-marketing" class="tab-content">
    <div class="marketing-container">
        <h2>📊 마케팅 분석 데이터 수집</h2>
        
        <div class="info-box">
            <strong>💡 통합 시트 방식</strong><br>
            모든 계정의 마케팅 데이터가 하나의 "전체데이터" 시트에 누적됩니다.<br>
            스프레드시트 ID는 .env 파일의 MARKETING_SPREADSHEET_ID에 설정하세요.
        </div>
        
        <div class="section">
            <div class="section-header">
                <h3>계정 선택</h3>
                <div class="button-group">
                    <button id="marketingSelectAll" class="btn-secondary">전체 선택/해제</button>
                    <button onclick="initializeMarketingSheets()" class="btn-secondary">
                        🔧 스프레드시트 초기화
                    </button>
                </div>
            </div>
            <div id="marketingAccountList" class="account-list">
                <!-- 계정 목록 동적 생성 -->
            </div>
        </div>
        
        <div class="section">
            <div class="action-buttons">
                <button id="marketingStartBtn" onclick="startMarketingCollection()" class="btn btn-primary">
                    ▶ 수집 시작
                </button>
                <button id="marketingStopBtn" onclick="stopMarketingCollection()" class="btn btn-danger" disabled>
                    ■ 중지
                </button>
            </div>
        </div>
        
        <div class="section">
            <h3>진행 상황</h3>
            <div id="marketingStatus" class="status-text">대기 중</div>
            <div class="progress-bar-container">
                <div id="marketingProgressBar" class="progress-bar">0 / 0</div>
            </div>
        </div>
        
        <div class="section">
            <h3>실행 로그</h3>
            <textarea id="marketingLogArea" class="log-area" readonly></textarea>
        </div>
    </div>
</div>
*/

// ========== 작업달력 ==========
let currentCalendarYear = new Date().getFullYear();
let currentCalendarMonth = new Date().getMonth() + 1;
let calendarLogs = [];
let calendarFilter = 'all';

function loadWorkCalendar() {
    fetch(`/api/work-log/calendar?year=${currentCalendarYear}&month=${currentCalendarMonth}`)
        .then(r => r.json())
        .then(data => {
            calendarLogs = data.logs || [];
            renderCalendar();
            loadCalendarStats();
        })
        .catch(err => console.error('작업 로그 로드 실패:', err));
}

function loadCalendarStats() {
    fetch(`/api/work-log/stats?year=${currentCalendarYear}&month=${currentCalendarMonth}`)
        .then(r => r.json())
        .then(data => {
            document.getElementById('statTotalWorks').textContent = data.total_works || 0;
            document.getElementById('statDeletedProducts').textContent = (data.deleted_products || 0).toLocaleString();
            document.getElementById('statUploadedProducts').textContent = (data.uploaded_products || 0).toLocaleString();
            document.getElementById('statProcessedAccounts').textContent = data.processed_accounts || 0;
        })
        .catch(err => console.error('통계 로드 실패:', err));
}

function renderCalendar() {
    const grid = document.getElementById('workCalendarGrid');
    if (!grid) return;

    // 월 표시 업데이트
    document.getElementById('calendarCurrentMonth').textContent = `${currentCalendarYear}년 ${currentCalendarMonth}월`;

    // 해당 월의 첫날과 마지막날
    const firstDay = new Date(currentCalendarYear, currentCalendarMonth - 1, 1);
    const lastDay = new Date(currentCalendarYear, currentCalendarMonth, 0);
    const daysInMonth = lastDay.getDate();
    const startDayOfWeek = firstDay.getDay(); // 0(일) ~ 6(토)

    // 이전 달 마지막 날들
    const prevMonthLastDay = new Date(currentCalendarYear, currentCalendarMonth - 1, 0).getDate();

    // 오늘 날짜
    const today = new Date();
    const isCurrentMonth = (today.getFullYear() === currentCalendarYear && today.getMonth() + 1 === currentCalendarMonth);
    const todayDate = today.getDate();

    let html = '';

    // 요일 헤더
    ['일', '월', '화', '수', '목', '금', '토'].forEach(day => {
        html += `<div class="calendar-header">${day}</div>`;
    });

    // 이전 달 날짜들
    for (let i = startDayOfWeek - 1; i >= 0; i--) {
        const day = prevMonthLastDay - i;
        html += `<div class="calendar-day other-month"><div class="day-number">${day}</div></div>`;
    }

    // 현재 달 날짜들
    for (let day = 1; day <= daysInMonth; day++) {
        const dateStr = `${currentCalendarYear}-${String(currentCalendarMonth).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        const isToday = isCurrentMonth && day === todayDate;

        // 해당 날짜의 작업들
        const dayLogs = calendarLogs.filter(log => log.datetime.startsWith(dateStr));

        // 필터 적용
        const filteredLogs = calendarFilter === 'all'
            ? dayLogs
            : dayLogs.filter(log => log.work_type === calendarFilter);

        // 작업 내용 칸 안에 직접 표시 (최대 3개)
        let workItemsHTML = '';
        if (filteredLogs.length > 0) {
            const displayCount = 3; // 최대 3개 표시
            const displayLogs = filteredLogs.slice(0, displayCount);

            workItemsHTML = '<div class="work-items">';
            displayLogs.forEach(log => {
                const time = log.datetime.split(' ')[1]?.substring(0, 5) || ''; // HH:MM
                const account = log.account || '';
                const workType = log.work_type || '';
                workItemsHTML += `<div class="work-item">[${time}] ${account}-${workType}</div>`;
            });

            // 나머지 개수 표시
            if (filteredLogs.length > displayCount) {
                workItemsHTML += `<div class="work-more">+${filteredLogs.length - displayCount}개 더</div>`;
            }
            workItemsHTML += '</div>';
        }

        html += `
            <div class="calendar-day ${isToday ? 'today' : ''}" onclick="showDayWorks('${dateStr}')">
                <div class="day-number">${day}</div>
                ${workItemsHTML}
            </div>
        `;
    }

    // 다음 달 날짜들
    const totalCells = Math.ceil((startDayOfWeek + daysInMonth) / 7) * 7;
    const remainingCells = totalCells - (startDayOfWeek + daysInMonth);
    for (let day = 1; day <= remainingCells; day++) {
        html += `<div class="calendar-day other-month"><div class="day-number">${day}</div></div>`;
    }

    grid.innerHTML = html;
}

function prevCalendarMonth() {
    currentCalendarMonth--;
    if (currentCalendarMonth < 1) {
        currentCalendarMonth = 12;
        currentCalendarYear--;
    }
    loadWorkCalendar();
}

function nextCalendarMonth() {
    currentCalendarMonth++;
    if (currentCalendarMonth > 12) {
        currentCalendarMonth = 1;
        currentCalendarYear++;
    }
    loadWorkCalendar();
}

function filterCalendarWork(type) {
    calendarFilter = type;

    // 필터 버튼 활성화 상태 변경
    document.querySelectorAll('#tab-work-calendar .filter-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.filter === type) {
            btn.classList.add('active');
        }
    });

    renderCalendar();
}

function showDayWorks(dateStr) {
    console.log('[디버그] 조회할 날짜:', dateStr);

    fetch(`/api/work-log/day?date=${dateStr}`)
        .then(r => r.json())
        .then(data => {
            console.log('[디버그] API 응답:', data);

            const logs = data.logs || [];

            if (logs.length === 0) {
                showToast('해당 날짜에 작업 기록이 없습니다.', 'info');
                return;
            }

            const dateObj = new Date(dateStr);
            const dateText = `${dateObj.getFullYear()}년 ${dateObj.getMonth() + 1}월 ${dateObj.getDate()}일`;

            const detail = logs.map(log => {
                const time = log.datetime.split(' ')[1] || '';
                const typeColors = {
                    '상품삭제': '#f44336',
                    '상품등록': '#4CAF50',
                    '상품수정': '#ff9800',
                    '마케팅수집': '#9c27b0',
                    '예약작업': '#009688'
                };
                const color = typeColors[log.work_type] || '#2196F3';

                return `
                    <div style="background: #f9f9f9; padding: 12px; border-radius: 6px; margin-bottom: 10px; border-left: 3px solid ${color};">
                        <div style="display: flex; justify-content: space-between; margin-bottom: 8px; align-items: center;">
                            <div>
                                <span style="font-weight: 600; color: ${color};">${log.work_type}</span>
                                <span style="color: #666; font-size: 13px; margin-left: 10px;">${time}</span>
                            </div>
                            <div style="display: flex; gap: 5px;">
                                <button onclick='editWork(${JSON.stringify(log)})' style="padding: 4px 10px; background: #2196F3; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px;">✏️ 수정</button>
                                <button onclick='deleteWork("${log.datetime}")' style="padding: 4px 10px; background: #f44336; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px;">🗑️ 삭제</button>
                            </div>
                        </div>
                        <div style="font-size: 13px; color: #555; line-height: 1.6;">
                            <strong>${log.account}</strong><br>
                            ${log.count > 0 ? `• 처리 수: ${log.count}개<br>` : ''}
                            ${log.detail ? `• ${log.detail}<br>` : ''}
                            ${log.method ? `• 실행: ${log.method}` : ''}
                        </div>
                    </div>
                `;
            }).join('');

            showModal(`${dateText} 작업 내역 (${logs.length}건)`, detail);
        })
        .catch(err => console.error('일별 로그 조회 실패:', err));
}

// 탭 전환 시 작업달력 로드
(function () {
    // 페이지 로드 시 또는 즉시 실행
    const setupCalendarTab = function () {
        const originalSwitchTab = window.switchTab;
        if (typeof originalSwitchTab === 'function') {
            window.switchTab = function (tabName) {
                originalSwitchTab(tabName);
                if (tabName === 'work-calendar') {
                    setTimeout(function () {
                        loadWorkCalendar();
                    }, 100);
                }
            };
        }
    };

    // 즉시 실행
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupCalendarTab);
    } else {
        setupCalendarTab();
    }

    // 탭 클릭 이벤트 리스너도 추가 (백업)
    document.addEventListener('click', function (e) {
        const tab = e.target.closest('[data-tab="work-calendar"]');
        if (tab) {
            setTimeout(function () {
                loadWorkCalendar();
            }, 100);
        }
    });
})();

// 공용 모달창 표시 함수 (캘린더 상세 등)
function showModal(title, content) {
    let modal = document.getElementById('commonModal');
    if (!modal) {
        // 모달 HTML 동적 생성
        const div = document.createElement('div');
        div.id = 'commonModal';
        div.className = 'modal';
        div.style.display = 'none';
        // 배경 클릭 시 닫기
        div.onclick = function (e) {
            if (e.target === div) {
                closeCommonModal();
            }
        };
        div.innerHTML = `
            <div class="modal-content" style="position: relative;">
                <div class="modal-header">
                    <h2 id="commonModalTitle"></h2>
                    <button class="close-btn" onclick="closeCommonModal()" style="position: absolute; right: 15px; top: 15px; font-size: 28px; background: none; border: none; cursor: pointer; color: #666; line-height: 1; padding: 0; width: 30px; height: 30px;">&times;</button>
                </div>
                <div class="modal-body" id="commonModalBody" style="max-height: 70vh; overflow-y: auto;"></div>
            </div>
        `;
        document.body.appendChild(div);
        modal = div;
    }

    document.getElementById('commonModalTitle').textContent = title;
    document.getElementById('commonModalBody').innerHTML = content;
    modal.style.display = 'flex';

    // ESC 키로 닫기
    const escHandler = function (e) {
        if (e.key === 'Escape') {
            closeCommonModal();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);
}

function closeCommonModal() {
    const modal = document.getElementById('commonModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// 작업 추가 모달
function showAddWorkModal() {
    const modal = document.getElementById('addWorkModal');
    if (!modal) return;

    // 현재 날짜/시간으로 초기화
    const now = new Date();
    document.getElementById('workDate').value = now.toISOString().split('T')[0];
    document.getElementById('workTime').value = now.toTimeString().slice(0, 5);

    // 폼 초기화
    document.getElementById('addWorkForm').reset();
    document.getElementById('workDate').value = now.toISOString().split('T')[0];
    document.getElementById('workTime').value = now.toTimeString().slice(0, 5);

    modal.style.display = 'flex';
}

// 작업 수정
let editingWorkDatetime = null;

function editWork(log) {
    // 상세 팝업 먼저 닫기
    closeCommonModal();

    const modal = document.getElementById('addWorkModal');
    if (!modal) return;

    // 수정 모드로 전환
    editingWorkDatetime = log.datetime;

    // 폼 채우기
    const [date, time] = log.datetime.split(' ');
    document.getElementById('workDate').value = date;
    document.getElementById('workTime').value = time.slice(0, 5);
    document.getElementById('workType').value = log.work_type;
    document.getElementById('workAccount').value = log.account;
    document.getElementById('workCount').value = log.count || '';
    document.getElementById('workDetail').value = log.detail || '';
    document.getElementById('workMethod').value = log.method || '';

    // 모달 제목 변경
    modal.querySelector('.modal-header h2').textContent = '✏️ 작업 수정';

    // 모달 열기
    modal.style.display = 'flex';
}

function closeAddWorkModal() {
    const modal = document.getElementById('addWorkModal');
    if (modal) {
        modal.style.display = 'none';
        // 제목 원래대로
        modal.querySelector('.modal-header h2').textContent = '➕ 작업 추가';
        editingWorkDatetime = null;
    }
}

function submitAddWork(event) {
    event.preventDefault();

    const date = document.getElementById('workDate').value;
    const time = document.getElementById('workTime').value;
    const workType = document.getElementById('workType').value;
    const account = document.getElementById('workAccount').value;
    const count = parseInt(document.getElementById('workCount').value) || 0;
    const detail = document.getElementById('workDetail').value;
    const method = document.getElementById('workMethod').value;
    const datetime = `${date} ${time}:00`;

    if (editingWorkDatetime) {
        // 수정 모드
        fetch('/api/work-log/update', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                datetime: editingWorkDatetime,
                work_type: workType,
                account: account,
                count: count,
                detail: detail,
                method: method,
                new_datetime: datetime
            })
        })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    showToast('✅ 작업이 수정되었습니다', 'success');
                    closeAddWorkModal();
                    loadWorkCalendar();
                } else {
                    showToast('❌ ' + (data.message || '작업 수정 실패'), 'error');
                }
            })
            .catch(err => {
                console.error('작업 수정 실패:', err);
                showToast('❌ 오류 발생', 'error');
            });
    } else {
        // 추가 모드 (기존 코드)
        fetch('/api/work-log/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                work_type: workType,
                account: account,
                count: count,
                detail: detail,
                method: method,
                datetime: datetime
            })
        })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    showToast('✅ 작업이 추가되었습니다', 'success');
                    closeAddWorkModal();
                    loadWorkCalendar();
                } else {
                    showToast('❌ 작업 추가 실패', 'error');
                }
            })
            .catch(err => {
                console.error('작업 추가 실패:', err);
                showToast('❌ 오류 발생', 'error');
            });
    }
}

// 작업 삭제
function deleteWork(datetime) {
    if (!confirm('이 작업을 삭제하시겠습니까?')) {
        return;
    }

    fetch('/api/work-log/delete', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            datetime: datetime
        })
    })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                showToast('✅ 작업이 삭제되었습니다', 'success');
                // 모달 닫기
                document.querySelectorAll('.modal').forEach(m => {
                    m.classList.remove('active');
                    m.style.display = 'none';
                });
                loadWorkCalendar();
            } else {
                showToast('❌ ' + (data.message || '작업 삭제 실패'), 'error');
            }
        })
        .catch(err => {
            console.error('작업 삭제 실패:', err);
            showToast('❌ 오류 발생', 'error');
        });
}

// ========== 일일장부 동기화 기능 ==========
let syncIsRunning = false;
let syncPollInterval = null;

function saveSyncSheetUrl() {
    const url = document.getElementById('syncSheetUrl').value.trim();
    if (!url) return;
    localStorage.setItem('syncOrderSheetUrl', url);
    showToast('동기화 시트 URL 저장됨', 'success');
}

function loadSyncSheetUrl() {
    const url = localStorage.getItem('syncOrderSheetUrl');
    if (url && document.getElementById('syncSheetUrl')) {
        document.getElementById('syncSheetUrl').value = url;
    }
}

function clearSyncLog() {
    const logContent = document.getElementById('syncLogContent');
    if (logContent) logContent.innerHTML = '';
}

function addSyncLog(msg, type = 'info') {
    const logContent = document.getElementById('syncLogContent');
    if (!logContent) return;

    const div = document.createElement('div');
    const now = new Date().toLocaleTimeString();
    div.style.color = type === 'error' ? '#e74c3c' : (type === 'success' ? '#2ecc71' : '#333');
    div.textContent = `[${now}] ${msg}`;
    logContent.appendChild(div);
    logContent.scrollTop = logContent.scrollHeight;
}

async function startDailySync() {
    const sheetUrl = document.getElementById('syncSheetUrl').value.trim();
    const month = document.getElementById('syncMonth').value;
    const syncOrderInfo = document.getElementById('syncOrderInfo').checked;
    const syncLogistics = document.getElementById('syncLogistics').checked;
    const fileInput = document.getElementById('syncSourceFile');

    if (!sheetUrl) {
        showToast('일일장부 시트 URL을 입력해주세요.', 'warning');
        return;
    }

    if (!fileInput.files || fileInput.files.length === 0) {
        showToast('동기화할 소스 데이터 파일(Excel/CSV)을 선택해주세요.', 'warning');
        return;
    }

    if (!syncOrderInfo && !syncLogistics) {
        showToast('동기화할 항목을 최소 하나 이상 선택해주세요.', 'warning');
        return;
    }

    if (!confirm(`${month} 데이터를 업로드한 파일 기준으로 동기화하시겠습니까?`)) return;

    syncIsRunning = true;
    document.getElementById('syncStartBtn').disabled = true;
    document.getElementById('syncStopBtn').disabled = false;
    updateSyncStatus('running', '동기화 중...');
    clearSyncLog();
    addSyncLog(`${month} 동기화 시작 (파일 기반)...`, 'info');

    try {
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('sheet_url', sheetUrl);
        formData.append('month', month);
        formData.append('sync_order_info', syncOrderInfo);
        formData.append('sync_logistics', syncLogistics);

        const r = await fetch('/api/sync/daily-journal', {
            method: 'POST',
            body: formData
        });

        const d = await r.json();
        if (d.success) {
            addSyncLog('파일 업로드 완료 및 동기화 작업 시작.', 'success');
            pollSyncStatus();
        } else {
            addSyncLog('동기화 시작 실패: ' + d.message, 'error');
            stopDailySync();
        }
    } catch (e) {
        addSyncLog('오류 발생: ' + e.message, 'error');
        stopDailySync();
    }
}

function stopDailySync() {
    syncIsRunning = false;
    document.getElementById('syncStartBtn').disabled = false;
    document.getElementById('syncStopBtn').disabled = true;
    updateSyncStatus('ready', '준비');
    if (syncPollInterval) {
        clearInterval(syncPollInterval);
        syncPollInterval = null;
    }
}

function updateSyncStatus(state, text) {
    const dot = document.querySelector('#syncStatus .status-dot');
    const txt = document.querySelector('#syncStatus .status-text');
    if (!dot || !txt) return;

    dot.className = 'status-dot ' + state;
    txt.textContent = text;
}

async function pollSyncStatus() {
    if (syncPollInterval) clearInterval(syncPollInterval);

    syncPollInterval = setInterval(async () => {
        if (!syncIsRunning) return;

        try {
            const r = await fetch('/api/sync/status');
            const d = await r.json();

            if (d.logs && d.logs.length > 0) {
                d.logs.forEach(log => {
                    addSyncLog(log.message, log.type);
                });
            }

            if (d.status === 'completed') {
                addSyncLog('동기화 완료!', 'success');
                showToast('동기화가 완료되었습니다.', 'success');
                stopDailySync();
            } else if (d.status === 'error') {
                addSyncLog('동기화 중단됨 (오류 발생)', 'error');
                showToast('동기화 중 오류가 발생했습니다.', 'danger');
                stopDailySync();
            }
        } catch (e) {
            console.error('동기화 상태 조회 오류:', e);
        }
    }, 2000);
}

// 초기화 시 로드 (DOM이 이미 로드되었을 수 있으므로 즉시 실행 포함)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadSyncSheetUrl);
} else {
    loadSyncSheetUrl();
}
