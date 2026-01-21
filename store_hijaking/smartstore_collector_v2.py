#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
스마트스토어 상품 수집기 v2.2
- undetected-chromedriver로 탐지 우회
- 시작 시 크롬창 표시 (로그인 가능)

pip install undetected-chromedriver pandas openpyxl
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
    
    def fetch_product_api(self, channel_uid: str, product_no: str) -> Dict:
        """상품 API 호출하여 전체 데이터 가져오기"""
        try:
            api_url = f"https://smartstore.naver.com/i/v2/channels/{channel_uid}/products/{product_no}?withWindow=false"
            result = self.driver.execute_script(f"""
                return fetch("{api_url}", {{
                    method: 'GET',
                    headers: {{'Accept': 'application/json'}}
                }})
                .then(response => response.json())
                .catch(error => null);
            """)
            # Promise 결과 대기
            time.sleep(1)
            result = self.driver.execute_async_script(f"""
                var callback = arguments[arguments.length - 1];
                fetch("{api_url}", {{
                    method: 'GET',
                    headers: {{'Accept': 'application/json'}}
                }})
                .then(response => response.json())
                .then(data => callback(data))
                .catch(error => callback(null));
            """)
            return result if result else {}
        except Exception as e:
            print(f"[DEBUG] API 호출 오류: {e}")
            return {}

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

        # 상세설명 - DOM에서 가져오거나, seViewerContent에서 가져옴
        # 우선 data에서 seViewerContent 확인
        detail_html = ''
        if 'seViewerContent' in data:
            svc = data['seViewerContent']
            if isinstance(svc, dict):
                # 상품번호로 찾거나 첫 번째 HTML 찾기
                for key, val in svc.items():
                    if isinstance(val, str) and 'se-viewer' in val:
                        detail_html = val
                        break

        # seViewerContent에 없으면 detailContents 사용
        if not detail_html:
            detail_contents = product.get('detailContents', {})
            if isinstance(detail_contents, dict):
                detail_html = detail_contents.get('detailContentText', '')

        if not detail_html:
            detail_html = product.get('detailContent', product.get('content', ''))

        # lazy-load 이미지 정리: base64 src를 data-src의 실제 URL로 교체
        if detail_html:
            detail_html = re.sub(
                r'src="data:image[^"]*"\s*data-src="(https?://[^"]+)"',
                r'src="\1"',
                detail_html
            )
            detail_html = re.sub(
                r'data-src="(https?://[^"]+)"\s*src="data:image[^"]*"',
                r'src="\1"',
                detail_html
            )

        result['상세설명'] = detail_html

        # 옵션 - API 데이터에서 가져오기
        option_combinations = product.get('optionCombinations', [])
        option_standards = product.get('optionStandards', [])
        option_usable = product.get('optionUsable', False)

        # 옵션 그룹명 추출 (API의 options 배열에서)
        option_group_names = {}
        options_list = product.get('options', [])
        if isinstance(options_list, list):
            for idx, opt in enumerate(options_list):
                if isinstance(opt, dict) and opt.get('groupName'):
                    option_group_names[f'optionGroupName{idx+1}'] = opt.get('groupName')

        # optionCombinations 정리 (필요한 필드만)
        cleaned_combinations = []
        for combo in option_combinations:
            if isinstance(combo, dict):
                cleaned_combo = {
                    'optionName1': combo.get('optionName1', ''),
                    'optionName2': combo.get('optionName2', ''),
                    'optionName3': combo.get('optionName3', ''),
                    'stockQuantity': combo.get('stockQuantity', 0),
                    'price': combo.get('price', 0),
                    'sellerManagerCode': combo.get('sellerManagerCode', ''),
                    'usable': True
                }
                cleaned_combinations.append(cleaned_combo)

        option_info = {
            'simpleOptionSortType': 'CREATE',
            'optionSimple': [],
            'optionCustom': [],
            'optionCombinationSortType': product.get('optionCombinationSortType', 'CREATE'),
            'optionCombinationGroupNames': option_group_names,
            'optionCombinations': cleaned_combinations if cleaned_combinations else option_combinations,
            'standardOptionGroups': [],
            'optionStandards': option_standards,
            'useStockManagement': product.get('useStockManagement', True),
            'optionDeliveryAttributes': []
        }
        result['옵션상품'] = str(option_info)
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
        
        result['상세설명'] = product.get('detailContent', '')
        
        # 옵션
        option_info = {
            'simpleOptionSortType': 'CREATE',
            'optionSimple': [],
            'optionCustom': [],
            'optionCombinationSortType': product.get('optionCombinationSortType', 'CREATE'),
            'optionCombinationGroupNames': product.get('optionCombinationGroupNames', {}),
            'optionCombinations': product.get('optionCombinations', []),
            'standardOptionGroups': [],
            'optionStandards': [],
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


class MainApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("스마트스토어 상품 수집기 v2.2")
        self.root.geometry("900x700")
        
        self.collector = SmartStoreCollector()
        self.collected_data = []
        
        self.init_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 시작 시 바로 브라우저 실행
        self.root.after(500, self.start_browser)
    
    def init_ui(self):
        main = ttk.Frame(self.root, padding="10")
        main.pack(fill=tk.BOTH, expand=True)
        
        # 브라우저 상태
        status_frame = ttk.LabelFrame(main, text="🌐 브라우저 상태", padding="10")
        status_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.browser_status = ttk.Label(status_frame, text="⏳ 브라우저 시작 중...", foreground='orange', font=('', 10, 'bold'))
        self.browser_status.pack(side=tk.LEFT)
        
        self.restart_btn = ttk.Button(status_frame, text="🔄 브라우저 재시작", command=self.restart_browser)
        self.restart_btn.pack(side=tk.RIGHT)
        
        # URL 입력
        url_frame = ttk.LabelFrame(main, text="🔗 상품 URL 입력 (여러 개는 줄바꿈)", padding="10")
        url_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.url_text = scrolledtext.ScrolledText(url_frame, height=4, font=('Consolas', 10))
        self.url_text.pack(fill=tk.X)
        self.url_text.insert(tk.END, "https://smartstore.naver.com/opalrin/products/12943483896")
        
        # 버튼
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.collect_btn = ttk.Button(btn_frame, text="📥 상품 수집", command=self.collect_products, width=15)
        self.collect_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.save_btn = ttk.Button(btn_frame, text="💾 엑셀 저장", command=self.save_excel, state='disabled')
        self.save_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.clear_btn = ttk.Button(btn_frame, text="🗑️ 초기화", command=self.clear_data)
        self.clear_btn.pack(side=tk.LEFT)
        
        self.count_label = ttk.Label(btn_frame, text="수집: 0개", foreground='blue', font=('', 10, 'bold'))
        self.count_label.pack(side=tk.RIGHT)
        
        # 진행
        progress_frame = ttk.LabelFrame(main, text="📋 진행 상태", padding="10")
        progress_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))
        
        self.log_text = scrolledtext.ScrolledText(progress_frame, height=14, state='disabled', font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # 안내
        help_text = """💡 사용법: 크롬창에서 네이버 로그인 → URL 입력 → 상품 수집 → 엑셀 저장"""
        ttk.Label(main, text=help_text, foreground='gray').pack(anchor='w')
    
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
        self.save_btn.config(state='normal' if self.collected_data else 'disabled')
    
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

                        # 0. 채널 UID 가져오기 (API 호출용)
                        channel_uid = None
                        api_data = None

                        if 'simpleProductForDetailPage' in data:
                            spd = data['simpleProductForDetailPage']
                            if isinstance(spd, dict):
                                spd_a = spd.get('A', {})
                                if isinstance(spd_a, dict):
                                    channel_info = spd_a.get('channel', {})
                                    if isinstance(channel_info, dict):
                                        channel_uid = channel_info.get('channelUid', '')

                        # API 호출로 전체 데이터 가져오기 (옵션, 원산지 등 포함)
                        if channel_uid:
                            self.log(f"  🔗 API 호출 중... (channelUid: {channel_uid[:10]}...)")
                            api_data = self.collector.fetch_product_api(channel_uid, product_no)
                            if api_data and api_data.get('name'):
                                self.log(f"  ✅ API에서 데이터 가져옴 (옵션 {len(api_data.get('optionCombinations', []))}개)")

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

                                # 브랜드/제조사/원산지 관련 키 확인
                                brand_keys = [k for k in prod_keys if 'brand' in k.lower() or 'manufacturer' in k.lower() or 'origin' in k.lower() or 'naver' in k.lower()]
                                if brand_keys:
                                    self.log(f"  🏷️ 브랜드/제조사/원산지 관련 키: {brand_keys}")
                                    for bk in brand_keys:
                                        bv = product.get(bk)
                                        if isinstance(bv, dict):
                                            self.log(f"    {bk}: {list(bv.keys())[:10]}")
                                        else:
                                            self.log(f"    {bk}: {str(bv)[:100]}")

                                # 옵션 관련 키 확인
                                option_keys = [k for k in prod_keys if 'option' in k.lower()]
                                if option_keys:
                                    self.log(f"  🎯 옵션 관련 키: {option_keys}")
                                    for ok in option_keys:
                                        ov = product.get(ok)
                                        if isinstance(ov, list):
                                            self.log(f"    {ok}: 리스트({len(ov)}개)")
                                        elif isinstance(ov, dict):
                                            self.log(f"    {ok}: {list(ov.keys())[:5]}")
                                        else:
                                            self.log(f"    {ok}: {type(ov).__name__}")

                                # 태그 관련 키 확인
                                tag_keys = [k for k in prod_keys if 'tag' in k.lower()]
                                if tag_keys:
                                    self.log(f"  🏷️ 태그 관련 키: {tag_keys}")

                                # content/detail 관련 키 확인
                                content_keys = [k for k in prod_keys if 'content' in k.lower() or 'detail' in k.lower() or 'description' in k.lower()]
                                if content_keys:
                                    self.log(f"  📝 상세설명 관련 키: {content_keys}")
                                    for ck in content_keys:
                                        cv = product.get(ck)
                                        if isinstance(cv, str):
                                            self.log(f"    {ck}: {len(cv)}자")
                                        else:
                                            self.log(f"    {ck}: {type(cv).__name__}")

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

                            # API 데이터가 있으면 우선 사용 (옵션, 원산지 등 포함)
                            if api_data and api_data.get('name'):
                                result = self.collector._parse_to_excel_format_v2(data, api_data, url, store_name, product_no)
                            else:
                                result = self.collector._parse_to_excel_format_v2(data, product, url, store_name, product_no)

                            # 상세설명이 없거나 짧으면 DOM에서 가져오기
                            detail_len = len(result.get('상세설명', ''))
                            if detail_len < 100:
                                try:
                                    # 페이지 스크롤하여 lazy-load 이미지 로딩 트리거
                                    self.collector.driver.execute_script("""
                                        window.scrollTo(0, document.body.scrollHeight);
                                    """)
                                    time.sleep(0.5)
                                    self.collector.driver.execute_script("""
                                        window.scrollTo(0, 0);
                                    """)
                                    time.sleep(0.3)

                                    # DOM에서 .se-viewer 요소의 outerHTML 가져오기
                                    # lazy-load 이미지의 data-src를 src로 교체
                                    detail_html = self.collector.driver.execute_script("""
                                        var viewer = document.querySelector('.se-viewer');
                                        if (!viewer) return '';

                                        // 복제본 생성 (원본 DOM 변경 방지)
                                        var clone = viewer.cloneNode(true);

                                        // data-src 속성이 있는 이미지의 src를 실제 URL로 교체
                                        var imgs = clone.querySelectorAll('img[data-src]');
                                        for (var i = 0; i < imgs.length; i++) {
                                            var dataSrc = imgs[i].getAttribute('data-src');
                                            if (dataSrc && dataSrc.startsWith('http')) {
                                                imgs[i].setAttribute('src', dataSrc);
                                                imgs[i].removeAttribute('data-src');
                                            }
                                        }

                                        // data-lazy-src 속성도 확인
                                        var lazyImgs = clone.querySelectorAll('img[data-lazy-src]');
                                        for (var i = 0; i < lazyImgs.length; i++) {
                                            var lazySrc = lazyImgs[i].getAttribute('data-lazy-src');
                                            if (lazySrc && lazySrc.startsWith('http')) {
                                                lazyImgs[i].setAttribute('src', lazySrc);
                                                lazyImgs[i].removeAttribute('data-lazy-src');
                                            }
                                        }

                                        return clone.outerHTML;
                                    """)
                                    if detail_html and len(detail_html) > detail_len:
                                        # Python에서 추가 정리: base64 src를 data-src의 실제 URL로 교체
                                        # 패턴: src="data:image..." data-src="https://..." 또는 반대 순서
                                        def fix_lazy_images(html):
                                            # 패턴1: src="data:..." 뒤에 data-src="http..." 가 있는 경우
                                            html = re.sub(
                                                r'src="data:image[^"]*"\s*data-src="(https?://[^"]+)"',
                                                r'src="\1"',
                                                html
                                            )
                                            # 패턴2: data-src="http..." 뒤에 src="data:..." 가 있는 경우
                                            html = re.sub(
                                                r'data-src="(https?://[^"]+)"\s*src="data:image[^"]*"',
                                                r'src="\1"',
                                                html
                                            )
                                            return html
                                        detail_html = fix_lazy_images(detail_html)
                                        result['상세설명'] = detail_html
                                        self.log(f"  📝 상세설명 DOM에서 추출 ({len(detail_html)}자)")
                                except Exception as e:
                                    self.log(f"  ⚠️ DOM 상세설명 추출 실패: {e}")

                            # seViewerContent에서도 확인
                            if not result.get('상세설명') and 'seViewerContent' in data:
                                svc = data['seViewerContent']
                                if isinstance(svc, dict):
                                    for key, val in svc.items():
                                        if isinstance(val, str) and len(val) > 100:
                                            # lazy-load 이미지 정리
                                            def fix_lazy_images_svc(html):
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
                                                return html
                                            result['상세설명'] = fix_lazy_images_svc(val)
                                            self.log(f"  📝 상세설명 seViewerContent에서 추출")
                                            break

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
            self.update_count()
            self.log("🗑️ 초기화 완료")
    
    def on_closing(self):
        self.collector.close()
        self.root.destroy()
    
    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = MainApp()
    app.run()
