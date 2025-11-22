FROM python:3.11-slim
WORKDIR /app
COPY app.py .
VOLUME ["/metadata", "/storage", "/backup"]
CMD ["python", "app.py"]
