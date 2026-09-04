FROM python:3.11-slim

# Don't write .pyc files, and stream logs straight out instead of buffering them
# (so `docker logs` shows output in real time).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy requirements first: Docker caches this layer, so changing application
# code doesn't force a full dependency reinstall on every build.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Run as an unprivileged user rather than root.
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Bind to 0.0.0.0, not localhost: inside a container, localhost is the container
# itself and would be unreachable from outside.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
