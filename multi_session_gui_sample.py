# -*- coding: utf-8 -*-
"""
멀티세션 GUI 샘플 - 두 가지 방식 비교
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
import random


class Option1_TabBasedGUI:
    """대안 1: 탭 기반 멀티세션 (v1.5 개선)"""

    def __init__(self, root):
        self.root = root
        self.root.title("대안 1: 탭 기반 멀티세션")
        self.root.geometry("800x600")

        # 상단: 그룹 선택 및 설정
        top_frame = ttk.LabelFrame(root, text="세션 설정", padding=10)
        top_frame.pack(fill=tk.X, padx=10, pady=5)

        # 그룹 선택
        ttk.Label(top_frame, text="그룹 선택:").pack(side=tk.LEFT)
        self.group_listbox = tk.Listbox(top_frame, selectmode=tk.MULTIPLE, height=3, width=30)
        self.group_listbox.pack(side=tk.LEFT, padx=5)
        for g in ["01_테스트그룹", "02_코드리크", "03_프코노미", "04_샘플스토어"]:
            self.group_listbox.insert(tk.END, g)

        # 설정
        settings_frame = ttk.Frame(top_frame)
        settings_frame.pack(side=tk.LEFT, padx=20)

        ttk.Label(settings_frame, text="업로드 수:").grid(row=0, column=0, sticky='w')
        ttk.Entry(settings_frame, width=6).grid(row=0, column=1)
        ttk.Label(settings_frame, text="옵션 수:").grid(row=1, column=0, sticky='w')
        ttk.Entry(settings_frame, width=6).grid(row=1, column=1)

        # 실행 버튼
        ttk.Button(top_frame, text="▶ 멀티세션 시작", command=self.start_sessions).pack(side=tk.RIGHT, padx=10)

        # 중앙: 탭 기반 로그
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 전체 로그 탭
        all_log_frame = ttk.Frame(self.notebook)
        self.notebook.add(all_log_frame, text="📋 전체 로그")

        self.all_log = tk.Text(all_log_frame, height=20, bg='#1e1e1e', fg='#ffffff', font=('Consolas', 10))
        self.all_log.pack(fill=tk.BOTH, expand=True)

        # 세션별 탭 (샘플)
        self.session_tabs = {}
        self.session_logs = {}

        # 하단: 진행률
        bottom_frame = ttk.Frame(root)
        bottom_frame.pack(fill=tk.X, padx=10, pady=5)

        self.progress_vars = {}
        self.progress_labels = {}

    def start_sessions(self):
        """선택된 그룹으로 세션 시작"""
        selections = self.group_listbox.curselection()
        if not selections:
            return

        # 기존 세션 탭 삭제
        for tab_id in list(self.session_tabs.keys()):
            self.notebook.forget(self.session_tabs[tab_id])
        self.session_tabs.clear()
        self.session_logs.clear()

        # 새 세션 탭 생성
        for i, idx in enumerate(selections):
            group_name = self.group_listbox.get(idx)
            session_id = i + 1

            # 탭 생성
            tab_frame = ttk.Frame(self.notebook)
            self.notebook.add(tab_frame, text=f"S{session_id}: {group_name[:10]}")
            self.session_tabs[session_id] = tab_frame

            # 상단: 진행률
            progress_frame = ttk.Frame(tab_frame)
            progress_frame.pack(fill=tk.X, padx=5, pady=5)

            var = tk.DoubleVar(value=0)
            self.progress_vars[session_id] = var

            ttk.Label(progress_frame, text=f"세션 #{session_id}").pack(side=tk.LEFT)
            ttk.Progressbar(progress_frame, variable=var, maximum=100, length=300).pack(side=tk.LEFT, padx=10)
            label = ttk.Label(progress_frame, text="0%")
            label.pack(side=tk.LEFT)
            self.progress_labels[session_id] = label

            # 로그 영역
            log_text = tk.Text(tab_frame, bg='#1e1e1e', fg='#00ff00', font=('Consolas', 10))
            log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            self.session_logs[session_id] = log_text

            # 시뮬레이션 시작
            threading.Thread(target=self.simulate_session, args=(session_id, group_name), daemon=True).start()

    def simulate_session(self, session_id, group_name):
        """세션 시뮬레이션"""
        log = self.session_logs[session_id]

        self.log_message(log, f"[세션 #{session_id}] {group_name} 시작\n", '#00ffff')
        self.log_message(self.all_log, f"[S{session_id}] {group_name} 시작\n", '#00ffff')

        for i in range(10):
            time.sleep(random.uniform(0.5, 1.5))
            progress = (i + 1) * 10
            self.progress_vars[session_id].set(progress)
            self.progress_labels[session_id].config(text=f"{progress}%")

            msg = f"[{i+1}/10] 상품 처리 완료\n"
            color = '#00ff00' if random.random() > 0.2 else '#ff6600'
            self.log_message(log, msg, color)
            self.log_message(self.all_log, f"[S{session_id}] {msg}", color)

        self.log_message(log, f"[완료] 세션 #{session_id} 종료\n", '#ffff00')
        self.log_message(self.all_log, f"[S{session_id}] 완료!\n", '#ffff00')

    def log_message(self, text_widget, msg, color='#ffffff'):
        """로그 메시지 추가"""
        text_widget.configure(state='normal')
        text_widget.insert(tk.END, msg)
        text_widget.see(tk.END)
        text_widget.configure(state='disabled')


class Option2_DashboardGUI:
    """대안 2: 대시보드 기반 (테이블 형태)"""

    def __init__(self, root):
        self.root = root
        self.root.title("대안 2: 대시보드 기반 멀티세션")
        self.root.geometry("900x600")

        # 상단: 그룹 선택
        top_frame = ttk.LabelFrame(root, text="그룹 선택", padding=10)
        top_frame.pack(fill=tk.X, padx=10, pady=5)

        self.group_vars = {}
        groups = ["01_테스트그룹", "02_코드리크", "03_프코노미", "04_샘플스토어", "05_추가스토어"]

        for i, g in enumerate(groups):
            var = tk.BooleanVar(value=False)
            self.group_vars[g] = var
            ttk.Checkbutton(top_frame, text=g, variable=var).grid(row=0, column=i, padx=10)

        ttk.Button(top_frame, text="전체 선택", command=self.select_all).grid(row=0, column=len(groups), padx=5)
        ttk.Button(top_frame, text="▶ 실행", command=self.start_all).grid(row=0, column=len(groups)+1, padx=5)

        # 중앙: 대시보드 테이블
        dash_frame = ttk.LabelFrame(root, text="세션 대시보드", padding=10)
        dash_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Treeview (테이블)
        columns = ('session', 'group', 'status', 'progress', 'success', 'failed', 'current')
        self.tree = ttk.Treeview(dash_frame, columns=columns, show='headings', height=8)

        self.tree.heading('session', text='세션')
        self.tree.heading('group', text='그룹')
        self.tree.heading('status', text='상태')
        self.tree.heading('progress', text='진행률')
        self.tree.heading('success', text='성공')
        self.tree.heading('failed', text='실패')
        self.tree.heading('current', text='현재 작업')

        self.tree.column('session', width=60, anchor='center')
        self.tree.column('group', width=150)
        self.tree.column('status', width=80, anchor='center')
        self.tree.column('progress', width=100, anchor='center')
        self.tree.column('success', width=60, anchor='center')
        self.tree.column('failed', width=60, anchor='center')
        self.tree.column('current', width=250)

        self.tree.pack(fill=tk.BOTH, expand=True)

        # 버튼 프레임
        btn_frame = ttk.Frame(dash_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        ttk.Button(btn_frame, text="선택 세션 중지", command=self.stop_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="선택 세션 재시작", command=self.restart_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="전체 중지", command=self.stop_all).pack(side=tk.RIGHT, padx=5)

        # 하단: 통합 로그 (접을 수 있음)
        log_frame = ttk.LabelFrame(root, text="통합 로그 (최근 50줄)", padding=5)
        log_frame.pack(fill=tk.X, padx=10, pady=5)

        self.log_text = tk.Text(log_frame, height=8, bg='#2d2d2d', fg='#e0e0e0', font=('Consolas', 9))
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 태그 설정 (색상)
        self.log_text.tag_configure('info', foreground='#a0a0a0')
        self.log_text.tag_configure('success', foreground='#00cc00')
        self.log_text.tag_configure('error', foreground='#ff4444')
        self.log_text.tag_configure('warning', foreground='#ffaa00')

        self.session_data = {}
        self.running = False

    def select_all(self):
        for var in self.group_vars.values():
            var.set(True)

    def start_all(self):
        """선택된 그룹 모두 실행"""
        selected = [g for g, var in self.group_vars.items() if var.get()]
        if not selected:
            return

        # 기존 데이터 클리어
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.session_data.clear()

        self.running = True

        # 각 그룹에 대해 세션 생성
        for i, group in enumerate(selected):
            session_id = i + 1
            item_id = self.tree.insert('', tk.END, values=(
                f"#{session_id}", group, "⏳ 대기", "0%", 0, 0, "초기화 중..."
            ))
            self.session_data[session_id] = {
                'item_id': item_id,
                'group': group,
                'success': 0,
                'failed': 0,
                'running': True
            }

            # 시뮬레이션 스레드 시작
            threading.Thread(target=self.simulate_session, args=(session_id,), daemon=True).start()

    def simulate_session(self, session_id):
        """세션 시뮬레이션"""
        data = self.session_data[session_id]
        item_id = data['item_id']
        group = data['group']

        self.log(f"[S{session_id}] {group} 시작", 'info')

        total = 10
        for i in range(total):
            if not data['running'] or not self.running:
                self.update_row(item_id, session_id, group, "⏹ 중지", f"{i*10}%", data['success'], data['failed'], "사용자 중지")
                self.log(f"[S{session_id}] 사용자에 의해 중지됨", 'warning')
                return

            time.sleep(random.uniform(0.8, 2.0))

            # 랜덤 성공/실패
            product_name = f"상품_{i+1}"
            if random.random() > 0.15:
                data['success'] += 1
                self.log(f"[S{session_id}] ✓ {product_name} 업로드 성공", 'success')
            else:
                data['failed'] += 1
                self.log(f"[S{session_id}] ✗ {product_name} 업로드 실패", 'error')

            progress = f"{(i+1)*10}%"
            self.update_row(item_id, session_id, group, "🔄 진행중", progress, data['success'], data['failed'], f"{product_name} 처리 완료")

        self.update_row(item_id, session_id, group, "✅ 완료", "100%", data['success'], data['failed'], "모든 작업 완료")
        self.log(f"[S{session_id}] {group} 완료 - 성공: {data['success']}, 실패: {data['failed']}", 'info')

    def update_row(self, item_id, session_id, group, status, progress, success, failed, current):
        """테이블 행 업데이트"""
        try:
            self.tree.item(item_id, values=(f"#{session_id}", group, status, progress, success, failed, current))
        except:
            pass

    def log(self, msg, tag='info'):
        """로그 추가"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state='normal')
        self.log_text.insert(tk.END, f"[{timestamp}] {msg}\n", tag)
        self.log_text.see(tk.END)
        # 50줄 제한
        lines = int(self.log_text.index('end-1c').split('.')[0])
        if lines > 50:
            self.log_text.delete('1.0', '2.0')
        self.log_text.configure(state='disabled')

    def stop_selected(self):
        """선택된 세션 중지"""
        selected = self.tree.selection()
        for item in selected:
            values = self.tree.item(item, 'values')
            session_id = int(values[0].replace('#', ''))
            if session_id in self.session_data:
                self.session_data[session_id]['running'] = False

    def restart_selected(self):
        """선택된 세션 재시작"""
        pass  # 구현 필요

    def stop_all(self):
        """전체 중지"""
        self.running = False
        for data in self.session_data.values():
            data['running'] = False


def main():
    # 선택 창
    selector = tk.Tk()
    selector.title("GUI 샘플 선택")
    selector.geometry("300x150")

    ttk.Label(selector, text="확인할 GUI 샘플을 선택하세요", font=('맑은 고딕', 11)).pack(pady=20)

    def show_option1():
        selector.destroy()
        root = tk.Tk()
        Option1_TabBasedGUI(root)
        root.mainloop()

    def show_option2():
        selector.destroy()
        root = tk.Tk()
        Option2_DashboardGUI(root)
        root.mainloop()

    ttk.Button(selector, text="대안 1: 탭 기반 (v1.5 개선)", command=show_option1, width=30).pack(pady=5)
    ttk.Button(selector, text="대안 2: 대시보드 기반", command=show_option2, width=30).pack(pady=5)

    selector.mainloop()


if __name__ == "__main__":
    main()
