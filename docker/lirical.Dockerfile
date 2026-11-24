# LIRICAL for the clinical panel (module 6): ranks diseases by how well each study subject's HPO
# terms fit them, phenotype only (no VCF, so no ClinVar). Built by CodeBuild
# (infra/terraform/app/lirical.tf, scripts/run_lirical.py) and run as a Fargate task.
#
# LIRICAL's license is non-commercial use only and forbids modifying it: the release zip goes in
# unchanged, and the image stays in our private ECR.
#
# Its data is small, so it is part of the image, each file checked at build time: HPO at our
# release (2026-09-01, the one subject_hpo.tsv uses), HGNC's last monthly archive before it
# (2026-09-04 and 2026-10 give two genes one NCBI Gene ID, and LIRICAL stops on a duplicate),
# and the Jannovar transcript files LIRICAL requires even when it reads no VCF (Zenodo record
# 5410367, CC BY 4.0, MD5 from the record). NCBI keeps no archive of mim2gene_medgen, so it is
# whatever NCBI serves at build time; data/SHA256SUMS records every file, and image tags are
# immutable, so the image is the record of what ran.
FROM eclipse-temurin:21.0.13_9-jre-noble@sha256:b4f9d2a0bc273417cf5219b7b832bbf0493ed500b7b57d5001d9f83374659060

ARG LIRICAL_VERSION=2.4.2
ARG LIRICAL_SHA256=0e85d64dddaac4605bcabbc714e9d7ec46e847091813faa04a6ff0f27b609633
ARG HPO_RELEASE=2026-09-01
ARG HP_JSON_SHA256=a7b3a012e7b4007a35a7cf8da35f2373b54cc16907f80d13d62470d31f833501
ARG HPOA_SHA256=e89aa39c8f97bf5a52c5d160f9250a603681d630ade8ec2679d84ac5aece1f72
ARG HGNC_DATE=2026-08-04
ARG HGNC_SHA256=2106d1f237d6c542a85a4c399225e011ee9c5822199e7a400b7b9f842c8c8ca0

# python3-boto3 for S3 in lirical_task.py; unzip for the release zip.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl unzip python3 python3-boto3 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSfL -o /tmp/lirical.zip \
        "https://github.com/TheJacksonLaboratory/LIRICAL/releases/download/v${LIRICAL_VERSION}/lirical-cli-${LIRICAL_VERSION}-distribution.zip" \
    && echo "${LIRICAL_SHA256}  /tmp/lirical.zip" | sha256sum -c - \
    && unzip -q /tmp/lirical.zip -d /opt \
    && mv /opt/lirical-cli-${LIRICAL_VERSION} /opt/lirical \
    && mv /opt/lirical/lirical-cli-${LIRICAL_VERSION}.jar /opt/lirical/lirical-cli.jar \
    && rm -rf /tmp/lirical.zip /opt/lirical/examples

WORKDIR /opt/lirical/data
RUN set -e; \
    hpo="https://github.com/obophenotype/human-phenotype-ontology/releases/download/v${HPO_RELEASE}"; \
    curl -sSfL -o hp.json "${hpo}/hp.json"; \
    curl -sSfL -o phenotype.hpoa "${hpo}/phenotype.hpoa"; \
    curl -sSfL -o hgnc_complete_set.txt \
        "https://storage.googleapis.com/public-download-files/hgnc/archive/archive/monthly/tsv/hgnc_complete_set_${HGNC_DATE}.txt"; \
    printf '%s  %s\n' \
        "${HP_JSON_SHA256}" hp.json \
        "${HPOA_SHA256}" phenotype.hpoa \
        "${HGNC_SHA256}" hgnc_complete_set.txt | sha256sum -c -; \
    zenodo="https://zenodo.org/records/5410367/files"; \
    curl -sSfL -o hg19_ensembl.ser "${zenodo}/ensembl_87_hg19.ser"; \
    curl -sSfL -o hg19_refseq.ser "${zenodo}/refseq_105_hg19.ser"; \
    curl -sSfL -o hg19_refseq_curated.ser "${zenodo}/refseq_curated_105_hg19.ser"; \
    curl -sSfL -o hg38_ensembl.ser "${zenodo}/ensembl_91_hg38.ser"; \
    curl -sSfL -o hg38_refseq.ser "${zenodo}/refseq_109_hg38.ser"; \
    curl -sSfL -o hg38_refseq_curated.ser "${zenodo}/refseq_curated_109_hg38.ser"; \
    printf '%s  %s\n' \
        ecaffeaa26531a002e75953c6b309c53 hg19_ensembl.ser \
        b2087f8f3d41d20ad52fb9660853642e hg19_refseq.ser \
        a92fea7b8e37d46c75936783ae326d71 hg19_refseq_curated.ser \
        6218669555a52057ee88132edfed0ae2 hg38_ensembl.ser \
        6b1205bb534adb5ff9e0e569e6fabc5d hg38_refseq.ser \
        c2747c4c1b42a75930603d6deda105cf hg38_refseq_curated.ser | md5sum -c -; \
    curl -sSfL -o mim2gene_medgen "https://ftp.ncbi.nlm.nih.gov/gene/DATA/mim2gene_medgen"; \
    date -u +%Y-%m-%dT%H:%M:%SZ > BUILT_AT; \
    sha256sum hp.json phenotype.hpoa hgnc_complete_set.txt mim2gene_medgen *.ser > SHA256SUMS

COPY lirical_task.py /opt/lirical/lirical_task.py
RUN useradd --create-home lirical
USER lirical
WORKDIR /home/lirical
ENTRYPOINT ["python3", "/opt/lirical/lirical_task.py"]
