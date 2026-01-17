# marketing_collector.py 수정 지시사항

## 목적
`marketing_collector.py`가 `data111.py`와 동일한 데이터를 수집하도록 수정

---

## 현재 차이점 요약

| 항목 | marketing_collector.py | data111.py | 수정 필요 |
|------|------------------------|------------|----------|
| 상품노출성과 (7개 컬럼) | ✅ 있음 | ✅ 있음 | ❌ |
| 상품클릭리포트 (7개 컬럼) | ✅ 있음 | ✅ 있음 | ❌ |
| 쇼핑몰 ID/명/타입 | ✅ 있음 | ✅ 있음 | ❌ |
| 쇼핑몰 등급 | ❌ 없음 | ✅ 있음 | ⭕ 추가 |
| 안읽은 쪽지 | ❌ 없음 | ✅ 있음 | ⭕ 추가 |
| 받은쪽지 | ❌ 없음 | ✅ 있음 | ⭕ 추가 |
| 클린위반 | ❌ 없음 | ✅ 있음 | ⭕ 추가 |
| 전체채널 데이터 | ❌ 없음 | ✅ 있음 | ⭕ 추가 |

---

## 수정 작업 1: 쇼핑몰 정보 항목 추가

### 위치
`collect_shopping_partner_data()` 함수 내 쇼핑몰 정보 수집 부분 (약 870~890 라인)

### 현재 코드
```python
mall_info_data.append(["항목", "값"])
try:
    mid = self.driver.find_element(By.CSS_SELECTOR, "li.id span.fb").text
    mall_info_data.append(["쇼핑몰 ID", mid])

    mnm = self.driver.find_element(By.CSS_SELECTOR, "li.name span:not(strong span)").text
    mall_info_data.append(["쇼핑몰 명", mnm])

    mtp = self.driver.find_element(By.CSS_SELECTOR, "li.type span:not(strong span)").text
    mall_info_data.append(["쇼핑몰 타입", mtp])
except:
    pass
```

### 수정 후 코드
```python
mall_info_data.append(["항목", "값"])

# 쇼핑몰 ID
try:
    mid = self.driver.find_element(By.CSS_SELECTOR, "li.id span.fb").text.strip()
    mall_info_data.append(["쇼핑몰 ID", mid])
except:
    pass

# 쇼핑몰 명
try:
    mnm = self.driver.find_element(By.CSS_SELECTOR, "li.name span:not(strong span)").text.strip()
    mall_info_data.append(["쇼핑몰 명", mnm])
except:
    pass

# 쇼핑몰 타입
try:
    mtp = self.driver.find_element(By.CSS_SELECTOR, "li.type span:not(strong span)").text.strip()
    mall_info_data.append(["쇼핑몰 타입", mtp])
except:
    pass

# 쇼핑몰 등급 (추가)
try:
    mall_grade = self.driver.find_element(By.CSS_SELECTOR, "li.grade span:not(strong span)").text.strip()
    mall_info_data.append(["쇼핑몰 몰등급", mall_grade])
except:
    pass

# 안읽은 쪽지 (추가)
try:
    unread_msg = self.driver.find_element(By.CSS_SELECTOR, "li.msg em.point2").text.strip()
    mall_info_data.append(["안읽은 쪽지", unread_msg])
except:
    pass

# 받은쪽지 (추가)
try:
    recv_msg = self.driver.find_element(
        By.XPATH, "//li[@class='msg']//span[@class='even']/following-sibling::em").text.strip()
    mall_info_data.append(["받은쪽지", recv_msg])
except:
    pass

# 클린위반 (추가)
try:
    clean_violation = self.driver.find_element(By.CSS_SELECTOR, "li.clean em.point2 a").text.strip()
    mall_info_data.append(["클린위반", clean_violation])
except:
    pass
```

---

## 수정 작업 2: 전체채널 데이터 수집 함수 추가

### 위치
`collect_marketing_data()` 함수 다음에 새 함수 추가

### 추가할 함수
```python
def collect_channel_data(self):
    """전체채널 데이터 수집 (채널명, 유입수)"""
    wait = WebDriverWait(self.driver, 20)
    channel_data = []

    try:
        # 1. 마케팅분석 메뉴로 이동
        print("    -> 마케팅분석 메뉴로 이동 (전체채널)")
        time.sleep(2)

        # 데이터분석 메뉴 클릭
        data_menu = None
        selectors = [
            "//a[@role='menuitem'][contains(text(),'데이터분석')]",
            "//a[contains(text(),'데이터분석')]",
        ]
        for sel in selectors:
            try:
                data_menu = wait.until(EC.element_to_be_clickable((By.XPATH, sel)))
                break
            except:
                continue

        if data_menu:
            self.safe_click(data_menu)
            print("    -> 데이터분석 클릭 완료")
        time.sleep(2)

        # 2. 마케팅분석 클릭
        marketing_link = None
        selectors = [
            "//a[contains(@href,'bizadvisor/marketing')]",
            "//a[contains(text(),'마케팅분석')]",
            "a[href='#/bizadvisor/marketing']",
        ]
        for sel in selectors:
            try:
                if sel.startswith("//"):
                    marketing_link = wait.until(EC.element_to_be_clickable((By.XPATH, sel)))
                else:
                    marketing_link = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                break
            except:
                continue

        if marketing_link:
            self.safe_click(marketing_link)
            print("    -> 마케팅분석 클릭 완료")
        else:
            self.driver.get("https://sell.smartstore.naver.com/#/bizadvisor/marketing")
            print("    -> 마케팅분석 URL 직접 이동")
        time.sleep(3)

        # 3. 전체채널 탭 확인 (기본 선택되어 있음)
        print("    -> 전체채널 탭 확인")
        try:
            channel_tab = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//ul[@class='seller-menu-tap']//a[contains(@href,'bizadvisor/marketing')]/span[text()='전체채널']/..")))
            self.safe_click(channel_tab)
            print("    -> 전체채널 탭 클릭")
        except:
            print("    -> 전체채널 탭 이미 선택됨")
        time.sleep(2)

        # 4. iframe 전환
        print("    -> iframe 전환")
        try:
            iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe#__delegate")))
            self.driver.switch_to.frame(iframe)
            print("    -> iframe 전환 완료")
        except Exception as e:
            print(f"    -> iframe 전환 실패, 계속 진행: {e}")
        time.sleep(2)

        # 5. 날짜 선택 - "어제" 선택
        print("    -> 날짜 선택 (어제)")
        try:
            date_btn = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "a.btn.select_data")))
            self.safe_click(date_btn)
            print("    -> 캘린더 팝업 열림")
            time.sleep(1)

            yesterday_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//div[@class='fix_range']//a/span[text()='어제']/..")))
            self.safe_click(yesterday_btn)
            print("    -> '어제' 선택")
            time.sleep(1)

            apply_btn = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "span.select_range")))
            self.safe_click(apply_btn)
            print("    -> '적용' 클릭 완료")
            time.sleep(3)

        except Exception as e:
            print(f"    -> 날짜 선택 실패: {e}")

        # 6. 차원 "상세" 선택
        print("    -> 차원 '상세' 선택")
        try:
            detail_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//div[@class='search_filter']//dd[@data-test-id='table-container-top-search-filter-dimension-opts']//a/span[text()='상세']/..")))
            self.safe_click(detail_btn)
            print("    -> '상세' 선택 완료")
            time.sleep(3)
        except Exception as e:
            print(f"    -> '상세' 선택 실패: {e}")

        # 7. 노출개수 1000으로 변경
        print("    -> 노출개수 1000으로 변경")
        try:
            selectbox = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "div.selectbox_box.list_count div.selectbox_label a")))
            self.safe_click(selectbox)
            time.sleep(1)

            option_1000 = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//div[@class='selectbox_box list_count']//ul/li/a[text()='1000']")))
            self.safe_click(option_1000)
            print("    -> 노출개수 1000 선택 완료")
            time.sleep(3)
        except Exception as e:
            print(f"    -> 노출개수 변경 실패: {e}")

        # 8. 테이블 데이터 수집
        print("    -> 전체채널 테이블 데이터 수집 중...")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.tbl_list")))
        time.sleep(2)

        # 헤더 추가
        headers = ["채널명", "유입수"]
        channel_data.append(headers)

        # 전체 행 수집 (total_row)
        try:
            total_row = self.driver.find_element(By.CSS_SELECTOR, "tr.total_row")
            total_cells = total_row.find_elements(By.TAG_NAME, "td")
            if len(total_cells) >= 6:
                channel_name = total_cells[2].text.strip()
                inflow = total_cells[5].text.strip()
                channel_data.append([channel_name, inflow])
                print(f"    -> 전체 행: {channel_name}, {inflow}")
        except Exception as e:
            print(f"    -> 전체 행 없음: {e}")

        # 페이지네이션 처리
        page_num = 1
        while True:
            print(f"    -> 페이지 {page_num} 수집 중...")
            time.sleep(1)

            rows = self.driver.find_elements(By.CSS_SELECTOR, "table.tbl_list tbody tr:not(.total_row)")
            print(f"    -> 페이지 {page_num}에서 {len(rows)}개 행 발견")

            page_count = 0
            for row in rows:
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) >= 6:
                        channel_name = cells[2].text.strip()
                        inflow_text = cells[5].text.strip()

                        try:
                            inflow = int(inflow_text.replace(",", ""))
                            if inflow >= 1:
                                channel_data.append([channel_name, inflow_text])
                                page_count += 1
                        except ValueError:
                            pass
                except Exception as e:
                    continue

            print(f"    -> 페이지 {page_num}에서 유입수>=1인 행: {page_count}개")

            try:
                next_btn = self.driver.find_element(By.CSS_SELECTOR, "li.btn.next:not(.disabled) a")
                if next_btn:
                    self.safe_click(next_btn)
                    time.sleep(3)
                    page_num += 1
                else:
                    break
            except:
                print("    -> 마지막 페이지")
                break

        self.driver.switch_to.default_content()
        print(f"    -> 전체채널 총 {len(channel_data)-1}개 행 수집 완료 (헤더 제외)")
        return channel_data

    except Exception as e:
        print(f"    전체채널 데이터 수집 오류: {e}")
        try:
            self.driver.switch_to.default_content()
        except:
            pass
        return channel_data
```

---

## 수정 작업 3: collect_multiple_accounts() 수집 순서 수정

### 위치
`collect_multiple_accounts()` 함수 내 (약 528~590 라인)

### 현재 코드
```python
# 2. 비즈어드바이저 수집 (상품노출성과)
self._log(f"[단계2] 비즈어드바이저 데이터 수집 시작...")
marketing_data = self.collect_marketing_data()
self._log(f"[단계2] 비즈어드바이저 수집 완료 - {len(marketing_data)}건")

# 3. 쇼핑파트너센터 수집 (클릭리포트, 몰정보)
self._log(f"[단계3] 쇼핑파트너센터 데이터 수집 시작...")
report_data, mall_info = self.collect_shopping_partner_data()
self._log(f"[단계3] 쇼핑파트너센터 수집 완료 - 리포트:{len(report_data)}건, 몰정보:{len(mall_info)}건")

# 4. 저장
store_name = account.get('store_name') or account['login_id']
self._log(f"[단계4] 구글시트 저장 중... ({store_name})")
self.save_to_sheets(store_name, marketing_data, report_data, mall_info)
self._log(f"[단계4] 저장 완료!")

# 5. 로그아웃
self._log(f"[단계5] 로그아웃...")
```

### 수정 후 코드
```python
# 2. 비즈어드바이저 수집 (상품노출성과)
self._log(f"[단계2] 비즈어드바이저 데이터 수집 시작...")
marketing_data = self.collect_marketing_data()
self._log(f"[단계2] 비즈어드바이저 수집 완료 - {len(marketing_data)}건")

# 3. 전체채널 데이터 수집 (추가)
self._log(f"[단계3] 전체채널 데이터 수집 시작...")
channel_data = self.collect_channel_data()
self._log(f"[단계3] 전체채널 수집 완료 - {len(channel_data)}건")

# 4. 쇼핑파트너센터 수집 (클릭리포트, 몰정보)
self._log(f"[단계4] 쇼핑파트너센터 데이터 수집 시작...")
report_data, mall_info = self.collect_shopping_partner_data()
self._log(f"[단계4] 쇼핑파트너센터 수집 완료 - 리포트:{len(report_data)}건, 몰정보:{len(mall_info)}건")

# 5. 저장
store_name = account.get('store_name') or account['login_id']
self._log(f"[단계5] 구글시트 저장 중... ({store_name})")
self.save_to_sheets(store_name, marketing_data, report_data, mall_info, channel_data)
self._log(f"[단계5] 저장 완료!")

# 6. 로그아웃
self._log(f"[단계6] 로그아웃...")
```

---

## 수정 작업 4: save_to_sheets() 함수 수정

### 위치
`save_to_sheets()` 함수 (약 909~941 라인)

### 현재 코드
```python
def save_to_sheets(self, store_name, marketing_data, report_data, mall_info_data):
    """데이터 저장"""
    try:
        if not self.marketing_spreadsheet:
            self.connect_spreadsheet()

        try:
            ws = self.marketing_spreadsheet.worksheet(store_name)
        except:
            ws = self.marketing_spreadsheet.add_worksheet(store_name, 1000, 20)

        ws.clear()

        body = []
        if marketing_data:
            body.extend(marketing_data)
            body.append([])
            body.append([])

        if report_data:
            body.extend(report_data)
            body.append([])
            body.append([])

        if mall_info_data:
            body.extend(mall_info_data)

        if body:
            ws.update(values=body, range_name='A1')
            print(f"  -> 시트 저장 완료: {store_name}", flush=True)

    except Exception as e:
        print(f"구글 시트 저장 실패: {e}")
```

### 수정 후 코드
```python
def save_to_sheets(self, store_name, marketing_data, report_data, mall_info_data, channel_data=None):
    """데이터 저장 (data111.py와 동일한 레이아웃)"""
    try:
        if not self.marketing_spreadsheet:
            self.connect_spreadsheet()

        # 최대 행/열 계산
        max_rows = max(
            len(marketing_data) if marketing_data else 0,
            len(report_data) if report_data else 0,
            len(mall_info_data) if mall_info_data else 0,
            len(channel_data) if channel_data else 0
        )
        max_rows = max(max_rows + 100, 1000)
        max_cols = 35  # S열(19) + 전체채널(2열) + 여유

        try:
            ws = self.marketing_spreadsheet.worksheet(store_name)
            if ws.row_count < max_rows or ws.col_count < max_cols:
                ws.resize(rows=max_rows, cols=max_cols)
        except:
            ws = self.marketing_spreadsheet.add_worksheet(store_name, max_rows, max_cols)

        ws.clear()

        # 마케팅분석 데이터 (A~G열)
        if marketing_data and len(marketing_data) > 0:
            ws.update(values=marketing_data, range_name='A1')
            print(f"    -> 마케팅분석 {len(marketing_data)}개 행 저장 완료 (A~G열)")

        # 상품클릭리포트 (I열~)
        if report_data and len(report_data) > 0:
            ws.update(values=report_data, range_name='I1')
            print(f"    -> 상품클릭리포트 {len(report_data)}개 행 저장 완료 (I열~)")

        # 쇼핑몰 정보 (Q열~)
        if mall_info_data and len(mall_info_data) > 0:
            ws.update(values=mall_info_data, range_name='Q1')
            print(f"    -> 쇼핑몰 정보 {len(mall_info_data)}개 행 저장 완료 (Q열~)")

        # 전체채널 데이터 (S열~)
        if channel_data and len(channel_data) > 0:
            ws.update(values=channel_data, range_name='S1')
            print(f"    -> 전체채널 {len(channel_data)}개 행 저장 완료 (S열~)")

        print(f"  -> 시트 저장 완료: {store_name}", flush=True)

    except Exception as e:
        print(f"구글 시트 저장 실패: {e}")
```

---

## 최종 데이터 저장 레이아웃

| 열 범위 | 데이터 종류 | 컬럼 |
|---------|------------|------|
| A~G열 | 상품노출성과 | 상품명, 상품ID, 채널그룹, 채널명, 키워드, 평균노출순위, 유입수 |
| I~O열 | 상품클릭리포트 | 상품ID, 상품명, 노출수, 클릭수, 클릭율, 적용수수료, 클릭당수수료 |
| Q~R열 | 쇼핑몰정보 | 항목, 값 (ID/명/타입/등급/안읽은쪽지/받은쪽지/클린위반) |
| S~T열 | 전체채널 | 채널명, 유입수 |

---

## 체크리스트

- [ ] 쇼핑몰 등급 수집 추가
- [ ] 안읽은 쪽지 수집 추가
- [ ] 받은쪽지 수집 추가
- [ ] 클린위반 수집 추가
- [ ] `collect_channel_data()` 함수 추가
- [ ] `collect_multiple_accounts()` 수집 순서 수정 (전체채널 추가)
- [ ] `save_to_sheets()` 함수 수정 (channel_data 파라미터 추가, 열 위치 지정)
