FROM python:3.11-slim

WORKDIR /app

# 安装必要的系统依赖 (针对 akshare, pandas 等可能需要的编译库)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

COPY . .

# 暴露 Streamlit 默认端口
EXPOSE 8501

# 默认启动命令留空，由 docker-compose 覆盖
