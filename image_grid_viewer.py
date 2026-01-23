# -*- coding: utf-8 -*-
"""
PyQt6 이미지 그리드 뷰어 - 성능 최적화 버전
- 8x50 그리드 (400개 이미지)
- QThreadPool을 이용한 병렬 다운로드
- 이미지 리사이징 최적화
- 플레이스홀더 및 캐싱 적용
"""

import sys
import hashlib
from typing import Dict, Optional
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QScrollArea, QPushButton, QProgressBar
)
from PyQt6.QtCore import Qt, QRunnable, QThreadPool, pyqtSignal, QObject, QSize
from PyQt6.QtGui import QPixmap, QImage, QColor, QPainter
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from urllib.request import urlopen
from urllib.error import URLError
import time


# ============================================================
# 이미지 캐시 (메모리 캐싱으로 중복 다운로드 방지)
# ============================================================
class ImageCache:
    """간단한 메모리 캐시 - URL 해시를 키로 사용"""

    def __init__(self, max_size: int = 500):
        self._cache: Dict[str, QPixmap] = {}
        self._max_size = max_size

    def get(self, url: str) -> Optional[QPixmap]:
        """캐시에서 이미지 조회"""
        key = hashlib.md5(url.encode()).hexdigest()
        return self._cache.get(key)

    def put(self, url: str, pixmap: QPixmap):
        """캐시에 이미지 저장"""
        if len(self._cache) >= self._max_size:
            # 가장 오래된 항목 제거 (간단한 FIFO)
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        key = hashlib.md5(url.encode()).hexdigest()
        self._cache[key] = pixmap

    def clear(self):
        """캐시 초기화"""
        self._cache.clear()


# 전역 캐시 인스턴스
image_cache = ImageCache()


# ============================================================
# 워커 시그널 (QRunnable은 시그널을 직접 가질 수 없으므로 별도 객체 사용)
# ============================================================
class WorkerSignals(QObject):
    """워커 스레드에서 메인 스레드로 결과 전달용 시그널"""
    finished = pyqtSignal(int, QPixmap)  # (인덱스, 이미지)
    error = pyqtSignal(int, str)  # (인덱스, 에러메시지)
    progress = pyqtSignal(int)  # 진행률


# ============================================================
# 이미지 다운로드 워커 (QThreadPool에서 실행)
# ============================================================
class ImageDownloadWorker(QRunnable):
    """
    백그라운드에서 이미지를 다운로드하는 워커
    - QThreadPool에서 병렬 실행됨
    - 다운로드 후 50x50으로 리사이징하여 메모리 최적화
    """

    def __init__(self, index: int, url: str, size: QSize = QSize(50, 50)):
        super().__init__()
        self.index = index
        self.url = url
        self.size = size
        self.signals = WorkerSignals()

    def run(self):
        """워커 실행 (백그라운드 스레드)"""
        try:
            # 1. 캐시 확인
            cached = image_cache.get(self.url)
            if cached:
                self.signals.finished.emit(self.index, cached)
                return

            # 2. HTTP 요청으로 이미지 다운로드
            with urlopen(self.url, timeout=10) as response:
                data = response.read()

            # 3. QImage로 로드
            image = QImage()
            if not image.loadFromData(data):
                raise ValueError("이미지 로드 실패")

            # 4. 50x50으로 리사이징 (SmoothTransformation으로 품질 유지)
            #    원본 이미지가 크더라도 메모리에는 작은 이미지만 유지
            scaled_image = image.scaled(
                self.size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            # 5. QPixmap으로 변환
            pixmap = QPixmap.fromImage(scaled_image)

            # 6. 캐시에 저장
            image_cache.put(self.url, pixmap)

            # 7. 결과 전달
            self.signals.finished.emit(self.index, pixmap)

        except Exception as e:
            self.signals.error.emit(self.index, str(e))


# ============================================================
# 이미지 라벨 (플레이스홀더 포함)
# ============================================================
class ImageLabel(QLabel):
    """
    이미지를 표시하는 라벨
    - 로딩 중에는 플레이스홀더(회색 박스) 표시
    - 로딩 완료 후 이미지 표시
    """

    def __init__(self, size: int = 50, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("""
            QLabel {
                background-color: #E0E0E0;
                border: 1px solid #BDBDBD;
                border-radius: 3px;
            }
        """)
        self.show_placeholder()

    def show_placeholder(self):
        """로딩 중 플레이스홀더 표시"""
        self.setText("...")
        self.setStyleSheet("""
            QLabel {
                background-color: #E0E0E0;
                border: 1px solid #BDBDBD;
                border-radius: 3px;
                color: #757575;
                font-size: 10px;
            }
        """)

    def show_error(self):
        """에러 시 표시"""
        self.setText("X")
        self.setStyleSheet("""
            QLabel {
                background-color: #FFCDD2;
                border: 1px solid #EF9A9A;
                border-radius: 3px;
                color: #C62828;
                font-size: 12px;
                font-weight: bold;
            }
        """)

    def set_image(self, pixmap: QPixmap):
        """이미지 설정"""
        self.setText("")
        self.setPixmap(pixmap)
        self.setStyleSheet("""
            QLabel {
                background-color: white;
                border: 1px solid #BDBDBD;
                border-radius: 3px;
            }
        """)


# ============================================================
# 메인 윈도우
# ============================================================
class ImageGridViewer(QMainWindow):
    """
    이미지 그리드 뷰어 메인 윈도우
    - 8x50 그리드 (400개 이미지)
    - QThreadPool로 병렬 다운로드
    """

    COLUMNS = 8
    ROWS = 50
    IMAGE_SIZE = 50

    def __init__(self):
        super().__init__()
        self.setWindowTitle("이미지 그리드 뷰어 (PyQt6 최적화)")
        self.setMinimumSize(500, 600)

        # QThreadPool 설정 (동시 실행 워커 수 제한)
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(10)  # 동시 10개 다운로드

        # 이미지 라벨 저장
        self.image_labels: Dict[int, ImageLabel] = {}

        # 진행 상태
        self.loaded_count = 0
        self.total_count = self.COLUMNS * self.ROWS

        self._build_ui()
        self._generate_dummy_urls()

    def _build_ui(self):
        """UI 구성"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # === 상단 컨트롤 ===
        control_layout = QHBoxLayout()

        self.load_btn = QPushButton("🔄 이미지 로드 시작")
        self.load_btn.clicked.connect(self.start_loading)
        self.load_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        control_layout.addWidget(self.load_btn)

        self.clear_btn = QPushButton("🗑️ 캐시 초기화")
        self.clear_btn.clicked.connect(self.clear_cache)
        control_layout.addWidget(self.clear_btn)

        control_layout.addStretch()

        self.status_label = QLabel("대기 중...")
        control_layout.addWidget(self.status_label)

        main_layout.addLayout(control_layout)

        # === 진행 바 ===
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(self.total_count)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # === 스크롤 영역 + 그리드 ===
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 그리드 컨테이너
        grid_container = QWidget()
        grid_layout = QGridLayout(grid_container)
        grid_layout.setSpacing(4)
        grid_layout.setContentsMargins(8, 8, 8, 8)

        # 8x50 그리드에 ImageLabel 배치
        for row in range(self.ROWS):
            for col in range(self.COLUMNS):
                index = row * self.COLUMNS + col
                label = ImageLabel(self.IMAGE_SIZE)
                self.image_labels[index] = label
                grid_layout.addWidget(label, row, col)

        scroll_area.setWidget(grid_container)
        main_layout.addWidget(scroll_area)

    def _generate_dummy_urls(self):
        """테스트용 더미 URL 400개 생성"""
        self.image_urls = []

        # 다양한 색상의 placeholder 이미지 사용
        colors = [
            "FF6B6B", "4ECDC4", "45B7D1", "96CEB4", "FFEAA7",
            "DDA0DD", "98D8C8", "F7DC6F", "BB8FCE", "85C1E9"
        ]

        for i in range(self.total_count):
            color = colors[i % len(colors)]
            # placeholder.com은 색상 지정 가능
            url = f"https://via.placeholder.com/150/{color}/FFFFFF?text={i+1}"
            self.image_urls.append(url)

    def start_loading(self):
        """이미지 로딩 시작"""
        self.load_btn.setEnabled(False)
        self.loaded_count = 0
        self.progress_bar.setValue(0)
        self.status_label.setText("로딩 중...")

        # 모든 라벨 플레이스홀더로 초기화
        for label in self.image_labels.values():
            label.show_placeholder()

        # 각 URL에 대해 워커 생성 및 실행
        for index, url in enumerate(self.image_urls):
            worker = ImageDownloadWorker(
                index=index,
                url=url,
                size=QSize(self.IMAGE_SIZE, self.IMAGE_SIZE)
            )

            # 시그널 연결
            worker.signals.finished.connect(self.on_image_loaded)
            worker.signals.error.connect(self.on_image_error)

            # QThreadPool에 워커 추가 (자동 병렬 실행)
            self.thread_pool.start(worker)

    def on_image_loaded(self, index: int, pixmap: QPixmap):
        """이미지 로드 완료 콜백 (메인 스레드에서 실행)"""
        if index in self.image_labels:
            self.image_labels[index].set_image(pixmap)

        self.loaded_count += 1
        self.progress_bar.setValue(self.loaded_count)
        self.status_label.setText(f"로딩 중... {self.loaded_count}/{self.total_count}")

        if self.loaded_count >= self.total_count:
            self.on_loading_complete()

    def on_image_error(self, index: int, error: str):
        """이미지 로드 에러 콜백"""
        if index in self.image_labels:
            self.image_labels[index].show_error()

        self.loaded_count += 1
        self.progress_bar.setValue(self.loaded_count)

        if self.loaded_count >= self.total_count:
            self.on_loading_complete()

    def on_loading_complete(self):
        """로딩 완료"""
        self.load_btn.setEnabled(True)
        self.status_label.setText(f"✅ 완료! ({self.total_count}개)")

    def clear_cache(self):
        """캐시 초기화"""
        image_cache.clear()
        self.status_label.setText("캐시 초기화됨")

        # 모든 라벨 플레이스홀더로 리셋
        for label in self.image_labels.values():
            label.show_placeholder()

        self.progress_bar.setValue(0)
        self.loaded_count = 0


# ============================================================
# 메인 실행
# ============================================================
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = ImageGridViewer()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
