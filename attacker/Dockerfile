FROM kalilinux/kali-rolling

RUN apt update && \
    apt install -y python3 python3-pip && \
    pip install docker --break-system-packages

WORKDIR /attacker
CMD ["sleep", "infinity"]
