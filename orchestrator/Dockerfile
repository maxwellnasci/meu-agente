FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

# A imagem base traz ferramentas de build antigas (setuptools 79.0.1 com 3
# advisories - PYSEC-2026-3447, GHSA-xmj3-9gf7-h52w; pip 24.0). O produto nao
# usa setuptools em runtime (o build-backend e o hatchling), mas a imagem nao
# deve carregar versoes com vulnerabilidade conhecida (achado do pip-audit no CI).
RUN pip install --no-cache-dir -U pip "setuptools>=84.1.0" wheel

RUN pip install --no-cache-dir -e .

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]
