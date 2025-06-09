FROM python:3.12-slim

# 安裝必要套件與 Chrome
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    wget \
    unzip \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# 安裝 Google Chrome（官方 stable 版）
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# 設定工作目錄並複製程式碼
WORKDIR /app
COPY . .

# 安裝 Python 套件
RUN pip install --upgrade pip && pip install -r requirements.txt

# 設定環境變數（必要時）
ENV PYTHONUNBUFFERED=1

# 執行主程式
CMD ["python", "report_bot_main.py"]