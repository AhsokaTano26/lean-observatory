FROM python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd -g 10001 lean-ns && useradd --no-create-home -u 10001 -g 10001 lean-ns
WORKDIR /app
COPY ns_queue ./ns_queue
ARG SOURCE_SHA256=unbound
LABEL io.lean-observatory.ns.source-sha256=$SOURCE_SHA256
USER 10001:10001
EXPOSE 8792
CMD ["python3", "-m", "ns_queue.web", "--root", "/data", "--host", "0.0.0.0", "--port", "8792"]
