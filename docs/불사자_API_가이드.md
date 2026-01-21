# 불사자 API 가이드

> 불사자(Bulsaja) 상품 관리 플랫폼 API 완벽 가이드
> 최종 업데이트: 2026-01-20

---

## 목차

1. [API 개요](#1-api-개요)
2. [인증](#2-인증)
3. [상품 API](#3-상품-api)
4. [마켓 그룹 API](#4-마켓-그룹-api)
5. [업로드 API](#5-업로드-api)
6. [삭제 API](#6-삭제-api)
7. [SKU 구조](#7-sku-구조)
8. [가격 계산](#8-가격-계산)
9. [필드 수정 규칙](#9-필드-수정-규칙)

---

## 1. API 개요

### Base URL
```
https://api.bulsaja.com/api
```

### 주요 엔드포인트

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/manage/list/serverside` | POST | 상품 목록 조회 |
| `/manage/sourcing-product/{id}` | GET | 상품 상세 조회 |
| `/sourcing/uploadfields/{id}` | PUT | 상품 정보 수정 |
| `/market/{market_id}/upload/` | POST | 마켓 업로드 |
| `/market/delete/sourcingproducts` | POST | 상품 삭제 |
| `/market/groups/` | POST | 마켓 그룹 목록 |
| `/market/groups/valid` | GET | 유효한 마켓 그룹 |
| `/market/{market_id}/` | GET | 마켓 상세 정보 |
| `/manage/category/bulsaja_category` | POST | 카테고리 검색 |
| `/sourcing/bulk-copy-market-group` | POST | 마켓 그룹으로 상품 복사 |

---

## 2. 인증

### 헤더 구조
```http
Accept: application/json, text/plain, */*
Content-Type: application/json
accesstoken: {JWT_ACCESS_TOKEN}
refreshtoken: {JWT_REFRESH_TOKEN}
Origin: https://www.bulsaja.com
Referer: https://www.bulsaja.com/
```

### 토큰 설명
- **accesstoken**: 단기 액세스 토큰 (소문자)
- **refreshtoken**: 장기 리프레시 토큰 (소문자)

> **주의**: 헤더 키는 반드시 소문자로 작성해야 합니다.

---

## 3. 상품 API

### 3.1 상품 목록 조회

**엔드포인트**: `POST /manage/list/serverside`

**Request Body**:
```json
{
  "startRow": 0,
  "endRow": 100,
  "filterModel": {},
  "sortModel": []
}
```

**Response 주요 필드**:
| 필드 | 타입 | 설명 |
|------|------|------|
| `ID` | string | 불사자 상품 ID |
| `date` | string | 수집일 (예: 2025/12/24) |
| `productName` | string | 번역된 상품명 |
| `marketType` | string | 마켓 타입 (uploaded 등) |
| `status` | number | 상태 (0=수집, 1=수정중, 2=검토, 3=판매중, 4=업로드완료) |
| `uploadSkus` | array | SKU 배열 |
| `uploadedSuccessUrl` | object | 마켓별 업로드 상품번호 |

---

### 3.2 상품 상세 조회

**엔드포인트**: `GET /manage/sourcing-product/{product_id}`

**Response 전체 필드**:

#### 기본 정보
| 필드 | 타입 | 설명 |
|------|------|------|
| `ID` | string | 불사자 상품 ID |
| `date` | string | 수집일시 |
| `product_url` | string | 원본 상품 URL |
| `type` | string | 상품 타입 (oversea=해외) |
| `method` | string | 수집 방법 |
| `stock` | number | 재고 수량 |
| `brand` | string | 브랜드명 (중국어) |
| `originalProductName` | string | 원본 상품명 (중국어) |
| `productName` | string | 번역된 상품명 |
| `marketType` | string | 마켓 타입 |
| `category_level` | number | 카테고리 레벨 |

#### 업로드 정보
| 필드 | 타입 | 설명 |
|------|------|------|
| `uploadedSuccessUrl` | object | 마켓별 업로드 상품번호 |
| `uploadedMarkets` | string | 업로드된 마켓 목록 |
| `uploadedProductDate` | string | 업로드 일시 |
| `uploadBulsajaCode` | string | 불사자 고유 코드 |
| `uploadRecentExchangeRate` | number | 적용 환율 |

#### 상품명 필드
| 필드 | 타입 | 수정 | 설명 |
|------|------|------|------|
| `uploadCommonProductName` | string | O | 공통 상품명 |
| `uploadCoupangProductName` | string | O | 쿠팡용 상품명 |
| `uploadSmartStoreProductName` | string | O | 스마트스토어용 상품명 |
| `uploadSearchCategory` | string | X | 카테고리 검색용 |
| `uploadProductSearchText` | string | X | 검색 텍스트 |

#### 이미지/비디오 필드
| 필드 | 타입 | 수정 | 설명 |
|------|------|------|------|
| `uploadThumbnails` | array | O | 썸네일 URL 배열 (최대 5개) |
| `videoUrls` | array | X | 원본 비디오 URL |
| `uploadVideoUrls` | array | O | 업로드용 비디오 URL |

#### 상세페이지 필드
| 필드 | 타입 | 수정 | 설명 |
|------|------|------|------|
| `detailContents` | object | X | 원본 상세페이지 |
| `uploadDetailContents` | object | O | 번역된 상세페이지 |
| `uploadDetail_page` | object | O | 상세페이지 설정 |

**uploadDetail_page 구조**:
```json
{
  "is_include_option_image": true,
  "bottom_image": "https://...",
  "top_image": "https://...",
  "is_include_fixed_image": true,
  "option_image_position": "TOP",
  "option_place_method": "DUAL",
  "is_include_product_name": true,
  "is_include_video": true
}
```

#### 태그 필드
| 필드 | 타입 | 수정 | 설명 |
|------|------|------|------|
| `tags` | array | X | 원본 태그 |
| `uploadCommonTags` | array | O | 공통 태그 (최대 20개) |
| `uploadSmartStoreTags` | array | O | 스마트스토어 태그 (최대 10개) |
| `groupFile` | string | O | 작업 그룹/태그 |

#### 연락처/배송 필드
| 필드 | 타입 | 수정 | 설명 |
|------|------|------|------|
| `uploadContact` | object | O | 연락처 정보 |
| `original_deliveryFee` | number | X | 원본 배송비 (위안) |
| `overseaDeliveryFee` | number | X | 해외배송비 (원) |

**uploadContact 구조**:
```json
{
  "refund_info": "환불 정보",
  "tel": "전화번호",
  "as_info": "구매문의 : 평일 10:00~17:00"
}
```

---

### 3.3 상품 정보 수정

**엔드포인트**: `PUT /sourcing/uploadfields/{product_id}`

**Request Body**: 상세 조회 응답의 data 객체 전체

---

## 4. 마켓 그룹 API

### 4.1 유효한 마켓 그룹 목록

**엔드포인트**: `GET /market/groups/vaild`

> **Note**: URL에 오타가 있습니다 (valid → vaild). 실제 API는 이 오타 URL을 사용합니다.

**Response**: 마켓 그룹 배열

```json
[
  {
    "id": 7538,
    "name": "22_리코즈",
    "user_id": 11669,
    "created_at": "2025-05-28 22:10:31",
    "updated_at": "2026-01-12 23:19:27",
    "base_price": { ... },
    "delivery": { ... },
    "fake_pct": { ... },
    "detail_page": { ... },
    "setting": { ... },
    "contact": { ... },
    "exchange": { ... },
    "is_global": 1,
    "sort_order": 7538,
    "detailRowData": [ ... ]
  }
]
```

#### 마켓 그룹 주요 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | number | 마켓 그룹 ID |
| `name` | string | 마켓 그룹명 (예: 22_리코즈) |
| `user_id` | number | 사용자 ID |
| `created_at` | string | 생성일시 |
| `updated_at` | string | 수정일시 |
| `base_price` | object | 가격 설정 |
| `delivery` | object | 배송 설정 |
| `fake_pct` | object | 마켓별 할인율 설정 |
| `detail_page` | object | 상세페이지 설정 |
| `setting` | object | 기타 설정 |
| `contact` | object | 연락처 정보 |
| `exchange` | object | 환율 설정 |
| `is_global` | number | 해외배송 여부 |
| `sort_order` | number | 정렬 순서 |
| `detailRowData` | array | 연결된 마켓 목록 |

#### base_price 구조 (가격 설정)

```json
{
  "card_fee": 3.3,
  "plus_margin": 15000,
  "raise_digit": 100,
  "discount_rate": 20,
  "discount_unit": "%",
  "percent_margin": 30
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `card_fee` | number | 카드 수수료 (%) |
| `plus_margin` | number | 추가 마진 (원) |
| `raise_digit` | number | 올림 단위 (원) |
| `discount_rate` | number | 할인율 |
| `discount_unit` | string | 할인 단위 (% 또는 원) |
| `percent_margin` | number | 마진율 (%) |

#### delivery 구조 (배송 설정)

```json
{
  "type": "FREE",
  "return_fee": 30000,
  "delivery_fee": 5000,
  "exchange_fee": 60000,
  "mountain_fee": 8000,
  "delivery_attribute_type": "TODAY"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | string | 배송비 타입 (FREE/PAID) |
| `return_fee` | number | 반품 배송비 |
| `delivery_fee` | number | 기본 배송비 |
| `exchange_fee` | number | 교환 배송비 |
| `mountain_fee` | number | 도서산간 추가비 |
| `delivery_attribute_type` | string | 발송 타입 (TODAY 등) |

#### fake_pct 구조 (마켓별 할인율)

```json
{
  "st11": 12,
  "auction": 15,
  "coupang": 13,
  "gmarket": 15,
  "smartstore": 8
}
```

#### detail_page 구조 (상세페이지 설정)

```json
{
  "top_image": "https://...",
  "bottom_image": "https://...",
  "is_include_video": true,
  "option_place_method": "DUAL",
  "option_image_position": "TOP",
  "is_include_fixed_image": true,
  "is_include_option_image": true,
  "is_include_product_name": true
}
```

#### setting 구조 (기타 설정)

```json
{
  "brand": "",
  "maker": "",
  "is_tax_free": false,
  "minor_limit": "AUTO",
  "shipment_date": 8,
  "max_purchase_qty": 0,
  "coupang_thumbnail_mode": "OPTION_IMAGE",
  "apply_lowest_price_option_for_smartstore": false
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `brand` | string | 브랜드명 |
| `maker` | string | 제조사명 |
| `is_tax_free` | boolean | 면세 여부 |
| `minor_limit` | string | 미성년자 구매 제한 (AUTO/NONE) |
| `shipment_date` | number | 발송 예정일 (일) |
| `max_purchase_qty` | number | 최대 구매 수량 (0=무제한) |
| `coupang_thumbnail_mode` | string | 쿠팡 썸네일 모드 |
| `apply_lowest_price_option_for_smartstore` | boolean | 스마트스토어 최저가 옵션 적용 |

#### exchange 구조 (환율 설정)

```json
{
  "rate": 208,
  "currency": "CNY",
  "auto_exchange": true
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `rate` | number | 현재 환율 |
| `currency` | string | 통화 (CNY) |
| `auto_exchange` | boolean | 자동 환율 적용 |

#### detailRowData 구조 (연결된 마켓 정보)

```json
[
  {
    "id": 6680,
    "market_group_id": 7538,
    "user_id": 11669,
    "type": "SMARTSTORE",
    "account": {
      "api_key": "...",
      "secret_key": "...",
      "is_manual_upload": true,
      "smartstore_seller_id": "email@gmail.com",
      "smartstore_seller_pw": "password"
    },
    "opt": {
      "phone_number": "010-xxxx-xxxx",
      "inbound_address": "반품교환지 주소",
      "outbound_address": "상품출고지 주소",
      "delivery_company_code": "CJGLS"
    },
    "state": true
  }
]
```

---

### 4.2 마켓 상세 정보

**엔드포인트**: `GET /market/{market_id}/`

**Response**:
```json
{
  "id": 10400,
  "market_group_id": 9662,
  "user_id": 11669,
  "created_at": "2024-...",
  "updated_at": "2025-...",
  "type": "SMARTSTORE",
  "account": {
    "api_key": "마켓 API 키",
    "secret_key": "마켓 시크릿 키",
    "is_manual_upload": false,
    "smartstore_seller_id": "판매자 이메일",
    "smartstore_seller_pw": "판매자 비밀번호"
  },
  "opt": {
    "phone_number": "010-xxxx-xxxx",
    "inbound_address": "반품교환지 주소",
    "inbound_address_no": "주소번호",
    "inbound_address_name": "반품교환지명",
    "outbound_address": "상품출고지 주소",
    "outbound_address_no": "주소번호",
    "outbound_address_name": "상품출고지명",
    "delivery_company_code": "CJGLS",
    "is_manual_upload": false
  }
}
```

### 마켓 타입
- `SMARTSTORE`: 스마트스토어
- `COUPANG`: 쿠팡
- `GMARKET`: 지마켓 (ESM으로 통합)
- `AUCTION`: 옥션 (ESM으로 통합)
- `ESM`: 지마켓/옥션 통합
- `ST11`: 11번가

---

### 4.3 마켓 타입별 account/opt 구조

#### SMARTSTORE (스마트스토어)

**account**:
```json
{
  "api_key": "API 키",
  "secret_key": "시크릿 키",
  "is_manual_upload": true,
  "smartstore_seller_id": "판매자 이메일",
  "smartstore_seller_pw": "판매자 비밀번호"
}
```

**opt**:
```json
{
  "phone_number": "010-xxxx-xxxx",
  "inbound_address": "반품교환지 주소",
  "inbound_address_no": 107725963,
  "inbound_address_name": "반품교환지",
  "outbound_address": "상품출고지 주소",
  "outbound_address_no": 107725962,
  "outbound_address_name": "상품출고지",
  "delivery_company_code": "CJGLS",
  "is_manual_upload": false
}
```

#### ESM (지마켓/옥션)

**account**:
```json
{
  "auction_id": "옥션 아이디",
  "gmarket_id": "지마켓 아이디"
}
```

**opt**:
```json
{
  "return_address": "반품지 주소",
  "return_zip_code": "우편번호",
  "pickup_address_code": "반품지 코드",
  "pickup_address_name": "반품지명",
  "delivery_company_code": "10001",
  "delivery_company_name": "대한통운",
  "dispatch_address_code": "출고지 코드",
  "dispatch_address_name": "출고지명"
}
```

#### ST11 (11번가)

**account**:
```json
{
  "api_key": "11번가 API 키"
}
```

**opt**:
```json
{
  "phone": "010-xxxx-xxxx",
  "inbound_addr": "반품교환지 주소",
  "inbound_addr_seq": "3",
  "inbound_addr_name": "반품/교환지",
  "outbound_addr_seq": "2",
  "outbound_addr_name": "출고지",
  "force_category_match": true,
  "send_close_template_no": "템플릿 번호",
  "send_close_template_name": "템플릿명"
}
```

#### COUPANG (쿠팡)

**account**:
```json
{
  "api_key": "쿠팡 API 키 (UUID)",
  "account_id": "계정 아이디",
  "account_pw": "계정 비밀번호",
  "secret_key": "시크릿 키",
  "vendor_code": "벤더 코드 (예: A01463289)"
}
```

**opt**:
```json
{
  "return_address": "반품지 주소",
  "return_zip_code": "우편번호",
  "return_center_code": "반품센터 코드",
  "return_charge_name": "반품지명",
  "delivery_company_code": "CJGLS",
  "outbound_shipping_day": "8",
  "return_address_detail": "상세 주소",
  "company_contact_number": "연락처",
  "outbound_shipping_address": "출고지 주소",
  "outbound_shipping_place_code": "출고지 코드"
}
```

---

## 5. 업로드 API

### 5.1 마켓 업로드

**엔드포인트**: `POST /market/{market_id}/upload/`

**Request Body**:
```json
{
  "productId": "U01KD7X9YZ7MD5A5H9S3Z87YWA4",
  "notices": null,
  "preventDuplicateUpload": false,
  "removeDuplicateWords": true,
  "targetMarket": "SMARTSTORE"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `productId` | string | O | 불사자 상품 ID |
| `notices` | null/string | X | 공지사항 |
| `preventDuplicateUpload` | boolean | X | 중복 업로드 방지 |
| `removeDuplicateWords` | boolean | X | 중복 단어 제거 |
| `targetMarket` | string | O | 대상 마켓 |

---

## 6. 삭제 API

### 6.1 상품 삭제

**엔드포인트**: `POST /market/delete/sourcingproducts`

**Request Body**:
```json
{
  "data": {
    "sourcingIds": ["U01KEXGR5TJZM0HMVS1JJXZVRZ9"],
    "deleteType": 0
  }
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `sourcingIds` | array | O | 삭제할 불사자 상품 ID 배열 |
| `deleteType` | number | O | 삭제 유형 (아래 참조) |

### 6.2 deleteType 옵션

| deleteType | 설명 |
|------------|------|
| `0` | 업로드한 마켓만 삭제 |
| `1` | 불사자 수집상품 관리에서만 삭제 |
| `2` | 마켓 및 불사자 수집상품 관리에서 모두 삭제 |
| `3` | 마켓과 연결 끊기 (마켓에선 유지, 불사자에서만 연결 해제) |

### 6.3 Response

```json
{
  "results": [
    {
      "id": "U01KEXGR5TJZM0HMVS1JJXZVRZ9",
      "code": 1,
      "status": "업로드 상품 삭제처리 완료",
      "marketResult": [
        {
          "type": "SMARTSTORE",
          "code": 1,
          "status": "[SMARTSTORE] 업로드 상품 삭제 완료",
          "productId": 12984262382,
          "result": {
            "message": "OK",
            "data": {
              "channelProductNo": 12984262382
            }
          }
        }
      ],
      "statusResult": {
        "status_0_count": 0,
        "status_4_count": 103834,
        "other_status_count": 292036,
        "total_count": 395870
      }
    }
  ]
}
```

### 6.4 Response 필드 설명

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | string | 불사자 상품 ID |
| `code` | number | 결과 코드 (1 = 성공) |
| `status` | string | 처리 상태 메시지 |
| `marketResult` | array | 마켓별 삭제 결과 |
| `marketResult[].type` | string | 마켓 타입 (SMARTSTORE 등) |
| `marketResult[].code` | number | 마켓별 결과 코드 (1 = 성공) |
| `marketResult[].productId` | number | 삭제된 마켓 상품번호 |
| `marketResult[].result` | object | 마켓 API 응답 |
| `statusResult` | object | 삭제 후 전체 상품 현황 통계 |

### 6.5 주의사항

1. **11번가**: 삭제 대신 판매중지 상태로 변경됨
2. **쿠팡**: 서버 특성상 여러 번 삭제 요청이 필요할 수 있음
3. **일시적 실패**: 마켓 API 문제로 삭제가 안 되는 현상 발생 가능

### 6.6 Python 예시

```python
def delete_products(sourcing_ids, delete_type=2):
    """
    상품 삭제

    Args:
        sourcing_ids: 삭제할 불사자 상품 ID 리스트
        delete_type: 삭제 유형 (0=마켓만, 1=불사자만, 2=모두, 3=연결끊기)
    """
    url = f"{BASE_URL}/market/delete/sourcingproducts"
    payload = {
        "data": {
            "sourcingIds": sourcing_ids,
            "deleteType": delete_type
        }
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    return response.json()

# 사용 예시 - 마켓 + 불사자 모두 삭제
result = delete_products(
    ["U01KEXGR5TJZM0HMVS1JJXZVRZ9", "U01ANOTHER_PRODUCT_ID"],
    delete_type=2
)

# 결과 확인
for item in result["results"]:
    print(f"{item['id']}: {item['status']} (code: {item['code']})")
```

---

## 7. SKU 구조

### 7.1 uploadSkus 배열

각 SKU 객체의 전체 필드:

```json
{
  "skuRef": "3768966850356",
  "_origin_price": 62,
  "origin_price": 13082,
  "sale_price": 58800,
  "main_product": false,
  "exclude": false,
  "id": "1",
  "text": "A. A형 직목 난로 엘보 굴뚝",
  "_text": "A款直脖柴炉+弯头+烟筒",
  "urlRef": "https://cdn.bulsaja.com/...",
  "stock": 200
}
```

| 필드 | 타입 | 수정 | 설명 |
|------|------|------|------|
| `skuRef` | string | **X** | SKU 참조 ID (타오바오 SKU ID) |
| `_origin_price` | number | **X** | **위안 원가 - 절대 수정 금지!** |
| `origin_price` | number | O | 원화 할인전 가격 |
| `sale_price` | number | O | 원화 할인후 가격 |
| `main_product` | boolean | O | 대표상품 여부 |
| `exclude` | boolean | **X** | **제외 여부 - 수정 시 옵션 구조 깨짐!** |
| `id` | string | **X** | 옵션 ID (vid와 매핑) |
| `text` | string | **X** | 한글 옵션명 (접두사 포함) |
| `_text` | string | **X** | 중국어 원본 옵션명 |
| `urlRef` | string | **X** | 옵션 이미지 URL |
| `stock` | number | **X** | 재고 수량 |

---

### 7.2 uploadSkuProps 구조

옵션 속성 정보 (mainOption.values[].vid = uploadSkus[].id 매핑):

```json
{
  "subOption": [],
  "mainOption": {
    "prop_name": "색상별로 정렬",
    "_prop_name": "颜色分类",
    "pid": 1,
    "values": [
      {
        "vid": 1,
        "_name": "A款直脖柴炉+弯头+烟筒",
        "name": "A. A형 직목 난로 엘보 굴뚝",
        "name_ko": "A형 직목 난로 엘보 굴뚝",
        "imageUrl": "https://...",
        "exclude": false,
        "origin_priceRef": 10603,
        "sale_priceRef": 10603,
        "_origin_priceRef": 51
      }
    ]
  }
}
```

---

### 7.3 original_skus 구조

원본 SKU 데이터 (수집 시점):

```json
{
  "skuRef": "3768966850356",
  "main_product": false,
  "exclude": false,
  "id": "1",
  "text": "A款直脖柴炉+弯头+烟筒",
  "text_ko": "A형 직목 난로 + 엘보 + 굴뚝",
  "origin_price": 62,
  "sale_price": 62,
  "urlRef": "https://img.alicdn.com/...",
  "stock": 200
}
```

> **참고**: original_skus의 가격은 위안(CNY) 단위입니다.

---

## 8. 가격 계산

### 8.1 가격 계산 공식

```
1단계: 원화 환산
    위안원가(_origin_price) × 환율(211) = 원화원가

2단계: 할인전 가격 (origin_price)
    (원화원가 + 추가마진) / (1 - 마진율/100) / (1 - 카드수수료/100)

3단계: 할인후 가격 (sale_price)
    origin_price × (1 - 할인율/100)

4단계: 올림 처리
    raise_digit 단위로 올림 (예: 100원 단위)
```

### 8.2 150% 가격 규칙

> **적용 대상**: 쿠팡 제외 모든 플랫폼 (스마트스토어, 지마켓, 옥션, 11번가)

| 항목 | 내용 |
|------|------|
| **기준** | origin_price (할인전 가격) |
| **허용 범위** | 대표옵션 가격의 50% ~ 150% |
| **위반 시** | 업로드 실패 또는 검수 탈락 |

---

## 9. 필드 수정 규칙

### 9.1 수정 가능 필드

```
- uploadCommonProductName (공통 상품명)
- uploadCoupangProductName (쿠팡 상품명)
- uploadSmartStoreProductName (스마트스토어 상품명)
- uploadThumbnails (썸네일 이미지)
- uploadDetailContents (상세페이지)
- uploadDetail_page (상세페이지 설정)
- uploadCommonTags (공통 태그)
- uploadSmartStoreTags (스마트스토어 태그)
- uploadCategory (카테고리)
- uploadContact (연락처 정보)
- uploadVideoUrls (비디오 URL)
- uploadSkus[].origin_price (원화 할인전)
- uploadSkus[].sale_price (원화 할인후)
- uploadSkus[].main_product (대표상품)
```

### 9.2 수정 금지 필드

```
- ID (상품 ID)
- uploadBulsajaCode (불사자 코드)
- uploadSkus[].skuRef (SKU 참조 ID)
- uploadSkus[]._origin_price (위안 원가) ⚠️ 절대 수정 금지
- uploadSkus[].exclude (제외 여부) ⚠️ 마켓 옵션 구조 매핑 깨짐
- uploadSkus[].id (옵션 ID)
- uploadSkus[].text (옵션명)
- uploadSkus[]._text (중국어 옵션명)
- uploadSkus[].urlRef (옵션 이미지)
- uploadSkus[].stock (재고)
- uploadSkuProps (옵션 속성 전체)
- original_sku_props (원본 옵션 속성)
- original_skus (원본 SKU)
```

---

### 9.3 main_product 설정 로직

```
1. 모든 SKU의 main_product = false로 초기화
2. 선택된 옵션들 중 sale_price가 가장 낮은 옵션 찾기
3. 해당 옵션의 main_product = true로 설정

⚠️ 대표상품은 반드시 1개만 존재해야 함
```

### 9.4 옵션 선택 로직

```
1. 미끼 키워드 필터: text 또는 _text에 미끼 키워드 포함 옵션 제외
2. 가격 범위 필터: _origin_price가 0 이하 제외, 설정된 범위 밖 제외
3. 가격 클러스터 분석: 저가 그룹(미끼) 탐지 및 제거
4. 정렬: 가격 낮은순(price_asc) 또는 높은순(price_desc)
5. 개수 제한: 설정된 옵션 개수만큼 선택
6. exclude 유지: exclude 필드는 기존 값 유지 (수정 안 함)
```

---

## 6. 이미지/번역 API

### 6.1 이미지 번역 (Photokit)

**엔드포인트**: `POST /sourcing/translate/photokit`

**용도**:
- 썸네일 이미지 텍스트 한글 번역
- 옵션 이미지 텍스트 한글 번역

> **Note**: 썸네일과 옵션 이미지 번역 모두 동일한 API 사용

**Request Body** (예상):
```json
{
  "productId": "U01KD7X9YZ7MD5A5H9S3Z87YWA4",
  "imageUrls": ["https://img.alicdn.com/..."],
  "targetLang": "ko"
}
```

> **Note**: 실제 페이로드 구조는 브라우저 네트워크 탭에서 확인 필요

---

## 7. 카테고리 API

### 7.1 카테고리 검색

**엔드포인트**: `POST /manage/category/bulsaja_category`

**Request Body**:
```json
{
  "keyword": "캠핑 장작 난로"
}
```

**Response**:
```json
{
  "success": true,
  "code": 0,
  "msg": "불사자 카테고리 검색에 성공했습니다.",
  "data": {
    "categoryMap": {
      "cp": [...],
      "ss": [...],
      "est": [...],
      "est_global": [...],
      "esm": [...]
    }
  }
}
```

#### 마켓별 카테고리 키

| 키 | 마켓 | 설명 |
|------|------|------|
| `ss` | 스마트스토어 | 네이버 스마트스토어 |
| `cp` | 쿠팡 | 쿠팡 |
| `esm` | 지마켓/옥션 | ESM 통합 |
| `est` | 11번가 | 11번가 국내 |
| `est_global` | 11번가 글로벌 | 11번가 해외직구 |

#### 카테고리 응답 구조

```json
{
  "id": "ss",
  "code": "50004779",
  "name": "생활/건강>주방용품>조리기구>조리도구세트",
  "needCert": false,
  "additional": {
    "addPrice": true
  }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | string | 마켓 식별자 |
| `code` | string | 카테고리 코드 |
| `name` | string | 카테고리 전체 경로 |
| `needCert` | boolean | 인증 필요 여부 |
| `additional` | object | 추가 설정 |

#### 쿠팡 카테고리 additional 필드

```json
{
  "addPrice": true,
  "requiredOptions": 1,
  "mandatoryOption": "수량",
  "mandatoryType": "NUMBER"
}
```

| 필드 | 설명 |
|------|------|
| `requiredOptions` | 필수 옵션 개수 |
| `mandatoryOption` | 필수 옵션명 |
| `mandatoryType` | 옵션 타입 (NUMBER 등) |

#### ESM 카테고리 additional 필드

```json
{
  "auction": "44090000",
  "gmarket": "300024394",
  "options": [{"name": "발송일", "code": 1021}],
  "addOption": true,
  "addPrice": true,
  "isBook": false,
  "goodsType": 5
}
```

| 필드 | 설명 |
|------|------|
| `auction` | 옥션 카테고리 코드 |
| `gmarket` | 지마켓 카테고리 코드 |
| `options` | 필수 옵션 목록 |
| `goodsType` | 상품 유형 |

---

## 카테고리 구조

### uploadCategory 객체

```json
{
  "ss_category": {
    "name": "스포츠/레저>캠핑>취사용품>버너",
    "code": "50002660",
    "search": "검색어",
    "categoryList": [...]
  },
  "cp_category": { ... },
  "esm_category": { ... },
  "est_category": { ... },
  "est_global_category": { ... }
}
```

| 키 | 마켓 |
|------|------|
| `ss_category` | 스마트스토어 |
| `cp_category` | 쿠팡 |
| `esm_category` | 지마켓/옥션 |
| `est_category` | 11번가 |
| `est_global_category` | 11번가 글로벌 |

---

## 업로드 성공 URL 구조

```json
{
  "uploadedSuccessUrl": {
    "coupang": null,
    "gmarket": null,
    "smartstore": "12987429099",
    "st11": null,
    "auction": null
  }
}
```

---

## 예시 코드

### Python - 상품 조회

```python
import requests

BASE_URL = "https://api.bulsaja.com/api"
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "accesstoken": "YOUR_ACCESS_TOKEN",
    "refreshtoken": "YOUR_REFRESH_TOKEN",
    "Origin": "https://www.bulsaja.com"
}

def get_product(product_id):
    url = f"{BASE_URL}/manage/sourcing-product/{product_id}"
    response = requests.get(url, headers=HEADERS)
    return response.json()

# 사용
product = get_product("U01KD7X9YZ7MD5A5H9S3Z87YWA4")
print(product["data"]["uploadCommonProductName"])
```

### Python - 상품 수정

```python
def update_product(product_id, data):
    url = f"{BASE_URL}/sourcing/uploadfields/{product_id}"
    response = requests.put(url, headers=HEADERS, json=data)
    return response.json()

# 가격 수정 예시
product_data = get_product("U01...")["data"]
for sku in product_data["uploadSkus"]:
    sku["sale_price"] = int(sku["sale_price"] * 1.1)  # 10% 인상

update_product("U01...", product_data)
```

### Python - 마켓 업로드

```python
def upload_to_market(market_id, product_id, target_market):
    url = f"{BASE_URL}/market/{market_id}/upload/"
    payload = {
        "productId": product_id,
        "notices": None,
        "preventDuplicateUpload": False,
        "removeDuplicateWords": True,
        "targetMarket": target_market
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    return response.json()

# 스마트스토어 업로드
result = upload_to_market(10400, "U01...", "SMARTSTORE")
```

---

## 에러 처리

### 토큰 만료
```json
{
  "name": "Expire Token",
  "message": "인증 토큰이 만료되었습니다. 재로그인 해주십시오.",
  "invisibleMsg": "",
  "errorJson": {}
}
```

토큰 만료 시 다시 로그인하여 새 토큰을 발급받아야 합니다.

---

## 주의사항

1. **_origin_price 절대 수정 금지**: 이 값은 가격 계산의 기준값으로 수정 시 모든 가격 체계가 깨집니다.

2. **exclude 필드 수정 금지**: 마켓과 SKU 간의 옵션 매핑 구조가 깨져 업로드 실패 및 판매 중 상품에 문제가 발생합니다.

3. **150% 규칙 준수**: 스마트스토어 등에서 옵션 가격이 대표 옵션의 50~150% 범위를 벗어나면 검수 탈락됩니다.

4. **대표상품 1개 필수**: main_product가 true인 SKU는 반드시 1개만 있어야 합니다.

5. **환율 확인**: uploadRecentExchangeRate 값을 확인하여 현재 적용된 환율을 파악하세요.

---

*이 문서는 실제 API 응답을 기반으로 작성되었습니다.*
