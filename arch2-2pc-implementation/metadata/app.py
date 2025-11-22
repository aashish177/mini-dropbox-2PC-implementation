from flask import Flask, request, jsonify
import grpc
from concurrent import futures
import os, sys, threading

sys.path.insert(0, '/app/proto')
import twopc_pb2
import twopc_pb2_grpc

app = Flask(__name__)

# In-memory metadata store
FILES = {}
USERS = {}

class MetadataParticipant(twopc_pb2_grpc.TwoPhaseCommitServicer):
    def __init__(self, node_id):
        self.node_id = node_id
        self.files = FILES
        self.prepared_transactions = {}

    def VoteRequest(self, request, context):
        caller_node_id = "1"
        print(f"\nPhase Voting of Node {self.node_id} receives RPC VoteRequest from Phase Voting of Node {caller_node_id}")

        txn_id = request.transaction_id
        metadata = request.metadata

        print(f" [Node {self.node_id}] Transaction ID: {txn_id}")
        print(f" [Node {self.node_id}] Operation: {request.operation}")
        print(f" [Node {self.node_id}] Filename: {metadata.filename}")
        print(f" [Node {self.node_id}] Size: {metadata.size} bytes")
        print(f" [Node {self.node_id}] User: {metadata.user}")

        try:
            if not metadata.filename or len(metadata.filename) == 0:
                raise ValueError("Invalid filename")
            
            if metadata.filename in self.files:
                raise ValueError(f"File '{metadata.filename}' already exists")
            
            if metadata.size <= 0:
                raise ValueError("Invalid file size")
            
            self.prepared_transactions[txn_id] = {
                'filename': metadata.filename,
                'size': metadata.size,
                'user': metadata.user,
                'operation': request.operation
            }

            print(f" [Node {self.node_id}] Metadata validation passed")
            print(f" [Node {self.node_id}] Voting: VOTE_COMMIT")

            return twopc_pb2.VoteResponse(
                transaction_id=txn_id,
                vote=twopc_pb2.VOTE_COMMIT,
                node_id=self.node_id
            )
        except Exception as e:
            print(f" [Node {self.node_id}] Validation failed: {e}")
            print(f" [Node {self.node_id}] Voting: VOTE_ABORT")

            return twopc_pb2.VoteResponse(
                transaction_id=txn_id,
                vote=twopc_pb2.VOTE_ABORT,
                node_id=self.node_id,
                reason=str(e)
            )

    def GlobalDecision(self, request, context):
        caller_node_id = "1"
        print(f"\nPhase Decision of Node {self.node_id} recevies RPC GlobalDecision from Phase Decision of Node {caller_node_id}")

        txn_id = request.transaction_id
        decision = request.decision

        decision_str = "GLOBAL_COMMIT" if decision == twopc_pb2.GLOBAL_COMMIT else "GLOBAL_ABORT"
        print(f" [Node {self.node_id}] Transaction ID: {txn_id}")
        print(f" [Node {self.node_id}] Decision: {decision_str}")

        if txn_id not in self.prepared_transactions:
            print(f" [Node {self.node_id}] Transaction not found in prepared state")
            return twopc_pb2.DecisionAck(
                transaction_id=txn_id,
                node_id=self.node_id,
                success=False
            )
        metadata = self.prepared_transactions[txn_id]

        try:
            if decision == twopc_pb2.GLOBAL_COMMIT:
                self.files[metadata['filename']] = {
                    'filename': metadata['filename'],
                    'size': metadata['size'],
                    'user': metadata['user'],
                    'path': f"/storage/{metadata['filename']}",
                    'version': 1
                }
                print(f" [Node {self.node_id}] COMMITED: Metadata saved for {metadata['filename']}")
            else:
                print(f" [Node {self.node_id}] ABORTED: Discarded metadata for {metadata['filename']}")
            
            del self.prepared_transactions[txn_id]

            return twopc_pb2.DecisionAck(
                transaction_id=txn_id,
                node_id=self.node_id,
                success=True
            )
        except Exception as e:
            print(f" [Node {self.node_id}] Error during {decision_str}: {e}")
            return twopc_pb2.DecisionAck(
                transaction_id=txn_id,
                node_id=self.node_id,
                success=False
            )
        
metadata_participant = None

def serve_grpc(node_id, port):
    global metadata_participant

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

    metadata_participant = MetadataParticipant(node_id)
    twopc_pb2_grpc.add_TwoPhaseCommitServicer_to_server(metadata_participant, server)

    server.add_insecure_port(f'[::]:{port}')
    server.start()

    print('*'*60)
    print(f"[Metadata Node {node_id}] gRPC server listening on port {port}")
    print('*'*60)

    server.wait_for_termination()

def serve_http(port):
    print(f"[Metadata] HTTP server listening on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)

# # ---------------- Add / Upload Metadata ----------------
# @app.route("/files", methods=["POST"])
# def add_file():
#     data = request.get_json()
#     if not data:
#         return jsonify({"error": "JSON body required"}), 400

#     filename = data.get("filename")
#     if not filename:
#         return jsonify({"error": "Filename is required"}), 400

#     # Store metadata including password
#     FILES[filename] = {
#         "filename": filename,
#         "path": data.get("path"),
#         "size": data.get("size"),
#         "version": data.get("version", 1),
#         "user": data.get("user"),
#         "password": data.get("password", "")
#     }

#     return jsonify(FILES[filename]), 201


# # ---------------- Get Metadata ----------------
# @app.route("/files/<filename>", methods=["GET"])
# def get_file(filename):
#     if filename not in FILES:
#         return jsonify({"error": "File not found"}), 404
#     return jsonify(FILES[filename])


# # ---------------- Delete Metadata ----------------
# @app.route("/files/<filename>", methods=["DELETE"])
# def delete_file(filename):
#     if filename not in FILES:
#         return jsonify({"error": "File not found"}), 404

#     del FILES[filename]
#     return jsonify({"status": "deleted"}), 200


# ---------------- User Registration ----------------
@app.route("/users", methods=["POST"])
def add_user():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")  # This should be a hashed password
    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    if username in USERS:
        return jsonify({"error": "Username already exists"}), 409

    USERS[username] = password
    return jsonify({"message": "User created"}), 201

# ---------------- Get User for Login ----------------
@app.route("/users/<username>", methods=["GET"])
def get_user(username):
    if username not in USERS:
        return jsonify({"error": "User not found"}), 404
    return jsonify({
        "username": username,
        "password": USERS[username]
    }), 200

# ---------------- List All Files (Optional) ----------------
@app.route("/files", methods=["GET"])
def list_files():
    return jsonify(list(FILES.values())), 200

# ---------------- Main ----------------
if __name__ == "__main__":
    node_id = os.environ.get('NODE_ID', '4')
    grpc_port = int(os.environ.get('GRPC_PORT', '50054'))
    http_port = int(os.environ.get('HTTP_PORT', '5005'))

    grpc_thread = threading.Thread(target=serve_grpc, args=(node_id, grpc_port), daemon=True)
    grpc_thread.start()

    serve_http(http_port)

    