"""
로컬 런처 서버
- 웹에서 요청 받아서 bulsabot.py 실행
- 사용법: local_launcher.exe 실행
- 기본 포트: 9999
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import subprocess
import os
import sys
import threading

app = Flask(__name__)
CORS(app)  # 외부 웹에서 요청 허용

# 설정 - exe와 같은 폴더의 bulsabot.py 사용
if getattr(sys, 'frozen', False):
    # PyInstaller로 빌드된 경우
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BULSABOT_PATH = os.path.join(BASE_DIR, "bulsabot.py")
current_process = None

@app.route('/run', methods=['POST'])
def run_bulsabot():
    global current_process
    
    try:
        data = request.json or {}
        groups = data.get('groups', '')
        max_concurrent = data.get('max_concurrent', 3)
        group_gap = data.get('group_gap', 60)
        
        if not groups:
            return jsonify({"success": False, "message": "그룹을 지정하세요"})
        
        if not os.path.exists(BULSABOT_PATH):
            return jsonify({"success": False, "message": f"파일 없음: {BULSABOT_PATH}"})
        
        # 환경변수 설정
        env = os.environ.copy()
        env["BULSABOT_GROUPS"] = groups
        env["BULSABOT_MAX_CONCURRENT"] = str(max_concurrent)
        env["BULSABOT_GROUP_GAP"] = str(group_gap)
        env["BULSABOT_NO_POPUP"] = "1"
        
        # Python 찾기
        python_exe = sys.executable if not getattr(sys, 'frozen', False) else "python"
        
        # 새 콘솔에서 실행
        current_process = subprocess.Popen(
            [python_exe, BULSABOT_PATH],
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0,
            env=env
        )
        
        print(f"[실행] bulsabot.py 시작 - 그룹: {groups}, 동시: {max_concurrent}")
        
        return jsonify({
            "success": True, 
            "message": f"실행 시작! 그룹: {groups}",
            "pid": current_process.pid
        })
        
    except Exception as e:
        print(f"[오류] {e}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/stop', methods=['POST'])
def stop_bulsabot():
    global current_process
    
    if current_process:
        try:
            current_process.terminate()
            current_process = None
            return jsonify({"success": True, "message": "중지됨"})
        except:
            pass
    
    return jsonify({"success": False, "message": "실행 중인 프로세스 없음"})

@app.route('/status', methods=['GET'])
def get_status():
    global current_process
    
    running = False
    if current_process:
        poll = current_process.poll()
        running = poll is None
        if not running:
            current_process = None
    
    return jsonify({
        "running": running,
        "pid": current_process.pid if current_process else None
    })

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"ok": True, "message": "로컬 런처 실행 중"})

def main():
    print("=" * 50)
    print("🚀 로컬 런처 서버 시작")
    print(f"📁 실행 경로: {BASE_DIR}")
    print(f"📁 bulsabot: {BULSABOT_PATH}")
    print(f"🌐 http://localhost:9999")
    print("=" * 50)
    print("이 창을 닫지 마세요!")
    print("")
    
    app.run(host='127.0.0.1', port=9999, debug=False, use_reloader=False)

if __name__ == '__main__':
    main()
