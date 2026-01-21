# 불사자 옵션 필터링 로직 정리

## 1. 미끼 옵션 필터링 (`filter_bait_options`)

### 1.1 가격 기반 필터링
**두 가지 기준:**

1. **절대 기준**: 3위안(CNY) 이하 → 무조건 미끼
   - 배송비 미끼, 샘플 미끼 등

2. **상대 기준**: 가격 편차가 클 때만 적용
   - 조건: `최대가 > 최소가 × 5` (5배 이상 차이)
   - 기준: `중간값(median)의 15%` 이하면 미끼
   - 예: 중간값 100위안 → 15위안 이하는 미끼

### 1.2 키워드 기반 필터링
**세 가지 키워드 유형:**

1. **강력 미끼 키워드** (`STRONG_BAIT_KEYWORDS`)
   - 예외 없이 무조건 미끼
   - 예: "배송비", "샘플" 등

2. **문맥 의존 키워드** (`CONTEXT_DEPENDENT_BAIT_KEYWORDS`)
   - "케이블만" → 미끼
   - "케이블 포함" → 정상
   - 패턴: `키워드 + 만/용/전용` → 미끼

3. **일반 미끼 키워드** (`DEFAULT_BAIT_KEYWORDS`)
   - 예외 키워드(`BAIT_EXCEPTION_KEYWORDS`)가 있으면 정상
   - 예외 키워드: 포함, 세트, 구성 등

### 1.3 반환값
```python
(valid_skus, bait_skus)  # 유효 SKU, 미끼 SKU
```

---

## 2. 대표 옵션 선택 (`select_main_option`)

### 우선순위:
1. **상품명 매칭** (30% 이상 일치)
   - 상품명에서 옵션 키워드 추출하여 매칭
   - 이미지 있는 옵션 우선

2. **이미지 있는 첫 번째 옵션**
   - `urlRef`, `image`, `img` 필드 확인

3. **첫 번째 옵션** (폴백)

---

## 3. 불사자 UI "최저 옵션가 기준범위 적용" 버튼

### 불사자 자체 기능 (우리 코드 아님):
- 최저가 옵션 선택
- 최저가 기준 50% 범위 내 옵션 자동 선택
- **모든 옵션 `exclude: false` 유지**
- 모든 옵션 가격 계산됨
- `main_product`만 최저가에 true

### 우리 코드가 해야 할 일:
1. 미끼 옵션 식별 (가격+키워드)
2. 유효 옵션 중 대표 옵션 선택
3. **exclude 건드리지 않음**
4. 모든 옵션 가격 계산
5. 대표 옵션에만 `main_product: true`

---

## 4. 핵심 상수/설정

```python
# bulsaja_common.py에 정의됨
DEFAULT_BAIT_KEYWORDS = [...]  # 기본 미끼 키워드
STRONG_BAIT_KEYWORDS = [...]   # 강력 미끼 키워드
CONTEXT_DEPENDENT_BAIT_KEYWORDS = [...]  # 문맥 의존 키워드
BAIT_EXCEPTION_KEYWORDS = [...]  # 예외 키워드
BAIT_ONLY_PATTERNS = ['만', '용', '전용']  # 미끼 패턴
```

---

## 5. 주의사항

### 절대 수정 금지 (bulsaja_sku_rules.md 참조)
- `exclude` 필드
- `id` (조합형 옵션 ID)
- `skuRef`, `urlRef`, `stock`
- `_origin_price`, `text`, `_text`

### 수정 가능
- `origin_price` (원화 원가)
- `sale_price` (원화 판매가)
- `main_product` (대표상품 여부)

---
마지막 업데이트: 2026-01-18
