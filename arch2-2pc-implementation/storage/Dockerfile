# Use lightweight Python 3 image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY storage/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy proto files
COPY proto /app/proto

# Generate gRPC code
RUN python -m grpc_tools.protoc \
    -I/app/proto \
    --python_out=/app/proto \
    --grpc_python_out=/app/proto \
    /app/proto/twopc.proto 

COPY storage/app.py .

# Create storage directory in container
RUN mkdir -p /storage /storage/temp

# Expose Flask port
ENV PYTHONUNBUFFERED=1

# Run app
CMD ["python", "app.py"]
