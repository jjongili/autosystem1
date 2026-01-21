"""
시뮬레이터 GUI 샘플 - 체크박스 기반 옵션 선택
알바 검수용 원클릭 UI
"""
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import requests
from io import BytesIO

class SimulatorGUISample:
    def __init__(self, root):
        self.root = root
        self.root.title("불사자 시뮬레이터 - 옵션 검수")
        self.root.geometry("1400x700")

        # 샘플 데이터
        self.sample_data = [
            {
                "id": "U01ABC123",
                "name": "캠핑 접이식 의자 경량 휴대용",
                "thumbnail": "https://via.placeholder.com/80x80/4CAF50/white?text=썸네일",
                "is_safe": True,
                "options": [
                    {"label": "A", "name": "블루 대형", "cn_name": "蓝色 大号", "image": "https://via.placeholder.com/60x60/2196F3/white?text=A", "price": 32000},
                    {"label": "B", "name": "레드 대형", "cn_name": "红色 大号", "image": "https://via.placeholder.com/60x60/F44336/white?text=B", "price": 32000},
                    {"label": "C", "name": "블랙 대형", "cn_name": "黑色 大号", "image": "https://via.placeholder.com/60x60/333333/white?text=C", "price": 35000},
                ],
                "selected": "A"
            },
            {
                "id": "U01DEF456",
                "name": "스테인리스 보온병 대용량 1L",
                "thumbnail": "https://via.placeholder.com/80x80/FF9800/white?text=썸네일",
                "is_safe": False,
                "unsafe_reason": "위험키워드: 스타벅스",
                "options": [
                    {"label": "A", "name": "실버 1L", "cn_name": "银色 1L", "image": "https://via.placeholder.com/60x60/9E9E9E/white?text=A", "price": 28000},
                    {"label": "B", "name": "블랙 1L", "cn_name": "黑色 1L", "image": "https://via.placeholder.com/60x60/333333/white?text=B", "price": 28000},
                ],
                "selected": "A"
            },
            {
                "id": "U01GHI789",
                "name": "LED 캠핑 랜턴 충전식 밝기조절",
                "thumbnail": "https://via.placeholder.com/80x80/9C27B0/white?text=썸네일",
                "is_safe": True,
                "options": [
                    {"label": "A", "name": "화이트 기본형", "cn_name": "白色 基本款", "image": "https://via.placeholder.com/60x60/FFFFFF/333?text=A", "price": 18000},
                    {"label": "B", "name": "블랙 프리미엄", "cn_name": "黑色 高级款", "image": "https://via.placeholder.com/60x60/333333/white?text=B", "price": 25000},
                    {"label": "C", "name": "그린 기본형", "cn_name": "绿色 基本款", "image": "https://via.placeholder.com/60x60/4CAF50/white?text=C", "price": 18000},
                    {"label": "D", "name": "오렌지 기본형", "cn_name": "橙色 基本款", "image": "https://via.placeholder.com/60x60/FF9800/white?text=D", "price": 18000},
                ],
                "selected": "A"
            },
        ]

        self.option_vars = {}  # 각 상품별 선택 변수
        self.image_cache = {}  # 이미지 캐시

        self.create_ui()

    def create_ui(self):
        # 메인 프레임
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 상단 툴바
        toolbar = ttk.Frame(main_frame)
        toolbar.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(toolbar, text="불사자 시뮬레이터", font=("맑은 고딕", 14, "bold")).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="불사자 업데이트", command=self.update_bulsaja).pack(side=tk.RIGHT, padx=5)
        ttk.Button(toolbar, text="엑셀 저장", command=self.save_excel).pack(side=tk.RIGHT, padx=5)

        # 스크롤 가능한 캔버스
        canvas_frame = ttk.Frame(main_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_frame)
        scrollbar_y = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollbar_x = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=canvas.xview)

        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 마우스 휠 스크롤
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # 헤더 생성
        self.create_header()

        # 데이터 행 생성
        for idx, item in enumerate(self.sample_data):
            self.create_row(idx, item)

    def create_header(self):
        """헤더 행 생성"""
        header_frame = ttk.Frame(self.scrollable_frame)
        header_frame.pack(fill=tk.X, pady=(0, 5))

        # 헤더 스타일
        style = ttk.Style()
        style.configure("Header.TLabel", font=("맑은 고딕", 9, "bold"), background="#4472C4", foreground="white")

        headers = [
            ("썸네일", 90),
            ("옵션 A", 80),
            ("옵션 B", 80),
            ("옵션 C", 80),
            ("옵션 D", 80),
            ("상품명", 200),
            ("안전", 50),
            ("선택옵션", 120),
            ("중국어", 120),
            ("가격", 70),
        ]

        for text, width in headers:
            lbl = tk.Label(header_frame, text=text, width=width//8, bg="#4472C4", fg="white",
                          font=("맑은 고딕", 9, "bold"), relief="solid", bd=1)
            lbl.pack(side=tk.LEFT, padx=1)

    def create_row(self, idx, item):
        """데이터 행 생성 - 체크박스 방식"""
        row_frame = ttk.Frame(self.scrollable_frame)
        row_frame.pack(fill=tk.X, pady=2)

        # 배경색 (안전/위험)
        bg_color = "#C8E6C9" if item.get("is_safe", True) else "#FFCDD2"

        # 썸네일
        thumb_frame = tk.Frame(row_frame, width=90, height=80, bg=bg_color, relief="solid", bd=1)
        thumb_frame.pack(side=tk.LEFT, padx=1)
        thumb_frame.pack_propagate(False)

        thumb_label = tk.Label(thumb_frame, text="[썸네일]", bg=bg_color, font=("맑은 고딕", 8))
        thumb_label.pack(expand=True)
        # 실제 구현시: self.load_image(item["thumbnail"], thumb_label, 80, 80)

        # 옵션 A~D (체크박스 + 이미지)
        self.option_vars[item["id"]] = tk.StringVar(value=item.get("selected", "A"))

        for opt_idx, opt_label in enumerate(["A", "B", "C", "D"]):
            opt_frame = tk.Frame(row_frame, width=80, height=80, bg=bg_color, relief="solid", bd=1)
            opt_frame.pack(side=tk.LEFT, padx=1)
            opt_frame.pack_propagate(False)

            # 옵션이 있는 경우
            if opt_idx < len(item.get("options", [])):
                opt = item["options"][opt_idx]

                # 라디오버튼 (체크박스 스타일)
                rb = tk.Radiobutton(
                    opt_frame,
                    text=opt_label,
                    variable=self.option_vars[item["id"]],
                    value=opt_label,
                    bg=bg_color,
                    font=("맑은 고딕", 10, "bold"),
                    indicatoron=0,  # 버튼 스타일
                    width=2,
                    selectcolor="#2196F3",
                    command=lambda i=item["id"], o=opt_label: self.on_option_select(i, o)
                )
                rb.pack(pady=2)

                # 이미지 플레이스홀더
                img_label = tk.Label(opt_frame, text=f"[{opt_label}]", bg=bg_color, font=("맑은 고딕", 7))
                img_label.pack(expand=True)
                # 실제 구현시: self.load_image(opt["image"], img_label, 50, 50)
            else:
                # 빈 옵션
                tk.Label(opt_frame, text="-", bg=bg_color).pack(expand=True)

        # 상품명
        name_frame = tk.Frame(row_frame, width=200, height=80, bg=bg_color, relief="solid", bd=1)
        name_frame.pack(side=tk.LEFT, padx=1)
        name_frame.pack_propagate(False)

        name_text = item.get("name", "")[:25]
        tk.Label(name_frame, text=name_text, bg=bg_color, font=("맑은 고딕", 9),
                wraplength=180, justify="left").pack(expand=True, padx=5)

        # 안전여부
        safe_frame = tk.Frame(row_frame, width=50, height=80, bg=bg_color, relief="solid", bd=1)
        safe_frame.pack(side=tk.LEFT, padx=1)
        safe_frame.pack_propagate(False)

        safe_text = "O" if item.get("is_safe", True) else "X"
        safe_color = "#4CAF50" if item.get("is_safe", True) else "#F44336"
        tk.Label(safe_frame, text=safe_text, bg=bg_color, fg=safe_color,
                font=("맑은 고딕", 16, "bold")).pack(expand=True)

        # 선택된 옵션명
        selected_frame = tk.Frame(row_frame, width=120, height=80, bg=bg_color, relief="solid", bd=1)
        selected_frame.pack(side=tk.LEFT, padx=1)
        selected_frame.pack_propagate(False)

        selected_idx = ord(item.get("selected", "A")) - ord("A")
        if selected_idx < len(item.get("options", [])):
            selected_name = f"{item['selected']}. {item['options'][selected_idx]['name']}"
        else:
            selected_name = "-"

        self.selected_labels = getattr(self, 'selected_labels', {})
        self.selected_labels[item["id"]] = tk.Label(selected_frame, text=selected_name, bg=bg_color,
                                                     font=("맑은 고딕", 9), wraplength=110)
        self.selected_labels[item["id"]].pack(expand=True)

        # 중국어 옵션명
        cn_frame = tk.Frame(row_frame, width=120, height=80, bg=bg_color, relief="solid", bd=1)
        cn_frame.pack(side=tk.LEFT, padx=1)
        cn_frame.pack_propagate(False)

        if selected_idx < len(item.get("options", [])):
            cn_name = item['options'][selected_idx].get('cn_name', '')
        else:
            cn_name = "-"

        self.cn_labels = getattr(self, 'cn_labels', {})
        self.cn_labels[item["id"]] = tk.Label(cn_frame, text=cn_name, bg=bg_color,
                                               font=("맑은 고딕", 9), wraplength=110)
        self.cn_labels[item["id"]].pack(expand=True)

        # 가격
        price_frame = tk.Frame(row_frame, width=70, height=80, bg=bg_color, relief="solid", bd=1)
        price_frame.pack(side=tk.LEFT, padx=1)
        price_frame.pack_propagate(False)

        if selected_idx < len(item.get("options", [])):
            price = f"₩{item['options'][selected_idx]['price']:,}"
        else:
            price = "-"

        self.price_labels = getattr(self, 'price_labels', {})
        self.price_labels[item["id"]] = tk.Label(price_frame, text=price, bg=bg_color,
                                                  font=("맑은 고딕", 9))
        self.price_labels[item["id"]].pack(expand=True)

        # 데이터 참조 저장
        row_frame.item_data = item

    def on_option_select(self, item_id, option_label):
        """옵션 선택 시 콜백 - 원클릭으로 바로 반영"""
        # 데이터 업데이트
        for item in self.sample_data:
            if item["id"] == item_id:
                item["selected"] = option_label

                # UI 업데이트
                selected_idx = ord(option_label) - ord("A")
                if selected_idx < len(item.get("options", [])):
                    opt = item["options"][selected_idx]

                    # 선택옵션 레이블 업데이트
                    if item_id in self.selected_labels:
                        self.selected_labels[item_id].config(text=f"{option_label}. {opt['name']}")

                    # 중국어 레이블 업데이트
                    if item_id in self.cn_labels:
                        self.cn_labels[item_id].config(text=opt.get('cn_name', ''))

                    # 가격 레이블 업데이트
                    if item_id in self.price_labels:
                        self.price_labels[item_id].config(text=f"₩{opt['price']:,}")

                print(f"[선택] {item_id}: 옵션 {option_label} 선택됨")
                break

    def update_bulsaja(self):
        """불사자 업데이트 버튼"""
        changes = []
        for item in self.sample_data:
            changes.append(f"{item['id']}: 옵션 {item['selected']}")

        print("=== 불사자 업데이트 ===")
        for c in changes:
            print(c)
        print("========================")

        # 실제 구현시: 불사자 API 호출

    def save_excel(self):
        """엑셀 저장 버튼"""
        print("엑셀 저장 (미구현)")

    def load_image(self, url, label, width, height):
        """URL에서 이미지 로드 (실제 구현시 사용)"""
        try:
            if url in self.image_cache:
                photo = self.image_cache[url]
            else:
                response = requests.get(url, timeout=5)
                img = Image.open(BytesIO(response.content))
                img = img.resize((width, height), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.image_cache[url] = photo

            label.config(image=photo, text="")
            label.image = photo
        except Exception as e:
            print(f"이미지 로드 실패: {e}")


def main():
    root = tk.Tk()
    app = SimulatorGUISample(root)
    root.mainloop()


if __name__ == "__main__":
    main()
