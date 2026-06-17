# 1. 使用官方輕量版 Python 基礎鏡像
FROM python:3.10-slim

# 2. 安裝系統依賴（包含解決預覽錯誤必備的 ffmpeg 與字體軟體）
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

# 3. 設定工作目錄
WORKDIR /app

# 4. 複製並安裝 Python 套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 複製專案所有程式碼
COPY . .

# 6. 設定 Railway 啟動指令 (符合 Gradio 6.0+ 規範，自動帶入環境變數與 PORT)
CMD ["sh", "-c", "GRADIO_ANALYTICS_ENABLED=False GRADIO_SERVER_NAME=0.0.0.0 GRADIO_SERVER_PORT=${PORT:-7860} python app.py"]
