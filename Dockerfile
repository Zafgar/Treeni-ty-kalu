# Treeni-ty-kalu — yksi kontti tarjoilee sekä API:n että käyttöliittymän.
FROM python:3.11-slim

WORKDIR /app

# Riippuvuudet ensin (parempi välimuisti)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sovelluskoodi
COPY backend ./backend
COPY frontend ./frontend

# Tietokanta pysyvään levyyn (liitä volyymi /data:han pilvessä)
ENV TREENI_DB_PATH=/data/treeni.db
RUN mkdir -p /data

# Pilvialustat antavat portin PORT-ympäristömuuttujassa (oletus 8000)
EXPOSE 8000
CMD ["sh", "-c", "cd backend && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
