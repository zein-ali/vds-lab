FROM python:3.10-slim

RUN apt-get update && apt-get install -y tcpdump iproute2 net-tools tshark && \
    pip install scapy flask requests

WORKDIR /app
COPY ids.py .

ENTRYPOINT ["python", "-u", "ids.py"]
