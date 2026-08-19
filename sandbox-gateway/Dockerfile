FROM python:3.12-slim

# Gateway dependencies.
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.30"

# Sandbox runtime environment: sandboxed agent code sees this image's
# filesystem read-only, so what is installed here is what agents can import.
# Extend this list to enrich the code-interpreter environment.
RUN pip install --no-cache-dir \
    numpy \
    pandas \
    matplotlib \
    openpyxl \
    requests

WORKDIR /srv
COPY main.py .

# The gateway is internet-reachable; run it unprivileged. The platform-mounted
# sandbox CLI (/usr/local/gcp/bin/sandbox) does not require root.
RUN useradd --create-home --uid 1000 gateway
USER gateway

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
