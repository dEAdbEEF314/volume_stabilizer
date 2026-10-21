FROM python:3.12-slim

# Install system dependencies including ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files
COPY pyproject.toml README.md /app/
COPY volume_stabilizer /app/volume_stabilizer

# Install dependencies and package
RUN pip install --no-cache-dir .

# Create volume mount directories
RUN mkdir -p /music /output /data

EXPOSE 8080

ENV VS_INPUT_ROOT=/music \
    VS_OUTPUT_ROOT=/output \
    VS_DATA_DIR=/data \
    VS_TARGET_LUFS=-10.0 \
    VS_PEAK_CEILING=-1.0 \
    VS_MAX_REDUCTION=3.0

CMD ["uvicorn", "volume_stabilizer.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
