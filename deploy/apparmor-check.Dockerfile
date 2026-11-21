FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends apparmor && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["apparmor_parser", "--skip-kernel-load", "--skip-cache", "/profile"]
