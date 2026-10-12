# Development-only MinIO build. Upstream community images are no longer
# reliably published; build pinned AGPL source rather than use a stale mirror.
FROM golang:1.24-bookworm AS server-build
RUN git clone --depth 1 --branch RELEASE.2025-10-15T17-29-55Z https://github.com/minio/minio.git /src
WORKDIR /src
RUN CGO_ENABLED=0 go build -o /out/minio .

FROM golang:1.24-bookworm AS client-build
RUN git clone --depth 1 --branch RELEASE.2025-04-16T18-13-26Z https://github.com/minio/mc.git /src
WORKDIR /src
RUN CGO_ENABLED=0 go build -o /out/mc .

FROM debian:bookworm-slim AS server
COPY --from=server-build /out/minio /usr/local/bin/minio
COPY --from=server-build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
EXPOSE 9000 9001
ENTRYPOINT ["minio"]

FROM debian:bookworm-slim AS client
COPY --from=client-build /out/mc /usr/local/bin/mc
COPY --from=client-build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
ENTRYPOINT ["mc"]
