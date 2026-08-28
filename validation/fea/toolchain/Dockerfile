FROM debian:bookworm-slim@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        calculix-ccx=2.20-1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

WORKDIR /workspace
