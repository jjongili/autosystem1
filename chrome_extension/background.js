// Background Service Worker

// 현재 버전 (포트 변경 등 설정 업데이트 시 증가)
const CONFIG_VERSION = 2;

// 설치/업데이트 시 초기화
chrome.runtime.onInstalled.addListener((details) => {
  console.log('구매대행 자동로그인 확장:', details.reason);

  // 기본 서버 URL 및 포트 설정 (항상 최신값으로 업데이트)
  chrome.storage.local.set({
    serverHost: 'http://182.222.231.21',
    serverPort: '8080',
    configVersion: CONFIG_VERSION
  });
});

// 서비스워커 시작 시 설정 버전 확인 및 마이그레이션
chrome.storage.local.get(['configVersion', 'serverPort'], (result) => {
  // 설정 버전이 없거나 이전 버전이면 포트 강제 업데이트
  if (!result.configVersion || result.configVersion < CONFIG_VERSION) {
    console.log('설정 마이그레이션: 포트 8080으로 업데이트');
    chrome.storage.local.set({
      serverHost: 'http://182.222.231.21',
      serverPort: '8080',
      configVersion: CONFIG_VERSION
    });
  }
});

// 탭 업데이트 감지 (2차 인증 페이지 자동 감지)
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url) {
    // 11번가 2차 인증 페이지
    if (tab.url.includes('otpLoginForm') || tab.url.includes('2단계')) {
      // content script에서 처리
      console.log('2차 인증 페이지 감지:', tab.url);
    }
  }
});
