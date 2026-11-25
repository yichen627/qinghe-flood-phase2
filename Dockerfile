FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN mkdir -p /var/qinghe && useradd --uid 10001 --create-home appuser && chown -R appuser /var/qinghe /app
USER appuser
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
