# -*- coding: utf-8 -*-
"""
Claude Code 메모리뱅크 Hook v2.0
- 세션 시작/종료 시 컨텍스트 자동 저장/로드
- 중요 변경사항 자동 기록
- 대화 요약 자동 생성
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

# 경로 설정
MEMORY_DIR = Path(__file__).parent.parent / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_date():
    return datetime.now().strftime("%Y-%m-%d")

# ==================== 메모리뱅크 파일 관리 ====================

def update_active_context(task_name, details="", status="in_progress"):
    """현재 작업 상태 업데이트"""
    filepath = MEMORY_DIR / "activeContext.md"

    content = f"""# Active Context - 현재 작업 상태

## 현재 진행 중인 작업
**{task_name}**

## 상태
- {status}

## 세부 내용
{details}

## 마지막 업데이트
- {get_timestamp()}
"""
    filepath.write_text(content, encoding='utf-8')
    print(f"[MemoryBank] activeContext 업데이트: {task_name}")

def append_progress(entry, category="작업"):
    """진행 이력에 추가"""
    filepath = MEMORY_DIR / "progress.md"

    if filepath.exists():
        content = filepath.read_text(encoding='utf-8')
    else:
        content = "# Progress - 진행 이력\n\n"

    today = get_date()
    timestamp = datetime.now().strftime("%H:%M:%S")

    # 오늘 날짜 섹션이 없으면 추가
    if f"## {today}" not in content:
        content += f"\n## {today}\n"

    # 엔트리 추가
    content += f"- [{timestamp}] **[{category}]** {entry}\n"

    filepath.write_text(content, encoding='utf-8')
    print(f"[MemoryBank] progress 추가: {entry}")

def add_decision(title, decision, reason):
    """결정사항 추가"""
    filepath = MEMORY_DIR / "decisions.md"

    if filepath.exists():
        content = filepath.read_text(encoding='utf-8')
    else:
        content = "# Decisions - 주요 결정사항\n\n"

    timestamp = get_timestamp()
    entry = f"""
### {title}
- **결정**: {decision}
- **이유**: {reason}
- **일시**: {timestamp}
---
"""
    content += entry
    filepath.write_text(content, encoding='utf-8')
    print(f"[MemoryBank] decision 추가: {title}")

def update_tech_context(key, value):
    """기술 컨텍스트 업데이트"""
    filepath = MEMORY_DIR / "techContext.md"

    if filepath.exists():
        content = filepath.read_text(encoding='utf-8')
    else:
        content = "# Tech Context - 기술 컨텍스트\n\n"

    # 기존 키가 있으면 업데이트, 없으면 추가
    lines = content.split('\n')
    updated = False
    new_lines = []

    for line in lines:
        if line.startswith(f"- **{key}**:"):
            new_lines.append(f"- **{key}**: {value}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"- **{key}**: {value}")

    filepath.write_text('\n'.join(new_lines), encoding='utf-8')
    print(f"[MemoryBank] techContext 업데이트: {key}={value}")

# ==================== 세션 관리 ====================

def load_context():
    """세션 시작 시 컨텍스트 로드 (Claude가 읽을 수 있는 형태로)"""
    context_parts = []

    files = ["activeContext.md", "progress.md", "decisions.md", "techContext.md"]

    for filename in files:
        filepath = MEMORY_DIR / filename
        if filepath.exists():
            content = filepath.read_text(encoding='utf-8')
            # progress.md는 최근 20줄만
            if filename == "progress.md":
                lines = content.split('\n')
                # 헤더 + 최근 항목만
                header = lines[:2]
                recent = [l for l in lines[2:] if l.strip()][-20:]
                content = '\n'.join(header + recent)

            context_parts.append(f"=== {filename} ===\n{content}")

    return '\n\n'.join(context_parts)

def save_session_summary(summary):
    """세션 종료 시 요약 저장"""
    filepath = MEMORY_DIR / "sessions.md"

    if filepath.exists():
        content = filepath.read_text(encoding='utf-8')
    else:
        content = "# Session History - 세션 이력\n\n"

    timestamp = get_timestamp()

    # 세션 요약 추가
    entry = f"""
## Session: {timestamp}
{summary}

---
"""
    content += entry

    # 최근 10개 세션만 유지 (파일 크기 관리)
    sessions = content.split('## Session:')
    if len(sessions) > 11:  # 헤더 + 10개 세션
        content = sessions[0] + '## Session:'.join(sessions[-10:])

    filepath.write_text(content, encoding='utf-8')
    print(f"[MemoryBank] 세션 저장 완료")

def auto_save_on_stop(stdin_data=None):
    """Stop Hook: 세션 종료 시 자동 저장

    stdin으로 대화 요약 정보를 받아서 저장
    """
    summary_parts = []

    # stdin에서 대화 요약 읽기 (Claude가 전달)
    if stdin_data:
        try:
            data = json.loads(stdin_data)
            if 'summary' in data:
                summary_parts.append(data['summary'])
            if 'files_modified' in data:
                summary_parts.append(f"수정된 파일: {', '.join(data['files_modified'])}")
        except:
            summary_parts.append(stdin_data)

    # 현재 activeContext 읽기
    active_path = MEMORY_DIR / "activeContext.md"
    if active_path.exists():
        active_content = active_path.read_text(encoding='utf-8')
        # 작업명 추출
        for line in active_content.split('\n'):
            if line.startswith('**') and line.endswith('**'):
                summary_parts.append(f"마지막 작업: {line.strip('*')}")
                break

    if not summary_parts:
        summary_parts.append("세션 종료 (자동 저장)")

    save_session_summary('\n'.join(summary_parts))

    # activeContext 초기화
    update_active_context("대기 중", "", "idle")

def compact_memory():
    """메모리뱅크 압축 (오래된 항목 정리)"""
    # progress.md 압축 - 최근 7일만 유지
    progress_path = MEMORY_DIR / "progress.md"
    if progress_path.exists():
        content = progress_path.read_text(encoding='utf-8')
        lines = content.split('\n')

        header = []
        date_sections = {}
        current_date = None

        for line in lines:
            if line.startswith('# '):
                header.append(line)
            elif line.startswith('## '):
                current_date = line.replace('## ', '')
                date_sections[current_date] = []
            elif current_date:
                date_sections[current_date].append(line)

        # 최근 7일만 유지
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

        new_content = '\n'.join(header) + '\n'
        for date in sorted(date_sections.keys()):
            if date >= cutoff:
                new_content += f"\n## {date}\n"
                new_content += '\n'.join(date_sections[date])

        progress_path.write_text(new_content, encoding='utf-8')
        print(f"[MemoryBank] progress.md 압축 완료 (최근 7일 유지)")

    # decisions.md 압축 - 최근 20개만 유지
    decisions_path = MEMORY_DIR / "decisions.md"
    if decisions_path.exists():
        content = decisions_path.read_text(encoding='utf-8')
        sections = content.split('### ')

        if len(sections) > 21:  # 헤더 + 20개
            header = sections[0]
            recent = sections[-20:]
            content = header + '### '.join(recent)
            decisions_path.write_text(content, encoding='utf-8')
            print(f"[MemoryBank] decisions.md 압축 완료 (최근 20개 유지)")

# ==================== CLI 인터페이스 ====================

def print_help():
    print("""
Claude Code 메모리뱅크 Hook v2.0

Usage: python memory_hook.py [command] [args...]

Commands:
  load                           - 컨텍스트 로드 (세션 시작)
  update [task] [details]        - 현재 작업 업데이트
  progress [entry] [category]    - 진행 기록 추가
  decision [title] [decision] [reason] - 결정사항 추가
  tech [key] [value]             - 기술 컨텍스트 업데이트
  save [summary]                 - 세션 저장
  compact                        - 메모리뱅크 압축
  stop                           - Stop Hook (stdin에서 요약 읽음)

Examples:
  python memory_hook.py update "PPT 기반 검수 업데이트" "지재권 위험 키워드 추가"
  python memory_hook.py progress "BRAND_KEYWORDS 139개로 확장" "코드"
  python memory_hook.py decision "브랜드키워드" "빈set으로 항상위험" "제품유형과 일치하는 단어 포함"
""")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_help()
        sys.exit(1)

    command = sys.argv[1]

    if command == "load":
        ctx = load_context()
        print(ctx)

    elif command == "update":
        task = sys.argv[2] if len(sys.argv) > 2 else "작업 중"
        details = sys.argv[3] if len(sys.argv) > 3 else ""
        update_active_context(task, details)

    elif command == "progress":
        entry = sys.argv[2] if len(sys.argv) > 2 else "진행"
        category = sys.argv[3] if len(sys.argv) > 3 else "작업"
        append_progress(entry, category)

    elif command == "decision":
        if len(sys.argv) >= 5:
            add_decision(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]))
        else:
            print("Error: decision requires title, decision, reason")

    elif command == "tech":
        if len(sys.argv) >= 4:
            update_tech_context(sys.argv[2], " ".join(sys.argv[3:]))
        else:
            print("Error: tech requires key and value")

    elif command == "save":
        summary = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "세션 종료"
        save_session_summary(summary)

    elif command == "compact":
        compact_memory()

    elif command == "stop":
        # stdin에서 데이터 읽기 (Hook에서 전달)
        stdin_data = None
        if not sys.stdin.isatty():
            stdin_data = sys.stdin.read()
        auto_save_on_stop(stdin_data)

    elif command == "help" or command == "-h":
        print_help()

    else:
        print(f"Unknown command: {command}")
        print_help()
        sys.exit(1)
