# PLINK 2 and REGENIE for the GWAS, x86_64 only: REGENIE ships no ARM build. Built by CodeBuild on
# x86 (infra/terraform/app/gwas.tf, scripts/run_regenie.py) and run as a Fargate task, never on a
# laptop. Official release binaries, each checked against the SHA-256 GitHub lists for it.
# Pinned exactly; bump deliberately (a change here gives the image a new tag).
FROM debian:trixie-20261104-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2

ARG PLINK2_VERSION=v2.0.0-b.1.4
ARG PLINK2_SHA256=16b5cf92faed7e8b8aa1010c6eab9bac17c92b57ccfa69c4d059b1b17b98eb70
ARG REGENIE_VERSION=v4.1.3
ARG REGENIE_SHA256=6e271dbcbeee2326fbba67de6297a137b56e6b2661b1aa510a62c40dba286b10

# python3-boto3 for S3 in gwas_task.py; libgomp1 and zlib1g for REGENIE.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl unzip python3 python3-boto3 libgomp1 zlib1g \
    && rm -rf /var/lib/apt/lists/*

# The generic x86_64 PLINK 2, not the AVX2 build: Fargate does not promise a CPU generation.
RUN curl -sSfL -o /tmp/plink2.zip \
        "https://github.com/chrchang/plink-ng/releases/download/${PLINK2_VERSION}/plink2_linux_x86_64.zip" \
    && echo "${PLINK2_SHA256}  /tmp/plink2.zip" | sha256sum -c - \
    && unzip -j /tmp/plink2.zip plink2 -d /usr/local/bin \
    && curl -sSfL -o /tmp/regenie.zip \
        "https://github.com/rgcgithub/regenie/releases/download/${REGENIE_VERSION}/regenie_${REGENIE_VERSION}.gz_x86_64_Linux.zip" \
    && echo "${REGENIE_SHA256}  /tmp/regenie.zip" | sha256sum -c - \
    && unzip -j /tmp/regenie.zip -d /tmp/regenie \
    && mv /tmp/regenie/regenie_* /usr/local/bin/regenie \
    && chmod +x /usr/local/bin/plink2 /usr/local/bin/regenie \
    && rm -rf /tmp/plink2.zip /tmp/regenie.zip /tmp/regenie \
    && plink2 --version && regenie --version

COPY gwas_task.py /opt/gwas/gwas_task.py
RUN useradd --create-home gwas
USER gwas
WORKDIR /home/gwas
ENTRYPOINT ["python3", "/opt/gwas/gwas_task.py"]
