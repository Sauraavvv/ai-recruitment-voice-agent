FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The agent's voice comes from an API (TTS_PROVIDER=deepgram, the default), so the local
# Kitten TTS model is left out of the image for now: lighter and quicker to build on a small
# server. To bring Kitten back: uncomment the two marked blocks below, rebuild, and set
# TTS_PROVIDER=kitten (no system packages needed: its English path uses no espeak).

COPY requirements.txt requirements-dev.txt requirements-nodeps.txt ./
ARG INSTALL_DEV=false
RUN pip install --require-hashes -r requirements.txt \
    && if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; fi

# [Kitten 1/2] The Kitten package itself (installed without its unused PyTorch dependencies)
# RUN pip install --no-deps --require-hashes -r requirements-nodeps.txt

# [Kitten 2/2] The model, baked into the image (pinned revision): a call never waits on a
# download. Only the download script is copied, so code changes don't invalidate this layer.
# COPY app/scripts/download_tts_model.py /tmp/download_tts_model.py
# RUN python /tmp/download_tts_model.py --dest /opt/models/kitten-tts-2-nano \
#     && rm -rf /tmp/download_tts_model.py /opt/models/kitten-tts-2-nano/.cache
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/artifacts && chown appuser:appuser /app/artifacts
COPY --chown=appuser:appuser . .
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
