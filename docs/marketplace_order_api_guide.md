# 한국 주요 마켓플레이스 주문관리 API 종합 가이드

> **작성일**: 2026-01-22  
> **목적**: 스마트스토어, 11번가, 쿠팡, ESM의 **전체 주문관리 API** 정리  
> **범위**: 주문조회, 발송처리, 반품, 교환, 취소, CS 처리

---

## 목차

1. [네이버 스마트스토어 (Commerce API)](#1-네이버-스마트스토어-commerce-api)
2. [쿠팡 (Wing API)](#2-쿠팡-wing-api)
3. [11번가 (Seller API)](#3-11번가-seller-api)
4. [ESM 2.0 (Gmarket/Auction)](#4-esm-20-gmarketauction)
5. [공통 구현 가이드](#5-공통-구현-가이드)

---

# 1. 네이버 스마트스토어 (Commerce API)

## 1.1 API 기본 정보

| 항목          | 내용                                 |
| ------------- | ------------------------------------ |
| **공식 문서** | https://apicenter.commerce.naver.com |
| **Base URL**  | `https://api.commerce.naver.com`     |
| **인증 방식** | OAuth 2.0 (Client Credentials)       |
| **API 버전**  | v2.71.0 (2026-01-20)                 |

## 1.2 인증 (OAuth 2.0)

```http
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

client_id={APPLICATION_ID}
&client_secret={APPLICATION_SECRET}
&grant_type=client_credentials
```

```json
// Response
{
  "access_token": "AAA...YYY",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

---

## 1.3 주문 조회 API

### 1.3.1 변경된 주문 목록 조회

```http
GET /external/v1/pays/orders/seller/changed/{statusType}
Authorization: Bearer {access_token}
```

| 파라미터      | 타입  | 필수 | 설명                     |
| ------------- | ----- | ---- | ------------------------ |
| `statusType`  | Path  | O    | 주문상태                 |
| `changedFrom` | Query | O    | 조회 시작일시 (ISO 8601) |
| `changedTo`   | Query | O    | 조회 종료일시            |
| `pageStart`   | Query | X    | 페이지 시작 (기본 0)     |
| `pageSize`    | Query | X    | 페이지 크기 (최대 300)   |

**statusType 전체 목록**:
| 코드 | 설명 | 용도 |
|------|------|------|
| `PAY_COMPLETED` | 결제완료 | 신규주문 수집 |
| `PACKING` | 상품준비중 | 발송대기 |
| `SHIPPING` | 배송중 | 배송추적 |
| `DELIVERED` | 배송완료 | 구매확정 대기 |
| `PURCHASE_CONFIRMED` | 구매확정 | 정산대상 |
| `CANCELED` | 취소완료 | 취소처리 완료 |
| `CANCEL_REQUESTED` | 취소요청 | 취소승인 대기 |
| `RETURN_REQUESTED` | 반품요청 | 반품처리 대기 |
| `RETURN_COMPLETED` | 반품완료 | 반품처리 완료 |
| `EXCHANGE_REQUESTED` | 교환요청 | 교환처리 대기 |
| `EXCHANGE_COMPLETED` | 교환완료 | 교환처리 완료 |
| `HOLD` | 발송보류 | CS 처리 중 |

### 1.3.2 주문 상세 조회

```http
GET /external/v1/pays/orders/{orderId}
Authorization: Bearer {access_token}
```

### 1.3.3 상품주문 상세 조회

```http
GET /external/v1/pay-orders/{productOrderId}
Authorization: Bearer {access_token}
```

### 1.3.4 주문 응답 필드 상세 (전체 수집 가능 정보)

#### 📦 주문 기본 정보

| 필드명                          | 타입     | 설명                                    |
| ------------------------------- | -------- | --------------------------------------- |
| `orderId`                       | String   | 주문번호                                |
| `orderDate`                     | DateTime | 주문일시                                |
| `paymentDate`                   | DateTime | 결제일시                                |
| `orderStatus`                   | String   | 주문상태                                |
| `payLocationType`               | String   | 결제위치 (PC/MOBILE)                    |
| `paymentMethod`                 | String   | 결제수단 (CARD/BANK/VIRTUAL_ACCOUNT 등) |
| `isDeliveryMemoParticularInput` | Boolean  | 배송메모 특이사항 여부                  |

#### 💰 금액 정보 (가격/수수료/정산)

| 필드명                     | 타입    | 설명                    |
| -------------------------- | ------- | ----------------------- |
| `totalPaymentAmount`       | Integer | 총 결제금액             |
| `productOrderAmount`       | Integer | 상품주문금액            |
| `deliveryFee`              | Integer | 배송비                  |
| `productDiscountAmount`    | Integer | 상품할인금액            |
| `sellerDiscountAmount`     | Integer | 셀러쿠폰 할인금액       |
| `platformDiscountAmount`   | Integer | 네이버쿠폰 할인금액     |
| `pointUsageAmount`         | Integer | 포인트 사용금액         |
| `giftCardUsageAmount`      | Integer | 상품권 사용금액         |
| `commissionRate`           | Float   | 수수료율 (%)            |
| `commissionAmount`         | Integer | **수수료 금액**         |
| `expectedSettlementAmount` | Integer | **예상 정산금액**       |
| `actualSettlementAmount`   | Integer | **실제 정산금액**       |
| `settlementDate`           | Date    | 정산예정일              |
| `refundAmount`             | Integer | 환불금액 (취소/반품 시) |

#### 👤 주문자 정보 (Orderer)

| 필드명                | 타입    | 설명                   |
| --------------------- | ------- | ---------------------- |
| `orderer.name`        | String  | 주문자 이름            |
| `orderer.tel`         | String  | 주문자 연락처          |
| `orderer.email`       | String  | 주문자 이메일          |
| `orderer.memberId`    | String  | 네이버 회원ID (마스킹) |
| `orderer.isNonMember` | Boolean | 비회원 여부            |

#### 📍 수령자 정보 (Receiver/ShippingAddress)

| 필드명                          | 타입    | 설명                  |
| ------------------------------- | ------- | --------------------- |
| `shippingAddress.name`          | String  | 수령인 이름           |
| `shippingAddress.tel1`          | String  | 수령인 연락처1        |
| `shippingAddress.tel2`          | String  | 수령인 연락처2 (예비) |
| `shippingAddress.zipCode`       | String  | 우편번호              |
| `shippingAddress.baseAddress`   | String  | 기본 주소             |
| `shippingAddress.detailAddress` | String  | 상세 주소             |
| `shippingAddress.roadNameYn`    | Boolean | 도로명주소 여부       |
| `shippingMemo`                  | String  | 배송 메모             |
| `deliveryMemo`                  | String  | 배송 요청사항         |

#### 📦 상품 정보 (ProductOrderInfo)

| 필드명                 | 타입    | 설명                           |
| ---------------------- | ------- | ------------------------------ |
| `productOrderId`       | String  | 상품주문번호                   |
| `productId`            | String  | 상품번호                       |
| `productName`          | String  | 상품명                         |
| `sellerProductCode`    | String  | **판매자 관리코드**            |
| `optionCode`           | String  | 옵션코드                       |
| `optionPrice`          | Integer | 옵션 추가금액                  |
| `quantity`             | Integer | 주문수량                       |
| `unitPrice`            | Integer | 상품 단가                      |
| `totalProductAmount`   | Integer | 상품 총액                      |
| `mallProductId`        | String  | 원본몰 상품ID                  |
| `productClass`         | String  | 상품유형 (GENERAL/COMBINATION) |
| `productOption`        | String  | 옵션정보 텍스트                |
| `optionManagementCode` | String  | **옵션 관리코드**              |
| `thumbnailImageUrl`    | String  | 상품 썸네일 URL                |

#### 🚚 배송 정보

| 필드명                 | 타입     | 설명                                       |
| ---------------------- | -------- | ------------------------------------------ |
| `deliveryMethod`       | String   | 배송방법 (DELIVERY/QUICK/VISIT)            |
| `deliveryCompanyCode`  | String   | 택배사 코드                                |
| `deliveryCompanyName`  | String   | 택배사명                                   |
| `trackingNumber`       | String   | 송장번호                                   |
| `shippingDate`         | DateTime | 발송일시                                   |
| `deliveredDate`        | DateTime | 배송완료일시                               |
| `deliveryFeePayMethod` | String   | 배송비 결제방법 (PREPAID/CASH_ON_DELIVERY) |
| `deliveryPolicyType`   | String   | 배송비 정책 (FREE/CONDITIONAL_FREE/PAID)   |
| `claimDeliveryFee`     | Integer  | 클레임 배송비                              |

#### 📊 정산 관련 추가 정보

| 필드명                                            | 타입     | 설명                                |
| ------------------------------------------------- | -------- | ----------------------------------- |
| `channelCommissionRate`                           | Float    | 채널 수수료율                       |
| `knowledgeShoppingSellingInterlockCommissionRate` | Float    | 지식쇼핑 연동 수수료율              |
| `inflowPath`                                      | String   | 유입경로 (NAVER_SHOPPING/DIRECT 등) |
| `inflowPathDetails`                               | String   | 유입경로 상세                       |
| `purchaseConfirmDate`                             | DateTime | 구매확정일시                        |
| `claimType`                                       | String   | 클레임 유형                         |
| `claimStatus`                                     | String   | 클레임 상태                         |

---

## 1.4 발송 처리 API

### 1.4.1 발송 처리 (단건/다건)

```http
POST /external/v1/pay-orders/ship
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001", "2024012212345678002"],
  "deliveryCompanyCode": "CJGLS",
  "trackingNumber": "123456789012"
}
```

### 1.4.2 발송 정보 수정

```http
PUT /external/v1/pay-orders/{productOrderId}/dispatch
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "deliveryCompanyCode": "HANJIN",
  "trackingNumber": "987654321098"
}
```

### 1.4.3 발송 보류 설정

```http
PUT /external/v1/pay-orders/hold
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001"],
  "reason": "재고 부족으로 입고 대기 중"
}
```

### 1.4.4 발송 보류 해제

```http
PUT /external/v1/pay-orders/release-hold
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001"]
}
```

**택배사 코드**:
| 코드 | 택배사명 |
|------|----------|
| `CJGLS` | CJ대한통운 |
| `HANJIN` | 한진택배 |
| `LOTTE` | 롯데택배 |
| `EPOST` | 우체국 |
| `KDEXP` | 경동택배 |
| `LOGEN` | 로젠택배 |
| `GTX` | GS25편의점택배 |
| `CUPOST` | CU편의점택배 |
| `DAESIN` | 대신택배 |
| `ILYANG` | 일양로지스 |
| `CHUNIL` | 천일택배 |
| `HDEXP` | 합동택배 |

---

## 1.5 취소 처리 API

### 1.5.1 취소 요청 목록 조회

```http
GET /external/v1/pay-orders/seller/cancel/requested
Authorization: Bearer {access_token}

# Query Parameters
changedFrom={시작일시}
changedTo={종료일시}
```

### 1.5.2 취소 요청 승인

```http
POST /external/v1/pay-orders/cancel/approve
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001"],
  "cancelReason": "고객 요청에 의한 취소 승인"
}
```

### 1.5.3 취소 요청 거부

```http
POST /external/v1/pay-orders/cancel/reject
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001"],
  "rejectReason": "이미 발송 완료된 상품입니다"
}
```

### 1.5.4 판매자 직접 취소 (발송 전)

```http
POST /external/v1/pay-orders/cancel
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001"],
  "cancelReason": "재고 소진",
  "cancelReasonCode": "SOLD_OUT"
}
```

**취소사유 코드 (cancelReasonCode)**:
| 코드 | 설명 |
|------|------|
| `SOLD_OUT` | 재고 소진 |
| `INTENT_CHANGED` | 고객 변심 |
| `WRONG_ORDER` | 주문 착오 |
| `DELIVERY_DELAY` | 배송 지연 |
| `SERVICE_UNSATISFIED` | 서비스 불만족 |

---

## 1.6 반품 처리 API

### 1.6.1 반품 요청 목록 조회

```http
GET /external/v1/pay-orders/seller/return/requested
Authorization: Bearer {access_token}

changedFrom={시작일시}&changedTo={종료일시}
```

### 1.6.2 반품 요청 승인

```http
POST /external/v1/pay-orders/return/approve
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001"],
  "returnReason": "반품 승인 처리"
}
```

### 1.6.3 반품 요청 거부

```http
POST /external/v1/pay-orders/return/reject
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001"],
  "rejectReason": "사용 흔적이 있어 반품 불가"
}
```

### 1.6.4 반품 수거 완료 처리

```http
POST /external/v1/pay-orders/return/collect
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001"]
}
```

### 1.6.5 반품 완료 처리 (환불)

```http
POST /external/v1/pay-orders/return/complete
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001"]
}
```

### 1.6.6 반품 배송비 청구

```http
POST /external/v1/pay-orders/return/withhold
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001"],
  "returnShippingCharge": 5000,
  "claimType": "BUYER_FAULT"
}
```

### 1.6.7 반품 사유 변경 (귀책 변경)

```http
POST /external/v1/pay-orders/return/change-claim-reason
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001"],
  "claimReasonType": "SELLER_FAULT",
  "claimReasonDetail": "상품 불량으로 판매자 귀책 변경",
  "collectDeliveryCompanyCode": "CJGLS",
  "collectTrackingNumber": "123456789012"
}
```

**귀책 유형 (claimReasonType)**:
| 코드 | 설명 | 배송비 부담 |
|------|------|------------|
| `BUYER_FAULT` | 구매자 귀책 (단순변심 등) | 구매자 |
| `SELLER_FAULT` | 판매자 귀책 (불량, 오배송 등) | 판매자 |
| `DELIVERY_FAULT` | 배송 중 파손 | 택배사/판매자 |

**사용 시나리오**:

- 고객이 "단순변심"으로 반품 신청했으나, 상품 확인 결과 불량이 확인된 경우
- 귀책을 변경하여 배송비 부담 주체를 조정

---

## 1.7 교환 처리 API

### 1.7.1 교환 요청 목록 조회

```http
GET /external/v1/pay-orders/seller/exchange/requested
Authorization: Bearer {access_token}

changedFrom={시작일시}&changedTo={종료일시}
```

### 1.7.2 교환 요청 승인

```http
POST /external/v1/pay-orders/exchange/approve
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001"]
}
```

### 1.7.3 교환 요청 거부

```http
POST /external/v1/pay-orders/exchange/reject
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001"],
  "rejectReason": "교환 불가 상품입니다"
}
```

### 1.7.4 교환 상품 발송

```http
POST /external/v1/pay-orders/exchange/ship
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "productOrderIds": ["2024012212345678001"],
  "deliveryCompanyCode": "CJGLS",
  "trackingNumber": "123456789012"
}
```

---

## 1.8 클레임 조회 API

### 1.8.1 취소/반품/교환 사유 조회

```http
GET /external/v1/pay-orders/{productOrderId}/claim
Authorization: Bearer {access_token}
```

**응답 예시**:

```json
{
  "claimType": "RETURN",
  "claimStatus": "RETURN_REQUESTED",
  "claimReason": "상품 불량",
  "claimReasonDetail": "포장 파손으로 인한 제품 손상",
  "requestDate": "2024-01-25T10:30:00+09:00",
  "returnShippingCharge": 2500,
  "returnShippingPayMet": "PREPAID"
}
```

---

# 2. 쿠팡 (Wing API)

## 2.1 API 기본 정보

| 항목          | 내용                                              |
| ------------- | ------------------------------------------------- |
| **공식 문서** | https://developers.coupangcorp.com                |
| **Base URL**  | `https://api.coupang.com/v2/providers/seller-api` |
| **인증 방식** | HMAC-SHA256 Signature                             |

## 2.2 HMAC 인증 생성

```python
import hmac
import hashlib
import datetime

def generate_hmac_signature(method, uri, secret_key, access_key):
    datetime_str = datetime.datetime.utcnow().strftime('%y%m%dT%H%M%SZ')
    message = f"{datetime_str}{method}{uri}"
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return {
        "Authorization": f"CEA algorithm=HmacSHA256, access-key={access_key}, "
                        f"signed-date={datetime_str}, signature={signature}",
        "Content-Type": "application/json;charset=UTF-8"
    }
```

---

## 2.3 주문 조회 API

### 2.3.1 주문 목록 조회

```http
GET /apis/api/v1/orders
Authorization: {HMAC Signature}

vendorId={판매자ID}
status={주문상태}
createdAtFrom={시작 Unix timestamp ms}
createdAtTo={종료 Unix timestamp ms}
maxPerPage=50
nextToken={페이지네이션 토큰}
```

**status 값**:
| 상태 | 설명 | 용도 |
|------|------|------|
| `ACCEPT` | 결제완료/발주확인대기 | 신규주문 |
| `INSTRUCT` | 상품준비중 | 발송대기 |
| `DEPARTURE` | 배송지시 | 발송처리됨 |
| `DELIVERING` | 배송중 | 배송추적 |
| `FINAL_DELIVERY` | 배송완료 | 완료 |
| `NONE_TRACKING` | 송장미입력 | 발송필요 |
| `CANCEL` | 취소 | 취소완료 |
| `RETURN` | 반품 | CS |

### 2.3.2 주문 상세 조회

```http
GET /apis/api/v1/orders/{orderId}
Authorization: {HMAC Signature}
```

### 2.3.3 반품/교환 목록 조회

```http
GET /apis/api/v1/return-exchange-requests
Authorization: {HMAC Signature}

vendorId={판매자ID}
status={RECEIPT|PROGRESS|COMPLETE}
createdAtFrom={시작일}
createdAtTo={종료일}
```

### 2.3.4 주문 응답 필드 상세 (전체 수집 가능 정보)

#### 📦 주문 기본 정보

| 필드명                   | 타입     | 설명          |
| ------------------------ | -------- | ------------- |
| `orderId`                | Long     | 주문번호      |
| `orderAt`                | DateTime | 주문일시      |
| `paidAt`                 | DateTime | 결제일시      |
| `status`                 | String   | 주문상태      |
| `orderedAt`              | DateTime | 발주확인일시  |
| `shipmentBoxId`          | Long     | 배송박스 ID   |
| `remoteAreaDeliveryType` | String   | 도서산간 유형 |

#### 💰 금액 정보 (가격/수수료/정산)

| 필드명                  | 타입    | 설명              |
| ----------------------- | ------- | ----------------- |
| `orderPrice`            | Integer | 주문금액          |
| `salePrice`             | Integer | 판매가            |
| `discountPrice`         | Integer | 할인금액          |
| `couponDiscount`        | Integer | 쿠폰할인          |
| `coupangDiscount`       | Integer | 쿠팡할인 부담금   |
| `shippingPrice`         | Integer | 배송비            |
| `cancelPrice`           | Integer | 취소금액          |
| `sellerProductPrice`    | Integer | 판매자 공급가     |
| `sellerCommissionPrice` | Integer | **판매 수수료**   |
| `settlementPrice`       | Integer | **정산 예정금액** |
| `commissionRate`        | Float   | 수수료율 (%)      |
| `refundPrice`           | Integer | 환불금액          |
| `extraFee`              | Integer | 추가비용          |

#### 👤 주문자 정보 (Orderer)

| 필드명                  | 타입   | 설명          |
| ----------------------- | ------ | ------------- |
| `orderer.name`          | String | 주문자 이름   |
| `orderer.email`         | String | 주문자 이메일 |
| `orderer.ordererNumber` | String | 주문자 연락처 |
| `orderer.safeNumber`    | String | 안심번호      |

#### 📍 수령자 정보 (Receiver)

| 필드명                | 타입   | 설명             |
| --------------------- | ------ | ---------------- |
| `receiver.name`       | String | 수령인 이름      |
| `receiver.phone`      | String | 수령인 연락처    |
| `receiver.safeNumber` | String | 안심번호         |
| `receiver.postCode`   | String | 우편번호         |
| `receiver.addr1`      | String | 기본 주소        |
| `receiver.addr2`      | String | 상세 주소        |
| `receiverMessage`     | String | 배송 메시지      |
| `parcelPrintMessage`  | String | 송장 출력 메시지 |

#### 📦 상품 정보 (OrderItem)

| 필드명                  | 타입    | 설명               |
| ----------------------- | ------- | ------------------ |
| `vendorItemId`          | Long    | 옵션ID (쿠팡)      |
| `vendorItemPackageId`   | Long    | 패키지ID           |
| `vendorItemPackageName` | String  | 패키지명           |
| `vendorItemName`        | String  | 상품옵션명         |
| `productId`             | Long    | 상품ID             |
| `quantity`              | Integer | 주문수량           |
| `externalVendorSkuCode` | String  | **판매자 SKU코드** |
| `sellerProductId`       | Long    | 판매자 상품ID      |
| `sellerProductName`     | String  | 판매자 상품명      |
| `sellerProductItemName` | String  | 판매자 옵션명      |

#### 🚚 배송 정보

| 필드명                  | 타입     | 설명             |
| ----------------------- | -------- | ---------------- |
| `deliveryCompanyCode`   | String   | 택배사 코드      |
| `invoiceNumber`         | String   | 송장번호         |
| `shippedAt`             | DateTime | 발송일시         |
| `deliveredAt`           | DateTime | 배송완료일시     |
| `deliveryDate`          | Date     | 배송예정일       |
| `estimatedDeliveryDate` | Date     | 고객 희망 배송일 |
| `splitShipping`         | Boolean  | 분할배송 여부    |

---

## 2.4 발송 처리 API

### 2.4.1 발송 처리 (송장 입력)

```http
PUT /apis/api/v1/orders/{orderId}/shipments
Authorization: {HMAC Signature}
Content-Type: application/json

{
  "vendorId": "A00012345",
  "orderShipments": [
    {
      "orderId": 123456789,
      "vendorItemId": 123456,
      "splitShipping": false,
      "invoiceNumber": "123456789012",
      "deliveryCompanyCode": "CJGLS",
      "estimatedShippingDate": "2024-01-23"
    }
  ]
}
```

### 2.4.2 송장 수정

```http
PUT /apis/api/v1/orders/{orderId}/shipments/{shipmentBoxId}
Authorization: {HMAC Signature}

{
  "invoiceNumber": "987654321098",
  "deliveryCompanyCode": "HANJIN"
}
```

### 2.4.3 분할 발송

```http
PUT /apis/api/v1/orders/{orderId}/shipments
Content-Type: application/json

{
  "vendorId": "A00012345",
  "orderShipments": [
    {
      "orderId": 123456789,
      "vendorItemId": 123456,
      "splitShipping": true,
      "splitQuantity": 5,
      "invoiceNumber": "111111111111",
      "deliveryCompanyCode": "CJGLS"
    },
    {
      "orderId": 123456789,
      "vendorItemId": 123456,
      "splitShipping": true,
      "splitQuantity": 5,
      "invoiceNumber": "222222222222",
      "deliveryCompanyCode": "HANJIN"
    }
  ]
}
```

**쿠팡 택배사 코드**:
| 코드 | 택배사 |
|------|--------|
| `CJGLS` | CJ대한통운 |
| `KGB` | 로젠택배 |
| `EPOST` | 우체국택배 |
| `HANJIN` | 한진택배 |
| `HYUNDAI` | 현대택배 |
| `LOTTE` | 롯데택배 |
| `KDEXP` | 경동택배 |
| `DAESIN` | 대신택배 |

---

## 2.5 취소 처리 API

### 2.5.1 취소 요청 승인

```http
PATCH /apis/api/v1/orders/{orderId}/cancel/approve
Authorization: {HMAC Signature}

{
  "vendorId": "A00012345",
  "receiptId": 123456
}
```

### 2.5.2 취소 요청 거부

```http
PATCH /apis/api/v1/orders/{orderId}/cancel/reject
Authorization: {HMAC Signature}

{
  "vendorId": "A00012345",
  "receiptId": 123456,
  "rejectReason": "이미 발송 완료"
}
```

### 2.5.3 판매자 직접 취소

```http
PATCH /apis/api/v1/orders/{orderId}/cancel
Authorization: {HMAC Signature}

{
  "vendorId": "A00012345",
  "vendorItemId": 123456,
  "cancelCount": 1,
  "cancelReason": "재고 소진"
}
```

---

## 2.6 반품 처리 API

### 2.6.1 반품 요청 조회

```http
GET /apis/api/v1/return-requests
Authorization: {HMAC Signature}

vendorId={판매자ID}
status={RECEIPT|PROGRESS|COMPLETE}
```

### 2.6.2 반품 요청 승인

```http
PATCH /apis/api/v1/return-requests/{receiptId}/approve
Authorization: {HMAC Signature}

{
  "vendorId": "A00012345"
}
```

### 2.6.3 반품 요청 거부

```http
PATCH /apis/api/v1/return-requests/{receiptId}/reject
Authorization: {HMAC Signature}

{
  "vendorId": "A00012345",
  "rejectReason": "반품 불가 상품"
}
```

### 2.6.4 반품 수거 완료

```http
PATCH /apis/api/v1/return-requests/{receiptId}/confirm-retrieve
Authorization: {HMAC Signature}

{
  "vendorId": "A00012345"
}
```

---

## 2.7 교환 처리 API

### 2.7.1 교환 요청 조회

```http
GET /apis/api/v1/exchange-requests
Authorization: {HMAC Signature}

vendorId={판매자ID}
status={RECEIPT|PROGRESS|COMPLETE}
```

### 2.7.2 교환 요청 승인

```http
PATCH /apis/api/v1/exchange-requests/{receiptId}/approve
Authorization: {HMAC Signature}

{
  "vendorId": "A00012345"
}
```

### 2.7.3 교환 상품 발송

```http
PUT /apis/api/v1/exchange-requests/{receiptId}/dispatch
Authorization: {HMAC Signature}

{
  "vendorId": "A00012345",
  "invoiceNumber": "123456789012",
  "deliveryCompanyCode": "CJGLS"
}
```

---

# 3. 11번가 (Seller API)

## 3.1 API 기본 정보

| 항목          | 내용                                     |
| ------------- | ---------------------------------------- |
| **공식 문서** | https://openapi.11st.co.kr               |
| **Base URL**  | `https://api.11st.co.kr/rest/sellershop` |
| **인증 방식** | API Key (Header)                         |

## 3.2 인증

```http
openapikey: {API_KEY}
Content-Type: application/json
```

---

## 3.3 주문 조회 API

### 3.3.1 주문 목록 조회

```http
GET /rest/sellershop/orders
openapikey: {API_KEY}

ordStrtDt={YYYYMMDD}
ordEndDt={YYYYMMDD}
ordStCd={주문상태코드}
page=1&pageSize=100
```

**주문상태코드 (ordStCd)**:
| 코드 | 상태 | 설명 |
|------|------|------|
| `102` | 결제완료 | 신규주문 |
| `201` | 상품준비중 | 발송대기 |
| `202` | 배송대기 | 발송대기 |
| `301` | 배송중 | 배송처리 |
| `302` | 배송완료 | 완료 |
| `401` | 구매확정 | 정산대상 |
| `501` | 취소요청 | CS |
| `502` | 취소완료 | CS완료 |
| `601` | 반품요청 | CS |
| `602` | 반품진행 | CS진행 |
| `603` | 반품완료 | CS완료 |
| `701` | 교환요청 | CS |
| `702` | 교환진행 | CS진행 |
| `703` | 교환완료 | CS완료 |

### 3.3.2 주문 상세 조회

```http
GET /rest/sellershop/orders/{ordNo}
openapikey: {API_KEY}
```

### 3.3.3 클레임 목록 조회

```http
GET /rest/sellershop/claims
openapikey: {API_KEY}

clmStrtDt={YYYYMMDD}
clmEndDt={YYYYMMDD}
clmTpCd={CLM01|CLM02|CLM03}
```

| clmTpCd | 설명 |
| ------- | ---- |
| `CLM01` | 취소 |
| `CLM02` | 반품 |
| `CLM03` | 교환 |

### 3.3.4 주문 응답 필드 상세 (전체 수집 가능 정보)

#### 📦 주문 기본 정보

| 필드명       | 타입     | 설명                 |
| ------------ | -------- | -------------------- |
| `ordNo`      | String   | 주문번호             |
| `ordDt`      | DateTime | 주문일시             |
| `payDt`      | DateTime | 결제일시             |
| `ordStCd`    | String   | 주문상태코드         |
| `ordStNm`    | String   | 주문상태명           |
| `ordMediaCd` | String   | 주문채널 (PC/MOBILE) |
| `memNo`      | String   | 회원번호             |

#### 💰 금액 정보 (가격/수수료/정산)

| 필드명           | 타입    | 설명              |
| ---------------- | ------- | ----------------- |
| `totOrdAmt`      | Integer | 총 주문금액       |
| `prdPrc`         | Integer | 상품가격          |
| `dlvCst`         | Integer | 배송비            |
| `totDscntAmt`    | Integer | 총 할인금액       |
| `cpnDscntAmt`    | Integer | 쿠폰 할인금액     |
| `pntUseAmt`      | Integer | 포인트 사용금액   |
| `slrCpnDscntAmt` | Integer | 셀러쿠폰 할인     |
| `cardDscntAmt`   | Integer | 카드할인          |
| `selFee`         | Integer | **판매 수수료**   |
| `selFeeRate`     | Float   | **수수료율 (%)**  |
| `stlAmt`         | Integer | **정산 예정금액** |
| `rfndAmt`        | Integer | 환불금액          |
| `addDlvCst`      | Integer | 추가 배송비       |

#### 👤 주문자 정보

| 필드명     | 타입   | 설명            |
| ---------- | ------ | --------------- |
| `ordNm`    | String | 주문자 이름     |
| `ordTelNo` | String | 주문자 전화번호 |
| `ordHpNo`  | String | 주문자 휴대폰   |
| `ordEmail` | String | 주문자 이메일   |

#### 📍 수령자 정보

| 필드명        | 타입   | 설명                |
| ------------- | ------ | ------------------- |
| `rcvrNm`      | String | 수령인 이름         |
| `rcvrTelNo`   | String | 수령인 전화번호     |
| `rcvrHpNo`    | String | 수령인 휴대폰       |
| `rcvrZpcd`    | String | 우편번호 (5자리)    |
| `rcvrZpcdOld` | String | 구 우편번호 (6자리) |
| `rcvrAddr`    | String | 기본주소            |
| `rcvrAddrDtl` | String | 상세주소            |
| `dlvMsg`      | String | 배송 메시지         |
| `entrncPwd`   | String | 공동현관 비밀번호   |

#### 📦 상품 정보 (prdOrds)

| 필드명        | 타입    | 설명                |
| ------------- | ------- | ------------------- |
| `prdNo`       | String  | 상품번호            |
| `prdNm`       | String  | 상품명              |
| `optNo`       | String  | 옵션번호            |
| `optNm`       | String  | 옵션명              |
| `ordQty`      | Integer | 주문수량            |
| `sellerPrdCd` | String  | **판매자 상품코드** |
| `sellerOptCd` | String  | **판매자 옵션코드** |
| `prdPrc`      | Integer | 상품가격            |
| `optPrc`      | Integer | 옵션추가금액        |

#### 🚚 배송 정보

| 필드명            | 타입     | 설명            |
| ----------------- | -------- | --------------- |
| `dlvMthdCd`       | String   | 배송방법코드    |
| `dlvCoCd`         | String   | 택배사 코드     |
| `dlvCoNm`         | String   | 택배사명        |
| `trkNo`           | String   | 송장번호        |
| `sndDt`           | DateTime | 발송일시        |
| `dlvCmplDt`       | DateTime | 배송완료일시    |
| `dlvCstPayMthdCd` | String   | 배송비 결제방법 |

---

## 3.4 발송 처리 API

### 3.4.1 배송 정보 등록 (발송처리)

```http
PUT /rest/sellershop/orders/{ordNo}/delivery
openapikey: {API_KEY}
Content-Type: application/json

{
  "dlvMthdCd": "01",
  "dlvCoCd": "04",
  "trkNo": "123456789012"
}
```

### 3.4.2 배송 정보 수정

```http
PUT /rest/sellershop/orders/{ordNo}/delivery/modify
openapikey: {API_KEY}
Content-Type: application/json

{
  "dlvCoCd": "05",
  "trkNo": "987654321098"
}
```

**11번가 택배사 코드 (dlvCoCd)**:
| 코드 | 택배사 |
|------|--------|
| `01` | 우체국 |
| `04` | CJ대한통운 |
| `05` | 한진택배 |
| `06` | 롯데택배 |
| `08` | 로젠택배 |
| `16` | 경동택배 |
| `22` | 대신택배 |
| `46` | GS편의점택배 |

**배송방법 코드 (dlvMthdCd)**:
| 코드 | 설명 |
|------|------|
| `01` | 택배 |
| `02` | 직접배송 |
| `03` | 퀵서비스 |
| `04` | 방문수령 |

---

## 3.5 취소 처리 API

### 3.5.1 취소 요청 승인

```http
PUT /rest/sellershop/claims/{clmNo}/cancel/approve
openapikey: {API_KEY}
```

### 3.5.2 취소 요청 거부

```http
PUT /rest/sellershop/claims/{clmNo}/cancel/reject
openapikey: {API_KEY}
Content-Type: application/json

{
  "rjtRsnCd": "01",
  "rjtRsnDtl": "이미 발송 완료된 상품입니다"
}
```

**거부사유 코드 (rjtRsnCd)**:
| 코드 | 설명 |
|------|------|
| `01` | 이미 발송 완료 |
| `02` | 주문제작 상품 |
| `03` | 기타 |

---

## 3.6 반품 처리 API

### 3.6.1 반품 요청 승인

```http
PUT /rest/sellershop/claims/{clmNo}/return/approve
openapikey: {API_KEY}
Content-Type: application/json

{
  "aprvRsnDtl": "반품 승인합니다"
}
```

### 3.6.2 반품 요청 거부

```http
PUT /rest/sellershop/claims/{clmNo}/return/reject
openapikey: {API_KEY}
Content-Type: application/json

{
  "rjtRsnCd": "01",
  "rjtRsnDtl": "사용 흔적이 있어 반품 불가합니다"
}
```

### 3.6.3 반품 수거 완료

```http
PUT /rest/sellershop/claims/{clmNo}/return/collect
openapikey: {API_KEY}
```

### 3.6.4 반품 완료 (환불 확정)

```http
PUT /rest/sellershop/claims/{clmNo}/return/complete
openapikey: {API_KEY}
```

---

## 3.7 교환 처리 API

### 3.7.1 교환 요청 승인

```http
PUT /rest/sellershop/claims/{clmNo}/exchange/approve
openapikey: {API_KEY}
```

### 3.7.2 교환 요청 거부

```http
PUT /rest/sellershop/claims/{clmNo}/exchange/reject
openapikey: {API_KEY}
Content-Type: application/json

{
  "rjtRsnCd": "01",
  "rjtRsnDtl": "교환 불가 상품입니다"
}
```

### 3.7.3 교환 상품 발송

```http
PUT /rest/sellershop/claims/{clmNo}/exchange/delivery
openapikey: {API_KEY}
Content-Type: application/json

{
  "dlvCoCd": "04",
  "trkNo": "123456789012"
}
```

---

# 4. ESM 2.0 (Gmarket/Auction)

## 4.1 API 기본 정보

| 항목          | 내용                                 |
| ------------- | ------------------------------------ |
| **공식 문서** | ESM 셀러센터 → 개발자센터            |
| **Base URL**  | `https://api.gmarket.co.kr` (지마켓) |
|               | `https://api.auction.co.kr` (옥션)   |
| **인증 방식** | Bearer Token (OAuth 2.0)             |

## 4.2 인증

```http
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
&client_id={CLIENT_ID}
&client_secret={CLIENT_SECRET}
```

---

## 4.3 주문 조회 API

### 4.3.1 주문 목록 조회

```http
GET /v1/orders
Authorization: Bearer {access_token}

siteType={GMKT|AUCTION}
searchDateType={ORD|PAY}
startDate={YYYY-MM-DD}
endDate={YYYY-MM-DD}
orderStatus={주문상태}
pageNo=1&pageSize=100
```

**orderStatus 값**:
| 상태 | 설명 |
|------|------|
| `ORDER_RECEIVED` | 주문접수 |
| `PAY_COMPLETE` | 결제완료 |
| `PREPARING` | 상품준비중 |
| `SHIPPING` | 배송중 |
| `DELIVERED` | 배송완료 |
| `CONFIRMED` | 구매확정 |
| `CANCEL_REQUESTED` | 취소요청 |
| `RETURN_REQUESTED` | 반품요청 |
| `EXCHANGE_REQUESTED` | 교환요청 |

### 4.3.2 클레임 목록 조회

```http
GET /v1/claims
Authorization: Bearer {access_token}

claimType={CANCEL|RETURN|EXCHANGE}
startDate={YYYY-MM-DD}
endDate={YYYY-MM-DD}
```

### 4.3.3 주문 응답 필드 상세 (전체 수집 가능 정보)

#### 📦 주문 기본 정보

| 필드명          | 타입     | 설명                      |
| --------------- | -------- | ------------------------- |
| `ordNo`         | String   | 주문번호                  |
| `siteType`      | String   | 사이트 (GMKT/AUCTION)     |
| `orderDate`     | DateTime | 주문일시                  |
| `paymentDate`   | DateTime | 결제일시                  |
| `orderStatus`   | String   | 주문상태                  |
| `paymentMethod` | String   | 결제수단                  |
| `orderChannel`  | String   | 주문채널 (WEB/MOBILE/APP) |

#### 💰 금액 정보 (가격/수수료/정산)

| 필드명                 | 타입    | 설명               |
| ---------------------- | ------- | ------------------ |
| `totalAmount`          | Integer | 총 주문금액        |
| `productAmount`        | Integer | 상품금액           |
| `deliveryFee`          | Integer | 배송비             |
| `totalDiscount`        | Integer | 총 할인금액        |
| `sellerCouponDiscount` | Integer | 판매자 쿠폰 할인   |
| `ebayDiscount`         | Integer | 이베이 할인 부담금 |
| `pointUsage`           | Integer | 포인트 사용        |
| `commissionAmount`     | Integer | **판매 수수료**    |
| `commissionRate`       | Float   | **수수료율 (%)**   |
| `settlementAmount`     | Integer | **정산 예정금액**  |
| `settlementDate`       | Date    | 정산예정일         |
| `refundAmount`         | Integer | 환불금액           |

#### 👤 주문자 정보 (Orderer)

| 필드명             | 타입   | 설명          |
| ------------------ | ------ | ------------- |
| `orderer.name`     | String | 주문자 이름   |
| `orderer.phone`    | String | 주문자 연락처 |
| `orderer.email`    | String | 주문자 이메일 |
| `orderer.memberId` | String | 회원ID        |

#### 📍 수령자 정보 (Receiver)

| 필드명                   | 타입   | 설명              |
| ------------------------ | ------ | ----------------- |
| `receiver.name`          | String | 수령인 이름       |
| `receiver.phone`         | String | 수령인 연락처     |
| `receiver.mobile`        | String | 수령인 휴대폰     |
| `receiver.zipCode`       | String | 우편번호          |
| `receiver.address`       | String | 기본주소          |
| `receiver.addressDetail` | String | 상세주소          |
| `receiver.memo`          | String | 배송 메시지       |
| `receiver.doorPassword`  | String | 공동현관 비밀번호 |

#### 📦 상품 정보 (OrderItems)

| 필드명             | 타입    | 설명                |
| ------------------ | ------- | ------------------- |
| `itemNo`           | String  | 상품번호            |
| `itemName`         | String  | 상품명              |
| `optionNo`         | String  | 옵션번호            |
| `optionName`       | String  | 옵션명              |
| `quantity`         | Integer | 주문수량            |
| `price`            | Integer | 상품가격            |
| `optionPrice`      | Integer | 옵션추가금액        |
| `sellerItemCode`   | String  | **판매자 상품코드** |
| `sellerOptionCode` | String  | **판매자 옵션코드** |

#### 🚚 배송 정보

| 필드명                | 타입     | 설명         |
| --------------------- | -------- | ------------ |
| `deliveryCompanyCode` | String   | 택배사 코드  |
| `deliveryCompanyName` | String   | 택배사명     |
| `trackingNumber`      | String   | 송장번호     |
| `shippedDate`         | DateTime | 발송일시     |
| `deliveredDate`       | DateTime | 배송완료일시 |
| `deliveryType`        | String   | 배송유형     |

---

## 4.4 발송 처리 API

### 4.4.1 발송 처리

```http
POST /v1/orders/{ordNo}/shipment
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "deliveryCompanyCode": "CJGLS",
  "trackingNumber": "123456789012",
  "sendDate": "2024-01-23"
}
```

### 4.4.2 발송 정보 수정

```http
PUT /v1/orders/{ordNo}/shipment
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "deliveryCompanyCode": "HANJIN",
  "trackingNumber": "987654321098"
}
```

---

## 4.5 취소 처리 API

### 4.5.1 취소 승인

```http
POST /v1/claims/{claimNo}/cancel/approve
Authorization: Bearer {access_token}
```

### 4.5.2 취소 거부

```http
POST /v1/claims/{claimNo}/cancel/reject
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "rejectReason": "이미 발송 완료된 상품입니다"
}
```

---

## 4.6 반품 처리 API

### 4.6.1 반품 승인

```http
POST /v1/claims/{claimNo}/return/approve
Authorization: Bearer {access_token}
```

### 4.6.2 반품 거부

```http
POST /v1/claims/{claimNo}/return/reject
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "rejectReason": "반품 불가 사유"
}
```

### 4.6.3 반품 수거 완료

```http
POST /v1/claims/{claimNo}/return/collect
Authorization: Bearer {access_token}
```

### 4.6.4 반품 완료

```http
POST /v1/claims/{claimNo}/return/complete
Authorization: Bearer {access_token}
```

---

## 4.7 교환 처리 API

### 4.7.1 교환 승인

```http
POST /v1/claims/{claimNo}/exchange/approve
Authorization: Bearer {access_token}
```

### 4.7.2 교환 발송

```http
POST /v1/claims/{claimNo}/exchange/shipment
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "deliveryCompanyCode": "CJGLS",
  "trackingNumber": "123456789012"
}
```

---

# 5. 공통 구현 가이드

## 5.1 통합 주문 상태 정규화

```python
class UnifiedOrderStatus:
    PAID = "PAID"                     # 결제완료
    PREPARING = "PREPARING"           # 상품준비중
    SHIPPED = "SHIPPED"               # 발송완료
    DELIVERING = "DELIVERING"         # 배송중
    DELIVERED = "DELIVERED"           # 배송완료
    CONFIRMED = "CONFIRMED"           # 구매확정
    CANCEL_REQUESTED = "CANCEL_REQ"   # 취소요청
    CANCELED = "CANCELED"             # 취소완료
    RETURN_REQUESTED = "RETURN_REQ"   # 반품요청
    RETURNED = "RETURNED"             # 반품완료
    EXCHANGE_REQUESTED = "EXCH_REQ"   # 교환요청
    EXCHANGED = "EXCHANGED"           # 교환완료

STATUS_MAPPING = {
    "smartstore": {
        "PAY_COMPLETED": UnifiedOrderStatus.PAID,
        "PACKING": UnifiedOrderStatus.PREPARING,
        "SHIPPING": UnifiedOrderStatus.DELIVERING,
        "DELIVERED": UnifiedOrderStatus.DELIVERED,
        "PURCHASE_CONFIRMED": UnifiedOrderStatus.CONFIRMED,
        "CANCEL_REQUESTED": UnifiedOrderStatus.CANCEL_REQUESTED,
        "CANCELED": UnifiedOrderStatus.CANCELED,
        "RETURN_REQUESTED": UnifiedOrderStatus.RETURN_REQUESTED,
        "RETURN_COMPLETED": UnifiedOrderStatus.RETURNED,
        "EXCHANGE_REQUESTED": UnifiedOrderStatus.EXCHANGE_REQUESTED,
        "EXCHANGE_COMPLETED": UnifiedOrderStatus.EXCHANGED,
    },
    "coupang": {
        "ACCEPT": UnifiedOrderStatus.PAID,
        "INSTRUCT": UnifiedOrderStatus.PREPARING,
        "DEPARTURE": UnifiedOrderStatus.SHIPPED,
        "DELIVERING": UnifiedOrderStatus.DELIVERING,
        "FINAL_DELIVERY": UnifiedOrderStatus.DELIVERED,
        "CANCEL": UnifiedOrderStatus.CANCELED,
        "RETURN": UnifiedOrderStatus.RETURN_REQUESTED,
    },
    "11st": {
        "102": UnifiedOrderStatus.PAID,
        "201": UnifiedOrderStatus.PREPARING,
        "301": UnifiedOrderStatus.DELIVERING,
        "302": UnifiedOrderStatus.DELIVERED,
        "401": UnifiedOrderStatus.CONFIRMED,
        "501": UnifiedOrderStatus.CANCEL_REQUESTED,
        "502": UnifiedOrderStatus.CANCELED,
        "601": UnifiedOrderStatus.RETURN_REQUESTED,
        "603": UnifiedOrderStatus.RETURNED,
        "701": UnifiedOrderStatus.EXCHANGE_REQUESTED,
        "703": UnifiedOrderStatus.EXCHANGED,
    },
    "esm": {
        "PAY_COMPLETE": UnifiedOrderStatus.PAID,
        "PREPARING": UnifiedOrderStatus.PREPARING,
        "SHIPPING": UnifiedOrderStatus.DELIVERING,
        "DELIVERED": UnifiedOrderStatus.DELIVERED,
        "CONFIRMED": UnifiedOrderStatus.CONFIRMED,
        "CANCEL_REQUESTED": UnifiedOrderStatus.CANCEL_REQUESTED,
        "RETURN_REQUESTED": UnifiedOrderStatus.RETURN_REQUESTED,
        "EXCHANGE_REQUESTED": UnifiedOrderStatus.EXCHANGE_REQUESTED,
    }
}
```

## 5.2 통합 클레임 처리 인터페이스

```python
from abc import ABC, abstractmethod

class MarketplaceClaimHandler(ABC):
    @abstractmethod
    def get_claims(self, claim_type: str, start_date: str, end_date: str) -> List[dict]:
        """클레임 목록 조회"""
        pass

    @abstractmethod
    def approve_cancel(self, claim_id: str) -> bool:
        """취소 승인"""
        pass

    @abstractmethod
    def reject_cancel(self, claim_id: str, reason: str) -> bool:
        """취소 거부"""
        pass

    @abstractmethod
    def approve_return(self, claim_id: str) -> bool:
        """반품 승인"""
        pass

    @abstractmethod
    def reject_return(self, claim_id: str, reason: str) -> bool:
        """반품 거부"""
        pass

    @abstractmethod
    def complete_return_collect(self, claim_id: str) -> bool:
        """반품 수거 완료"""
        pass

    @abstractmethod
    def complete_return(self, claim_id: str) -> bool:
        """반품 완료 (환불)"""
        pass

    @abstractmethod
    def approve_exchange(self, claim_id: str) -> bool:
        """교환 승인"""
        pass

    @abstractmethod
    def ship_exchange(self, claim_id: str, courier_code: str, tracking_no: str) -> bool:
        """교환 상품 발송"""
        pass
```

## 5.3 Rate Limit 정리

| 플랫폼       | 호출 제한 | 페이지 크기 | 조회 기간  |
| ------------ | --------- | ----------- | ---------- |
| 스마트스토어 | 1000회/분 | 최대 300건  | 최근 6개월 |
| 쿠팡         | 100회/분  | 최대 50건   | 최근 3개월 |
| 11번가       | 300회/분  | 최대 100건  | 최근 1년   |
| ESM          | 500회/분  | 최대 100건  | 최근 6개월 |

## 5.4 클레임 처리 프로세스 플로우

```
[취소 프로세스]
고객 취소요청 → 판매자 확인 → 승인/거부
                              ↓ (승인 시)
                          환불 처리 → 완료

[반품 프로세스]
고객 반품요청 → 판매자 확인 → 승인/거부
                              ↓ (승인 시)
                          수거 진행 → 수거 완료 → 환불 처리 → 완료

[교환 프로세스]
고객 교환요청 → 판매자 확인 → 승인/거부
                              ↓ (승인 시)
                          수거 진행 → 수거 완료 → 교환 상품 발송 → 완료
```

---

## 부록: 개발자 등록 URL

| 플랫폼           | URL                                  |
| ---------------- | ------------------------------------ |
| 네이버 커머스API | https://apicenter.commerce.naver.com |
| 쿠팡 Wing        | https://developers.coupangcorp.com   |
| 11번가 오픈API   | https://openapi.11st.co.kr           |
| ESM 2.0          | ESM 셀러센터 → 설정 → 개발자센터     |

---

> **⚠️ 주의사항**
>
> - API 키/시크릿은 환경변수로 관리하세요
> - 프로덕션에서는 HTTPS 필수
> - 각 플랫폼 공식 문서에서 최신 정보 확인 필수
