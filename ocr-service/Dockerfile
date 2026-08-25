# Cloud host cannot reach registry-1.docker.io; DaoCloud mirror is already used there.
FROM docker.m.daocloud.io/library/python:3.10-bookworm

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OCR_HOST=0.0.0.0 \
    OCR_PORT=9188 \
    OCR_CACHE_DIR=/data/ocr-cache \
    OCR_MODEL_VERSION=PP-OCRv5

# Cloud host often cannot reach deb.debian.org; use Aliyun Debian + Tsinghua PyPI.
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's/deb.debian.org/mirrors.aliyun.com/g; s/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's/deb.debian.org/mirrors.aliyun.com/g; s/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list; \
    fi; \
    apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# CPU Paddle + PP-OCRv5. First start downloads models into the cache volume.
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    "paddlepaddle==3.0.0" \
    "paddleocr>=3.0.0"

COPY engine.py cache.py main.py /app/

EXPOSE 9188
VOLUME ["/data/ocr-cache"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9188/health', timeout=5).read()"

CMD ["python", "main.py"]
