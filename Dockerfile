# Pinned to the interpreter patch level that produced Cloud Run revision
# genie-blog-run-00269-cf6. The floating `python:3.11` tag moves on every
# CPython patch release, and the build trigger uses --no-cache, so the tag alone
# cannot reproduce the running image. Digest of the base image as built:
# sha256:c7220863385ee39fb6d822da81f4469d0cd33ff893d92ce94105e5c3f4b95fe2
FROM python:3.11.15

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
