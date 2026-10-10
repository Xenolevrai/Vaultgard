# Image de production VaultGuard : Python minimal, utilisateur non-root, aucune clé dans l'image.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY agent/requirements.txt agent/requirements.txt
RUN pip install -r agent/requirements.txt && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin vaultguard \
    && mkdir -p /data && chown vaultguard /data
COPY agent/*.py agent/
COPY agent/abi agent/abi
COPY dashboard dashboard
RUN rm -f agent/test_*.py
USER vaultguard
WORKDIR /app/agent
# DB_PATH sur le volume /data : sinon la base irait dans /app/agent/data (non inscriptible, read_only, perdue au redémarrage)
ENV HOST=0.0.0.0 PORT=8000 AUDIT_PATH=/data/audit.jsonl DB_PATH=/data/vaultguard.db ENV_FILE=/nonexistent
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request as u;u.urlopen(u.Request('http://127.0.0.1:8000/healthz',headers={'Host':'localhost'}),timeout=2)"
CMD ["python", "server.py"]
