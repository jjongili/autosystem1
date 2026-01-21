# -*- coding: utf-8 -*-
"""
OCR 텍스트 선택 삭제 GUI
- 이미지에서 OCR로 감지된 텍스트 박스 표시
- 클릭으로 삭제할 박스 선택/해제
- 선택한 박스만 제거 (인페인팅)

사용법:
    python ocr_gui.py [이미지경로]
    python ocr_gui.py  # 기본: ocr_output 폴더의 첫 번째 이미지
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import threading

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageTk, ImageDraw
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    print("[ERROR] opencv-python, pillow 설치 필요")
    print("pip install opencv-python pillow")
    sys.exit(1)

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    print("[WARNING] easyocr 설치 필요: pip install easyocr")


class OCRTextRemoverGUI:
    """OCR 텍스트 선택 삭제 GUI"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("OCR 텍스트 선택 삭제")
        self.root.geometry("1400x900")

        # 상태 변수
        self.image_path: Optional[str] = None
        self.original_image: Optional[np.ndarray] = None
        self.display_image: Optional[Image.Image] = None
        self.photo_image: Optional[ImageTk.PhotoImage] = None
        self.detections: List[Dict] = []
        self.selected_indices: set = set()  # 선택된 박스 인덱스
        self.scale_factor: float = 1.0

        # EasyOCR 리더 (지연 로딩)
        self.reader = None
        self.reader_loading = False

        # GUI 구성
        self._setup_ui()

    def _setup_ui(self):
        """UI 구성"""
        # 메인 프레임
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 상단: 버튼 영역
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(btn_frame, text="이미지 열기", command=self._open_image).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="OCR 실행", command=self._run_ocr).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="전체 선택", command=self._select_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="전체 해제", command=self._deselect_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="선택 삭제 (인페인팅)", command=self._remove_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="결과 저장", command=self._save_result).pack(side=tk.LEFT, padx=5)

        # 상태 라벨
        self.status_var = tk.StringVar(value="이미지를 열어주세요")
        ttk.Label(btn_frame, textvariable=self.status_var).pack(side=tk.RIGHT, padx=10)

        # 중앙: 이미지 + 텍스트 목록
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # 왼쪽: 이미지 캔버스
        canvas_frame = ttk.Frame(content_frame)
        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 스크롤바
        h_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
        v_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Canvas(
            canvas_frame,
            bg='gray',
            xscrollcommand=h_scroll.set,
            yscrollcommand=v_scroll.set
        )
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        h_scroll.config(command=self.canvas.xview)
        v_scroll.config(command=self.canvas.yview)

        # 캔버스 클릭 이벤트
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        # 오른쪽: 텍스트 목록
        list_frame = ttk.LabelFrame(content_frame, text="감지된 텍스트", padding=5)
        list_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))

        # 트리뷰
        columns = ("idx", "text", "conf", "selected")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=25)
        self.tree.heading("idx", text="#")
        self.tree.heading("text", text="텍스트")
        self.tree.heading("conf", text="신뢰도")
        self.tree.heading("selected", text="선택")
        self.tree.column("idx", width=40, anchor="center")
        self.tree.column("text", width=200)
        self.tree.column("conf", width=60, anchor="center")
        self.tree.column("selected", width=50, anchor="center")

        tree_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.Y)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 트리뷰 클릭 이벤트
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)

    def _open_image(self):
        """이미지 파일 열기"""
        filetypes = [
            ("이미지 파일", "*.jpg *.jpeg *.png *.bmp *.webp"),
            ("모든 파일", "*.*")
        ]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            self._load_image(path)

    def _load_image(self, path: str):
        """이미지 로드"""
        self.image_path = path
        self.original_image = cv2.imread(path)

        if self.original_image is None:
            messagebox.showerror("오류", f"이미지를 열 수 없습니다:\n{path}")
            return

        # 초기화
        self.detections = []
        self.selected_indices = set()
        self.tree.delete(*self.tree.get_children())

        self._update_canvas()
        self.status_var.set(f"이미지 로드됨: {Path(path).name}")

    def _update_canvas(self, result_image: np.ndarray = None):
        """캔버스 업데이트"""
        if self.original_image is None:
            return

        # 사용할 이미지
        img = result_image if result_image is not None else self.original_image.copy()

        # BGR -> RGB
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # 박스 그리기
        if result_image is None:  # 원본 이미지일 때만 박스 표시
            for i, det in enumerate(self.detections):
                bbox = det['bbox']
                pts = np.array(bbox, np.int32)

                # 선택 여부에 따라 색상
                if i in self.selected_indices:
                    color = (255, 0, 0)  # 빨강 (선택됨)
                    thickness = 3
                else:
                    color = (0, 255, 0)  # 초록 (미선택)
                    thickness = 2

                cv2.polylines(img_rgb, [pts], True, color, thickness)

                # 번호 표시
                x, y = int(bbox[0][0]), int(bbox[0][1]) - 5
                cv2.putText(img_rgb, str(i + 1), (x, y),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        # PIL 이미지로 변환
        self.display_image = Image.fromarray(img_rgb)

        # 캔버스 크기에 맞게 스케일 조정
        canvas_width = self.canvas.winfo_width() or 900
        canvas_height = self.canvas.winfo_height() or 700
        img_width, img_height = self.display_image.size

        # 스케일 계산 (이미지가 캔버스보다 크면 축소)
        scale_w = canvas_width / img_width if img_width > canvas_width else 1.0
        scale_h = canvas_height / img_height if img_height > canvas_height else 1.0
        self.scale_factor = min(scale_w, scale_h, 1.0)

        if self.scale_factor < 1.0:
            new_size = (int(img_width * self.scale_factor), int(img_height * self.scale_factor))
            display = self.display_image.resize(new_size, Image.LANCZOS)
        else:
            display = self.display_image

        self.photo_image = ImageTk.PhotoImage(display)

        # 캔버스에 이미지 표시
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo_image)
        self.canvas.config(scrollregion=(0, 0, display.width, display.height))

    def _run_ocr(self):
        """OCR 실행"""
        if self.original_image is None:
            messagebox.showwarning("경고", "먼저 이미지를 열어주세요")
            return

        if not EASYOCR_AVAILABLE:
            messagebox.showerror("오류", "easyocr가 설치되지 않았습니다.\npip install easyocr")
            return

        # 로딩 중이면 무시
        if self.reader_loading:
            return

        self.status_var.set("OCR 실행 중...")
        self.root.update()

        # 별도 스레드에서 OCR 실행
        threading.Thread(target=self._run_ocr_thread, daemon=True).start()

    def _run_ocr_thread(self):
        """OCR 스레드"""
        try:
            # 리더 초기화 (처음 한 번만)
            if self.reader is None:
                self.reader_loading = True
                self.root.after(0, lambda: self.status_var.set("EasyOCR 모델 로딩 중..."))
                self.reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
                self.reader_loading = False

            # OCR 실행
            self.root.after(0, lambda: self.status_var.set("텍스트 감지 중..."))
            results = self.reader.readtext(self.image_path)

            # 결과 저장
            self.detections = []
            for bbox, text, confidence in results:
                self.detections.append({
                    'bbox': bbox,
                    'text': text,
                    'confidence': confidence
                })

            # UI 업데이트 (메인 스레드)
            self.root.after(0, self._update_detection_ui)

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("OCR 오류", str(e)))
            self.root.after(0, lambda: self.status_var.set("OCR 오류 발생"))

    def _update_detection_ui(self):
        """감지 결과 UI 업데이트"""
        # 트리뷰 업데이트
        self.tree.delete(*self.tree.get_children())
        for i, det in enumerate(self.detections):
            text = det['text'][:30] + "..." if len(det['text']) > 30 else det['text']
            conf = f"{det['confidence']:.2f}"
            selected = "V" if i in self.selected_indices else ""
            self.tree.insert("", tk.END, values=(i + 1, text, conf, selected), iid=str(i))

        # 캔버스 업데이트
        self._update_canvas()
        self.status_var.set(f"감지 완료: {len(self.detections)}개 텍스트")

    def _on_canvas_click(self, event):
        """캔버스 클릭 - 박스 선택/해제"""
        if not self.detections:
            return

        # 클릭 좌표를 원본 이미지 좌표로 변환
        x = event.x / self.scale_factor
        y = event.y / self.scale_factor

        # 클릭된 박스 찾기
        for i, det in enumerate(self.detections):
            bbox = det['bbox']
            pts = np.array(bbox, np.float32)

            # 점이 다각형 안에 있는지 확인
            if cv2.pointPolygonTest(pts, (x, y), False) >= 0:
                self._toggle_selection(i)
                break

    def _on_tree_click(self, event):
        """트리뷰 클릭 - 박스 선택/해제"""
        selection = self.tree.selection()
        if selection:
            idx = int(selection[0])
            self._toggle_selection(idx)

    def _toggle_selection(self, idx: int):
        """선택 토글"""
        if idx in self.selected_indices:
            self.selected_indices.remove(idx)
        else:
            self.selected_indices.add(idx)

        # UI 업데이트
        self._update_detection_ui()

    def _select_all(self):
        """전체 선택"""
        self.selected_indices = set(range(len(self.detections)))
        self._update_detection_ui()

    def _deselect_all(self):
        """전체 해제"""
        self.selected_indices = set()
        self._update_detection_ui()

    def _remove_selected(self):
        """선택된 텍스트 제거 (인페인팅)"""
        if not self.selected_indices:
            messagebox.showwarning("경고", "삭제할 텍스트를 선택해주세요")
            return

        self.status_var.set("인페인팅 처리 중...")
        self.root.update()

        try:
            img = self.original_image.copy()

            # 마스크 생성
            mask = np.zeros(img.shape[:2], dtype=np.uint8)

            for i in self.selected_indices:
                det = self.detections[i]
                pts = np.array(det['bbox'], np.int32)
                cv2.fillPoly(mask, [pts], 255)

            # 마스크 확장
            kernel = np.ones((5, 5), np.uint8)
            mask = cv2.dilate(mask, kernel, iterations=2)

            # 인페인팅
            result = cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)

            # 결과 표시
            self._update_canvas(result)
            self.result_image = result
            self.status_var.set(f"제거 완료: {len(self.selected_indices)}개 텍스트")

        except Exception as e:
            messagebox.showerror("오류", f"인페인팅 실패:\n{e}")
            self.status_var.set("인페인팅 오류")

    def _save_result(self):
        """결과 저장"""
        if not hasattr(self, 'result_image') or self.result_image is None:
            messagebox.showwarning("경고", "먼저 '선택 삭제'를 실행해주세요")
            return

        # 저장 경로
        default_name = Path(self.image_path).stem + "_edited.jpg"
        path = filedialog.asksaveasfilename(
            defaultextension=".jpg",
            initialfile=default_name,
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png")]
        )

        if path:
            cv2.imwrite(path, self.result_image)
            self.status_var.set(f"저장됨: {Path(path).name}")
            messagebox.showinfo("저장 완료", f"저장되었습니다:\n{path}")


def main():
    # 이미지 경로 (인자 또는 기본값)
    image_path = None
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
    else:
        # ocr_output 폴더에서 첫 번째 original 이미지 찾기
        output_dir = Path(__file__).parent / "ocr_output"
        if output_dir.exists():
            for subdir in output_dir.iterdir():
                if subdir.is_dir():
                    for img in subdir.glob("*_original.jpg"):
                        image_path = str(img)
                        break
                if image_path:
                    break

    # GUI 실행
    root = tk.Tk()
    app = OCRTextRemoverGUI(root)

    # 이미지 자동 로드
    if image_path and Path(image_path).exists():
        root.after(100, lambda: app._load_image(image_path))

    root.mainloop()


if __name__ == "__main__":
    main()
