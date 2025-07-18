from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
import threading
import os
import uuid
import secrets
import requests

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory stores
REGISTERED_CLIENTS = {"smartcardadmin123", "smartcard_client"}
valid_tokens = {}
pending_requests = {}

# ---------------- UI Routes ----------------

@app.route("/", methods=["GET"])
@app.route("/token-page", methods=["GET"])
def token_page():
    return render_template("token.html")

@app.route("/generate-token", methods=["GET", "POST"])
def generate_token():
    if request.method == "POST":
        client_id = request.form.get("client_id", "").strip()
    else:
        client_id = request.args.get("client_id", "").strip()

    if not client_id or client_id not in REGISTERED_CLIENTS:
        if request.method == "POST":
            return render_template("token.html", error="Invalid or unregistered Client ID")
        return jsonify({"error": "Invalid or unregistered Client ID"}), 400

    token = secrets.token_hex(16)
    valid_tokens[token] = client_id
    print("✅ /generate-token route accessed")

    try:
        local_response = requests.post("http://localhost:5005/receive-token", json={
            "token": token,
            "client_id": client_id
        })
        print(f"[➡️ Sent to local] Response: {local_response.status_code}")
    except Exception as e:
        print(f"[⚠️ Error sending to local] {e}")

    if request.method == "POST":
        return render_template("token.html", token=token, client_id=client_id)
    else:
        return jsonify({
            "status": "success",
            "message": "Token generated and sent to client.",
            "token": token,
            "client_id": client_id
        }), 200

# ---------------- Token Verification API ----------------

@app.route("/verify-token", methods=["POST"])
def verify_token():
    data = request.get_json()
    token = data.get("token")
    client_id = data.get("client_id")

    print(f"[🔍 Cloud] Verifying token: {token} for client_id: {client_id}")

    if not token or not client_id:
        return jsonify({"status": "invalid", "reason": "Missing token or client_id"}), 400

    if valid_tokens.get(token) == client_id.strip():
        return jsonify({"status": "valid"}), 200

    return jsonify({"status": "invalid"}), 401

@app.route("/get-token", methods=["POST"])
def get_token():
    data = request.get_json()
    client_id = data.get("client_id", "").strip()

    if not client_id or client_id not in REGISTERED_CLIENTS:
        return jsonify({"error": "Invalid or unregistered client ID"}), 400

    token = str(uuid.uuid4())
    valid_tokens[token] = client_id
    print(f"[✅ Cloud] Token generated for {client_id}: {token}")
    return jsonify({"token": token})


# ---------------- Cloud Tunnel APIs ----------------

@app.route("/listschema/<table>", methods=["GET"])
def list_schema(table):
    return _request_through_tunnel("get_schema", {"table": table}, f"schema-{table}", "schema")

@app.route("/tables", methods=["GET"])
def list_tables():
    return _request_through_tunnel("get_tables", {}, "tables-request", "tables")

@app.route("/listcolumns/<table>", methods=["GET"])
def list_columns(table):
    return _request_through_tunnel("get_columns", {"table": table}, f"columns-{table}", "columns")

@app.route("/data/<table>/<column>", methods=["GET"])
def column_data(table, column):
    return _request_through_tunnel("get_column_data", {
        "table": table,
        "column": column
    }, f"data-{table}-{column}", "data")

def _request_through_tunnel(event_name, payload, request_id, key):
    event = threading.Event()
    pending_requests[request_id] = {"event": event}
    socketio.emit(event_name, {**payload, "request_id": request_id}, namespace="/tunnel")
    event.wait(timeout=5)

    data = pending_requests.pop(request_id, {}).get("data")
    if not data:
        return jsonify({"error": "Timeout or no response"}), 500
    return jsonify({key: data})


# ---------------- WebSocket Event Handlers ----------------

@socketio.on("connect", namespace="/tunnel")
def handle_connect():
    print("✅ Local connector connected via WebSocket /tunnel")

@socketio.on("disconnect", namespace="/tunnel")
def handle_disconnect():
    print("❌ Local connector disconnected from /tunnel")

@socketio.on("schema_response", namespace="/tunnel")
@socketio.on("tables_response", namespace="/tunnel")
@socketio.on("columns_response", namespace="/tunnel")
@socketio.on("column_data_response", namespace="/tunnel")
def handle_response(data):
    request_id = data.get("request_id")
    key = [k for k in ["schema", "tables", "columns", "data"] if k in data][0]
    if request_id in pending_requests:
        pending_requests[request_id]["data"] = data.get(key)
        pending_requests[request_id]["event"].set()

# ---------------- Server Startup ----------------

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 10000))
    socketio.run(app, host="0.0.0.0", port=PORT)
