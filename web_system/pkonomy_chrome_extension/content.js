// Content Script - 완전 자동 로그인 시스템
// 기능: ID/PW 자동 입력, 로그인 클릭, 2차 인증 자동 처리, 비밀번호 변경 자동 처리

const SERVER_URL = 'http://182.222.231.21:8080';
const API_KEY = 'pkonomiautokey2024';
let loginInfo = null;
let authCheckInterval = null;
let authAttempts = 0;
const MAX_AUTH_ATTEMPTS = 30; // 30초 대기
let loginStartTime = null; // 자동로그인 시작 시간

// API 요청 헬퍼
async function apiRequest(endpoint, options = {}) {
  const url = `${SERVER_URL}${endpoint}`;
  const defaultOptions = {
    headers: {
      'X-API-Key': API_KEY,
      ...(options.headers || {})
    }
  };
  return fetch(url, { ...defaultOptions, ...options });
}

// ========== 메인 실행 ==========
(async function() {
  console.log('[자동로그인] 시작:', window.location.href);
  
  // 로그인 시작 시간 저장
  loginStartTime = new Date();
  console.log('[자동로그인] 시작 시간:', loginStartTime.toISOString());
  
  const url = window.location.href;
  
  // 11번가 셀러오피스 2FA 페이지 (로그인 정보 없어도 처리)
  if (url.includes('selleroffice.11st.co.kr') || url.includes('soffice.11st.co.kr')) {
    if (detect2FAPage()) {
      console.log('[11번가] 2단계 인증 페이지 감지');
      await handle11st2FA();
      return;
    }
  }
  
  // 저장된 로그인 정보 확인
  const stored = await chrome.storage.local.get(['pendingLogin']);
  loginInfo = stored.pendingLogin;
  
  if (!loginInfo) {
    console.log('[자동로그인] 대기 중인 로그인 정보 없음');
    return;
  }
  
  console.log('[자동로그인] 플랫폼:', loginInfo.platform);
  
  // 페이지 로드 대기
  await sleep(1500);
  
  // 비밀번호 변경 페이지 감지
  if (detectPasswordChangePage()) {
    console.log('[비밀번호 변경] 페이지 감지');
    await handlePasswordChange();
    return;
  }
  
  // 2차 인증 페이지 감지
  if (detect2FAPage()) {
    console.log('[2차 인증] 페이지 감지');
    await handle2FAPage();
    return;
  }
  
  // 로그인 페이지 처리
  const platform = loginInfo.platform;
  
  if (platform === '스마트스토어' && (url.includes('accounts.commerce.naver.com') || url.includes('nid.naver.com'))) {
    await handleSmartStore();
  } else if (platform === '쿠팡' && (url.includes('xauth.coupang.com') || url.includes('wing.coupang.com'))) {
    await handleCoupang();
  } else if (platform === '11번가' && url.includes('login.11st.co.kr')) {
    await handle11st();
  } else if (['ESM통합', '지마켓', '옥션'].includes(platform) && url.includes('signin.esmplus.com')) {
    await handleESM(platform);
  }
  
  // 로그인 후 2차 인증 감지 (3초 후부터)
  setTimeout(() => {
    if (detect2FAPage()) {
      console.log('[2차 인증] 로그인 후 감지');
      handle2FAPage();
    }
  }, 3000);
})();

// ========== 플랫폼별 로그인 ==========

async function handleSmartStore() {
  console.log('[스마트스토어] 로그인 시작, URL:', window.location.href);
  const url = window.location.href;
  
  // 1. nid.naver.com (네이버 일반 로그인)
  if (url.includes('nid.naver.com')) {
    console.log('[스마트스토어] 네이버 일반 로그인 페이지 감지');
    
    const idInput = await waitForElement('input[id="id"], input[name="id"]', 5000);
    const pwInput = document.querySelector('input[id="pw"], input[name="pw"], input[type="password"]');
    
    console.log('[스마트스토어] ID입력:', !!idInput, 'PW입력:', !!pwInput);
    
    if (idInput && pwInput) {
      await typeValue(idInput, loginInfo.login_id);
      await sleep(300);
      await typeValue(pwInput, loginInfo.password);
      await sleep(500);
      
      // 모든 버튼 로그
      const allBtns = document.querySelectorAll('button');
      console.log('[스마트스토어] 페이지 내 버튼 수:', allBtns.length);
      allBtns.forEach((btn, i) => {
        console.log(`[버튼${i}] text="${btn.textContent.trim()}" id="${btn.id}" class="${btn.className}"`);
      });
      
      // 로그인 버튼 찾기 - 텍스트가 정확히 "로그인"인 버튼
      let loginBtn = null;
      for (const btn of allBtns) {
        const text = btn.textContent.trim();
        // "로그인"만 있고 "패스키"가 없는 버튼
        if (text === '로그인') {
          loginBtn = btn;
          console.log('[스마트스토어] 로그인 버튼 발견:', btn.className);
          break;
        }
      }
      
      if (loginBtn) {
        console.log('[스마트스토어] 버튼 클릭 시도');
        // 여러 방식으로 클릭 시도
        loginBtn.focus();
        loginBtn.click();
        
        // click 이벤트 직접 발생
        const clickEvent = new MouseEvent('click', {
          view: window,
          bubbles: true,
          cancelable: true
        });
        loginBtn.dispatchEvent(clickEvent);
        
        await chrome.storage.local.remove('pendingLogin');
        console.log('[스마트스토어] 로그인 버튼 클릭 완료');
      } else {
        console.log('[스마트스토어] 로그인 버튼 못 찾음 - Enter 키 시도');
        pwInput.focus();
        
        // Enter 키 이벤트
        ['keydown', 'keypress', 'keyup'].forEach(type => {
          pwInput.dispatchEvent(new KeyboardEvent(type, {
            key: 'Enter',
            code: 'Enter',
            keyCode: 13,
            which: 13,
            bubbles: true
          }));
        });
        
        await chrome.storage.local.remove('pendingLogin');
      }
    } else {
      console.log('[스마트스토어] 입력 필드를 찾지 못함');
    }
    return;
  }
  
  // 2. commerce.naver.com (네이버 커머스 로그인)
  if (url.includes('commerce.naver.com') || url.includes('accounts.commerce.naver.com')) {
    console.log('[스마트스토어] 네이버 커머스 로그인 페이지 감지');
    
    await sleep(1000);
    
    // 바로 ID/PW 입력 (탭 클릭 안 함)
    const idInput = document.querySelector('input[id="id"], input[name="id"], input[type="text"]');
    const pwInput = document.querySelector('input[id="pw"], input[name="pw"], input[type="password"]');
    
    console.log('[스마트스토어] ID입력:', !!idInput, 'PW입력:', !!pwInput);
    
    if (idInput && pwInput) {
      await typeValue(idInput, loginInfo.login_id);
      await sleep(300);
      await typeValue(pwInput, loginInfo.password);
      await sleep(500);
      
      // 로그인 버튼 찾기
      const buttons = document.querySelectorAll('button');
      for (const btn of buttons) {
        const text = btn.textContent.trim();
        if (text === '로그인') {
          console.log('[스마트스토어] 로그인 버튼 클릭');
          btn.click();
          await chrome.storage.local.remove('pendingLogin');
          return;
        }
      }
      
      // Enter 키 시도
      console.log('[스마트스토어] Enter 시도');
      pwInput.focus();
      pwInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }));
      await chrome.storage.local.remove('pendingLogin');
    } else {
      console.log('[스마트스토어] 입력 필드를 찾지 못함');
      await chrome.storage.local.remove('pendingLogin');
    }
    return;
  }
  
  console.log('[스마트스토어] 알 수 없는 로그인 페이지:', url);
}

async function handleCoupang() {
  console.log('[쿠팡] 로그인 시작');
  
  const idInput = await waitForElement('input[name="username"], input[id="username"], input[placeholder*="아이디"]', 5000);
  if (!idInput) {
    console.log('[쿠팡] ID 입력란 없음');
    return;
  }
  
  const pwInput = document.querySelector('input[name="password"], input[id="password"], input[type="password"]');
  if (!pwInput) {
    console.log('[쿠팡] PW 입력란 없음');
    return;
  }
  
  await typeValue(idInput, loginInfo.login_id);
  await sleep(300);
  await typeValue(pwInput, loginInfo.password);
  await sleep(500);
  
  // 로그인 버튼 찾기
  let loginBtn = document.querySelector('#kc-login');
  if (!loginBtn) loginBtn = document.querySelector('button[type="submit"]');
  if (!loginBtn) loginBtn = document.querySelector('.login-button');
  if (!loginBtn) loginBtn = findButtonByText(['로그인', 'Log In', 'Sign In']);
  
  if (loginBtn) {
    console.log('[쿠팡] 로그인 버튼 클릭');
    loginBtn.click();
    await chrome.storage.local.remove('pendingLogin');
  } else {
    console.log('[쿠팡] 로그인 버튼 없음 - Enter 키 시도');
    pwInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }));
    await chrome.storage.local.remove('pendingLogin');
  }
}

async function handle11st() {
  console.log('[11번가] 로그인 시작');
  
  const idInput = await waitForElement('input[id="loginName"], input[name="loginName"], input[placeholder*="아이디"]', 5000);
  if (!idInput) {
    console.log('[11번가] ID 입력란 없음');
    return;
  }
  
  const pwInput = document.querySelector('input[id="passWord"], input[name="passWord"], input[type="password"]');
  if (!pwInput) {
    console.log('[11번가] PW 입력란 없음');
    return;
  }
  
  await typeValue(idInput, loginInfo.login_id);
  await sleep(300);
  await typeValue(pwInput, loginInfo.password);
  await sleep(500);
  
  // 로그인 버튼 찾기
  let loginBtn = document.querySelector('button.btn_login');
  if (!loginBtn) loginBtn = document.querySelector('button[type="submit"]');
  if (!loginBtn) loginBtn = document.querySelector('.login-btn');
  if (!loginBtn) loginBtn = document.querySelector('a.btn_login');
  if (!loginBtn) loginBtn = findButtonByText(['로그인', 'Login']);
  
  if (loginBtn) {
    console.log('[11번가] 로그인 버튼 클릭');
    loginBtn.click();
    await chrome.storage.local.remove('pendingLogin');
  } else {
    console.log('[11번가] 로그인 버튼 없음 - Enter 키 시도');
    pwInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }));
    await chrome.storage.local.remove('pendingLogin');
  }
}

async function handleESM(platform) {
  console.log('[ESM] 로그인 시작 -', platform);
  
  await sleep(1000);
  
  // 탭 선택
  const tabSelectors = {
    'ESM통합': "button[data-montelena-acode='700000273']",
    '지마켓': "button[data-montelena-acode='700000274']",
    '옥션': "button[data-montelena-acode='700000275']"
  };
  
  const tabBtn = document.querySelector(tabSelectors[platform]);
  if (tabBtn) {
    tabBtn.click();
    console.log('[ESM] 탭 선택:', platform);
    await sleep(1000);
  }
  
  // ID/PW 입력란 찾기 (여러 방법)
  let idInput = document.querySelector('input[placeholder*="아이디"]');
  if (!idInput) idInput = document.querySelector('input[type="text"]:not([readonly])');
  
  let pwInput = document.querySelector('input[placeholder*="비밀번호"]');
  if (!pwInput) pwInput = document.querySelector('input[type="password"]');
  
  if (!idInput || !pwInput) {
    console.log('[ESM] 입력란 없음');
    return;
  }
  
  let loginId = loginInfo.login_id;
  let password = loginInfo.password;
  
  // ESM통합 계정으로 로그인
  if (loginInfo.esm_master && loginInfo.esm_master_pw && platform !== 'ESM통합') {
    const esmTab = document.querySelector("button[data-montelena-acode='700000273']");
    if (esmTab) {
      esmTab.click();
      await sleep(1000);
      loginId = loginInfo.esm_master;
      password = loginInfo.esm_master_pw;
    }
  }
  
  await typeValue(idInput, loginId);
  await sleep(300);
  await typeValue(pwInput, password);
  await sleep(500);
  
  // 로그인 버튼 찾기
  let loginBtn = findButtonByText(['로그인']);
  if (!loginBtn) loginBtn = document.querySelector('button[type="submit"]');
  
  if (loginBtn) {
    console.log('[ESM] 로그인 버튼 클릭');
    loginBtn.click();
    await chrome.storage.local.remove('pendingLogin');
  } else {
    console.log('[ESM] 로그인 버튼 없음 - Enter 키 시도');
    pwInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }));
    await chrome.storage.local.remove('pendingLogin');
  }
}

// ========== 2차 인증 처리 ==========

function detect2FAPage() {
  const body = document.body.innerText;
  const html = document.documentElement.innerHTML;
  
  // 2차 인증 키워드 검색
  const keywords = [
    '인증번호', '인증코드', '본인확인', '2단계',
    '보안인증', 'OTP', '문자인증', 'SMS 인증',
    '인증번호 전송', '인증번호를 입력'
  ];
  
  return keywords.some(keyword => body.includes(keyword) || html.includes(keyword));
}

async function handle2FAPage() {
  console.log('[2차 인증] 처리 시작');

  // 인증번호 전송 버튼 자동 클릭 안 함 (수동으로 전송해야 함)
  await sleep(1000);
  console.log('[2차 인증] 인증번호 전송 버튼은 수동으로 클릭하세요');

  // 인증코드 자동 입력 시작
  startAuthCodeCheck();
}

// 11번가 셀러오피스 전용 2FA 처리
async function handle11st2FA() {
  console.log('[11번가 2FA] 처리 시작');

  await sleep(1000);

  // 인증번호 전송 버튼 자동 클릭 안 함 (수동으로 전송해야 함)
  console.log('[11번가 2FA] 인증번호 전송 버튼은 수동으로 클릭하세요');

  // 2. 인증코드 입력창 찾기
  const codeInput = document.querySelector('input[placeholder*="인증"], input[type="text"][maxlength="6"], input[name*="auth"], input#authNo');
  if (!codeInput) {
    console.log('[11번가 2FA] 인증번호 입력창 대기 중...');
  }
  
  // 3. 서버에서 인증코드 가져오기 (60초간 시도)
  console.log('[11번가 2FA] 인증코드 대기 시작');
  let attempts = 0;
  const maxAttempts = 60; // 60초
  
  const checkInterval = setInterval(async () => {
    attempts++;
    
    if (attempts > maxAttempts) {
      console.log('[11번가 2FA] 타임아웃');
      clearInterval(checkInterval);
      return;
    }
    
    try {
      const response = await apiRequest('/api/sms/auth-code');
      if (!response.ok) {
        console.log(`[11번가 2FA] 대기 중... (${attempts}/${maxAttempts})`);
        return;
      }
      
      const data = await response.json();
      console.log('[11번가 2FA] 서버 응답:', data);
      
      // 인증코드 찾기
      let code = null;
      if (data.code && /^\d{6}$/.test(data.code)) {
        code = data.code;
      } else if (data.auth_codes) {
        for (const phone in data.auth_codes) {
          const c = data.auth_codes[phone];
          if (c && /^\d{6}$/.test(c)) {
            code = c;
            break;
          }
        }
      }
      
      if (code) {
        console.log('[11번가 2FA] 인증코드 발견:', code);
        clearInterval(checkInterval);
        
        // 입력창에 코드 입력
        const input = document.querySelector('input[placeholder*="인증"], input[type="text"][maxlength="6"], input[name*="auth"], input#authNo');
        if (input) {
          await typeValue(input, code);
          await sleep(500);
          
          // 확인 버튼 클릭 - "로그인" 제외하고 정확히 "확인"만 찾기
          const confirmBtn = find11stConfirmButton();
          if (confirmBtn) {
            console.log('[11번가 2FA] 확인 버튼 클릭:', confirmBtn.textContent.trim());
            confirmBtn.click();
          } else {
            console.log('[11번가 2FA] 확인 버튼을 찾을 수 없음');
          }
        } else {
          console.log('[11번가 2FA] 입력창을 찾을 수 없음');
        }
      } else {
        console.log(`[11번가 2FA] 대기 중... (${attempts}/${maxAttempts})`);
      }
    } catch (e) {
      console.error('[11번가 2FA] 오류:', e);
    }
  }, 1000);
}

// 11번가 2FA 확인 버튼 찾기 (로그인 버튼 제외)
function find11stConfirmButton() {
  const buttons = document.querySelectorAll('button, input[type="submit"], input[type="button"]');
  
  for (const btn of buttons) {
    const text = (btn.textContent || btn.value || '').trim();
    
    // "로그인"이 포함되면 스킵
    if (text.includes('로그인')) continue;
    
    // 정확히 "확인"이거나 "인증" 관련 텍스트
    if (text === '확인' || text === '인증' || text === '인증하기' || text === '완료') {
      return btn;
    }
  }
  
  // 못 찾으면 빨간색/주요 버튼 중 확인 버튼 찾기
  const primaryBtns = document.querySelectorAll('button.btn_red, button.btn_primary, button[class*="confirm"], button[class*="submit"]');
  for (const btn of primaryBtns) {
    const text = (btn.textContent || btn.value || '').trim();
    if (!text.includes('로그인') && (text === '확인' || text.includes('확인'))) {
      return btn;
    }
  }
  
  return null;
}

// 2차 인증용 확인 버튼 찾기 (로그인 버튼 제외)
function findConfirmButtonExcludeLogin() {
  const buttons = document.querySelectorAll('button, input[type="submit"], input[type="button"]');
  
  // 1차: 정확히 "확인", "인증", "인증하기", "완료", "다음" 찾기
  for (const btn of buttons) {
    const text = (btn.textContent || btn.value || '').trim();
    
    // "로그인"이 포함되면 스킵
    if (text.includes('로그인')) continue;
    
    if (text === '확인' || text === '인증' || text === '인증하기' || text === '완료' || text === '다음') {
      return btn;
    }
  }
  
  // 2차: 확인이 포함된 버튼 찾기
  for (const btn of buttons) {
    const text = (btn.textContent || btn.value || '').trim();
    if (!text.includes('로그인') && text.includes('확인')) {
      return btn;
    }
  }
  
  // 3차: 마지막으로 로그인 버튼 (다른게 없으면)
  return findButtonByText(['로그인']);
}

async function startAuthCodeCheck() {
  console.log('[2차 인증] 인증코드 대기 시작');
  authAttempts = 0;
  
  // 로그인 시작 시간이 없으면 현재 시간 사용
  if (!loginStartTime) {
    loginStartTime = new Date();
  }
  console.log('[2차 인증] 기준 시간:', loginStartTime.toISOString());
  
  authCheckInterval = setInterval(async () => {
    authAttempts++;
    
    if (authAttempts > MAX_AUTH_ATTEMPTS) {
      console.log('[2차 인증] 타임아웃');
      clearInterval(authCheckInterval);
      return;
    }
    
    try {
      // 서버에서 인증코드 가져오기
      const response = await apiRequest('/api/sms/status');
      
      if (!response.ok) {
        console.log('[2차 인증] 서버 응답 오류:', response.status);
        return;
      }
      
      const data = await response.json();
      const authCodes = data.auth_codes || {};
      
      // 모든 폰 프로필에서 최신 인증코드 찾기
      let latestCode = null;
      for (const phone in authCodes) {
        const codeInfo = authCodes[phone];
        
        // codeInfo가 객체인 경우 (code, time 포함)
        let code, codeTime;
        if (typeof codeInfo === 'object' && codeInfo !== null) {
          code = codeInfo.code;
          codeTime = codeInfo.time; // "HH:MM:SS" 형식
        } else {
          code = codeInfo;
          codeTime = null;
        }
        
        if (code && code !== '------' && /^\d{4,6}$/.test(code)) {
          // 시간 필터링: 로그인 시작 이후의 코드만 사용
          if (codeTime) {
            const today = new Date();
            const [hours, minutes, seconds] = codeTime.split(':').map(Number);
            const codeDate = new Date(today.getFullYear(), today.getMonth(), today.getDate(), hours, minutes, seconds);
            
            if (codeDate < loginStartTime) {
              console.log(`[2차 인증] 이전 코드 무시: ${code} (시간: ${codeTime}, 로그인 시작: ${loginStartTime.toTimeString().slice(0,8)})`);
              continue;
            }
          }
          
          latestCode = code;
          console.log(`[2차 인증] 유효한 인증코드 발견: ${code} (폰: ${phone}, 시간: ${codeTime || '알 수 없음'})`);
          break;
        }
      }
      
      if (latestCode) {
        clearInterval(authCheckInterval);
        await inputAuthCode(latestCode);
      } else {
        console.log(`[2차 인증] 대기 중... (${authAttempts}/${MAX_AUTH_ATTEMPTS})`);
      }
    } catch (e) {
      console.error('[2차 인증] 오류:', e);
    }
  }, 1000); // 1초마다 확인
}

async function inputAuthCode(code) {
  console.log('[2차 인증] 인증코드 입력 시도:', code);
  
  // 인증코드 입력창 찾기 (여러 셀렉터 시도)
  const selectors = [
    'input[placeholder*="인증"]',
    'input[placeholder*="코드"]',
    'input[placeholder*="번호"]',
    'input[name*="otp"]',
    'input[name*="auth"]',
    'input[name*="certNo"]',
    'input[id*="otp"]',
    'input[id*="auth"]',
    'input[id*="certNo"]',
    'input#authNo',
    'input[maxlength="6"]',
    'input[maxlength="4"]',
    'input[type="text"][maxlength="6"]',
    'input[type="tel"]'
  ];
  
  let codeInput = null;
  
  // 각 셀렉터로 시도
  for (const selector of selectors) {
    const input = document.querySelector(selector);
    if (input && input.offsetParent !== null) { // 보이는 요소만
      codeInput = input;
      console.log('[2차 인증] 입력창 발견:', selector);
      break;
    }
  }
  
  // 못 찾으면 모든 text input 중에서 찾기
  if (!codeInput) {
    const allInputs = document.querySelectorAll('input[type="text"], input[type="tel"], input:not([type])');
    for (const input of allInputs) {
      if (input.offsetParent !== null && !input.value) {
        codeInput = input;
        console.log('[2차 인증] 빈 입력창 발견');
        break;
      }
    }
  }
  
  if (codeInput) {
    // 기존 값 지우고 입력
    codeInput.focus();
    codeInput.value = '';
    
    // 한 글자씩 입력
    for (const char of code) {
      codeInput.value += char;
      codeInput.dispatchEvent(new Event('input', { bubbles: true }));
      await sleep(50);
    }
    
    // change 이벤트
    codeInput.dispatchEvent(new Event('change', { bubbles: true }));
    
    console.log('[2차 인증] 인증코드 입력 완료:', codeInput.value);
    await sleep(500);
    
    // 확인 버튼 클릭 - "로그인" 제외하고 찾기
    const confirmBtn = findConfirmButtonExcludeLogin();
    if (confirmBtn) {
      console.log('[2차 인증] 확인 버튼 클릭:', confirmBtn.textContent.trim());
      confirmBtn.click();
      
      await chrome.storage.local.remove('pendingLogin');
    } else {
      console.log('[2차 인증] 확인 버튼을 찾을 수 없음');
    }
  } else {
    console.log('[2차 인증] 입력창을 찾을 수 없음');
    // 모든 input 로그
    document.querySelectorAll('input').forEach((inp, i) => {
      console.log(`[input${i}] type=${inp.type} id=${inp.id} name=${inp.name} placeholder=${inp.placeholder} visible=${inp.offsetParent !== null}`);
    });
  }
}

// ========== 비밀번호 변경 처리 ==========

function detectPasswordChangePage() {
  const body = document.body.innerText;
  const html = document.documentElement.innerHTML;
  
  // 비밀번호 변경 키워드 검색
  const keywords = [
    '비밀번호 변경', '비밀번호를 변경', '비밀번호 재설정',
    '새 비밀번호', '새로운 비밀번호', 'password change',
    '현재 비밀번호', '기존 비밀번호'
  ];
  
  return keywords.some(keyword => 
    body.includes(keyword) || html.toLowerCase().includes(keyword.toLowerCase())
  );
}

async function handlePasswordChange() {
  console.log('[비밀번호 변경] 처리 시작');
  await sleep(1000);
  
  // 먼저 "30일 후에 변경" 또는 "다음에 변경" 버튼 찾기 (스킵 버튼)
  const skipBtn = findButtonByText(['30일 후에 변경', '다음에 변경', '나중에 변경', '다음에', '나중에', '건너뛰기', 'Skip', 'Later']);
  if (skipBtn) {
    console.log('[비밀번호 변경] 스킵 버튼 발견:', skipBtn.textContent.trim());
    skipBtn.click();
    await chrome.storage.local.remove('pendingLogin');
    return;
  }
  
  // 스킵 버튼이 없으면 실제 비밀번호 변경 시도
  await sleep(1000);
  
  // 현재 비밀번호 입력
  const currentPwInput = document.querySelector(
    'input[placeholder*="현재"], input[placeholder*="기존"], ' +
    'input[name*="current"], input[name*="old"], ' +
    'input[id*="current"], input[id*="old"]'
  );
  
  // 새 비밀번호 입력창 2개 찾기
  const newPwInputs = document.querySelectorAll(
    'input[placeholder*="새"], input[placeholder*="신규"], ' +
    'input[name*="new"], input[id*="new"], ' +
    'input[type="password"]:not([name*="current"]):not([name*="old"])'
  );
  
  if (!currentPwInput || newPwInputs.length < 2) {
    console.log('[비밀번호 변경] 입력창을 찾을 수 없음');
    return;
  }
  
  // 새 비밀번호 생성 (마지막 특수문자만 변경)
  const oldPassword = loginInfo.password;
  const newPassword = generateNewPassword(oldPassword);
  
  console.log('[비밀번호 변경] 기존:', oldPassword, '→ 새:', newPassword);
  
  // 입력
  await typeValue(currentPwInput, oldPassword);
  await typeValue(newPwInputs[0], newPassword);
  await typeValue(newPwInputs[1], newPassword);
  await sleep(500);
  
  // 확인 버튼 클릭
  const confirmBtn = findButtonByText(['확인', '변경', '저장', '다음', '완료']);
  if (confirmBtn) {
    console.log('[비밀번호 변경] 확인 버튼 클릭');
    confirmBtn.click();
    
    // 서버에 비밀번호 업데이트 요청
    await updatePasswordToServer(newPassword);
    
    // 로그인 정보 업데이트
    loginInfo.password = newPassword;
    await chrome.storage.local.set({ pendingLogin: loginInfo });
    
    // 3초 후 2차 인증 확인
    setTimeout(() => {
      if (detect2FAPage()) {
        console.log('[비밀번호 변경] 후 2차 인증 감지');
        handle2FAPage();
      }
    }, 3000);
  }
}

function generateNewPassword(oldPassword) {
  // 마지막 문자 확인
  const lastChar = oldPassword.slice(-1);
  
  // 특수문자 순환 리스트
  const specialChars = ['!', '@', '#', '$', '%', '^', '&', '*'];
  
  let newLastChar;
  const currentIndex = specialChars.indexOf(lastChar);
  
  if (currentIndex !== -1) {
    // 다음 특수문자로 변경
    newLastChar = specialChars[(currentIndex + 1) % specialChars.length];
  } else {
    // 기존 마지막 문자가 특수문자가 아니면 !로 시작
    newLastChar = '!';
  }
  
  return oldPassword.slice(0, -1) + newLastChar;
}

async function updatePasswordToServer(newPassword) {
  try {
    const response = await apiRequest('/api/update-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        platform: loginInfo.platform,
        login_id: loginInfo.login_id,
        new_password: newPassword
      })
    });
    
    const data = await response.json();
    if (data.success) {
      console.log('[비밀번호 변경] 서버 업데이트 성공');
    } else {
      console.error('[비밀번호 변경] 서버 업데이트 실패:', data.message);
    }
  } catch (e) {
    console.error('[비밀번호 변경] 서버 통신 오류:', e);
  }
}

// ========== 유틸리티 함수 ==========

async function typeValue(element, value) {
  if (!element) return;
  
  element.focus();
  element.value = '';
  
  // React/Vue 등 프레임워크 호환
  const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value'
  ).set;
  nativeInputValueSetter.call(element, value);
  
  element.dispatchEvent(new Event('input', { bubbles: true }));
  element.dispatchEvent(new Event('change', { bubbles: true }));
  element.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
  
  await sleep(100);
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForElement(selector, timeout = 5000) {
  const startTime = Date.now();
  
  while (Date.now() - startTime < timeout) {
    const element = document.querySelector(selector);
    if (element) return element;
    await sleep(100);
  }
  
  console.log(`[대기] 요소를 찾을 수 없음: ${selector}`);
  return null;
}

function findButtonByText(textList) {
  const buttons = document.querySelectorAll('button, input[type="submit"], input[type="button"], a.btn');
  
  for (const btn of buttons) {
    const text = btn.textContent.trim() || btn.value || '';
    for (const searchText of textList) {
      if (text.includes(searchText)) {
        return btn;
      }
    }
  }
  
  return null;
}

// ========== 메시지 리스너 (팝업에서 수동 입력 지원) ==========
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'inputAuthCode') {
    const code = request.code;
    console.log('[수동 입력] 인증코드:', code);
    
    inputAuthCode(code).then(() => {
      sendResponse({ success: true });
    }).catch(err => {
      sendResponse({ success: false, error: err.message });
    });
    
    return true; // 비동기 응답
  }
});
