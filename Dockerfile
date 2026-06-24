FROM python:3.11-slim

# matplotlib headless backend needs libgl; pillow needs libjpeg/libpng.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libjpeg62-turbo \
        zlib1g \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install image-to-laser-dxf from the public GitHub repo. Pin a commit/tag for
# reproducibility, or leave @main for the latest. Local development uses
# `pip install -e ../image-to-laser-dxf` instead.
ARG ITD_REF=main
RUN pip install --no-cache-dir \
        "image-to-laser-dxf @ git+https://github.com/yang362323/image-to-laser-dxf.git@${ITD_REF}"

# Copy the bot package and install it.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir -e ".[dev]"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HEALTH_PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8080/healthz || exit 1

CMD ["python", "-m", "app.main"]
