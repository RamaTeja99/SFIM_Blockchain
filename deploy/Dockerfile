FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    libssl-dev \
    libtss2-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY backend/ ./backend/
COPY *.py ./

# Create non-root user
RUN useradd -m -u 1000 sfim && chown -R sfim:sfim /app
USER sfim

# Expose port
EXPOSE 7000

# Default command
CMD ["python", "-m", "backend.cmd.node"]
