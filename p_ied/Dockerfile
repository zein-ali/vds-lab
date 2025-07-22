FROM python:3.10-slim
WORKDIR /app
COPY p_ied.py .
RUN pip install flask requests
CMD ["python", "-u", "p_ied.py"]
