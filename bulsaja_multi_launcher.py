# -*- coding: utf-8 -*-
"""
불사자 멀티 터미널 런처
- 여러 터미널 창에서 동시에 업로드 실행
- 각 세션이 독립적으로 진행됨

사용법:
    python bulsaja_multi_launcher.py
"""

import os
import sys
import json
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox


CONFIG_FILE = "bulsaja_uploader_config.json"


class MultiLauncher:
    """멀티 터미널 런처 GUI"""

    def __init__(self, root):
        self.root = root
        self.root.title("불사자 멀티 터미널 런처")
        self.root.geometry("600x500")
        self.root.resizable(False, False)

        self.config = self._load_config()
        self.group_vars = {}  # {group_name: BooleanVar}

        self._create_ui()

    def _load_config(self) -> dict:
        """설정 파일 로드"""
        config_path = Path(__file__).parent / CONFIG_FILE
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _save_config(self):
        """설정 파일 저장"""
        config_path = Path(__file__).parent / CONFIG_FILE
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def _create_ui(self):
        # 상단 설명
        header = ttk.Frame(self.root, padding=10)
        header.pack(fill=tk.X)

        ttk.Label(header, text="멀티 터미널 업로드", font=("맑은 고딕", 14, "bold")).pack()
        ttk.Label(header, text="선택한 그룹마다 별도 터미널 창에서 업로드가 진행됩니다",
                 foreground="gray").pack()

        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)

        # 그룹 선택 영역
        group_frame = ttk.LabelFrame(self.root, text="마켓 그룹 선택", padding=10)
        group_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 스크롤 가능한 프레임
        canvas = tk.Canvas(group_frame)
        scrollbar = ttk.Scrollbar(group_frame, orient=tk.VERTICAL, command=canvas.yview)
        self.groups_inner = ttk.Frame(canvas)

        self.groups_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.groups_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 그룹 목록 로드
        self._load_groups()

        # 설정 영역
        settings_frame = ttk.LabelFrame(self.root, text="업로드 설정", padding=10)
        settings_frame.pack(fill=tk.X, padx=10, pady=5)

        # 1행
        row1 = ttk.Frame(settings_frame)
        row1.pack(fill=tk.X, pady=2)

        ttk.Label(row1, text="업로드 수:").pack(side=tk.LEFT)
        self.upload_count_var = tk.StringVar(value=str(self.config.get('upload_count', 10)))
        ttk.Entry(row1, textvariable=self.upload_count_var, width=6).pack(side=tk.LEFT, padx=5)

        ttk.Label(row1, text="옵션 수:").pack(side=tk.LEFT, padx=(20, 0))
        self.option_count_var = tk.StringVar(value=str(self.config.get('option_count', 5)))
        ttk.Entry(row1, textvariable=self.option_count_var, width=6).pack(side=tk.LEFT, padx=5)

        ttk.Label(row1, text="마켓:").pack(side=tk.LEFT, padx=(20, 0))
        self.market_var = tk.StringVar(value=self.config.get('market', '스마트스토어'))
        ttk.Combobox(row1, textvariable=self.market_var, width=12,
                    values=['스마트스토어', '11번가', 'G마켓/옥션', '쿠팡']).pack(side=tk.LEFT, padx=5)

        # 2행
        row2 = ttk.Frame(settings_frame)
        row2.pack(fill=tk.X, pady=2)

        ttk.Label(row2, text="옵션정렬:").pack(side=tk.LEFT)
        self.sort_var = tk.StringVar(value=self.config.get('option_sort', 'price_asc'))
        ttk.Combobox(row2, textvariable=self.sort_var, width=12,
                    values=['price_asc', 'price_desc', 'price_main']).pack(side=tk.LEFT, padx=5)

        self.prevent_dup_var = tk.BooleanVar(value=self.config.get('prevent_duplicate', True))
        ttk.Checkbutton(row2, text="중복업로드 방지", variable=self.prevent_dup_var).pack(side=tk.LEFT, padx=20)

        # 실행 버튼
        btn_frame = ttk.Frame(self.root, padding=10)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="전체 선택", command=self._select_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="전체 해제", command=self._deselect_all).pack(side=tk.LEFT, padx=5)

        self.launch_btn = ttk.Button(btn_frame, text="▶ 터미널 실행", command=self._launch_terminals)
        self.launch_btn.pack(side=tk.RIGHT, padx=5)

        ttk.Button(btn_frame, text="닫기", command=self.root.destroy).pack(side=tk.RIGHT, padx=5)

        # 상태바
        self.status_var = tk.StringVar(value="그룹을 선택하고 '터미널 실행'을 클릭하세요")
        ttk.Label(self.root, textvariable=self.status_var, foreground="gray").pack(pady=5)

    def _load_groups(self):
        """마켓 그룹 목록 로드"""
        # 기존 위젯 삭제
        for widget in self.groups_inner.winfo_children():
            widget.destroy()

        self.group_vars = {}

        # API에서 그룹 목록 가져오기
        try:
            from bulsaja_common import BulsajaAPIClient
            api = BulsajaAPIClient(
                self.config.get('access_token', ''),
                self.config.get('refresh_token', '')
            )
            groups = api.get_market_groups()

            if not groups:
                ttk.Label(self.groups_inner, text="그룹이 없습니다. 토큰을 확인하세요.",
                         foreground="red").pack(pady=20)
                return

            for group_name in groups:
                # groups는 문자열 리스트
                if not group_name:
                    continue

                var = tk.BooleanVar(value=False)
                self.group_vars[group_name] = var

                frame = ttk.Frame(self.groups_inner)
                frame.pack(fill=tk.X, pady=2)

                cb = ttk.Checkbutton(frame, text=group_name, variable=var)
                cb.pack(side=tk.LEFT)

        except Exception as e:
            ttk.Label(self.groups_inner, text=f"그룹 로드 실패: {e}",
                     foreground="red").pack(pady=20)

    def _select_all(self):
        """전체 선택"""
        for var in self.group_vars.values():
            var.set(True)

    def _deselect_all(self):
        """전체 해제"""
        for var in self.group_vars.values():
            var.set(False)

    def _launch_terminals(self):
        """선택된 그룹마다 터미널 실행"""
        selected_groups = [name for name, var in self.group_vars.items() if var.get()]

        if not selected_groups:
            messagebox.showwarning("경고", "그룹을 1개 이상 선택하세요")
            return

        # 설정 저장
        self.config['upload_count'] = int(self.upload_count_var.get())
        self.config['option_count'] = int(self.option_count_var.get())
        self.config['market'] = self.market_var.get()
        self.config['market_name'] = self.market_var.get()
        self.config['option_sort'] = self.sort_var.get()
        self.config['prevent_duplicate'] = self.prevent_dup_var.get()
        self._save_config()

        # 각 그룹에 대해 터미널 실행
        script_path = Path(__file__).parent / "bulsaja_uploader_cli.py"

        if not script_path.exists():
            messagebox.showerror("오류", "bulsaja_uploader_cli.py 파일이 없습니다")
            return

        # 임시 설정 파일 생성 (세션별)
        temp_dir = Path(tempfile.gettempdir()) / "bulsaja_multi"
        temp_dir.mkdir(exist_ok=True)

        launched = 0
        for i, group_name in enumerate(selected_groups, 1):
            # 세션별 설정 파일
            session_config = self.config.copy()
            session_config_file = temp_dir / f"session_{i}_config.json"

            with open(session_config_file, 'w', encoding='utf-8') as f:
                json.dump(session_config, f, ensure_ascii=False, indent=2)

            # Windows에서 새 cmd 창 열기
            cmd = [
                'cmd', '/c', 'start',
                f'세션 #{i} - {group_name}',  # 창 제목
                'cmd', '/k',
                'python', str(script_path),
                '--config', str(session_config_file),
                '--session', str(i),
                '--group', group_name
            ]

            try:
                subprocess.Popen(cmd, shell=True)
                launched += 1
            except Exception as e:
                messagebox.showerror("오류", f"터미널 실행 실패: {e}")

        if launched > 0:
            self.status_var.set(f"{launched}개 터미널 창이 실행되었습니다")
            messagebox.showinfo("실행 완료", f"{launched}개의 터미널 창이 열렸습니다.\n각 창에서 업로드가 진행됩니다.")


def main():
    root = tk.Tk()
    app = MultiLauncher(root)
    root.mainloop()


if __name__ == "__main__":
    main()
