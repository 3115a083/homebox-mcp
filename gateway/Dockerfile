FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock \
    && useradd --uid 10001 --create-home app \
    && mkdir -p /state /labels && chown app:app /state /labels
COPY gateway.py bridge.py label_renderer.py import_photos.py migrate_to_ferret.py ferret_mcp_transport.py ferret_care_setup.py audit_ferret_tools.py ./
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER app
CMD ["python", "/app/gateway.py"]
