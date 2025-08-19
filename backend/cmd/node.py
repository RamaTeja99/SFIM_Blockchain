import asyncio
import os
import sys
import json
import logging
import time
import secrets
from pathlib import Path
from typing import List, Dict

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import websockets

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.consensus import PBFTNode, Message
from backend.tpm_attest import TPMManager, AttestationVerifier
from backend.models import (init_database, get_db_session, SessionLocal,
                            IntegrityEvent, TPMQuote, Node as NodeModel, AuditLog)

# Configuration
NODE_ID = int(os.getenv('NODE_ID', 0))
PORT = int(os.getenv('PORT', 7000))
TOTAL_NODES = int(os.getenv('TOTAL_NODES', 4))
PEERS = os.getenv('PEERS', '').split(',') if os.getenv('PEERS') else []
DATABASE_URL = os.getenv('SFIM_DB', 'sqlite:///sfim_audit.db')
USE_SIMULATED_TPM = os.getenv('USE_SIMULATED_TPM', 'true').lower() == 'true'

# Generate deterministic private key for each node
PRIVATE_KEY_SEED = secrets.token_bytes(32) if NODE_ID == 0 else f"node_{NODE_ID}_seed".encode().ljust(32, b'\x00')

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(f"PBFTNode-{NODE_ID}")

# Global objects
app = FastAPI(title=f"SFIM Node {NODE_ID}", version="1.0.0")
pbft_node: PBFTNode = None
tpm_manager: TPMManager = None
attestation_verifier: AttestationVerifier = None
connected_clients: List[WebSocket] = []

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Initialize node on startup"""
    global pbft_node, tpm_manager, attestation_verifier

    logger.info(f"Starting PBFT Node {NODE_ID}")
    logger.info(f"Total nodes: {TOTAL_NODES}")
    logger.info(f"Peers: {PEERS}")
    logger.info(f"Database: {DATABASE_URL}")

    # Initialize database
    init_database(DATABASE_URL)

    # Initialize TPM
    tmp_manager = TPMManager(use_simulation=USE_SIMULATED_TPM)
    attestation_verifier = AttestationVerifier()

    # Perform initial attestation
    try:
        initial_quote = tpm_manager.collect_quote()
        trust_level = tpm_manager.get_node_trust_level(initial_quote)

        if trust_level == "untrusted":
            logger.error("Initial TPM attestation failed!")
            raise RuntimeError("Node failed TPM attestation")

        logger.info(f"Initial TPM attestation: {trust_level}")

        # Store attestation in database
        await store_tpm_quote(initial_quote, trust_level)

    except Exception as e:
        logger.error(f"TPM initialization failed: {e}")
        if not USE_SIMULATED_TPM:
            raise

    # Initialize PBFT node
    pbft_node = PBFTNode(
        node_id=NODE_ID,
        total_nodes=TOTAL_NODES,
        private_key_seed=PRIVATE_KEY_SEED,
        peers=PEERS,
        port=PORT + 1000  # Use different port for PBFT internal communication
    )

    # Set commit callback
    pbft_node.set_commit_callback(handle_consensus_commit)

    # Start PBFT node
    await pbft_node.start()

    # Register node in database
    await register_node()

    # Start periodic tasks
    asyncio.create_task(periodic_attestation())
    asyncio.create_task(cleanup_old_data())

    logger.info(f"PBFT Node {NODE_ID} started successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info(f"Shutting down PBFT Node {NODE_ID}")

    if pbft_node:
        await pbft_node.stop()

    # Close all WebSocket connections
    for client in connected_clients:
        await client.close()


async def store_tpm_quote(quote, trust_level: str):
    """Store TPM quote in database"""
    try:
        db = SessionLocal()

        # Serialize PCR values
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

        # Check if node already exists
        existing_node = db.query(NodeModel).filter(NodeModel.node_id == NODE_ID).first()

        if existing_node:
            # Update existing node
            existing_node.status = 'active'
            existing_node.last_seen = time.time()
        else:
            # Create new node
            node = NodeModel(
                node_id=NODE_ID,
                address=f"ws://node{NODE_ID}:{PORT}",
                status='active',
                trust_score=100
            )
            db.add(node)

        db.commit()
        db.close()

    except Exception as e:
        logger.error(f"Error registering node: {e}")


async def handle_consensus_commit(digest: str, commit_messages: List[Message]):
    """Handle successful consensus commit"""
    try:
        logger.info(f"Consensus reached for digest: {digest[:16]}...")

        # Store in database
        db = SessionLocal()

        # Aggregate signatures
        signatures = [msg.signature for msg in commit_messages]
        aggregated_sig = pbft_node.bls.aggregate(signatures)

        event = IntegrityEvent(
            merkle_root=digest,
            bls_signature=aggregated_sig,
            node_id=NODE_ID,
            consensus_round=pbft_node.sequence_number,
            status='committed'
        )

        db.add(event)

        # Log the event
        audit_log = AuditLog(
            event_type='consensus',
            node_id=NODE_ID,
            message=f'Consensus reached for digest {digest[:16]}',
            details=json.dumps({
                'digest': digest,
                'commit_count': len(commit_messages),
                'consensus_round': pbft_node.sequence_number
            })
        )

        db.add(audit_log)
        db.commit()
        db.close()

        # Broadcast to connected clients
        await broadcast_to_clients({
            'type': 'consensus_commit',
            'digest': digest,
            'node_id': NODE_ID,
            'timestamp': int(time.time() * 1000)
        })

    except Exception as e:
        logger.error(f"Error handling consensus commit: {e}")


async def periodic_attestation():
    """Perform periodic TPM attestation"""
    while True:
        try:
            await asyncio.sleep(60)  # Every minute

            quote = tpm_manager.collect_quote()
            trust_level = tpm_manager.get_node_trust_level(quote)

            await store_tpm_quote(quote, trust_level)

            if trust_level == "untrusted":
                logger.error("Periodic TPM attestation failed!")
                # Node should quarantine itself

        except Exception as e:
            logger.error(f"Periodic attestation error: {e}")


async def cleanup_old_data():
    """Clean up old database records"""
    while True:
        try:
            await asyncio.sleep(3600)  # Every hour

            db = SessionLocal()

            # Delete old audit logs (keep last 1000)
            old_logs = db.query(AuditLog).order_by(AuditLog.id.desc()).offset(1000)
            for log in old_logs:
                db.delete(log)

            # Delete old TPM quotes (keep last 100 per node)
            old_quotes = db.query(TPMQuote).filter(TPMQuote.node_id == NODE_ID).order_by(TPMQuote.id.desc()).offset(100)
            for quote in old_quotes:
                db.delete(quote)

            db.commit()
            db.close()

        except Exception as e:
            logger.error(f"Cleanup error: {e}")


async def broadcast_to_clients(message: dict):
    """Broadcast message to all connected WebSocket clients"""
    if connected_clients:
        message_json = json.dumps(message)
        disconnected = []

        for client in connected_clients:
            try:
                await client.send_text(message_json)
            except:
                disconnected.append(client)

        # Remove disconnected clients
        for client in disconnected:
            connected_clients.remove(client)


# WebSocket endpoints
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint for client connections"""
    await websocket.accept()
    connected_clients.append(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get('type') == 'integrity_event':
                # Handle integrity event from agent
                digest = message.get('merkle_root', '')

                if pbft_node and pbft_node.is_primary:
                    await pbft_node.propose(digest)
                    logger.info(f"Proposed new integrity event: {digest[:16]}...")

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)


@app.websocket("/feed")
async def feed_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time data feed"""
    await websocket.accept()

    try:
        while True:
            # Send recent events
            db = SessionLocal()

            events = db.query(IntegrityEvent).order_by(IntegrityEvent.id.desc()).limit(50).all()
            quotes = db.query(TPMQuote).order_by(TPMQuote.id.desc()).limit(10).all()

            feed_data = {
                'type': 'feed_update',
                'events': [event.to_dict() for event in events],
                'quotes': [quote.to_dict() for quote in quotes],
                'timestamp': int(time.time() * 1000)
            }

            await websocket.send_text(json.dumps(feed_data))
            db.close()

            await asyncio.sleep(2)  # Update every 2 seconds

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Feed WebSocket error: {e}")


# REST API endpoints
@app.get("/api/status")
async def get_status():
    """Get node status"""
    return {
        'node_id': NODE_ID,
        'is_primary': pbft_node.is_primary if pbft_node else False,
        'total_nodes': TOTAL_NODES,
        'connected_peers': len(pbft_node.connections) if pbft_node else 0,
        'database_url': DATABASE_URL,
        'use_simulated_tpm': USE_SIMULATED_TPM,
        'timestamp': int(time.time() * 1000)
    }


@app.get("/api/events")
async def get_events(limit: int = 50, db=Depends(get_db_session)):
    """Get recent integrity events"""
    events = db.query(IntegrityEvent).order_by(IntegrityEvent.id.desc()).limit(limit).all()
    return [event.to_dict() for event in events]


@app.get("/api/quotes")
async def get_quotes(limit: int = 20, db=Depends(get_db_session)):
    """Get recent TPM quotes"""
    quotes = db.query(TPMQuote).order_by(TPMQuote.id.desc()).limit(limit).all()
    return [quote.to_dict() for quote in quotes]


@app.get("/api/nodes")
async def get_nodes(db=Depends(get_db_session)):
    """Get all nodes"""
    nodes = db.query(NodeModel).all()
    return [node.to_dict() for node in nodes]


@app.get("/api/logs")
async def get_logs(limit: int = 100, db=Depends(get_db_session)):
    """Get audit logs"""
    logs = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return [log.to_dict() for log in logs]


@app.post("/api/attestation/challenge")
async def attestation_challenge():
    """Trigger manual attestation challenge"""
    try:
        quote = tpm_manager.collect_quote()
        trust_level = tpm_manager.get_node_trust_level(quote)

        await store_tpm_quote(quote, trust_level)

        return {
            'success': True,
            'trust_level': trust_level,
            'is_valid': quote.is_valid,
            'timestamp': quote.timestamp
        }
    except Exception as e:
        logger.error(f"Attestation challenge failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def main():
    """Main entry point"""
    logger.info(f"Starting SFIM Node {NODE_ID} on port {PORT}")

    uvicorn.run(
        "backend.cmd.node:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        reload=False
    )


if __name__ == "__main__":
    main()