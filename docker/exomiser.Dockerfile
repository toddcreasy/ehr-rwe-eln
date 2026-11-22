# Exomiser for the clinical panel (module 6, step 6f): ranks each study subject's panel genes by how
# well their variants and HPO terms fit. Built by CodeBuild (infra/terraform/app/exomiser.tf,
# scripts/run_exomiser.py) and run as a Fargate task, never on a laptop: its data bundle is 33 GB.
# The CLI is the official release zip, checked against the SHA-256 GitHub lists for it. Pinned
# exactly; bump deliberately (a change here gives the image a new tag).
FROM eclipse-temurin:21.0.13_9-jre-noble@sha256:b4f9d2a0bc273417cf5219b7b832bbf0493ed500b7b57d5001d9f83374659060

ARG EXOMISER_VERSION=15.1.0
ARG EXOMISER_SHA256=47faa54d4791686c9dc3f896762834630e9eaf607ad3cf3399074353c3dda248

# python3-boto3 for S3 in exomiser_task.py; unzip for the CLI and the data bundle.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl unzip python3 python3-boto3 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSfL -o /tmp/exomiser.zip \
        "https://github.com/exomiser/Exomiser/releases/download/${EXOMISER_VERSION}/exomiser-cli-${EXOMISER_VERSION}-distribution.zip" \
    && echo "${EXOMISER_SHA256}  /tmp/exomiser.zip" | sha256sum -c - \
    && unzip -q /tmp/exomiser.zip -d /opt \
    && mv /opt/exomiser-cli-${EXOMISER_VERSION} /opt/exomiser \
    && mv /opt/exomiser/exomiser-cli-${EXOMISER_VERSION}.jar /opt/exomiser/exomiser-cli.jar \
    && rm -rf /tmp/exomiser.zip /opt/exomiser/examples

COPY exomiser_task.py /opt/exomiser/exomiser_task.py
RUN useradd --create-home exomiser
USER exomiser
WORKDIR /home/exomiser
ENTRYPOINT ["python3", "/opt/exomiser/exomiser_task.py"]
