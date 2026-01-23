# Simulator GUI v3 - 핵심 문서

> **이 문서는 AI 컨텍스트 복구용입니다. 세션이 끊어졌을 때 이 파일을 먼저 읽으세요.**

---

## 1. 파일 개요

### simulator_gui_v3.py
- **위치**: `c:\Project\autosystem1\simulator_gui_v3.py`
- **목적**: 타오바오/1688 구매대행 상품 수집 + 검수 + 직접 API 업로드 GUI
- **핵심 기능**:
  1. 불사자 API로 상품 수집 (수집탭)
  2. 엑셀 저장/로드
  3. 검수탭에서 옵션 선택 + 썸네일 분석
  4. 스마트스토어/11번가/쿠팡 직접 업로드 (불사자 없이)

### thumbnail_analyzer.py
- **위치**: `c:\Project\autosystem1\thumbnail_analyzer.py`
- **목적**: 썸네일 자동 분석 - 스마트스토어 업로드에 적합한 이미지 찾기
- **핵심**: 중국어 텍스트 없는 흰배경 이미지 선별

---

## 2. 썸네일 점수 시스템 (thumbnail_analyzer.py)

### 점수 체계
| 항목 | 점수 범위 | 설명 |
|------|----------|------|
| 누끼 점수 | 0~50 | 흰배경/단색 배경 정도 |
| 텍스트 점수 | -30~+30 | 중국어 텍스트 유무 |
| 중앙객체 점수 | 0~20 | 제품이 중앙에 있는지 |

### 누끼 점수 상세
```python
# check_nukki() 메서드
90%+ 흰색 배경 → 50점 (완벽한 누끼)
70%+ 흰색 배경 → 40점 (좋은 누끼)
80%+ 밝은색 배경 → 30점 (괜찮은 누끼)
단색+밝은색 → 25점
단색 배경 → 15점
복잡한 배경 → 0점
```

### 텍스트 점수 상세
```python
# check_text() 메서드 - easyocr 사용
텍스트 0개 → +30점 (최고)
텍스트 1~2개 → +10점
텍스트 3~5개 → -10점
텍스트 6개+ → -30점 (최악)
```

### 추천 등급
- `best`: 누끼 O + 텍스트 X → 바로 사용 가능
- `needs_translate`: 누끼 O + 텍스트 O → 번역 필요
- `needs_nukki`: 누끼 X + 텍스트 X → 누끼 제거 필요
- `needs_both`: 둘 다 필요
- `poor`: 복잡함 - 수동 확인

---

## 3. 직접 API 업로드용 데이터 구조

### _analyze_single_product 반환 데이터
```python
result = {
    # 기본 정보
    'product_id': '...',
    'name': '...',
    'thumbnail_url': '...',

    # 직접 API 업로드용 추가 데이터
    'option_images': {'A': url, 'B': url, ...},  # 옵션별 이미지
    'option_prices': {'A': 12000, 'B': 13000, ...},  # 옵션별 가격
    'all_thumbnails': [url1, url2, url3, ...],  # 전체 썸네일 목록
    'all_skus': [...],  # 전체 SKU 데이터
    'raw_product': {...},  # 원본 상품 데이터 전체
}
```

---

## 4. 탭 간 데이터 흐름

### 방법 1: 엑셀 경유
```
수집탭 → _save_collection_to_excel() → 엑셀파일
         → 자동으로 검수탭 전환 + _load_excel_file()
```

### 방법 2: 메모리 직접 전달
```
수집탭 → _transfer_to_review() → 검수탭
         (엑셀 저장 없이 바로 전달)
```

---

## 5. 핵심 함수 위치

### 수집 관련
- `_analyze_single_product()`: 단일 상품 분석, 모든 데이터 수집
- `_save_collection_to_excel()`: 엑셀 저장 + 자동 검수탭 전환
- `_transfer_to_review()`: 메모리 직접 전달

### 검수 관련
- `_parse_excel_data()`: 엑셀 → 검수탭 데이터 변환
- `_on_option_click()`: 옵션 클릭 시 이미지 업데이트
- `_load_option_image_async()`: 비동기 옵션 이미지 로드
- `_analyze_thumbnails()`: **전체 썸네일 분석하여 최적 선택**

### 썸네일 분석
- `_analyze_thumbnails()` in simulator_gui_v3.py
  - `item['all_thumbnails']`에서 전체 목록 가져옴
  - `ThumbnailAnalyzer.get_best_thumbnail()` 호출
  - 최적 썸네일 자동 선택 + UI 업데이트

---

## 6. 엑셀 컬럼 구조

### 메인 시트
| 컬럼명 | 설명 |
|--------|------|
| 썸네일이미지 | =IMAGE() 함수 |
| 옵션이미지 | =IMAGE() 함수 |
| 상품명 | 번역된 상품명 |
| 안전여부 | O/X |
| 위험사유 | 위험시 사유 |
| 전체옵션 | 총 옵션 수 |
| 유효옵션 | 유효한 옵션 수 |
| 최종옵션 | 실제 사용할 옵션 수 |
| 대표옵션 | A. 옵션명 |
| 선택 | A (선택된 라벨) |
| 옵션명 | 전체 옵션 목록 |
| 불사자ID | 상품 ID |
| **옵션이미지JSON** | {"A": url, "B": url, ...} |
| **옵션가격JSON** | {"A": 12000, ...} |
| **전체썸네일** | url1\|url2\|url3... |

### 원본SKU데이터 시트
- 각 상품별 전체 SKU 데이터 (직접 API용)

---

## 7. 스마트스토어 정책

- **중국어 텍스트 이미지**: 반려됨 (절대 사용 불가)
- **한국어 텍스트 이미지**: 허용
- **권장**: 흰배경 + 텍스트 없는 누끼 이미지

→ 썸네일 분석의 목적: 중국어 없는 최적 이미지 자동 선별

---

## 8. 의존성

```bash
pip install opencv-python pillow easyocr
pip install openpyxl requests
pip install tkinter  # 보통 기본 포함
```

---

## 9. 주의사항

1. `all_thumbnails`는 파이프(`|`)로 구분된 문자열로 엑셀에 저장됨
2. 옵션 클릭 시 `option_images`에서 해당 옵션 이미지 로드
3. 썸네일 분석은 easyocr 첫 로딩 시 시간 소요 (GPU 없으면 느림)
4. 이미지 로딩은 ThreadPoolExecutor로 비동기 처리

---

## 10. 최근 수정 이력

| 날짜 | 수정 내용 |
|------|----------|
| 최근 | **직접 API 업로드 옵션 추가** - uploadDetailContents, uploadCategory 선택적 수집 |
| 최근 | `_analyze_thumbnails()` - 전체 썸네일 분석으로 변경 |
| 최근 | `_on_option_click()` - 옵션 이미지 업데이트 추가 |
| 최근 | `_transfer_to_review()` - 메모리 직접 전달 추가 |
| 최근 | 직접 API용 데이터 수집 (option_images, all_thumbnails 등) |

---

## 11. 직접 API 업로드 옵션 (신규)

### UI 위치
수집탭 → "🔗 직접 API 업로드용 (스마트스토어 등)" 섹션

### 체크박스 옵션
| 옵션 | 변수 | 설명 |
|------|-----|------|
| 상세이미지 | `fetch_detail_contents_var` | uploadDetailContents 수집 |
| 카테고리 | `fetch_category_var` | uploadCategory 수집 |

### 동작 원리
```python
# 체크박스 선택 시 수집 로직 (1176-1185줄)
if fetch_detail_contents or fetch_category:
    upload_fields = self.api_client.get_upload_fields(prod_id)
    if fetch_detail_contents:
        detail['uploadDetailContents'] = upload_fields.get('uploadDetailContents', {})
    if fetch_category:
        detail['uploadCategory'] = upload_fields.get('uploadCategory', {})
```

### API 차이
| API | 엔드포인트 | 데이터 |
|-----|-----------|--------|
| `get_product_detail()` | `/manage/sourcing-product/{id}` | 기본 정보만 |
| `get_upload_fields()` | `/sourcing/uploadfields/{id}` | 전체 업로드 필드 |

### 수집된 데이터 저장 위치
- `result['upload_detail_contents']` - 상세이미지
- `result['upload_category']` - 카테고리

---

**이 문서를 읽은 후 simulator_gui_v3.py와 thumbnail_analyzer.py를 읽으면 전체 맥락 파악 가능**
