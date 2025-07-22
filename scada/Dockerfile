FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy source code
COPY . .

# Install dependencies
RUN pip install flask requests gunicorn

# Expose SCADA API port
EXPOSE 5001

# Start the SCADA service
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5001", "scada:app", "--threads", "8", "--log-level", "debug"]
