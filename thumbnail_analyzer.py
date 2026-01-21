# -*- coding: utf-8 -*-
"""
썸네일 자동 분석/선택 모듈
- 누끼 감지 (배경 분석)
- 중국어 텍스트 감지 (OCR)
- 점수 기반 최적 썸네일 선택

사용법:
    python thumbnail_analyzer.py U01KF9YZQN29TCSFKVX11CQ2FQ7
"""

import os
import sys
import json
import requests
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import tempfile

try:
    import cv2
    import numpy as np
    from PIL import Image
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    print("[ERROR] opencv-python, pillow 필요: pip install opencv-python pillow")

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    print("[WARNING] easyocr 설치 필요: pip install easyocr")

# 불사자 API 클라이언트
sys.path.insert(0, str(Path(__file__).parent))
from bulsaja_common import BulsajaAPIClient


@dataclass
class ThumbnailScore:
    """썸네일 점수 결과"""
    url: str
    index: int
    total_score: int
    is_nukki: bool
    nukki_score: int
    has_text: bool
    text_count: int
    text_score: int
    center_score: int
    recommendation: str  # "best", "good", "needs_nukki", "needs_translate", "poor"


class ThumbnailAnalyzer:
    """썸네일 분석기"""

    def __init__(self):
        self.ocr_reader = None
        self._ocr_loaded = False

    def _load_ocr(self):
        """OCR 모델 지연 로딩"""
        if not self._ocr_loaded and EASYOCR_AVAILABLE:
            print("  OCR 모델 로딩 중...")
            self.ocr_reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
            self._ocr_loaded = True
            print("  OCR 모델 로딩 완료")

    def download_image(self, url: str) -> Optional[np.ndarray]:
        """이미지 다운로드 및 numpy 배열로 변환"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.bulsaja.com/'
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            # 바이트를 numpy 배열로 변환
            img_array = np.frombuffer(response.content, np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            return img
        except Exception as e:
            print(f"    [ERROR] 이미지 다운로드 실패: {e}")
            return None

    def check_nukki(self, img: np.ndarray) -> Tuple[bool, int]:
        """
        누끼 감지 (배경이 흰색/단색인지 확인)

        Returns:
            (is_nukki, score)
            - is_nukki: 누끼 여부
            - score: 누끼 점수 (0~50)
        """
        if img is None:
            return False, 0

        h, w = img.shape[:2]

        # 테두리 픽셀 추출 (상하좌우 5픽셀)
        border_size = 5
        top = img[:border_size, :, :]
        bottom = img[-border_size:, :, :]
        left = img[:, :border_size, :]
        right = img[:, -border_size:, :]

        # 모든 테두리 픽셀 합치기
        border_pixels = np.vstack([
            top.reshape(-1, 3),
            bottom.reshape(-1, 3),
            left.reshape(-1, 3),
            right.reshape(-1, 3)
        ])

        # 흰색 (250~255) 픽셀 비율 계산
        white_threshold = 250
        white_pixels = np.all(border_pixels >= white_threshold, axis=1)
        white_ratio = np.sum(white_pixels) / len(border_pixels)

        # 밝은색 (230~255) 픽셀 비율
        bright_threshold = 230
        bright_pixels = np.all(border_pixels >= bright_threshold, axis=1)
        bright_ratio = np.sum(bright_pixels) / len(border_pixels)

        # 단색 여부 (표준편차가 낮으면 단색)
        color_std = np.std(border_pixels)

        # 점수 계산
        score = 0

        if white_ratio >= 0.9:
            # 90% 이상 흰색 → 완벽한 누끼
            score = 50
            is_nukki = True
        elif white_ratio >= 0.7:
            # 70% 이상 흰색 → 좋은 누끼
            score = 40
            is_nukki = True
        elif bright_ratio >= 0.8:
            # 80% 이상 밝은색 → 괜찮은 누끼
            score = 30
            is_nukki = True
        elif color_std < 30 and bright_ratio >= 0.5:
            # 단색 배경 + 밝은색
            score = 25
            is_nukki = True
        elif color_std < 20:
            # 단색 배경 (어두운색이라도)
            score = 15
            is_nukki = False
        else:
            # 복잡한 배경
            score = 0
            is_nukki = False

        return is_nukki, score

    def check_text(self, img: np.ndarray) -> Tuple[bool, int, int]:
        """
        중국어 텍스트 감지

        Returns:
            (has_text, text_count, score)
            - has_text: 텍스트 존재 여부
            - text_count: 감지된 텍스트 수
            - score: 점수 (-30 ~ +30)
        """
        if img is None or not EASYOCR_AVAILABLE:
            return False, 0, 0

        self._load_ocr()
        if self.ocr_reader is None:
            return False, 0, 0

        try:
            # BGR to RGB
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            results = self.ocr_reader.readtext(img_rgb)

            # 신뢰도 0.3 이상인 텍스트만 카운트
            confident_texts = [r for r in results if r[2] >= 0.3]
            text_count = len(confident_texts)

            if text_count == 0:
                # 텍스트 없음 → 좋음
                return False, 0, 30
            elif text_count <= 2:
                # 텍스트 적음 → 약간 감점
                return True, text_count, 10
            elif text_count <= 5:
                # 텍스트 보통 → 감점
                return True, text_count, -10
            else:
                # 텍스트 많음 → 큰 감점
                return True, text_count, -30

        except Exception as e:
            print(f"    [ERROR] OCR 실패: {e}")
            return False, 0, 0

    def check_center_object(self, img: np.ndarray) -> int:
        """
        중앙에 제품이 있는지 확인 (간단한 휴리스틱)

        Returns:
            score: 0~20
        """
        if img is None:
            return 0

        h, w = img.shape[:2]

        # 중앙 영역 (40% ~ 60%)
        center_y1, center_y2 = int(h * 0.3), int(h * 0.7)
        center_x1, center_x2 = int(w * 0.3), int(w * 0.7)
        center_region = img[center_y1:center_y2, center_x1:center_x2]

        # 테두리 영역
        border_region = np.vstack([
            img[:int(h*0.2), :, :].reshape(-1, 3),
            img[-int(h*0.2):, :, :].reshape(-1, 3)
        ])

        # 중앙과 테두리의 색상 차이
        center_mean = np.mean(center_region, axis=(0, 1))
        border_mean = np.mean(border_region, axis=0)
        color_diff = np.linalg.norm(center_mean - border_mean)

        # 차이가 클수록 중앙에 뭔가 있음
        if color_diff > 50:
            return 20
        elif color_diff > 30:
            return 15
        elif color_diff > 15:
            return 10
        else:
            return 5

    def analyze_thumbnail(self, url: str, index: int) -> ThumbnailScore:
        """단일 썸네일 분석"""
        print(f"  [{index+1}] 분석 중...")

        img = self.download_image(url)
        if img is None:
            return ThumbnailScore(
                url=url, index=index, total_score=-100,
                is_nukki=False, nukki_score=0,
                has_text=False, text_count=0, text_score=0,
                center_score=0, recommendation="error"
            )

        # 1. 누끼 체크
        is_nukki, nukki_score = self.check_nukki(img)
        print(f"      누끼: {'O' if is_nukki else 'X'} ({nukki_score}점)")

        # 2. 텍스트 체크
        has_text, text_count, text_score = self.check_text(img)
        print(f"      텍스트: {text_count}개 ({text_score}점)")

        # 3. 중앙 객체 체크
        center_score = self.check_center_object(img)
        print(f"      중앙객체: {center_score}점")

        # 총점 계산
        total_score = nukki_score + text_score + center_score
        print(f"      총점: {total_score}점")

        # 추천 등급 결정
        if is_nukki and not has_text:
            recommendation = "best"  # 누끼 + 텍스트 없음 = 최고
        elif is_nukki and has_text:
            recommendation = "needs_translate"  # 누끼 + 텍스트 = 번역 필요
        elif not is_nukki and not has_text:
            recommendation = "needs_nukki"  # 배경 있음 + 텍스트 없음 = 누끼 제거 필요
        elif not is_nukki and has_text and text_count <= 3:
            recommendation = "needs_both"  # 둘 다 필요
        else:
            recommendation = "poor"  # 복잡함

        return ThumbnailScore(
            url=url, index=index, total_score=total_score,
            is_nukki=is_nukki, nukki_score=nukki_score,
            has_text=has_text, text_count=text_count, text_score=text_score,
            center_score=center_score, recommendation=recommendation
        )

    def analyze_thumbnails(self, urls: List[str]) -> List[ThumbnailScore]:
        """여러 썸네일 분석 및 순위 매기기"""
        results = []
        for i, url in enumerate(urls):
            result = self.analyze_thumbnail(url, i)
            results.append(result)

        # 점수순 정렬
        results.sort(key=lambda x: x.total_score, reverse=True)
        return results

    def get_best_thumbnail(self, urls: List[str]) -> Tuple[int, ThumbnailScore, str]:
        """
        최적 썸네일 선택

        Returns:
            (best_index, score_info, action_needed)
            - best_index: 최적 썸네일 인덱스 (0-based)
            - score_info: 점수 정보
            - action_needed: 필요한 작업 ("none", "translate", "nukki", "both")
        """
        results = self.analyze_thumbnails(urls)

        if not results:
            return 0, None, "error"

        best = results[0]

        # 필요한 작업 결정
        if best.recommendation == "best":
            action = "none"
        elif best.recommendation == "needs_translate":
            action = "translate"
        elif best.recommendation == "needs_nukki":
            action = "nukki"
        elif best.recommendation == "needs_both":
            action = "both"
        else:
            action = "manual"  # 수동 확인 필요

        return best.index, best, action


def load_tokens() -> Tuple[str, str]:
    """토큰 로드"""
    config_file = Path(__file__).parent / "bulsaja_uploader_config.json"
    if config_file.exists():
        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('access_token', ''), data.get('refresh_token', '')
    return '', ''


def main():
    if not CV2_AVAILABLE:
        print("opencv-python이 필요합니다: pip install opencv-python pillow")
        return

    # 상품 ID
    product_id = sys.argv[1] if len(sys.argv) > 1 else "U01KF9YZQN29TCSFKVX11CQ2FQ7"

    print("=" * 60)
    print("썸네일 자동 분석")
    print("=" * 60)
    print(f"상품 ID: {product_id}")

    # 토큰 로드
    access_token, refresh_token = load_tokens()
    if not access_token:
        print("[ERROR] 토큰이 없습니다.")
        return

    # API 클라이언트
    api = BulsajaAPIClient(access_token, refresh_token)

    # 상품 상세 조회
    print("\n상품 정보 조회 중...")
    try:
        product = api.get_product_detail(product_id)
    except Exception as e:
        print(f"[ERROR] 상품 조회 실패: {e}")
        return

    product_name = product.get('uploadCommonProductName', product.get('name', ''))
    print(f"상품명: {product_name}")

    # 썸네일 URL 추출
    thumbnails = product.get('uploadThumbnails', [])
    if not thumbnails:
        print("[ERROR] 썸네일이 없습니다.")
        return

    print(f"썸네일: {len(thumbnails)}개")

    # 분석
    print("\n" + "-" * 40)
    print("썸네일 분석 시작")
    print("-" * 40)

    analyzer = ThumbnailAnalyzer()
    best_idx, best_score, action = analyzer.get_best_thumbnail(thumbnails)

    # 결과 출력
    print("\n" + "=" * 60)
    print("분석 결과")
    print("=" * 60)

    if best_score:
        print(f"\n추천 메인 썸네일: #{best_idx + 1}")
        print(f"  URL: {thumbnails[best_idx][:60]}...")
        print(f"  총점: {best_score.total_score}점")
        print(f"  누끼: {'O' if best_score.is_nukki else 'X'} ({best_score.nukki_score}점)")
        print(f"  텍스트: {best_score.text_count}개 ({best_score.text_score}점)")
        print(f"  중앙객체: {best_score.center_score}점")

        action_msg = {
            "none": "바로 사용 가능",
            "translate": "썸네일 번역 필요",
            "nukki": "누끼 제거 필요 (rembg)",
            "both": "누끼 제거 + 번역 필요",
            "manual": "수동 확인 필요"
        }
        print(f"\n필요 작업: {action_msg.get(action, action)}")

        # 현재 메인과 비교
        if best_idx == 0:
            print("\n현재 메인 썸네일이 최적입니다!")
        else:
            print(f"\n현재 메인(#1) → 추천(#{best_idx + 1})로 변경 권장")


if __name__ == "__main__":
    main()
