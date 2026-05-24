FROM python:3.11-slim

WORKDIR /app

RUN addgroup --system tipmaster && adduser --system --ingroup tipmaster tipmaster

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R tipmaster:tipmaster /app

USER tipmaster

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
