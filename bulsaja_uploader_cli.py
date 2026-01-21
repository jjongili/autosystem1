# -*- coding: utf-8 -*-
"""
불사자 업로더 CLI - 터미널에서 실행되는 단일 세션 업로더
멀티세션 GUI에서 호출됨

사용법:
    python bulsaja_uploader_cli.py --config config.json --session 1 --group "그룹명"
    python bulsaja_uploader_cli.py --config config.json --session 1 --group "그룹명" --simulate
"""

import os
import sys
import json
import time
import random
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

# 공통 모듈
sys.path.insert(0, str(Path(__file__).parent))
from bulsaja_common import (
    filter_bait_options, select_main_option, BulsajaAPIClient, load_bait_keywords
)

# 콘솔 색상 (Windows)
class Colors:
    RESET = '\033[0m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'


def colored(text, color):
    """색상 적용"""
    return f"{color}{text}{Colors.RESET}"


class CLIUploader:
    """CLI 업로더"""

    def __init__(self, config: dict, session_id: int, group_name: str):
        self.config = config
        self.session_id = session_id
        self.group_name = group_name

        # API 클라이언트
        self.api = BulsajaAPIClient(
            config.get('access_token', ''),
            config.get('refresh_token', '')
        )

        # 설정값
        self.upload_count = config.get('upload_count', 10)
        self.option_count = config.get('option_count', 5)
        self.option_sort = config.get('option_sort', 'price_asc')
        self.status_filters = config.get('status_filters', ['0', '1', '2'])
        self.market_name = config.get('market_name', '스마트스토어')
        self.skip_sku_update = config.get('skip_sku_update', False)
        self.skip_price_update = config.get('skip_price_update', False)
        self.prevent_duplicate = config.get('prevent_duplicate', True)

        # 통계
        self.stats = {
            'success': 0,
            'failed': 0,
            'skipped': 0,
            'total': 0
        }

    def log(self, msg: str, level: str = "info"):
        """로그 출력"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        session_tag = f"[S{self.session_id}]"

        if level == "error":
            print(f"{colored(timestamp, Colors.CYAN)} {colored(session_tag, Colors.MAGENTA)} {colored('ERROR', Colors.RED)} {msg}")
        elif level == "success":
            print(f"{colored(timestamp, Colors.CYAN)} {colored(session_tag, Colors.MAGENTA)} {colored('OK', Colors.GREEN)} {msg}")
        elif level == "warning":
            print(f"{colored(timestamp, Colors.CYAN)} {colored(session_tag, Colors.MAGENTA)} {colored('WARN', Colors.YELLOW)} {msg}")
        elif level == "progress":
            print(f"{colored(timestamp, Colors.CYAN)} {colored(session_tag, Colors.MAGENTA)} {colored('>>>', Colors.BLUE)} {msg}")
        else:
            print(f"{colored(timestamp, Colors.CYAN)} {colored(session_tag, Colors.MAGENTA)} {msg}")

    def get_market_id(self) -> Optional[int]:
        """마켓 그룹에서 마켓 ID 조회 (v1.5 방식)"""
        import requests

        market_type_map = {
            '스마트스토어': 'SMARTSTORE',
            '11번가': 'ST11',
            'G마켓/옥션': 'ESM',
            '쿠팡': 'COUPANG'
        }
        target_type = market_type_map.get(self.market_name, 'SMARTSTORE')

        try:
            # 1. 그룹 목록에서 그룹 ID 조회
            groups_url = f"{self.api.BASE_URL}/market/groups/"
            response = self.api.session.post(groups_url, json={})
            response.raise_for_status()
            groups = response.json()

            group_id = None
            for group in groups:
                if group.get('name') == self.group_name:
                    group_id = group.get('id')
                    break

            if not group_id:
                self.log(f"그룹 '{self.group_name}'을 찾을 수 없음", "error")
                return None

            self.log(f"그룹 ID: {group_id}")

            # 2. 그룹 내 마켓 목록 조회
            markets_url = f"{self.api.BASE_URL}/market/group/{group_id}/markets"
            response = self.api.session.get(markets_url)
            response.raise_for_status()
            markets = response.json()

            # 3. 마켓 타입에 맞는 ID 찾기
            for market in markets:
                if market.get('type') == target_type:
                    market_id = market.get('id')
                    self.log(f"마켓 ID: {market_id} ({target_type})")
                    return market_id

            self.log(f"그룹 '{self.group_name}'에서 {self.market_name} 마켓을 찾을 수 없음", "error")
            return None

        except Exception as e:
            self.log(f"마켓 조회 실패: {e}", "error")
            return None

    def get_products(self) -> List[dict]:
        """상품 목록 조회"""
        try:
            products = self.api.get_product_list(
                group_name=self.group_name,
                status_filters=self.status_filters,
                limit=self.upload_count
            )
            return products
        except Exception as e:
            self.log(f"상품 목록 조회 실패: {e}", "error")
            return []

    def process_product(self, product: dict, market_id: int) -> bool:
        """단일 상품 처리"""
        product_id = product.get('ID', product.get('id', ''))
        product_name = product.get('uploadCommonProductName', product.get('name', ''))[:30]

        self.log(f"처리 중: {product_name}", "progress")

        try:
            # 1. 상품 상세 조회
            detail = self.api.get_product_detail(product_id)
            if not detail:
                self.log(f"상품 상세 조회 실패: {product_name}", "error")
                return False

            # 2. SKU 업데이트 (필요 시)
            if not self.skip_sku_update:
                skus = detail.get('uploadSkus', [])
                if skus:
                    # 미끼 옵션 필터링
                    filtered_skus = filter_bait_options(skus, load_bait_keywords())

                    # 옵션 정렬 및 제한
                    if self.option_sort == 'price_asc':
                        filtered_skus.sort(key=lambda x: x.get('_origin_price', 0))
                    elif self.option_sort == 'price_desc':
                        filtered_skus.sort(key=lambda x: x.get('_origin_price', 0), reverse=True)

                    # 개수 제한
                    selected_skus = filtered_skus[:self.option_count]

                    # 대표상품 선택
                    if selected_skus:
                        for sku in selected_skus:
                            sku['main_product'] = False
                        selected_skus[0]['main_product'] = True

            # 3. 업로드 요청
            result = self.api.upload_product(
                product_id=product_id,
                market_id=market_id,
                prevent_duplicate=self.prevent_duplicate
            )

            if result and result.get('code') == 1:
                self.log(f"업로드 성공: {product_name}", "success")
                self.stats['success'] += 1
                return True
            else:
                error_msg = result.get('message', '알 수 없는 오류') if result else '응답 없음'
                self.log(f"업로드 실패: {product_name} - {error_msg}", "error")
                self.stats['failed'] += 1
                return False

        except Exception as e:
            self.log(f"처리 오류: {product_name} - {e}", "error")
            self.stats['failed'] += 1
            return False

    def run(self):
        """업로드 실행"""
        print()
        print(colored("=" * 60, Colors.CYAN))
        print(colored(f"  불사자 업로더 CLI - 세션 #{self.session_id}", Colors.BOLD))
        print(colored("=" * 60, Colors.CYAN))
        print()

        self.log(f"그룹: {self.group_name}")
        self.log(f"마켓: {self.market_name}")
        self.log(f"업로드 수: {self.upload_count}")
        self.log(f"옵션 수: {self.option_count}")
        print()

        # 마켓 ID 조회
        market_id = self.get_market_id()
        if not market_id:
            self.log("마켓 ID를 찾을 수 없어 종료합니다", "error")
            return

        self.log(f"마켓 ID: {market_id}")

        # 상품 목록 조회
        products = self.get_products()
        if not products:
            self.log("업로드할 상품이 없습니다", "warning")
            return

        self.stats['total'] = len(products)
        self.log(f"대상 상품: {len(products)}개")
        print()
        print(colored("-" * 40, Colors.CYAN))
        print()

        # 각 상품 처리
        for i, product in enumerate(products):
            self.log(f"[{i+1}/{len(products)}]", "progress")
            self.process_product(product, market_id)

            # 딜레이
            if i < len(products) - 1:
                time.sleep(1.5)

        # 결과 출력
        print()
        print(colored("=" * 60, Colors.CYAN))
        print(colored(f"  세션 #{self.session_id} 완료", Colors.BOLD))
        print(colored("=" * 60, Colors.CYAN))
        print()
        print(f"  총 처리: {self.stats['total']}개")
        print(f"  {colored('성공', Colors.GREEN)}: {self.stats['success']}개")
        print(f"  {colored('실패', Colors.RED)}: {self.stats['failed']}개")
        print(f"  {colored('건너뜀', Colors.YELLOW)}: {self.stats['skipped']}개")
        print()

        # 창 유지
        input("Enter를 누르면 창이 닫힙니다...")


def main():
    # Windows 콘솔 색상 활성화
    if sys.platform == 'win32':
        os.system('color')

    parser = argparse.ArgumentParser(description='불사자 업로더 CLI')
    parser.add_argument('--config', required=True, help='설정 파일 경로')
    parser.add_argument('--session', type=int, default=1, help='세션 번호')
    parser.add_argument('--group', required=True, help='마켓 그룹명')

    args = parser.parse_args()

    # 설정 파일 로드
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"설정 파일을 찾을 수 없습니다: {args.config}")
        sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # 업로더 실행
    uploader = CLIUploader(config, args.session, args.group)
    uploader.run()


if __name__ == "__main__":
    main()
