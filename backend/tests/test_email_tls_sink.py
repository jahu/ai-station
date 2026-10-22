"""Actual TLS/SMTP to a private local sink; no external recipients or credentials."""

import shutil
import socket
import socketserver
import ssl
import subprocess
import threading
from uuid import uuid4

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from fastapi.testclient import TestClient


@pytest.mark.skipif(
    shutil.which("openssl") is None, reason="Local TLS sink needs the normal OpenSSL test utility"
)
def test_reviewed_email_reaches_actual_local_tls_smtp_sink(tmp_path, monkeypatch):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=smtp.example.com",
            "-addext",
            "subjectAltName=DNS:smtp.example.com",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    received = []
    commands = []

    class Handler(socketserver.StreamRequestHandler):
        def reply(self, value):
            self.wfile.write(value + b"\r\n")
            self.wfile.flush()

        def handle(self):
            self.reply(b"220 private AI Station fixture")
            while True:
                line = self.rfile.readline(100_000)
                if not line:
                    return
                command = line.split(b" ", 1)[0].strip().upper()
                commands.append(command)
                if command in {b"EHLO", b"HELO"}:
                    self.reply(b"250-smtp.example.com\r\n250 AUTH PLAIN")
                elif command == b"AUTH":
                    self.reply(b"235 authenticated fixture")
                elif command in {b"MAIL", b"RCPT", b"NOOP", b"RSET"}:
                    self.reply(b"250 OK")
                elif command == b"DATA":
                    self.reply(b"354 end with dot")
                    body = bytearray()
                    while True:
                        piece = self.rfile.readline(100_000)
                        if piece in {b".\r\n", b""}:
                            break
                        body.extend(piece[1:] if piece.startswith(b"..") else piece)
                    received.append(bytes(body))
                    self.reply(b"250 accepted by private test sink")
                elif command == b"QUIT":
                    self.reply(b"221 bye")
                    return
                else:
                    self.reply(b"500 unsupported fixture command")

    class Sink(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

        def get_request(self):
            connection, address = super().get_request()
            return server_context.wrap_socket(connection, server_side=True), address

    sink = Sink(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=sink.serve_forever, daemon=True)
    thread.start()
    original_connection = socket.create_connection
    original_context = ssl.create_default_context

    def local_connection(address, *args, **kwargs):
        assert address == ("smtp.example.com", 465)
        return original_connection(("127.0.0.1", sink.server_address[1]), *args, **kwargs)

    monkeypatch.setattr("app.email_delivery.smtplib.socket.create_connection", local_connection)
    monkeypatch.setattr(
        "app.email_delivery.ssl.create_default_context", lambda: original_context(cafile=str(cert))
    )
    try:
        with TestClient(app) as api:
            connector = api.post(
                "/api/connectors",
                json={
                    "key": "tls-sink",
                    "name": "Local sink fixture",
                    "kind": "email",
                    "secret": "synthetic-password",
                    "smtp": {
                        "host": "smtp.example.com",
                        "username": "fixture",
                        "sender": "station@example.com",
                        "allowed_recipients": ["recipient@example.com"],
                    },
                },
            )
            assert connector.status_code == 201, connector.text
            row = connector.json()
            preview = api.post(
                "/api/email/connectors/" + row["id"] + "/drafts",
                json={
                    "client_request_id": str(uuid4()),
                    "expected_updated_at": row["updated_at"],
                    "recipients": ["recipient@example.com"],
                    "subject": "Local TLS acceptance",
                    "body": "This synthetic message must reach only the private local test sink.",
                },
            )
            assert preview.status_code == 201, preview.text
            assert not received
            run_id = preview.json()["run"]["id"]
            assert (
                api.post("/api/runs/" + run_id + "/approval", json={"resolution": "granted"}).status_code
                == 200
            )
            with session_factory()() as session:
                tick(session, "local-smtp-sink-worker")
            receipt = api.get("/api/email/deliveries").json()[0]
            assert receipt["state"] == "accepted", receipt
            assert len(received) == 1 and b"Local TLS acceptance" in received[0]
            assert b"recipient@example.com" in received[0] and b"synthetic-password" not in received[0]
            assert b"AUTH" in commands and b"DATA" in commands
            assert receipt["message_id"].encode() in received[0]
    finally:
        sink.shutdown()
        sink.server_close()
        thread.join(timeout=5)
