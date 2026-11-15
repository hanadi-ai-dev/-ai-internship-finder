# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY src ./src
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home assistant && mkdir /app/data && chown assistant /app/data
COPY --chown=assistant:assistant config ./config
COPY --chown=assistant:assistant data/demo ./data/demo
USER assistant
EXPOSE 8000
CMD ["uvicorn", "internship_assistant.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
