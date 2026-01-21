"""
시뮬레이터 GUI v2 - 실제 엑셀 데이터 로드 + 옵션 박스 선택 방식
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("pandas 없음 - pip install pandas openpyxl")

try:
    from PIL import Image, ImageTk
    import requests
    from io import BytesIO
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("PIL 없음 - pip install pillow requests")


class SimulatorGUIv2:
    def __init__(self, root):
        self.root = root
        self.root.title("불사자 시뮬레이터 v2 - 옵션 검수")
        self.root.geometry("1500x800")

        self.data = []  # 엑셀에서 로드한 데이터
        self.selected_options = {}  # {row_idx: selected_option_label}
        self.option_frames = {}  # {(row_idx, opt_label): frame}
        self.image_cache = {}

        self.create_ui()

        # 자동으로 최신 시뮬레이션 파일 로드 시도
        self.auto_load_latest()

    def create_ui(self):
        # 상단 툴바
        toolbar = ttk.Frame(self.root, padding=5)
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="엑셀 파일 열기", command=self.load_excel).pack(side=tk.LEFT, padx=5)
        ttk.Label(toolbar, text="파일:").pack(side=tk.LEFT, padx=(20, 5))
        self.file_label = ttk.Label(toolbar, text="(없음)", foreground="gray")
        self.file_label.pack(side=tk.LEFT)

        ttk.Button(toolbar, text="불사자 업데이트", command=self.update_bulsaja).pack(side=tk.RIGHT, padx=5)
        ttk.Button(toolbar, text="변경사항 저장", command=self.save_changes).pack(side=tk.RIGHT, padx=5)

        # 상품 수 표시
        self.count_label = ttk.Label(toolbar, text="상품: 0개")
        self.count_label.pack(side=tk.RIGHT, padx=20)

        # 메인 영역 (스크롤)
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 캔버스 + 스크롤바
        self.canvas = tk.Canvas(main_frame, bg="white")
        scrollbar_y = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        scrollbar_x = ttk.Scrollbar(main_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)

        self.scrollable_frame = ttk.Frame(self.canvas)
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 마우스 휠
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

    def auto_load_latest(self):
        """가장 최신 시뮬레이션 파일 자동 로드"""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        simulation_files = [f for f in os.listdir(base_dir) if f.startswith("simulation_") and f.endswith(".xlsx")]

        if simulation_files:
            simulation_files.sort(reverse=True)  # 최신 파일 먼저
            latest_file = os.path.join(base_dir, simulation_files[0])
            self.load_excel_file(latest_file)

    def load_excel(self):
        """파일 다이얼로그로 엑셀 선택"""
        filepath = filedialog.askopenfilename(
            title="시뮬레이션 엑셀 선택",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            initialdir=os.path.dirname(os.path.abspath(__file__))
        )
        if filepath:
            self.load_excel_file(filepath)

    def load_excel_file(self, filepath):
        """엑셀 파일 로드"""
        if not PANDAS_AVAILABLE:
            messagebox.showerror("오류", "pandas가 설치되지 않았습니다.\npip install pandas openpyxl")
            return

        df = None
        error_messages = []

        # 1차 시도: openpyxl (xlsx)
        try:
            df = pd.read_excel(filepath, engine='openpyxl')
        except Exception as e:
            error_messages.append(f"openpyxl: {e}")

        # 2차 시도: xlrd (xls) - 구버전 형식
        if df is None:
            try:
                df = pd.read_excel(filepath, engine='xlrd')
            except Exception as e:
                error_messages.append(f"xlrd: {e}")

        # 3차 시도: engine 자동 감지
        if df is None:
            try:
                df = pd.read_excel(filepath)
            except Exception as e:
                error_messages.append(f"auto: {e}")

        # 4차 시도: HTML로 저장된 엑셀 (간혹 이런 경우 있음)
        if df is None:
            try:
                df = pd.read_html(filepath)[0]
            except Exception as e:
                error_messages.append(f"html: {e}")

        # 파일 헤더 확인 (디버깅용)
        if df is None:
            try:
                with open(filepath, 'rb') as f:
                    header = f.read(20)
                header_info = f"파일 헤더: {header[:10]}"
                if header.startswith(b'PK'):
                    header_info += " (ZIP/XLSX 형식)"
                elif header.startswith(b'<'):
                    header_info += " (HTML/XML 형식)"
                elif header.startswith(b'\xd0\xcf\x11\xe0'):
                    header_info += " (구 XLS 형식 - pip install xlrd)"
                else:
                    header_info += " (알 수 없는 형식)"
                error_messages.append(header_info)
            except:
                pass

        if df is not None:
            self.parse_excel_data(df)
            self.file_label.config(text=os.path.basename(filepath), foreground="black")
            self.count_label.config(text=f"상품: {len(self.data)}개")
            self.render_data()
        else:
            error_detail = "\n".join(error_messages)
            messagebox.showerror("오류", f"엑셀 로드 실패:\n\n{error_detail}\n\n해결방법:\n1. 엑셀에서 '다른 이름으로 저장' → 'Excel 통합 문서(*.xlsx)' 선택\n2. 또는: pip install xlrd (구버전 xls용)")

    def parse_excel_data(self, df):
        """엑셀 데이터 파싱"""
        self.data = []

        for idx, row in df.iterrows():
            item = {
                "row_idx": idx,
                "name": str(row.get("상품명", ""))[:30] if pd.notna(row.get("상품명")) else "",
                "is_safe": row.get("안전여부") == "O" if pd.notna(row.get("안전여부")) else True,
                "unsafe_reason": str(row.get("위험사유", "")) if pd.notna(row.get("위험사유")) else "",
                "thumbnail_formula": str(row.get("썸네일\n이미지", "")) if pd.notna(row.get("썸네일\n이미지")) else "",
                "option_image_formula": str(row.get("옵션\n이미지", "")) if pd.notna(row.get("옵션\n이미지")) else "",
                "total_options": row.get("전체옵션", 0) if pd.notna(row.get("전체옵션")) else 0,
                "final_options": row.get("최종옵션", 0) if pd.notna(row.get("최종옵션")) else 0,
                "bait_options": row.get("미끼옵션", 0) if pd.notna(row.get("미끼옵션")) else 0,
                "main_option": str(row.get("대표옵션", "")) if pd.notna(row.get("대표옵션")) else "",
                "selected": str(row.get("선택", "A")) if pd.notna(row.get("선택")) else "A",
                "option_names": str(row.get("옵션명", "")) if pd.notna(row.get("옵션명")) else "",
                "cn_option_names": str(row.get("중국어\n옵션명", "")) if pd.notna(row.get("중국어\n옵션명")) else "",
                "group_name": str(row.get("그룹명", "")) if pd.notna(row.get("그룹명")) else "",
            }

            # 썸네일 URL 추출
            item["thumbnail_url"] = self.extract_image_url(item["thumbnail_formula"])
            item["option_image_url"] = self.extract_image_url(item["option_image_formula"])

            # 옵션 파싱 (A. 블루, B. 레드 형태)
            item["options"] = self.parse_options(item["option_names"], item["cn_option_names"])

            self.data.append(item)
            self.selected_options[idx] = item["selected"]

    def extract_image_url(self, formula):
        """=IMAGE("url") 에서 URL 추출"""
        if not formula or not isinstance(formula, str):
            return ""
        if formula.startswith('=IMAGE("') and formula.endswith('")'):
            return formula[8:-2]
        return formula

    def parse_options(self, option_names, cn_option_names):
        """옵션명 파싱 (A. 블루\nB. 레드 형태)"""
        options = []

        if not option_names:
            return options

        # 한글 옵션
        ko_lines = option_names.strip().split('\n')
        # 중국어 옵션
        cn_lines = cn_option_names.strip().split('\n') if cn_option_names else []

        for i, line in enumerate(ko_lines):
            line = line.strip()
            if not line:
                continue

            # "A. 블루 대형" 형태 파싱
            if '. ' in line:
                parts = line.split('. ', 1)
                label = parts[0].strip()
                name = parts[1].strip() if len(parts) > 1 else ""
            else:
                label = chr(ord('A') + i)
                name = line

            # 중국어 옵션
            cn_name = ""
            if i < len(cn_lines):
                cn_line = cn_lines[i].strip()
                if '. ' in cn_line:
                    cn_name = cn_line.split('. ', 1)[1] if len(cn_line.split('. ', 1)) > 1 else cn_line
                else:
                    cn_name = cn_line

            options.append({
                "label": label,
                "name": name,
                "cn_name": cn_name,
                "image_url": ""  # 개별 옵션 이미지는 없음
            })

        return options

    def render_data(self):
        """데이터 렌더링"""
        # 기존 위젯 삭제
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        self.option_frames = {}

        if not self.data:
            ttk.Label(self.scrollable_frame, text="데이터 없음").pack(pady=50)
            return

        # 헤더
        self.create_header()

        # 데이터 행
        for item in self.data:
            self.create_row(item)

    def create_header(self):
        """헤더 생성"""
        header_frame = tk.Frame(self.scrollable_frame, bg="#4472C4")
        header_frame.pack(fill=tk.X, pady=(0, 2))

        headers = [
            ("썸네일", 100),
            ("옵션 선택 (클릭하여 대표옵션 변경)", 500),
            ("상품명", 180),
            ("안전", 50),
            ("옵션", 60),
            ("그룹", 100),
        ]

        for text, width in headers:
            lbl = tk.Label(header_frame, text=text, width=width//8, bg="#4472C4", fg="white",
                          font=("맑은 고딕", 9, "bold"), pady=5)
            lbl.pack(side=tk.LEFT, padx=1)

    def create_row(self, item):
        """데이터 행 생성 - 옵션 박스 선택 방식"""
        row_idx = item["row_idx"]

        # 배경색
        bg_color = "#C8E6C9" if item.get("is_safe", True) else "#FFCDD2"

        row_frame = tk.Frame(self.scrollable_frame, bg=bg_color, relief="solid", bd=1)
        row_frame.pack(fill=tk.X, pady=1)

        # 1. 썸네일
        thumb_frame = tk.Frame(row_frame, width=100, height=90, bg=bg_color)
        thumb_frame.pack(side=tk.LEFT, padx=2, pady=2)
        thumb_frame.pack_propagate(False)

        thumb_label = tk.Label(thumb_frame, text="[썸네일]", bg=bg_color, font=("맑은 고딕", 8))
        thumb_label.pack(expand=True)

        # 이미지 로드 (비동기로 하면 좋지만 일단 동기)
        if PIL_AVAILABLE and item.get("thumbnail_url"):
            self.load_image_async(item["thumbnail_url"], thumb_label, 80, 80)

        # 2. 옵션 선택 영역
        options_container = tk.Frame(row_frame, width=500, height=90, bg=bg_color)
        options_container.pack(side=tk.LEFT, padx=2, pady=2)
        options_container.pack_propagate(False)

        # 옵션 박스들
        options = item.get("options", [])
        max_display = 5  # 최대 표시 개수

        for i, opt in enumerate(options[:max_display]):
            is_selected = (self.selected_options.get(row_idx, "A") == opt["label"])

            opt_frame = tk.Frame(
                options_container,
                width=90, height=85,
                bg="#2196F3" if is_selected else "#E0E0E0",
                relief="solid",
                bd=2 if is_selected else 1,
                cursor="hand2"
            )
            opt_frame.pack(side=tk.LEFT, padx=2, pady=2)
            opt_frame.pack_propagate(False)

            # 클릭 이벤트 바인딩
            opt_frame.bind("<Button-1>", lambda e, r=row_idx, o=opt["label"]: self.on_option_click(r, o))

            # 옵션 라벨 (A, B, C...)
            lbl_text = opt["label"]
            lbl_color = "white" if is_selected else "black"
            lbl_bg = "#2196F3" if is_selected else "#E0E0E0"

            label_widget = tk.Label(opt_frame, text=lbl_text, bg=lbl_bg, fg=lbl_color,
                                   font=("맑은 고딕", 11, "bold"))
            label_widget.pack(pady=2)
            label_widget.bind("<Button-1>", lambda e, r=row_idx, o=opt["label"]: self.on_option_click(r, o))

            # 옵션명 (짧게)
            name_short = opt["name"][:8] + "..." if len(opt["name"]) > 8 else opt["name"]
            name_widget = tk.Label(opt_frame, text=name_short, bg=lbl_bg, fg=lbl_color,
                                  font=("맑은 고딕", 8), wraplength=80)
            name_widget.pack(pady=2)
            name_widget.bind("<Button-1>", lambda e, r=row_idx, o=opt["label"]: self.on_option_click(r, o))

            # 툴팁 (호버 시 전체 옵션명)
            self.create_tooltip(opt_frame, f"{opt['label']}. {opt['name']}\n{opt['cn_name']}")

            # 프레임 저장
            self.option_frames[(row_idx, opt["label"])] = {
                "frame": opt_frame,
                "label": label_widget,
                "name": name_widget
            }

        # 더보기 버튼 (옵션이 5개 초과인 경우)
        if len(options) > max_display:
            more_btn = tk.Label(options_container, text=f"+{len(options)-max_display}개",
                               bg="#9E9E9E", fg="white", font=("맑은 고딕", 9),
                               width=6, cursor="hand2")
            more_btn.pack(side=tk.LEFT, padx=2, pady=30)
            more_btn.bind("<Button-1>", lambda e, opts=options, r=row_idx: self.show_all_options(opts, r))

        # 3. 상품명
        name_frame = tk.Frame(row_frame, width=180, height=90, bg=bg_color)
        name_frame.pack(side=tk.LEFT, padx=2, pady=2)
        name_frame.pack_propagate(False)

        tk.Label(name_frame, text=item.get("name", "")[:25], bg=bg_color,
                font=("맑은 고딕", 9), wraplength=170, justify="left").pack(expand=True, padx=5)

        # 4. 안전여부
        safe_frame = tk.Frame(row_frame, width=50, height=90, bg=bg_color)
        safe_frame.pack(side=tk.LEFT, padx=2, pady=2)
        safe_frame.pack_propagate(False)

        safe_text = "O" if item.get("is_safe", True) else "X"
        safe_color = "#4CAF50" if item.get("is_safe", True) else "#F44336"
        tk.Label(safe_frame, text=safe_text, bg=bg_color, fg=safe_color,
                font=("맑은 고딕", 16, "bold")).pack(expand=True)

        # 5. 옵션 수
        opt_count_frame = tk.Frame(row_frame, width=60, height=90, bg=bg_color)
        opt_count_frame.pack(side=tk.LEFT, padx=2, pady=2)
        opt_count_frame.pack_propagate(False)

        tk.Label(opt_count_frame, text=f"{item.get('final_options', 0)}/{item.get('total_options', 0)}",
                bg=bg_color, font=("맑은 고딕", 9)).pack(expand=True)

        # 6. 그룹명
        group_frame = tk.Frame(row_frame, width=100, height=90, bg=bg_color)
        group_frame.pack(side=tk.LEFT, padx=2, pady=2)
        group_frame.pack_propagate(False)

        tk.Label(group_frame, text=item.get("group_name", "")[:12], bg=bg_color,
                font=("맑은 고딕", 8)).pack(expand=True)

    def on_option_click(self, row_idx, option_label):
        """옵션 박스 클릭 시"""
        old_selected = self.selected_options.get(row_idx, "A")

        # 이전 선택 해제 (회색으로)
        if (row_idx, old_selected) in self.option_frames:
            old_widgets = self.option_frames[(row_idx, old_selected)]
            old_widgets["frame"].config(bg="#E0E0E0", bd=1)
            old_widgets["label"].config(bg="#E0E0E0", fg="black")
            old_widgets["name"].config(bg="#E0E0E0", fg="black")

        # 새 선택 적용 (파란색으로)
        if (row_idx, option_label) in self.option_frames:
            new_widgets = self.option_frames[(row_idx, option_label)]
            new_widgets["frame"].config(bg="#2196F3", bd=2)
            new_widgets["label"].config(bg="#2196F3", fg="white")
            new_widgets["name"].config(bg="#2196F3", fg="white")

        self.selected_options[row_idx] = option_label
        print(f"[선택 변경] Row {row_idx}: {old_selected} → {option_label}")

    def show_all_options(self, options, row_idx):
        """모든 옵션 팝업"""
        popup = tk.Toplevel(self.root)
        popup.title(f"전체 옵션 ({len(options)}개)")
        popup.geometry("400x500")

        for opt in options:
            is_selected = (self.selected_options.get(row_idx, "A") == opt["label"])
            bg = "#2196F3" if is_selected else "#E0E0E0"
            fg = "white" if is_selected else "black"

            btn = tk.Button(popup, text=f"{opt['label']}. {opt['name']}\n{opt['cn_name']}",
                           bg=bg, fg=fg, font=("맑은 고딕", 10),
                           width=40, height=2,
                           command=lambda o=opt["label"]: self.select_from_popup(row_idx, o, popup))
            btn.pack(pady=2, padx=10)

    def select_from_popup(self, row_idx, option_label, popup):
        """팝업에서 옵션 선택"""
        self.on_option_click(row_idx, option_label)
        popup.destroy()

    def create_tooltip(self, widget, text):
        """툴팁 생성"""
        def show_tooltip(event):
            tooltip = tk.Toplevel(widget)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")

            label = tk.Label(tooltip, text=text, bg="lightyellow", relief="solid", bd=1,
                           font=("맑은 고딕", 9), padx=5, pady=3)
            label.pack()

            widget.tooltip = tooltip

        def hide_tooltip(event):
            if hasattr(widget, 'tooltip'):
                widget.tooltip.destroy()

        widget.bind("<Enter>", show_tooltip)
        widget.bind("<Leave>", hide_tooltip)

    def load_image_async(self, url, label, width, height):
        """이미지 로드"""
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
            pass  # 이미지 로드 실패 시 기본 텍스트 유지

    def save_changes(self):
        """변경사항 저장"""
        changes = []
        for row_idx, selected in self.selected_options.items():
            original = self.data[row_idx].get("selected", "A") if row_idx < len(self.data) else "A"
            if selected != original:
                changes.append(f"Row {row_idx}: {original} → {selected}")

        if changes:
            msg = f"변경된 항목: {len(changes)}개\n\n" + "\n".join(changes[:20])
            if len(changes) > 20:
                msg += f"\n... 외 {len(changes)-20}개"
            messagebox.showinfo("변경사항", msg)
        else:
            messagebox.showinfo("변경사항", "변경된 항목이 없습니다.")

    def update_bulsaja(self):
        """불사자 업데이트"""
        changes = []
        for row_idx, selected in self.selected_options.items():
            if row_idx < len(self.data):
                item = self.data[row_idx]
                changes.append({
                    "name": item.get("name", ""),
                    "selected": selected,
                    "group": item.get("group_name", "")
                })

        msg = f"총 {len(changes)}개 상품 업데이트 예정\n\n불사자 API 연동이 필요합니다."
        messagebox.showinfo("불사자 업데이트", msg)


def main():
    root = tk.Tk()
    app = SimulatorGUIv2(root)
    root.mainloop()


if __name__ == "__main__":
    main()
