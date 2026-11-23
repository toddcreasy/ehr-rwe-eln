# BIAS-2015 v3.0.0 on Ensembl VEP 115, for scripts/run_bias.py. Built on x86 by CodeBuild
# (infra/terraform/app/bias.tf), run as an on-demand Fargate task; never built or run locally.
#
# Base: Ensembl's own VEP image, pinned by digest. It runs as user vep, with every VEP plugin
# (REVEL and AlphaMissense among them) in /plugins.
FROM ensemblorg/ensembl-vep:release_115.0@sha256:b156136b0c80cbc244512156d65047f49f1bab416cd3ba3b23812774909ca3b9

USER root
# tabix from Ubuntu is built with libcurl, so it reads gnomAD's indexed files over HTTPS; the
# image's own htslib is not. boto3 for S3.
# noninteractive: tzdata, pulled in by python3, otherwise stops the build to ask for a time zone.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3 python3-boto3 tabix ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
RUN test -f /plugins/REVEL.pm && test -f /plugins/AlphaMissense.pm

# BIAS-2015 at tag v3.0.0, the release its 2026.03.01 data tables were built for. AGPL for
# non-commercial academic use (LICENSE in the source).
ARG BIAS_COMMIT=0a8db2d6280ee0266de31639b5190476d2032370
ARG BIAS_SHA256=56c97e2436c6df09517c0fb7ed1f61b1c2a3e6f3ec95bb904f0700f41485a018
RUN curl -fsSL -o /tmp/bias.tar.gz "https://github.com/bitscopic/BIAS-2015/archive/${BIAS_COMMIT}.tar.gz" \
    && echo "${BIAS_SHA256}  /tmp/bias.tar.gz" | sha256sum -c - \
    && mkdir /opt/bias \
    && tar -xzf /tmp/bias.tar.gz -C /opt/bias --strip-components=1 \
    && rm -rf /tmp/bias.tar.gz /opt/bias/test /opt/bias/doc

COPY bias_task.py /opt/bias/bias_task.py
# Everything the task downloads and writes goes here, on the task's own disk.
RUN mkdir /work && chown vep /work

USER vep
WORKDIR /work
ENTRYPOINT ["python3", "/opt/bias/bias_task.py"]
