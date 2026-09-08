# AGNIES — read-only viewer deploy (no LLM pipeline runs on this box).
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
WORKDIR /app/agnies_agent

CMD ["waitress-serve", "--host=0.0.0.0", "--port=8060", "backend.wsgi:application"]
