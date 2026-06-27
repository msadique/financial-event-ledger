FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY app ./app
COPY tests ./tests
RUN pip install --no-cache-dir ".[test]"
RUN useradd --create-home appuser && mkdir -p /data /reports && chown -R appuser:appuser /data /reports /app
USER appuser
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
