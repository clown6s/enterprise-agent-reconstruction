# 应用镜像：构建依赖 + 运行依赖分离，减小最终镜像
FROM python:3.13-slim AS build

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/opt/appdeps -r requirements.txt

# 只拷贝运行期需要的东西，避免把测试/脚本带进镜像
FROM python:3.13-slim AS runtime

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENV=prod

# requirements 中有需要编译的库（bcrypt、opentelemetry 等），装最小编译工具
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/appdeps /usr/local
COPY app ./app
COPY main.py ./main.py
COPY scripts ./scripts

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys;urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=3)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]