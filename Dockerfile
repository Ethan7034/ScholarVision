# Scholar Vision v2.0
# 后端 API 镜像：FastAPI + PyMuPDF + Redis 客户端
# 说明：本文件与 docker-compose.yml 一起构成 README 中第 8 层（Infrastructure）的实现。
# 单独 `docker build` 也能跑，但缓存/队列需要 Redis，推荐用 docker compose up。

FROM python:3.12-slim

# 不写 .pyc、不加 buffer，容器内日志能实时刷出
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖再拷代码：改代码时依赖层命中缓存，构建更快
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 端口仅供容器内部与宿主机映射使用，实际对外暴露由 compose / 隧道决定
EXPOSE 8000

# 生产环境不要开 --reload（reload 会额外起进程，与 compose 的 restart 策略冲突）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
