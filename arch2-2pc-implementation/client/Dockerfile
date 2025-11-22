FROM python:3.11-slim

WORKDIR /app

COPY client/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY client/cli.py .

ENV PYTHONUNBUFFERED=1

CMD ["python", "cli.py"]