# PulseGo orchestrator (API + WebSocket). Railway service root = orchestrator/.
FROM python:3.11-slim
WORKDIR /app

# system deps for psycopg / bcrypt wheels are bundled, but keep build tools minimal
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway injects $PORT. Bind 0.0.0.0 so the platform can route to us.
ENV PORT=8000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
