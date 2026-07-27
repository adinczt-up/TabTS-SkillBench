FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/tabts-skillbench
COPY . .
RUN uv pip install --system --no-cache ".[benchmark,runner]"

RUN useradd --create-home --uid 1000 benchmark \
    && mkdir -p /work /data \
    && chown -R benchmark:benchmark /work

USER benchmark
WORKDIR /work
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["tabts-bench"]
CMD ["--help"]
