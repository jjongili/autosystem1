# 모바일 반응형 개선 계획

## 현재 상태 분석

### 1. login.html - 반응형 미구현
- @media 쿼리: 없음
- 문제점: padding 40px 고정, 모바일에서 과도함

### 2. index.html - 부분 구현
- @media 쿼리: 3개 (1200px, 768px, 1024px)
- 구현됨: SMS 패널, 차트, 불사자 대시보드
- 미구현: 상단 네비게이션, 탭 메뉴, 관제센터 카드

### 3. pconomy_dashboard_v3.html - 완전 구현
- @media 쿼리: 2개 (1024px, 480px)
- 노치 지원, 터치 스크롤 최적화

### 4. bulsaja_dashboard_final.html - 완전 구현
- @media 쿼리: 2개 (1024px, 480px)
- 테이블 ↔ 카드뷰 전환

---

## Breakpoint 전략 (통일)

| Breakpoint | 용도 |
|------------|------|
| 1200px | 대형 → 중형 화면 전환 |
| 1024px | 태블릿 (테이블→카드뷰) |
| 768px | 태블릿 세로 |
| 480px | 모바일 폰 |

---

## 파일별 개선 계획

### 1. login.html (신규 추가)

```css
/* 모바일 반응형 */
@media (max-width: 480px) {
    .login-container {
        margin: 20px;
        padding: 30px 25px;
        border-radius: 12px;
    }

    .logo h1 {
        font-size: 20px;
    }

    .logo p {
        font-size: 13px;
    }

    .form-group input {
        padding: 12px 14px;
        font-size: 15px;
    }

    .login-btn {
        padding: 12px;
        font-size: 15px;
    }
}
```

---

### 2. index.html 추가 필요 CSS

#### 2-1. 상단 네비게이션 반응형
```css
@media (max-width: 768px) {
    /* 상단 헤더 */
    .header {
        padding: 10px 15px;
        flex-wrap: wrap;
    }

    .header-left {
        width: 100%;
        justify-content: space-between;
        margin-bottom: 10px;
    }

    .header-right {
        width: 100%;
        justify-content: flex-end;
    }

    /* 탭 메뉴 가로 스크롤 */
    .main-tabs {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
    }

    .main-tabs::-webkit-scrollbar {
        display: none;
    }

    .tab-item {
        white-space: nowrap;
        padding: 8px 12px;
        font-size: 12px;
    }
}
```

#### 2-2. 관제센터 카드 반응형
```css
@media (max-width: 768px) {
    .monitor-container {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
        gap: 8px;
    }

    .monitor-card {
        width: 100% !important;
        min-width: auto !important;
        max-width: none !important;
    }
}
```

#### 2-3. SMS 대화창 반응형
```css
@media (max-width: 768px) {
    .sms-template-panel {
        position: fixed;
        left: 0;
        right: 0;
        bottom: 0;
        width: 100%;
        height: 60vh;
        border-left: none;
        border-top: 1px solid #e0e0e0;
        border-radius: 16px 16px 0 0;
        z-index: 1000;
    }

    .conversation-messages {
        padding: 10px;
    }

    .msg-item {
        max-width: 85%;
    }
}
```

#### 2-4. 매출현황 차트 반응형
```css
@media (max-width: 480px) {
    .sales-summary {
        gap: 10px;
    }

    .summary-card {
        min-width: calc(50% - 10px);
        padding: 12px;
    }

    .summary-value {
        font-size: 16px;
    }

    .summary-label {
        font-size: 11px;
    }
}
```

#### 2-5. 마케팅분석 테이블 반응형
```css
@media (max-width: 1024px) {
    .marketing-account-table {
        display: none;
    }

    .marketing-card-view {
        display: block;
    }
}
```

---

### 3. style.css 공통 반응형 추가

```css
/* 모바일 공통 */
@media (max-width: 768px) {
    /* 컨텐츠 패딩 축소 */
    .main-content {
        padding: 10px;
    }

    .card {
        padding: 15px;
        border-radius: 10px;
    }

    /* 버튼 터치 영역 확대 */
    button, .btn {
        min-height: 44px;
        min-width: 44px;
    }

    /* 입력 필드 터치 최적화 */
    input, select, textarea {
        font-size: 16px; /* iOS 줌 방지 */
    }
}

@media (max-width: 480px) {
    /* 폰트 크기 조정 */
    h1 { font-size: 20px; }
    h2 { font-size: 18px; }
    h3 { font-size: 16px; }

    /* 테이블 가로 스크롤 */
    .table-container {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
    }
}
```

---

## 구현 우선순위

1. **login.html** - 간단, 빠른 적용 가능
2. **index.html 상단 네비게이션** - 모든 페이지 공통
3. **index.html SMS 패널** - 자주 사용
4. **index.html 관제센터** - 복잡, 카드뷰 전환 필요
5. **index.html 마케팅분석** - 테이블→카드뷰 전환 필요

---

## 추가 고려사항

### 터치 최적화
- 버튼 최소 크기: 44x44px (Apple HIG)
- 터치 타겟 간격: 8px 이상

### iOS Safari 대응
- `input` font-size 16px 이상 (자동 줌 방지)
- `-webkit-overflow-scrolling: touch` (스크롤 관성)
- Safe Area (노치) 대응: `env(safe-area-inset-*)`

### 성능 최적화
- CSS 미디어 쿼리로 불필요한 요소 `display: none`
- 이미지 lazy loading
- 터치 이벤트 passive 옵션

---

## 예상 작업량

| 파일 | 예상 코드량 | 난이도 |
|------|------------|--------|
| login.html | 30줄 | 쉬움 |
| index.html 네비 | 50줄 | 보통 |
| index.html SMS | 80줄 | 보통 |
| index.html 관제 | 100줄 | 어려움 |
| index.html 마케팅 | 150줄 | 어려움 |
| style.css 공통 | 60줄 | 쉬움 |
| **총계** | ~470줄 | - |
