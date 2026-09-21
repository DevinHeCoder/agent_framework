# syntax=docker/dockerfile:1
# ============ 阶段 1：构建依赖（隔离缓存，缩小最终镜像） ============
FROM python:3.13-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ============ 阶段 2：运行镜像（最小化 + 非 root + 健康检查） ============
FROM python:3.13-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# 复制已安装依赖
COPY --from=builder /install /usr/local

# 复制应用代码
COPY config/ ./config/
COPY src/ ./src/
COPY static/ ./static/

# 非 root 运行
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"]

CMD ["python", "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
