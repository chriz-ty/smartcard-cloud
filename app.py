from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit
import threading
import os

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Shared store for all pending requests
pending_requests = {}

@app.route("/")
def home():
    return "SmartCard AI mock cloud is running"

@app.route("/verify-token", methods=["POST"])
def verify():
    data = request.get_json()
    token = data.get("token")
    client_id = data.get("client_id")

    if token == "secret123" and client_id == "dummy_client":
        return jsonify({"status": "valid"}), 200
    else:
        return jsonify({"status": "invalid"}), 401


@app.route("/listschema/<table>", methods=["GET"])
def list_schema(table):
    token = request.headers.get("Authorization")
    
    request_id = f"schema-{table}"
    event = threading.Event()
    pending_requests[request_id] = {"event": event}

    socketio.emit("get_schema", {"table": table, "request_id": request_id}, namespace="/tunnel")

    event.wait(timeout=5)
    data = pending_requests.get(request_id, {}).get("data")

    pending_requests.pop(request_id, None)

    if not data:
        return jsonify({"error": "Timeout or no response"}), 500

    return jsonify(data)


@app.route("/tables", methods=["GET"])
def list_tables():
    request_id = "tables-request"
    event = threading.Event()
    pending_requests[request_id] = {"event": event}

    socketio.emit("get_tables", {"request_id": request_id}, namespace="/tunnel")

    event.wait(timeout=5)
    data = pending_requests.get(request_id, {}).get("data")

    pending_requests.pop(request_id, None)

    if not data:
        return jsonify({"error": "Timeout or no response"}), 500

    return jsonify({"tables": data})


# ================= SocketIO =================

@socketio.on("connect", namespace="/tunnel")
def handle_connect():
    print("✅ Local connector connected via WebSocket /tunnel")

@socketio.on("disconnect", namespace="/tunnel")
def handle_disconnect():
    print("❌ Local connector disconnected from /tunnel")

@socketio.on("schema_response", namespace="/tunnel")
def handle_schema_response(data):
    request_id = data.get("request_id")
    if request_id in pending_requests:
        pending_requests[request_id]["data"] = data.get("schema")
        pending_requests[request_id]["event"].set()

@socketio.on("tables_response", namespace="/tunnel")
def handle_tables_response(data):
    request_id = data.get("request_id")
    if request_id in pending_requests:
        pending_requests[request_id]["data"] = data.get("tables")
        pending_requests[request_id]["event"].set()


if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))
    socketio.run(app, host="0.0.0.0", port=PORT)
