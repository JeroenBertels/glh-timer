# Use a slim Python image
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Cloud Run sets PORT automatically (usually 8080)
ENV PORT=8080

# Create working directory
WORKDIR /app

# Install system deps (optional but good hygiene for some libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY app /app/app
COPY make_qr.py /app/make_qr.py
COPY make_qr_pdf.py /app/make_qr_pdf.py

# Expose the port (not strictly required, but nice)
EXPOSE 8080

# Start FastAPI via uvicorn; IMPORTANT: bind to 0.0.0.0 and use $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
