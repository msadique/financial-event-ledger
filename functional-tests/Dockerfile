FROM python:3.12-slim
WORKDIR /tests
COPY pyproject.toml .
COPY tests ./tests
RUN pip install --no-cache-dir .
CMD ["python", "-m", "pytest", "-v"]
