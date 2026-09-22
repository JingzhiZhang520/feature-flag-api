FROM python:3.12-slim AS runtime
WORKDIR /service
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home service
COPY --chown=service:service . .
USER service
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir -r requirements-dev.txt
USER service
CMD ["pytest", "-q"]

FROM runtime AS final
