import asyncio
import os
import sys
import hashlib
import json
import logging
import time
import secrets
from pathlib import Path
from typing import List, Dict, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import websockets

# Local imports
from backend.merkle import  merkle_root
from backend.tpm_attest import TPMManager
from backend.models import (init_database, get_db_session, SessionLocal,
                    IntegrityEvent, FileStorage, TPMQuote, NodeModel, AuditLog)

# Configuration with proper defaults
NODE_ID = int(os.getenv('NODE_ID', 0))
PORT = int(os.getenv('PORT', 7000))
TOTAL_NODES = int(os.getenv('TOTAL_NODES', 4))
PEERS = [peer.strip() for peer in os.getenv('PEERS', '').split(',') if peer.strip()]
DATABASE_URL = os.getenv('SFIM_DB', f'sqlite:///./data/node{NODE_ID}_sfim.db')
USE_SIMULATED_TPM = os.getenv('USE_SIMULATED_TPM', 'true').lower() == 'true'

# Ensure data directory exists
Path('./data').mkdir(exist_ok=True)
Path(os.getenv('WATCH_PATHS', './watched')).mkdir(exist_ok=True)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(f"SFIMNode-{NODE_ID}")

app = FastAPI(title=f"SFIM Node {NODE_ID}", version="1.0.0")

# Global variables
tpm_manager: Optional[TPMManager] = None
connected_clients: List[WebSocket] = []
peer_connections: Dict[int, WebSocket] = {}
consensus_state = {
    'view': 0,
    'sequence_number': 0,
    'prepare_messages': {},
    'commit_messages': {},
    'prepared_digests': set(),
    'committed_digests': set()
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*","http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# BLS Manager for consensus signatures
class BLSManager:
    def __init__(self, node_id: int):
        self.node_id = node_id
        self.private_key = f"node_{node_id}_key".encode().ljust(32, b'\x00')

    def sign(self, message: bytes) -> str:
        return hashlib.sha256(self.private_key + message).hexdigest()

    def verify(self, node_id: int, message: bytes, signature: str) -> bool:
        expected_key = f"node_{node_id}_key".encode().ljust(32, b'\x00')
        expected_sig = hashlib.sha256(expected_key + message).hexdigest()
        return signature == expected_sig

    def aggregate(self, signatures: List[str]) -> str:
        return hashlib.sha256("".join(signatures).encode()).hexdigest()


bls_manager = BLSManager(NODE_ID)


@app.on_event("startup")
async def startup_event():
    global tpm_manager

    logger.info(f"Starting SFIM Node {NODE_ID}")
    logger.info(f"Peers: {PEERS}")

    # Initialize database
    init_database(DATABASE_URL)

    # Initialize TPM
    tpm_manager = TPMManager(use_simulation=USE_SIMULATED_TPM)

    # Perform initial TPM attestation
    try:
        initial_quote = tpm_manager.collect_quote()
        trust_level = tpm_manager.get_node_trust_level(initial_quote)
        logger.info(f"Initial TPM attestation: {trust_level}")
        await store_tpm_quote(initial_quote, trust_level)
    except Exception as e:
        logger.error(f"TPM initialization failed: {e}")

    # Connect to peer nodes
    await connect_to_peers()

    # Register this node
    await register_node()

    # Start background tasks
    asyncio.create_task(periodic_attestation())
    asyncio.create_task(cleanup_old_data())

    logger.info(f"SFIM Node {NODE_ID} started successfully")


async def connect_to_peers():
    """Connect to peer nodes via WebSocket"""
    for i, peer_url in enumerate(PEERS):
        if i != NODE_ID:
            try:
                ws_url = peer_url.replace('http://', 'ws://') + '/peer'
                websocket = await websockets.connect(ws_url)
                peer_connections[i] = websocket
                logger.info(f"Connected to peer {i}")

                # Start listening to peer messages
                asyncio.create_task(listen_to_peer(i, websocket))
            except Exception as e:
                logger.error(f"Failed to connect to peer {i}: {e}")


async def listen_to_peer(peer_id: int, websocket):
    """Listen to messages from a peer"""
    try:
        async for message in websocket:
            data = json.loads(message)
            await handle_consensus_message(data)
    except Exception as e:
        logger.error(f"Error listening to peer {peer_id}: {e}")
        if peer_id in peer_connections:
            del peer_connections[peer_id]


async def store_tpm_quote(quote, trust_level: str):
    """Store TPM quote in database"""
    try:
        db = SessionLocal()
        pcr_data = json.dumps({k: v.hex() for k, v in quote.pcr_values.items()}).encode()
        tpm_quote = TPMQuote(
            node_id=NODE_ID,
            pcr_values=pcr_data,
            nonce=quote.nonce.hex(),
            signature=quote.signature,
            is_valid=quote.is_valid,
            trust_level=trust_level
        )
        db.add(tpm_quote)
        db.commit()
        db.close()
    except Exception as e:
        logger.error(f"Error storing TPM quote: {e}")


async def register_node():
    """Register this node in the database"""
    try:
        db = SessionLocal()
        existing_node = db.query(NodeModel).filter(NodeModel.node_id == NODE_ID).first()
        if existing_node:
            existing_node.status = 'active'
            existing_node.last_seen = time.time()
        else:
            node = NodeModel(
                node_id=NODE_ID,
                address=f"http://localhost:{PORT}",
                status='active',
                trust_score=100
            )
            db.add(node)
        db.commit()
        db.close()
    except Exception as e:
        logger.error(f"Error registering node: {e}")


def is_primary():
    """Check if this node is the primary for current view"""
    return (consensus_state['view'] % TOTAL_NODES) == NODE_ID


@property
def required_votes():
    """Number of votes required for consensus (2f + 1)"""
    return (2 * ((TOTAL_NODES - 1) // 3)) + 1


async def broadcast_to_peers(message: dict):
    """Broadcast message to all connected peers"""
    message_json = json.dumps(message)

    for node_id, websocket in peer_connections.items():
        try:
            await websocket.send(message_json)
        except Exception as e:
            logger.error(f"Failed to send to peer {node_id}: {e}")


async def broadcast_to_clients(message: dict):
    """Broadcast message to connected WebSocket clients"""
    if connected_clients:
        message_json = json.dumps(message)
        disconnected = []

        for client in connected_clients:
            try:
                await client.send_text(message_json)
            except Exception:
                disconnected.append(client)

        for client in disconnected:
            connected_clients.remove(client)


@app.websocket("/ws")
async def unified_websocket_endpoint(websocket: WebSocket):
    """Unified WebSocket endpoint for all communication"""
    await websocket.accept()
    connected_clients.append(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            message_type = message.get('type')

            if message_type == 'integrity_event':
                await handle_integrity_event(message, websocket)
            elif message_type == 'file_upload':
                await handle_file_upload_event(message)

    except WebSocketDisconnect:
        connected_clients.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")


@app.websocket("/peer")
async def peer_websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for peer-to-peer communication"""
    await websocket.accept()

    try:
        async for message in websocket:
            data = json.loads(message)
            await handle_consensus_message(data)
    except WebSocketDisconnect:
        pass


async def handle_file_upload_event(message, websocket):
    """
    WebSocket handler for file upload events.
    Expects:
      - Initial JSON: {type: 'file_upload', fileName, mimeType, fileSize}
      - Binary frames: file data (may be chunked)
    """
    file_name = message.get("fileName", "unknown")
    mime_type = message.get("mimeType", "application/octet-stream")
    file_size = int(message.get("fileSize", 0))

    # Signal client you are ready for the binary data.
    await websocket.send_text(json.dumps({"type": "file_upload_ready"}))

    file_content = b""
    bytes_received = 0
    while bytes_received < file_size:
        frame = await websocket.receive()
        if "bytes" in frame and frame["bytes"]:
            file_content += frame["bytes"]
            bytes_received += len(frame["bytes"])
        elif "text" in frame:
            # Optional: handle {type: "file_upload_end"} JSON.
            try:
                endmsg = json.loads(frame["text"])
                if endmsg.get("type") == "file_upload_end":
                    break
            except Exception:
                pass

    ### Core upload logic (from your /api/upload endpoint) ###
    db = SessionLocal()
    try:
        # Step 1: Read and hash file
        file_hash = hashlib.sha512(file_content).hexdigest()

        # Step 2: TPM Attestation
        tpm_quote = tpm_manager.collect_quote()
        trust_level = tpm_manager.get_node_trust_level(tpm_quote)
        if trust_level == "untrusted":
            await websocket.send_text(json.dumps({"type": "error", "message": "TPM attestation failed - untrusted node"}))
            return

        # Step 3: Create Merkle Tree
        combined_data = [
            file_hash.encode(),
            tpm_quote.signature,
            f"trust:{trust_level}".encode(),
            f"node:{NODE_ID}".encode()
        ]
        merkle_tree_root = merkle_root(combined_data).hex()

        # Step 4/5: Store file, integrity event, TPM quote
        file_record = FileStorage(
            file_name=file_name,
            file_hash=file_hash,
            file_size=len(file_content),
            mime_type=mime_type,
            file_data=file_content,
            merkle_root=merkle_tree_root,
            node_id=NODE_ID,
            consensus_round=0,
            status='pending'
        )
        db.add(file_record)
        integrity_event = IntegrityEvent(
            merkle_root=merkle_tree_root,
            file_path=file_name,
            file_hash=file_hash,
            node_id=NODE_ID,
            consensus_round=0,
            status='pending'
        )
        db.add(integrity_event)
        tpm_quote_record = TPMQuote(
            node_id=NODE_ID,
            pcr_values=json.dumps({k: v.hex() for k, v in tpm_quote.pcr_values.items()}).encode(),
            nonce=tpm_quote.nonce.hex(),
            signature=tpm_quote.signature,
            is_valid=tpm_quote.is_valid,
            trust_level=trust_level
        )
        db.add(tpm_quote_record)
        db.commit()

        # PBFT consensus
        if is_primary():
            await initiate_consensus(merkle_tree_root)

        await broadcast_to_clients({
            'type': 'file_uploaded',
            'file_name': file_name,
            'merkle_root': merkle_tree_root,
            'trust_level': trust_level,
            'status': 'pending_consensus'
        })

        await websocket.send_text(json.dumps({
            "type": "file_upload_ack",
            "success": True,
            "message": "File uploaded and consensus initiated",
            "file_hash": file_hash,
            "merkle_root": merkle_tree_root,
            "trust_level": trust_level,
            "consensus_status": "pending"
        }))
    except Exception as e:
        logger.error(f"WebSocket file upload failed: {e}")
        db.rollback()
        await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
    finally:
        db.close()

async def handle_integrity_event(message: dict, websocket: WebSocket):
    """Handle integrity event from file agent"""
    merkle_root_val = message.get('merkle_root')

    if is_primary():
        # Initiate PBFT consensus
        await initiate_consensus(merkle_root_val)


async def handle_consensus_message(message: dict):
    """Handle PBFT consensus messages"""
    msg_type = message.get('type')

    if msg_type == 'pre_prepare':
        await handle_pre_prepare(message)
    elif msg_type == 'prepare':
        await handle_prepare(message)
    elif msg_type == 'commit':
        await handle_commit(message)


async def initiate_consensus(merkle_root_val: str):
    """Start PBFT consensus process"""
    if not is_primary():
        return

    consensus_state['sequence_number'] += 1

    # Create PRE-PREPARE message
    message = {
        'type': 'pre_prepare',
        'view': consensus_state['view'],
        'sequence': consensus_state['sequence_number'],
        'digest': merkle_root_val,
        'node_id': NODE_ID,
        'signature': bls_manager.sign(f"pre_prepare:{merkle_root_val}".encode()),
        'timestamp': int(time.time() * 1000)
    }

    logger.info(f"Initiating consensus for digest: {merkle_root_val[:16]}...")
    await broadcast_to_peers(message)


async def handle_pre_prepare(message: dict):
    """Handle PRE-PREPARE message"""
    digest = message['digest']

    # Send PREPARE message
    prepare_msg = {
        'type': 'prepare',
        'view': consensus_state['view'],
        'sequence': message['sequence'],
        'digest': digest,
        'node_id': NODE_ID,
        'signature': bls_manager.sign(f"prepare:{digest}".encode()),
        'timestamp': int(time.time() * 1000)
    }

    await broadcast_to_peers(prepare_msg)
    logger.info(f"Sent PREPARE for digest: {digest[:16]}...")


async def handle_prepare(message: dict):
    """Handle PREPARE message"""
    digest = message['digest']

    if digest not in consensus_state['prepare_messages']:
        consensus_state['prepare_messages'][digest] = []

    consensus_state['prepare_messages'][digest].append(message)

    # Check if we have enough PREPARE messages
    if (len(consensus_state['prepare_messages'][digest]) >= required_votes and
            digest not in consensus_state['prepared_digests']):
        consensus_state['prepared_digests'].add(digest)

        # Send COMMIT message
        commit_msg = {
            'type': 'commit',
            'view': consensus_state['view'],
            'sequence': message['sequence'],
            'digest': digest,
            'node_id': NODE_ID,
            'signature': bls_manager.sign(f"commit:{digest}".encode()),
            'timestamp': int(time.time() * 1000)
        }

        await broadcast_to_peers(commit_msg)
        logger.info(f"Sent COMMIT for digest: {digest[:16]}...")


async def handle_commit(message: dict):
    """Handle COMMIT message"""
    digest = message['digest']

    if digest not in consensus_state['commit_messages']:
        consensus_state['commit_messages'][digest] = []

    consensus_state['commit_messages'][digest].append(message)

    # Check if we have enough COMMIT messages
    if (len(consensus_state['commit_messages'][digest]) >= required_votes and
            digest not in consensus_state['committed_digests']):
        consensus_state['committed_digests'].add(digest)
        logger.info(f"CONSENSUS REACHED for digest: {digest[:16]}...")

        # Execute committed operation
        await execute_consensus_commit(digest, consensus_state['commit_messages'][digest])


async def execute_consensus_commit(digest: str, commit_messages: List[dict]):
    """Execute the committed operation"""
    try:
        db = SessionLocal()

        # Update file storage status
        file_records = db.query(FileStorage).filter(FileStorage.merkle_root == digest).all()
        for file_record in file_records:
            file_record.status = 'committed'
            file_record.consensus_round = consensus_state['sequence_number']

        # Update integrity events
        events = db.query(IntegrityEvent).filter(IntegrityEvent.merkle_root == digest).all()
        signatures = [msg['signature'] for msg in commit_messages]
        aggregated_sig = bls_manager.aggregate(signatures)

        for event in events:
            event.status = 'committed'
            event.bls_signature = aggregated_sig
            event.consensus_round = consensus_state['sequence_number']

        # Create audit log
        audit_log = AuditLog(
            event_type='consensus',
            node_id=NODE_ID,
            message=f'Consensus reached for digest {digest[:16]}',
            details=json.dumps({
                'digest': digest,
                'commit_count': len(commit_messages),
                'consensus_round': consensus_state['sequence_number'],
                'files_committed': len(file_records)
            })
        )
        db.add(audit_log)
        db.commit()
        db.close()

        # Broadcast to clients
        await broadcast_to_clients({
            'type': 'consensus_commit',
            'digest': digest,
            'node_id': NODE_ID,
            'files_committed': len(file_records),
            'timestamp': int(time.time() * 1000)
        })

    except Exception as e:
        logger.error(f"Error executing consensus commit: {e}")


@app.post("/api/upload")
async def upload_file_complete_workflow(
        file: UploadFile = File(...),
        db: Session = Depends(get_db_session)
):
    """Complete file upload workflow with TPM, Merkle tree, and PBFT"""

    try:
        # Step 1: Read and hash file
        file_content = await file.read()
        file_hash = hashlib.sha512(file_content).hexdigest()

        # Step 2: TPM Attestation
        tpm_quote = tpm_manager.collect_quote()
        trust_level = tpm_manager.get_node_trust_level(tpm_quote)

        if trust_level == "untrusted":
            raise HTTPException(status_code=400, detail="TPM attestation failed - untrusted node")

        # Step 3: Create Merkle Tree (combine file hash + TPM quote)
        combined_data = [
            file_hash.encode(),
            tpm_quote.signature,
            f"trust:{trust_level}".encode(),
            f"node:{NODE_ID}".encode()
        ]
        merkle_tree_root = merkle_root(combined_data).hex()

        # Step 4: Store file and create integrity event
        file_record = FileStorage(
            file_name=file.filename or 'unknown',
            file_hash=file_hash,
            file_size=len(file_content),
            mime_type=file.content_type,
            file_data=file_content,
            merkle_root=merkle_tree_root,
            node_id=NODE_ID,
            consensus_round=0,
            status='pending'
        )
        db.add(file_record)

        integrity_event = IntegrityEvent(
            merkle_root=merkle_tree_root,
            file_path=file.filename,
            file_hash=file_hash,
            node_id=NODE_ID,
            consensus_round=0,
            status='pending'
        )
        db.add(integrity_event)

        # Step 5: Store TPM Quote
        tpm_quote_record = TPMQuote(
            node_id=NODE_ID,
            pcr_values=json.dumps({k: v.hex() for k, v in tpm_quote.pcr_values.items()}).encode(),
            nonce=tpm_quote.nonce.hex(),
            signature=tpm_quote.signature,
            is_valid=tpm_quote.is_valid,
            trust_level=trust_level
        )
        db.add(tpm_quote_record)
        db.commit()

        # Step 6: Initiate PBFT Consensus
        if is_primary():
            await initiate_consensus(merkle_tree_root)

        # Step 7: Broadcast to connected clients
        await broadcast_to_clients({
            'type': 'file_uploaded',
            'file_name': file.filename,
            'merkle_root': merkle_tree_root,
            'trust_level': trust_level,
            'status': 'pending_consensus'
        })

        return {
            "success": True,
            "message": "File uploaded and consensus initiated",
            "file_hash": file_hash,
            "merkle_root": merkle_tree_root,
            "trust_level": trust_level,
            "consensus_status": "pending"
        }

    except Exception as e:
        logger.error(f"File upload failed: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/verify")
async def verify_file_complete(file: UploadFile = File(...), db: Session = Depends(get_db_session)):
    """Complete file verification with TPM and consensus check"""

    try:
        # Calculate file hash
        file_content = await file.read()
        file_hash = hashlib.sha512(file_content).hexdigest()

        # Check if file exists
        file_record = db.query(FileStorage).filter(FileStorage.file_hash == file_hash).first()
        integrity_event = db.query(IntegrityEvent).filter(IntegrityEvent.file_hash == file_hash).first()

        if file_record and integrity_event:
            # Get latest TPM quote for validation
            latest_quote = db.query(TPMQuote).filter(
                TPMQuote.node_id == file_record.node_id
            ).order_by(TPMQuote.id.desc()).first()

            return {
                "valid": True,
                "message": "File verified successfully",
                "log": {
                    "id": integrity_event.id,
                    "fileName": file_record.file_name,
                    "hash": file_hash,
                    "status": integrity_event.status,
                    "timestamp": integrity_event.timestamp.isoformat(),
                    "merkle_root": integrity_event.merkle_root,
                    "node_id": integrity_event.node_id,
                    "consensus_round": integrity_event.consensus_round,
                    "trust_level": latest_quote.trust_level if latest_quote else "unknown"
                }
            }
        else:
            # Create mock response for fallback
            return {
                "valid": False,
                "message": "File not found in blockchain",
                "log": {
                    "id": None,
                    "fileName": file.filename,
                    "hash": file_hash,
                    "status": "not_found",
                    "timestamp": time.time(),
                    "merkle_root": None,
                    "node_id": NODE_ID,
                    "consensus_round": 0
                }
            }

    except Exception as e:
        logger.error(f"File verification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Additional API endpoints
@app.get("/api/status")
async def get_status():
    return {
        'node_id': NODE_ID,
        'is_primary': is_primary(),
        'total_nodes': TOTAL_NODES,
        'connected_peers': len(peer_connections),
        'database_url': DATABASE_URL,
        'use_simulated_tpm': USE_SIMULATED_TPM,
        'timestamp': int(time.time() * 1000)
    }


@app.get("/api/files")
async def get_files(limit: int = 50, db: Session = Depends(get_db_session)):
    files = db.query(FileStorage).order_by(FileStorage.id.desc()).limit(limit).all()
    return [file_record.to_dict() for file_record in files]


@app.get("/api/events")
async def get_events(limit: int = 50, db: Session = Depends(get_db_session)):
    events = db.query(IntegrityEvent).order_by(IntegrityEvent.id.desc()).limit(limit).all()
    return [event.to_dict() for event in events]


@app.get("/api/quotes")
async def get_quotes(limit: int = 20, db: Session = Depends(get_db_session)):
    quotes = db.query(TPMQuote).order_by(TPMQuote.id.desc()).limit(limit).all()
    return [quote.to_dict() for quote in quotes]


@app.get("/api/nodes")
async def get_nodes(db: Session = Depends(get_db_session)):
    nodes = db.query(NodeModel).all()
    return [node.to_dict() for node in nodes]


@app.get("/api/logs")
async def get_logs(limit: int = 100, db: Session = Depends(get_db_session)):
    logs = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return [log.to_dict() for log in logs]


# Background tasks
async def periodic_attestation():
    """Periodic TPM attestation"""
    while True:
        try:
            await asyncio.sleep(60)  # Every minute
            quote = tpm_manager.collect_quote()
            trust_level = tpm_manager.get_node_trust_level(quote)
            await store_tpm_quote(quote, trust_level)

            if trust_level == "untrusted":
                logger.error("Periodic TPM attestation failed!")
        except Exception as e:
            logger.error(f"Periodic attestation error: {e}")


async def cleanup_old_data():
    """Clean up old data periodically"""
    while True:
        try:
            await asyncio.sleep(3600)  # Every hour
            db = SessionLocal()

            # Keep only last 1000 audit logs
            old_logs = db.query(AuditLog).order_by(AuditLog.id.desc()).offset(1000)
            for log in old_logs:
                db.delete(log)

            # Keep only last 100 TPM quotes per node
            old_quotes = db.query(TPMQuote).filter(TPMQuote.node_id == NODE_ID).order_by(TPMQuote.id.desc()).offset(100)
            for quote in old_quotes:
                db.delete(quote)

            db.commit()
            db.close()
        except Exception as e:
            logger.error(f"Cleanup error: {e}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
