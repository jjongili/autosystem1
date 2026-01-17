# 구매대행 통합관리 시스템 설정 가이드

## 📁 폴더 구조

```
web_system/
├── server.py              # 메인 서버
├── requirements.txt       # 패키지 목록
├── credentials.json       # 구글 서비스 계정 키 (직접 추가)
├── templates/
│   ├── login.html        # 로그인 페이지
│   └── index.html        # 메인 대시보드
├── static/               # 정적 파일 (자동 생성)
└── pw_sessions/          # SMS 브라우저 프로필 (자동 생성)
    ├── 8295/
    ├── 8217/
    └── 4682/
```

---

## 🚀 설치 및 실행

### 1. 패키지 설치
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 구글 서비스 계정 설정
1. [Google Cloud Console](https://console.cloud.google.com/) 접속
2. 프로젝트 생성
3. Google Sheets API, Google Drive API 활성화
4. 서비스 계정 생성 → JSON 키 다운로드
5. `credentials.json`으로 이름 변경 후 `web_system/` 폴더에 저장

### 3. 구글 시트 준비

#### 계정목록 탭 (헤더)
| 플랫폼 | 계정명 | 아이디 | 비밀번호 | API Key | API Secret | 메모 |

#### 담당자 탭 (헤더)
| 아이디 | 비밀번호 |

예시:
| 아이디 | 비밀번호 |
|--------|----------|
| admin  | admin123 |
| 홍길동 | pass1234 |

### 4. 시트 공유
- 서비스 계정 이메일 (credentials.json 내 `client_email`)에 **편집자** 권한 공유

### 5. 서버 실행
```bash
python server.py
```

### 6. 접속
- 서버 PC: http://localhost:8000
- 다른 PC: http://서버IP:8000

---

## 📱 SMS 초기 설정 (최초 1회)

1. 웹에서 로그인
2. SMS 탭에서 각 폰 버튼 클릭 (8295, 8217, 4682)
3. 열리는 구글 메시지 웹에서 QR 로그인 (해당 폰으로 스캔)
4. 이후 세션 유지되어 자동 로그인

---

## 🔧 환경 변수 (선택)

`.env` 파일 또는 환경 변수로 설정 가능:

```env
CREDENTIALS_FILE=./credentials.json
SPREADSHEET_NAME=계정관리
HOST=0.0.0.0
PORT=8000
SECRET_KEY=your-secret-key
```

---

## 🎮 기능 설명

### 📱 SMS 탭
- **폰 버튼**: 개별 SMS 브라우저 실행
- **전체 실행**: 3개 브라우저 동시 실행
- **새로고침**: 최신 메시지 로드
- **자동 새로고침**: 5초마다 자동 갱신
- **인증코드**: 자동 추출 + 복사 버튼
- **메시지 전송**: 발신번호 선택해서 전송

### 📋 계정관리 탭
- **플랫폼 필터**: 스마트스토어/쿠팡/11번가/ESM
- **검색**: 계정명, ID로 검색
- **로그인(🚀)**: 플랫폼 URL 열고 ID 복사
- **복사(📋)**: ID 클립보드 복사
- **수정(✏️)**: 계정 정보 수정
- **삭제(🗑️)**: 계정 삭제

---

## 🔒 보안 참고

- 담당자 비밀번호는 평문 또는 SHA256 해시 저장 가능
- 세션은 8시간 유지 (설정 변경 가능)
- 내부망에서만 사용 권장

---

## ❓ 문제 해결

### "구글 시트 연결 실패"
- credentials.json 경로 확인
- 시트 이름 확인 (`SPREADSHEET_NAME`)
- 서비스 계정에 시트 공유 확인

### "SMS 브라우저 실행 안됨"
- playwright 브라우저 설치 확인: `playwright install chromium`
- headless=False 필수 (QR 로그인)

### "접속이 안됨"
- 방화벽에서 8000 포트 허용
- 서버 PC의 IP 주소 확인
