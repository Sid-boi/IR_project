# ─────────────────────────────────────────────────────────────────────────────
# FIR Lab — Python workbench
# Python 3.10-slim + course libs + project libs
# Last updated: Oct 2026
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.10-slim

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ── Upgrade pip first ─────────────────────────────────────────────────────────
RUN pip install --no-cache-dir --upgrade pip

# ── Course-required libs (from FIR installation PDF) ─────────────────────────
# Pinned to ES 7.x client to match elasticsearch:7.17.28 in compose
RUN pip install --no-cache-dir \
    "numpy<2" \
    scikit-learn \
    scikit-image \
    notebook \
    "elasticsearch>=7,<8" \
    "elasticsearch-dsl>=7,<8"

# ── Evaluation + stats ────────────────────────────────────────────────────────
RUN pip install --no-cache-dir \
    scipy \
    pandas \
    ranx \
    pytrec-eval-terrier

# ── Visualisation ─────────────────────────────────────────────────────────────
RUN pip install --no-cache-dir \
    matplotlib \
    ipywidgets

# ── Experiment utilities ──────────────────────────────────────────────────────
RUN pip install --no-cache-dir \
    tqdm

# ── Learning to Rank ─────────────────────────────────────────────────────────
# LambdaMART via LightGBM — Notebook 04b
RUN pip install --no-cache-dir \
    lightgbm

# ── Optional: biomedical sentence splitting ───────────────────────────────────
# Uncomment if you want scispaCy for passage chunking
# Heavy install (~500MB) — only needed if not using naive splitter
# RUN pip install --no-cache-dir scispacy && \
#     python -m spacy download en_core_sci_sm

# ── Work directories ──────────────────────────────────────────────────────────
RUN mkdir -p \
    /work/data \
    /work/runs \
    /work/notebooks \
    /work/scripts

WORKDIR /work
