FROM python:3.11-slim
WORKDIR /app
COPY services/upload/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proto /app/proto

RUN python -m grpc_tools.protoc \
    -I/app/proto \
    --python_out=/app/proto \
    --grpc_python_out=/app/proto \
    /app/proto/twopc.proto 

COPY services/upload/app.py .

ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"]