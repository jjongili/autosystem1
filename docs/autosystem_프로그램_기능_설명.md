# AutoSystem 프로그램 기능 설명서

> 작성일: 2026-01-23
> 작성자: 프코노미 (Antigravity)

---

## 목차

1. [스마트스토어 관리](#1-스마트스토어-관리)
2. [11번가 관리](#2-11번가-관리)
3. [불사자 상품 관리](#3-불사자-상품-관리)
4. [ESM (G마켓/옥션) 관리](#4-esm-g마켓옥션-관리)
5. [기타 유틸리티](#5-기타-유틸리티)

---

## 1. 스마트스토어 관리

### 1.1 smartstore_all_in_one_v1.1.py

**파일**: `1. smartstore_all_in_one_v1.1.py`

**기능**: 스마트스토어 통합 관리 프로그램

- **등록갯수**: 스토어별 등록 상품 개수 조회
- **배송코드**: 배송지 주소록 코드 조회
- **배송변경**: 상품 배송정보 일괄 변경
- **상품삭제**: 조건에 맞는 상품 일괄 삭제 (삭제금지상품 예외 처리)
- **혜택설정**: 상품 혜택 일괄 설정
- **중복삭제**: 중복 상품 자동 삭제

**특징**:

- 구글시트 연동 (stores 탭에서 계정 관리)
- 병렬 처리 지원 (PARALLEL_STORES, PARALLEL_WORKERS)
- Ctrl+C 안전 중단 지원

**버전 이력**:
| 버전 | 변경사항 |
|------|----------|
| v1.1 | 열 범위 계산 버그 수정, Thread Safety 개선, HTTP 세션 재사용 |

---

### 1.2 smartstore_zzim_auto_v1.6.py

**파일**: `8. smartstore_zzim_auto_v1.6.py`

**기능**: 스마트스토어 찜 자동화 프로그램

- 여러 네이버 계정으로 상품 찜 자동 실행
- 각 계정별 별도 프로필 폴더 사용 (충돌 방지)
- 숨김 모드 (화면 밖 실행) 지원

**특징**:

- Selenium 기반 브라우저 자동화
- URL 순서 랜덤 셔플
- 연속 스킵 옵션 (20/40/80/전체)
- 설정 자동 저장/불러오기

---

### 1.3 smartstore_hijacker_v2.0.py

**파일**: `12. smartstore_hijacker_v2.0.py`

**기능**: 스마트스토어 상품 데이터 수집

- 다른 스마트스토어의 상품 정보 수집
- 구글시트 연동

---

## 2. 11번가 관리

### 2.1 11st_all_products_display_v0.2.py

**파일**: `2. 11st_all_products_display_v0.2.py`

**기능**: 11번가 전체 상품 전시중지/전시재개 자동화

- **판매중지**: 전체 상품 전시중지 처리
- **판매재개**: 전체 상품 전시재개 처리

**특징**:

- 구글시트 기반 계정 관리 (11번가 탭)
- prodmarket API로 상품 목록 조회
- 계정 단위 + 상품 단위 병렬 처리

---

### 2.2 bulsaja_11st_disconnect.py

**파일**: `bulsaja_11st_disconnect.py`

**기능**: 불사자 상품의 11번가 마켓 연결 해제

- 특정 그룹의 상품에서 11번가 마켓 연결 끊기
- 미리보기 후 진행 (제외 상품 확인)
- 병렬 처리 10개 동시 실행

**그룹 지원**:

- 플로 (1~20번)
- 흑곰 (1~20번)
- 검은곰 (1~20번)

---

## 3. 불사자 상품 관리

### 3.1 product_name_generator_v2.py (Premium Dashboard)

**파일**: `product_name_generator_v2.py`
**기능**: 대량 상품명 생성, 노출 순위 추적 및 집중 관리 통합 솔루션

- **Madword 스타일 대시보드**: 전문가용 통합 관리 인터페이스 제공
- **키워드 트래픽 분석**: 네이버 광고/검색 API를 통한 실시간 검색량 및 경쟁강도 분석
- **지능형 IP Guard**: Kiwi(형태소 분석) + Gemini AI를 결합한 고효율 지식재산권 검수
- **커머스 API & 순위 추적**: 스마트스토어 직접 상품명 업데이트 및 검색 노출 순위 실시간 모니터링
- **집중 관리(Focus) 시스템**: 유입이 발생하는 '정예 상품' 선정 및 순위 변동 이력 영구 관리

**핵심 워크플로우**:

1.  **시뮬레이션 모드**: 1만 개 이상의 대량 데이터를 서버 반영 없이 시뮬레이션 및 데이터 집계(CSV)
2.  **검증 데이터 수입(Import)**: 외부 도구에서 판별된 노출 상품 코드를 일괄 등록하여 집중 관리 대상 선정
3.  **정예 SEO 관리**: 선정된 집중 관리 아이템(200여 개)에 대해 실시간 순위 추적 및 최적화 반복

**버전 이력**:
| 버전 | 변경사항 |
|------|----------|
| v1.0 | 기본 PyQt6 UI 탑재, 불사자 API 연동 |
| v2.0 | 'Madword' 스타일 UI 개편, 네이버 트래픽 데이터 연동, 순위 추적기(Rank Tracker) 및 커머스 API 탑재, 집중 관리(Focus) 워크플로우 도입 |

---

### 3.2 bulsaja_image_translator_v2.0+api.py

**파일**: `6. bulsaja_image_translator_v2.0+api.py`

**기능**: 불사자 상품 이미지 자동 번역

- 썸네일 이미지 자동 번역
- 옵션 이미지 자동 번역
- API 기반 백그라운드 처리 (브라우저 조작 없음)

**특징**:

- 이미지 단위 병렬 처리로 속도 대폭 향상
- 상태/번역 필터에 '전체' 옵션

**참조 파일**: 없음 (독립 실행)

**pip 패키지**: `requests`, `websocket-client`

**버전 이력**:
| 버전 | 변경사항 |
|------|----------|
| v2.1 | 이미지 단위 병렬 처리 |
| v2.2 | 상태/번역 필터에 '전체' 옵션 추가 |

---

### 3.3 bulsaja_uploader_v1.6.py

**파일**: `7. bulsaja_uploader_v1.6.py`

**기능**: 불사자 상품 마켓 업로드

- 스마트스토어, 11번가, G마켓/옥션, 쿠팡 업로드
- 마켓 그룹 선택 (다중 선택)
- 동시 세션 설정

**업로드 조건**:

- 미업로드 (수집완료+수정중+검토완료)
- 수집완료만
- 수정중만
- 검토완료만
- 업로드완료 (판매중)
- 전체

**특징**:

- 미끼 옵션 자동 필터링
- 대표옵션 자동 선택
- 카테고리 오류 시 ESM 카테고리로 재시도

**참조 파일**:
| 파일 | 필수 | 설명 |
|------|------|------|
| `bulsaja_common.py` | ✅ | API 클라이언트, 미끼필터, 안전검사 |
| `banned_words.json` | ❌ | 금지단어 (없으면 기본값) |
| `excluded_words.json` | ❌ | 예외단어 (없으면 기본값) |
| `remove_words.json` | ❌ | 제거단어 (없으면 기본값) |
| `bait_keywords.json` | ❌ | 미끼옵션 키워드 (없으면 기본값) |

**pip 패키지**: `requests`, `websocket-client`

**버전 이력**:
| 버전 | 변경사항 |
|------|----------|
| v1.2 | 그룹별 마켓 ID 동적 매핑 |
| v1.3 | 카테고리 오류 시 ESM 카테고리로 재시도 |
| v1.5 | 중복실패 별도 카운트, 실패태그 건너뜀 옵션 |
| v1.6 | 가격 계산 공식 수정 (불사자 공식 적용, 카드수수료 포함) |

---

### 3.4 bulsaja_copier_v0.2.py

**파일**: `9. Bulsaja copier v0.2.py`

**기능**: 불사자 상품 복사 프로그램

- 한 그룹의 상품을 다른 그룹으로 복사
- 중복 체크 후 복사
- 통합그룹 단위 복사 지원

**통합그룹**:

- 통합1~10 (4개 그룹씩 묶음)
- 41개 그룹 지원

---

### 3.5 bulsaja_shipping_fixer.py

**파일**: `bulsaja_shipping_fixer.py`

**기능**: 불사자 배송비 확인/수정 도구

- **1단계**: 배송비 올림 처리 (예: 6720 → 7000)
- **2단계**: 저장된 해외마켓ID로 매칭하여 배송비 적용

**특징**:

- 해외마켓ID + 배송비 매핑 저장
- 동일 타오바오 상품의 복사본에 일괄 적용

---

### 3.6 ai_shipping_gui.py

**파일**: `ai_shipping_gui.py`

**기능**: AI 배송비 자동 업데이트 프로그램

- 불사자 AI API로 배송비 자동 분석
- 썸네일 이미지 기반 배송비 추정
- 천원 단위 올림 적용

**기능 상세**:

- **대량 ID 모드**: 수백 개의 ID를 불러와서 자동 순회 처리
- **스마트 필터**: 배송비 "0원"인 상품만 처리하는 옵션
- **전체 그룹 순회**: 모든 창고를 자동으로 돌며 업데이트

---

### 3.7 bulsaja_smartstore_sync.py

**파일**: `bulsaja_smartstore_sync_v1.0 (1).py`

**기능**: 불사자-스마트스토어 동기화

- 불사자 '업로드됨' 상품 중 실제 스마트스토어에 없는 상품 찾기
- 자동으로 미업로드 + 수정중 상태로 변경
- 불사자 내장 API 활용 (네이버 API 불필요)

---

### 3.8 simulator_gui_v4.py

**파일**: `simulator_gui_v4.py`

**기능**: 불사자 상품 시뮬레이터 (검수 도구)

- **수집 탭**: 상품 목록 조회 및 필터링
- **검수 탭**: 상품 상세 정보 확인 및 검수
- **설정 탭**: 프로그램 설정

**특징**:

- PyQt6 기반 최적화 UI
- QThreadPool을 이용한 이미지 병렬 로딩
- 대량 데이터 처리 최적화

**검수 수준**:

- 보통 (자동판단)
- 엄격 (AI검수)
- 검수제외

**참조 파일**: 없음 (독립 실행)

**pip 패키지**: `PyQt6`

---

### 3.9 bulsaja_option_updater_v2.py

**파일**: `9. bulsaja_option_updater_v2.py`

**기능**: 불사자 상품 옵션 일괄 수정 (시뮬레이터 결과 반영)

**핵심 기능**:
- 대표옵션 설정 (main_product: true)
- 가격범위 자동 적용 (50%~150% 밖 옵션 제외)
- 썸네일 변경 (uploadThumbnails 순서 변경)
- 미끼옵션 제외 (exclude: true 설정)
- **양방향 동기화**: uploadSkus ↔ uploadSkuProps.mainOption.values[] exclude 동기화

**워크플로우**:
```
시뮬레이터 검수 → 엑셀 저장 → 사용자 수정 → 옵션 업데이터 실행 → 불사자 반영
```

**참조 파일**:
| 파일 | 필수 | 설명 |
|------|------|------|
| `bulsaja_common.py` | ✅ | API 클라이언트, 토큰 추출 |

**pip 패키지**: `openpyxl`

**엑셀 컬럼**:
| 컬럼 | 내용 | 설명 |
|------|------|------|
| B | 불사자ID | 상품 ID |
| L | 선택 | A/B/C... 대표옵션 |
| K | 미끼옵션목록 | 제외할 옵션 |
| Q | 썸네일선택 | 1~6 (선택사항) |

**버전 이력**:
| 버전 | 변경사항 |
|------|----------|
| v1.0 | 초기 버전 (mainImage, SKU 삭제 방식 - API 비준수) |
| v2.0 | API 규격 준수 (main_product, exclude 사용), 가격범위 자동 적용, 썸네일 변경 추가 |

**v2.0 주요 수정 (2026-01-27)**:
- 대표옵션: `mainImage` → `main_product` 필드 사용
- 옵션제외: SKU 삭제 → `exclude: true` 설정 (마켓 구조 유지)
- 가격범위: 대표옵션 기준 50%~150% 자동 계산
- 썸네일: `uploadThumbnails` 배열 순서 변경으로 대표 썸네일 변경
- **양방향 동기화**: 가격탭(`uploadSkus`)과 옵션탭(`uploadSkuProps.mainOption.values[]`)의 exclude 값 자동 동기화 (vid ↔ id 매핑)

---

## 4. ESM (G마켓/옥션) 관리

### 4.1 esm_manager_gui.py

**파일**: `10. esm_manager_gui.py`

**기능**: ESM Plus 상품 자동 관리

- Selenium JavaScript fetch로 API 호출
- 브라우저 세션 직접 사용 (세션 유지)

**판매상태 관리**:

- 판매중
- 판매중지
- 품절

---

## 5. 기타 유틸리티

### 5.1 bulsaja_common.py

**파일**: `bulsaja_common.py`

**기능**: 불사자 공통 모듈 (다른 프로그램에서 참조)

- **BulsajaAPIClient**: 불사자 API 클라이언트 클래스
- **extract_tokens_from_browser()**: 크롬 디버그 모드에서 토큰 추출
- **filter_bait_options()**: 미끼 옵션 필터링
- **select_main_option()**: 대표옵션 선택
- **load_bait_keywords()**: 미끼 키워드 로드
- **check_product_safety()**: 상품 안전성 검사

**이 모듈을 참조하는 프로그램**:
- `7. bulsaja_uploader_v1.6.py`
- `9. bulsaja_option_updater_v2.py`
- `bulsaja_dashboard_v2.py`
- `bulsaja_status_fixer.py`
- `bulsaja_uploader_cli.py`
- `bulsaja_uploader_server.py`
- `thumbnail_analyzer.py`

**선택적 JSON 파일** (없으면 기본값 사용):
| 파일 | 설명 |
|------|------|
| `banned_words.json` | 금지단어 (브랜드/위험상품) |
| `excluded_words.json` | 예외단어 (탐지 제외) |
| `remove_words.json` | 제거단어 (상품명에서 삭제) |
| `bait_keywords.json` | 미끼옵션 키워드 |

**pip 패키지**: `requests`, `websocket-client`, `kiwipiepy` (형태소 분석)

---

### 5.2 ali_products_sheet_gui.py

**파일**: `11. ali_products_sheet_gui.py`

**기능**: 알리익스프레스 상품 구글시트 등록

---

### 5.3 delete_exceptions_sync.py

**파일**: `delete_exceptions_sync.py`

**기능**: 삭제금지상품 목록 동기화

- 구글시트의 '삭제금지상품' 탭 자동 업데이트
- smartstore_all_in_one에서 호출

---

## 공통 사항

### 인증 방식

모든 불사자 연동 프로그램은 **Chrome Debug Mode**를 통한 토큰 추출 방식 사용:

1. 크롬을 디버그 모드로 실행 (포트 9222)
2. 불사자 사이트 로그인
3. localStorage에서 accessToken, refreshToken 추출

### 설정 파일

각 프로그램은 개별 설정 파일(JSON) 사용:

- `bulsaja_uploader_config.json`
- `bulsaja_translator_config.json`
- `simulator_gui_v4_config.json`
- 등

### 병렬 처리

대부분의 프로그램이 ThreadPoolExecutor를 이용한 병렬 처리 지원

---

## 연락처

문의: 프코노미 (Antigravity)
