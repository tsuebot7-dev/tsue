FROM python:3.12-slim

WORKDIR /app

# Playwright/Chromium uchun zarur tizim kutubxonalari
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# requirements.txt dagi playwright versiyasiga mos brauzer va barcha
# zarur OS kutubxonalarini o'rnatadi (--with-deps shart, aks holda
# Chromium ishga tushmaydi)
RUN playwright install --with-deps chromium

COPY . .

# Railway $PORT muhit o'zgaruvchisini avtomatik beradi
ENV PORT=8000
EXPOSE 8000

CMD ["python", "run.py"]
