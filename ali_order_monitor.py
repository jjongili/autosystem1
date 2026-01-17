
import os
import sys
import time
import json
import asyncio
import re
from datetime import datetime
from collections import defaultdict
import gspread
from google.oauth2.service_account import Credentials
from playwright.async_api import async_playwright

# Configuration
CREDENTIALS_FILE = r"C:\autosystem\autosms-466614-951e91617c69.json"
SPREADSHEET_KEY = "1MHhu1GdvV1OGS8Wy3NxWOKuqFvgZpqgwn08kG70EDsY"  # Sales Sheet
DEBUG_PORT = 9300  # Default Chrome debug port

# Standard Columns (can be overridden by header search)
# We look for ANY of these keywords in the header row
COL_HEADERS_MAP = {
    "product_name": ["상품명", "품목명", "제품명", "Item Name", "Product Name", "상품"],
    "qty": ["수량", "Qty", "Quantity", "개수"],
    "revenue": ["실결제금액", "결제금액", "판매금액", "금액", "매출"],
    "ali_order_id": ["해외주문번호", "알리주문번호", "Ali Order ID", "Order ID", "주문번호(해외)"],
    "owner": ["사업자", "Operator", "Owner", "사업자명"],
    "market": ["마켓", "Market", "Platform", "사이트"]
}

class GoogleSheetManager:
    def __init__(self, key=SPREADSHEET_KEY, creds_file=CREDENTIALS_FILE):
        self.key = key
        self.creds_file = creds_file
        self.client = None
        self.sheet = None
        
    def connect(self):
        try:
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            creds = Credentials.from_service_account_file(self.creds_file, scopes=scopes)
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(self.key)
            print(f"[OK] Connected to Sheet: {self.sheet.title}")
            return True
        except Exception as e:
            print(f"[ERR] Failed to connect to Sheet: {e}")
            return False

    def get_data(self, month=None):
        if not month:
            month = f"{datetime.now().month}월"
        
        try:
            ws = self.sheet.worksheet(month)
            print(f"[INFO] Reading worksheet: {month}")
            data = ws.get_all_values()
            return data
        except Exception as e:
            print(f"[ERR] Failed to read worksheet '{month}': {e}")
            return []

class AliExpressFetcher:
    def __init__(self, port=DEBUG_PORT):
        self.port = port
        self.playwright = None
        self.browser = None
        self.page = None

    async def connect(self):
        try:
            self.playwright = await async_playwright().start()
            # Try to connect to existing Chrome with debugging port
            self.browser = await self.playwright.chromium.connect_over_cdp(f"http://localhost:{self.port}")
            context = self.browser.contexts[0]
            if context.pages:
                self.page = context.pages[0]
            else:
                self.page = await context.new_page()
            print(f"[OK] Connected to Chrome on port {self.port}")
            return True
        except Exception as e:
            print(f"[ERR] Failed to connect to Chrome: {e}")
            print("[INFO] Ensure Chrome is running with: chrome.exe --remote-debugging-port=9300 --user-data-dir=...")
            return False

    async def get_order_details(self, ali_order_ids):
        results = {}
        for order_id in ali_order_ids:
            if not order_id: continue
            
            print(f"[INFO] Fetching details for Ali Order ID: {order_id}")
            try:
                # Go to order detail page
                url = f"https://www.aliexpress.com/p/order/detail.html?orderId={order_id}"
                await self.page.goto(url, timeout=30000, wait_until="domcontentloaded")
                # Random sleep to behave like a human
                await asyncio.sleep(2)
                
                # Extract Data using Playwright Selectors
                # Note: Selectors need to be robust. Ali structure changes frequently.
                # We'll try common class names or structure.
                
                # Setup extraction script
                data = await self.page.evaluate("""() => {
                    const getText = (sel) => document.querySelector(sel)?.innerText?.trim() || "";
                    
                    // Product List
                    const products = [];
                    const items = document.querySelectorAll('.product-item'); // Hypothetical class
                    
                    // Fallback: Try generic structure if specific class fails
                    // This part depends heavily on actual Ali HTML structure which varies.
                    // For now we will try to grab the visible text that looks like product info.
                    
                    return {
                        "html_sample": document.body.innerHTML.substring(0, 500) // Debug hook
                    };
                }""")
                
                # Placeholder: Real selector logic required. 
                # Since we can't see the page live, we'll assume we can grab the body text 
                # and maybe parse the JSON embedded in the page (often in window.runParams).
                
                content = await self.page.content()
                
                # Extract from JSON if possible (often reliable in Ali)
                # Look for `window.runParams = { ... }` or similar data blocks
                
                order_info = {
                     "order_id": order_id,
                     "product_code": "N/A", # Needs parsing
                     "product_name": "N/A",
                     "option": "N/A",
                     "qty": "N/A",
                     "order_date": "N/A"
                }

                # Try explicit selectors (best guess based on standard Ali layout)
                # Order Date: Often at top "Order time: ..."
                date_el = await self.page.query_selector("div.order-info span.date, div:has-text('Order time:')")
                if date_el:
                    order_info['order_date'] = await date_el.inner_text()
                    
                # Product Info
                # We save the raw content or a summary for now if selectors fail
                results[order_id] = order_info
                
            except Exception as e:
                print(f"[WARN] Error fetching {order_id}: {e}")
                results[order_id] = {"error": str(e)}
                
        return results

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

def find_col_idx(headers, keywords):
    for idx, h in enumerate(headers):
        h_clean = h.replace("\n", "").strip()
        # Find if any keyword is *part of* the header (case insensitive)
        for k in keywords:
            if k.lower() in h_clean.lower():
                return idx
    return -1

def analyze_sheet():
    manager = GoogleSheetManager()
    if not manager.connect():
        return
    
    data = manager.get_data() # Gets current month
    if not data or len(data) < 2:
        print("Empty data.")
        return

    # In server.py, get_sales_from_sheet uses row 2 as headers (index 1)
    # Let's verify that assumption by printing the first few rows
    headers = data[1] 
    rows = data[2:]
    
    print(f"Raw Headers (Row 2): {headers}")
    
    # Identify Columns
    col_idx = {}
    for key, keywords in COL_HEADERS_MAP.items():
        col_idx[key] = find_col_idx(headers, keywords)
        
    # Manual Override/Fallback based on known structure (ali_tracking_gui.py)
    # Row 1 is usually header.
    # AD(30) = Platform, AE(31) = Ali Order ID
    # J(10) = Seller Product Code, K(11) = Product Name? Let's verify with printed headers.
    
    # Based on printed headers:
    # Index 9: Seller Product Code (looks like ID)
    # Index 10: Product Name (likely)
    # Index 30: Ali Order ID
    
    if col_idx["ali_order_id"] == -1:
        col_idx["ali_order_id"] = 30 # AE column (1-based 31)
        print("  [Fallback] Mapped 'ali_order_id' -> Index 30")
        
    if col_idx["product_name"] == 9: # Probably mapped to Code
        col_idx["product_name"] = 10
        print("  [Fallback] Remapped 'product_name' -> Index 10 (Correction from Code to Name)")
        
    print("Final Column Indices:", col_idx)

    # Aggregation for Top 40
    product_stats = defaultdict(lambda: {"qty": 0, "revenue": 0, "count": 0, "ali_ids": set()})
    
    for row in rows:
        # Skip if row is too short
        if len(row) < 31: continue
        
        name_idx = col_idx.get("product_name")
        qty_idx = col_idx.get("qty")
        rev_idx = col_idx.get("revenue")
        ali_idx = col_idx.get("ali_order_id")
        
        if name_idx == -1: continue # Can't aggregate without name
        
        p_name = row[name_idx].strip()
        if not p_name: continue
        
        qty = 0
        if qty_idx != -1 and len(row) > qty_idx:
            try: qty = int(row[qty_idx].replace(",",""))
            except: pass
            
        rev = 0
        if rev_idx != -1 and len(row) > rev_idx:
            try: rev = int(row[rev_idx].replace(",","").replace("원",""))
            except: pass
            
        ali_id = ""
        if ali_idx != -1 and len(row) > ali_idx:
            ali_id = row[ali_idx].strip()
            # Basic validation for Ali Order ID (digits)
            if not ali_id.isdigit():
                ali_id = ""
            
        product_stats[p_name]["qty"] += qty
        product_stats[p_name]["revenue"] += rev
        product_stats[p_name]["count"] += 1
        if ali_id:
            product_stats[p_name]["ali_ids"].add(ali_id)

    # Sort -> Top 40 (by Revenue)
    sorted_products = sorted(product_stats.items(), key=lambda x: x[1]['revenue'], reverse=True)
    top_40 = sorted_products[:40]
    
    print(f"\n[INFO] Top 40 Products (by Revenue) - {datetime.now().strftime('%Y-%m')}")
    print(f"{'Rank':<5} {'Product Name':<40} {'Revenue':<15} {'Qty':<5} {'Orders'}")
    print("-" * 80)
    
    ali_ids_to_fetch = set()
    
    for rank, (name, stats) in enumerate(top_40, 1):
        # Truncate long names for display
        disp_name = (name[:35] + '..') if len(name) > 35 else name
        print(f"{rank:<5} {disp_name:<40} {stats['revenue']:<15,} {stats['qty']:<5} {len(stats['ali_ids'])}")
        ali_ids_to_fetch.update(stats['ali_ids'])
        
    print("-" * 80)
    print(f"Total Unique AliExpress Orders linked to Top 40: {len(ali_ids_to_fetch)}")
    
    return list(ali_ids_to_fetch)

async def main():
    ali_ids = analyze_sheet()
    
    if not ali_ids:
        print("No AliExpress IDs found in Top 40 products.")
        return

    print(f"\n[INFO] Attempting to fetch details for {len(ali_ids)} orders...")
    fetcher = AliExpressFetcher()
    if await fetcher.connect():
        # Fetch first 5 
        details = await fetcher.get_order_details(ali_ids[:5])
        print("\n[INFO] Fetched Details (Sample of first 5):")
        print(json.dumps(details, indent=2, ensure_ascii=False))
        
        # Save full list to file
        if len(ali_ids) > 0:
            with open("ali_top40_details.json", "w", encoding="utf-8") as f:
                json.dump(details, f, ensure_ascii=False, indent=2)
            print(f"[INFO] Saved details to ali_top40_details.json")
            
        await fetcher.close()
    else:
        print("[WARN] Skipping AliExpress fetch (Browser not connected)")

if __name__ == "__main__":
    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
