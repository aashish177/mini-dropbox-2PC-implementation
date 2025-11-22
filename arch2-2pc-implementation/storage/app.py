from flask import Flask, request, jsonify, send_file
from concurrent import futures
import os, grpc, sys
import requests, threading

sys.path.insert(0, '/app/proto')
import twopc_pb2
import twopc_pb2_grpc

app = Flask(__name__)

STORAGE_PATH = "/storage"
TEMP_PATH = "/storage/temp"
METADATA_API = "http://metadata:5005/files"

os.makedirs(STORAGE_PATH, exist_ok=True)
os.makedirs(TEMP_PATH, exist_ok=True)

class StorageParticipant(twopc_pb2_grpc.TwoPhaseCommitServicer):
    def __init__(self, node_id):
        self.node_id = node_id
        self.storage_path = STORAGE_PATH
        self.temp_path = TEMP_PATH
        self.prepared_transactions = {}

        print(f"[Storage Node {self.node_id}] Intialized...")
        print(f" Storage path: {self.storage_path}")
        print(f" Temp path: {self.temp_path}")

    def VoteRequest(self, request, context):
        caller_node_id = "1"
        print(f"\nPhase Voting of Node {self.node_id} receives RPC VoteRequest from Phase Voting of Node {caller_node_id}")

        txn_id = request.transaction_id
        filename = request.filename
        file_data = request.file_data

        print(f"  [Node {self.node_id}] Transaction ID: {txn_id}")
        print(f"  [Node {self.node_id}] Operation: {request.operation}")
        print(f"  [Node {self.node_id}] Filename: {filename}")
        print(f"  [Node {self.node_id}] File size: {len(file_data)} bytes")
              
        try:
            temp_file_path = os.path.join(self.temp_path, f"{txn_id}_{filename}")
            final_file_path = os.path.join(self.storage_path, filename)

            print(f"  [Node {self.node_id}] Saving to temp: {temp_file_path}")

            with open(temp_file_path, 'wb') as f:
                f.write(file_data)
            
            if not os.path.exists(temp_file_path):
                raise Exception("File not written successfully")
            
            self.prepared_transactions[txn_id] = {
                'temp_path': temp_file_path,
                'final_path': final_file_path,
                'operation': request.operation,
                'filename': filename
            }

            print(f"  [Node {self.node_id}] File saved to temp location")
            print(f"  [Node {self.node_id}] Voting: VOTE_COMMIT")

            return twopc_pb2.VoteResponse(
                transaction_id=txn_id,
                vote=twopc_pb2.VOTE_COMMIT,
                node_id=self.node_id
            )
        
        except Exception as e:
            print(f" [Node {self.node_id}] Error: {e}")
            print(f" [Node {self.node_id}] Voting: VOTE_ABORT")

            return twopc_pb2.VoteResponse(
                transaction_id=txn_id,
                vote=twopc_pb2.VOTE_ABORT,
                node_id=self.node_id,
                reason=str(e)
            )
    
    def GlobalDecision(self, request, context):
        caller_node_id = "1"
        print(f"\n Phase Decision of Node {self.node_id} receives RPC GlobalDecision from Phase Decision of Node {caller_node_id}")

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
        
        txn = self.prepared_transactions[txn_id]

        try:
            if decision == twopc_pb2.GLOBAL_COMMIT:
                os.rename(txn['temp_path'], txn['final_path'])
                print(f" [Node {self.node_id}] COMMITED: {txn['temp_path']} to {txn['final_path']}")

            else:
                if os.path.exists(txn['temp_path']):
                    os.remove(txn['temp_path'])
                print(f" [Node {self.node_id}] ABORTED: Deleted {txn['temp_path']}")

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
        
def serve_grpc(node_id, port):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

    participant = StorageParticipant(node_id)
    twopc_pb2_grpc.add_TwoPhaseCommitServicer_to_server(participant, server)

    server.add_insecure_port(f'[::]:{port}')
    server.start()

    print("*"*60)
    print(f"[Storage Node {node_id}] gRPC server listening on port {port}\n")

    server.wait_for_termination()




# # ---------------- Upload ----------------
# @app.route("/upload", methods=["POST"])
# def upload_file():
#     if "file" not in request.files:
#         return jsonify({"error": "No file part"}), 400
#     f = request.files["file"]

#     # Get username/password
#     # username = request.form.get("user") or request.values.get("user")
#     # password = request.form.get("password") or request.values.get("password")
#     # if not username or not password:
#     #     return jsonify({"error": "Username and password are required"}), 400

#     print("request.form:", request.form)
#     print("request.files:", request.files)
#     print("request.values:", request.values)

#     # Save file
#     save_path = os.path.join(STORAGE_PATH, f.filename)
#     try:
#         f.save(save_path)
#     except Exception as e:
#         return jsonify({"error": f"Failed to save file: {e}"}), 500

#     # Build metadata
#     size = os.path.getsize(save_path)
#     metadata = {
#         "filename": f.filename,
#         "path": save_path,
#         "size": size,
#         "version": 1,
#         # "user": username,
#         # "password": password
#     }

#     # Send metadata to metadata container
#     try:
#         r = requests.post(METADATA_API, json=metadata)
#         r.raise_for_status()
#     except Exception as e:
#         return jsonify({"error": f"Failed to save metadata: {e}"}), 500

#     return jsonify({"path": save_path, "status": "saved"}), 200

# # ---------------- Download ----------------
# @app.route("/download", methods=["GET"])
# def download_file():
#     filename = request.args.get("filename")
#     # username = request.args.get("user")
#     # password = request.args.get("password")

#     # if not filename or not username or not password:
#     #     return jsonify({"error": "Filename, username, and password required"}), 400

#     # Fetch metadata
#     try:
#         r = requests.get(f"{METADATA_API}/{filename}")
#         r.raise_for_status()
#         metadata = r.json()
#     except Exception as e:
#         return jsonify({"error": f"Failed to fetch metadata: {e}"}), 404

#     # Validate username/password
#     # if username.strip() != metadata["user"].strip() or password.strip() != metadata["password"].strip():
#     #     return jsonify({"error": "Invalid username or password"}), 403

#     # Check if file exists
#     file_path = metadata["path"]
#     if not os.path.exists(file_path):
#         return jsonify({"error": "File not found"}), 404

#     return send_file(file_path, as_attachment=True)

# # ---------------- Delete ----------------
# @app.route("/delete", methods=["DELETE"])
# def delete_file():
#     filename = request.args.get("filename")
#     # username = request.args.get("user")
#     # password = request.args.get("password")

#     # if not filename or not username or not password:
#     #     return jsonify({"error": "Filename, username, and password required"}), 400

#     # Fetch metadata
#     try:
#         r = requests.get(f"{METADATA_API}/{filename}")
#         r.raise_for_status()
#         metadata = r.json()
#     except Exception as e:
#         return jsonify({"error": f"Failed to fetch metadata: {e}"}), 404

#     # # Validate username/password
#     # if username.strip() != metadata["user"].strip() or password.strip() != metadata["password"].strip():
#     #     return jsonify({"error": "Invalid username or password"}), 403

#     # Delete file
#     try:
#         file_path = metadata["path"]
#         if os.path.exists(file_path):
#             os.remove(file_path)
#     except Exception as e:
#         return jsonify({"error": f"Failed to delete file: {e}"}), 500

#     # Delete metadata
#     try:
#         r = requests.delete(f"{METADATA_API}/{filename}")
#         r.raise_for_status()
#     except Exception as e:
#         return jsonify({"error": f"Failed to delete metadata: {e}"}), 500

#     return jsonify({"status": "deleted"}), 200

# ---------------- Main ----------------
if __name__ == "__main__":
    node_id = os.environ.get('NODE_ID', '2')
    grpc_port = int(os.environ.get('GRPC_PORT', '50052'))

    serve_grpc(node_id, grpc_port)