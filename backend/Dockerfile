# Dockerfile for Django Backend
FROM python:3.11-slim

WORKDIR /app

COPY requirements/base.txt /app/
RUN pip install -r base.txt

COPY . /app/

CMD ["gunicorn", "config.wsgi", "-b", "0.0.0.0:8000"]
