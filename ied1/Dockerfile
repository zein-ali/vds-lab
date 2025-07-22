FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy source code
COPY . .

# Install dependencies
RUN pip install flask requests gunicorn

# Expose IED API port
EXPOSE 5003

# Start the IED service
CMD ["python", "-u", "ied1.py"]
