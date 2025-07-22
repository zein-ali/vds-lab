FROM python:3.11-slim
WORKDIR /app
COPY merging_unit.py .
RUN pip install requests

# Start the IED service
CMD ["python", "-u", "merging_unit.py"]
