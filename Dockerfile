FROM python:3.11-slim

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    xvfb \
    x11vnc \
    fluxbox \
    novnc \
    websockify \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# TF-Hub cache (baked into image at build time)
ENV TFHUB_CACHE_DIR=/app/.tfhub

# Copy requirements and install Python dependencies
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ensure TF-Hub cache dir exists in the image
RUN mkdir -p /app/.tfhub

# Warm TF-Hub cache at build time so runtime doesn't need network.
# This will download the Kaggle-hosted TF-Hub model artifacts into TFHUB_CACHE_DIR.
RUN python - <<'PY'
import os
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')

import tensorflow as tf
# Needed for the Kaggle BERT preprocessor SavedModel (registers CaseFoldUTF8 op)
import tensorflow_text  # noqa: F401
import tensorflow_hub as hub

pre_url = "https://kaggle.com/models/tensorflow/bert/TensorFlow2/en-uncased-preprocess/3"
enc_url = "https://www.kaggle.com/models/google/universal-sentence-encoder/TensorFlow2/cmlm-en-base/1"

print("Warming TF-Hub cache...")
pre = hub.KerasLayer(pre_url)
enc = hub.KerasLayer(enc_url)

out = enc(pre(tf.constant(["tfhub warmup"])))["default"].numpy()
print("TF-Hub warmup OK, embedding shape:", out.shape)
PY

# Install Playwright browsers
RUN playwright install chromium

# Copy application code
COPY . .

# Entrypoint starts noVNC stack when PLAYWRIGHT_HEADLESS=0
RUN chmod +x /app/docker-entrypoint.sh

# Create directory for Playwright state
RUN mkdir -p /app/.playwright


EXPOSE 8000 5900 6080

CMD ["/app/docker-entrypoint.sh"]
