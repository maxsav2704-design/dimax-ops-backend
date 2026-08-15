FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_ROOT_USER_ACTION=ignore

ARG DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-heb \
    tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
COPY constraints.txt /app/constraints.txt
RUN python -m pip install --no-cache-dir --upgrade pip==26.1.2 \
    && pip install --no-cache-dir -c constraints.txt -r requirements.txt \
    && pip check

RUN groupadd --gid 10001 dimax \
    && useradd --uid 10001 --gid 10001 --no-create-home \
        --home-dir /app --shell /usr/sbin/nologin dimax

COPY --chown=10001:10001 . /app
COPY --chown=10001:10001 --chmod=755 docker-entrypoint.sh /usr/local/bin/dimax-entrypoint

USER 10001:10001

ENTRYPOINT ["/usr/local/bin/dimax-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
