"""
시장 데이터 로컬 대시보드 (별도 포트 5051).
- data/latest.json을 읽어서 표시
- '지금 새로고침' 버튼으로 fetch_market.py를 즉시 실행

실행:
    python3 market_dashboard.py
브라우저:
    http://localhost:5051
"""
import json
import subprocess
import sys
from pathlib import Path
from flask import Flask, send_from_directory, jsonify

BASE = Path(__file__).parent
DOCS_DIR = BASE / "docs"
DATA_DIR = DOCS_DIR / "data"

app = Flask(__name__)


@app.route("/")
def index():
    return send_from_directory(DOCS_DIR, "index.html")


@app.route("/data/latest.json")
def latest():
    f = DATA_DIR / "latest.json"
    if not f.exists():
        return jsonify({"error": "no data yet — run fetch_market.py first"}), 404
    return send_from_directory(DATA_DIR, "latest.json")


@app.route("/api/refresh", methods=["POST"])
def refresh():
    """fetch_market.py를 즉시 실행 (텔레그램은 환경변수가 있을 때만 보냄)."""
    try:
        result = subprocess.run(
            [sys.executable, str(BASE / "fetch_market.py")],
            capture_output=True, text=True, timeout=120,
        )
        return jsonify({
            "ok": result.returncode == 0,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
        })
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "timeout"}), 504
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    import socket
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "127.0.0.1"
    print("\n" + "=" * 50)
    print("  📊 시장 데이터 대시보드")
    print("=" * 50)
    print(f"  로컬:        http://localhost:5051")
    print(f"  같은 와이파이: http://{local_ip}:5051")
    print("=" * 50 + "\n")
    app.run(host="0.0.0.0", port=5051, debug=False)
