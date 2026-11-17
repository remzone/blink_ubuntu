#!/usr/bin/env python3
"""Run in a disposable container with NET_ADMIN, /dev/net/tun, fake resolved.
Verifies the actual privileged IPC process without sending remote VPN traffic.
"""
import json
import http.client
import socket
import threading
import os
import tempfile
import select
import signal
import subprocess
import time

if not os.path.exists("/.dockerenv"):
    raise SystemExit("Run only in a disposable Docker container")

binary = "/usr/bin/blink"
config = tempfile.TemporaryDirectory(prefix="session-smoke-", dir="/project/work")
os.environ["XDG_CONFIG_HOME"] = config.name
listener = socket.socket()
listener.bind(("127.0.0.1", 0))
listener.listen(8)
port = listener.getsockname()[1]
server_errors = []

def receive_exact(conn, n):
    result = b""
    while len(result) < n:
        part = conn.recv(n-len(result))
        if not part:
            raise RuntimeError("truncated VLESS handshake")
        result += part
    return result

def serve():
    try:
        for _ in range(4):
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(10)
                header = receive_exact(conn, 18)
                if header[0] != 0 or header[1:17] != bytes.fromhex("00000000000040008000000000000001"):
                    raise RuntimeError("unexpected VLESS identity")
                receive_exact(conn, header[17])
                request = receive_exact(conn, 4)
                if request[0] != 1 or request[3] != 1:
                    raise RuntimeError("expected VLESS TCP/IPv4")
                address = receive_exact(conn, 4)
                if address != socket.inet_aton("198.18.0.1"):
                    raise RuntimeError("wrong tunneled destination")
                payload = b""
                while b"\r\n\r\n" not in payload:
                    payload += conn.recv(4096)
                    if len(payload) > 16384:
                        raise RuntimeError("HTTP request too large")
                body = b"blink-loopback-ok"
                conn.sendall(b"\x00\x00HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
    except Exception as exc:
        server_errors.append(str(exc))

server = threading.Thread(target=serve, daemon=True)
server.start()
source = "vless://00000000-0000-4000-8000-000000000001@127.0.0.1:{}?security=none#Synthetic".format(port)
subprocess.run([binary, "import"], input=source, text=True, check=True)
profiles = json.loads(subprocess.check_output([binary, "list"], text=True))
profile = subprocess.check_output([binary, "export", profiles[0]["id"]], text=True)

def rules(family):
    return subprocess.check_output(["ip", family, "-j", "rule", "show"])

before = [rules("-4"), rules("-6")]
for stop in ("eof", "stdout", "sigterm", "command"):
    p = subprocess.Popen([binary, "session"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, bufsize=1)
    p.stdin.write(profile)
    p.stdin.flush()
    deadline = time.monotonic() + 30
    ready = False
    try:
        while time.monotonic() < deadline:
            if p.poll() is not None:
                raise RuntimeError("session exited: " + p.stderr.read())
            readable, _, _ = select.select([p.stdout], [], [], 1)
            if readable:
                event = json.loads(p.stdout.readline())
                if event.get("routed"):
                    ready = True
                    break
        if not ready:
            raise RuntimeError("session did not install routes")
        subprocess.run(["ip", "link", "show", "blink0"], check=True, stdout=subprocess.DEVNULL)
        connection = http.client.HTTPConnection("198.18.0.1", 8080, timeout=10)
        connection.request("GET", "/test")
        response = connection.getresponse()
        if response.status != 200 or response.read() != b"blink-loopback-ok":
            raise RuntimeError("TUN -> VLESS -> mock server data path failed")
        connection.close()
        print("TUN HTTP round trip:", stop, "OK")
        if stop == "stdout":
            p.stdout.close()  # exercise SIGPIPE rollback with stdin still open
        elif stop == "sigterm":
            p.send_signal(signal.SIGTERM)
        elif stop == "command":
            p.stdin.write('{"command":"stop"}\n')
            p.stdin.flush()
        else:
            p.stdin.close()
        p.wait(timeout=30)
        if p.returncode:
            raise RuntimeError("unclean exit: " + p.stderr.read())
        if [rules("-4"), rules("-6")] != before:
            raise RuntimeError("policy rules left behind")
        link = subprocess.run(["ip", "link", "show", "blink0"], capture_output=True)
        if link.returncode == 0:
            raise RuntimeError("TUN left behind")
        print("session cleanup:", stop, "OK")
    finally:
        if server_errors:
            print("Mock server:", "; ".join(server_errors))
        if p.poll() is None:
            p.stdin.close()
            p.terminate()
            p.wait(timeout=30)
        for stream in (p.stdin, p.stdout, p.stderr):
            if stream and not stream.closed:
                stream.close()

listener.close()
server.join(timeout=2)
if server_errors:
    raise RuntimeError("; ".join(server_errors))

config.cleanup()
