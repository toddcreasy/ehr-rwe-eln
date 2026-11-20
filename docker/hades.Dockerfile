# OHDSI HADES (R) in its own image: R 4.6.1, HADES's current target, and Java 21, which
# DatabaseConnector needs for JDBC. Java comes from the Temurin image; R and the dated CRAN
# snapshot from rocker. Pinned exactly; bump deliberately.
FROM eclipse-temurin:21.0.9_10-jdk-noble AS java

FROM rocker/r-ver:4.6.1
COPY --from=java /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/java/openjdk/bin:$PATH \
    DATABASECONNECTOR_JAR_FOLDER=/opt/jdbc \
    _JAVA_OPTIONS=-Xmx4g

# Build tools and libraries the packages compile against when no binary is available.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2-dev libssl-dev libcurl4-openssl-dev libfontconfig1-dev libharfbuzz-dev \
        libfribidi-dev libfreetype6-dev libpng-dev libtiff5-dev libjpeg-dev zlib1g-dev cmake \
    && rm -rf /var/lib/apt/lists/* \
    && R CMD javareconf

COPY r/install.R /tmp/install.R
RUN mkdir -p /opt/jdbc && Rscript /tmp/install.R \
    && Rscript -e 'ip <- installed.packages()[, c("Package", "Version")]; \
        write.table(ip[order(ip[, 1]), ], "/opt/installed-versions.txt", sep = "\t", \
        quote = FALSE, row.names = FALSE)'

RUN useradd --create-home hades
USER hades
WORKDIR /work/r
