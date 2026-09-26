# The helper, hosted: one person's own instance, behind a passcode, taking the ao3 login
# only encrypted. Built by .github/workflows/deploy-hosted.yml - see HOSTING.md.
#
# The build context is this folder, and `hosted-settings.ini` has to be in it: the workflow
# writes it with deploy_config.py just before building. It holds no secrets - the passcode
# and the private key reach the container as environment variables, set on the host.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    AO3DOWNLOADER_CONFIG_FOLDER=/app/config \
    AO3DOWNLOADER_LOG_FOLDER=/app/data \
    AO3DOWNLOADER_HOST=0.0.0.0 \
    PORT=10000

WORKDIR /app

# the dependencies alone first, so a code change does not reinstall them
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.8.17 \
    && uv sync --frozen --no-dev --no-install-project

COPY source_code ./source_code
COPY hosted-settings.ini ./config/settings.ini

# nothing in here needs root. the config and log folders are written to at start
RUN useradd --create-home helper && mkdir -p /app/data && chown -R helper /app/config /app/data
USER helper

EXPOSE 10000
CMD ["/app/.venv/bin/python", "-m", "source_code.server"]
