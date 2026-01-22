# Git 워크플로우 교훈 (2025-01-22)

## 사건 개요

Pconomy 대시보드가 Gemini의 git 복구 작업 후 망가진 원인을 분석한 결과, **git commit과 push의 차이**를 이해하지 못한 것이 근본 원인이었음.

---

## 발견된 문제점

### 1. Gemini의 실수
- **app.js 변경사항 미커밋**: 1월 18일~21일 동안 app.js를 수정했지만 커밋하지 않음
- **push 미실행**: 커밋을 해도 GitHub에 push하지 않음
- **복구 시 원격 저장소 사용**: `git restore`로 복구할 때 GitHub의 오래된 버전(1월 18일)을 가져옴

### 2. 동일한 실수 반복
- Claude도 커밋 후 push를 하지 않아 사용자가 GitHub에서 직접 확인 후 지적

---

## 핵심 교훈

### 교훈 1: commit ≠ push
```
git commit = 로컬 저장소에만 저장 (내 컴퓨터)
git push   = 원격 저장소에 업로드 (GitHub)
```

**반드시 commit + push를 함께 실행해야 백업이 완료됨**

### 교훈 2: 모든 파일 확인
```bash
git status  # 먼저 상태 확인
git add .   # 모든 변경 파일 스테이징
git commit -m "메시지"
git push origin main
```

`git add .` 사용 시에도 `.gitignore`에 포함된 파일은 제외됨.
새로운 파일이나 폴더가 추가되었는지 항상 확인할 것.

### 교훈 3: GitHub 웹에서 검증
커밋/푸시 후 반드시 GitHub 웹사이트에서 확인:
- 파일이 실제로 업로드되었는지
- 최신 커밋 시간이 맞는지
- 파일 내용이 정확한지

### 교훈 4: 복구 전 확인사항
`git restore` 또는 `git checkout` 실행 전:
1. 현재 로컬 파일 백업
2. 원격 저장소의 해당 파일 버전 확인
3. 어떤 버전으로 복구되는지 이해

---

## 올바른 Git 워크플로우

### 작업 완료 후
```bash
# 1. 상태 확인
git status

# 2. 변경사항 스테이징
git add .

# 3. 커밋
git commit -m "작업 내용 설명"

# 4. 푸시 (필수!)
git push origin main

# 5. GitHub 웹에서 확인
```

### 복구가 필요할 때
```bash
# 1. 현재 파일 백업 (중요!)
cp file.js file.js.backup

# 2. GitHub에서 해당 파일 히스토리 확인
# 3. 복구 실행
git restore file.js

# 4. 복구된 내용 검토
```

---

## 이 사건에서 배운 점

| 항목 | 잘못된 방식 | 올바른 방식 |
|------|------------|------------|
| 백업 | commit만 함 | commit + push |
| 확인 | 터미널 메시지만 봄 | GitHub 웹에서 검증 |
| 복구 | 무조건 git restore | 백업 후 복구 |
| 파일 | 일부 파일만 add | git status로 전체 확인 |

---

## 체크리스트

작업 완료 시:
- [ ] `git status`로 모든 변경 파일 확인
- [ ] `git add .`로 스테이징
- [ ] `git commit`으로 커밋
- [ ] `git push`로 GitHub에 업로드
- [ ] GitHub 웹에서 파일 확인

복구 시:
- [ ] 현재 파일 백업
- [ ] GitHub에서 복구할 버전 확인
- [ ] 복구 후 정상 동작 테스트
