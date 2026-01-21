# 불사자 API 데이터 구조

## original_skus vs uploadSkus

### original_skus (원본 - 수집 시 데이터)
```json
{
  "skuRef": "5436191106176",
  "origin_price": 138,              // 위안 가격 그대로
  "sale_price": 138,                // 위안 가격 그대로
  "id": "1",
  "text": "一维便携式2100",          // 중국어 원본
  "text_ko": "1차원 휴대용 2100",    // 한글 번역
  "urlRef": "https://...",
  "stock": 125,
  "main_product": false,
  "exclude": false
}
```

### uploadSkus (업로드용 - 가격 변환됨)
```json
{
  "skuRef": "5506700415611",
  "_origin_price": 208,             // 위안 원가 - 절대 수정 금지!
  "origin_price": 43888,            // 원화 할인전 가격 (스마트스토어 정상가)
  "sale_price": 115300,             // 원화 할인후 가격 (스마트스토어 판매가)
  "main_product": true,
  "exclude": false,                 // 수정 금지! 마켓 옵션 구조 깨짐
  "id": "2",                        // 조합형 옵션 ID - 수정 금지
  "text": "B. 2D 휴대용 M9...",     // 한글 옵션명 (A., B. 접두사)
  "_text": "二维便携式M9...",        // 중국어 원본
  "urlRef": "https://...",
  "stock": 137
}
```

## 수정 가능한 필드 (3개만!)
- `origin_price`: 원화 할인전 가격 (스마트스토어 정상가)
- `sale_price`: 원화 할인후 가격 (스마트스토어 판매가)
- `main_product`: true/false

## 절대 수정 금지 필드
- `_origin_price`: 위안 원가
- `exclude`: 제외 여부 (마켓 옵션 구조 깨짐!)
- `id`: 조합형 옵션 ID
- `text`, `_text`: 옵션명
- `skuRef`, `urlRef`, `stock`

## 스마트스토어 150% 규칙
- **origin_price (할인전 가격) 기준**으로 판단
- 대표옵션 origin_price의 50%~150% 범위만 허용
- 불사자 버그: sale_price로 판단함 → 주의!

## 가격 계산 설정 (uploadBase_price)
```json
{
  "card_fee": 3.3,         // 카드 수수료 %
  "discount_rate": 20,     // 할인율 %
  "discount_unit": "%",
  "percent_margin": 25,    // 마진율 %
  "plus_margin": 10000,    // 추가 마진 (원)
  "raise_digit": 100       // 올림 단위 (원)
}
```

**가격 계산 공식 (불사자 기준):**
1. **원화원가 = 위안원가 × 환율** (배송비 미포함!)
2. **정상가(origin_price) = 원화원가 + 원화원가 × (카드수수료% + 마진율%) + 정액마진 + 해외배송비**
3. **마켓별 판매가 = 정상가 × (1 + 마켓수수료%) × (1 - 할인율%)**

**주의:**
- 원화원가에는 배송비가 포함되지 않음! 배송비는 정상가 계산 시에만 더해짐.
- 마켓별로 수수료가 다르게 적용됨 (uploadFake_pct)

## 마켓별 판매가 가중치 (uploadFake_pct) - 마켓 수수료
```json
{
  "smartstore": 8,   // 스마트스토어 8%
  "st11": 12,        // 11번가 12%
  "gmarket": 15,     // 지마켓 15%
  "auction": 15,     // 옥션 15%
  "coupang": 13      // 쿠팡 13%
}
```

## uploadSkuProps 구조 (옵션 속성)
```json
{
  "mainOption": {
    "prop_name": "색상별로 정렬",
    "_prop_name": "颜色分类",
    "pid": 1,
    "values": [
      {
        "vid": 1,                    // 옵션 ID (uploadSkus.id와 매핑)
        "name": "A. A형 직목 난로...",
        "_name": "A款直脖柴炉...",
        "name_ko": "A형 직목 난로...",
        "imageUrl": "https://...",
        "exclude": false,            // 여기서도 exclude 관리!
        "origin_priceRef": 10603,
        "sale_priceRef": 10603,
        "_origin_priceRef": 51
      }
    ]
  },
  "subOption": []
}
```

**중요:** `uploadSkuProps.mainOption.values[].vid` = `uploadSkus[].id`

## 실제 데이터 예시
대표상품 (main_product: true):
- id: "5"
- _origin_price: 51 (위안)
- origin_price: 10,761 (원화 할인전)
- sale_price: 55,800 (원화 할인후)

150% 범위 계산 (origin_price 기준):
- 대표: 10,761원
- 최소: 5,380원 (50%)
- 최대: 16,141원 (150%)

**마지막 옵션 exclude 예시:**
- id: "29" → `exclude: true` (uploadSkuProps에서도 동일)

## 수정하면 안되는 필드
- `_origin_price`: 위안 원가
- `id`: 조합형 옵션 ID (vid↔id 매핑)
- `text`, `_text`: 옵션명
- `skuRef`, `urlRef`, `stock`

## 카테고리 API
- 엔드포인트: `POST /api/manage/category/bulsaja_category`
- 요청: `{"keyword": "상품명"}`
- 응답: `categoryMap.ss[]` (스마트스토어), `categoryMap.cp[]` (쿠팡) 등
- 주의: 카테고리 검색만으로 저장되지 않음, 별도 업데이트 필요

## uploadCategory 구조 (카테고리 설정)
```json
{
  "uploadCategory": {
    "esm_category": {
      "name": "캠핑/낚시>취사용품>버너",
      "code": "300029653",
      "categoryList": [...],
      "search": "검색어"
    },
    "ss_category": {
      "name": "스포츠/레저>캠핑>취사용품>버너",
      "code": "50002660",
      "categoryList": [...]
    },
    "cp_category": {
      "name": "스포츠/레져-캠핑-캠핑주방용품-버너/스토브",
      "code": "81957",
      "categoryList": [...]
    },
    "est_category": {...},
    "est_global_category": {...}
  }
}
```

**ESM 카테고리 중요사항:**
- ESM = G마켓/옥션 통합 카테고리
- **카테고리에 따라 반품/교환 배송비 최대값이 다름!**
- 일부 카테고리는 반품배송비 2만원까지만 설정 가능
- 배송비를 높게 설정하려면 **특정 카테고리로 강제 지정** 필요
- 카테고리 오류 메시지: "해당 카테고리는 사용하실 수 없습니다"

**카테고리 코드 예시:**
- ESM 버너: 300029653
- ESM 바비큐그릴: 300029658
- ESM 화로대: 300029660
- 스마트스토어 버너: 50002660
- 쿠팡 버너/스토브: 81957

## API 헤더
- `Accesstoken`: 액세스 토큰
- `Refreshtoken`: 리프레시 토큰
- `Content-Type`: application/json

## 업로드 조건 (status)
- 0: 수집 완료
- 1: 수정중
- 2: 검토 완료
- 3: 판매중/업로드 완료

## 상품 목록 조회 API (/manage/list/serverside)

**중요: 서버사이드 필터 형식**

상품 리스트는 서버사이드에서 처리됨. `filterModel` 형식 주의!

### 올바른 필터 형식 (text 타입 - 단일 값)
```json
{
  "request": {
    "startRow": 0,
    "endRow": 100,
    "sortModel": [],
    "filterModel": {
      "marketGroupName": {
        "filterType": "text",
        "type": "equals",
        "filter": "그룹명"
      },
      "status": {
        "filterType": "text",
        "type": "equals",
        "filter": "0"
      }
    }
  }
}
```

### 상태 필터 OR 조건 (여러 상태값 동시 필터링)
```json
{
  "filterModel": {
    "status": {
      "filterType": "text",
      "operator": "OR",
      "conditions": [
        {"filterType": "text", "type": "equals", "filter": "0"},
        {"filterType": "text", "type": "equals", "filter": "1"},
        {"filterType": "text", "type": "equals", "filter": "2"}
      ]
    }
  }
}
```
→ 여러 상태값을 OR로 묶을 때 `operator: "OR"` + `conditions` 배열 사용

### 잘못된 필터 형식 (set 타입) - 사용 금지!
```json
{
  "filterModel": {
    "marketGroupName": {
      "filterType": "set",
      "values": ["그룹명"]
    }
  }
}
```
→ 이 형식은 불사자 API에서 작동 안 함!

### 참조 파일
- `6. bulsaja_image_translator_v2.0+api.py` - 올바른 필터 구현 예시
- `bulsaja_common.py` - `get_products_by_group()` 메서드
