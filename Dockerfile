FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /var/qinghe && useradd --uid 10001 --create-home appuser && chown -R appuser /var/qinghe /app
USER appuser
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
