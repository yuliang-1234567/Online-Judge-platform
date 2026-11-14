# 固定官方标签对应的 digest；更新基础镜像时必须重新核验来源并记录版本。
FROM docker.io/library/python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

# coreutils 提供 GNU timeout，time 提供独立的 /usr/bin/time。
# apt 包仍来自当次官方仓库：记录实际包版本，不承诺重复构建的镜像 ID 相同。
RUN apt-get update \
    && apt-get install -y --no-install-recommends coreutils time \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /work
# 只是镜像默认身份；M2.3 须显式覆盖为核验过的宿主专用 UID/GID。
USER 65532:65532
# 不绑定 ENTRYPOINT，后续 Runner 可以传入完整 argv；默认仅显示版本。
CMD ["/usr/local/bin/python3", "--version"]
