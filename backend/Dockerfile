FROM python:3.12-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# requirements.txt is the compiled lock (see its header), not the declaration -
# that is requirements.in, which this image has no use for. `--require-hashes`
# is the point of having compiled it with `--generate-hashes`: without it the
# hashes are decoration, and an unpinned transitive could still float in. pip is
# upgraded first because --require-hashes wants a pip that understands it.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --require-hashes -r requirements.txt

COPY app/ ./app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
