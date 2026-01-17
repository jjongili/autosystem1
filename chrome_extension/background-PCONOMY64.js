// Background Service Worker

// 설치 시 초기화
chrome.runtime.onInstalled.addListener(() => {
  console.log('구매대행 자동로그인 확장 설치됨');

  // 기본 서버 URL 및 포트 설정
  chrome.storage.local.set({
    serverHost: 'http://182.222.231.21',
    serverPort: '8080'
  });
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
