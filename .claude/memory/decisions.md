# Decisions - 주요 결정사항

## 기술 결정

### 마케팅 분석 로그인 방식
- **결정**: Enter 키로 로그인 (버튼 클릭 X)
- **이유**: 로그인 버튼이 여러 개 있어서 잘못된 버튼 클릭 가능
- **선택자**:
  - ID: `input[placeholder="아이디 또는 이메일 주소"]`
  - PW: `input[placeholder="비밀번호"]`

### 로그 출력 방식
- **결정**: `print(msg, flush=True)` + 타임스탬프
- **이유**: subprocess에서 실시간 로그 확인 필요

### gspread API 사용
- **결정**: `ws.update(values=body, range_name='A1')` 형식
- **이유**: 새 버전 API 호환

## 아키텍처 결정

### 브라우저 자동화
- Selenium: 마케팅 분석 (marketing_collector.py)
- Playwright: SMS 기능 (server.py)

### 레이저레벨기
- **결정**: 공구로 허용
- **이유**: PPT는 레이저포인터만 금지, 레벨기/줄자/측정기는 건설공구
- **일시**: 2026-01-16 12:25:48
---

### 레이저제모기
- **결정**: 의료기기로 금지
- **이유**: 의료기기법 위반, MEDICAL_KEYWORDS에 추가
- **일시**: 2026-01-16 12:25:55
---
