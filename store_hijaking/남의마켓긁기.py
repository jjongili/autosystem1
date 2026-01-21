#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
스마트스토어 상품 수집기 v2.4
- undetected-chromedriver로 탐지 우회
- 시작 시 크롬창 표시 (로그인 가능)
- 옵션 데이터 수집 로직 개선
- 구글시트 연동 기능 추가

pip install undetected-chromedriver pandas openpyxl gspread google-auth
"""

import os
import sys
import json
import re
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
from datetime import datetime
from typing import Dict, List, Any, Tuple
import threading
import random
import string

# 스크립트 위치 기준 경로 설정
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    import pandas as pd
except ImportError:
    print("pip install pandas openpyxl")
    sys.exit(1)

try:
    import undetected_chromedriver as uc
except ImportError:
    print("pip install undetected-chromedriver")
    sys.exit(1)

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    print("구글시트 기능을 사용하려면: pip install gspread google-auth")
    GSPREAD_AVAILABLE = False


class GoogleSheetsManager:
    """구글 시트 관리 클래스"""

    SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

    # smartstore_copy_tool.py와 동일한 헤더 양식
    HEADERS = [
        "상품번호", "상품명", "판매가", "정상가", "재고수량",
        "카테고리ID", "카테고리명", "상품상태코드", "상품상태명",
        "대표이미지URL", "추가이미지URLs", "동영상URL", "상세설명HTML",
        "옵션사용여부", "옵션정보JSON", "배송방법", "배송비유형",
        "기본배송비", "반품배송비", "교환배송비",
        "A/S전화번호", "A/S안내", "원산지코드", "원산지명",
        "제조사", "브랜드", "모델명", "인증정보JSON",
        "속성정보JSON", "태그", "판매시작일", "판매종료일",
        "최소구매수량", "최대구매수량", "할인율", "할인가", "원본상품번호", "수집URL"
    ]

    def __init__(self, credentials_path: str):
        self.credentials_path = credentials_path
        self.client = None
        self._connect()

    def _connect(self):
        if not os.path.exists(self.credentials_path):
            raise FileNotFoundError(f"credentials.json 파일을 찾을 수 없습니다: {self.credentials_path}")
        creds = Credentials.from_service_account_file(self.credentials_path, scopes=self.SCOPES)
        self.client = gspread.authorize(creds)

    def get_or_create_sheet(self, spreadsheet_id: str, sheet_name: str):
        spreadsheet = self.client.open_by_key(spreadsheet_id)
        try:
            worksheet = spreadsheet.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(self.HEADERS))
        return worksheet

    def setup_headers(self, worksheet):
        existing = worksheet.row_values(1)
        if existing != self.HEADERS:
            worksheet.update('A1', [self.HEADERS])

    def clear_data(self, worksheet):
        worksheet.batch_clear(['A2:AL10000'])

    def append_products(self, worksheet, products: List[List[Any]]):
        if products:
            worksheet.append_rows(products, value_input_option='RAW')


class SmartStoreCollector:
    """스마트스토어 상품 수집기"""
    
    def __init__(self):
        self.driver = None
    
    def start_browser(self):
        """브라우저 시작"""
        if self.driver:
            return
        
        options = uc.ChromeOptions()
        options.add_argument('--window-size=1400,900')
        
        # undetected-chromedriver 사용
        self.driver = uc.Chrome(options=options)
        
        # 네이버 로그인 페이지로 이동
        self.driver.get("https://nid.naver.com/nidlogin.login")
    
    def close(self):
        """브라우저 종료"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
    
    def parse_url(self, url: str) -> Tuple[str, str]:
        pattern = r'smartstore\.naver\.com/([^/]+)/products/(\d+)'
        match = re.search(pattern, url)
        if match:
            return match.group(1), match.group(2)
        return '', ''

    def _is_valid_detail_html(self, html: str) -> bool:
        """정상적인 스마트에디터 상세설명인지 판별"""
        if not isinstance(html, str):
            return False
        if len(html) < 200:
            return False
        if '<div' not in html:
            return False
        if 'se-viewer' not in html:
            return False
        return True

    def _fix_lazy_images(self, html: str) -> str:
        """lazy-load 이미지 정리"""
        if not html:
            return html

        # data-src -> src
        html = re.sub(
            r'src="data:image[^"]*"\s*data-src="(https?://[^"]+)"',
            r'src="\1"',
            html
        )
        html = re.sub(
            r'data-src="(https?://[^"]+)"\s*src="data:image[^"]*"',
            r'src="\1"',
            html
        )
        html = re.sub(
            r'data-lazy-src="(https?://[^"]+)"',
            r'src="\1"',
            html
        )
        return html

    def collect_product(self, url: str) -> Dict[str, Any]:
        """상품 정보 수집"""
        store_name, product_no = self.parse_url(url)
        
        if not product_no:
            raise ValueError(f"유효하지 않은 URL: {url}")
        
        if self.driver is None:
            raise Exception("브라우저가 실행 중이 아닙니다.")
        
        # 상품 페이지로 이동
        self.driver.get(url)
        time.sleep(3)
        
        # 현재 URL 확인
        current_url = self.driver.current_url
        print(f"[DEBUG] 현재 URL: {current_url}")
        
        # __PRELOADED_STATE__ 추출
        try:
            data = self.driver.execute_script("return window.__PRELOADED_STATE__;")
            
            if data:
                print(f"[DEBUG] __PRELOADED_STATE__ 키: {list(data.keys())}")
                
                # productDetail 확인
                if 'productDetail' in data:
                    pd_keys = list(data['productDetail'].keys())
                    print(f"[DEBUG] productDetail 키: {pd_keys}")
                    
                    # 상품번호로 찾기
                    if product_no in data['productDetail']:
                        print(f"[DEBUG] 상품번호 {product_no} 찾음!")
                    else:
                        print(f"[DEBUG] 상품번호 {product_no} 없음, 다른 키 탐색")
                        for key in pd_keys:
                            val = data['productDetail'][key]
                            if isinstance(val, dict):
                                print(f"[DEBUG] 키 '{key}' 내부: {list(val.keys())[:10]}")
                
                return self._parse_to_excel_format(data, url, store_name, product_no)
            else:
                print("[DEBUG] __PRELOADED_STATE__ 없음!")
                
        except Exception as e:
            print(f"[DEBUG] JS 실행 오류: {e}")
        
        return self._extract_from_dom(url, store_name, product_no)
    
    def _extract_from_dom(self, url: str, store_name: str, product_no: str) -> Dict[str, Any]:
        """DOM에서 직접 추출 (개선된 버전)"""
        result = self._create_empty_row(url, store_name, product_no)

        try:
            from selenium.webdriver.common.by import By

            # 상품명 - 여러 선택자 시도
            name_selectors = [
                'h3.DCVBehA8ZB',  # 현재 구조
                'h3._copyable',
                '.product_title',
                'h3[class*="title"]',
                '.productName'
            ]
            for sel in name_selectors:
                try:
                    name_elem = self.driver.find_element(By.CSS_SELECTOR, sel)
                    if name_elem.text.strip():
                        result['상품명'] = name_elem.text.strip()
                        break
                except:
                    continue

            # 판매가 - 현재 구조
            price_selectors = [
                'strong.Xu9MEKUuIo span.e1DMQNBPJ_',  # 현재 구조
                'strong[class*="price"] span',
                '.sale_price',
                '._1LY7DqCnwR'
            ]
            for sel in price_selectors:
                try:
                    price_elem = self.driver.find_element(By.CSS_SELECTOR, sel)
                    price_text = price_elem.text.replace(',', '').replace('원', '')
                    price_num = int(re.sub(r'\D', '', price_text))
                    if price_num > 0:
                        result['판매가'] = price_num
                        break
                except:
                    continue

            # 등록가 (정가)
            orig_selectors = [
                'del.VaZJPclpdJ span.e1DMQNBPJ_',  # 현재 구조
                'del span',
                '.original_price'
            ]
            for sel in orig_selectors:
                try:
                    orig_elem = self.driver.find_element(By.CSS_SELECTOR, sel)
                    orig_text = orig_elem.text.replace(',', '').replace('원', '')
                    orig_num = int(re.sub(r'\D', '', orig_text))
                    if orig_num > 0:
                        result['등록가'] = orig_num
                        break
                except:
                    continue

            # 이미지
            images = []
            img_selectors = [
                'img.TgO1N1wWTm',  # 대표이미지
                'img.fxmqPhYp6y',  # 추가이미지
                '.product_thumb img'
            ]
            for sel in img_selectors:
                try:
                    img_elems = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    for img in img_elems:
                        src = img.get_attribute('src')
                        if src and 'shop-phinf.pstatic.net' in src:
                            # 고화질 이미지로 변환
                            clean_src = re.sub(r'\?type=.*', '', src)
                            if clean_src not in images:
                                images.append(clean_src)
                except:
                    continue
            if images:
                result['썸네일'] = str(images)

            # 배송비
            try:
                delivery_elem = self.driver.find_element(By.CSS_SELECTOR, '.Se0UVy4E71, .delivery_fee')
                if '무료' in delivery_elem.text:
                    result['배송비'] = 0
            except:
                pass

            result['판매자코드'] = ''.join(random.choices(string.ascii_letters + string.digits, k=21))

        except Exception as e:
            print(f"[DEBUG] DOM 추출 오류: {e}")

        return result
    
    def _parse_to_excel_format_v2(self, data: Dict, product: Dict, url: str, store_name: str, product_no: str) -> Dict[str, Any]:
        """상품 데이터를 엑셀 형식으로 변환 (simpleProductForDetailPage 구조 지원)"""
        if not product:
            return self._create_empty_row(url, store_name, product_no)

        result = self._create_empty_row(url, store_name, product_no)

        # 상품명
        result['상품명'] = product.get('name', product.get('dispName', product.get('productName', '')))
        result['판매상태'] = '판매중'

        # 가격 - benefitsView.discountedSalePrice 우선 (실제 판매가)
        benefits = product.get('benefitsView', {})
        if isinstance(benefits, dict) and benefits.get('discountedSalePrice'):
            result['판매가'] = benefits.get('discountedSalePrice', 0)
        else:
            result['판매가'] = product.get('salePrice', product.get('dispSalePrice', 0))

        # 등록가 (정가)
        result['등록가'] = product.get('salePrice', product.get('dispSalePrice', result['판매가']))

        # 재고수
        result['재고수'] = product.get('stockQuantity', 0)

        # 카테고리 - category.wholeCategoryName
        category = product.get('category', {})
        if isinstance(category, dict):
            result['카테고리'] = category.get('wholeCategoryName', category.get('categoryName', ''))
        elif isinstance(category, str):
            result['카테고리'] = category

        # 이미지 - representativeImageUrl, optionalImageUrls
        images = []

        # 대표 이미지
        rep_url = product.get('representativeImageUrl', '')
        if rep_url:
            images.append(rep_url)

        # 추가 이미지
        opt_urls = product.get('optionalImageUrls', [])
        if isinstance(opt_urls, list):
            images.extend(opt_urls)

        # 기존 구조도 지원 (channelProductImages, productImages)
        if not images:
            cpi = product.get('channelProductImages', {})
            if isinstance(cpi, dict):
                rep = cpi.get('representativeImage', {})
                if isinstance(rep, dict) and rep.get('url'):
                    images.append(rep['url'])
                opts = cpi.get('optionalImages', [])
                for img in opts:
                    if isinstance(img, dict) and img.get('url'):
                        images.append(img['url'])

        if not images:
            pi = product.get('productImages', {})
            if isinstance(pi, dict):
                rep = pi.get('representativeImage', {})
                if isinstance(rep, dict) and rep.get('url'):
                    images.append(rep['url'])
                opts = pi.get('optionalImages', [])
                for img in opts:
                    if isinstance(img, dict) and img.get('url'):
                        images.append(img['url'])

        result['썸네일'] = str(images) if images else ''

        # =========================
        # 상세설명 (se-viewer HTML만 허용)
        # =========================
        detail_html = ''

        # seViewerContent만 사용 (PRELOADED_STATE에서 가장 신뢰할 수 있는 소스)
        svc = data.get('seViewerContent', {})
        if isinstance(svc, dict):
            for _, val in svc.items():
                if self._is_valid_detail_html(val):
                    detail_html = self._fix_lazy_images(val)
                    break

        # product.detailContent / content 는 사용 금지
        # 옵션 텍스트 섞이는 주범이므로 완전 차단
        # 상세설명이 없으면 빈 값 유지 -> _collect_thread에서 DOM으로 추출

        result['상세설명'] = detail_html

        # ========== 옵션 수집 로직 개선 ==========
        option_combinations = product.get('optionCombinations', [])
        option_group_names = product.get('optionCombinationGroupNames', {})
        option_standards = product.get('optionStandards', [])
        option_usable = product.get('optionUsable', False)
        
        # 디버깅: 현재 product에서 옵션 확인
        print(f"[DEBUG] product에서 옵션 확인: combinations={len(option_combinations)}, groupNames={option_group_names}")

        # product에 옵션이 없으면 다른 위치 탐색
        if not option_combinations:
            # 1. simpleProductForDetailPage에서 다시 확인
            if 'simpleProductForDetailPage' in data:
                spd = data['simpleProductForDetailPage']
                if isinstance(spd, dict):
                    # A/B 키 확인
                    for key in ['A', 'B']:
                        if key in spd and isinstance(spd[key], dict):
                            spd_product = spd[key]
                            if spd_product.get('optionCombinations'):
                                option_combinations = spd_product.get('optionCombinations', [])
                                option_group_names = spd_product.get('optionCombinationGroupNames', option_group_names)
                                option_standards = spd_product.get('optionStandards', option_standards)
                                print(f"[DEBUG] simpleProductForDetailPage.{key}에서 옵션 발견: {len(option_combinations)}개")
                                break
                    
                    # 상품번호로 직접 찾기
                    if not option_combinations and product_no in spd:
                        spd_prod = spd[product_no]
                        if isinstance(spd_prod, dict):
                            # A/B 구조
                            for key in ['A', 'B']:
                                if key in spd_prod and isinstance(spd_prod[key], dict):
                                    if spd_prod[key].get('optionCombinations'):
                                        option_combinations = spd_prod[key].get('optionCombinations', [])
                                        option_group_names = spd_prod[key].get('optionCombinationGroupNames', option_group_names)
                                        option_standards = spd_prod[key].get('optionStandards', option_standards)
                                        print(f"[DEBUG] simpleProductForDetailPage[{product_no}].{key}에서 옵션 발견: {len(option_combinations)}개")
                                        break
                            # 직접
                            if not option_combinations and spd_prod.get('optionCombinations'):
                                option_combinations = spd_prod.get('optionCombinations', [])
                                option_group_names = spd_prod.get('optionCombinationGroupNames', option_group_names)
                                option_standards = spd_prod.get('optionStandards', option_standards)
                                print(f"[DEBUG] simpleProductForDetailPage[{product_no}]에서 옵션 발견: {len(option_combinations)}개")
            
            # 2. product 키에서 찾기
            if not option_combinations and 'product' in data:
                prod_data = data.get('product', {})
                if isinstance(prod_data, dict):
                    # A/B 키 확인
                    for key in ['A', 'B']:
                        if key in prod_data and isinstance(prod_data[key], dict):
                            prod_sub = prod_data[key]
                            if prod_sub.get('optionCombinations'):
                                option_combinations = prod_sub.get('optionCombinations', [])
                                option_group_names = prod_sub.get('optionCombinationGroupNames', option_group_names)
                                option_standards = prod_sub.get('optionStandards', option_standards)
                                print(f"[DEBUG] product.{key}에서 옵션 발견: {len(option_combinations)}개")
                                break
                    
                    # 상품번호로 찾기
                    if not option_combinations and product_no in prod_data:
                        prod_sub = prod_data[product_no]
                        if isinstance(prod_sub, dict):
                            for key in ['A', 'B']:
                                if key in prod_sub and isinstance(prod_sub[key], dict):
                                    if prod_sub[key].get('optionCombinations'):
                                        option_combinations = prod_sub[key].get('optionCombinations', [])
                                        option_group_names = prod_sub[key].get('optionCombinationGroupNames', option_group_names)
                                        option_standards = prod_sub[key].get('optionStandards', option_standards)
                                        print(f"[DEBUG] product[{product_no}].{key}에서 옵션 발견: {len(option_combinations)}개")
                                        break
                            if not option_combinations and prod_sub.get('optionCombinations'):
                                option_combinations = prod_sub.get('optionCombinations', [])
                                option_group_names = prod_sub.get('optionCombinationGroupNames', option_group_names)
                                option_standards = prod_sub.get('optionStandards', option_standards)
                                print(f"[DEBUG] product[{product_no}]에서 옵션 발견: {len(option_combinations)}개")
                    
                    # 직접 확인
                    if not option_combinations and prod_data.get('optionCombinations'):
                        option_combinations = prod_data.get('optionCombinations', [])
                        option_group_names = prod_data.get('optionCombinationGroupNames', option_group_names)
                        option_standards = prod_data.get('optionStandards', option_standards)
                        print(f"[DEBUG] product에서 직접 옵션 발견: {len(option_combinations)}개")
            
            # 3. productDetail에서 찾기
            if not option_combinations and 'productDetail' in data:
                pd_data = data.get('productDetail', {})
                if isinstance(pd_data, dict):
                    # 상품번호로 찾기
                    if product_no in pd_data:
                        pd_prod = pd_data[product_no]
                        if isinstance(pd_prod, dict) and pd_prod.get('optionCombinations'):
                            option_combinations = pd_prod.get('optionCombinations', [])
                            option_group_names = pd_prod.get('optionCombinationGroupNames', option_group_names)
                            option_standards = pd_prod.get('optionStandards', option_standards)
                            print(f"[DEBUG] productDetail[{product_no}]에서 옵션 발견: {len(option_combinations)}개")
                    
                    # 다른 키 탐색
                    if not option_combinations:
                        for key, val in pd_data.items():
                            if isinstance(val, dict) and val.get('optionCombinations'):
                                option_combinations = val.get('optionCombinations', [])
                                option_group_names = val.get('optionCombinationGroupNames', option_group_names)
                                option_standards = val.get('optionStandards', option_standards)
                                print(f"[DEBUG] productDetail.{key}에서 옵션 발견: {len(option_combinations)}개")
                                break
            
            # 4. 전체 data에서 optionCombinations 키 직접 탐색
            if not option_combinations:
                for key, val in data.items():
                    if isinstance(val, dict):
                        if val.get('optionCombinations'):
                            option_combinations = val.get('optionCombinations', [])
                            option_group_names = val.get('optionCombinationGroupNames', option_group_names)
                            option_standards = val.get('optionStandards', option_standards)
                            print(f"[DEBUG] data.{key}에서 옵션 발견: {len(option_combinations)}개")
                            break
                        # 중첩 구조
                        for subkey, subval in val.items():
                            if isinstance(subval, dict) and subval.get('optionCombinations'):
                                option_combinations = subval.get('optionCombinations', [])
                                option_group_names = subval.get('optionCombinationGroupNames', option_group_names)
                                option_standards = subval.get('optionStandards', option_standards)
                                print(f"[DEBUG] data.{key}.{subkey}에서 옵션 발견: {len(option_combinations)}개")
                                break
                        if option_combinations:
                            break

        option_info = {
            'simpleOptionSortType': 'CREATE',
            'optionSimple': [],
            'optionCustom': [],
            'optionCombinationSortType': product.get('optionCombinationSortType', 'CREATE'),
            'optionCombinationGroupNames': option_group_names,
            'optionCombinations': option_combinations,
            'standardOptionGroups': [],
            'optionStandards': option_standards,
            'useStockManagement': product.get('useStockManagement', True),
            'optionDeliveryAttributes': []
        }
        result['옵션상품'] = str(option_info)
        
        print(f"[DEBUG] 최종 옵션: {len(option_combinations)}개, 그룹명: {option_group_names}")
        # ========== 옵션 수집 로직 끝 ==========
        
        result['추가상품'] = '{}'

        # 태그 - seoInfo.sellerTags
        tags = []
        seo_info = product.get('seoInfo', {})
        if isinstance(seo_info, dict):
            tags = seo_info.get('sellerTags', [])
        if not tags:
            tags = product.get('tags', product.get('sellerTags', []))
        if tags:
            result['상품태그'] = str(tags)

        # 브랜드/제조사/모델명 - naverShoppingSearchInfo
        brand = ''
        manufacturer = ''
        model_name = '상세설명참조'

        naver_info = product.get('naverShoppingSearchInfo', {})
        if isinstance(naver_info, dict):
            brand = naver_info.get('brandName', '')
            manufacturer = naver_info.get('manufacturerName', '')
            model_name = naver_info.get('modelName', '상세설명참조')

        result['브랜드'] = brand
        result['제조사'] = manufacturer
        result['모델명'] = model_name

        # 원산지 - originAreaInfo (이 데이터에는 없지만 다른 상품에 있을 수 있음)
        origin = ''
        origin_info = product.get('originAreaInfo', {})
        if isinstance(origin_info, dict):
            origin = origin_info.get('content', origin_info.get('originAreaName', ''))
        elif isinstance(origin_info, str):
            origin = origin_info
        result['원산지'] = origin if origin else '상세설명에 표시'

        # 배송비 - productDeliveryInfo.baseFee
        delivery = product.get('productDeliveryInfo', product.get('deliveryInfo', {}))
        if isinstance(delivery, dict):
            result['배송비'] = delivery.get('baseFee', 0)
            # deliveryFeeType이 FREE면 0
            if delivery.get('deliveryFeeType') == 'FREE':
                result['배송비'] = 0

        result['판매자코드'] = ''.join(random.choices(string.ascii_letters + string.digits, k=21))

        return result

    def _parse_to_excel_format(self, data: Dict, url: str, store_name: str, product_no: str) -> Dict[str, Any]:
        """데이터를 엑셀 형식으로 변환 (기존 호환용)"""
        product = None

        if 'productDetail' in data:
            pd_data = data['productDetail']
            if product_no in pd_data:
                product = pd_data[product_no]
            else:
                for key, val in pd_data.items():
                    if isinstance(val, dict) and 'name' in val:
                        product = val
                        break

        if not product and 'product' in data:
            product = data['product']

        if not product:
            return self._create_empty_row(url, store_name, product_no)

        result = self._create_empty_row(url, store_name, product_no)
        
        result['상품명'] = product.get('name', '')
        result['판매상태'] = '판매중'
        result['판매가'] = product.get('salePrice', product.get('discountedSalePrice', 0))
        result['등록가'] = product.get('regularPrice', product.get('originalPrice', result['판매가']))
        result['재고수'] = product.get('stockQuantity', 0)
        
        category = product.get('category', {})
        if isinstance(category, dict):
            result['카테고리'] = category.get('wholeCategoryName', '')
        
        # 이미지
        images = []
        pi = product.get('productImages', {})
        if isinstance(pi, dict):
            rep = pi.get('representativeImage', {})
            if isinstance(rep, dict) and rep.get('url'):
                images.append(rep['url'])
            opts = pi.get('optionalImages', [])
            for img in opts:
                if isinstance(img, dict) and img.get('url'):
                    images.append(img['url'])
        result['썸네일'] = str(images) if images else ''

        # 상세설명 (se-viewer HTML만 허용)
        detail_html = ''
        svc = data.get('seViewerContent', {})
        if isinstance(svc, dict):
            for _, val in svc.items():
                if self._is_valid_detail_html(val):
                    detail_html = self._fix_lazy_images(val)
                    break
        # detailContent / content 사용 금지
        result['상세설명'] = detail_html

        # 옵션 - 개선된 로직 적용
        option_combinations = product.get('optionCombinations', [])
        option_group_names = product.get('optionCombinationGroupNames', {})
        option_standards = product.get('optionStandards', [])
        
        # product에 옵션이 없으면 다른 위치 탐색
        if not option_combinations:
            # simpleProductForDetailPage에서 찾기
            if 'simpleProductForDetailPage' in data:
                spd = data['simpleProductForDetailPage']
                if isinstance(spd, dict):
                    for key in ['A', 'B']:
                        if key in spd and isinstance(spd[key], dict):
                            if spd[key].get('optionCombinations'):
                                option_combinations = spd[key].get('optionCombinations', [])
                                option_group_names = spd[key].get('optionCombinationGroupNames', option_group_names)
                                option_standards = spd[key].get('optionStandards', option_standards)
                                print(f"[DEBUG] _parse_to_excel_format: simpleProductForDetailPage.{key}에서 옵션 발견: {len(option_combinations)}개")
                                break
        
        option_info = {
            'simpleOptionSortType': 'CREATE',
            'optionSimple': [],
            'optionCustom': [],
            'optionCombinationSortType': product.get('optionCombinationSortType', 'CREATE'),
            'optionCombinationGroupNames': option_group_names,
            'optionCombinations': option_combinations,
            'standardOptionGroups': [],
            'optionStandards': option_standards,
            'useStockManagement': product.get('useStockManagement', True),
            'optionDeliveryAttributes': []
        }
        result['옵션상품'] = str(option_info)
        result['추가상품'] = '{}'
        
        tags = product.get('tags', [])
        if tags:
            result['상품태그'] = str([{'text': t} if isinstance(t, str) else t for t in tags])
        
        naver_info = product.get('naverShoppingSearchInfo', {})
        if isinstance(naver_info, dict):
            result['브랜드'] = naver_info.get('brandName', '')
            result['제조사'] = naver_info.get('manufacturerName', '')
            result['모델명'] = naver_info.get('modelName', '상세설명참조')
        
        origin = product.get('originAreaInfo', {})
        if isinstance(origin, dict):
            result['원산지'] = origin.get('content', '상세설명에 표시')
        
        delivery = product.get('deliveryInfo', {})
        if isinstance(delivery, dict):
            fee = delivery.get('deliveryFee', {})
            if isinstance(fee, dict):
                result['배송비'] = fee.get('baseFee', 0)
        
        result['판매자코드'] = ''.join(random.choices(string.ascii_letters + string.digits, k=21))
        
        return result
    
    def _create_empty_row(self, url: str, store_name: str, product_no: str) -> Dict[str, Any]:
        return {
            'ID(수정금지)': 0,
            '등록날자': '',
            '수정날자': datetime.now().strftime('%Y-%m-%d'),
            '분류명': '전체선택',
            '수집URL': url,
            '상태': '등록준비',
            '상품코드': '',
            '처리결과': '',
            '배송코드': '',
            '판매자코드': '',
            '모델명': '상세설명참조',
            '상품명': '',
            '재고수': 0,
            '판매상태': '판매중',
            '등록가': 0,
            '판매가': 0,
            '추가판매가': 0,
            '원가': 0,
            '노출가': 0,
            '오픈마켓등록가': 0,
            '배송비': 0,
            '썸네일': '',
            '상세설명': '',
            '카테고리': '',
            '옵션상품': '{}',
            '추가상품': '{}',
            '상품속성': '',
            '상품태그': '',
            '브랜드': '',
            '제조사': '',
            '원산지': '상세설명에 표시',
            '주문코드': '',
            '제조일자': '',
            '인증': '',
            '비고': ''
        }

    def convert_to_gsheet_row(self, data: Dict[str, Any], url: str) -> List[Any]:
        """수집된 데이터를 구글시트 양식으로 변환"""
        # 구글시트 셀 최대 길이 (50000자 제한, 여유분 확보)
        MAX_CELL_LENGTH = 49000

        def truncate_text(text: str, max_length: int = MAX_CELL_LENGTH) -> str:
            if text and len(text) > max_length:
                return text[:max_length] + "...[잘림]"
            return text

        # 이미지 처리
        thumbnail = data.get('썸네일', '')
        main_image = ''
        additional_images = ''
        if thumbnail:
            try:
                images = eval(thumbnail) if isinstance(thumbnail, str) else thumbnail
                if isinstance(images, list) and len(images) > 0:
                    main_image = images[0]
                    if len(images) > 1:
                        additional_images = ','.join(images[1:])
            except:
                main_image = thumbnail

        # 옵션 정보 처리
        option_str = data.get('옵션상품', '{}')
        option_info = {}
        has_options = '미사용'
        try:
            option_info = eval(option_str) if isinstance(option_str, str) else option_str
            if option_info.get('optionCombinations'):
                has_options = '사용'
        except:
            pass

        # 태그 처리
        tags_str = data.get('상품태그', '')
        tags = ''
        if tags_str:
            try:
                tags_list = eval(tags_str) if isinstance(tags_str, str) else tags_str
                if isinstance(tags_list, list):
                    tags = ','.join([t.get('text', t) if isinstance(t, dict) else str(t) for t in tags_list])
            except:
                tags = tags_str

        # URL에서 상품번호 추출
        _, product_no = self.parse_url(url)

        return [
            product_no,  # 상품번호
            data.get('상품명', ''),  # 상품명
            data.get('판매가', 0),  # 판매가
            data.get('등록가', data.get('판매가', 0)),  # 정상가
            data.get('재고수', 0),  # 재고수량
            '',  # 카테고리ID
            data.get('카테고리', ''),  # 카테고리명
            'SALE',  # 상품상태코드
            '판매중',  # 상품상태명
            main_image,  # 대표이미지URL
            additional_images,  # 추가이미지URLs
            '',  # 동영상URL
            truncate_text(data.get('상세설명', '') or ''),  # 상세설명HTML
            has_options,  # 옵션사용여부
            truncate_text(json.dumps(option_info, ensure_ascii=False) if option_info else ''),  # 옵션정보JSON
            'DELIVERY',  # 배송방법
            'FREE' if data.get('배송비', 0) == 0 else 'PAID',  # 배송비유형
            data.get('배송비', 0),  # 기본배송비
            0,  # 반품배송비
            0,  # 교환배송비
            '',  # A/S전화번호
            '',  # A/S안내
            '',  # 원산지코드
            data.get('원산지', ''),  # 원산지명
            data.get('제조사', ''),  # 제조사
            data.get('브랜드', ''),  # 브랜드
            data.get('모델명', ''),  # 모델명
            '',  # 인증정보JSON
            '',  # 속성정보JSON
            tags,  # 태그
            '',  # 판매시작일
            '',  # 판매종료일
            1,  # 최소구매수량
            99,  # 최대구매수량
            0,  # 할인율
            0,  # 할인가
            product_no,  # 원본상품번호
            url  # 수집URL
        ]


class MainApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("스마트스토어 상품 수집기 v2.4 (구글시트 연동)")
        self.root.geometry("900x800")

        self.collector = SmartStoreCollector()
        self.collected_data = []
        self.collected_urls = []  # URL도 함께 저장

        # 구글시트 설정
        self.credentials_path = os.path.join(SCRIPT_DIR, "credentials.json")
        self.config_path = os.path.join(SCRIPT_DIR, "collector_config.json")

        self.init_ui()
        self.load_config()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 시작 시 바로 브라우저 실행
        self.root.after(500, self.start_browser)
    
    def init_ui(self):
        main = ttk.Frame(self.root, padding="10")
        main.pack(fill=tk.BOTH, expand=True)

        # 브라우저 상태
        status_frame = ttk.LabelFrame(main, text="브라우저 상태", padding="10")
        status_frame.pack(fill=tk.X, pady=(0, 10))

        self.browser_status = ttk.Label(status_frame, text="브라우저 시작 중...", foreground='orange', font=('', 10, 'bold'))
        self.browser_status.pack(side=tk.LEFT)

        self.restart_btn = ttk.Button(status_frame, text="브라우저 재시작", command=self.restart_browser)
        self.restart_btn.pack(side=tk.RIGHT)

        # URL 입력
        url_frame = ttk.LabelFrame(main, text="상품 URL 입력 (여러 개는 줄바꿈)", padding="10")
        url_frame.pack(fill=tk.X, pady=(0, 10))

        self.url_text = scrolledtext.ScrolledText(url_frame, height=4, font=('Consolas', 10))
        self.url_text.pack(fill=tk.X)
        self.url_text.insert(tk.END, "https://smartstore.naver.com/opalrin/products/12943483896")

        # 구글시트 설정
        gsheet_frame = ttk.LabelFrame(main, text="구글 시트 설정", padding="10")
        gsheet_frame.pack(fill=tk.X, pady=(0, 10))

        row1 = ttk.Frame(gsheet_frame)
        row1.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(row1, text="스프레드시트 ID:").pack(side=tk.LEFT)
        self.spreadsheet_id = ttk.Entry(row1, width=50)
        self.spreadsheet_id.pack(side=tk.LEFT, padx=(5, 15))
        # 사용자가 제공한 기본 ID
        self.spreadsheet_id.insert(0, "1777ejgWg1Wslm4nAXDnt3AJV9FnlzLhYhC5aTS7Fq6s")

        ttk.Label(row1, text="시트 이름:").pack(side=tk.LEFT)
        self.sheet_name = ttk.Entry(row1, width=15)
        self.sheet_name.pack(side=tk.LEFT, padx=(5, 0))
        self.sheet_name.insert(0, "수집상품")

        row2 = ttk.Frame(gsheet_frame)
        row2.pack(fill=tk.X)
        cred_status = "OK" if os.path.exists(self.credentials_path) else "없음"
        cred_color = 'green' if os.path.exists(self.credentials_path) else 'red'
        ttk.Label(row2, text=f"credentials.json: {cred_status}", foreground=cred_color).pack(side=tk.LEFT)
        ttk.Label(row2, text=f"  ({self.credentials_path})", foreground='gray').pack(side=tk.LEFT)

        # 버튼
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        self.collect_btn = ttk.Button(btn_frame, text="상품 수집", command=self.collect_products, width=12)
        self.collect_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.save_btn = ttk.Button(btn_frame, text="엑셀 저장", command=self.save_excel, state='disabled', width=12)
        self.save_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.gsheet_save_btn = ttk.Button(btn_frame, text="구글시트 저장", command=self.save_to_gsheet, state='disabled', width=14)
        self.gsheet_save_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.clear_btn = ttk.Button(btn_frame, text="초기화", command=self.clear_data, width=10)
        self.clear_btn.pack(side=tk.LEFT)

        self.count_label = ttk.Label(btn_frame, text="수집: 0개", foreground='blue', font=('', 10, 'bold'))
        self.count_label.pack(side=tk.RIGHT)
        
        # 진행
        progress_frame = ttk.LabelFrame(main, text="진행 상태", padding="10")
        progress_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))

        self.log_text = scrolledtext.ScrolledText(progress_frame, height=14, state='disabled', font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 안내
        help_text = """사용법: 크롬창에서 네이버 로그인 -> URL 입력 -> 상품 수집 -> 엑셀/구글시트 저장"""
        ttk.Label(main, text=help_text, foreground='gray').pack(anchor='w')

    def load_config(self):
        """저장된 설정 불러오기"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                if config.get('spreadsheet_id'):
                    self.spreadsheet_id.delete(0, tk.END)
                    self.spreadsheet_id.insert(0, config['spreadsheet_id'])
                if config.get('sheet_name'):
                    self.sheet_name.delete(0, tk.END)
                    self.sheet_name.insert(0, config['sheet_name'])
                self.log("[설정] 저장된 설정을 불러왔습니다.")
            except Exception as e:
                self.log(f"[경고] 설정 불러오기 실패: {e}")

    def save_config(self):
        """현재 설정 저장"""
        config = {
            'spreadsheet_id': self.spreadsheet_id.get().strip(),
            'sheet_name': self.sheet_name.get().strip()
        }
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"설정 저장 실패: {e}")
    
    def log(self, msg):
        self.log_text.config(state='normal')
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')
        self.root.update_idletasks()
    
    def start_browser(self):
        """브라우저 시작"""
        def _start():
            try:
                self.log("🌐 브라우저 시작 중... (잠시 기다려주세요)")
                self.collector.start_browser()
                self.root.after(0, lambda: self.browser_status.config(text="✅ 브라우저 실행 중 - 로그인 후 수집하세요", foreground='green'))
                self.log("✅ 브라우저 시작 완료! 네이버 로그인 페이지가 열렸습니다.")
                self.log("👉 로그인 완료 후 '상품 수집' 버튼을 클릭하세요.")
            except Exception as e:
                self.root.after(0, lambda: self.browser_status.config(text=f"❌ 오류", foreground='red'))
                self.log(f"❌ 브라우저 시작 실패: {e}")
        
        threading.Thread(target=_start, daemon=True).start()
    
    def restart_browser(self):
        """브라우저 재시작"""
        self.browser_status.config(text="⏳ 재시작 중...", foreground='orange')
        
        def _restart():
            self.collector.close()
            time.sleep(1)
            self.start_browser()
        
        threading.Thread(target=_restart, daemon=True).start()
    
    def get_urls(self) -> List[str]:
        text = self.url_text.get('1.0', tk.END)
        urls = []
        for line in text.strip().split('\n'):
            line = line.strip()
            if line and 'smartstore.naver.com' in line and '/products/' in line:
                urls.append(line)
        return urls
    
    def update_count(self):
        self.count_label.config(text=f"수집: {len(self.collected_data)}개")
        state = 'normal' if self.collected_data else 'disabled'
        self.save_btn.config(state=state)
        self.gsheet_save_btn.config(state=state if GSPREAD_AVAILABLE else 'disabled')
    
    def collect_products(self):
        urls = self.get_urls()
        if not urls:
            messagebox.showwarning("알림", "URL을 입력하세요.")
            return
        
        if self.collector.driver is None:
            messagebox.showwarning("알림", "브라우저가 실행 중이 아닙니다.\n'브라우저 재시작' 버튼을 클릭하세요.")
            return
        
        threading.Thread(target=self._collect_thread, args=(urls,), daemon=True).start()
    
    def _collect_thread(self, urls: List[str]):
        try:
            self.collect_btn.config(state='disabled')
            self.log(f"🔄 {len(urls)}개 상품 수집 시작...")
            
            self.progress_bar['maximum'] = len(urls)
            success = 0
            fail = 0
            start_id = len(self.collected_data) + 1
            
            for i, url in enumerate(urls):
                try:
                    self.log(f"📦 [{i+1}/{len(urls)}] 수집 중...")
                    
                    # URL 파싱
                    store_name, product_no = self.collector.parse_url(url)
                    self.log(f"  🔍 스토어: {store_name}, 상품번호: {product_no}")
                    
                    # 페이지 이동
                    self.collector.driver.get(url)
                    time.sleep(3)
                    
                    # 현재 URL 확인
                    current_url = self.collector.driver.current_url
                    self.log(f"  🌐 현재URL: {current_url[:60]}...")
                    
                    # __PRELOADED_STATE__ 추출
                    data = self.collector.driver.execute_script("return window.__PRELOADED_STATE__;")
                    
                    if data:
                        all_keys = list(data.keys())
                        self.log(f"  📋 전체 키: {all_keys}")

                        # 상품 데이터 찾기 - 여러 가능한 위치 탐색
                        product = None

                        # 1. simpleProductForDetailPage 우선 확인 (실제 데이터가 여기에 있음)
                        if 'simpleProductForDetailPage' in data:
                            spd = data['simpleProductForDetailPage']
                            if isinstance(spd, dict):
                                # A/B 테스트 구조 확인
                                if 'A' in spd and isinstance(spd['A'], dict) and spd['A'].get('name'):
                                    product = spd['A']
                                    self.log(f"  ✅ simpleProductForDetailPage.A에서 찾음")
                                elif 'B' in spd and isinstance(spd['B'], dict) and spd['B'].get('name'):
                                    product = spd['B']
                                    self.log(f"  ✅ simpleProductForDetailPage.B에서 찾음")
                                elif spd.get('name'):
                                    product = spd
                                    self.log(f"  ✅ simpleProductForDetailPage에서 직접 찾음")

                        # 2. productDetail 확인 (기존 방식)
                        if not product and 'productDetail' in data:
                            pd_data = data['productDetail']
                            pd_keys = list(pd_data.keys())
                            self.log(f"  📋 productDetail 키: {pd_keys[:5]}")

                            if product_no in pd_data:
                                candidate = pd_data[product_no]
                                if isinstance(candidate, dict) and candidate.get('name'):
                                    product = candidate
                                    self.log(f"  ✅ productDetail에서 상품번호로 찾음")
                            if not product:
                                for key, val in pd_data.items():
                                    if isinstance(val, dict) and val.get('name'):
                                        product = val
                                        self.log(f"  ✅ productDetail에서 name 필드로 찾음")
                                        break

                        # 3. product 키 확인 (name이 실제 값이 있는지 확인)
                        if not product and 'product' in data:
                            prod_data = data['product']
                            prod_keys = list(prod_data.keys())[:20] if isinstance(prod_data, dict) else []
                            self.log(f"  🔍 product 키 내부: {prod_keys}")

                            if isinstance(prod_data, dict):
                                # 상품번호로 직접 찾기
                                if product_no in prod_data:
                                    candidate = prod_data[product_no]
                                    candidate_keys = list(candidate.keys())[:15] if isinstance(candidate, dict) else []
                                    self.log(f"  🔍 product[{product_no}] 내부: {candidate_keys}")

                                    if isinstance(candidate, dict):
                                        # A/B 테스트 구조 확인 (name이 실제 값이 있는지 확인)
                                        if 'A' in candidate and isinstance(candidate['A'], dict) and candidate['A'].get('name'):
                                            product = candidate['A']
                                            self.log(f"  ✅ product[{product_no}].A에서 찾음")
                                        elif 'B' in candidate and isinstance(candidate['B'], dict) and candidate['B'].get('name'):
                                            product = candidate['B']
                                            self.log(f"  ✅ product[{product_no}].B에서 찾음")
                                        elif candidate.get('name'):
                                            product = candidate
                                            self.log(f"  ✅ product[{product_no}]에서 찾음")

                                # name 필드로 직접 찾기 (값이 있는지 확인)
                                if not product and prod_data.get('name'):
                                    product = prod_data
                                    self.log(f"  ✅ product 키에서 직접 찾음")

                                # 중첩 구조 탐색
                                if not product:
                                    for key, val in prod_data.items():
                                        if isinstance(val, dict):
                                            # A/B 테스트 구조 (name 값 확인)
                                            if 'A' in val and isinstance(val['A'], dict) and val['A'].get('name'):
                                                product = val['A']
                                                self.log(f"  ✅ product.{key}.A에서 찾음")
                                                break
                                            if val.get('name'):
                                                product = val
                                                self.log(f"  ✅ product.{key}에서 찾음")
                                                break

                        # 4. simpleProductForDetailPage 재확인 (앞서 못 찾은 경우 다른 구조 시도)
                        if not product and 'simpleProductForDetailPage' in data:
                            spd = data['simpleProductForDetailPage']
                            spd_keys = list(spd.keys())[:15] if isinstance(spd, dict) else []
                            self.log(f"  🔍 simpleProductForDetailPage 키 내부: {spd_keys}")
                            if isinstance(spd, dict):
                                if product_no in spd:
                                    candidate = spd[product_no]
                                    if isinstance(candidate, dict):
                                        # A/B 테스트 구조 확인
                                        if 'A' in candidate and isinstance(candidate['A'], dict):
                                            product = candidate['A']
                                            self.log(f"  ✅ simpleProductForDetailPage[{product_no}].A에서 찾음")
                                        elif 'B' in candidate and isinstance(candidate['B'], dict):
                                            product = candidate['B']
                                            self.log(f"  ✅ simpleProductForDetailPage[{product_no}].B에서 찾음")
                                        elif 'name' in candidate:
                                            product = candidate
                                            self.log(f"  ✅ simpleProductForDetailPage[{product_no}]에서 찾음")
                                        else:
                                            # 다른 중첩 구조 탐색
                                            self.log(f"  🔍 simpleProductForDetailPage[{product_no}] 내부: {list(candidate.keys())[:10]}")
                                            for subkey, subval in candidate.items():
                                                if isinstance(subval, dict) and 'name' in subval:
                                                    product = subval
                                                    self.log(f"  ✅ simpleProductForDetailPage[{product_no}].{subkey}에서 찾음")
                                                    break
                                elif 'name' in spd:
                                    product = spd
                                    self.log(f"  ✅ simpleProductForDetailPage에서 직접 찾음")
                                else:
                                    for key, val in spd.items():
                                        if isinstance(val, dict):
                                            # A/B 테스트 구조
                                            if 'A' in val and isinstance(val['A'], dict) and 'name' in val['A']:
                                                product = val['A']
                                                self.log(f"  ✅ simpleProductForDetailPage.{key}.A에서 찾음")
                                                break
                                            if 'name' in val:
                                                product = val
                                                self.log(f"  ✅ simpleProductForDetailPage.{key}에서 찾음")
                                                break

                        # 4. 다른 가능한 키들 탐색
                        possible_keys = ['item', 'productInfo', 'goods', 'productData', 'currentProduct', 'productSimpleView']
                        for pk in possible_keys:
                            if not product and pk in data:
                                candidate = data[pk]
                                self.log(f"  🔍 {pk} 키 내부: {list(candidate.keys())[:10] if isinstance(candidate, dict) else type(candidate)}")
                                if isinstance(candidate, dict):
                                    if product_no in candidate:
                                        product = candidate[product_no]
                                        self.log(f"  ✅ {pk}[{product_no}]에서 찾음")
                                        break
                                    elif 'name' in candidate:
                                        product = candidate
                                        self.log(f"  ✅ {pk} 키에서 찾음")
                                        break
                                    else:
                                        for subkey, subval in candidate.items():
                                            if isinstance(subval, dict) and 'name' in subval:
                                                product = subval
                                                self.log(f"  ✅ {pk}.{subkey}에서 찾음")
                                                break
                                        if product:
                                            break

                        # 4. 모든 키 순회하며 상품 데이터 찾기
                        if not product:
                            for key, val in data.items():
                                if isinstance(val, dict):
                                    # name과 salePrice 둘 다 있으면 상품 데이터로 추정
                                    if 'name' in val and ('salePrice' in val or 'price' in val):
                                        product = val
                                        self.log(f"  ✅ {key} 키에서 상품 구조 발견")
                                        break
                                    # 중첩된 구조 확인
                                    for subkey, subval in val.items():
                                        if isinstance(subval, dict) and 'name' in subval and ('salePrice' in subval or 'price' in subval):
                                            product = subval
                                            self.log(f"  ✅ {key}.{subkey}에서 상품 구조 발견")
                                            break
                                    if product:
                                        break

                        # 5. 디버깅: 각 키의 내용 일부 출력
                        if not product:
                            self.log(f"  🔍 상품 데이터 탐색 중...")
                            for key in all_keys:
                                val = data[key]
                                if isinstance(val, dict):
                                    sub_keys = list(val.keys())[:8]
                                    self.log(f"    {key}: {sub_keys}")

                        if product:
                            # 상품 데이터 구조 확인
                            if isinstance(product, dict):
                                prod_keys = list(product.keys())
                                self.log(f"  🔍 상품 데이터 키(전체): {prod_keys}")

                                # 주요 필드 존재 여부 확인
                                has_name = 'name' in product
                                has_options = 'optionCombinations' in product
                                has_detail = 'detailContent' in product or 'content' in product
                                has_category = 'category' in product
                                self.log(f"  📊 필드 확인: name={has_name}, options={has_options}, detail={has_detail}, category={has_category}")

                                # 옵션 관련 키 상세 출력
                                option_keys = [k for k in prod_keys if 'option' in k.lower()]
                                if option_keys:
                                    self.log(f"  🎯 옵션 관련 키: {option_keys}")
                                    for ok in option_keys:
                                        ov = product.get(ok)
                                        if isinstance(ov, list):
                                            self.log(f"    {ok}: 리스트({len(ov)}개)")
                                            if ov and len(ov) > 0:
                                                self.log(f"      첫번째 항목: {list(ov[0].keys()) if isinstance(ov[0], dict) else ov[0]}")
                                        elif isinstance(ov, dict):
                                            self.log(f"    {ok}: {list(ov.keys())[:5]}")
                                        else:
                                            self.log(f"    {ok}: {type(ov).__name__}")

                            name = product.get('name', product.get('productName', product.get('productTitle', 'N/A')))
                            self.log(f"  📦 상품명: {name[:30] if name and name != 'N/A' else 'N/A'}")

                            # name이 없으면 다른 구조 탐색
                            if not name or name == 'N/A':
                                self.log(f"  🔍 상품명 없음, 구조 탐색 중...")
                                # A/B 테스트 키나 다른 중첩 구조 확인
                                for pk, pv in product.items() if isinstance(product, dict) else []:
                                    if isinstance(pv, dict) and 'name' in pv:
                                        product = pv
                                        name = pv.get('name', 'N/A')
                                        self.log(f"  ✅ product.{pk}에서 상품명 발견: {name[:30]}")
                                        break

                            # product에 필수 필드가 없으면 simpleProductForDetailPage 재확인
                            if (not name or name == 'N/A') and 'simpleProductForDetailPage' in data:
                                spd = data['simpleProductForDetailPage']
                                if isinstance(spd, dict) and product_no in spd:
                                    candidate = spd[product_no]
                                    if isinstance(candidate, dict):
                                        # A/B 테스트 구조
                                        if 'A' in candidate and isinstance(candidate['A'], dict):
                                            product = candidate['A']
                                            name = product.get('name', 'N/A')
                                            self.log(f"  ✅ simpleProductForDetailPage[{product_no}].A에서 재탐색 성공: {name[:30] if name else 'N/A'}")
                                        elif 'name' in candidate:
                                            product = candidate
                                            name = candidate.get('name', 'N/A')
                                            self.log(f"  ✅ simpleProductForDetailPage[{product_no}]에서 재탐색 성공: {name[:30] if name else 'N/A'}")

                            result = self.collector._parse_to_excel_format_v2(data, product, url, store_name, product_no)

                            # 상세설명 HTML이 없거나 se-viewer가 아니면 DOM에서 강제 재추출
                            if not result.get('상세설명') or 'se-viewer' not in result.get('상세설명'):
                                try:
                                    # 스크롤해서 lazy-load 이미지 로딩
                                    self.collector.driver.execute_script(
                                        "window.scrollTo(0, document.body.scrollHeight);"
                                    )
                                    time.sleep(0.5)

                                    # DOM에서 상세설명 추출 (여러 선택자 시도)
                                    detail_html = self.collector.driver.execute_script("""
                                        // 1. se-viewer (스마트에디터)
                                        var viewer = document.querySelector('.se-viewer');
                                        if (viewer) {
                                            var clone = viewer.cloneNode(true);
                                            var imgs = clone.querySelectorAll('img[data-src], img[data-lazy-src]');
                                            imgs.forEach(img => {
                                                var src = img.getAttribute('data-src') || img.getAttribute('data-lazy-src');
                                                if (src && src.startsWith('http')) {
                                                    img.setAttribute('src', src);
                                                }
                                            });
                                            return clone.outerHTML;
                                        }

                                        // 2. 상세설명 영역 (다른 클래스들)
                                        var selectors = [
                                            '._3Lkew7jnxH',
                                            '.product_detail_area',
                                            '#INTRODUCE',
                                            '.detail_content',
                                            '[class*="detail"]'
                                        ];

                                        for (var sel of selectors) {
                                            var elem = document.querySelector(sel);
                                            if (elem && elem.innerHTML.length > 500) {
                                                return elem.outerHTML;
                                            }
                                        }

                                        return '';
                                    """)

                                    if detail_html and len(detail_html) > 200:
                                        result['상세설명'] = self.collector._fix_lazy_images(detail_html)
                                        self.log(f"  [상세] DOM 추출 성공 ({len(detail_html)}자)")
                                    else:
                                        # seViewerContent 디버깅
                                        svc = data.get('seViewerContent', {})
                                        self.log(f"  [디버그] seViewerContent 타입: {type(svc).__name__}, 키: {list(svc.keys()) if isinstance(svc, dict) else 'N/A'}")

                                        # detailContents에서 시도
                                        detail_contents = product.get('detailContents', {})
                                        if isinstance(detail_contents, dict):
                                            detail_text = detail_contents.get('detailContentText', '')
                                            if detail_text and '<' in detail_text and len(detail_text) > 200:
                                                result['상세설명'] = self.collector._fix_lazy_images(detail_text)
                                                self.log(f"  [상세] detailContents에서 추출 ({len(detail_text)}자)")
                                            else:
                                                result['상세설명'] = ''
                                                self.log(f"  [경고] 상세설명 없음")
                                        else:
                                            result['상세설명'] = ''
                                            self.log(f"  [경고] 상세설명 없음")
                                except Exception as e:
                                    self.log(f"  [경고] DOM 추출 실패: {e}")
                                    result['상세설명'] = ''

                            if result.get('상품명'):
                                result['ID(수정금지)'] = start_id + success
                                self.collected_data.append(result)

                                opt_count = 0
                                try:
                                    opt_data = eval(result.get('옵션상품', '{}'))
                                    opt_count = len(opt_data.get('optionCombinations', []))
                                except:
                                    pass

                                self.log(f"  ✅ {result['상품명'][:35]} | {result.get('판매가',0):,}원 | 옵션 {opt_count}개")
                                success += 1
                            else:
                                # JS 파싱 실패 시 DOM 추출 시도
                                self.log(f"  🔄 JS 파싱 실패, DOM 추출 시도...")
                                result = self.collector._extract_from_dom(url, store_name, product_no)
                                if result.get('상품명'):
                                    result['ID(수정금지)'] = start_id + success
                                    self.collected_data.append(result)
                                    self.log(f"  ✅ [DOM] {result['상품명'][:35]} | {result.get('판매가',0):,}원")
                                    success += 1
                                else:
                                    self.log(f"  ⚠️ 파싱 실패")
                                    fail += 1
                        else:
                            # product 못 찾음 - DOM 추출 시도
                            self.log(f"  🔄 상품 데이터 못 찾음, DOM 추출 시도...")
                            result = self.collector._extract_from_dom(url, store_name, product_no)
                            if result.get('상품명'):
                                result['ID(수정금지)'] = start_id + success
                                self.collected_data.append(result)
                                self.log(f"  ✅ [DOM] {result['상품명'][:35]} | {result.get('판매가',0):,}원")
                                success += 1
                            else:
                                self.log(f"  ⚠️ 상품 데이터를 찾을 수 없음")
                                fail += 1
                    else:
                        # __PRELOADED_STATE__ 없음 - DOM 추출 시도
                        self.log(f"  🔄 __PRELOADED_STATE__ 없음, DOM 추출 시도...")
                        result = self.collector._extract_from_dom(url, store_name, product_no)
                        if result.get('상품명'):
                            result['ID(수정금지)'] = start_id + success
                            self.collected_data.append(result)
                            self.log(f"  ✅ [DOM] {result['상품명'][:35]} | {result.get('판매가',0):,}원")
                            success += 1
                        else:
                            self.log(f"  ⚠️ __PRELOADED_STATE__ 없음, DOM 추출도 실패")
                            fail += 1

                except Exception as e:
                    self.log(f"  ❌ 오류: {str(e)}")
                    fail += 1
                
                self.progress_bar['value'] = i + 1
                self.root.after(0, self.update_count)
                
                if i < len(urls) - 1:
                    time.sleep(2)
            
            self.log(f"\n✅ 완료! 성공: {success}개, 실패: {fail}개")
            self.root.after(0, lambda: messagebox.showinfo("완료", f"성공: {success}개\n실패: {fail}개"))
            
        except Exception as e:
            self.log(f"❌ 오류: {e}")
        finally:
            self.collect_btn.config(state='normal')
            self.progress_bar['value'] = 0
            self.root.after(0, self.update_count)
    
    def save_excel(self):
        if not self.collected_data:
            messagebox.showwarning("알림", "저장할 데이터가 없습니다.")
            return
        
        timestamp = datetime.now().strftime('%Y%m%d%H%M')
        filepath = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=f"Excel_save_{timestamp}.xlsx"
        )
        
        if not filepath:
            return
        
        try:
            df = pd.DataFrame(self.collected_data)
            columns = [
                'ID(수정금지)', '등록날자', '수정날자', '분류명', '수집URL', '상태',
                '상품코드', '처리결과', '배송코드', '판매자코드', '모델명', '상품명',
                '재고수', '판매상태', '등록가', '판매가', '추가판매가', '원가',
                '노출가', '오픈마켓등록가', '배송비', '썸네일', '상세설명', '카테고리',
                '옵션상품', '추가상품', '상품속성', '상품태그', '브랜드', '제조사',
                '원산지', '주문코드', '제조일자', '인증', '비고'
            ]
            df = df[[c for c in columns if c in df.columns]]
            df.to_excel(filepath, index=False, engine='openpyxl')
            
            self.log(f"💾 저장 완료: {filepath}")
            messagebox.showinfo("완료", f"저장되었습니다.\n{filepath}")
        except Exception as e:
            messagebox.showerror("오류", str(e))
    
    def clear_data(self):
        if self.collected_data and messagebox.askyesno("확인", "초기화하시겠습니까?"):
            self.collected_data = []
            self.collected_urls = []
            self.update_count()
            self.log("[초기화] 완료")

    def save_to_gsheet(self):
        """수집된 데이터를 구글시트에 저장"""
        if not GSPREAD_AVAILABLE:
            messagebox.showerror("오류", "gspread 라이브러리가 설치되지 않았습니다.\npip install gspread google-auth")
            return

        if not self.collected_data:
            messagebox.showwarning("알림", "저장할 데이터가 없습니다.")
            return

        spreadsheet_id = self.spreadsheet_id.get().strip()
        sheet_name = self.sheet_name.get().strip()

        if not spreadsheet_id:
            messagebox.showwarning("입력 오류", "스프레드시트 ID를 입력하세요.")
            return
        if not sheet_name:
            messagebox.showwarning("입력 오류", "시트 이름을 입력하세요.")
            return

        threading.Thread(target=self._save_gsheet_thread, args=(spreadsheet_id, sheet_name), daemon=True).start()

    def _save_gsheet_thread(self, spreadsheet_id: str, sheet_name: str):
        """구글시트 저장 쓰레드"""
        try:
            self.gsheet_save_btn.config(state='disabled')
            self.log("[구글시트] 연결 중...")

            manager = GoogleSheetsManager(self.credentials_path)
            worksheet = manager.get_or_create_sheet(spreadsheet_id, sheet_name)
            manager.setup_headers(worksheet)

            self.log("[구글시트] 데이터 변환 중...")

            # 수집된 데이터를 구글시트 양식으로 변환
            sheet_data = []
            for data in self.collected_data:
                url = data.get('수집URL', '')
                row = self.collector.convert_to_gsheet_row(data, url)
                sheet_data.append(row)

            self.log(f"[구글시트] {len(sheet_data)}개 상품 저장 중...")

            # 기존 데이터 삭제 후 새로 추가
            manager.clear_data(worksheet)
            manager.append_products(worksheet, sheet_data)

            self.log(f"[완료] {len(sheet_data)}개 상품이 구글시트에 저장되었습니다.")
            self.root.after(0, lambda: messagebox.showinfo("완료", f"{len(sheet_data)}개 상품이 구글시트에 저장되었습니다.\n\nhttps://docs.google.com/spreadsheets/d/{spreadsheet_id}"))

        except FileNotFoundError as e:
            self.log(f"[오류] credentials.json 파일을 찾을 수 없습니다.")
            self.root.after(0, lambda: messagebox.showerror("오류", str(e)))
        except Exception as e:
            self.log(f"[오류] {str(e)}")
            self.root.after(0, lambda: messagebox.showerror("오류", str(e)))
        finally:
            self.root.after(0, lambda: self.gsheet_save_btn.config(state='normal' if self.collected_data else 'disabled'))

    def on_closing(self):
        self.save_config()
        self.collector.close()
        self.root.destroy()
    
    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = MainApp()
    app.run()