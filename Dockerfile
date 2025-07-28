FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir flask pdfplumber

CMD ["python", "main.py"]