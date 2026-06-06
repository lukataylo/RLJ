# PulseGo routing service (/optimize). Railway service root = routing/.
FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# OR-Tools is optional at runtime (import-guarded); install it for the cloud CPU solver.
RUN pip install --no-cache-dir "ortools>=9.8" || echo "ortools unavailable; portfolio falls back"

ENV PORT=8100
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8100} --workers 1"]
