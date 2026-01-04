import socket

def check_connection(host, port):
    try:
        s = socket.create_connection((host, port), timeout=2)
        s.close()
        return True
    except Exception as e:
        print(f"Error connecting to {host}:{port}: {e}")
        return False

if __name__ == "__main__":
    host = "host.docker.internal"
    port = 47658
    if check_connection(host, port):
        print(f"Connection to {host}:{port} successful!")
    else:
        print(f"Connection to {host}:{port} failed.")
