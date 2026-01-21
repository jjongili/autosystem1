# -*- coding: utf-8 -*-
"""
불사자 업로더 - 서버 통신 버전
서버에서 작업 명령을 받아 실행하고 진행상황을 WebSocket으로 보고

사용법:
    python bulsaja_uploader_server.py --server http://서버주소:8000 --token 인증토큰
"""

import os
import sys
import json
import time
import asyncio
import argparse
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from queue import Queue

try:
    import websockets
except ImportError:
    print("websockets 패키지가 필요합니다: pip install websockets")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("requests 패키지가 필요합니다: pip install requests")
    sys.exit(1)

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
    return f"{color}{text}{Colors.RESET}"


class ServerConnectedUploader:
    """서버 연결 업로더"""

    def __init__(self, server_url: str, client_token: str, bulsaja_config: dict):
        self.server_url = server_url.rstrip('/')
        self.client_token = client_token
        self.bulsaja_config = bulsaja_config

        # WebSocket URL 생성
        ws_url = server_url.replace('http://', 'ws://').replace('https://', 'wss://')
        self.ws_url = f"{ws_url}/ws/upload?token={client_token}"

        # API 클라이언트
        self.api = BulsajaAPIClient(
            bulsaja_config.get('access_token', ''),
            bulsaja_config.get('refresh_token', '')
        )

        # 현재 작업 정보
        self.current_job = None
        self.running = True
        self.ws = None

        # 설정값
        self.option_count = bulsaja_config.get('option_count', 5)
        self.option_sort = bulsaja_config.get('option_sort', 'price_asc')
        self.status_filters = bulsaja_config.get('status_filters', ['0', '1', '2'])
        self.market_name = bulsaja_config.get('market_name', '스마트스토어')
        self.prevent_duplicate = bulsaja_config.get('prevent_duplicate', True)

    def log(self, msg: str, level: str = "info"):
        """로그 출력"""
        timestamp = datetime.now().strftime("%H:%M:%S")

        if level == "error":
            print(f"{colored(timestamp, Colors.CYAN)} {colored('ERROR', Colors.RED)} {msg}")
        elif level == "success":
            print(f"{colored(timestamp, Colors.CYAN)} {colored('OK', Colors.GREEN)} {msg}")
        elif level == "warning":
            print(f"{colored(timestamp, Colors.CYAN)} {colored('WARN', Colors.YELLOW)} {msg}")
        elif level == "progress":
            print(f"{colored(timestamp, Colors.CYAN)} {colored('>>>', Colors.BLUE)} {msg}")
        else:
            print(f"{colored(timestamp, Colors.CYAN)} {msg}")

    async def send_status(self, status: dict):
        """서버에 상태 전송"""
        if self.ws:
            try:
                await self.ws.send(json.dumps({
                    "type": "status",
                    "job_id": self.current_job.get('job_id') if self.current_job else None,
                    **status
                }))
            except Exception as e:
                self.log(f"상태 전송 실패: {e}", "error")

    async def send_progress(self, completed: int, total: int, current_product: str = ""):
        """진행상황 전송"""
        await self.send_status({
            "status": "running",
            "completed": completed,
            "total": total,
            "current": current_product,
            "percent": round(completed / total * 100, 1) if total > 0 else 0
        })

    async def send_result(self, success: bool, stats: dict, error: str = None):
        """작업 결과 전송"""
        await self.send_status({
            "status": "completed" if success else "failed",
            "stats": stats,
            "error": error
        })

    def get_market_id(self, group_name: str) -> Optional[int]:
        """마켓 ID 조회"""
        market_type_map = {
            '스마트스토어': 'SMARTSTORE',
            '11번가': 'ST11',
            'G마켓/옥션': 'ESM',
            '쿠팡': 'COUPANG'
        }
        target_type = market_type_map.get(self.market_name, 'SMARTSTORE')

        try:
            groups_url = f"{self.api.BASE_URL}/market/groups/"
            response = self.api.session.post(groups_url, json={})
            response.raise_for_status()
            groups = response.json()

            group_id = None
            for group in groups:
                if group.get('name') == group_name:
                    group_id = group.get('id')
                    break

            if not group_id:
                return None

            markets_url = f"{self.api.BASE_URL}/market/group/{group_id}/markets"
            response = self.api.session.get(markets_url)
            response.raise_for_status()
            markets = response.json()

            for market in markets:
                if market.get('type') == target_type:
                    return market.get('id')

            return None
        except Exception as e:
            self.log(f"마켓 조회 실패: {e}", "error")
            return None

    def get_products(self, group_name: str, limit: int) -> List[dict]:
        """상품 목록 조회"""
        try:
            return self.api.get_product_list(
                group_name=group_name,
                status_filters=self.status_filters,
                limit=limit
            )
        except Exception as e:
            self.log(f"상품 목록 조회 실패: {e}", "error")
            return []

    def process_product(self, product: dict, market_id: int) -> bool:
        """단일 상품 처리"""
        product_id = product.get('ID', product.get('id', ''))
        product_name = product.get('uploadCommonProductName', product.get('name', ''))[:30]

        try:
            # 상품 상세 조회
            detail = self.api.get_product_detail(product_id)
            if not detail:
                return False

            # SKU 처리
            skus = detail.get('uploadSkus', [])
            if skus:
                filtered_skus = filter_bait_options(skus, load_bait_keywords())
                if self.option_sort == 'price_asc':
                    filtered_skus.sort(key=lambda x: x.get('_origin_price', 0))
                elif self.option_sort == 'price_desc':
                    filtered_skus.sort(key=lambda x: x.get('_origin_price', 0), reverse=True)
                selected_skus = filtered_skus[:self.option_count]
                if selected_skus:
                    for sku in selected_skus:
                        sku['main_product'] = False
                    selected_skus[0]['main_product'] = True

            # 업로드
            result = self.api.upload_product(
                product_id=product_id,
                market_id=market_id,
                prevent_duplicate=self.prevent_duplicate
            )

            return result and result.get('code') == 1
        except Exception as e:
            self.log(f"처리 오류: {product_name} - {e}", "error")
            return False

    async def execute_job(self, job: dict):
        """작업 실행"""
        self.current_job = job
        job_id = job.get('job_id')
        group_name = job.get('group_name')
        upload_count = job.get('upload_count', 10)

        self.log(f"작업 시작: {job_id} - 그룹: {group_name}", "progress")

        stats = {'success': 0, 'failed': 0, 'total': 0}

        try:
            # 마켓 ID 조회
            market_id = self.get_market_id(group_name)
            if not market_id:
                await self.send_result(False, stats, "마켓 ID를 찾을 수 없습니다")
                return

            # 상품 목록 조회
            products = self.get_products(group_name, upload_count)
            if not products:
                await self.send_result(False, stats, "업로드할 상품이 없습니다")
                return

            stats['total'] = len(products)

            # 진행상황 초기 전송
            await self.send_progress(0, stats['total'])

            # 각 상품 처리
            for i, product in enumerate(products):
                product_name = product.get('uploadCommonProductName', product.get('name', ''))[:30]

                # 진행상황 전송
                await self.send_progress(i, stats['total'], product_name)

                # 상품 처리
                if self.process_product(product, market_id):
                    stats['success'] += 1
                    self.log(f"[{i+1}/{stats['total']}] 성공: {product_name}", "success")
                else:
                    stats['failed'] += 1
                    self.log(f"[{i+1}/{stats['total']}] 실패: {product_name}", "error")

                # 딜레이
                if i < len(products) - 1:
                    await asyncio.sleep(1.5)

            # 완료 전송
            await self.send_progress(stats['total'], stats['total'])
            await self.send_result(True, stats)

            self.log(f"작업 완료: 성공 {stats['success']}, 실패 {stats['failed']}", "success")

        except Exception as e:
            self.log(f"작업 실행 오류: {e}", "error")
            await self.send_result(False, stats, str(e))
        finally:
            self.current_job = None

    async def connect_and_listen(self):
        """서버 연결 및 명령 대기"""
        self.log(f"서버 연결 중: {self.server_url}", "progress")

        retry_count = 0
        max_retries = 10

        while self.running and retry_count < max_retries:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    self.ws = ws
                    retry_count = 0

                    self.log("서버 연결 완료! 작업 대기 중...", "success")

                    # 클라이언트 등록
                    await ws.send(json.dumps({
                        "type": "register",
                        "client_id": self.client_token,
                        "status": "ready"
                    }))

                    # 메시지 수신 대기
                    async for message in ws:
                        try:
                            data = json.loads(message)
                            msg_type = data.get('type')

                            if msg_type == 'job':
                                # 새 작업 수신
                                await self.execute_job(data)

                            elif msg_type == 'ping':
                                # 핑 응답
                                await ws.send(json.dumps({"type": "pong"}))

                            elif msg_type == 'cancel':
                                # 작업 취소
                                if self.current_job:
                                    self.log("작업 취소 요청 수신", "warning")
                                    # TODO: 현재 작업 중단 로직

                            elif msg_type == 'shutdown':
                                # 종료 명령
                                self.log("서버 종료 명령 수신", "warning")
                                self.running = False
                                break

                        except json.JSONDecodeError:
                            self.log(f"잘못된 메시지: {message}", "warning")

            except websockets.exceptions.ConnectionClosed:
                self.log("서버 연결 끊김, 재연결 시도...", "warning")
                retry_count += 1
                await asyncio.sleep(5)

            except Exception as e:
                self.log(f"연결 오류: {e}", "error")
                retry_count += 1
                await asyncio.sleep(5)

        if retry_count >= max_retries:
            self.log("최대 재연결 시도 횟수 초과", "error")

    def run(self):
        """실행"""
        print()
        print(colored("=" * 60, Colors.CYAN))
        print(colored("  불사자 업로더 - 서버 연결 모드", Colors.BOLD))
        print(colored("=" * 60, Colors.CYAN))
        print()
        self.log(f"서버: {self.server_url}")
        self.log(f"마켓: {self.market_name}")
        print()

        # Windows 콘솔 색상 활성화
        if sys.platform == 'win32':
            os.system('color')

        try:
            asyncio.run(self.connect_and_listen())
        except KeyboardInterrupt:
            self.log("사용자 종료", "warning")
        finally:
            self.running = False


def main():
    parser = argparse.ArgumentParser(description='불사자 업로더 - 서버 연결 모드')
    parser.add_argument('--server', required=True, help='서버 URL (예: http://192.168.0.100:8000)')
    parser.add_argument('--token', required=True, help='클라이언트 인증 토큰')
    parser.add_argument('--config', default='bulsaja_config.json', help='불사자 설정 파일')

    args = parser.parse_args()

    # 설정 파일 로드
    config_path = Path(args.config)
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            bulsaja_config = json.load(f)
    else:
        print(f"설정 파일을 찾을 수 없습니다: {args.config}")
        print("기본 설정으로 실행합니다.")
        bulsaja_config = {
            'access_token': '',
            'refresh_token': '',
            'option_count': 5,
            'option_sort': 'price_asc',
            'status_filters': ['0', '1', '2'],
            'market_name': '스마트스토어',
            'prevent_duplicate': True
        }

    # 업로더 실행
    uploader = ServerConnectedUploader(args.server, args.token, bulsaja_config)
    uploader.run()


if __name__ == "__main__":
    main()
