# Mini Dropbox - Two-Phase Commit Implementation

A distributed file storage system implementing the Two-Phase Commit (2PC) protocol to ensure atomic file uploads across replicated storage and metadata nodes.

---

## System Architecture

### Overview
This system uses a 5-node distributed architecture with 2PC coordination:

- **Node 1 (Coordinator)**: Upload service - orchestrates 2PC protocol
- **Node 2 & 3 (Storage Participants)**: Replicated file storage
- **Node 4 & 5 (Metadata Participants)**: Replicated metadata storage
- **Download Service**: Handles file download and delete operations

### Communication Protocols
- **gRPC**: 2PC coordination (voting and decision phases)
- **HTTP/REST**: User authentication, file upload, download, delete

### Port Assignments
| Service | HTTP Port | gRPC Port | Purpose |
|---------|-----------|-----------|---------|
| Upload (Coordinator) | 5003 | - | 2PC coordination, auth |
| Download | 5004 | - | Download, delete |
| Metadata1 | 5005 | 50054 | User management, 2PC participant |
| Metadata2 | 5006 | 50055 | 2PC participant |
| Storage1 | 5008 | 50052 | File storage, 2PC participant |
| Storage2 | 5009 | 50053 | File storage, 2PC participant |

---

## Two-Phase Commit Protocol

### Upload Flow (2PC Atomic Transaction)

**Phase 1: Voting**
1. Client sends file to coordinator
2. Coordinator generates unique transaction ID
3. Coordinator sends `VoteRequest` to all 4 participants
4. Each participant:
   - **Storage nodes**: Save file to `/storage/temp/{txn_id}_{filename}`
   - **Metadata nodes**: Validate (check for duplicates, permissions)
   - Vote `COMMIT` or `ABORT`
5. Coordinator collects all votes

**Phase 2: Decision**
1. Coordinator decides:
   - If **all** vote `COMMIT` → `GLOBAL_COMMIT`
   - If **any** vote `ABORT` → `GLOBAL_ABORT`
2. Coordinator broadcasts decision to all participants
3. Each participant executes:
   - On `GLOBAL_COMMIT`: Move temp file to permanent location
   - On `GLOBAL_ABORT`: Delete temp file (rollback)

### Download/Delete Flow (Non-2PC)
- Direct read/write operations
- Download: Retrieves file from Storage1
- Delete: Removes file and metadata (not atomic)

---

## Implementation Details

### Key Components

**1. Protocol Buffers Definition** (`proto/twopc.proto`)
```protobuf
service TwoPhaseCommit {
    rpc VoteRequest(VoteRequestMsg) returns (VoteResponse);
    rpc GlobalDecision(DecisionMsg) returns (DecisionAck);
}
```

**2. Coordinator** (`services/upload/app.py`)
- Manages 2PC protocol execution
- Connects to all 4 participants via gRPC
- Implements voting and decision phases
- Handles timeouts (10-second RPC timeout)

**3. Storage Participant** (`storage/app.py`)
- Runs both gRPC server (2PC) and HTTP server (download/delete)
- Temporary storage pattern: `/storage/temp/{txn_id}_{filename}`
- Commit: `os.rename(temp_path, final_path)`
- Abort: `os.remove(temp_path)`

**4. Metadata Participant** (`metadata/app.py`)
- Runs both gRPC server (2PC) and HTTP server (user management)
- Validates file existence during voting phase
- Stores metadata in prepared state, commits on decision

---

## Setup and Installation

### Prerequisites
- Docker 20.10+
- Docker Compose 2.0+

### Build and Start
```bash
# Navigate to project directory
cd arch2-2pc-implementation

# Build and start all services
docker-compose up --build

# Or run in detached mode
docker-compose up --build -d
```

### Verify Services
```bash
docker ps
```
You should see 7 containers running: coordinator, download, 2 storage nodes, 2 metadata nodes, and client.

---

## Testing Scenarios

### Initial Setup
```bash
# Connect to client container
docker exec -it client /bin/bash

# Create user account
python3 cli.py signup testuser password123

# Login (saves JWT token)
python3 cli.py login testuser password123
```

---

## Scenario 1: Happy Path (Successful Upload)

### Description
All participants vote `COMMIT`, transaction succeeds, file replicated across all nodes.

### Steps
```bash
# 1. Create test file
echo "Hello 2PC World!" > happy.txt

# 2. Upload file
python3 cli.py upload happy.txt
```

### Expected Output
```json
{
  "filename": "happy.txt",
  "message": "File uploaded successfully via 2PC",
  "size": 17
}
```

### Verification
```bash
# List files
python3 cli.py list

# Exit client container
exit

# From Mac terminal - verify file exists on both storage nodes
docker exec node2_storage1 cat /storage/happy.txt
docker exec node3_storage2 cat /storage/happy.txt

# Verify temp directory is cleaned up
docker exec node2_storage1 ls /storage/temp
docker exec node3_storage2 ls /storage/temp
# Should be empty
```

### What Happened (Behind the Scenes)
1. **Voting Phase**:
   - Storage1: Saves to `/storage/temp/txn123_happy.txt` → votes `COMMIT`
   - Storage2: Saves to `/storage/temp/txn123_happy.txt` → votes `COMMIT`
   - Metadata1: Validates file doesn't exist → votes `COMMIT`
   - Metadata2: Validates file doesn't exist → votes `COMMIT`
   - **Result**: All 4 participants vote `COMMIT`

2. **Decision Phase**:
   - Coordinator: All votes are `COMMIT` → Decision = `GLOBAL_COMMIT`
   - Storage1: `mv /storage/temp/txn123_happy.txt /storage/happy.txt` ✓
   - Storage2: `mv /storage/temp/txn123_happy.txt /storage/happy.txt` ✓
   - Metadata1: Persist metadata ✓
   - Metadata2: Persist metadata ✓

3. **Result**: File successfully replicated to all nodes atomically

---

## Scenario 2: Duplicate File (2PC Abort)

### Description
Metadata participants detect duplicate file, vote `ABORT`, transaction rolls back cleanly.

### Steps
```bash
# Connect to client
docker exec -it client /bin/bash
python3 cli.py login testuser password123

# 1. Upload file first time (succeeds)
echo "First upload" > duplicate.txt
python3 cli.py upload duplicate.txt

# 2. Try to upload same filename again (should fail)
python3 cli.py upload duplicate.txt
```

### Expected Output (Second Upload)
```json
{
  "error": "Upload failed - transaction aborted",
  "filename": "duplicate.txt"
}
```

### Verification
```bash
# List files - should show only ONE instance
python3 cli.py list

# Exit and check storage
exit

# Verify only one file exists
docker exec node2_storage1 ls /storage | grep duplicate.txt
# Should show only one file

# Verify temp directory is empty (rollback succeeded)
docker exec node2_storage1 ls /storage/temp
docker exec node3_storage2 ls /storage/temp
# Should be empty
```

### What Happened (Behind the Scenes)
1. **Voting Phase** (Second Upload):
   - Storage1: Saves to `/storage/temp/txn456_duplicate.txt` → votes `COMMIT`
   - Storage2: Saves to `/storage/temp/txn456_duplicate.txt` → votes `COMMIT`
   - Metadata1: **Detects file already exists** → votes `ABORT` ✗
   - Metadata2: **Detects file already exists** → votes `ABORT` ✗
   - **Result**: 2 COMMIT, 2 ABORT

2. **Decision Phase**:
   - Coordinator: Not all votes are `COMMIT` → Decision = `GLOBAL_ABORT`
   - Storage1: `rm /storage/temp/txn456_duplicate.txt` (rollback) ✓
   - Storage2: `rm /storage/temp/txn456_duplicate.txt` (rollback) ✓
   - Metadata1: Discard prepared state ✓
   - Metadata2: Discard prepared state ✓

3. **Result**: Transaction aborted, no orphaned files, original file intact

---

## Additional Operations

### Download File
```bash
docker exec -it client /bin/bash
python3 cli.py login testuser password123

# Download to specific location
python3 cli.py download happy.txt --output retrieved.txt
cat retrieved.txt
```

### Delete File
```bash
python3 cli.py delete happy.txt
python3 cli.py list  # File should be gone
```

### List Files
```bash
python3 cli.py list
```

---

## Logs and Debugging

### View Coordinator Logs
```bash
docker logs node1_coordinator
```

### View Storage Node Logs
```bash
docker logs node2_storage1
docker logs node3_storage2
```

### View Metadata Node Logs
```bash
docker logs node4_metadata1
docker logs node5_metadata2
```

### Watch Live Logs
```bash
# Terminal 1: Run services in foreground
docker-compose up

# Terminal 2: Execute commands
docker exec -it client /bin/bash
```

---

## Key Properties Achieved

✅ **Atomicity**: All nodes commit or all nodes abort - no partial states
✅ **Consistency**: File list matches actual storage contents
✅ **No Orphaned Files**: Failed transactions leave no temp files
✅ **Fault Tolerance**: Node failures trigger clean abort
✅ **Replication**: 2x storage redundancy, 2x metadata redundancy

---

## Cleanup

```bash
# Stop all containers
docker-compose down

# Remove volumes (deletes stored files)
docker-compose down -v

# Remove token file
rm -f ~/.mini_dropbox_token
```

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                         CLIENT                               │
└────────────┬─────────────────────────┬──────────────────────┘
             │                         │
             ▼ (Upload)                ▼ (Download/Delete)
    ┌────────────────┐        ┌───────────────┐
    │ COORDINATOR    │        │  DOWNLOAD     │
    │  (Node 1)      │        │  SERVICE      │
    │  Port 5003     │        │  Port 5004    │
    └────────┬───────┘        └───────┬───────┘
             │                        │
    ┌────────┴────────────────────────┴────────┐
    │         2PC Protocol (gRPC)              │
    ├──────┬──────────┬──────────┬─────────────┤
    ▼      ▼          ▼          ▼             │
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐   │
│Storage1│ │Storage2│ │Metadata│ │Metadata│   │
│ Node 2 │ │ Node 3 │ │ Node 4 │ │ Node 5 │   │
│  5008  │ │  5009  │ │  5005  │ │  5006  │   │
│ 50052  │ │ 50053  │ │ 50054  │ │ 50055  │   │
└────────┘ └────────┘ └────────┘ └────────┘   │
     │          │          │          │        │
     └──────────┴──────────┴──────────┴────────┘
              File Replication
```

---

## Implementation Highlights

- **Temporary Storage Pattern**: Enables clean rollback without affecting permanent files
- **gRPC Communication**: Efficient binary protocol for distributed coordination
- **Transaction State Management**: Each participant tracks in-flight transactions
- **Timeout Handling**: 10-second RPC timeout prevents indefinite blocking
- **Dual Server Architecture**: Storage nodes run both gRPC (2PC) and HTTP (download/delete)

---

## Future Enhancements

- Implement 2PC for delete operations
- Add persistent transaction log for crash recovery
- Implement coordinator failover with Raft consensus
- Add Three-Phase Commit (3PC) for non-blocking protocol
- Optimize with parallel gRPC calls during decision phase

---

## Project Information

**Course**: Distributed Systems - CSE 5406
**Topic**: Two-Phase Commit Protocol for Atomic File Upload
**Date**: November 2024
