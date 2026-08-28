# Pronunciation assessment service. CPU WhisperX baseline.
# Cloud host uses DaoCloud mirror + Tsinghua PyPI like ocr-service.
FROM docker.m.daocloud.io/library/python:3.10-bookworm

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PRON_HOST=0.0.0.0 \
    PRON_PORT=9190 \
    PRON_DEVICE=cpu \
    PRON_COMPUTE_TYPE=int8 \
    PRON_LANGUAGE=en \
    HF_HOME=/data/hf-cache

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's/deb.debian.org/mirrors.aliyun.com/g; s/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's/deb.debian.org/mirrors.aliyun.com/g; s/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list; \
    fi; \
    apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    "whisperx>=3.1.1" \
    "torch>=2.0.0" \
    "torchaudio>=2.0.0" \
    "librosa>=0.10.0" \
    "numpy>=1.23.0"

COPY engine.py main.py /app/

EXPOSE 9190
VOLUME ["/data/hf-cache"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9190/health', timeout=5).read()"

CMD ["python", "main.py"]
