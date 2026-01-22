// 마케팅분석 내부 탭 전환 함수
function switchMarketingInnerTab(tabName) {
    // 모든 내부 탭 버튼 비활성화
    document.querySelectorAll('#mkt-subtab-performance .inner-tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });

    // 모든 내부 탭 컨텐츠 숨기기
    document.querySelectorAll('#mkt-subtab-performance .inner-tab-content').forEach(content => {
        content.classList.remove('active');
    });

    // 선택된 탭 활성화
    if (tabName === 'visitors') {
        document.querySelector('.inner-tab-btn[onclick*="visitors"]').classList.add('active');
        document.getElementById('mkt-inner-visitors').classList.add('active');
    } else if (tabName === 'products') {
        document.querySelector('.inner-tab-btn[onclick*="products"]').classList.add('active');
        document.getElementById('mkt-inner-products').classList.add('active');
    }
}

// 스케줄러 작업 상세 설정 모달
function openTaskSettingsModal() {
    const task = document.getElementById('schedTask').value;
    showToast(`${task} 상세 설정 기능은 준비 중입니다.`, 'info');
}
