FROM python:3.11

WORKDIR /app

COPY requirements.txt requirements-customer.txt ./
RUN pip install -r requirements.txt -r requirements-customer.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
