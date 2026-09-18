# Voice gateway for InstaCloud. Built remotely; no local Docker needed.
# Lives at the repo root because the gateway reads routing.yaml and the cached
# authority fallback from the root.
FROM python:3.12-slim
WORKDIR /app
COPY gateway/requirements.txt gateway/requirements.txt
RUN pip install --no-cache-dir -r gateway/requirements.txt
COPY routing.yaml routing.yaml
COPY db/cached_authorities.json db/cached_authorities.json
COPY gateway gateway
WORKDIR /app/gateway
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
