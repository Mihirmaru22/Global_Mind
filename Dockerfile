# Runtime image for GlobleMind — FastAPI API + the bundled React UI in one
# process. Runs from source (WORKDIR /app) so PROJECT_ROOT resolves to the repo
# root and the committed frontend/ + config/ are found. An editable install
# links src/ in place and installs the dependencies from pyproject.toml.
FROM python:3.11-slim

# System libraries:
#  - libmagic1 is REQUIRED by python-magic (Stage 1 file detection); without it
#    the app fails to import.
#  - ghostscript / libgl1 / libglib2.0-0 back camelot + opencv (table-extraction
#    dependency) so the pip install never trips on a missing shared library.
# OCR (OCR.space) and the vector store (Qdrant Cloud) are network APIs — there
# are no local services to install.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmagic1 \
        ghostscript \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (better layer caching), editable so PROJECT_ROOT
# stays at /app and the frontend/config are served from source.
COPY pyproject.toml requirements.txt ./
COPY src ./src
# pyproject holds the full dependency list; requirements.txt is installed too as
# a backstop so nothing pinned only there is ever missed.
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir -r requirements.txt

# Bring in the rest: the built frontend, provider config, etc.
COPY . .

ENV PYTHONUNBUFFERED=1

# Render / Railway inject $PORT; default to 8000 for local runs. Binding 0.0.0.0
# and streaming straight from uvicorn keeps SSE (token streaming, ingestion
# progress, thinking trace) working — no buffering proxy in the way.
CMD ["sh", "-c", "python -m uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
