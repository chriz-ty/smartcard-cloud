import eventlet
eventlet.monkey_patch()  # ✅ Must come before all other imports
from flask import Flask, redirect, request, jsonify, render_template
from flask_socketio import SocketIO, emit
from sqlalchemy import create_engine, text
import threading
import os
import uuid
import secrets
import requests
import json
import urllib.parse


app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
socketio = SocketIO(app, cors_allowed_origins="*")


# In-memory stores
REGISTERED_CLIENTS = {"smartcardadmin123", "smartcard_client"}
valid_tokens = {}
pending_requests = {}
mysql_schema_store = {}
synced_postgres = []
mysql_schema_store.clear()  # Clear old data on every startup



# ---------------- UI Routes ----------------

# Mock function to get databases and tables from IBM DB2
# In a real application, this would connect to your IBM DB2 instance
# and fetch the actual databases and tables
def get_databases():
    # This is a mock implementation
    # Replace this with actual database connection and query logic
    return [
        {
            "name": "SALESDB",
            "tables": ["CUSTOMERS", "ORDERS", "PRODUCTS", "SALES"]
        },
        {
            "name": "HRDB",
            "tables": ["EMPLOYEES", "DEPARTMENTS", "SALARIES", "ATTENDANCE"]
        },
        {
            "name": "INVENTORY",
            "tables": ["ITEMS", "SUPPLIERS", "STOCK_LEVELS", "PURCHASE_ORDERS"]
        }
    ]

@app.route("/", methods=["GET"])
@app.route("/token-page", methods=["GET"])
def index():
    databases = get_databases()
    selected_databases = []
    return render_template(
        'cloud_dashboard.html',
        databases=databases,
        selected_databases=selected_databases,
        mysql_data=mysql_schema_store,
        postgres_dbs=synced_postgres,
        token=request.args.get('token')
    )


def token_page():
    return render_template("token.html")

@app.route("/generate-token", methods=["GET", "POST"])
def generate_token():
    if request.method == "POST":
        client_id = request.form.get("client_id", "").strip()
    else:
        client_id = request.args.get("client_id", "").strip()

    if not client_id or client_id not in REGISTERED_CLIENTS:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"error": "Invalid or unregistered Client ID"}), 400
        return render_template("cloud_dashboard.html", error="Invalid or unregistered Client ID")

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

    # AJAX request: return JSON
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            "status": "success",
            "message": "Token generated and sent to client.",
            "token": token,
            "client_id": client_id
        }), 200
    # Normal POST: render dashboard with token
    databases = get_databases()
    selected_databases = []
    return render_template('cloud_dashboard.html', 
                         databases=databases,
                         selected_databases=selected_databases,
                         token=token,
                         client_id=client_id,
                         mysql_schema_store=mysql_schema_store)

@app.route("/preview-mysql", methods=["GET"])
def preview_mysql():
    db_key = request.args.get("db_key")
    if db_key not in mysql_schema_store:
        return "Invalid database selected", 404

    db_data = mysql_schema_store[db_key]  # this is a dict of tables → list of column dicts
    return render_template("preview_mysql.html", db_key=db_key, db_data=db_data)

@app.route("/receive-postgres", methods=["POST"])
def receive_postgres():
    data = request.get_json()
    print("📥 Received PostgreSQL Data:", data)
    
    synced_postgres.clear()
    for db_name, tables in data.items():
        synced_postgres.append({
            "name": db_name,
            "tables": tables
        })
    
    return jsonify({"source": "postgresql", "status": "received"})


@app.route("/sync-postgres", methods=["GET"])
def sync_postgres():
    request_id = f"postgres-sync-{uuid.uuid4()}"
    event = threading.Event()
    pending_requests[request_id] = {"event": event}

    # emit to local client to get all tables (flat list)
    socketio.emit("get_tables", {"request_id": request_id}, namespace="/tunnel")
    event.wait(timeout=5)

    tables = pending_requests.pop(request_id, {}).get("data", [])
    synced_postgres.clear()

    if isinstance(tables, list):
        synced_postgres.append({
            "name": "test_postgres_db",  # or dynamic if you can extract from local
            "tables": tables
        })

    return redirect("/")

@app.route("/preview-postgres")
def preview_postgres():
    db_name = request.args.get("db")
    table_name = request.args.get("table")

    # Request schema from local connector
    schema_request_id = f"schema-{uuid.uuid4()}"
    schema_event = threading.Event()
    pending_requests[schema_request_id] = {"event": schema_event}

    socketio.emit("get_schema", {
        "request_id": schema_request_id,
        "table": table_name
    }, namespace="/tunnel")

    schema_event.wait(timeout=5)
    schema_data = pending_requests.pop(schema_request_id, {}).get("data", [])

    # Format for template
    formatted_schema = [{"name": col.get("name", ""), "type": col.get("type", "")} for col in schema_data]

    return render_template("preview_postgres.html", databases=[{
        "name": db_name,
        "tables": {
            table_name: formatted_schema
        }
    }])



@app.route("/disconnect-postgres", methods=["POST"])
def disconnect_postgres():
    try:
        if os.path.exists("synced_postgres.json"):
            os.remove("synced_postgres.json")
        return jsonify({"status": "disconnected"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



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

@app.route("/receive-tally", methods=["POST"])
def receive_tally():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid Tally data"}), 400

    with open("tally_data.json", "w") as f:
        json.dump(data, f)

    return jsonify({"message": "Tally data received"}), 200


@app.route("/tally-preview")
def tally_preview():
    try:
        with open("tally_data.json", "r") as f:
            companies = json.load(f)
    except Exception as e:
        print(f"Error reading tally_data.json: {e}")
        companies = {}

    return render_template("tally_preview.html", companies=companies)

@app.route('/receive-mysql', methods=['POST'])
def receive_mysql():
    data = request.get_json()
    mysql_schema_store.clear()
    mysql_schema_store.update(data)
    print("✅ Received MySQL schema from local:", data.keys())
    return jsonify({"status": "MySQL schema received"}), 200

@app.route("/disconnect-mysql", methods=["POST"])
def disconnect_mysql():
    mysql_schema_store.clear()
    return jsonify({"status": "disconnected"}), 200


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
