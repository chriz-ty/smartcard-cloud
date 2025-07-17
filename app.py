from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit
import threading
import os

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*") 

# Store schema response temporarily
pending_schemas = {}

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
    pending_schemas[request_id] = {"event": event}

    # Emit event to local client
    socketio.emit("get_schema", {"table": table, "request_id": request_id}, namespace="/tunnel")

    # Wait max 5 seconds
    event.wait(timeout=5)
    data = pending_schemas.get(request_id, {}).get("data")
    
    # Clean up
    pending_schemas.pop(request_id, None)

    if not data:
        return jsonify({"error": "Timeout or no response"}), 500

    return jsonify(data)

# SocketIO endpoint for local client
@socketio.on("connect", namespace="/tunnel")
def handle_connect():
    print("Local connector connected via WebSocket /tunnel")

@socketio.on("schema_response", namespace="/tunnel")
def handle_schema_response(data):
    request_id = data.get("request_id")
    if request_id in pending_schemas:
        pending_schemas[request_id]["data"] = data.get("schema")
        pending_schemas[request_id]["event"].set()


if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))
    socketio.run(app, host="0.0.0.0", port=PORT)
