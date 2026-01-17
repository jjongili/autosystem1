# 네이버 쇼핑검색광고 상품소재 자동 등록

## 개요

스마트스토어 상품을 네이버 쇼핑검색광고에 자동으로 등록하는 스크립트입니다.

## 플로우

```
구글시트 (스토어 정보)
    ↓
커머스 API (상품 목록 + 상품명)
    ↓
네이버 쇼핑 검색 API (상품명 → nvmid 조회)
    ↓
SearchAd API (광고소재 등록)
```

## 필요 API 키

### 1. 구글시트 서비스 계정
- Google Cloud Console에서 서비스 계정 생성
- JSON 키 파일 다운로드
- 구글시트에 서비스 계정 이메일 공유

### 2. 네이버 검색 API (developers.naver.com)
- https://developers.naver.com 접속
- 애플리케이션 등록 → "검색" API 선택
- Client ID, Client Secret 발급

### 3. 커머스 API (스마트스토어)
- 스마트스토어 판매자센터 → API 설정
- 애플리케이션 등록 → client_id, client_secret 발급
- 필요 권한: 상품 조회

### 4. SearchAd API (검색광고)
- 네이버 광고 → API 사용관리
- API KEY, SECRET KEY, CUSTOMER_ID 발급

## 설치

```bash
pip install requests python-dotenv gspread oauth2client bcrypt
```

## 환경변수 설정 (.env)

```env
# 구글시트
SERVICE_ACCOUNT_JSON=service_account.json
SPREADSHEET_KEY=1234567890abcdefghij

# 네이버 검색 API
NAVER_CLIENT_ID=wLJxa2pupN4FLzJXx5uv
NAVER_CLIENT_SECRET=HpZRVLTOTl

# SearchAd API
SEARCHAD_API_KEY=0100000000...
SEARCHAD_SECRET_KEY=AQAAAADW...
SEARCHAD_CUSTOMER_ID=2623436
```

## 구글시트 형식

시트 이름: `stores`

| store_name | client_id | client_secret | biz_id | active |
|------------|-----------|---------------|--------|--------|
| 푸로테카 | xxx | $2a$... | grp-xxx | TRUE |
| 더일레븐 | yyy | $2a$... | grp-yyy | TRUE |

- `store_name`: 스토어 이름 (캠페인 검색용)
- `client_id`: 커머스 API client_id
- `client_secret`: 커머스 API client_secret (bcrypt 해시)
- `biz_id`: 비즈채널 ID (선택)
- `active`: 활성화 여부 (TRUE/FALSE)

## 사용법

### 기본 실행
```bash
python shopping_ad_automation.py
```

### 특정 스토어 지정
```bash
python shopping_ad_automation.py --store 푸로테카
```

### 상품 수 지정
```bash
python shopping_ad_automation.py --store 푸로테카 --max 50
```

### 입찰가 지정
```bash
python shopping_ad_automation.py --store 푸로테카 --bid 100
```

### 조회만 (등록 안함)
```bash
python shopping_ad_automation.py --store 푸로테카 --dry-run
```

### 전체 옵션
```bash
python shopping_ad_automation.py \
    --store 푸로테카 \
    --max 100 \
    --bid 70 \
    --dry-run
```

## 옵션

| 옵션 | 단축 | 설명 | 기본값 |
|------|------|------|--------|
| `--store` | `-s` | 대상 스토어명 | 첫 번째 스토어 |
| `--max` | `-m` | 최대 상품 수 | 10 |
| `--bid` | `-b` | 입찰가 (원) | 70 |
| `--dry-run` | `-d` | 조회만 (등록 안함) | False |

## 주요 함수

### nvmid 조회
```python
from shopping_ad_automation import find_nvmid_by_product_name

nvmid = find_nvmid_by_product_name("서서일하는 홈오피스 모션 작업대", "푸로테카")
print(nvmid)  # 90360647040
```

### 상품 목록 조회
```python
from shopping_ad_automation import fetch_products_with_names

products = fetch_products_with_names(client_id, client_secret, max_count=10)
# [{"channelProductNo": "12816136091", "name": "서서일하는 홈오피스..."}, ...]
```

### 광고소재 등록
```python
from shopping_ad_automation import register_shopping_ads

results = register_shopping_ads(
    adgroup_id="grp-xxx",
    nvmids=["90360647040", "90262027583"],
    bid_amt=70
)
```

## 에러 해결

### 1. nvmid 조회 실패
- 네이버 쇼핑에 등록되지 않은 상품
- 상품명이 너무 길거나 특수문자 포함
- API 호출 제한 (하루 25,000건)

### 2. 커머스 API 403
- IP 허용 설정 확인
- 권한 스코프 확인

### 3. SearchAd API 3826 에러
- nvmid가 아닌 channelProductNo 사용 시 발생
- referenceKey에 nvmid 사용 필수

## 참고

- nvmid = 네이버쇼핑상품번호 = productId
- channelProductNo = 스마트스토어 상품번호
- 커머스 API는 nvmid를 제공하지 않음 → 네이버 쇼핑 검색 API로 조회 필요
