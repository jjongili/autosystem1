# -*- coding: utf-8 -*-
"""
OCR 텍스트 감지 테스트 - PoC
타오바오 상품 이미지에서 중국어 텍스트 감지 및 제거 테스트

사용법:
    python test_ocr_poc.py U01KF9YZQN29TCSFKVX11CQ2FQ7

필요 패키지:
    pip install easyocr opencv-python pillow requests
"""

import os
import sys
import json
import requests
from pathlib import Path
from typing import List, Dict, Tuple

# 상위 디렉토리 추가 (bulsaja_common 임포트용)
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    print("[WARNING] opencv-python 설치 필요: pip install opencv-python")

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    print("[WARNING] easyocr 설치 필요: pip install easyocr")

# 불사자 API 클라이언트
from bulsaja_common import BulsajaAPIClient


class OCRTester:
    """OCR 테스트 클래스"""

    def __init__(self, output_dir: str = "ocr_output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # EasyOCR 리더 (중국어 간체 + 영어)
        if EASYOCR_AVAILABLE:
            print("EasyOCR 모델 로딩 중... (처음 실행 시 다운로드, 약 100MB)")
            self.reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
            print("EasyOCR 로딩 완료")
        else:
            self.reader = None

    def download_image(self, url: str, filename: str) -> str:
        """이미지 다운로드"""
        filepath = self.output_dir / filename

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.bulsaja.com/'
            }
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            with open(filepath, 'wb') as f:
                f.write(response.content)

            return str(filepath)
        except Exception as e:
            print(f"  [ERROR] 다운로드 실패: {e}")
            return None

    def detect_text(self, image_path: str) -> List[Dict]:
        """이미지에서 텍스트 감지"""
        if not self.reader:
            return []

        try:
            # EasyOCR로 텍스트 감지
            results = self.reader.readtext(image_path)

            detected = []
            for bbox, text, confidence in results:
                # bbox: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                detected.append({
                    'bbox': bbox,
                    'text': text,
                    'confidence': confidence
                })

            return detected
        except Exception as e:
            print(f"  [ERROR] OCR 실패: {e}")
            return []

    def draw_text_boxes(self, image_path: str, detections: List[Dict], output_path: str):
        """감지된 텍스트 영역 표시"""
        if not CV2_AVAILABLE:
            return

        img = cv2.imread(image_path)
        if img is None:
            return

        for det in detections:
            bbox = det['bbox']
            text = det['text']
            conf = det['confidence']

            # 박스 그리기 (빨간색)
            pts = np.array(bbox, np.int32)
            pts = pts.reshape((-1, 1, 2))
            cv2.polylines(img, [pts], True, (0, 0, 255), 2)

            # 신뢰도 표시
            x, y = int(bbox[0][0]), int(bbox[0][1]) - 10
            cv2.putText(img, f"{conf:.2f}", (x, y),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        cv2.imwrite(output_path, img)

    def remove_text_simple(self, image_path: str, detections: List[Dict], output_path: str):
        """텍스트 영역 간단 제거 (흰색으로 채우기)"""
        if not CV2_AVAILABLE:
            return

        img = cv2.imread(image_path)
        if img is None:
            return

        for det in detections:
            bbox = det['bbox']

            # 다각형 영역을 흰색으로 채우기
            pts = np.array(bbox, np.int32)
            cv2.fillPoly(img, [pts], (255, 255, 255))

        cv2.imwrite(output_path, img)

    def remove_text_inpaint(self, image_path: str, detections: List[Dict], output_path: str):
        """텍스트 영역 인페인팅 제거 (주변 색상으로 채우기)"""
        if not CV2_AVAILABLE:
            return

        img = cv2.imread(image_path)
        if img is None:
            return

        # 마스크 생성
        mask = np.zeros(img.shape[:2], dtype=np.uint8)

        for det in detections:
            bbox = det['bbox']
            pts = np.array(bbox, np.int32)
            cv2.fillPoly(mask, [pts], 255)

        # 마스크 확장 (텍스트 경계 포함)
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=2)

        # 인페인팅
        result = cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)

        cv2.imwrite(output_path, result)

    def analyze_image(self, url: str, index: int) -> Dict:
        """단일 이미지 분석"""
        print(f"\n[{index}] 이미지 분석 중...")
        print(f"  URL: {url[:80]}...")

        # 1. 다운로드
        filename = f"img_{index:02d}_original.jpg"
        filepath = self.download_image(url, filename)
        if not filepath:
            return {'error': 'download_failed'}
        print(f"  [OK] 다운로드 완료: {filename}")

        # 2. OCR
        detections = self.detect_text(filepath)
        print(f"  [OK] 텍스트 감지: {len(detections)}개")

        # 감지된 텍스트 출력
        for i, det in enumerate(detections[:5]):  # 상위 5개만
            try:
                text_display = det['text'].encode('cp949', errors='replace').decode('cp949')
            except:
                text_display = det['text'].encode('ascii', errors='replace').decode('ascii')
            print(f"    [{i+1}] \"{text_display}\" (conf: {det['confidence']:.2f})")
        if len(detections) > 5:
            print(f"    ... and {len(detections) - 5} more")

        # 3. 결과 이미지 생성
        if detections:
            # 박스 표시 이미지
            boxed_path = str(self.output_dir / f"img_{index:02d}_boxed.jpg")
            self.draw_text_boxes(filepath, detections, boxed_path)
            print(f"  [OK] 박스 표시: img_{index:02d}_boxed.jpg")

            # 간단 제거 (흰색)
            white_path = str(self.output_dir / f"img_{index:02d}_white.jpg")
            self.remove_text_simple(filepath, detections, white_path)
            print(f"  [OK] 흰색 제거: img_{index:02d}_white.jpg")

            # 인페인팅 제거
            inpaint_path = str(self.output_dir / f"img_{index:02d}_inpaint.jpg")
            self.remove_text_inpaint(filepath, detections, inpaint_path)
            print(f"  [OK] 인페인팅: img_{index:02d}_inpaint.jpg")

        return {
            'url': url,
            'filepath': filepath,
            'detections': detections,
            'text_count': len(detections)
        }


def load_tokens() -> Tuple[str, str]:
    """토큰 파일에서 로드"""
    # bulsaja_uploader_config.json에서 로드
    config_file = Path(__file__).parent.parent / "bulsaja_uploader_config.json"

    if config_file.exists():
        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('access_token', ''), data.get('refresh_token', '')

    # 환경변수에서
    return os.environ.get('BULSAJA_ACCESS_TOKEN', ''), os.environ.get('BULSAJA_REFRESH_TOKEN', '')


def main():
    # 상품 ID
    product_id = sys.argv[1] if len(sys.argv) > 1 else "U01KF9YZQN29TCSFKVX11CQ2FQ7"

    print("=" * 60)
    print("OCR 텍스트 감지 테스트")
    print("=" * 60)
    print(f"상품 ID: {product_id}")

    # 토큰 로드
    access_token, refresh_token = load_tokens()
    if not access_token:
        print("\n[ERROR] 토큰이 없습니다. bulsaja_tokens.json 파일을 확인하세요.")
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

    # 상품명
    product_name = product.get('uploadCommonProductName', product.get('name', ''))
    print(f"상품명: {product_name}")

    # 상세 이미지 URL 추출
    # uploadDetailContents는 object이고 images 필드에 URL 리스트가 있음
    detail_contents_obj = product.get('uploadDetailContents', {})

    # 디버깅: 구조 확인
    detail_contents = []

    if isinstance(detail_contents_obj, dict):
        print(f"uploadDetailContents 키: {list(detail_contents_obj.keys())[:10]}")

        # renderContent에서 이미지 URL 추출
        render_content = detail_contents_obj.get('renderContent', '')
        if render_content:
            # HTML에서 이미지 URL 추출 (img src 또는 직접 URL)
            import re
            # img 태그에서 src 추출
            img_urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', render_content)
            if img_urls:
                detail_contents = img_urls
            else:
                # 직접 이미지 URL 패턴
                img_urls = re.findall(r'https?://[^\s<>"]+\.(?:jpg|jpeg|png|gif|webp)', render_content, re.IGNORECASE)
                detail_contents = list(set(img_urls))  # 중복 제거

        if not detail_contents:
            # detailContents에서 시도
            original_detail = product.get('detailContents', {})
            if isinstance(original_detail, dict):
                render_content = original_detail.get('renderContent', '')
                if render_content:
                    img_urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', render_content)
                    if not img_urls:
                        img_urls = re.findall(r'https?://[^\s<>"]+\.(?:jpg|jpeg|png|gif|webp)', render_content, re.IGNORECASE)
                    detail_contents = list(set(img_urls))

    elif isinstance(detail_contents_obj, list):
        detail_contents = detail_contents_obj

    if not detail_contents:
        print("[ERROR] 상세 이미지가 없습니다.")
        print(f"  uploadDetailContents 타입: {type(detail_contents_obj)}")
        if isinstance(detail_contents_obj, dict):
            print(f"  가용 키: {list(detail_contents_obj.keys())}")
            # renderContent 샘플 출력
            rc = detail_contents_obj.get('renderContent', '')
            if rc:
                print(f"  renderContent 샘플 (200자): {rc[:200]}...")
        return

    print(f"상세 이미지: {len(detail_contents)}개")

    # OCR 테스터
    output_dir = Path(__file__).parent / "ocr_output" / product_id[:10]
    tester = OCRTester(str(output_dir))

    # 처음 5개 이미지만 테스트
    test_count = min(5, len(detail_contents))
    print(f"\n처음 {test_count}개 이미지 테스트...")

    results = []
    total_texts = 0

    for i, url in enumerate(detail_contents[:test_count]):
        result = tester.analyze_image(url, i + 1)
        results.append(result)
        total_texts += result.get('text_count', 0)

    # 요약
    print("\n" + "=" * 60)
    print("테스트 결과 요약")
    print("=" * 60)
    print(f"분석 이미지: {len(results)}개")
    print(f"총 감지 텍스트: {total_texts}개")
    print(f"출력 폴더: {output_dir}")
    print("\n출력 파일:")
    print("  - *_original.jpg : 원본 이미지")
    print("  - *_boxed.jpg    : 텍스트 영역 표시")
    print("  - *_white.jpg    : 흰색으로 제거")
    print("  - *_inpaint.jpg  : 인페인팅 제거")


if __name__ == "__main__":
    main()
