# Mini Dropbox with Two-Phase Commit (2PC) Protocol

A distributed file storage system implementing the Two-Phase Commit protocol for atomic file uploads across multiple replicated storage and metadata nodes.

## Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [Two-Phase Commit Implementation](#two-phase-commit-implementation)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Setup and Installation](#setup-and-installation)
- [Usage](#usage)
- [Implementation Details](#implementation-details)
- [Testing Scenarios](#testing-scenarios)
- [Key Features](#key-features)
- [Limitations](#limitations)

---

## Overview

This project implements a distributed file storage system (similar to Dropbox) with **Two-Phase Commit (2PC)** protocol to ensure atomicity when uploading files across multiple replicated nodes. The system guarantees that file uploads either succeed on all nodes or fail completely, preventing partial failures and maintaining data consistency.

### What is Two-Phase Commit?

Two-Phase Commit is a distributed algorithm that ensures all participants in a distributed transaction either commit or abort the transaction. It consists of two phases:

1. **Voting Phase (Prepare)**: Coordinator asks all participants if they can commit
2. **Decision Phase (Commit/Abort)**: Coordinator tells all participants to commit or abort based on votes

---

## Architecture

### System Components (5 Nodes)

```
┌─────────────────────────────────────────┐
│  Node 1: Coordinator (Upload Service)  │
│  - Orchestrates 2PC protocol            │
│  - Handles authentication (JWT)         │
│  - gRPC Client to all participants      │
│  Port: 5003 (HTTP)                      │
└───────────────┬─────────────────────────┘
                │ gRPC (2PC Protocol)
        ┌───────┴────────┬────────┬────────┐
        ▼                ▼        ▼        ▼
    ┌───────┐      ┌───────┐  ┌───────┐  ┌───────┐
    │Node 2 │      │Node 3 │  │Node 4 │  │Node 5 │
    │Storage│      │Storage│  │Meta   │  │Meta   │
    │Rep 1  │      │Rep 2  │  │Rep 1  │  │Rep 2  │
    │       │      │       │  │       │  │       │
    │gRPC   │      │gRPC   │  │gRPC   │  │gRPC   │
    │50052  │      │50053  │  │50054  │  │50055  │
    └───────┘      └───────┘  └───────┘  └───────┘
```

### Node Responsibilities

| Node | Role | Responsibilities | Ports |
|------|------|------------------|-------|
| **Node 1** | Coordinator | JWT auth, 2PC orchestration, client interface | 5003 (HTTP) |
| **Node 2** | Storage Participant | File storage (replica 1), 2PC voting | 50052 (gRPC) |
| **Node 3** | Storage Participant | File storage (replica 2), 2PC voting | 50053 (gRPC) |
| **Node 4** | Metadata Participant | Metadata validation (replica 1), 2PC voting | 50054 (gRPC), 5005 (HTTP) |
| **Node 5** | Metadata Participant | Metadata validation (replica 2), 2PC voting | 50055 (gRPC), 5006 (HTTP) |

---

## Two-Phase Commit Implementation

### Phase 1: Voting Phase

When a user uploads a file, the coordinator initiates the voting phase:

```
1. Coordinator generates transaction ID (txn_id)
2. Coordinator sends VoteRequest to all 4 participants:
   ├─> Node 2 (Storage): Save file to /storage/temp/txn_id_filename
   ├─> Node 3 (Storage): Save file to /storage/temp/txn_id_filename
   ├─> Node 4 (Metadata): Validate metadata (check duplicates, size, etc.)
   └─> Node 5 (Metadata): Validate metadata (check duplicates, size, etc.)

3. Each participant responds:
   ├─> VOTE_COMMIT (if preparation succeeded)
   └─> VOTE_ABORT (if preparation failed)

4. Coordinator collects all votes
```

**Storage Participant Voting Logic:**
- Saves file to **temporary** location (`/storage/temp/txn_id_filename`)
- Stores transaction state in `prepared_transactions` dictionary
- Returns `VOTE_COMMIT` if successful, `VOTE_ABORT` if failed

**Metadata Participant Voting Logic:**
- Validates filename (non-empty, no duplicates)
- Validates file size (> 0)
- Stores metadata in **prepared** state (not committed yet)
- Returns `VOTE_COMMIT` if valid, `VOTE_ABORT` if invalid

### Phase 2: Decision Phase

After collecting all votes, the coordinator makes a decision:

```
1. Coordinator evaluates votes:
   ├─> If ALL voted COMMIT → Decision = GLOBAL_COMMIT
   └─> If ANY voted ABORT  → Decision = GLOBAL_ABORT

2. Coordinator sends GlobalDecision to all participants:
   ├─> Node 2: GlobalDecision(txn_id, COMMIT/ABORT)
   ├─> Node 3: GlobalDecision(txn_id, COMMIT/ABORT)
   ├─> Node 4: GlobalDecision(txn_id, COMMIT/ABORT)
   └─> Node 5: GlobalDecision(txn_id, COMMIT/ABORT)

3. Participants execute decision:
   ├─> COMMIT: Move temp file to permanent location
   └─> ABORT:  Delete temp file, discard metadata
```

**Storage Participant Decision Logic:**
```python
if decision == GLOBAL_COMMIT:
    # Move file from temp to permanent
    os.rename('/storage/temp/txn_id_file.txt', '/storage/file.txt')
else:  # GLOBAL_ABORT
    # Delete temp file
    os.remove('/storage/temp/txn_id_file.txt')
```

**Metadata Participant Decision Logic:**
```python
if decision == GLOBAL_COMMIT:
    # Commit metadata to permanent storage
    FILES[filename] = metadata
else:  # GLOBAL_ABORT
    # Discard prepared metadata
    del prepared_transactions[txn_id]
```

### Example: Successful Upload Flow

```
Client: upload("photo.jpg", <data>)
  ↓
Coordinator (Node 1):
  ├─ Generate txn_id = "a3f8c9d2"
  ├─ Send VoteRequest to Nodes 2-5
  ↓
Node 2 (Storage):
  ├─ Save to /storage/temp/a3f8c9d2_photo.jpg
  └─ Return VOTE_COMMIT
  ↓
Node 3 (Storage):
  ├─ Save to /storage/temp/a3f8c9d2_photo.jpg
  └─ Return VOTE_COMMIT
  ↓
Node 4 (Metadata):
  ├─ Validate: filename="photo.jpg", size=1024, user="alice"
  ├─ Check: "photo.jpg" not in FILES ✓
  └─ Return VOTE_COMMIT
  ↓
Node 5 (Metadata):
  ├─ Validate: filename="photo.jpg", size=1024, user="alice"
  └─ Return VOTE_COMMIT
  ↓
Coordinator:
  ├─ All votes = COMMIT
  ├─ Decision = GLOBAL_COMMIT
  ├─ Send GlobalDecision(COMMIT) to Nodes 2-5
  ↓
Nodes 2-3:
  └─ Move: temp/a3f8c9d2_photo.jpg → photo.jpg
  ↓
Nodes 4-5:
  └─ Commit: FILES["photo.jpg"] = {...}
  ↓
Client: "Upload successful!"
```

### Example: Failed Upload Flow (Duplicate File)

```
Client: upload("photo.jpg", <data>)  # File already exists
  ↓
Coordinator (Node 1):
  ├─ Generate txn_id = "b7e2d1a5"
  ├─ Send VoteRequest to Nodes 2-5
  ↓
Node 2 (Storage):
  ├─ Save to /storage/temp/b7e2d1a5_photo.jpg
  └─ Return VOTE_COMMIT
  ↓
Node 3 (Storage):
  ├─ Save to /storage/temp/b7e2d1a5_photo.jpg
  └─ Return VOTE_COMMIT
  ↓
Node 4 (Metadata):
  ├─ Validate: filename="photo.jpg"
  ├─ Check: "photo.jpg" already in FILES ✗
  └─ Return VOTE_ABORT (reason: "File already exists")
  ↓
Node 5 (Metadata):
  ├─ Validate: filename="photo.jpg"
  └─ Return VOTE_ABORT (reason: "File already exists")
  ↓
Coordinator:
  ├─ Votes = [COMMIT, COMMIT, ABORT, ABORT]
  ├─ Decision = GLOBAL_ABORT (at least one ABORT)
  ├─ Send GlobalDecision(ABORT) to Nodes 2-5
  ↓
Nodes 2-3:
  └─ Delete: temp/b7e2d1a5_photo.jpg (rollback)
  ↓
Nodes 4-5:
  └─ Discard prepared metadata
  ↓
Client: "Upload failed - File already exists"
Result: NO orphaned files, consistent state maintained!
```

---

## Project Structure

```
arch2-2pc-implementation/
├── proto/
│   ├── twopc.proto              # gRPC service definitions
│   ├── twopc_pb2.py             # Generated protobuf classes
│   └── twopc_pb2_grpc.py        # Generated gRPC stubs
│
├── services/
│   └── upload/
│       ├── app.py               # Coordinator implementation
│       ├── Dockerfile
│       └── requirements.txt
│
├── storage/
│   ├── app.py                   # Storage participant
│   ├── Dockerfile
│   └── requirements.txt
│
├── metadata/
│   ├── app.py                   # Metadata participant
│   ├── Dockerfile
│   └── requirements.txt
│
├── client/
│   ├── cli.py                   # CLI client
│   ├── Dockerfile
│   └── requirements.txt
│
├── docker-compose.yml           # Multi-container orchestration
└── README.md                    # This file
```

---

## Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- Python 3.11+ (for local development)

---

## Setup and Installation

### Using Docker (Recommended)

```bash
# Navigate to project directory
cd arch2-2pc-implementation

# Build all containers
docker-compose build

# Start all services (5 nodes)
docker-compose up

# In another terminal, access the client
docker exec -it client /bin/bash
```

---

## Usage

### 1. User Signup

```bash
# Inside client container
python cli.py signup alice password123
```

**Output:**
```json
{"message": "Signup successful!"}
```

### 2. User Login

```bash
python cli.py login alice password123
```

**Output:**
```
Login successful!
```

**Note:** JWT token is saved to `~/.mini_dropbox_token`

### 3. Upload File

```bash
# Create a test file
echo "Hello 2PC!" > test.txt

# Upload it
python cli.py upload test.txt
```

**Expected Logs (Coordinator - Node 1):**
```
[Coordinator] New upload request: test.txt (Transaction ID: a3f8c9d2)

======================================================================
[Coordinator] Starting VOTING PHASE for transaction a3f8c9d2
Operation: upload, File: test.txt, Size: 11 bytes
======================================================================

Phase Voting of Node 1 sends RPC VoteRequest to Phase Voting of Node 2
  ← Node 2 voted: VOTE_COMMIT
Phase Voting of Node 1 sends RPC VoteRequest to Phase Voting of Node 3
  ← Node 3 voted: VOTE_COMMIT
Phase Voting of Node 1 sends RPC VoteRequest to Phase Voting of Node 4
  ← Node 4 voted: VOTE_COMMIT
Phase Voting of Node 1 sends RPC VoteRequest to Phase Voting of Node 5
  ← Node 5 voted: VOTE_COMMIT

[Coordinator] Votes collected: {'2': 0, '3': 0, '4': 0, '5': 0}

======================================================================
[Coordinator] Starting DECISION PHASE for transaction a3f8c9d2
Decision: GLOBAL_COMMIT
======================================================================

Phase Decision of Node 1 sends RPC GlobalDecision to Phase Decision of Node 2
  ✓ Node 2 acknowledged GLOBAL_COMMIT
Phase Decision of Node 1 sends RPC GlobalDecision to Phase Decision of Node 3
  ✓ Node 3 acknowledged GLOBAL_COMMIT
Phase Decision of Node 1 sends RPC GlobalDecision to Phase Decision of Node 4
  ✓ Node 4 acknowledged GLOBAL_COMMIT
Phase Decision of Node 1 sends RPC GlobalDecision to Phase Decision of Node 5
  ✓ Node 5 acknowledged GLOBAL_COMMIT
======================================================================
```

**Client Output:**
```json
{"message": "File uploaded successfully via 2PC", "filename": "test.txt", "size": 11}
```

### 4. List Files

```bash
python cli.py list
```

**Output:**
```json
[
  {
    "filename": "test.txt",
    "size": 11,
    "user": "alice",
    "path": "/storage/test.txt",
    "version": 1
  }
]
```

### 5. Verify Files Exist in Storage

```bash
# Check storage replicas
docker exec node2_storage1 ls -la /storage/
docker exec node3_storage2 ls -la /storage/

# Both should show test.txt
```

---

## Implementation Details

### gRPC Protocol Definition (`proto/twopc.proto`)

```protobuf
syntax = "proto3";

package twopc;

service TwoPhaseCommit {
    // Phase 1: Voting
    rpc VoteRequest(VoteRequestMsg) returns (VoteResponse);

    // Phase 2: Decision
    rpc GlobalDecision(DecisionMsg) returns (DecisionAck);
}

message VoteRequestMsg {
    string transaction_id = 1;
    string operation = 2;        // "upload"
    string filename = 3;
    bytes file_data = 4;         // File content
    FileMetadata metadata = 5;   // Metadata info
}

message VoteResponse {
    string transaction_id = 1;
    VoteDecision vote = 2;       // VOTE_COMMIT or VOTE_ABORT
    string node_id = 3;
    string reason = 4;           // Reason for abort
}

enum VoteDecision {
    VOTE_COMMIT = 0;
    VOTE_ABORT = 1;
}

message DecisionMsg {
    string transaction_id = 1;
    GlobalDecision decision = 2; // GLOBAL_COMMIT or GLOBAL_ABORT
}

enum GlobalDecision {
    GLOBAL_COMMIT = 0;
    GLOBAL_ABORT = 1;
}

message DecisionAck {
    string transaction_id = 1;
    string node_id = 2;
    bool success = 3;
}
```

### Key Components

#### Coordinator (`services/upload/app.py`)

**Responsibilities:**
- JWT authentication (signup/login)
- 2PC orchestration
- gRPC client to all participants

**Key Methods:**
1. `voting_phase()` - Sends VoteRequest to all participants
2. `decision_phase()` - Sends GlobalDecision based on votes
3. `execute_upload()` - Orchestrates complete 2PC flow

#### Storage Participant (`storage/app.py`)

**Responsibilities:**
- Temporary file storage during voting phase
- File commit/rollback during decision phase
- gRPC server for 2PC protocol

**State Management:**
```python
prepared_transactions = {
    "txn_123": {
        'temp_path': '/storage/temp/txn_123_file.txt',
        'final_path': '/storage/file.txt',
        'operation': 'upload',
        'filename': 'file.txt'
    }
}
```

#### Metadata Participant (`metadata/app.py`)

**Responsibilities:**
- Metadata validation during voting phase
- Metadata commit/rollback during decision phase
- HTTP server for user management
- gRPC server for 2PC protocol

**State Management:**
```python
FILES = {
    "file.txt": {
        'filename': 'file.txt',
        'size': 1024,
        'user': 'alice',
        'path': '/storage/file.txt',
        'version': 1
    }
}

prepared_transactions = {
    "txn_123": {
        'filename': 'file.txt',
        'size': 1024,
        'user': 'alice',
        'operation': 'upload'
    }
}
```

---

## Testing Scenarios

### Test 1: Successful Upload (Happy Path)

```bash
# Create test file
echo "Hello World" > hello.txt

# Upload
python cli.py upload hello.txt
```

**Expected:**
- ✅ All 4 participants vote COMMIT
- ✅ Coordinator sends GLOBAL_COMMIT
- ✅ File exists in both storage replicas
- ✅ Metadata exists in both metadata replicas

### Test 2: Duplicate File Upload (Abort Scenario)

```bash
# Upload first time
python cli.py upload test.txt

# Upload again (should fail)
python cli.py upload test.txt
```

**Expected:**
- ✅ Metadata participants vote ABORT
- ✅ Coordinator sends GLOBAL_ABORT
- ✅ Temp files deleted from storage
- ✅ No orphaned files

**Verification:**
```bash
docker exec node2_storage1 ls /storage/temp/
# Should be empty
```

### Test 3: Storage Node Failure

```bash
# Stop one storage node
docker stop node2_storage1

# Try upload (should timeout)
python cli.py upload test2.txt

# Restart node
docker start node2_storage1
```

**Expected:**
- ✅ Coordinator times out waiting for Node 2
- ✅ Transaction aborts
- ✅ No partial writes

---

## Key Features

### Atomicity Guarantee
Either all nodes commit or all nodes abort. No partial failures.

### Data Replication
- 2 storage replicas (fault tolerance)
- 2 metadata replicas (high availability)

### Rollback Capability
Temporary storage allows clean rollback on failure without side effects.

### Required Logging Format
Every RPC call logs:
- **Client side:** `"Phase <phase> of Node X sends RPC <name> to Phase <phase> of Node Y"`
- **Server side:** `"Phase <phase> of Node Y receives RPC <name> from Phase <phase> of Node X"`

### Authentication & Authorization
- JWT-based authentication
- Token expiration (24 hours)
- Secure password hashing (werkzeug)

---

## Limitations

### Known Limitations:

1. **No Persistent Transaction Log**
   - Coordinator crash may leave transactions in prepared state
   - Recovery not implemented

2. **Blocking Protocol**
   - Participants block waiting for coordinator decision
   - Vulnerable to coordinator failure

3. **In-Memory Metadata**
   - Metadata lost on service restart
   - Should use persistent database in production

4. **Single Coordinator**
   - No failover mechanism
   - Single point of failure

5. **No Three-Phase Commit (3PC)**
   - 2PC is blocking if coordinator fails
   - 3PC would add non-blocking property

### Comparison: Before vs After 2PC

**Before 2PC:**
```
Upload Flow:
1. Save to storage ✓
2. Save to metadata ✗ (fails)
Result: Orphaned file in storage ❌
```

**After 2PC:**
```
Upload Flow:
1. Prepare on storage ✓
2. Prepare on metadata ✗ (fails, votes ABORT)
3. Coordinator sends ABORT
4. Storage deletes temp file ✓
Result: Clean abort, no orphaned files ✅
```

---

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'twopc_pb2'"

**Solution:** Proto files not generated during build.
```bash
docker-compose build --no-cache
```

### Issue: Storage/Metadata nodes fail to start

**Solution:** Check import paths in Python files.
```python
# Should be:
sys.path.insert(0, '/app/proto')
```

### Issue: Coordinator can't connect to participants

**Solution:** Verify service names match docker-compose.yml.
```python
# services/upload/app.py
self.participants = {
    "2": ("storage1", 50052),  # Must match container_name
    ...
}
```

### Viewing Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f upload

# Filter for 2PC messages
docker-compose logs | grep "Phase Voting"
docker-compose logs | grep "Phase Decision"
```

### Cleaning Up

```bash
# Stop all services
docker-compose down

# Remove volumes (deletes uploaded files)
docker-compose down -v

# Rebuild from scratch
docker-compose build --no-cache
docker-compose up
```

---

## References

- [Two-Phase Commit Protocol - Wikipedia](https://en.wikipedia.org/wiki/Two-phase_commit_protocol)
- [gRPC Documentation](https://grpc.io/docs/)
- [Protocol Buffers](https://developers.google.com/protocol-buffers)
- [Docker Compose](https://docs.docker.com/compose/)

---

## Authors

CSE 5406-004 - Distributed Systems Project

---

## License

Educational use only.
