# -*- coding: utf-8 -*-
"""
불사자 이미지 번역 자동화 v2.2 (API 버전)
- 썸네일 이미지 자동 번역
- 옵션 이미지 자동 번역
- API 기반 백그라운드 처리 (브라우저 조작 없음)
- 동시 처리 지원
- v2.1: 이미지 단위 병렬 처리로 속도 대폭 향상
- v2.2: 상태/번역 필터에 '전체' 옵션 추가

by 프코노미
"""

import os
import time
import threading
import json
import requests
import websocket
import concurrent.futures
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# ==================== 설정 ====================
CONFIG_FILE = "bulsaja_translator_config.json"
DEBUG_PORT = 9222

# ==================== 설정 파일 관리 ====================
def load_config():
    """설정 파일 로드"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_config(config):
    """설정 파일 저장"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"설정 저장 실패: {e}")
        return False


# ==================== API 클라이언트 ====================
class BulsajaAPIClient:
    """불사자 API 클라이언트"""
    
    BASE_URL = "https://api.bulsaja.com/api"
    
    def __init__(self, access_token: str = "", refresh_token: str = ""):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.session = requests.Session()
        self._created_tags = set()
        if access_token:
            self._setup_session()
    
    def _setup_session(self):
        """세션 헤더 설정"""
        self.session.headers.update({
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'ko,en-US;q=0.9,en;q=0.8',
            'accesstoken': self.access_token,
            'refreshtoken': self.refresh_token,
            'content-type': 'application/json',
            'origin': 'https://www.bulsaja.com',
            'referer': 'https://www.bulsaja.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def update_tokens(self, access_token: str, refresh_token: str):
        """토큰 업데이트"""
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._setup_session()
    
    def test_connection(self) -> Tuple[bool, str, int]:
        """연결 테스트"""
        try:
            products, total = self.get_products(0, 1)
            return True, f"연결 성공 (총 {total}개 상품)", total
        except Exception as e:
            return False, str(e), 0
    
    def get_products(
        self,
        start_row: int = 0,
        end_row: int = 100,
        filter_model: Dict = None
    ) -> Tuple[List[Dict], int]:
        """상품 목록 조회"""
        url = f"{self.BASE_URL}/manage/list/serverside"
        
        payload = {
            "request": {
                "startRow": start_row,
                "endRow": end_row,
                "sortModel": [],
                "filterModel": filter_model or {}
            }
        }
        
        response = self.session.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        
        products = data.get('rowData', [])
        total_count = data.get('lastRow', len(products))
        return products, total_count
    
    def get_products_by_group(self, group_name: str, start: int = 0, limit: int = 1000,
                               status_filter: str = None, translate_filter: str = None,
                               tag_filter: str = None) -> Tuple[List[Dict], int]:
        """특정 그룹의 상품 조회 (필터 지원)"""
        filter_model = {}
        
        if group_name:
            filter_model["marketGroupName"] = {
                "filterType": "text",
                "type": "equals",
                "filter": group_name
            }
        
        if status_filter:
            status_value = {
                "수집완료": "0",
                "수정중": "1",
                "검토완료": "2",
                "수집중": "3",
                "판매중": "4"
            }.get(status_filter, status_filter)
            
            filter_model["status"] = {
                "filterType": "text",
                "type": "equals",
                "filter": status_value
            }
        
        if translate_filter:
            translate_value = {
                "번역완료": "1",
                "번역중": "0",
                "미번역": "2"
            }.get(translate_filter, translate_filter)
            
            filter_model["uploadDetailContents.imageTranslated"] = {
                "filterType": "text",
                "type": "equals",
                "filter": translate_value
            }
        
        if tag_filter:
            filter_model["groupFile"] = {
                "filterType": "text",
                "type": "contains",
                "filter": tag_filter
            }
        
        return self.get_products(start, start + limit, filter_model)
    
    def get_product_detail(self, product_id: str) -> Dict:
        """상품 상세 정보 조회"""
        url = f"{self.BASE_URL}/manage/sourcing-product/{product_id}"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()
    
    def translate_image(self, image_url: str, source_lang: str = "zh-CN", target_lang: str = "ko") -> Tuple[bool, str]:
        """이미지 번역 API 호출 (xiangji 번역 서비스)"""
        url = f"{self.BASE_URL}/sourcing/translate/xiangji"
        
        payload = {
            "imageUrl": image_url,
            "sourceLanguage": source_lang,
            "targetLanguage": target_lang
        }
        
        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            
            if data.get("Code") == 200 and data.get("Data"):
                translated_url = data["Data"].get("Url") or data["Data"].get("SslUrl")
                return True, translated_url
            else:
                return False, data.get("Message", "번역 실패")
                
        except requests.exceptions.HTTPError as e:
            return False, f"HTTP {e.response.status_code}: {e.response.text[:100]}"
        except Exception as e:
            return False, str(e)
    
    def upload_translated_image(self, image_url: str, product_id: str, image_type: str = "thumbnail", index: int = 0) -> Tuple[bool, str]:
        """번역된 이미지를 CDN에 업로드"""
        url = f"{self.BASE_URL}/manage/sourcing-product/upload/image"
        
        import random
        import string
        random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        filename = f"{random_str}.jpeg"
        
        key = f"sourcing-product/translated-images/{product_id}/{image_type}-image/{filename}"
        
        payload = {
            "image": image_url,
            "isBase64": False,
            "key": key,
            "resize": False
        }
        
        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            
            if data.get("msg") == "uploaded" and data.get("data"):
                cdn_url = data["data"].get("url")
                return True, cdn_url
            else:
                return False, f"업로드 실패: {data}"
                
        except requests.exceptions.HTTPError as e:
            return False, f"HTTP {e.response.status_code}: {e.response.text[:100]}"
        except Exception as e:
            return False, str(e)
    
    def update_product_fields(self, product_id: str, product_data: Dict) -> bool:
        """상품 필드 업데이트"""
        url = f"{self.BASE_URL}/sourcing/uploadfields/{product_id}"
        
        try:
            response = self.session.put(url, json=product_data)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"[DEBUG] update_product_fields 실패: {e}")
            return False
    
    def update_product_thumbnails(self, product_id: str, thumbnail_urls: List[str], original_product: Dict) -> bool:
        """상품 썸네일 URL 업데이트"""
        updated_product = original_product.copy()
        updated_product['uploadThumbnails'] = thumbnail_urls
        
        return self.update_product_fields(product_id, updated_product)
    
    def create_tag(self, tag_name: str) -> bool:
        """태그 생성"""
        if tag_name in self._created_tags:
            return True
        
        url = f"{self.BASE_URL}/manage/groups"
        payload = {"name": tag_name}
        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            self._created_tags.add(tag_name)
            return True
        except:
            self._created_tags.add(tag_name)
            return True
    
    def apply_tag(self, product_ids: List[str], tag_name: str) -> bool:
        """상품에 태그 적용"""
        url = f"{self.BASE_URL}/sourcing/bulk-update-groups"
        payload = {
            "productIds": product_ids if isinstance(product_ids, list) else [product_ids],
            "groupName": tag_name
        }
        
        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            return True
        except requests.exceptions.HTTPError:
            self.create_tag(tag_name)
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            return True


# ==================== 번역 자동화 클래스 ====================
class BulsajaImageTranslator:
    """불사자 이미지 번역 자동화 (API 버전) - v2.1 이미지 병렬 처리"""
    
    def __init__(self, gui):
        self.gui = gui
        self.api_client: Optional[BulsajaAPIClient] = None
        self.is_running = False
        
        # 통계
        self.stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
        }
        
        # 이미지 병렬 처리용 워커 수
        self.image_workers = 5  # 이미지 동시 처리 개수
    
    def log(self, message):
        """로그 출력"""
        if self.gui:
            self.gui.log(message)
        else:
            print(message)
    
    def init_api_client(self, access_token: str, refresh_token: str) -> Tuple[bool, str, int]:
        """API 클라이언트 초기화"""
        self.api_client = BulsajaAPIClient(access_token, refresh_token)
        return self.api_client.test_connection()
    
    def extract_tokens_from_browser(self, port: int = 9222) -> Tuple[bool, str, str, str]:
        """크롬 디버깅 모드에서 토큰 자동 추출"""
        try:
            tabs_url = f"http://127.0.0.1:{port}/json"
            try:
                response = requests.get(tabs_url, timeout=3)
                tabs = response.json()
            except requests.exceptions.ConnectionError:
                return False, "", "", f"크롬 디버그 포트 {port} 연결 실패"
            except Exception as e:
                return False, "", "", f"포트 연결 오류: {e}"
            
            bulsaja_tab = None
            tab_urls = []
            for tab in tabs:
                tab_urls.append(tab.get('url', ''))
                if 'bulsaja.com' in tab.get('url', ''):
                    bulsaja_tab = tab
                    break
            
            if not bulsaja_tab:
                return False, "", "", f"불사자 탭 없음. 열린 탭: {tab_urls[:3]}"
            
            ws_url = bulsaja_tab.get('webSocketDebuggerUrl')
            if not ws_url:
                return False, "", "", "WebSocket URL 없음"
            
            try:
                ws = websocket.create_connection(ws_url, timeout=5)
            except Exception as e:
                return False, "", "", f"WebSocket 연결 실패: {e}"
            
            cmd = {
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": """
                        (function() {
                            var tokenStr = localStorage.getItem('token');
                            if (tokenStr) {
                                try {
                                    var tokenObj = JSON.parse(tokenStr);
                                    if (tokenObj.state) {
                                        return JSON.stringify({
                                            accessToken: tokenObj.state.accessToken || '',
                                            refreshToken: tokenObj.state.refreshToken || ''
                                        });
                                    }
                                } catch(e) {}
                            }
                            return JSON.stringify({accessToken: '', refreshToken: ''});
                        })()
                    """,
                    "returnByValue": True
                }
            }
            
            ws.send(json.dumps(cmd))
            result = json.loads(ws.recv())
            ws.close()
            
            if 'result' in result and 'result' in result['result']:
                token_data = json.loads(result['result']['result'].get('value', '{}'))
                access_token = token_data.get('accessToken', '')
                refresh_token = token_data.get('refreshToken', '')
                
                if access_token and refresh_token:
                    return True, access_token, refresh_token, ""
                else:
                    return False, "", "", "토큰이 비어있음"
            
            return False, "", "", f"응답 파싱 실패: {result}"
            
        except Exception as e:
            return False, "", "", f"예외 발생: {e}"
    
    def translate_single_image(self, image_url: str, product_id: str, image_type: str, index: int) -> Tuple[bool, str, int]:
        """단일 이미지 번역 + 업로드
        
        Returns:
            (성공여부, 최종 CDN URL 또는 에러메시지, 인덱스)
        """
        if not image_url:
            return False, "빈 URL", index
        
        # 이미 번역된 이미지인지 확인
        if 'cdn.bulsaja.com' in image_url and 'translated' in image_url:
            return True, image_url, index
        
        # 1단계: 이미지 번역
        success, translated_url = self.api_client.translate_image(image_url)
        if not success:
            return False, translated_url, index
        
        # 2단계: CDN에 업로드
        success, cdn_url = self.api_client.upload_translated_image(
            translated_url, product_id, image_type, index
        )
        
        if not success:
            return False, cdn_url, index
        
        return True, cdn_url, index
    
    def process_product_thumbnails_parallel(self, product: Dict, max_workers: int = 5) -> Tuple[int, int, Dict]:
        """상품 썸네일 병렬 번역 처리
        
        Returns:
            (성공 개수, 실패 개수, 업데이트된 product)
        """
        product_id = product.get('ID', '')
        thumbnails = product.get('uploadThumbnails', [])
        
        if not thumbnails:
            return 0, 0, product
        
        success_count = 0
        fail_count = 0
        # 결과를 인덱스 순서대로 저장
        new_thumbnails = [None] * len(thumbnails)
        
        self.log(f"    🖼️ 썸네일 {len(thumbnails)}개 병렬 번역 시작...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for idx, thumb_url in enumerate(thumbnails):
                if not self.is_running:
                    break
                future = executor.submit(
                    self.translate_single_image, 
                    thumb_url, product_id, "thumbnail", idx
                )
                futures[future] = (idx, thumb_url)
            
            for future in concurrent.futures.as_completed(futures):
                idx, original_url = futures[future]
                try:
                    success, result_url, _ = future.result()
                    if success:
                        new_thumbnails[idx] = result_url
                        success_count += 1
                    else:
                        new_thumbnails[idx] = original_url  # 원본 유지
                        fail_count += 1
                        self.log(f"    [{idx+1}] ❌ {result_url[:50]}")
                except Exception as e:
                    new_thumbnails[idx] = original_url
                    fail_count += 1
                    self.log(f"    [{idx+1}] ❌ 예외: {e}")
        
        # None인 항목 원본으로 채우기
        for i, url in enumerate(new_thumbnails):
            if url is None:
                new_thumbnails[i] = thumbnails[i]
        
        self.log(f"    ✅ 썸네일 완료: {success_count}성공 / {fail_count}실패")
        
        product['uploadThumbnails'] = new_thumbnails
        return success_count, fail_count, product
    
    def process_product_options_parallel(self, product: Dict, max_workers: int = 5) -> Tuple[int, int, Dict]:
        """상품 옵션 이미지 병렬 번역 처리
        
        Returns:
            (성공 개수, 실패 개수, 업데이트된 product)
        """
        product_id = product.get('ID', '')
        skus = product.get('uploadSkus', [])
        
        if not skus:
            return 0, 0, product
        
        # 이미지가 있는 옵션만 필터링
        options_with_images = [(i, sku) for i, sku in enumerate(skus) if sku.get('urlRef')]
        
        if not options_with_images:
            return 0, 0, product
        
        success_count = 0
        fail_count = 0
        results = {}  # 인덱스별 결과
        
        self.log(f"    📦 옵션 이미지 {len(options_with_images)}개 병렬 번역 시작...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for sku_idx, sku in options_with_images:
                if not self.is_running:
                    break
                img_url = sku.get('urlRef', '')
                future = executor.submit(
                    self.translate_single_image,
                    img_url, product_id, "option", sku_idx
                )
                futures[future] = (sku_idx, img_url)
            
            for future in concurrent.futures.as_completed(futures):
                sku_idx, original_url = futures[future]
                try:
                    success, result_url, _ = future.result()
                    if success:
                        results[sku_idx] = result_url
                        success_count += 1
                    else:
                        fail_count += 1
                        self.log(f"    옵션[{sku_idx+1}] ❌ {result_url[:50]}")
                except Exception as e:
                    fail_count += 1
                    self.log(f"    옵션[{sku_idx+1}] ❌ 예외: {e}")
        
        # 결과 반영
        for sku_idx, new_url in results.items():
            product['uploadSkus'][sku_idx]['urlRef'] = new_url
        
        self.log(f"    ✅ 옵션 완료: {success_count}성공 / {fail_count}실패")
        
        return success_count, fail_count, product
    
    def process_single_product(self, product: Dict, do_thumbnail: bool, do_option: bool) -> Dict:
        """단일 상품 처리 (이미지 병렬)
        
        Returns:
            처리 결과 딕셔너리
        """
        product_id = product.get('ID', '')
        product_name = product.get('uploadCommonProductName', '')[:30]
        
        result = {
            'id': product_id,
            'name': product_name,
            'thumbnail_success': 0,
            'thumbnail_fail': 0,
            'option_success': 0,
            'option_fail': 0,
            'status': 'success'
        }
        
        try:
            # 썸네일 번역 (병렬)
            if do_thumbnail:
                ts, tf, product = self.process_product_thumbnails_parallel(product, self.image_workers)
                result['thumbnail_success'] = ts
                result['thumbnail_fail'] = tf
            
            # 옵션 이미지 번역 (병렬)
            if do_option:
                os, of, product = self.process_product_options_parallel(product, self.image_workers)
                result['option_success'] = os
                result['option_fail'] = of
            
            total_success = result['thumbnail_success'] + result['option_success']
            total_fail = result['thumbnail_fail'] + result['option_fail']
            
            # 상품 업데이트 (번역된 이미지 저장)
            if total_success > 0:
                self.log(f"  💾 상품 저장 중...")
                update_success = self.api_client.update_product_fields(product_id, product)
                if update_success:
                    self.log(f"  💾 저장 완료")
                else:
                    self.log(f"  ❌ 저장 실패")
                    result['status'] = 'partial'
            
            if total_fail > 0 and total_success == 0:
                result['status'] = 'failed'
            elif total_fail > 0:
                result['status'] = 'partial'
                
        except Exception as e:
            import traceback
            result['status'] = 'error'
            result['error'] = str(e)
            self.log(f"  ⚠️ 상세 오류: {e}")
            self.log(f"  {traceback.format_exc()}")
        
        return result
    
    def process_products(self, start_idx: int, count: int, concurrent_products: int = 3,
                        do_thumbnail: bool = True, do_option: bool = True,
                        group_name: str = None, tag_name: str = None,
                        status_filter: str = None, translate_filter: str = None,
                        tag_filter: str = None):
        """상품 처리 메인 루프"""
        
        self.stats = {"total": 0, "success": 0, "failed": 0, "skipped": 0}
        self.is_running = True
        
        self.log("")
        self.log("=" * 50)
        self.log(f"🚀 이미지 번역 자동화 시작 (API 모드 v2.1)")
        self.log(f"   시작: {start_idx}번 / 처리: {count}개")
        self.log(f"   상품 동시처리: {concurrent_products}개 / 이미지 동시처리: {self.image_workers}개")
        if group_name:
            self.log(f"   그룹: {group_name}")
        if status_filter:
            self.log(f"   상태: {status_filter}")
        if translate_filter:
            self.log(f"   상세페이지: {translate_filter}")
        if tag_filter:
            self.log(f"   태그필터: {tag_filter}")
        if do_thumbnail:
            self.log("   ✓ 썸네일 번역")
        if do_option:
            self.log("   ✓ 옵션 이미지 번역")
        self.log("=" * 50)
        
        try:
            # 상품 목록 조회
            self.log("📥 상품 목록 조회 중...")
            
            products, total = self.api_client.get_products_by_group(
                group_name, start_idx, count,
                status_filter=status_filter,
                translate_filter=translate_filter,
                tag_filter=tag_filter
            )
            
            if not products:
                self.log("❌ 처리할 상품이 없습니다")
                return
            
            self.log(f"📦 {len(products)}개 상품 로드됨")
            self.stats['total'] = len(products)
            
            # 배치 처리 (concurrent_products 개씩)
            processed = 0
            for batch_start in range(0, len(products), concurrent_products):
                if not self.is_running:
                    self.log("🛑 사용자에 의해 중지됨")
                    break
                
                batch = products[batch_start:batch_start + concurrent_products]
                self.log(f"\n--- 배치 {batch_start//concurrent_products + 1} ({len(batch)}개 상품 동시 처리) ---")
                
                # 상품 병렬 처리 (내부에서 이미지도 병렬)
                with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_products) as executor:
                    futures = {}
                    for idx, product in enumerate(batch):
                        product_id = product.get('ID', '')
                        product_name = product.get('uploadCommonProductName', '')[:20]
                        self.log(f"\n[{batch_start + idx + 1}] {product_name}")
                        future = executor.submit(self.process_single_product, product, do_thumbnail, do_option)
                        futures[future] = (batch_start + idx, product_id, product_name)
                    
                    for future in concurrent.futures.as_completed(futures):
                        idx, product_id, product_name = futures[future]
                        result = future.result()
                        
                        thumb_info = f"썸:{result['thumbnail_success']}" if do_thumbnail else ""
                        opt_info = f"옵:{result['option_success']}" if do_option else ""
                        
                        if result['status'] == 'success':
                            self.log(f"  ✅ [{idx+1}] 완료 ({thumb_info} {opt_info})")
                            self.stats['success'] += 1
                            
                            if tag_name:
                                self.api_client.apply_tag([product_id], tag_name)
                                
                        elif result['status'] == 'partial':
                            self.log(f"  ⚠️ [{idx+1}] 일부실패 ({thumb_info} {opt_info})")
                            self.stats['success'] += 1
                        else:
                            self.log(f"  ❌ [{idx+1}] 실패")
                            self.stats['failed'] += 1
                        
                        processed += 1
                        
                        if self.gui:
                            self.gui.update_progress(processed, len(products))
                
                # 배치 간 대기
                if batch_start + concurrent_products < len(products):
                    time.sleep(0.2)
            
        except Exception as e:
            self.log(f"❌ 처리 중 오류: {e}")
            import traceback
            self.log(traceback.format_exc())
        
        finally:
            self.log("")
            self.log("=" * 50)
            self.log(f"📊 처리 결과")
            self.log(f"   전체: {self.stats['total']}개")
            self.log(f"   성공: {self.stats['success']}개")
            self.log(f"   실패: {self.stats['failed']}개")
            self.log("=" * 50)
            
            self.is_running = False
            if self.gui:
                self.gui.on_finished()


# ==================== GUI 클래스 ====================
class App(tk.Tk):
    """메인 GUI 애플리케이션"""
    
    def __init__(self):
        super().__init__()
        
        self.title("불사자 이미지 번역 자동화 v2.2 (API - 병렬처리)")
        self.geometry("750x750")
        self.resizable(True, True)
        
        self.config_data = load_config()
        self.translator = BulsajaImageTranslator(self)
        self.worker_thread = None
        
        self.create_widgets()
        self.load_saved_settings()
        
        self.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def create_widgets(self):
        """위젯 생성"""
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # === API 연결 설정 ===
        conn_frame = ttk.LabelFrame(main_frame, text="🔑 불사자 API 연결", padding="10")
        conn_frame.pack(fill=tk.X, pady=(0, 10))
        
        token_row0 = ttk.Frame(conn_frame)
        token_row0.pack(fill=tk.X, pady=2)
        ttk.Button(token_row0, text="🌐 크롬 열기", command=self.open_debug_chrome, width=12).pack(side=tk.LEFT)
        ttk.Button(token_row0, text="🔑 토큰 가져오기", command=self.extract_tokens, width=14).pack(side=tk.LEFT, padx=5)
        self.token_status = ttk.Label(token_row0, text="", foreground="gray")
        self.token_status.pack(side=tk.LEFT, padx=5)
        ttk.Label(token_row0, text="포트:").pack(side=tk.LEFT, padx=(10, 0))
        self.port_var = tk.StringVar(value=str(DEBUG_PORT))
        ttk.Entry(token_row0, textvariable=self.port_var, width=6).pack(side=tk.LEFT, padx=2)
        
        token_row1 = ttk.Frame(conn_frame)
        token_row1.pack(fill=tk.X, pady=2)
        ttk.Label(token_row1, text="Access Token:", width=12).pack(side=tk.LEFT)
        self.access_token_var = tk.StringVar()
        ttk.Entry(token_row1, textvariable=self.access_token_var, show="*", width=50).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        token_row2 = ttk.Frame(conn_frame)
        token_row2.pack(fill=tk.X, pady=2)
        ttk.Label(token_row2, text="Refresh Token:", width=12).pack(side=tk.LEFT)
        self.refresh_token_var = tk.StringVar()
        ttk.Entry(token_row2, textvariable=self.refresh_token_var, show="*", width=50).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        token_row3 = ttk.Frame(conn_frame)
        token_row3.pack(fill=tk.X, pady=2)
        ttk.Button(token_row3, text="🔗 API 연결", command=self.connect_api).pack(side=tk.LEFT)
        self.api_conn_status = ttk.Label(token_row3, text="연결 안 됨", foreground="gray")
        self.api_conn_status.pack(side=tk.LEFT, padx=10)
        
        # === 처리 설정 ===
        config_frame = ttk.LabelFrame(main_frame, text="⚙️ 처리 설정", padding="10")
        config_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 그룹, 시작, 개수
        row1 = ttk.Frame(config_frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="그룹명:").pack(side=tk.LEFT)
        self.group_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.group_var, width=15).pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(row1, text="시작:").pack(side=tk.LEFT)
        self.start_var = tk.StringVar(value="0")
        ttk.Entry(row1, textvariable=self.start_var, width=6).pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(row1, text="개수:").pack(side=tk.LEFT)
        self.count_var = tk.StringVar(value="100")
        ttk.Entry(row1, textvariable=self.count_var, width=6).pack(side=tk.LEFT, padx=2)
        
        # 상태 필터, 번역 필터
        row2 = ttk.Frame(config_frame)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="상태필터:").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="전체")
        status_combo = ttk.Combobox(row2, textvariable=self.status_var, width=10, 
                                     values=["전체", "수집완료", "수정중", "검토완료", "수집중", "판매중"])
        status_combo.pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(row2, text="상세페이지:").pack(side=tk.LEFT)
        self.translate_var = tk.StringVar(value="전체")
        trans_combo = ttk.Combobox(row2, textvariable=self.translate_var, width=10,
                                    values=["전체", "번역완료", "번역중", "미번역"])
        trans_combo.pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(row2, text="태그필터:").pack(side=tk.LEFT)
        self.tag_filter_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.tag_filter_var, width=12).pack(side=tk.LEFT, padx=2)
        
        # 동시 처리 (상품/이미지)
        row3 = ttk.Frame(config_frame)
        row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="상품 동시처리:").pack(side=tk.LEFT)
        self.concurrent_var = tk.StringVar(value="2")
        ttk.Combobox(row3, textvariable=self.concurrent_var, width=4, 
                     values=["1", "2", "3", "4", "5"]).pack(side=tk.LEFT, padx=(2, 15))
        ttk.Label(row3, text="이미지 동시처리:").pack(side=tk.LEFT)
        self.img_concurrent_var = tk.StringVar(value="5")
        ttk.Combobox(row3, textvariable=self.img_concurrent_var, width=4,
                     values=["3", "5", "8", "10", "15"]).pack(side=tk.LEFT, padx=(2, 15))
        
        # 번역 옵션
        row4 = ttk.Frame(config_frame)
        row4.pack(fill=tk.X, pady=2)
        self.thumbnail_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row4, text="썸네일 번역", variable=self.thumbnail_var).pack(side=tk.LEFT)
        self.option_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row4, text="옵션이미지 번역", variable=self.option_var).pack(side=tk.LEFT, padx=10)
        
        # 완료 후 태그
        row5 = ttk.Frame(config_frame)
        row5.pack(fill=tk.X, pady=2)
        ttk.Label(row5, text="완료 후 태그:").pack(side=tk.LEFT)
        self.tag_var = tk.StringVar()
        ttk.Entry(row5, textvariable=self.tag_var, width=20).pack(side=tk.LEFT, padx=2)
        ttk.Label(row5, text="(비워두면 태그 안 함)", foreground="gray").pack(side=tk.LEFT, padx=5)
        
        # === 진행 상태 ===
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.progress_var = tk.StringVar(value="대기 중...")
        ttk.Label(progress_frame, textvariable=self.progress_var).pack(side=tk.LEFT)
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress_bar.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))
        
        # === 버튼 ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.btn_start = ttk.Button(btn_frame, text="🚀 시작", command=self.start_automation)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 10))
        
        self.btn_stop = ttk.Button(btn_frame, text="🛑 중지", command=self.stop, state="disabled")
        self.btn_stop.pack(side=tk.LEFT)
        
        ttk.Button(btn_frame, text="💾 설정 저장", command=self.save_settings).pack(side=tk.RIGHT)
        
        # === 로그 ===
        log_frame = ttk.LabelFrame(main_frame, text="📋 로그", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, state='disabled',
                                                   font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Footer
        footer = ttk.Frame(main_frame)
        footer.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(footer, text="v2.2 by 프코노미 (이미지 병렬처리)", foreground="gray").pack(side=tk.RIGHT)
    
    def load_saved_settings(self):
        """저장된 설정 로드"""
        if "port" in self.config_data:
            self.port_var.set(self.config_data["port"])
        if "access_token" in self.config_data:
            self.access_token_var.set(self.config_data["access_token"])
        if "refresh_token" in self.config_data:
            self.refresh_token_var.set(self.config_data["refresh_token"])
        if "start_idx" in self.config_data:
            self.start_var.set(self.config_data["start_idx"])
        if "count" in self.config_data:
            self.count_var.set(self.config_data["count"])
        if "concurrent" in self.config_data:
            self.concurrent_var.set(self.config_data["concurrent"])
        if "img_concurrent" in self.config_data:
            self.img_concurrent_var.set(self.config_data["img_concurrent"])
        if "group" in self.config_data:
            self.group_var.set(self.config_data["group"])
        if "tag" in self.config_data:
            self.tag_var.set(self.config_data["tag"])
    
    def save_settings(self):
        """설정 저장"""
        self.config_data["port"] = self.port_var.get()
        self.config_data["access_token"] = self.access_token_var.get()
        self.config_data["refresh_token"] = self.refresh_token_var.get()
        self.config_data["start_idx"] = self.start_var.get()
        self.config_data["count"] = self.count_var.get()
        self.config_data["concurrent"] = self.concurrent_var.get()
        self.config_data["img_concurrent"] = self.img_concurrent_var.get()
        self.config_data["group"] = self.group_var.get()
        self.config_data["tag"] = self.tag_var.get()
        save_config(self.config_data)
        self.log("✅ 설정 저장됨")
    
    def log(self, message):
        """로그 출력"""
        def _log():
            self.log_text.config(state='normal')
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')
        
        self.after(0, _log)
    
    def update_progress(self, current, total):
        """진행률 업데이트"""
        def _update():
            self.progress_var.set(f"{current}/{total} 처리 중...")
            self.progress_bar['value'] = (current / total) * 100 if total > 0 else 0
        
        self.after(0, _update)
    
    def open_debug_chrome(self):
        """크롬 디버그 모드로 열기"""
        import subprocess
        
        port = int(self.port_var.get().strip())
        profile_dir = f"C:\\chrome_debug_profile_{port}"
        
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        
        chrome_path = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_path = path
                break
        
        if not chrome_path:
            messagebox.showerror("오류", "Chrome을 찾을 수 없습니다")
            return
        
        url = "https://www.bulsaja.com/products/manage/list/"
        cmd = f'"{chrome_path}" --remote-debugging-port={port} --user-data-dir="{profile_dir}" --remote-allow-origins=* "{url}"'
        
        try:
            subprocess.Popen(cmd, shell=True)
            self.log(f"🌐 크롬 디버그 모드 실행 (포트: {port})")
            self.log("   불사자에 로그인 후 '토큰 가져오기' 클릭")
        except Exception as e:
            self.log(f"❌ 크롬 실행 실패: {e}")
    
    def extract_tokens(self):
        """크롬에서 토큰 자동 추출"""
        port = int(self.port_var.get().strip())
        self.log(f"🔍 크롬 포트 {port}에서 토큰 추출 중...")
        self.token_status.config(text="추출 중...", foreground="orange")
        
        def extract_task():
            success, access_token, refresh_token, error_msg = self.translator.extract_tokens_from_browser(port)
            
            if success:
                self.access_token_var.set(access_token)
                self.refresh_token_var.set(refresh_token)
                self.log("✅ 토큰 추출 성공!")
                self.token_status.config(text="✅ 추출 완료", foreground="green")
                self.after(500, self.connect_api)
            else:
                self.log(f"❌ 토큰 추출 실패: {error_msg}")
                self.token_status.config(text="❌ 실패", foreground="red")
        
        threading.Thread(target=extract_task, daemon=True).start()
    
    def connect_api(self):
        """API 연결"""
        access_token = self.access_token_var.get().strip()
        refresh_token = self.refresh_token_var.get().strip()
        
        if not access_token or not refresh_token:
            messagebox.showwarning("경고", "토큰을 입력하세요")
            return
        
        self.log("🔗 API 연결 중...")
        
        success, msg, total = self.translator.init_api_client(access_token, refresh_token)
        
        if success:
            self.api_conn_status.config(text=f"✅ 연결됨 ({total}개)", foreground="green")
            self.log(f"✅ {msg}")
        else:
            self.api_conn_status.config(text="❌ 실패", foreground="red")
            self.log(f"❌ 연결 실패: {msg}")
    
    def start_automation(self):
        """자동화 시작"""
        if not self.translator.api_client:
            messagebox.showwarning("경고", "먼저 API에 연결하세요")
            return
        
        if not self.thumbnail_var.get() and not self.option_var.get():
            messagebox.showwarning("경고", "번역 옵션을 선택하세요")
            return
        
        try:
            start_idx = int(self.start_var.get())
            count = int(self.count_var.get())
        except ValueError:
            messagebox.showerror("오류", "숫자를 입력하세요")
            return
        
        group_name = self.group_var.get().strip() or None
        tag_name = self.tag_var.get().strip() or None
        status_filter = self.status_var.get().strip()
        status_filter = None if status_filter in ("", "전체") else status_filter
        translate_filter = self.translate_var.get().strip()
        translate_filter = None if translate_filter in ("", "전체") else translate_filter
        tag_filter = self.tag_filter_var.get().strip() or None
        concurrent = int(self.concurrent_var.get())
        img_concurrent = int(self.img_concurrent_var.get())
        
        # 이미지 워커 수 설정
        self.translator.image_workers = img_concurrent
        
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.translator.is_running = True
        
        self.worker_thread = threading.Thread(
            target=self.translator.process_products,
            args=(start_idx, count, concurrent,
                  self.thumbnail_var.get(), self.option_var.get(),
                  group_name, tag_name,
                  status_filter, translate_filter, tag_filter),
            daemon=True
        )
        self.worker_thread.start()
    
    def stop(self):
        """중지"""
        self.translator.is_running = False
        self.log("🛑 중지 요청...")
    
    def on_finished(self):
        """완료 후 처리"""
        def _update():
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.progress_var.set("완료")
        
        self.after(0, _update)
    
    def on_close(self):
        """종료 시 정리"""
        self.translator.is_running = False
        self.save_settings()
        self.destroy()


# ==================== 메인 ====================
if __name__ == "__main__":
    app = App()
    app.mainloop()
