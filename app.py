from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return "✅ SmartCard AI mock cloud is running"

@app.route("/verify-token", methods=["POST"])
def verify():
    data = request.get_json()
    token = data.get("token")
    client_id = data.get("client_id")

    if token == "secret123" and client_id == "dummy_client":
        return jsonify({"status": "valid"}), 200
    else:
        return jsonify({"status": "invalid"}), 401

if __name__ == "__main__":
    app.run()
