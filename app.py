import os
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "인벤토리 관리 시스템 작동 중!"

if __name__ == "__main__":
    # Render 환경에 맞는 포트 설정
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
