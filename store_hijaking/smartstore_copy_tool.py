#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
스마트스토어 상품 복사 도구
- 원본 스마트스토어에서 상품 정보를 가져와 구글시트에 저장
- 구글시트 내용을 수정 후 다른 스마트스토어에 업로드
"""

import os
import sys
import json
import time
import hashlib
import hmac
import base64
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime
from typing import Optional, Dict, List, Any
import threading

# 스크립트 위치 기준 경로 설정
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    import requests
except ImportError:
    print("requests 라이브러리가 필요합니다: pip install requests")
    sys.exit(1)

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("gspread, google-auth 라이브러리가 필요합니다: pip install gspread google-auth")
    sys.exit(1)

try:
    import bcrypt
except ImportError:
    print("bcrypt 라이브러리가 필요합니다: pip install bcrypt")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("beautifulsoup4 라이브러리가 필요합니다: pip install beautifulsoup4")
    BeautifulSoup = None


class NaverCommerceAPI:
    """네이버 커머스 API 클래스"""
    
    BASE_URL = "https://api.commerce.naver.com/external"
    
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.access_token = None
        self.token_expires = 0
    
    def _generate_signature(self, timestamp: int) -> str:
        # 밑줄로 연결하여 password 생성
        password = f"{self.client_id}_{timestamp}"
        # bcrypt 해싱 (client_secret을 salt로 사용)
        hashed = bcrypt.hashpw(password.encode('utf-8'), self.client_secret.encode('utf-8'))
        # base64 인코딩
        return base64.b64encode(hashed).decode('utf-8')
    
    def get_access_token(self) -> str:
        current_time = int(time.time() * 1000)
        if self.access_token and current_time < self.token_expires - 60000:
            return self.access_token
        
        # 타임스탬프는 정수로 사용
        timestamp = current_time
        signature = self._generate_signature(timestamp)
        
        url = f"{self.BASE_URL}/v1/oauth2/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        data = {
            "client_id": self.client_id,
            "timestamp": timestamp,
            "client_secret_sign": signature,
            "grant_type": "client_credentials",
            "type": "SELF"
        }
        
        response = requests.post(url, headers=headers, data=data, timeout=30)
        if response.status_code == 200:
            result = response.json()
            self.access_token = result.get("access_token")
            expires_in = result.get("expires_in", 21600)
            self.token_expires = current_time + (expires_in * 1000)
            return self.access_token
        else:
            raise Exception(f"토큰 발급 실패: {response.status_code} - {response.text}")
    
    def _get_headers(self) -> Dict[str, str]:
        token = self.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json;charset=UTF-8"
        }
    
    def get_product_list(self, page: int = 1, size: int = 100) -> Dict[str, Any]:
        """상품 목록 조회 - POST /v1/products/search 사용"""
        url = f"{self.BASE_URL}/v1/products/search"
        payload = {
            "page": page,
            "size": min(size, 500)  # 최대 500개
        }
        
        response = requests.post(url, headers=self._get_headers(), json=payload, timeout=30)
        if response.status_code in [200, 201]:
            return response.json()
        else:
            raise Exception(f"상품 목록 조회 실패: {response.status_code} - {response.text}")
    
    def get_product_detail(self, product_no: str) -> Dict[str, Any]:
        """원상품 상세 조회 - Rate Limit 재시도 포함"""
        url = f"{self.BASE_URL}/v2/products/origin-products/{product_no}"
        
        for attempt in range(5):
            response = requests.get(url, headers=self._get_headers(), timeout=30)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                # Rate Limit - 대기 후 재시도
                retry_after = response.headers.get('Retry-After')
                wait_time = float(retry_after) if retry_after else (2 ** attempt) + 1
                time.sleep(min(wait_time, 30))
                continue
            else:
                raise Exception(f"상품 상세 조회 실패: {response.status_code} - {response.text}")
        
        raise Exception("상품 상세 조회 실패: Rate Limit 초과")
    
    def create_product(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """상품 등록 - POST /v2/products"""
        url = f"{self.BASE_URL}/v2/products"
        response = requests.post(url, headers=self._get_headers(), json=product_data, timeout=60)
        if response.status_code in [200, 201]:
            return response.json()
        else:
            raise Exception(f"상품 등록 실패: {response.status_code} - {response.text}")


class GoogleSheetsManager:
    """구글 시트 관리 클래스"""
    
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    
    HEADERS = [
        "상품번호", "상품명", "판매가", "정상가", "재고수량",
        "카테고리ID", "카테고리명", "상품상태코드", "상품상태명",
        "대표이미지URL", "추가이미지URLs", "동영상URL", "상세설명HTML",
        "옵션사용여부", "옵션정보JSON", "배송방법", "배송비유형",
        "기본배송비", "반품배송비", "교환배송비",
        "A/S전화번호", "A/S안내", "원산지코드", "원산지명",
        "제조사", "브랜드", "모델명", "인증정보JSON",
        "속성정보JSON", "태그", "판매시작일", "판매종료일",
        "최소구매수량", "최대구매수량", "할인율", "할인가", "원본상품번호"
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
        worksheet.batch_clear(['A2:AI10000'])
    
    def append_products(self, worksheet, products: List[List[Any]]):
        if products:
            worksheet.append_rows(products, value_input_option='RAW')
    
    def get_all_products(self, worksheet) -> List[Dict[str, Any]]:
        return worksheet.get_all_records()


def safe_get(data: Dict, *keys, default=''):
    try:
        for key in keys:
            data = data[key]
        return data if data is not None else default
    except (KeyError, TypeError, IndexError):
        return default


# 구글시트 셀 최대 길이 (50000자 제한, 여유분 확보)
MAX_CELL_LENGTH = 49000


def truncate_text(text: str, max_length: int = MAX_CELL_LENGTH) -> str:
    """텍스트가 너무 길면 잘라내기"""
    if text and len(text) > max_length:
        return text[:max_length] + "...[잘림]"
    return text


def extract_video_from_html(html_content: str) -> str:
    """HTML에서 동영상 URL 추출"""
    if not html_content or not BeautifulSoup:
        return ''

    try:
        soup = BeautifulSoup(html_content, 'html.parser')

        # iframe에서 동영상 찾기 (YouTube, 네이버 TV 등)
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src', '')
            if src and ('youtube' in src or 'youtu.be' in src or 'naver' in src or 'video' in src):
                print(f"[DEBUG] iframe 동영상 발견: {src[:60]}...")
                return src

        # video 태그에서 찾기
        videos = soup.find_all('video')
        for video in videos:
            src = video.get('src', '')
            if src:
                print(f"[DEBUG] video 태그 동영상 발견: {src[:60]}...")
                return src
            # source 태그 확인
            source = video.find('source')
            if source:
                src = source.get('src', '')
                if src:
                    print(f"[DEBUG] source 태그 동영상 발견: {src[:60]}...")
                    return src

        # 네이버 동영상 플레이어 URL 패턴 찾기
        import re
        patterns = [
            r'(https?://[^"\s]+\.mp4)',
            r'(https?://tv\.naver\.com/[^"\s]+)',
            r'(https?://smartstore\.naver\.com/videoplayer/[^"\s]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, html_content)
            if match:
                url = match.group(1)
                print(f"[DEBUG] 정규식 동영상 발견: {url[:60]}...")
                return url

    except Exception as e:
        print(f"[DEBUG] HTML 동영상 추출 오류: {e}")

    return ''


def product_to_row(product: Dict[str, Any], original_no: str, debug_first: bool = False) -> List[Any]:
    """상품 데이터를 시트 행으로 변환 - API 응답 구조 반영"""
    # originProduct가 있으면 그 안의 데이터 사용, 없으면 직접 접근
    origin = product.get('originProduct', product)

    # 첫 번째 상품만 전체 키 구조 출력
    if debug_first:
        print(f"\n[DEBUG] ===== 상품 전체 구조 (첫 번째 상품) =====")
        print(f"[DEBUG] product 최상위 키: {list(product.keys())}")
        print(f"[DEBUG] originProduct 키: {list(origin.keys())}")

        # detailAttribute 안 확인
        detail = origin.get('detailAttribute', {})
        print(f"[DEBUG] detailAttribute 키: {list(detail.keys())}")

        # smartstoreChannelProduct 확인
        channel = product.get('smartstoreChannelProduct', {})
        print(f"[DEBUG] smartstoreChannelProduct 키: {list(channel.keys())}")

        # video/gif 관련 키 찾기 (전체 탐색)
        def find_media_keys(obj, path=""):
            if isinstance(obj, dict):
                for key, val in obj.items():
                    key_lower = key.lower()
                    if 'video' in key_lower or 'gif' in key_lower or 'thumbnail' in key_lower:
                        val_preview = str(val)[:200] if val else 'None'
                        print(f"[DEBUG] 미디어 키 발견: {path}.{key} = {val_preview}")
                    find_media_keys(val, f"{path}.{key}")
            elif isinstance(obj, list) and len(obj) > 0:
                find_media_keys(obj[0], f"{path}[0]")

        find_media_keys(product, "product")
        print(f"[DEBUG] =========================================\n")

    # 상세 속성 (먼저 정의)
    detail_attr = origin.get('detailAttribute', {})

    # 이미지 처리
    images = origin.get('images', {})
    main_image = ''
    additional_images = []

    # images가 딕셔너리인 경우 (originProduct.images 구조)
    if isinstance(images, dict):
        rep_img = images.get('representativeImage', {})
        if rep_img:
            main_image = rep_img.get('url', '')

        opt_imgs = images.get('optionalImages', [])
        for img in opt_imgs:
            if isinstance(img, dict):
                img_url = img.get('url', '')
                if img_url:
                    additional_images.append(img_url)
            elif isinstance(img, str):
                additional_images.append(img)
    # images가 리스트인 경우
    elif isinstance(images, list):
        for img in images:
            if isinstance(img, dict):
                img_url = img.get('url', img.get('imageUrl', ''))
                if img_url:
                    if not main_image:
                        main_image = img_url
                    else:
                        additional_images.append(img_url)

    # 동영상 추출 - detailContent HTML에서 찾기
    detail_content = origin.get('detailContent', '') or ''
    video_url = extract_video_from_html(detail_content)

    # 디버그: 첫 번째 상품에서 iframe/video 태그 유무 확인
    if debug_first and detail_content:
        import re
        has_iframe = '<iframe' in detail_content.lower()
        has_video = '<video' in detail_content.lower()
        has_youtube = 'youtube' in detail_content.lower()
        has_naver_video = 'naver' in detail_content.lower() and 'video' in detail_content.lower()
        print(f"[DEBUG] detailContent 길이: {len(detail_content)}")
        print(f"[DEBUG] iframe 태그 있음: {has_iframe}")
        print(f"[DEBUG] video 태그 있음: {has_video}")
        print(f"[DEBUG] youtube 포함: {has_youtube}")
        print(f"[DEBUG] naver+video 포함: {has_naver_video}")
        if video_url:
            print(f"[DEBUG] 추출된 동영상 URL: {video_url}")
        else:
            print(f"[DEBUG] 동영상 URL 추출 실패")
    
    # 옵션 정보
    option_info = detail_attr.get('optionInfo', {})

    # 배송 정보
    delivery = origin.get('deliveryInfo', {})
    delivery_fee = delivery.get('deliveryFee', {})
    claim_delivery = delivery.get('claimDeliveryInfo', {})

    # AS 정보
    as_info = detail_attr.get('afterServiceInfo', {})

    # 원산지 정보
    origin_area = detail_attr.get('originAreaInfo', {})

    # 네이버쇼핑 검색 정보
    naver_search = detail_attr.get('naverShoppingSearchInfo', {})

    # 인증 정보
    cert_info = origin.get('productInfoProvidedNotice', {})

    # 속성 정보
    attr_info = origin.get('productAttributes', [])

    # 할인 정보
    discount_policy = detail_attr.get('immediateDiscountPolicy', {})
    discount_method = discount_policy.get('discountMethod', {})
    discount_value = discount_method.get('value', 0)
    discount_unit = discount_method.get('unitType', '')  # PERCENT or WON

    # 할인율 계산
    if discount_unit == 'PERCENT':
        discount_rate = discount_value
        sale_price = origin.get('salePrice', 0)
        discount_price = int(sale_price * (100 - discount_value) / 100) if sale_price else 0
    else:
        discount_rate = 0
        discount_price = discount_value

    # 긴 텍스트 필드 처리
    detail_content = truncate_text(origin.get('detailContent', '') or '')
    option_json = truncate_text(json.dumps(option_info, ensure_ascii=False) if option_info else '')
    cert_json = truncate_text(json.dumps(cert_info, ensure_ascii=False) if cert_info else '')
    attr_json = truncate_text(json.dumps(attr_info, ensure_ascii=False) if attr_info else '')
    as_guide = truncate_text(as_info.get('afterServiceGuideContent', '') or '')

    return [
        origin.get('originProductNo', original_no),  # 상품번호
        origin.get('name', ''),  # 상품명
        origin.get('salePrice', 0),  # 판매가
        origin.get('regularPrice', origin.get('salePrice', 0)),  # 정상가
        origin.get('stockQuantity', 0),  # 재고수량
        origin.get('leafCategoryId', ''),  # 카테고리ID
        '',  # 카테고리명 (별도 조회 필요)
        origin.get('statusType', ''),  # 상품상태코드
        '',  # 상품상태명
        main_image,  # 대표이미지URL
        ','.join(additional_images),  # 추가이미지URLs
        video_url,  # 동영상URL
        detail_content,  # 상세설명HTML
        '사용' if option_info.get('optionCombinations') else '미사용',  # 옵션사용여부
        option_json,  # 옵션정보JSON
        delivery.get('deliveryType', ''),  # 배송방법
        delivery_fee.get('deliveryFeeType', ''),  # 배송비유형
        delivery_fee.get('baseFee', 0),  # 기본배송비
        claim_delivery.get('returnDeliveryFee', 0),  # 반품배송비
        claim_delivery.get('exchangeDeliveryFee', 0),  # 교환배송비
        as_info.get('afterServiceTelephoneNumber', ''),  # A/S전화번호
        as_guide,  # A/S안내
        origin_area.get('originAreaCode', ''),  # 원산지코드
        origin_area.get('content', ''),  # 원산지명
        naver_search.get('manufacturerName', ''),  # 제조사
        naver_search.get('brandName', ''),  # 브랜드
        naver_search.get('modelName', ''),  # 모델명
        cert_json,  # 인증정보JSON
        attr_json,  # 속성정보JSON
        ','.join(origin.get('tags', [])) if origin.get('tags') else '',  # 태그
        origin.get('saleStartDate', ''),  # 판매시작일
        origin.get('saleEndDate', ''),  # 판매종료일
        safe_get(detail_attr, 'purchaseQuantityInfo', 'minPurchaseQuantity', default=1),  # 최소구매수량
        safe_get(detail_attr, 'purchaseQuantityInfo', 'maxPurchaseQuantityPerOrder', default=''),  # 최대구매수량
        discount_rate,  # 할인율 (%)
        discount_price,  # 할인가
        original_no  # 원본상품번호
    ]


def image_urls_to_html(image_urls_str: str) -> str:
    """이미지 URL 목록을 HTML로 변환"""
    if not image_urls_str:
        return ''

    # 줄바꿈 또는 쉼표로 구분된 URL 처리
    urls = []
    for line in image_urls_str.replace(',', '\n').split('\n'):
        url = line.strip()
        if url and (url.startswith('http://') or url.startswith('https://')):
            urls.append(url)

    if not urls:
        return ''

    # HTML 생성
    html_parts = ['<div style="text-align:center;">']
    for url in urls:
        html_parts.append(f'<img src="{url}" style="max-width:100%;">')
    html_parts.append('</div>')

    return ''.join(html_parts)


def row_to_product(row: Dict[str, Any]) -> Dict[str, Any]:
    """시트 행을 상품 등록 데이터로 변환 - 공식 API 구조"""
    # 이미지 구성
    images = {}
    if row.get('대표이미지URL'):
        images["representativeImage"] = {"url": row['대표이미지URL']}

    optional_images = []
    additional = row.get('추가이미지URLs', '')
    if additional:
        for url in additional.split(','):
            url = url.strip()
            if url:
                optional_images.append({"url": url})

    # 동영상도 optionalImages에 추가 (이미지와 동일한 배열)
    video_url = row.get('동영상URL', '') or ''
    if video_url:
        video_item = {"videoUrl": video_url}
        optional_images.append(video_item)
        print(f"[DEBUG] 동영상 업로드 추가: {video_url[:50]}...")

    if optional_images:
        images["optionalImages"] = optional_images

    # 옵션 정보 파싱 및 ID 제거 (새 상품 등록 시 ID가 있으면 오류 발생)
    option_info = {}
    if row.get('옵션정보JSON'):
        try:
            option_info = json.loads(row['옵션정보JSON'])
            # optionCombinations에서 id 필드 제거
            if 'optionCombinations' in option_info:
                for combo in option_info['optionCombinations']:
                    if 'id' in combo:
                        del combo['id']
            # 단독형 옵션에서도 id 제거
            if 'standardOptionGroups' in option_info:
                for group in option_info['standardOptionGroups']:
                    if 'id' in group:
                        del group['id']
                    if 'standardOptionAttributes' in group:
                        for attr in group['standardOptionAttributes']:
                            if 'id' in attr:
                                del attr['id']
        except:
            pass

    # 상세설명 처리: HTML이 없고 이미지URL만 있으면 변환
    detail_content = row.get('상세설명HTML', '') or ''
    if not detail_content.strip().startswith('<'):
        # HTML이 아니면 이미지 URL 목록으로 간주하여 변환
        detail_content = image_urls_to_html(detail_content)

    # 상품 등록 데이터 구성 - 공식 API 구조
    product_data = {
        "originProduct": {
            "statusType": row.get('상품상태코드', '') or "SALE",
            "saleType": "NEW",
            "leafCategoryId": str(row.get('카테고리ID', '')),
            "name": row.get('상품명', ''),
            "detailContent": detail_content,
            "images": images,
            "salePrice": int(row.get('판매가', 0) or 0),
            "stockQuantity": int(row.get('재고수량', 0) or 0),
            "taxType": "TAX",  # 부가세: 과세
            "deliveryInfo": {
                "deliveryType": "DELIVERY",
                "deliveryAttributeType": "NORMAL",
                "deliveryCompany": "CJGLS",  # 배송사: CJ대한통운
                "deliveryFee": {
                    "deliveryFeeType": "FREE",  # 무료배송
                    "baseFee": 0,
                    "deliveryFeePayType": "PREPAID"
                },
                "claimDeliveryInfo": {
                    "returnDeliveryFee": 200000,  # 반품배송비 20만원
                    "exchangeDeliveryFee": 100000  # 교환배송비 10만원
                }
            },
            "detailAttribute": {
                "minorPurchasable": True,  # 미성년자 구매 가능
                "afterServiceInfo": {
                    "afterServiceTelephoneNumber": "01046856687",
                    "afterServiceGuideContent": "상세설명참조"
                },
                "originAreaInfo": {
                    "originAreaCode": "03",  # 기타
                    "content": "중국OEM"
                },
                # 구매수량 제한
                "purchaseQuantityInfo": {
                    "maxPurchaseQuantityPerOrder": 99,  # 최대 99개
                    "maxPurchaseQuantityPerId": 99,
                    "maxPurchaseQuantityPerIdPeriod": 1  # 1일 기준
                },
                # 네이버쇼핑 검색 정보 (브랜드, 제조사 고정)
                "naverShoppingSearchInfo": {
                    "brandName": "오팔린",
                    "manufacturerName": "오팔린협력사"
                },
                # KC 인증 - 인증 대상 아님으로 설정
                "certificationTargetExcludeContent": {
                    "kcCertifiedProductExclusionYn": "TRUE",  # KC 인증 대상 아님
                    "childCertifiedProductExclusionYn": True,  # 어린이제품 인증 대상 제외
                    "greenCertifiedProductExclusionYn": True   # 친환경 인증 대상 제외
                },
                # 상품정보제공고시 (필수) - 기타 재화로 설정
                "productInfoProvidedNotice": {
                    "productInfoProvidedNoticeType": "ETC",
                    "etc": {
                        "returnCostReason": "상세설명참조",
                        "noRefundReason": "상세설명참조",
                        "qualityAssuranceStandard": "상세설명참조",
                        "compensationProcedure": "상세설명참조",
                        "troubleShootingContents": "상세설명참조",
                        "itemName": "상세설명참조",
                        "modelName": "상세설명참조",
                        "manufacturer": "오팔린협력사",
                        "customerServicePhoneNumber": "01046856687"
                    }
                }
            }
        },
        # 스마트스토어 채널 상품 정보 (필수)
        "smartstoreChannelProduct": {
            "channelProductName": row.get('상품명', ''),
            "channelProductDisplayStatusType": "ON",  # ON: 전시중, WAIT: 전시대기, SUSPENSION: 전시중지
            "storeKeepExclusiveProduct": False,
            "naverShoppingRegistration": True
        }
    }
    
    # 옵션 정보 추가
    if option_info:
        product_data["originProduct"]["detailAttribute"]["optionInfo"] = option_info

    # 모델명만 추가 (브랜드, 제조사는 고정값 사용)
    if row.get('모델명'):
        product_data["originProduct"]["detailAttribute"]["naverShoppingSearchInfo"]["modelName"] = row['모델명']

    # 태그
    if row.get('태그'):
        product_data["originProduct"]["tags"] = [t.strip() for t in row['태그'].split(',') if t.strip()]
    
    return product_data


class MainApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("스마트스토어 상품 복사 도구")
        self.root.geometry("900x750")
        self.root.resizable(True, True)

        self.credentials_path = os.path.join(SCRIPT_DIR, "credentials.json")
        self.config_path = os.path.join(SCRIPT_DIR, "config.json")
        self.init_ui()
        self.load_config()

        # 창 닫을 때 자동 저장
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        """창 닫을 때 설정 저장"""
        self.save_config()
        self.root.destroy()

    def load_config(self):
        """저장된 설정 불러오기"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                # 원본 스토어
                self.source_market.insert(0, config.get('source_market', ''))
                self.source_client_id.insert(0, config.get('source_client_id', ''))
                self.source_client_secret.insert(0, config.get('source_client_secret', ''))

                # 대상 스토어
                self.target_market.insert(0, config.get('target_market', ''))
                self.target_client_id.insert(0, config.get('target_client_id', ''))
                self.target_client_secret.insert(0, config.get('target_client_secret', ''))

                # 구글시트
                self.spreadsheet_id.insert(0, config.get('spreadsheet_id', ''))
                sheet_name = config.get('sheet_name', '상품목록')
                self.sheet_name.delete(0, tk.END)
                self.sheet_name.insert(0, sheet_name)

                # 조회 갯수 제한
                fetch_limit = config.get('fetch_limit', '0')
                self.fetch_limit.delete(0, tk.END)
                self.fetch_limit.insert(0, fetch_limit)

                self.log("✅ 저장된 설정을 불러왔습니다.")
            except Exception as e:
                self.log(f"⚠️ 설정 불러오기 실패: {str(e)}")

    def save_config(self):
        """현재 설정 저장"""
        config = {
            'source_market': self.source_market.get().strip(),
            'source_client_id': self.source_client_id.get().strip(),
            'source_client_secret': self.source_client_secret.get().strip(),
            'target_market': self.target_market.get().strip(),
            'target_client_id': self.target_client_id.get().strip(),
            'target_client_secret': self.target_client_secret.get().strip(),
            'spreadsheet_id': self.spreadsheet_id.get().strip(),
            'sheet_name': self.sheet_name.get().strip(),
            'fetch_limit': self.fetch_limit.get().strip()
        }
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"설정 저장 실패: {e}")
            return False

    def save_config_with_msg(self):
        """설정 저장 후 메시지 표시"""
        if self.save_config():
            self.log("💾 설정이 저장되었습니다.")
            messagebox.showinfo("완료", "설정이 저장되었습니다.")
        else:
            messagebox.showerror("오류", "설정 저장에 실패했습니다.")
    
    def init_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 원본 스토어 설정
        source_frame = ttk.LabelFrame(main_frame, text="📦 원본 스토어 (상품 가져오기)", padding="10")
        source_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(source_frame, text="※ 탭으로 구분된 텍스트 붙여넣기 시 자동 분리 (마켓명 → client_id → client_secret)", foreground='gray').pack(anchor='w')
        
        row1 = ttk.Frame(source_frame)
        row1.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(row1, text="마켓명:").pack(side=tk.LEFT)
        self.source_market = ttk.Entry(row1, width=15)
        self.source_market.pack(side=tk.LEFT, padx=(5, 15))
        self.source_market.bind('<KeyRelease>', lambda e: self._check_tab(self.source_market, self.source_client_id, self.source_client_secret))
        
        ttk.Label(row1, text="Client ID:").pack(side=tk.LEFT)
        self.source_client_id = ttk.Entry(row1, width=25)
        self.source_client_id.pack(side=tk.LEFT, padx=(5, 15))
        self.source_client_id.bind('<KeyRelease>', lambda e: self._check_tab(self.source_client_id, self.source_client_secret, None))
        
        ttk.Label(row1, text="Client Secret:").pack(side=tk.LEFT)
        self.source_client_secret = ttk.Entry(row1, width=25, show='*')
        self.source_client_secret.pack(side=tk.LEFT, padx=(5, 5))
        
        self.source_show_var = tk.BooleanVar()
        ttk.Checkbutton(row1, text="표시", variable=self.source_show_var, 
                       command=lambda: self.source_client_secret.config(show='' if self.source_show_var.get() else '*')).pack(side=tk.LEFT)
        
        # 대상 스토어 설정
        target_frame = ttk.LabelFrame(main_frame, text="📤 대상 스토어 (상품 업로드)", padding="10")
        target_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(target_frame, text="※ 탭으로 구분된 텍스트 붙여넣기 시 자동 분리 (마켓명 → client_id → client_secret)", foreground='gray').pack(anchor='w')
        
        row2 = ttk.Frame(target_frame)
        row2.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(row2, text="마켓명:").pack(side=tk.LEFT)
        self.target_market = ttk.Entry(row2, width=15)
        self.target_market.pack(side=tk.LEFT, padx=(5, 15))
        self.target_market.bind('<KeyRelease>', lambda e: self._check_tab(self.target_market, self.target_client_id, self.target_client_secret))
        
        ttk.Label(row2, text="Client ID:").pack(side=tk.LEFT)
        self.target_client_id = ttk.Entry(row2, width=25)
        self.target_client_id.pack(side=tk.LEFT, padx=(5, 15))
        self.target_client_id.bind('<KeyRelease>', lambda e: self._check_tab(self.target_client_id, self.target_client_secret, None))
        
        ttk.Label(row2, text="Client Secret:").pack(side=tk.LEFT)
        self.target_client_secret = ttk.Entry(row2, width=25, show='*')
        self.target_client_secret.pack(side=tk.LEFT, padx=(5, 5))
        
        self.target_show_var = tk.BooleanVar()
        ttk.Checkbutton(row2, text="표시", variable=self.target_show_var,
                       command=lambda: self.target_client_secret.config(show='' if self.target_show_var.get() else '*')).pack(side=tk.LEFT)
        
        # 구글시트 설정
        sheet_frame = ttk.LabelFrame(main_frame, text="📊 구글 시트 설정", padding="10")
        sheet_frame.pack(fill=tk.X, pady=(0, 10))
        
        row3 = ttk.Frame(sheet_frame)
        row3.pack(fill=tk.X)
        
        ttk.Label(row3, text="스프레드시트 ID:").pack(side=tk.LEFT)
        self.spreadsheet_id = ttk.Entry(row3, width=50)
        self.spreadsheet_id.pack(side=tk.LEFT, padx=(5, 15))
        
        ttk.Label(row3, text="시트 이름:").pack(side=tk.LEFT)
        self.sheet_name = ttk.Entry(row3, width=15)
        self.sheet_name.pack(side=tk.LEFT, padx=(5, 0))
        self.sheet_name.insert(0, "상품목록")
        
        row4 = ttk.Frame(sheet_frame)
        row4.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(row4, text="조회 갯수 제한 (테스트용):").pack(side=tk.LEFT)
        self.fetch_limit = ttk.Entry(row4, width=10)
        self.fetch_limit.pack(side=tk.LEFT, padx=(5, 10))
        self.fetch_limit.insert(0, "0")
        ttk.Label(row4, text="(0 = 전체 조회)", foreground='gray').pack(side=tk.LEFT)

        ttk.Label(sheet_frame, text=f"📁 credentials.json 위치: {self.credentials_path}", foreground='gray').pack(anchor='w', pady=(10, 0))
        
        # 버튼
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.fetch_btn = ttk.Button(btn_frame, text="📥 원본 스토어 → 구글시트", command=self.fetch_products)
        self.fetch_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.upload_btn = ttk.Button(btn_frame, text="📤 구글시트 → 대상 스토어", command=self.upload_products)
        self.upload_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.setup_btn = ttk.Button(btn_frame, text="🔧 시트 헤더 설정", command=self.setup_headers)
        self.setup_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.clear_btn = ttk.Button(btn_frame, text="🗑️ 시트 데이터 초기화", command=self.clear_sheet)
        self.clear_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.save_btn = ttk.Button(btn_frame, text="💾 설정 저장", command=self.save_config_with_msg)
        self.save_btn.pack(side=tk.LEFT)
        
        # 진행 상태
        progress_frame = ttk.LabelFrame(main_frame, text="📋 진행 상태", padding="10")
        progress_frame.pack(fill=tk.BOTH, expand=True)
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))
        
        self.log_text = scrolledtext.ScrolledText(progress_frame, height=18, state='disabled', font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
    
    def _check_tab(self, current, next1, next2):
        text = current.get()
        if '\t' in text:
            parts = text.split('\t')
            current.delete(0, tk.END)
            current.insert(0, parts[0].strip())
            if len(parts) > 1 and next1:
                next1.delete(0, tk.END)
                next1.insert(0, parts[1].strip())
            if len(parts) > 2 and next2:
                next2.delete(0, tk.END)
                next2.insert(0, parts[2].strip())
    
    def log(self, msg):
        self.log_text.config(state='normal')
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')
        self.root.update_idletasks()
    
    def set_buttons_enabled(self, enabled):
        state = 'normal' if enabled else 'disabled'
        self.fetch_btn.config(state=state)
        self.upload_btn.config(state=state)
        self.setup_btn.config(state=state)
        self.clear_btn.config(state=state)
    
    def validate_sheet(self):
        if not self.spreadsheet_id.get().strip():
            messagebox.showwarning("입력 오류", "스프레드시트 ID를 입력하세요.")
            return False
        if not self.sheet_name.get().strip():
            messagebox.showwarning("입력 오류", "시트 이름을 입력하세요.")
            return False
        return True
    
    def validate_source(self):
        if not self.source_client_id.get().strip():
            messagebox.showwarning("입력 오류", "원본 스토어 Client ID를 입력하세요.")
            return False
        if not self.source_client_secret.get().strip():
            messagebox.showwarning("입력 오류", "원본 스토어 Client Secret을 입력하세요.")
            return False
        return True
    
    def validate_target(self):
        if not self.target_client_id.get().strip():
            messagebox.showwarning("입력 오류", "대상 스토어 Client ID를 입력하세요.")
            return False
        if not self.target_client_secret.get().strip():
            messagebox.showwarning("입력 오류", "대상 스토어 Client Secret을 입력하세요.")
            return False
        return True
    
    def get_manager(self):
        return GoogleSheetsManager(self.credentials_path)
    
    def setup_headers(self):
        if not self.validate_sheet():
            return
        try:
            self.log("구글시트 연결 중...")
            manager = self.get_manager()
            worksheet = manager.get_or_create_sheet(self.spreadsheet_id.get().strip(), self.sheet_name.get().strip())
            manager.setup_headers(worksheet)
            self.log("✅ 시트 헤더 설정 완료!")
            messagebox.showinfo("완료", "시트 헤더가 설정되었습니다.")
        except Exception as e:
            self.log(f"❌ 오류: {str(e)}")
            messagebox.showerror("오류", str(e))
    
    def clear_sheet(self):
        if not self.validate_sheet():
            return
        if not messagebox.askyesno("확인", "시트의 모든 데이터를 삭제하시겠습니까? (헤더 제외)"):
            return
        try:
            self.log("데이터 초기화 중...")
            manager = self.get_manager()
            worksheet = manager.get_or_create_sheet(self.spreadsheet_id.get().strip(), self.sheet_name.get().strip())
            manager.clear_data(worksheet)
            self.log("✅ 데이터 초기화 완료!")
            messagebox.showinfo("완료", "데이터가 초기화되었습니다.")
        except Exception as e:
            self.log(f"❌ 오류: {str(e)}")
            messagebox.showerror("오류", str(e))
    
    def fetch_products(self):
        if not self.validate_source() or not self.validate_sheet():
            return
        thread = threading.Thread(target=self._fetch_thread, daemon=True)
        thread.start()
    
    def _fetch_thread(self):
        try:
            self.set_buttons_enabled(False)
            self.log("🔄 원본 스토어 연결 중...")
            
            api = NaverCommerceAPI(self.source_client_id.get().strip(), self.source_client_secret.get().strip())
            manager = self.get_manager()
            
            self.log("📊 구글시트 연결 중...")
            worksheet = manager.get_or_create_sheet(self.spreadsheet_id.get().strip(), self.sheet_name.get().strip())
            manager.setup_headers(worksheet)
            
            # 조회 갯수 제한 확인
            try:
                limit = int(self.fetch_limit.get().strip() or 0)
            except ValueError:
                limit = 0

            if limit > 0:
                self.log(f"📦 상품 목록 조회 중... (테스트 모드: {limit}개 제한)")
            else:
                self.log("📦 상품 목록 조회 중...")

            all_products = []
            page = 1

            while True:
                # 제한이 있으면 필요한 만큼만 조회
                if limit > 0:
                    remaining = limit - len(all_products)
                    if remaining <= 0:
                        break
                    page_size = min(remaining, 500)
                else:
                    page_size = 500

                result = api.get_product_list(page=page, size=page_size)
                contents = result.get('contents', [])
                if not contents:
                    break

                all_products.extend(contents)
                self.log(f"  - {page}페이지: {len(contents)}개 상품 조회")

                # 제한 도달 시 중단
                if limit > 0 and len(all_products) >= limit:
                    all_products = all_products[:limit]
                    break

                total_pages = result.get('totalPages', 1)
                is_last = result.get('last', False)

                if is_last or page >= total_pages:
                    break
                page += 1
                time.sleep(0.5)

            if limit > 0:
                self.log(f"📋 {len(all_products)}개 상품 조회 완료 (테스트 모드)")
            else:
                self.log(f"📋 총 {len(all_products)}개 상품 발견")

            # 첫 번째 상품 데이터 구조 확인
            if all_products:
                first = all_products[0]
                self.log(f"📌 API 응답 필드: {list(first.keys())}")
                # 상품명 필드 찾기
                for key in ['name', 'productName', 'channelProductName', 'originProductName']:
                    if first.get(key):
                        self.log(f"   - {key}: {first.get(key)[:50] if first.get(key) else 'None'}")
            
            # 상품 수가 많으면 상세 조회 스킵 여부 확인
            skip_detail = False
            if len(all_products) > 100:
                self.log("💡 상품 수가 많아 목록 데이터만 사용합니다 (상세 조회 스킵)")
                skip_detail = True
            else:
                self.log("📝 상품 상세 정보 조회 중...")
            
            sheet_data = []
            self.progress_bar['maximum'] = len(all_products)
            
            for i, product in enumerate(all_products):
                # originProductNo 가져오기
                product_no = str(product.get('originProductNo', ''))
                if not product_no:
                    # channelProducts 안에 있을 수 있음
                    channel_products = product.get('channelProducts', [])
                    if channel_products:
                        product_no = str(channel_products[0].get('originProductNo', ''))
                
                if not product_no:
                    continue
                
                # 첫 번째 상품만 디버그 출력
                is_first = (i == 0)

                if skip_detail:
                    # 목록 데이터만 사용
                    row = product_to_row(product, product_no, debug_first=is_first)
                else:
                    # 상세 조회
                    try:
                        detail = api.get_product_detail(product_no)
                        row = product_to_row(detail, product_no, debug_first=is_first)
                    except Exception as e:
                        self.log(f"  ⚠️ 상품 {product_no} 상세 조회 실패: {str(e)[:50]}")
                        row = product_to_row(product, product_no, debug_first=is_first)
                    time.sleep(0.5)  # Rate Limit 방지
                    
                sheet_data.append(row)
                self.progress_bar['value'] = i + 1
                if (i + 1) % 100 == 0:
                    self.log(f"  - {i + 1}/{len(all_products)} 상품 처리 완료")
            
            self.log("💾 구글시트에 저장 중...")
            manager.clear_data(worksheet)
            manager.append_products(worksheet, sheet_data)
            
            self.log(f"✅ 완료! {len(sheet_data)}개 상품이 구글시트에 저장되었습니다.")
            self.root.after(0, lambda: messagebox.showinfo("완료", f"{len(sheet_data)}개 상품이 구글시트에 저장되었습니다."))
            
        except Exception as e:
            self.log(f"❌ 오류: {str(e)}")
            self.root.after(0, lambda: messagebox.showerror("오류", str(e)))
        finally:
            self.set_buttons_enabled(True)
            self.progress_bar['value'] = 0
    
    def upload_products(self):
        if not self.validate_target() or not self.validate_sheet():
            return
        thread = threading.Thread(target=self._upload_thread, daemon=True)
        thread.start()
    
    def _upload_thread(self):
        try:
            self.set_buttons_enabled(False)
            self.log("🔄 대상 스토어 연결 중...")
            
            api = NaverCommerceAPI(self.target_client_id.get().strip(), self.target_client_secret.get().strip())
            manager = self.get_manager()
            
            self.log("📊 구글시트에서 데이터 읽는 중...")
            worksheet = manager.get_or_create_sheet(self.spreadsheet_id.get().strip(), self.sheet_name.get().strip())
            products = manager.get_all_products(worksheet)
            
            if not products:
                self.log("❌ 업로드할 상품이 없습니다.")
                self.root.after(0, lambda: messagebox.showwarning("알림", "업로드할 상품이 없습니다."))
                return
            
            self.log(f"📋 {len(products)}개 상품 발견")
            self.log("📤 상품 등록 중...")
            
            success_count = 0
            fail_count = 0
            self.progress_bar['maximum'] = len(products)
            
            for i, product in enumerate(products):
                try:
                    product_data = row_to_product(product)
                    api.create_product(product_data)
                    success_count += 1
                    self.log(f"  ✅ 상품 등록 성공: {product.get('상품명', 'N/A')[:30]}")
                except Exception as e:
                    fail_count += 1
                    error_msg = str(e)
                    self.log(f"  ❌ 상품 등록 실패: {product.get('상품명', 'N/A')[:30]}")
                    self.log(f"     오류: {error_msg[:300]}")
                    # 첫 번째 실패 시 요청 데이터 출력
                    if fail_count == 1:
                        self.log(f"  📋 요청 데이터 샘플:")
                        self.log(f"     카테고리ID: {product.get('카테고리ID', 'N/A')}")
                        self.log(f"     판매가: {product.get('판매가', 'N/A')}")
                        self.log(f"     재고: {product.get('재고수량', 'N/A')}")
                        self.log(f"     배송비유형: {product.get('배송비유형', 'N/A')}")
                        self.log(f"     원산지코드: {product.get('원산지코드', 'N/A')}")
                self.progress_bar['value'] = i + 1
                time.sleep(0.5)
            
            msg = f"상품 등록 완료!\n성공: {success_count}개\n실패: {fail_count}개"
            self.log(f"✅ {msg}")
            self.root.after(0, lambda: messagebox.showinfo("완료", msg))
            
        except Exception as e:
            self.log(f"❌ 오류: {str(e)}")
            self.root.after(0, lambda: messagebox.showerror("오류", str(e)))
        finally:
            self.set_buttons_enabled(True)
            self.progress_bar['value'] = 0
    
    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = MainApp()
    app.run()