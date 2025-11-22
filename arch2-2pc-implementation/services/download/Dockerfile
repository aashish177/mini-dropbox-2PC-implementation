FROM python:3.11-slim
WORKDIR /app
COPY services/download/requirements.txt .
RUN pip install -r requirements.txt
COPY services/download/app.py .
CMD ["python", "app.py"]