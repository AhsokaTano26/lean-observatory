# Trusted toolchain image only. Project/tool SOURCE builds occur at runtime after
# the queue's RH/resource/budget gates. No RH files or volumes are referenced.
FROM golang:1.26.0-bookworm AS go-toolchain
FROM rust:1.92.0-bookworm AS rust-toolchain
FROM ubuntu:24.04 AS trusted-environment
ENV DEBIAN_FRONTEND=noninteractive ELAN_HOME=/home/lean/.elan
RUN apt-get update && apt-get install -y --no-install-recommends python3 curl git ca-certificates xz-utils zstd elan build-essential util-linux && rm -rf /var/lib/apt/lists/*
COPY --from=go-toolchain /usr/local/go /usr/local/go
COPY --from=rust-toolchain /usr/local/cargo /opt/rust/cargo
COPY --from=rust-toolchain /usr/local/rustup /opt/rust/rustup
ENV PATH=/home/lean/.elan/bin:$PATH
RUN elan toolchain install leanprover/lean4:v4.34.0-rc2 && elan default leanprover/lean4:v4.34.0-rc2 && lean --version

FROM python:3.13-slim-bookworm AS ns-worker
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 SANDBOX_ROOT=/sandbox
RUN apt-get update && apt-get install -y --no-install-recommends util-linux coreutils ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=trusted-environment /usr /sandbox/usr
COPY --from=trusted-environment /etc /sandbox/etc
COPY --from=trusted-environment /home/lean/.elan /sandbox/home/lean/.elan
COPY --from=trusted-environment /opt/rust /sandbox/opt/rust
RUN mkdir -p /data /sandbox/work /sandbox/proc /sandbox/tmp /sandbox/dev /sandbox/opt/ns-queue \
 && chmod 1777 /sandbox/tmp \
 && ln -s usr/bin /sandbox/bin && ln -s usr/sbin /sandbox/sbin && ln -s usr/lib /sandbox/lib \
 && if [ -d /sandbox/usr/lib64 ]; then ln -s usr/lib64 /sandbox/lib64; fi \
 && touch /sandbox/dev/null /sandbox/dev/urandom && chmod 666 /sandbox/dev/null \
 && chown 0:10001 /data && chmod 2770 /data
WORKDIR /app
COPY ns_queue ./ns_queue
COPY ns_queue/child.py ns_queue/build-tools.sh ns_queue/manifest.json /sandbox/opt/ns-queue/
RUN chmod 755 /sandbox/opt/ns-queue/child.py /sandbox/opt/ns-queue/build-tools.sh \
 && ln -s /opt/ns-queue/child.py /sandbox/usr/local/bin/comparator-landrun \
 && ln -s /work/ns/tools/nanoda/target/release/nanoda_bin /sandbox/usr/local/bin/nanoda_bin \
 && printf '[safe]\n\tdirectory = /work/ns/tools/comparator\n\tdirectory = /work/ns/tools/comparator/.lake/packages/lean4export\n\tdirectory = /work/ns/tools/landrun\n\tdirectory = /work/ns/tools/nanoda\n' > /sandbox/etc/gitconfig
# The trusted supervisor needs chroot/unshare; each source argv drops to 10002.
# Host driver must supply private NS-only volumes, required namespace capability,
# no-new-privileges, proc-mount profile, CPU/memory/pids limits and no Docker socket.
USER 0:10001
CMD ["python3", "-m", "ns_queue.ns_worker", "--root", "/data"]
