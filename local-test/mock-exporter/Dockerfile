FROM python:3.12-slim
RUN pip install --no-cache-dir prometheus-client==0.20.0
WORKDIR /app
COPY exporter.py .
EXPOSE 8000
CMD ["python", "exporter.py"]
