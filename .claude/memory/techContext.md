# Tech Context - 기술 컨텍스트

## 프로젝트 구조

```
autosystem1/
├── web_system/                        # 통합관리 웹서버
│   ├── server.py                      # FastAPI 메인 서버 (8000+ 라인)
│   ├── modules/
│   │   ├── marketing_collector.py     # 마케팅 데이터 수집 (Selenium)
│   │   ├── daily_sync.py
│   │   ├── ali_tracking.py
│   │   └── delivery_check.py
│   ├── templates/
│   └── static/
│
├── 불사자 자동화 도구 (클로드코드 개발)
│   ├── 5. bulsaja_title_maker_*.py    # AI 상품명 생성기
│   ├── 6. bulsaja_image_translator_*.py # 이미지 번역기
│   ├── 7. bulsaja_uploader_v1.1.py    # 대량 업로더
│   ├── 8. bulsaja_simulator.py        # 시뮬레이터 (학습용)
│   ├── 9. bulsaja_option_updater.py   # 옵션 업데이터
│   └── bulsaja_common.py              # 공통 모듈
│
├── ESM(G마켓/옥션) 자동화
│   ├── 10. esm_manager_gui.py         # ESM 상품 관리 GUI
│   └── 10. esm_manager_auto_v0.2.py   # ESM 자동 삭제
│
├── CLAUDE.md                          # 프로젝트 지침
└── .claude/memory/                    # 메모리뱅크
```

## 주요 기술 스택
- Backend: FastAPI, Python
- Frontend: Vanilla JS (SPA)
- 데이터: Google Sheets (gspread)
- 브라우저 자동화:
  - Selenium (마케팅 분석)
  - Playwright (SMS)
- 스케줄러: APScheduler
- 실시간: WebSocket

## 중요 파일 위치

### 로그인 관련
- `marketing_collector.py:348-470` - do_login() 함수

### SMS 썸네일
- `server.py:1500-1623` - 썸네일 다운로드/스크린샷

### 환경 변수
- SPREADSHEET_KEY
- MARKETING_SPREADSHEET_KEY
- SERVICE_ACCOUNT_JSON
- API_KEY

## 자주 발생하는 이슈

### 1. 로그인 실패
- 확인: 선택자 변경 여부
- 디버그 폴더: `web_system/runtime/smartstore_debug/`

### 2. 한글 깨짐
- 해결: UTF-8 인코딩 설정 (파일 상단)

### 3. 썸네일 스크린샷 실패
- 원인: DOM에서 요소 분리됨
- 해결: bounding_box 체크 후 스크린샷

## 불사자 자동화 도구

### 공통 모듈 (bulsaja_common.py)
- `BulsajaAPIClient`: 불사자 API 클라이언트
- `extract_tokens_from_browser()`: CDP로 크롬에서 토큰 추출
- `filter_bait_options()`: 미끼옵션 필터링
- `select_main_option()`: 대표옵션 선택 (상품명 매칭)
- `check_product_safety()`: 금지 키워드/브랜드 검수

### 불사자 API 엔드포인트
- 상품 목록: `POST /api/manage/list/serverside`
- 상품 상세: `GET /api/manage/sourcing-product/{id}`
- 상품 수정: `PUT /api/sourcing/uploadfields/{id}`
- 그룹 목록: `POST /api/market/groups/` → [{name, id, market_count}, ...]
- 그룹 내 마켓: `GET /api/market/group/{group_id}/markets` → [{id, type, account}, ...]
- 업로드: `POST /api/market/{market_id}/upload/` (주의: market_id는 그룹 ID가 아닌 마켓 ID)

### 마켓 ID 매핑
```python
MARKET_IDS = {
    "스마트스토어": 10200,
    "11번가": 10201,
    "G마켓/옥션": 10202,
    "쿠팡": 14516,
}
```

## ESM(G마켓/옥션) 자동화

### API 방식
- Selenium JavaScript fetch로 브라우저 세션 사용
- `item.esmplus.com` API 호출
- 2차 인증은 수동 처리 필요

### 주요 URL
- 로그인: `https://signin.esmplus.com/login`
- 상품관리: `https://item.esmplus.com`
