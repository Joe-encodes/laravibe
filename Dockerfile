# ── 1. Frontend Build Stage ──
FROM node:20-bookworm-slim AS frontend-builder
WORKDIR /build
COPY laravibe-fe/package*.json ./
RUN npm install
COPY laravibe-fe/ .
# Inject the production API URL if needed, or leave blank to use relative paths
RUN npm run build

# ── 2. Final Production Stage ──
FROM python:3.12-slim-bookworm

# Install system dependencies (Docker CLI for sandbox)
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    lsb-release \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn

# Copy Python code
COPY . .

# Copy compiled Frontend from Stage 1
COPY --from=frontend-builder /build/dist ./static

# Final prep
RUN chmod +x start_prod.sh scripts/*.sh
RUN mkdir -p data logs

ENV PYTHONUNBUFFERED=1
ENV REPAIR_ENV=production

EXPOSE 8000

CMD ["bash", "start_prod.sh"]
