FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY py/app.py ./
COPY index.html ./
COPY styles ./styles
COPY scripts ./scripts
COPY media ./media
COPY db ./db
RUN mkdir -p cache data

EXPOSE 5000

# Long timeout: the one-off bulk Earth Engine analysis takes several minutes
CMD ["gunicorn", "-b", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "900", "app:app"]
