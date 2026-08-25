# Cloud host cannot reach registry-1.docker.io; DaoCloud mirror is already used there.
FROM docker.m.daocloud.io/library/python:3.10-bookworm

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHARACTER_HOST=127.0.0.1 \
    CHARACTER_PORT=9189 \
    OCR_SERVICE_URL=http://127.0.0.1:9188 \
    MP_HOME=/data/mediapipe

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

# Hands only: skip mediapipe extras (jax / opencv-contrib), they blow up the image.
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    "numpy<2" \
    "opencv-python-headless==4.10.0.84" \
    "protobuf>=4.25.3,<5" \
    "absl-py" \
    "attrs" \
    "flatbuffers" \
    "sounddevice" \
    "matplotlib" \
 && pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --no-deps "mediapipe==0.10.14"

COPY geometry.py ocr_client.py hunyuan_ocr.py hands.py debug_draw.py pipeline.py main.py /app/

EXPOSE 9189

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9189/health', timeout=5).read()"

CMD ["python", "main.py"]
