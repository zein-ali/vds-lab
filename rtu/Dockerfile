FROM python:3.12-slim

WORKDIR /app

COPY rtu.py .
RUN pip install flask requests
CMD ["python", "-u", "rtu.py"]
