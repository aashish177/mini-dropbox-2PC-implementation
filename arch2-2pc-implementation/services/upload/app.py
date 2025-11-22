import os
import jwt
import datetime
import uuid, grpc, sys
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, request, jsonify, Response
import requests

sys.path.insert(0, '/app/proto')
import twopc_pb2
import twopc_pb2_grpc

app = Flask(__name__)

METADATA_API = "http://metadata1:5005" # metadata service URL
STORAGE_API = "http://storage1:5006" # storage service URL
SECRET_KEY = os.environ.get("SECRET_KEY", "supersecretkey") # secret key for JWT - in more secure setup, use env variable

class TwoPhaseCommitCoordinator:
    def __init__(self):
        self.node_id = "1"
        print(f"[Cordinator Node {self.node_id}] Initializing 2PC Coordinator...")

        self.participants = {
            "2": ("storage1", 50052),
            "3": ("storage2", 50053),
            "4": ("metadata1", 50054),
            "5": ("metadata2", 50055)
        }

        self.channels = {}
        self.stubs = {}

        for node_id, (host, port) in self.participants.items():
            try:
                channel = grpc.insecure_channel(f"{host}:{port}")
                self.channels[node_id] = channel
                self.stubs[node_id] = twopc_pb2_grpc.TwoPhaseCommitStub(channel)
                print(f"[Coordinator] Connected to Node {node_id} at {host}:{port}")
            except Exception as e:
                print(f"[Coordinator] Failed to connect to Node {node_id}: {e}")

    def voting_phase(self, txn_id, filename, file_data, user):
        print("*" * 60)
        print(f"[Coordinator] Starting VOTING PHASE for transaction {txn_id}")
        print(f"[Coordinator] Operation: upload, File: {filename}, Size: {len(file_data)} bytes")

        votes = {}

        metadata = twopc_pb2.FileMetadata(
            filename=filename,
            size=len(file_data),
            user=user
        )

        for participant_id, stub in self.stubs.items():
            try:
                print(f"Phase Voting of Node {self.node_id} sends RPC VoteRequest to Phase Voting of Node {participant_id}")

                request = twopc_pb2.VoteRequestMsg(
                    transaction_id=txn_id,
                    operation="upload",
                    filename=filename,
                    file_data=file_data,
                    metadata=metadata
                )

                response = stub.VoteRequest(request, timeout=10)
                votes[participant_id] = response.vote

                vote_str = "VOTE_COMMIT" if response.vote == twopc_pb2.VOTE_COMMIT else "VOTE_ABORT"
                print(f" Node {participant_id} voted: {vote_str}")

                if response.vote == twopc_pb2.VOTE_ABORT:
                    print(f"Reason: {response.reason}")

            except grpc.RpcError as e:
                print(f" Failed to get cote from Node {participant_id}: {e}")
                votes[participant_id] = twopc_pb2.VOTE_ABORT

        print(f"\n [Coordinator] Votes collected: {votes}")
        return votes
    
    def decision_phase(self, txn_id, votes):
        all_commit = all(v == twopc_pb2.VOTE_COMMIT for v in votes.values())
        decision = twopc_pb2.GLOBAL_COMMIT if all_commit else twopc_pb2.GLOBAL_ABORT

        decision_str = "GLOBAL_COMMIT" if all_commit else "GLOBAL_ABORT"
        print("*"*60)
        print(f"[Coordinator] Starting DECISION PHASE for transaction {txn_id}")
        print(f"[Coordinator] Decision: {decision_str}")

        for participant_id, stub in self.stubs.items():
            try:
                print(f"Phase Decision of Node {self.node_id} sends RPC GlobalDecision to Phase Decision of Node {participant_id}")

                response = stub.GlobalDecision(
                    twopc_pb2.DecisionMsg(
                        transaction_id=txn_id,
                        decision=decision
                    ),
                    timeout=10
                )

                if response.success:
                    print(f"Node {participant_id} acknowledged {decision_str}")
                else:
                    print(f"Node {participant_id} failed to process {decision_str}")
            
            except grpc.RpcError as e:
                print(f"Failed to send decision to Node {participant_id}: {e}")

        print("*" * 60)
        return all_commit
    
    def execute_upload(self, filename, file_data, user):
        txn_id = str(uuid.uuid4())[:8]
        print(f"[Coordinator] New upload request: {filename} (Transaction ID: {txn_id})")

        votes = self.voting_phase(txn_id, filename, file_data, user)

        success = self.decision_phase(txn_id, votes)

        return success
    
coordinator = TwoPhaseCommitCoordinator()


# --- JWT Helpers ---
def encode_token(username):
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "exp": now + datetime.timedelta(days=1),
        "iat": now,
        "sub": username
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def decode_token(token):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload["sub"]
    except Exception:
        return None


# # --- Routes ---
@app.route("/auth/signup", methods=["POST"])
def signup():
    # grab the username and password
    data = request.json
    username = data.get("username")
    password = data.get("password")

    # validate input
    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    # hash password before sending to metadata service
    hashed_password = generate_password_hash(password)
    try:
        # send to metadata service
        resp = requests.post(f"{METADATA_API}/users", json={
            "username": username,
            "password": hashed_password
        })

        # check response from metadata service
        if resp.status_code == 201:
            return jsonify({"message": "Signup successful!"}), 201
        elif resp.status_code == 409:
            return jsonify({"error": "Username already exists"}), 409
        else:
            return jsonify({"error": "Metadata service error"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/auth/login", methods=["POST"])
def login():
    # grab the username and password
    data = request.json
    username = data.get("username")
    password = data.get("password")

    # validate input
    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    try:
        # fetch user from metadata service
        resp = requests.get(f"{METADATA_API}/users/{username}")

        # check the response
        if resp.status_code != 200:
            return jsonify({"error": "Invalid credentials"}), 401

        # if user is found, check password
        user = resp.json()
        stored_hash = user.get("password")
        if stored_hash and check_password_hash(stored_hash, password):
            token = encode_token(username)

            # store the token in the user's session
            return jsonify({"token": token})
        else:
            return jsonify({"error": "Invalid credentials"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# auth decorator
def require_auth(f):
    def wrapper(*args, **kwargs):
        # grab the header
        auth_header = request.headers.get("Authorization")

        # check if auth header is present and valid
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid token"}), 401
        
        # decode the token
        token = auth_header.split(" ", 1)[1]
        username = decode_token(token)
        if not username:
            return jsonify({"error": "Invalid or expired token"}), 401
        request.username = username
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# upload file endpoint
@app.route("/files/upload", methods=["POST"])
@require_auth
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    # # get the file
    # file = request.files["file"]
    # files = {'file': (file.filename, file.stream, file.mimetype)}

    # # forward the file to the storage service via POST
    # resp = requests.post(f"{STORAGE_API}/upload", files=files)

    # # check response from storage service
    # if resp.status_code != 200:
    #     return jsonify({"error": "Storage error"}), 500

    # try:
    #     return resp.json(), resp.status_code
    # except Exception:
    #     return jsonify({"error": "Non-JSON response from storage", "raw": resp.text}), resp.status_code

    file = request.files["file"]
    filename = file.filename
    file_data = file.read()
    username = request.username

    success = coordinator.execute_upload(filename, file_data, username)

    if success:
        return jsonify({
            "message": "File uploaded successfully via 2PC",
            "filename": filename,
            "size": len(file_data)}
        ), 200
    else:
        return jsonify({
            "error": "Upload failed - transaction aborted",
            "filename": filename
        }), 500

# list files endpoint
@app.route("/files", methods=["GET"])
@require_auth
def list_files():
    # forward request to metadata service via GET
    resp = requests.get(f"{METADATA_API}/files")

    # check response from metadata service
    if resp.status_code == 200:
        return resp.json(), resp.status_code
    else:
        return jsonify({"error": "Metadata error - " + resp.text}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003)