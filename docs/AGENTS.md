# AGENTS.md - 프로젝트 지식 베이스

**생성일:** 2026-01-06  
**프로젝트:** autosystem1 (온라인 셀러 자동화 시스템)

## 개요

이 프로젝트는 온라인 셀러 및 콘텐츠 크리에이터를 위한 자동화 시스템입니다. 주로 스마트스토어, 11번가, 알리프라이스 등 이커머스 플랫폼의 상품 관리, 주문 모니터링, 번역, 찜 자동화 등의 기능을 제공합니다.

## 프로젝트 구조

```
autosystem1/
├── *.py                    # 메인 자동화 스크립트
├── chrome_extension/       # 크롬 확장 프로그램
├── FocusFlow/             # PyQt6 기반 GUI 애플리케이션
├── web_system/            # FastAPI 웹 시스템
├── sa_automation/         # 스마트스토어 자동화
├── *.json                 # 설정 파일 (API 키, 번역 설정 등)
├── *.xlsx                 # 데이터베이스 파일
└── debug_responses_meta/  # 디버깅 데이터
```

## 빌드/테스트 명령어

### Python 환경
```bash
# 가상환경 생성 (권장)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r web_system/requirements.txt
pip install -r FocusFlow/requirements.txt

# 개별 테스트 실행
python test_gemini_api.py
python test_commerce_detail.py
python test_real_product.py

# GUI 애플리케이션 실행
python FocusFlow/main.py
python 10. esm_manager_gui.py

# 웹 시스템 실행
cd web_system
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Chrome 확장 프로그램
```bash
# 확장 프로그램 로드 (개발자 모드)
# 1. 크롬 브라우저 > 확장 프로그램 > 개발자 모드
# 2. '압축해제된 확장 프로그램을 로드합니다' 선택
# 3. chrome_extension 폴더 선택
```

## 코드 스타일 가이드

### 1. 기본 규칙
- **언어:** 모든 대화, 주석, 설명은 반드시 **한국어**로 작성
- **인코딩:** 모든 Python 파일은 `# -*- coding: utf-8 -*-` 선언
- **Python 버전:** Python 3.8+ 호환 코드 작성

### 2. 임포트 순서
```python
# 표준 라이브러리
import os
import sys
import time
from datetime import datetime

# 서드파티 라이브러리
import requests
import gspread
from selenium import webdriver

# 로컬 임포트
from config import load_config
from utils import helper_function
```

### 3. 네이밍 컨벤션
- **변수/함수:** snake_case (`user_data`, `process_order`)
- **클래스:** PascalCase (`GoogleSheetManager`, `OrderProcessor`)
- **상수:** UPPER_SNAKE_CASE (`API_KEY`, `MAX_RETRIES`)
- **파일명:** 영문 소문자 + 언더스코어 (`order_monitor.py`)

### 4. 타입 힌팅
```python
from typing import List, Dict, Optional, Tuple, Union

def process_orders(
    orders: List[Dict[str, Any]], 
    user_id: Optional[str] = None
) -> Tuple[bool, str]:
    """주문 처리 함수"""
    pass
```

### 5. 에러 핸들링
```python
# 좋은 예
try:
    result = api_call()
except requests.Timeout:
    print("[TIMEOUT] API 호출 시간 초과")
    return None
except requests.RequestException as e:
    print(f"[ERROR] API 호출 실패: {e}")
    return None
except Exception as e:
    print(f"[UNEXPECTED] 예상치 못한 오류: {e}")
    return None

# 나쁜 예 (Bare except 사용 금지)
try:
    result = api_call()
except:  # ❌ Bare except 사용 금지
    pass
```

### 6. 로깅 형식
```python
# 성공 메시지
print(f"[OK] 구글 시트 연결 성공: {sheet.title}")

# 에러 메시지
print(f"[ERR] API 호출 실패: {status_code}")

# 정보 메시지
print(f"[INFO] 처리 중인 상품 수: {total_count}")

# 디버그 메시지
print(f"[DEBUG] 응답 데이터: {response_data[:100]}...")
```

### 7. API 호출 패턴
```python
def call_api(url: str, payload: Dict[str, Any]) -> Optional[Dict]:
    """API 호출 표준 패턴"""
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    try:
        response = requests.post(
            url, 
            headers=headers, 
            json=payload, 
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        print("[TIMEOUT] API 응답 시간 초과")
        return None
    except requests.HTTPError as e:
        print(f"[HTTP_ERROR] {e.response.status_code}: {e.response.text}")
        return None
```

### 8. 설정 관리
```python
# .env 파일 사용 (권장)
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY")

# JSON 설정 파일
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)
```

### 9. 클래스 구조
```python
class DataManager:
    """데이터 관리 클래스"""
    
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.data = []
        self._load_config()
    
    def _load_config(self) -> None:
        """설정 로드 (내부 메서드)"""
        pass
    
    def process_data(self) -> bool:
        """데이터 처리"""
        try:
            # 처리 로직
            return True
        except Exception as e:
            print(f"[ERR] 데이터 처리 실패: {e}")
            return False
```

### 10. 동시성 처리
```python
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

def process_stores_parallel(stores: List[Dict], max_workers: int = 4):
    """병렬 처리 표준 패턴"""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_single_store, store): store 
            for store in stores
        }
        
        for future in as_completed(futures):
            store = futures[future]
            try:
                result = future.result()
                print(f"[OK] {store['name']} 처리 완료")
            except Exception as e:
                print(f"[ERR] {store['name']} 처리 실패: {e}")
```

## 주요 라이브러리

- **웹 자동화:** `selenium`, `playwright`
- **API 통신:** `requests`, `aiohttp`
- **구글 시트:** `gspread`, `google-auth`
- **GUI:** `PyQt6`, `tkinter`
- **웹 프레임워크:** `FastAPI`, `uvicorn`
- **데이터 처리:** `pandas`, `openpyxl`
- **AI API:** `google.generativeai`, `anthropic`

## 테스팅

### 단위 테스트
```python
# test_example.py
import unittest
from main import process_data

class TestMainFunction(unittest.TestCase):
    def test_process_data_success(self):
        """정상 데이터 처리 테스트"""
        test_data = {"key": "value"}
        result = process_data(test_data)
        self.assertTrue(result)
    
    def test_process_data_failure(self):
        """오류 상황 테스트"""
        test_data = None
        result = process_data(test_data)
        self.assertFalse(result)

if __name__ == "__main__":
    unittest.main()
```

### 통합 테스트
```bash
# 개별 테스트 실행
python -m unittest test_example.py

# 전체 테스트 실행
python -m unittest discover tests/
```

## 보안 주의사항

1. **API 키 관리:** 절대 코드에 직접 작성하지 말고 `.env` 파일 사용
2. **인증 정보:** `credentials.json` 등은 `.gitignore`에 추가
3. **데이터 로깅:** 민감정보는 로그에 출력하지 않음
4. **파일 권한:** 설정 파일은 적절한 권한으로 관리

## 배포

### 실행 파일 생성 (PyInstaller)
```bash
# GUI 애플리케이션
pyinstaller --onefile --windowed main.py

# 콘솔 애플리케이션
pyinstaller --onefile script.py
```

### Docker 배포
```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 특이사항

1. **한국어 우선:** 모든 출력과 주석은 한국어로 작성
2. **비개발자 친화:** 복잡한 기술 용어 대신 쉬운 설명 사용
3. **자동 검증:** 코드 수정 후 반드시 자체 테스트 수행
4. **예외 처리:** 외부 API 호출은 반드시 타임아웃과 예외 처리 포함
5. **병렬 처리:** 대용량 데이터는 ThreadPoolExecutor 사용 권장

## 참고

- 이 프로젝트는 온라인 셀러의 실제 비즈니스 요구에 맞춰 개발됨
- 사용자는 비개발자일 수 있으므로 UI/UX에 각별한 주의 필요
- 안정성과 신뢰성이 최우선 가치임