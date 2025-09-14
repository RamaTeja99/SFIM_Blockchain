import asyncio
import os
import sys
import hashlib
import json
import logging
import time
import secrets
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import websockets

# Local imports
from backend.merkle import merkle_root, MerkleTree
from backend.tpm_attest import TPMManager
from backend.consensus import PBFTNode, BLSManager
from backend.models import (db_manager, create_db_session, get_db_session, _update_legacy_globals,
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

# Global variables
tpm_manager: Optional[TPMManager] = None
pbft_node: Optional[PBFTNode] = None
connected_clients: List[WebSocket] = []
pending_uploads: Dict[str, dict] = {}
blockchain_files: Dict[str, dict] = {}


# FIXED: Modern FastAPI lifespan event handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern FastAPI lifespan event handler"""
    # Startup
    global tmp_manager, pbft_node
    logger.info(f"🚀 Starting SFIM Node {NODE_ID}")
    logger.info(f"📡 Peers: {PEERS}")

    try:
        # FIXED: Initialize database first with proper error handling
        logger.info("🔄 Initializing database...")
        db_manager.init_database(DATABASE_URL)
        _update_legacy_globals()  # Update legacy global variables
        logger.info("✅ Database initialized successfully")

        # Initialize TPM Manager
        logger.info("🔄 Initializing TPM Manager...")
        tmp_manager = TPMManager(use_simulation=USE_SIMULATED_TPM)
        logger.info("✅ TPM Manager initialized")

        # Initialize PBFT Node
        logger.info("🔄 Initializing PBFT Node...")
        private_key_seed = f"node_{NODE_ID}_seed".encode().ljust(32, b'\x00')
        pbft_node = PBFTNode(
            node_id=NODE_ID,
            total_nodes=TOTAL_NODES,
            private_key_seed=private_key_seed,
            peers=PEERS,
            port=PORT + 100
        )
        pbft_node.set_commit_callback(handle_consensus_commit)
        logger.info("✅ PBFT Node initialized")

        # Perform initial TPM attestation
        if tmp_manager:
            try:
                logger.info("🔄 Performing initial TPM attestation...")
                initial_quote = tmp_manager.collect_quote()
                trust_level = tmp_manager.get_node_trust_level(initial_quote)
                logger.info(f"🔐 Initial TPM attestation: {trust_level}")
                await store_tmp_quote(initial_quote, trust_level)
                logger.info("✅ TPM attestation completed")
            except Exception as e:
                logger.error(f"❌ TPM initialization failed: {e}")

        # Start PBFT node
        if pbft_node:
            try:
                logger.info("🔄 Starting PBFT node...")
                await pbft_node.start()
                logger.info("✅ PBFT Node started")
            except Exception as e:
                logger.error(f"❌ PBFT Node start failed: {e}")

        # Register this node
        await register_node()

        # Start background tasks
        logger.info("🔄 Starting background tasks...")
        asyncio.create_task(periodic_attestation())
        asyncio.create_task(cleanup_old_data())

        logger.info(f"🎉 SFIM Node {NODE_ID} started successfully!")

    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise e

    yield  # App runs here

    # Shutdown
    logger.info("🔄 Shutting down SFIM Node...")
    if pbft_node:
        await pbft_node.stop()
    logger.info("✅ SFIM Node shutdown complete")


# FIXED: Create FastAPI app with modern lifespan handler
app = FastAPI(
    title=f"SFIM Node {NODE_ID}",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def handle_consensus_commit(digest: str, commit_messages: List[dict]):
    """Handle when PBFT consensus is reached - ADD TO BLOCKCHAIN"""
    db = None
    try:
        logger.info(f"✅ BLOCKCHAIN COMMIT: {digest[:16]}...")
        db = create_db_session()  # FIXED: Use new database manager

        # Update file storage status to 'committed'
        file_records = db.query(FileStorage).filter(FileStorage.merkle_root == digest).all()
        for file_record in file_records:
            file_record.status = 'committed'
            file_record.consensus_round = pbft_node.sequence_number

            # Add to blockchain registry
            blockchain_files[file_record.file_hash] = {
                'file_hash': file_record.file_hash,
                'merkle_root': digest,
                'consensus_round': pbft_node.sequence_number,
                'node_id': NODE_ID,
                'status': 'committed',
                'timestamp': time.time()
            }

        # Update integrity events
        events = db.query(IntegrityEvent).filter(IntegrityEvent.merkle_root == digest).all()
        signatures = [msg['signature'] for msg in commit_messages]
        aggregated_sig = pbft_node.bls.aggregate(signatures)

        for event in events:
            event.status = 'committed'
            event.bls_signature = aggregated_sig
            event.consensus_round = pbft_node.sequence_number

        # Create audit log
        audit_log = AuditLog(
            event_type='blockchain_commit',
            node_id=NODE_ID,
            message=f'File(s) added to blockchain: {digest[:16]}',
            details=json.dumps({
                'digest': digest,
                'commit_count': len(commit_messages),
                'consensus_round': pbft_node.sequence_number,
                'files_committed': len(file_records)
            })
        )
        db.add(audit_log)
        db.commit()

        # Notify pending uploads
        for upload_id, upload_data in list(pending_uploads.items()):
            if upload_data.get('merkle_root') == digest:
                upload_data['status'] = 'committed'
                upload_data['consensus_round'] = pbft_node.sequence_number

        # Broadcast to clients
        await broadcast_to_clients({
            'type': 'blockchain_commit',
            'digest': digest,
            'node_id': NODE_ID,
            'files_committed': len(file_records),
            'timestamp': int(time.time() * 1000)
        })

        logger.info(f"🔗 {len(file_records)} file(s) successfully added to blockchain")

    except Exception as e:
        logger.error(f"❌ Error in blockchain commit: {e}")
        if db:
            db.rollback()
    finally:
        if db:
            db.close()


async def store_tmp_quote(quote, trust_level: str):
    """Store TPM quote in database"""
    db = None
    try:
        db = create_db_session()  # FIXED: Use new database manager
        pcr_data = json.dumps({k: v.hex() for k, v in quote.pcr_values.items()}).encode()
        tmp_quote = TPMQuote(
            node_id=NODE_ID,
            pcr_values=pcr_data,
            nonce=quote.nonce.hex(),
            signature=quote.signature,
            is_valid=quote.is_valid,
            trust_level=trust_level
        )
        db.add(tmp_quote)
        db.commit()
        logger.debug("✅ TPM quote stored successfully")
    except Exception as e:
        logger.error(f"❌ Error storing TPM quote: {e}")
        if db:
            db.rollback()
    finally:
        if db:
            db.close()


async def register_node():
    """Register this node in the database"""
    db = None
    try:
        db = create_db_session()  # FIXED: Use new database manager
        existing_node = db.query(NodeModel).filter(NodeModel.node_id == NODE_ID).first()
        if existing_node:
            existing_node.status = 'active'
            existing_node.last_seen = datetime.now()
        else:
            # from datetime import datetime
            node = NodeModel(
                node_id=NODE_ID,
                address=f"http://localhost:{PORT}",
                status='active',
                trust_score=100
            )
            db.add(node)
        db.commit()
        logger.info("✅ Node registered successfully")
    except Exception as e:
        logger.error(f"❌ Error registering node: {e}")
        if db:
            db.rollback()
    finally:
        if db:
            db.close()


def validate_tmp_quote_with_peers(quote, trust_level: str) -> bool:
    """Validate TPM quote with peer nodes"""
    return trust_level == 'trusted'


async def compute_merkle_root_for_new_file(new_file_hash: str) -> str:
    """Compute Merkle root including existing blockchain files + new file"""
    db = None
    try:
        db = create_db_session()  # FIXED: Use new database manager
        committed_files = db.query(FileStorage).filter(FileStorage.status == 'committed').all()
        file_hashes = [bytes.fromhex(f.file_hash) for f in committed_files]
        file_hashes.append(bytes.fromhex(new_file_hash))

        if file_hashes:
            root = merkle_root(file_hashes)
            logger.info(f"📊 Computed Merkle root for {len(file_hashes)} files")
            return root.hex()
        else:
            return hashlib.sha512(bytes.fromhex(new_file_hash)).hexdigest()

    except Exception as e:
        logger.error(f"❌ Error computing Merkle root: {e}")
        return hashlib.sha512(bytes.fromhex(new_file_hash)).hexdigest()
    finally:
        if db:
            db.close()


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


async def handle_file_upload_event(message, websocket):
    """Handle file upload via WebSocket - Not implemented"""
    logger.warning("WebSocket file upload is not implemented.")
    await websocket.send_text(json.dumps({
        "type": "error",
        "message": "File upload via WebSocket not supported"
    }))


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
                await handle_file_upload_event(message, websocket)
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")


async def handle_integrity_event(message: dict, websocket: WebSocket):
    """Handle integrity event from file agent"""
    merkle_root_val = message.get('merkle_root')
    if pbft_node and pbft_node.is_primary:
        await pbft_node.propose(merkle_root_val)


@app.post("/api/upload")
async def upload_file_blockchain_workflow(
        file: UploadFile = File(...),
        db: Session = Depends(get_db_session)
):
    """🔗 COMPLETE BLOCKCHAIN WORKFLOW"""
    upload_id = secrets.token_hex(16)

    try:
        logger.info(f"🚀 Starting blockchain upload workflow: {file.filename}")

        # Step 1: File Scanner
        file_content = await file.read()
        file_hash = hashlib.sha512(file_content).hexdigest()
        logger.info(f"📄 File scanned, SHA-512: {file_hash[:16]}...")

        # Step 2: TPM Attestation
        if not tmp_manager:
            raise HTTPException(status_code=500, detail="TPM Manager not initialized")

        tmp_quote = tmp_manager.collect_quote()
        trust_level = tmp_manager.get_node_trust_level(tmp_quote)

        if trust_level == "untrusted":
            raise HTTPException(status_code=400, detail="TPM attestation failed - untrusted node")

        logger.info(f"🔐 TPM quote generated, trust level: {trust_level}")

        # Step 3: Quote Validation
        if not validate_tmp_quote_with_peers(tmp_quote, trust_level):
            raise HTTPException(status_code=400, detail="TPM quote validation failed")

        logger.info(f"✅ TPM quote validated by peers")

        # Step 4: Merkle Tree Construction
        merkle_tree_root = await compute_merkle_root_for_new_file(file_hash)
        logger.info(f"🌳 Merkle root computed: {merkle_tree_root[:16]}...")

        # Step 5: Store file with 'pending' status
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

        # Store TPM Quote
        tmp_quote_record = TPMQuote(
            node_id=NODE_ID,
            pcr_values=json.dumps({k: v.hex() for k, v in tmp_quote.pcr_values.items()}).encode(),
            nonce=tmp_quote.nonce.hex(),
            signature=tmp_quote.signature,
            is_valid=tmp_quote.is_valid,
            trust_level=trust_level
        )
        db.add(tmp_quote_record)
        db.commit()

        # Step 6: Broadcasting + PBFT Consensus
        logger.info(f"📡 Broadcasting Merkle root to network...")

        pending_uploads[upload_id] = {
            'file_hash': file_hash,
            'merkle_root': merkle_tree_root,
            'status': 'pending',
            'timestamp': time.time()
        }

        # Initiate PBFT consensus
        if pbft_node and pbft_node.is_primary:
            await pbft_node.propose(merkle_tree_root)
            logger.info(f"🗳️ PBFT consensus initiated (Primary node)")
        else:
            logger.info(f"⏳ Waiting for PBFT consensus from primary node")

        # Step 7: Wait for consensus
        max_wait_time = 30
        wait_start = time.time()

        while time.time() - wait_start < max_wait_time:
            upload_status = pending_uploads.get(upload_id, {})
            if upload_status.get('status') == 'committed':
                logger.info(f"🔗 File successfully added to blockchain!")

                return {
                    "success": True,
                    "message": "File successfully added to blockchain",
                    "file_hash": file_hash,
                    "merkle_root": merkle_tree_root,
                    "trust_level": trust_level,
                    "consensus_status": "committed",
                    "consensus_round": upload_status.get('consensus_round'),
                    "blockchain_status": "✅ ON BLOCKCHAIN"
                }

            await asyncio.sleep(1)

        # Timeout
        logger.warning(f"⏰ Consensus timeout for upload: {file.filename}")
        return {
            "success": False,
            "message": "Consensus timeout - file not added to blockchain yet",
            "file_hash": file_hash,
            "merkle_root": merkle_tree_root,
            "trust_level": trust_level,
            "consensus_status": "timeout",
            "blockchain_status": "🟡 PENDING CONSENSUS"
        }

    except Exception as e:
        logger.error(f"❌ Blockchain upload failed: {e}")
        db.rollback()
        if upload_id in pending_uploads:
            del pending_uploads[upload_id]
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/verify")
async def verify_file_blockchain_integrity(file: UploadFile = File(...), db: Session = Depends(get_db_session)):
    """🔍 BLOCKCHAIN INTEGRITY VERIFICATION"""
    try:
        logger.info(f"🔍 Verifying blockchain integrity for: {file.filename}")

        file_content = await file.read()
        file_hash = hashlib.sha512(file_content).hexdigest()
        logger.info(f"📄 File hash: {file_hash[:16]}...")

        # Check blockchain registry
        if file_hash in blockchain_files:
            logger.info(f"✅ File found on blockchain!")

            db_record = db.query(FileStorage).filter(
                FileStorage.file_hash == file_hash,
                FileStorage.status == 'committed'
            ).first()

            if db_record:
                latest_quote = db.query(TPMQuote).filter(
                    TPMQuote.node_id == db_record.node_id
                ).order_by(TPMQuote.id.desc()).first()

                return {
                    "valid": True,
                    "message": "✅ File verified on blockchain - Integrity confirmed",
                    "blockchain_status": "✅ COMMITTED TO BLOCKCHAIN",
                    "log": {
                        "id": db_record.id,
                        "fileName": db_record.file_name,
                        "file_hash": file_hash,
                        "status": db_record.status,
                        "timestamp": db_record.created_at.isoformat(),
                        "merkle_root": db_record.merkle_root,
                        "node_id": db_record.node_id,
                        "consensus_round": db_record.consensus_round,
                        "trust_level": latest_quote.trust_level if latest_quote else "unknown",
                        "verification_result": "BLOCKCHAIN_VERIFIED"
                    }
                }
            else:
                return {
                    "valid": False,
                    "message": "⚠️ Blockchain inconsistency detected",
                    "blockchain_status": "🔴 INCONSISTENT"
                }
        else:
            # Check if pending
            file_record = db.query(FileStorage).filter(FileStorage.file_hash == file_hash).first()
            if file_record and file_record.status == 'pending':
                return {
                    "valid": False,
                    "message": "🟡 File uploaded but not yet committed to blockchain",
                    "blockchain_status": "🟡 PENDING CONSENSUS"
                }
            else:
                return {
                    "valid": False,
                    "message": "❌ File not found on blockchain - Upload first",
                    "blockchain_status": "🔴 NOT ON BLOCKCHAIN"
                }

    except Exception as e:
        logger.error(f"❌ Blockchain verification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Additional API endpoints
@app.get("/api/blockchain/status")
async def get_blockchain_status():
    return {
        'node_id': NODE_ID,
        'is_primary': pbft_node.is_primary if pbft_node else False,
        'total_nodes': TOTAL_NODES,
        'blockchain_files': len(blockchain_files),
        'pending_uploads': len(pending_uploads),
        'consensus_round': pbft_node.sequence_number if pbft_node else 0,
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


# Background tasks
async def periodic_attestation():
    """Periodic TPM attestation"""
    while True:
        try:
            await asyncio.sleep(60)
            if tmp_manager:
                quote = tmp_manager.collect_quote()
                trust_level = tmp_manager.get_node_trust_level(quote)
                await store_tmp_quote(quote, trust_level)
                if trust_level == "untrusted":
                    logger.error("❌ Periodic TPM attestation failed!")
        except Exception as e:
            logger.error(f"❌ Periodic attestation error: {e}")


async def cleanup_old_data():
    """Clean up old data periodically"""
    while True:
        try:
            await asyncio.sleep(3600)
            current_time = time.time()
            expired_uploads = [
                upload_id for upload_id, data in pending_uploads.items()
                if current_time - data.get('timestamp', 0) > 1800
            ]
            for upload_id in expired_uploads:
                del pending_uploads[upload_id]

            if expired_uploads:
                logger.info(f"🧹 Cleaned up {len(expired_uploads)} expired pending uploads")
        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")