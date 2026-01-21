// 초기 서버 설정 (기본값)
let SERVER_HOST = 'http://182.222.231.21';
let SERVER_PORT = '8080';
let API_KEY = 'pkonomiautokey2024';

// 동적 URL 생성 함수
function getServerUrl() {
  return `${SERVER_HOST}:${SERVER_PORT}`;
}

// 전역 변수
let accounts = [];
let authCodes = {};

// 한글 우선 + 영어 fallback 헬퍼 함수
function getStoreName(acc) {
  return acc['스토어명'] || acc.shop_alias || acc.store_name || acc['아이디'] || acc.login_id || '';
}

function getLoginId(acc) {
  return acc['아이디'] || acc.login_id || '';
}

function getPlatform(acc) {
  return acc['플랫폼'] || acc.platform || '';
}

// API 요청 헬퍼
async function apiRequest(endpoint, options = {}) {
  const url = `${getServerUrl()}${endpoint}`;
  const defaultOptions = {
    headers: {
      'X-API-Key': API_KEY,
      ...(options.headers || {})
    }
  };
  try {
    return await fetch(url, { ...defaultOptions, ...options });
  } catch (e) {
    throw e;
  }
}

// 설정 불러오기
async function loadConfig() {
  return new Promise((resolve) => {
    chrome.storage.local.get(['serverHost', 'serverPort'], (result) => {
      if (result.serverHost) SERVER_HOST = result.serverHost;
      if (result.serverPort) SERVER_PORT = result.serverPort;
      resolve();
    });
  });
}

// 설정 저장하기
async function saveConfig() {
  const hostInput = document.getElementById('cfgHost');
  const portInput = document.getElementById('cfgPort');
  
  const newHost = hostInput.value.trim() || 'http://182.222.231.21';
  const newPort = portInput.value.trim() || '8080';
  
  // 저장
  await chrome.storage.local.set({
    serverHost: newHost,
    serverPort: newPort
  });
  
  // 변수 업데이트
  SERVER_HOST = newHost;
  SERVER_PORT = newPort;
  
  alert('설정이 저장되었습니다. 다시 연결합니다.');
  
  // 재연결 시도
  connectServer();
}

// 초기화
document.addEventListener('DOMContentLoaded', async () => {
  // 설정 로드
  await loadConfig();

  // 계정 검색창 자동 포커스
  const searchInput = document.getElementById('searchInput');
  if (searchInput) {
    setTimeout(() => searchInput.focus(), 50);
  }

  // 설정 UI 초기값 세팅
  const hostDevice = document.getElementById('cfgHost');
  if (hostDevice) hostDevice.value = SERVER_HOST;
  
  const portDevice = document.getElementById('cfgPort');
  if (portDevice) portDevice.value = SERVER_PORT;

  // 탭 이벤트
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
    });
  });
  
  // 바로가기 버튼 이벤트
  document.querySelectorAll('.shortcut-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tabName = btn.dataset.tab;
      // 익스텐션 설정 탭으로 이동하는 경우 (ext-config로 분리)
      if (tabName === 'ext-config') {
         document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
         document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

         const configTab = document.querySelector('.tab[data-tab="config"]');
         if (configTab) configTab.classList.add('active');

         const configContent = document.getElementById('tab-config');
         if (configContent) configContent.classList.add('active');
         return;
      }

      // 나머지는 웹서버 탭 열기 (settings 포함)
      if (tabName) {
        openTab(tabName);
      }
    });
  });
  
  // 설정 저장 버튼
  const saveBtn = document.getElementById('saveConfigBtn');
  if (saveBtn) {
      saveBtn.addEventListener('click', saveConfig);
  }
  
  // 플랫폼 필터
  document.getElementById('platformFilter').addEventListener('change', renderAccounts);
  
  // 검색
  document.getElementById('searchInput').addEventListener('input', renderAccounts);

  // 인증코드 새로고침 (수동 - SMS 메시지도 새로고침)
  document.getElementById('refreshCodeBtn').addEventListener('click', manualRefreshAuthCode);
  
  // 인증코드 입력
  document.getElementById('inputCodeBtn').addEventListener('click', inputAuthCode);
  
  // 자동 연결
  await connectServer();
  
  // 인증코드 자동 새로고침 (3초마다)
  setInterval(refreshAuthCode, 3000);
  
  // 팝업 열 때 대기 중인 자동로그인 한 번 체크
  await checkPendingLogin();
});

// 대기 중인 자동 로그인 확인
async function checkPendingLogin() {
  try {
    const response = await apiRequest('/api/auto-login/pending');
    if (!response.ok) return;
    
    const data = await response.json();
    if (data.platform && data.login_id && data.password) {
      console.log('[자동로그인] 대기 정보 발견:', data.platform, data.login_id);
      
      // 로그인 정보 저장 (content script에서 사용)
      await chrome.storage.local.set({
        pendingLogin: {
          platform: data.platform,
          login_id: data.login_id,
          password: data.password
        }
      });
      
      // 새 탭에서 열기
      chrome.tabs.create({ url: data.url }, () => {
        const statusEl = document.getElementById('serverStatus');
        if (statusEl) {
          statusEl.className = 'status success';
          statusEl.textContent = `✅ ${data.platform} 로그인 진행 중...`;
        }
      });
    }
  } catch (e) {
    // 무시
  }
}

// 서버 연결
async function connectServer() {
  const statusEl = document.getElementById('serverStatus');
  statusEl.className = 'status info';
  statusEl.textContent = `🔄 연결 중... (${SERVER_PORT})`;
  
  try {
    const response = await apiRequest('/api/accounts');
    
    if (!response.ok) {
      statusEl.className = 'status error';
      statusEl.textContent = '❌ 연결 실패 (인증 오류)';
      return;
    }
    
    const data = await response.json();
    accounts = data.accounts || [];
    
    statusEl.className = 'status success';
    statusEl.textContent = `✅ 연결됨 (${accounts.length}개 계정)`;
    
    renderAccounts();
    refreshAuthCode();
    
  } catch (e) {
    statusEl.className = 'status error';
    statusEl.textContent = '❌ 서버 연결 실패';
    console.error('연결 오류:', e);
  }
}

// 계정 목록 렌더링
function renderAccounts() {
  const filter = document.getElementById('platformFilter').value;
  const search = document.getElementById('searchInput').value.toLowerCase();
  
  let filtered = accounts;
  
  // 플랫폼 필터
  if (filter) {
    filtered = filtered.filter(a => a.platform === filter);
  }
  
  // 검색 필터
  if (search) {
    filtered = filtered.filter(a => 
      getStoreName(a).toLowerCase().includes(search) ||
      getLoginId(a).toLowerCase().includes(search)
    );
  }
  
  const listEl = document.getElementById('accountList');
  
  if (filtered.length === 0) {
    listEl.innerHTML = '<div class="loading">계정이 없습니다</div>';
    return;
  }
  
  const platformColors = {
    '스마트스토어': 'ss',
    '쿠팡': 'cp',
    '11번가': 'st',
    '지마켓': 'gm',
    '옥션': 'ac'
  };
  
  listEl.innerHTML = filtered.map((acc, idx) => `
    <div class="account-item">
      <div class="info">
        <span class="platform-badge ${platformColors[getPlatform(acc)] || ''}">${getPlatform(acc)}</span>
        <span class="shop">${getStoreName(acc)}</span>
        <div class="id">${getLoginId(acc)}</div>
      </div>
      <button class="login-btn" data-platform="${getPlatform(acc)}" data-id="${getLoginId(acc)}">🚀 로그인</button>
    </div>
  `).join('');
  
  // 로그인 버튼 이벤트
  listEl.querySelectorAll('.login-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      doLogin(btn.dataset.platform, btn.dataset.id);
    });
  });
}

// 로그인 실행
async function doLogin(platform, loginId) {
  const statusEl = document.getElementById('serverStatus');
  statusEl.className = 'status info';
  statusEl.textContent = '🔄 자동 로그인 시작...';
  
  // 계정 정보 가져오기
  const account = accounts.find(a => a.platform === platform && a.login_id === loginId);
  if (!account) {
    statusEl.className = 'status error';
    statusEl.textContent = '❌ 계정을 찾을 수 없습니다';
    return;
  }
  
  // 플랫폼별 URL
  const urls = {
    '스마트스토어': 'https://accounts.commerce.naver.com/login?url=https%3A%2F%2Fsell.smartstore.naver.com%2F%23%2Flogin-callback',
    '쿠팡': 'https://xauth.coupang.com/auth/realms/seller/protocol/openid-connect/auth?response_type=code&client_id=wing&redirect_uri=https%3A%2F%2Fwing.coupang.com%2Fsso%2Flogin%3FreturnUrl%3D%252F&state=login&login=true&scope=openid',
    '11번가': 'https://login.11st.co.kr/auth/front/selleroffice/login.tmall',
    '지마켓': 'https://signin.esmplus.com/login',
    '옥션': 'https://signin.esmplus.com/login'
  };
  
  const url = urls[platform];
  if (!url) {
    statusEl.className = 'status error';
    statusEl.textContent = '❌ 지원하지 않는 플랫폼';
    return;
  }
  
  // 로그인 정보 저장 (content script에서 사용)
  await chrome.storage.local.set({
    pendingLogin: {
      platform,
      login_id: account.login_id,
      password: account.password
    }
  });
  
  // 새 탭에서 열기
  chrome.tabs.create({ url }, () => {
    statusEl.className = 'status success';
    statusEl.textContent = '✅ 로그인 진행 중...';
  });
}

// 현재 최신 인증코드
let currentAuthCode = null;
let currentAuthTime = null;

// 인증코드 새로고침 (최신 코드만 - 자동 호출용)
async function refreshAuthCode() {
  const codeEl = document.getElementById('authCode');
  const timeEl = document.getElementById('authTime');

  try {
    const response = await apiRequest('/api/sms/auth-code');

    if (!response.ok) {
      return;
    }

    const data = await response.json();
    currentAuthCode = data.code;
    currentAuthTime = data.time;

    codeEl.textContent = currentAuthCode || '------';
    timeEl.textContent = currentAuthTime ? `수신 시간: ${currentAuthTime}` : '수신 시간: -';

  } catch (e) {
    // 무시
  }
}

// 수동 새로고침 (버튼 클릭 시 - SMS 메시지도 새로고침)
async function manualRefreshAuthCode() {
  const codeEl = document.getElementById('authCode');
  const timeEl = document.getElementById('authTime');

  // 로딩 표시
  codeEl.textContent = '로딩...';

  try {
    // 1. SMS 메시지 새로고침 (서버에서 실제로 수집)
    await apiRequest('/api/sms/messages?refresh=true');

    // 2. 인증코드 가져오기
    const response = await apiRequest('/api/sms/auth-code');

    if (!response.ok) {
      codeEl.textContent = '오류';
      return;
    }

    const data = await response.json();
    currentAuthCode = data.code;
    currentAuthTime = data.time;

    codeEl.textContent = currentAuthCode || '------';
    timeEl.textContent = currentAuthTime ? `수신 시간: ${currentAuthTime}` : '수신 시간: -';

  } catch (e) {
    codeEl.textContent = '오류';
    console.error('새로고침 오류:', e);
  }
}

// 인증코드 입력
async function inputAuthCode() {
  if (!currentAuthCode || currentAuthCode === '------') {
    showAuthMessage('인증코드가 없습니다', 'error');
    return;
  }
  
  // 현재 탭에 인증코드 입력 메시지 전송
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  
  chrome.tabs.sendMessage(tab.id, {
    action: 'inputAuthCode',
    code: currentAuthCode
  }, (response) => {
    if (chrome.runtime.lastError) {
      showAuthMessage('페이지에서 사용 불가', 'error');
      return;
    }
    
    if (response && response.success) {
      showAuthMessage('인증코드 입력 완료!', 'success');
    }
  });
}

// 인증 메시지 표시 (팝업 내)
function showAuthMessage(msg, type) {
  const msgEl = document.getElementById('authMessage');
  if (msgEl) {
    msgEl.textContent = msg;
    msgEl.style.color = type === 'error' ? '#e53935' : '#43a047';
    msgEl.style.display = 'block';
    setTimeout(() => { msgEl.style.display = 'none'; }, 2000);
  }
}

// ========== 불사자 실행 (삭제 or 유지? 일단 유지) ==========
// ... (기존 코드 참고 / 필요없으면 제거 가능하나 안전하게 유지)

// ========== 바로가기 ==========
function openTab(tabName) {
  const url = `${getServerUrl()}/#${tabName}`;
  chrome.tabs.create({ url: url });
}
