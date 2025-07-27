# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Install system dependencies required by pdfplumber
RUN apt-get update && apt-get install -y \
    build-essential \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the current directory contents into the container
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir flask pdfplumber

# Expose the port the app runs on
# EXPOSE 5000

# Run the application
CMD ["python", "main.py"]