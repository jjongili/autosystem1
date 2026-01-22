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

// 스케줄러 작업별 옵션 설정값 저장
let scheduleTaskOptions = {};

// 스케줄러 계정 목록 캐시
let schedAccountsCache = [];

// 플랫폼 변경 시 계정 목록 로드
async function loadSchedAccounts() {
    const platform = document.getElementById('schedPlatform')?.value || '스마트스토어';
    const availableList = document.getElementById('schedAccountsAvailable');
    const selectedList = document.getElementById('schedAccountsSelected');

    if (!availableList || !selectedList) return;

    try {
        const r = await fetch(`/api/accounts?platform=${encodeURIComponent(platform)}`);
        const d = await r.json();
        const accounts = d.accounts || [];

        // 캐시 저장
        schedAccountsCache = accounts;

        // 기존 선택 유지
        const selectedValues = Array.from(selectedList.options).map(o => o.value);

        // 가능한 계정 목록 업데이트
        availableList.innerHTML = '';
        accounts.forEach(acc => {
            const name = acc.스토어명 || acc.아이디 || '';
            if (name && !selectedValues.includes(name)) {
                const opt = document.createElement('option');
                opt.value = name;
                opt.textContent = name;
                availableList.appendChild(opt);
            }
        });

        updateSchedSelectedCount();
    } catch (e) {
        console.error('계정 목록 로드 실패:', e);
    }
}

// 선택된 계정 수 업데이트
function updateSchedSelectedCount() {
    const selectedList = document.getElementById('schedAccountsSelected');
    const countSpan = document.getElementById('schedSelectedCount');
    if (selectedList && countSpan) {
        countSpan.textContent = selectedList.options.length;
    }
}

// 선택한 계정 오른쪽으로 이동
function schedMoveAccountRight() {
    const available = document.getElementById('schedAccountsAvailable');
    const selected = document.getElementById('schedAccountsSelected');
    moveSelectedOptions(available, selected);
    updateSchedSelectedCount();
}

// 전체 계정 오른쪽으로 이동
function schedMoveAllRight() {
    const available = document.getElementById('schedAccountsAvailable');
    const selected = document.getElementById('schedAccountsSelected');
    moveAllOptions(available, selected);
    updateSchedSelectedCount();
}

// 선택한 계정 왼쪽으로 이동
function schedMoveAccountLeft() {
    const available = document.getElementById('schedAccountsAvailable');
    const selected = document.getElementById('schedAccountsSelected');
    moveSelectedOptions(selected, available);
    updateSchedSelectedCount();
}

// 전체 계정 왼쪽으로 이동
function schedMoveAllLeft() {
    const available = document.getElementById('schedAccountsAvailable');
    const selected = document.getElementById('schedAccountsSelected');
    moveAllOptions(selected, available);
    updateSchedSelectedCount();
}

// 선택된 옵션 이동
function moveSelectedOptions(from, to) {
    const selectedOpts = Array.from(from.selectedOptions);
    selectedOpts.forEach(opt => {
        to.appendChild(opt);
    });
    sortSelectOptions(to);
}

// 전체 옵션 이동
function moveAllOptions(from, to) {
    while (from.options.length > 0) {
        to.appendChild(from.options[0]);
    }
    sortSelectOptions(to);
}

// select 옵션 정렬
function sortSelectOptions(select) {
    const opts = Array.from(select.options);
    opts.sort((a, b) => a.text.localeCompare(b.text));
    select.innerHTML = '';
    opts.forEach(o => select.appendChild(o));
}

// 선택된 계정 목록 가져오기
function getSelectedSchedAccounts() {
    const selected = document.getElementById('schedAccountsSelected');
    if (!selected) return [];
    return Array.from(selected.options).map(o => o.value);
}

// 작업 상세 설정 모달 닫기
function closeTaskSettingsModal() {
    const modal = document.getElementById('taskSettingsModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// 스케줄러 작업 상세 설정 모달
function openTaskSettingsModal() {
    const task = document.getElementById('schedTask').value;
    const platform = document.getElementById('schedPlatform').value;

    let optionsHtml = '';

    if (task === '배송변경' || task === '혜택설정') {
        optionsHtml = `
            <div style="margin-bottom: 15px;">
                <label style="font-weight: 600; display: block; margin-bottom: 8px;">대상 선택 방식:</label>
                <div style="display: flex; gap: 15px; margin-bottom: 10px;">
                    <label style="cursor: pointer;"><input type="radio" name="schedUpdateMode" value="count" checked> 수량 기준</label>
                    <label style="cursor: pointer;"><input type="radio" name="schedUpdateMode" value="date"> 날짜 기준</label>
                </div>
                <div id="schedOptionCount">
                    <label>처리 수량:</label>
                    <input type="number" id="schedTargetCount" value="${scheduleTaskOptions.targetCount || 100}" min="1" max="10000" style="width: 100px; padding: 5px;">
                    <span>개</span>
                </div>
                <div id="schedOptionDate" style="display: none;">
                    <label>기준 날짜 이후:</label>
                    <input type="date" id="schedTargetDate" value="${scheduleTaskOptions.targetDate || ''}" style="padding: 5px;">
                </div>
            </div>
        `;
    } else if (task === '상품삭제') {
        optionsHtml = `
            <div style="margin-bottom: 15px;">
                <label style="display: flex; align-items: center; cursor: pointer; margin-bottom: 10px;">
                    <input type="checkbox" id="schedDeleteExcessOnly" ${scheduleTaskOptions.deleteExcessOnly ? 'checked' : ''} style="margin-right: 8px;">
                    <span>초과분만 삭제 (삭제 기준 사용)</span>
                </label>
                <div id="schedDeleteCountWrap">
                    <label>삭제 수량 (오래된 순, 판매상품 제외):</label>
                    <input type="number" id="schedDeleteCount" value="${scheduleTaskOptions.deleteCount || 50}" min="1" max="5000" style="width: 100px; padding: 5px;">
                    <span>개</span>
                </div>
            </div>
        `;
    } else if (task === 'KC인증') {
        optionsHtml = `
            <div style="margin-bottom: 15px;">
                <label style="font-weight: 600; display: block; margin-bottom: 8px;">대상 선택 방식:</label>
                <div style="display: flex; gap: 15px; margin-bottom: 10px;">
                    <label style="cursor: pointer;"><input type="radio" name="schedKCMode" value="count" checked> 수량 기준</label>
                    <label style="cursor: pointer;"><input type="radio" name="schedKCMode" value="date"> 날짜 기준</label>
                </div>
                <div id="schedKCCount">
                    <label>처리 수량:</label>
                    <input type="number" id="schedKCLimit" value="${scheduleTaskOptions.kcLimit || 2000}" min="100" max="10000" style="width: 100px; padding: 5px;">
                    <span>개</span>
                </div>
                <div id="schedKCDate" style="display: none;">
                    <label>기준 날짜 이후:</label>
                    <input type="date" id="schedKCTargetDate" value="${scheduleTaskOptions.kcDate || ''}" style="padding: 5px;">
                </div>
                <p style="font-size: 12px; color: #666; margin-top: 8px;">※ KC인증 대상 제외 (어린이제품, 친환경) 설정</p>
            </div>
        `;
    } else if (task === '중복삭제') {
        optionsHtml = `
            <div style="margin-bottom: 15px;">
                <label style="font-weight: 600; display: block; margin-bottom: 8px;">중복 기준:</label>
                <div style="display: flex; flex-direction: column; gap: 8px;">
                    <label style="cursor: pointer;"><input type="checkbox" id="schedDupTitle" ${scheduleTaskOptions.dupTitle !== false ? 'checked' : ''}> 상품명 기준</label>
                    <label style="cursor: pointer;"><input type="checkbox" id="schedDupImage" ${scheduleTaskOptions.dupImage ? 'checked' : ''}> 대표이미지 기준</label>
                </div>
                <div style="margin-top: 10px;">
                    <label>중복 시 삭제 대상:</label>
                    <select id="schedDupDeleteTarget" style="padding: 5px;">
                        <option value="older" ${scheduleTaskOptions.dupDeleteTarget === 'older' ? 'selected' : ''}>오래된 상품 삭제</option>
                        <option value="newer" ${scheduleTaskOptions.dupDeleteTarget === 'newer' ? 'selected' : ''}>최신 상품 삭제</option>
                    </select>
                </div>
            </div>
        `;
    } else if (task === '마케팅수집') {
        optionsHtml = `
            <div style="margin-bottom: 15px;">
                <label style="font-weight: 600; display: block; margin-bottom: 8px;">수집 항목:</label>
                <div style="display: flex; flex-direction: column; gap: 8px;">
                    <label style="cursor: pointer;"><input type="checkbox" id="schedMktBizAdvisor" ${scheduleTaskOptions.mktBizAdvisor !== false ? 'checked' : ''}> 비즈어드바이저</label>
                    <label style="cursor: pointer;"><input type="checkbox" id="schedMktPartner" ${scheduleTaskOptions.mktPartner !== false ? 'checked' : ''}> 쇼핑파트너</label>
                    <label style="cursor: pointer;"><input type="checkbox" id="schedMktMallInfo" ${scheduleTaskOptions.mktMallInfo ? 'checked' : ''}> 쇼핑몰정보</label>
                </div>
            </div>
        `;
    } else {
        optionsHtml = `
            <p style="color: #666; text-align: center; padding: 20px;">
                이 작업은 별도의 상세 옵션이 없습니다.
            </p>
        `;
    }

    const modalContent = `
        <div style="padding: 10px 0;">
            <div style="background: #f8f9fa; padding: 12px; border-radius: 8px; margin-bottom: 15px;">
                <strong>플랫폼:</strong> ${platform} &nbsp;|&nbsp; <strong>작업:</strong> ${task}
            </div>
            ${optionsHtml}
            <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; padding-top: 15px; border-top: 1px solid #eee;">
                <button onclick="closeModal()" style="padding: 8px 20px; background: #f0f0f0; border: none; border-radius: 5px; cursor: pointer;">취소</button>
                <button onclick="saveTaskSettings('${task}')" style="padding: 8px 20px; background: #667eea; color: white; border: none; border-radius: 5px; cursor: pointer;">저장</button>
            </div>
        </div>
    `;

    showModal(`⚙️ ${task} 상세 설정`, modalContent);

    // 라디오 버튼 이벤트
    setTimeout(() => {
        document.querySelectorAll('input[name="schedUpdateMode"]').forEach(radio => {
            radio.addEventListener('change', function() {
                document.getElementById('schedOptionCount').style.display = this.value === 'count' ? 'block' : 'none';
                document.getElementById('schedOptionDate').style.display = this.value === 'date' ? 'block' : 'none';
            });
        });
        document.querySelectorAll('input[name="schedKCMode"]').forEach(radio => {
            radio.addEventListener('change', function() {
                document.getElementById('schedKCCount').style.display = this.value === 'count' ? 'block' : 'none';
                document.getElementById('schedKCDate').style.display = this.value === 'date' ? 'block' : 'none';
            });
        });
    }, 100);
}

// 작업 설정 저장
function saveTaskSettings(task) {
    // task가 없으면 현재 선택된 작업 가져오기
    if (!task) {
        task = document.getElementById('schedTask')?.value || '';
    }

    if (task === '배송변경' || task === '혜택설정') {
        const mode = document.querySelector('input[name="schedUpdateMode"]:checked')?.value || 'count';
        scheduleTaskOptions.updateMode = mode;
        scheduleTaskOptions.targetCount = parseInt(document.getElementById('schedTargetCount')?.value) || 100;
        scheduleTaskOptions.targetDate = document.getElementById('schedTargetDate')?.value || '';
    } else if (task === '상품삭제') {
        scheduleTaskOptions.deleteExcessOnly = document.getElementById('schedDeleteExcessOnly')?.checked || false;
        scheduleTaskOptions.deleteCount = parseInt(document.getElementById('schedDeleteCount')?.value) || 50;
    } else if (task === 'KC인증') {
        const mode = document.querySelector('input[name="schedKCMode"]:checked')?.value || 'count';
        scheduleTaskOptions.kcMode = mode;
        scheduleTaskOptions.kcLimit = parseInt(document.getElementById('schedKCLimit')?.value) || 2000;
        scheduleTaskOptions.kcDate = document.getElementById('schedKCTargetDate')?.value || '';
    } else if (task === '중복삭제') {
        scheduleTaskOptions.dupTitle = document.getElementById('schedDupTitle')?.checked;
        scheduleTaskOptions.dupImage = document.getElementById('schedDupImage')?.checked;
        scheduleTaskOptions.dupDeleteTarget = document.getElementById('schedDupDeleteTarget')?.value || 'older';
    } else if (task === '마케팅수집') {
        scheduleTaskOptions.mktBizAdvisor = document.getElementById('schedMktBizAdvisor')?.checked;
        scheduleTaskOptions.mktPartner = document.getElementById('schedMktPartner')?.checked;
        scheduleTaskOptions.mktMallInfo = document.getElementById('schedMktMallInfo')?.checked;
    }

    closeTaskSettingsModal();
    showToast(`${task} 설정이 저장되었습니다.`, 'success');
}

// 스케줄 수정 모달
function openEditScheduleModal(scheduleId) {
    const schedule = scheduleList.find(s => s.id === scheduleId);
    if (!schedule) {
        showToast('스케줄을 찾을 수 없습니다.', 'error');
        return;
    }

    // 기존 옵션 로드
    scheduleTaskOptions = schedule.options || {};

    const cronParts = (schedule.cron || '0 9 * * *').split(' ');

    const modalContent = `
        <div style="padding: 10px 0;">
            <input type="hidden" id="editScheduleId" value="${schedule.id}">

            <div style="margin-bottom: 15px;">
                <label style="font-weight: 600; display: block; margin-bottom: 5px;">스케줄 이름</label>
                <input type="text" id="editSchedName" value="${schedule.name}" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 5px;">
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px;">
                <div>
                    <label style="font-weight: 600; display: block; margin-bottom: 5px;">플랫폼</label>
                    <select id="editSchedPlatform" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 5px;">
                        <option value="스마트스토어" ${schedule.platform === '스마트스토어' ? 'selected' : ''}>스마트스토어</option>
                        <option value="11번가" ${schedule.platform === '11번가' ? 'selected' : ''}>11번가</option>
                    </select>
                </div>
                <div>
                    <label style="font-weight: 600; display: block; margin-bottom: 5px;">작업</label>
                    <select id="editSchedTask" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 5px;">
                        <option value="등록갯수" ${schedule.task === '등록갯수' ? 'selected' : ''}>등록갯수</option>
                        <option value="배송변경" ${schedule.task === '배송변경' ? 'selected' : ''}>배송변경</option>
                        <option value="상품삭제" ${schedule.task === '상품삭제' ? 'selected' : ''}>상품삭제</option>
                        <option value="혜택설정" ${schedule.task === '혜택설정' ? 'selected' : ''}>혜택설정</option>
                        <option value="중복삭제" ${schedule.task === '중복삭제' ? 'selected' : ''}>중복삭제</option>
                        <option value="KC인증" ${schedule.task === 'KC인증' ? 'selected' : ''}>KC인증</option>
                        <option value="마케팅수집" ${schedule.task === '마케팅수집' ? 'selected' : ''}>마케팅수집</option>
                    </select>
                </div>
            </div>

            <div style="margin-bottom: 15px;">
                <label style="font-weight: 600; display: block; margin-bottom: 5px;">실행 시간 (Cron: 분 시 일 월 요일)</label>
                <div style="display: flex; gap: 8px; align-items: center;">
                    <input type="text" id="editCronMin" value="${cronParts[0] || '0'}" style="width: 50px; padding: 8px; border: 1px solid #ddd; border-radius: 5px; text-align: center;" placeholder="분">
                    <input type="text" id="editCronHour" value="${cronParts[1] || '9'}" style="width: 50px; padding: 8px; border: 1px solid #ddd; border-radius: 5px; text-align: center;" placeholder="시">
                    <input type="text" id="editCronDay" value="${cronParts[2] || '*'}" style="width: 50px; padding: 8px; border: 1px solid #ddd; border-radius: 5px; text-align: center;" placeholder="일">
                    <input type="text" id="editCronMonth" value="${cronParts[3] || '*'}" style="width: 50px; padding: 8px; border: 1px solid #ddd; border-radius: 5px; text-align: center;" placeholder="월">
                    <input type="text" id="editCronDow" value="${cronParts[4] || '*'}" style="width: 50px; padding: 8px; border: 1px solid #ddd; border-radius: 5px; text-align: center;" placeholder="요일">
                </div>
                <p style="font-size: 11px; color: #999; margin-top: 5px;">예: 0 9 * * * = 매일 09:00, 0 9 * * 1-5 = 평일 09:00</p>
            </div>

            <div style="margin-bottom: 15px;">
                <label style="font-weight: 600; display: block; margin-bottom: 5px;">상태</label>
                <label style="cursor: pointer;">
                    <input type="checkbox" id="editSchedEnabled" ${schedule.enabled ? 'checked' : ''}> 활성화
                </label>
            </div>

            <div style="background: #f0f7ff; padding: 12px; border-radius: 8px; margin-bottom: 15px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: 600;">⚙️ 작업 옵션</span>
                    <button onclick="openTaskSettingsModalForEdit()" style="padding: 5px 12px; background: #667eea; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 12px;">설정</button>
                </div>
                <p style="font-size: 12px; color: #666; margin-top: 5px;">작업별 세부 옵션을 설정합니다.</p>
            </div>

            <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; padding-top: 15px; border-top: 1px solid #eee;">
                <button onclick="closeModal()" style="padding: 8px 20px; background: #f0f0f0; border: none; border-radius: 5px; cursor: pointer;">취소</button>
                <button onclick="saveEditSchedule()" style="padding: 8px 20px; background: #4caf50; color: white; border: none; border-radius: 5px; cursor: pointer;">저장</button>
            </div>
        </div>
    `;

    showModal(`✏️ 스케줄 수정: ${schedule.name}`, modalContent);
}

// 수정 모달에서 작업 옵션 열기
function openTaskSettingsModalForEdit() {
    const task = document.getElementById('editSchedTask')?.value;
    if (task) {
        // 현재 모달 닫고 설정 모달 열기
        const originalTask = document.getElementById('schedTask')?.value;
        if (document.getElementById('schedTask')) {
            document.getElementById('schedTask').value = task;
        }
        openTaskSettingsModal();
        // 원래 값 복원
        setTimeout(() => {
            if (document.getElementById('schedTask') && originalTask) {
                document.getElementById('schedTask').value = originalTask;
            }
        }, 100);
    }
}

// 스케줄 수정 저장
async function saveEditSchedule() {
    const id = document.getElementById('editScheduleId')?.value;
    const name = document.getElementById('editSchedName')?.value?.trim();

    if (!name) {
        showToast('스케줄 이름을 입력하세요.', 'error');
        return;
    }

    const cron = [
        document.getElementById('editCronMin')?.value || '0',
        document.getElementById('editCronHour')?.value || '9',
        document.getElementById('editCronDay')?.value || '*',
        document.getElementById('editCronMonth')?.value || '*',
        document.getElementById('editCronDow')?.value || '*'
    ].join(' ');

    try {
        const res = await fetchAPI(`/api/schedules/${id}`, {
            method: 'PUT',
            body: JSON.stringify({
                name: name,
                platform: document.getElementById('editSchedPlatform')?.value,
                task: document.getElementById('editSchedTask')?.value,
                cron: cron,
                enabled: document.getElementById('editSchedEnabled')?.checked,
                options: scheduleTaskOptions
            })
        });

        if (res.success) {
            showToast('스케줄이 수정되었습니다.', 'success');
            closeModal();
            loadSchedules();
        } else {
            showToast(res.error || '수정 실패', 'error');
        }
    } catch (e) {
        showToast('수정 오류: ' + e.message, 'error');
    }
}
