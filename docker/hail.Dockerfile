# Hail in its own image: it pins pandas below 3 and PySpark 3.5, which the project's Python 3.14
# environment cannot hold, and Hail's install guide asks for Java 11, which current Debian no
# longer packages. Java comes from the Temurin image; Python 3.12 from the official one.
# Pinned exactly; bump deliberately.
FROM eclipse-temurin:11.0.32_9-jre-noble AS java

FROM python:3.12.15-slim-bookworm
COPY --from=java /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/java/openjdk/bin:$PATH \
    PYTHONUNBUFFERED=1
# Spark's launch scripts call ps.
RUN apt-get update && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir hail==0.2.139
RUN useradd --create-home hail
USER hail
WORKDIR /work
ENTRYPOINT ["python", "/work/scripts/hail_gwas.py"]
