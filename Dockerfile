FROM python:3.13.13-alpine3.23 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .

RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir --prefix=/install -r requirements.txt

COPY ./src .


FROM python:3.13.13-alpine3.23 AS runtime

LABEL org.opencontainers.image.authors="Anthony Farina"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup -S -g 10015 docker && \
    adduser -S -u 10014 -G docker appuser

COPY --from=builder /install /usr/local
COPY --from=builder /app /app

USER appuser:docker

ENTRYPOINT ["python", "leviathan_bot.py"]