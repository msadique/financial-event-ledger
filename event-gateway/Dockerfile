FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY app ./app
COPY tests ./tests
RUN python -m pip install --upgrade pip \
    && python -m pip install ".[test]"
RUN useradd --create-home appuser && mkdir -p /data && chown -R appuser:appuser /data /app
USER appuser
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
