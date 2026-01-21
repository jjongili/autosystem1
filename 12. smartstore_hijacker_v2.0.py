import os
import sys
import json
import re
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
from datetime import datetime
from typing import Dict, List, Any, Tuple, Optional
import threading
import base64

# Third-party libraries
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
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

try:
    import bcrypt
except ImportError:
    print("pip install bcrypt")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

# ================= Constants & Config =================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "integrated_config.json")

# ================= Global Utilities =================
def truncate_text(text: str, max_length: int = 49000) -> str:
    if text and len(text) > max_length:
        return text[:max_length] + "...[truncated]"
    return text

def image_urls_to_html(image_urls_str: str) -> str:
    if not image_urls_str: return ''
    urls = []
    for line in image_urls_str.replace(',', '\n').split('\n'):
        url = line.strip()
        if url and (url.startswith('http')):
            urls.append(url)
    if not urls: return ''
    html_parts = ['<div style="text-align:center;">']
    for url in urls:
        html_parts.append(f'<img src="{url}" style="max-width:100%;">')
    html_parts.append('</div>')
    return ''.join(html_parts)

def extract_video_from_html(html_content: str) -> str:
    if not html_content or not BeautifulSoup: return ''
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src', '')
            if any(x in src for x in ['youtube', 'naver', 'vimeo']): return src
        videos = soup.find_all('video')
        for video in videos:
            src = video.get('src') or (video.find('source').get('src') if video.find('source') else None)
            if src: return src
    except: pass
    return ''

# ================= Naver Commerce API Class =================
class NaverCommerceAPI:
    BASE_URL = "https://api.commerce.naver.com/external"
    
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.access_token = None
        self.token_expires = 0
    
    def _generate_signature(self, timestamp: int) -> str:
        password = f"{self.client_id}_{timestamp}"
        hashed = bcrypt.hashpw(password.encode('utf-8'), self.client_secret.encode('utf-8'))
        return base64.b64encode(hashed).decode('utf-8')
    
    def get_access_token(self) -> str:
        current_time = int(time.time() * 1000)
        if self.access_token and current_time < self.token_expires - 60000:
            return self.access_token
        
        timestamp = current_time
        signature = self._generate_signature(timestamp)
        
        url = f"{self.BASE_URL}/v1/oauth2/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        data = {
            "client_id": self.client_id, "timestamp": timestamp,
            "client_secret_sign": signature, "grant_type": "client_credentials", "type": "SELF"
        }
        
        response = requests.post(url, headers=headers, data=data, timeout=30)
        if response.status_code == 200:
            result = response.json()
            self.access_token = result.get("access_token")
            expires_in = result.get("expires_in", 21600)
            self.token_expires = current_time + (expires_in * 1000)
            return self.access_token
        raise Exception(f"인증 실패: {response.status_code}")

    def _get_headers(self) -> Dict[str, str]:
        token = self.get_access_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def get_product_list(self, page: int = 1, size: int = 100) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/v1/products/search"
        payload = {"page": page, "size": min(size, 500)}
        response = requests.post(url, headers=self._get_headers(), json=payload, timeout=30)
        if response.status_code == 200: return response.json()
        raise Exception(f"목록 조회 실패: {response.status_code}")

    def get_product_detail(self, product_no: str) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/v2/products/origin-products/{product_no}"
        for attempt in range(3):
            response = requests.get(url, headers=self._get_headers(), timeout=30)
            if response.status_code == 200: return response.json()
            if response.status_code == 429: time.sleep(2); continue
            raise Exception(f"상세 조회 실패: {response.status_code}")
        raise Exception("상세 조회 실패 (Rate Limit)")

    def create_product(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/v2/products"
        response = requests.post(url, headers=self._get_headers(), json=product_data, timeout=60)
        if response.status_code in [200, 201]: return response.json()
        raise Exception(f"업로드 실패: {response.text}")

# ================= Google Sheets Manager =================
class GoogleSheetsManager:
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
        "최소구매수량", "최대구매수량", "할인율", "할인가", "원본상품번호", "수집URL"
    ]

    def __init__(self, credentials_path: str):
        self.credentials_path = credentials_path
        self._connect()

    def _connect(self):
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
        worksheet.update('A1', [self.HEADERS])

    def clear_data(self, worksheet):
        worksheet.batch_clear(['A2:AL10000'])

    def append_products(self, worksheet, products: List[List[Any]]):
        if products: worksheet.append_rows(products, value_input_option='RAW')

    def get_all_products(self, worksheet) -> List[Dict[str, Any]]:
        return worksheet.get_all_records()

# ================= Mappings =================
def product_to_row(product: Dict[str, Any], original_no: str, collect_url: str = '') -> List[Any]:
    origin = product.get('originProduct', product)
    detail_attr = origin.get('detailAttribute', {})
    images = origin.get('images', {})
    main_image = ''
    additional_images = []
    
    if isinstance(images, dict):
        rep = images.get('representativeImage', {})
        if rep: main_image = rep.get('url', '')
        opts = images.get('optionalImages', [])
        for img in opts:
            u = img.get('url') if isinstance(img, dict) else img
            if u: additional_images.append(u)
    
    detail_content = origin.get('detailContent', '') or ''
    video_url = extract_video_from_html(detail_content)
    option_info = detail_attr.get('optionInfo', {})
    delivery = origin.get('deliveryInfo', {})
    delivery_fee = delivery.get('deliveryFee', {})
    claim = delivery.get('claimDeliveryInfo', {})
    as_info = detail_attr.get('afterServiceInfo', {})
    orig_area = detail_attr.get('originAreaInfo', {})
    naver_search = detail_attr.get('naverShoppingSearchInfo', {})
    
    policy = detail_attr.get('immediateDiscountPolicy', {})
    method = policy.get('discountMethod', {})
    val, unit = method.get('value', 0), method.get('unitType', '')
    rate = val if unit == 'PERCENT' else 0
    
    return [
        origin.get('originProductNo', original_no), origin.get('name', ''), 
        origin.get('salePrice', 0), origin.get('regularPrice', origin.get('salePrice', 0)),
        origin.get('stockQuantity', 99), origin.get('leafCategoryId', ''), '',
        origin.get('statusType', 'SALE'), '', main_image, ','.join(additional_images),
        video_url, truncate_text(detail_content),
        '사용' if option_info.get('optionCombinations') else '미사용',
        json.dumps(option_info, ensure_ascii=False),
        delivery.get('deliveryType', 'DELIVERY'),
        delivery_fee.get('deliveryFeeType', 'FREE'),
        delivery_fee.get('baseFee', 0), claim.get('returnDeliveryFee', 3000),
        claim.get('exchangeDeliveryFee', 6000),
        as_info.get('afterServiceTelephoneNumber', ''),
        as_info.get('afterServiceGuideContent', ''),
        orig_area.get('originAreaCode', '03'), orig_area.get('content', '상세설명참조'),
        naver_search.get('manufacturerName', ''), naver_search.get('brandName', ''),
        naver_search.get('modelName', ''), '{}', '{}',
        ','.join(origin.get('tags', [])), '', '', 1, 99, rate, 0, original_no, collect_url
    ]

def row_to_product(row: Dict[str, Any]) -> Dict[str, Any]:
    images = {"representativeImage": {"url": row.get('대표이미지URL', '')}}
    opt_imgs = []
    if row.get('추가이미지URLs'):
        for u in str(row['추가이미지URLs']).split(','):
            if u.strip(): opt_imgs.append({"url": u.strip()})
    if opt_imgs: images["optionalImages"] = opt_imgs
    
    detail = row.get('상세설명HTML', '')
    if detail and not detail.startswith('<'): detail = image_urls_to_html(detail)
    
    opt_json = row.get('옵션정보JSON', '{}')
    try:
        opt_info = json.loads(opt_json); oc = opt_info.get('optionCombinations', [])
        for c in oc:
            for k in ['id', 'sellerManagerCode']:
                if k in c: del c[k]
    except: opt_info = {}

    return {
        "originProduct": {
            "name": row.get('상품명', ''), "statusType": row.get('상품상태코드', 'SALE'), "saleType": "NEW",
            "leafCategoryId": str(row.get('카테고리ID', '') or "50000000"), "detailContent": detail,
            "images": images, "salePrice": int(row.get('판매가', 0)), "stockQuantity": int(row.get('재고수량', 99)),
            "taxType": "TAX",
            "deliveryInfo": {
                "deliveryType": "DELIVERY", "deliveryAttributeType": "NORMAL", "deliveryCompany": "CJGLS",
                "deliveryFee": {
                    "deliveryFeeType": row.get('배송비유형', 'FREE'),
                    "baseFee": int(row.get('기본배송비', 0)), "deliveryFeePayType": "PREPAID"
                },
                "claimDeliveryInfo": {
                    "returnDeliveryFee": int(row.get('반품배송비', 3000)), "exchangeDeliveryFee": int(row.get('교환배송비', 6000))
                }
            },
            "detailAttribute": {
                "originAreaInfo": {"originAreaCode": "03", "content": row.get('원산지명', '상세설명참조')},
                "afterServiceInfo": {"afterServiceTelephoneNumber": "010-0000-0000", "afterServiceGuideContent": "상세설명참조"},
                "naverShoppingSearchInfo": {"brandName": row.get('브랜드', ''), "manufacturerName": row.get('제조사', '')},
                "certificationTargetExcludeContent": {"kcCertifiedProductExclusionYn": "TRUE", "childCertifiedProductExclusionYn": True},
                "productInfoProvidedNotice": {"productInfoProvidedNoticeType": "ETC", "etc": {"itemName": "상세설명참조", "manufacturer": "협력사"}}
            }
        },
        "smartstoreChannelProduct": {"channelProductName": row.get('상품명', '')},
        "optionInfo": opt_info if opt_info and opt_info.get('optionCombinations') else None
    }

# ================= Scraper / Collector =================
class SmartStoreCollector:
    def __init__(self, log_callback=None):
        self.driver = None
        self.log_callback = log_callback

    def log(self, msg):
        if self.log_callback: self.log_callback(msg)

    def start_browser(self):
        if self.driver: return
        self.log("🌐 브라우저 시작 중...")
        self.driver = uc.Chrome(options=uc.ChromeOptions())
        self.driver.get("https://nid.naver.com/nidlogin.login")
        self.log("✅ 브라우저 준비 완료.")

    def close(self):
        if self.driver: self.driver.quit(); self.driver = None

    def scrape_url(self, url: str) -> Optional[List[Any]]:
        try:
            self.driver.get(url)
            time.sleep(3)
            data = self.driver.execute_script("return window.__PRELOADED_STATE__;")
            if not data: return None
            
            pno_match = re.search(r'/products/(\d+)', url)
            if not pno_match: return None
            pno = pno_match.group(1)
            
            product = None
            if 'simpleProductForDetailPage' in data:
                spd = data['simpleProductForDetailPage']
                product = spd.get('A') or spd.get('B') or spd
            if not product and 'productDetail' in data:
                product = data['productDetail'].get(pno)
                
            if product and product.get('name'):
                return product_to_row(product, pno, url)
        except Exception as e: self.log(f"⚠️ {url} 수집 에러: {e}")
        return None

# ================= GUI App =================
class IntegratedApp:
    def __init__(self):
        self.root = tk.Tk(); self.root.title("스마트스토어 통합 도구 v2.0"); self.root.geometry("1000x850")
        self.config = {}; self.load_config()
        self.collector = SmartStoreCollector(log_callback=self.log_c)
        self.init_ui(); self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f: self.config = json.load(f)
            except: pass

    def save_config(self):
        self.config.update({"json_path": self.json_path_var.get().strip(), 
                            "sheet_id": self.sheet_id_var.get().strip(),
                            "source_cid": self.src_cid_var.get().strip(), 
                            "source_csec": self.src_csec_var.get().strip(),
                            "target_cid": self.tgt_cid_var.get().strip(), 
                            "target_csec": self.tgt_csec_var.get().strip()})
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(self.config, f, ensure_ascii=False, indent=2)
        messagebox.showinfo("저장", "설정이 저장되었습니다.")

    def init_ui(self):
        nb = ttk.Notebook(self.root); nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Tab 1: Collection
        t1 = ttk.Frame(nb); nb.add(t1, text=" 🛒 상품 수집 (Scraper/Fetch) ")
        f1 = ttk.Frame(t1, padding=10); f1.pack(fill=tk.BOTH, expand=True)

        # SOURCE API SECTION (Collection)
        s_f = ttk.LabelFrame(f1, text=" 📥 소스 API 설정 (수집용) ", padding=10); s_f.pack(fill=tk.X, pady=5)
        self.src_cid_var = tk.StringVar(value=self.config.get("source_cid", ""))
        self.src_csec_var = tk.StringVar(value=self.config.get("source_csec", ""))
        ttk.Label(s_f, text="Source Client ID:").grid(row=0, column=0, sticky='w')
        ttk.Entry(s_f, textvariable=self.src_cid_var, width=50).grid(row=0, column=1, padx=5, sticky='ew')
        ttk.Label(s_f, text="Source Client Secret:").grid(row=1, column=0, sticky='w', pady=5)
        ttk.Entry(s_f, textvariable=self.src_csec_var, width=50, show='*').grid(row=1, column=1, padx=5, pady=5, sticky='ew')

        mode_f = ttk.LabelFrame(f1, text=" 수집 방식 선택 ", padding=5); mode_f.pack(fill=tk.X, pady=5)
        self.col_mode = tk.StringVar(value="url")
        ttk.Radiobutton(mode_f, text="URL 스크래퍼 (브라우저)", variable=self.col_mode, value="url").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(mode_f, text="API 패치 (소스 마켓)", variable=self.col_mode, value="api").pack(side=tk.LEFT, padx=10)
        
        ttk.Label(f1, text="URL (여러 줄 입력):").pack(anchor='w')
        self.url_text = scrolledtext.ScrolledText(f1, height=5); self.url_text.pack(fill=tk.X, pady=5)
        
        btn_f = ttk.Frame(f1); btn_f.pack(fill=tk.X)
        ttk.Button(btn_f, text="브라우저 시작", command=self.collector.start_browser).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_f, text="수집 및 시드 저장", command=self.run_collection).pack(side=tk.LEFT, padx=5)
        self.log_collect = scrolledtext.ScrolledText(f1, height=20, state='disabled'); self.log_collect.pack(fill=tk.BOTH, expand=True, pady=10)

        # Tab 2: Upload
        t2 = ttk.Frame(nb); nb.add(t2, text=" 🚀 상품 업로드 (Uploader) ")
        f2 = ttk.Frame(t2, padding=10); f2.pack(fill=tk.BOTH, expand=True)

        # TARGET API SECTION (Upload)
        u_f = ttk.LabelFrame(f2, text=" 📤 타겟 API 설정 (업로드용) ", padding=10); u_f.pack(fill=tk.X, pady=5)
        self.tgt_cid_var = tk.StringVar(value=self.config.get("target_cid", ""))
        self.tgt_csec_var = tk.StringVar(value=self.config.get("target_csec", ""))
        ttk.Label(u_f, text="Target Client ID:").grid(row=0, column=0, sticky='w')
        ttk.Entry(u_f, textvariable=self.tgt_cid_var, width=50).grid(row=0, column=1, padx=5, sticky='ew')
        ttk.Label(u_f, text="Target Client Secret:").grid(row=1, column=0, sticky='w', pady=5)
        ttk.Entry(u_f, textvariable=self.tgt_csec_var, width=50, show='*').grid(row=1, column=1, padx=5, pady=5, sticky='ew')

        ttk.Button(f2, text="업로드 시작", command=self.run_upload).pack(pady=10)
        self.log_upload = scrolledtext.ScrolledText(f2, height=30, state='disabled'); self.log_upload.pack(fill=tk.BOTH, expand=True)

        # Tab 3: Settings
        t3 = ttk.Frame(nb); nb.add(t3, text=" ⚙️ 환경 설정 (Settings) ")
        f3 = ttk.Frame(t3, padding=20); f3.pack(fill=tk.BOTH, expand=True)
        
        # Google Section
        g_f = ttk.LabelFrame(f3, text=" ☁️ 구글 API 설정 ", padding=10); g_f.pack(fill=tk.X, pady=5)
        self.json_path_var = tk.StringVar(value=self.config.get("json_path", ""))
        self.sheet_id_var = tk.StringVar(value=self.config.get("sheet_id", ""))
        ttk.Label(g_f, text="credentials.json 경로:").grid(row=0, column=0, sticky='w')
        ttk.Entry(g_f, textvariable=self.json_path_var, width=50).grid(row=0, column=1, padx=5)
        ttk.Button(g_f, text="찾기", command=lambda: self.json_path_var.set(filedialog.askopenfilename())).grid(row=0, column=2)
        ttk.Label(g_f, text="Spreadsheet ID:").grid(row=1, column=0, sticky='w', pady=5)
        ttk.Entry(g_f, textvariable=self.sheet_id_var, width=50).grid(row=1, column=1, padx=5, pady=5, columnspan=2, sticky='ew')
        
        ttk.Button(f3, text="💾 설정 저장", command=self.save_config, width=20).pack(pady=20)

    def log_c(self, msg): self.write_log(self.log_collect, msg)
    def log_u(self, msg): self.write_log(self.log_upload, msg)
    def write_log(self, widget, msg):
        widget.config(state='normal'); widget.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n"); widget.see(tk.END); widget.config(state='disabled'); self.root.update_idletasks()

    def run_collection(self): threading.Thread(target=self._worker_collect, daemon=True).start()

    def _worker_collect(self):
        try:
            mode = self.col_mode.get()
            mgr = GoogleSheetsManager(self.json_path_var.get())
            ws = mgr.get_or_create_sheet(self.sheet_id_var.get(), "수집상품")
            rows = []
            if mode == "api":
                cid, csec = self.src_cid_var.get(), self.src_csec_var.get()
                if not cid or not csec: self.log_c("❌ 소스 API 정보를 입력하세요."); return
                api = NaverCommerceAPI(cid, csec)
                self.log_c("🚀 API 상품 목록 조회 시작...")
                plist = api.get_product_list().get('contents', [])
                for i, p in enumerate(plist):
                    pno = p.get('originProductNo'); self.log_c(f"[{i+1}/{len(plist)}] 패치 중: {pno}")
                    rows.append(product_to_row(api.get_product_detail(pno), pno)); time.sleep(0.5)
            else:
                urls = [u.strip() for u in self.url_text.get('1.0', tk.END).split('\n') if u.strip()]
                if not self.collector.driver: self.log_c("❌ 브라우저를 먼저 시작하세요."); return
                for url in urls: self.log_c(f"🔍 스크래핑: {url}"); r = self.collector.scrape_url(url); 
                if r: rows.append(r)
            
            if rows: 
                mgr.clear_data(ws); mgr.setup_headers(ws); mgr.append_products(ws, rows); 
                self.log_c(f"✅ 총 {len(rows)}개 시트 저장 완료!")
                messagebox.showinfo("성공", f"{len(rows)}개 상품 수집 완료")
        except Exception as e: self.log_c(f"❌ 에러: {e}")

    def run_upload(self): threading.Thread(target=self._worker_upload, daemon=True).start()

    def _worker_upload(self):
        try:
            cid, csec = self.tgt_cid_var.get(), self.tgt_csec_var.get()
            if not cid or not csec: self.log_u("❌ 타겟 API 정보를 입력하세요."); return
            api = NaverCommerceAPI(cid, csec)
            mgr = GoogleSheetsManager(self.json_path_var.get())
            ws = mgr.get_or_create_sheet(self.sheet_id_var.get(), "수집상품"); data = mgr.get_all_products(ws)
            if not data: self.log_u("❌ 업로드할 데이터가 없습니다."); return
            self.log_u(f"🚀 {len(data)}개 업로드 시작...")
            for i, row in enumerate(data):
                try: api.create_product(row_to_product(row)); self.log_u(f"[{i+1}/{len(data)}] ✅ 성공: {row.get('상품명')[:25]}...")
                except Exception as e: self.log_u(f"[{i+1}/{len(data)}] ❌ 실패: {e}")
                time.sleep(1.5)
            messagebox.showinfo("완료", "업로드 작업이 종료되었습니다.")
        except Exception as e: self.log_u(f"❌ 치명적 에러: {e}")

    def on_closing(self): self.collector.close(); self.root.destroy()

if __name__ == "__main__": IntegratedApp().root.mainloop()
