import socket
import sys

def find_free_port(start_port=8000, max_port=8010):
    for port in range(start_port, max_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    return None

if __name__ == "__main__":
    find_free_port()
