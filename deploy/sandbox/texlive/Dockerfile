# Rose Nexus — minimal TeX engine for the compile sandbox.
#
# Design rules (ADR-003):
#   - Everything the template needs is preinstalled: no network during a job.
#   - The image runs as an arbitrary non-root user (65534) with a read-only root.
#   - No shell-escape, no font packages beyond what the profiles declare.
#
# Build: ./scripts/build-teximage.sh
FROM docker.io/library/debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    SOURCE_DATE_EPOCH=0 \
    FORCE_SOURCE_DATE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        texlive-xetex \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
        lmodern \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt

WORKDIR /src
CMD ["xelatex", "--version"]
