FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY generate_load.py .

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "generate_load.py"]
