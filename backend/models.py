import os
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Integer, String, LargeBinary, DateTime, Boolean, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import Engine

Base = declarative_base()

# Database configuration - use relative paths
DATABASE_URL = os.getenv('SFIM_DB', 'sqlite:///./data/sfim_audit.db')


class IntegrityEvent(Base):
    """Database model for file integrity events"""
    __tablename__ = 'integrity_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    merkle_root = Column(String(128), nullable=False, index=True)
    file_path = Column(String(512), nullable=True)
    file_hash = Column(String(128), nullable=True)
    bls_signature = Column(String(256), nullable=True)
    node_id = Column(Integer, nullable=False)
    consensus_round = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default='pending')
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'merkle_root': self.merkle_root,
            'file_path': self.file_path,
            'file_hash': self.file_hash,
            'bls_signature': self.bls_signature,
            'node_id': self.node_id,
            'consensus_round': self.consensus_round,
            'status': self.status,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class FileStorage(Base):
    """Database model for storing uploaded files"""
    __tablename__ = 'file_storage'

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String(512), nullable=False)
    file_hash = Column(String(128), nullable=False, unique=True, index=True)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(128), nullable=True)
    file_data = Column(LargeBinary, nullable=False)
    merkle_root = Column(String(128), nullable=False, index=True)
    node_id = Column(Integer, nullable=False)
    consensus_round = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default='pending')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'file_name': self.file_name,
            'file_hash': self.file_hash,
            'file_size': self.file_size,
            'mime_type': self.mime_type,
            'merkle_root': self.merkle_root,
            'node_id': self.node_id,
            'consensus_round': self.consensus_round,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class TPMQuote(Base):
    """Database model for TPM attestation quotes"""
    __tablename__ = 'tmp_quotes'

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_id = Column(Integer, nullable=False, index=True)
    pcr_values = Column(LargeBinary, nullable=False)
    nonce = Column(String(64), nullable=False)
    signature = Column(LargeBinary, nullable=False)
    is_valid = Column(Boolean, nullable=False, default=False)
    trust_level = Column(String(32), nullable=False, default='unknown')
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'node_id': self.node_id,
            'nonce': self.nonce,
            'is_valid': self.is_valid,
            'trust_level': self.trust_level,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class NodeModel(Base):
    """Database model for network nodes"""
    __tablename__ = 'nodes'

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, nullable=False, unique=True, index=True)
    address = Column(String(256), nullable=False)
    public_key = Column(String(512), nullable=True)
    status = Column(String(32), nullable=False, default='active')
    last_seen = Column(DateTime, nullable=True)
    last_attestation = Column(DateTime, nullable=True)
    trust_score = Column(Integer, nullable=False, default=100)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'node_id': self.node_id,
            'address': self.address,
            'public_key': self.public_key,
            'status': self.status,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'last_attestation': self.last_attestation.isoformat() if self.last_attestation else None,
            'trust_score': self.trust_score,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class AuditLog(Base):
    """Database model for system audit logs"""
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(64), nullable=False, index=True)
    node_id = Column(Integer, nullable=True)
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)
    severity = Column(String(16), nullable=False, default='info')
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'event_type': self.event_type,
            'node_id': self.node_id,
            'message': self.message,
            'details': self.details,
            'severity': self.severity,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }


# Database setup
def create_engine_and_session(database_url: str = None) -> tuple[Engine, sessionmaker]:
    """Create database engine and session factory"""
    if database_url is None:
        database_url = DATABASE_URL

    # Ensure data directory exists
    if database_url.startswith('sqlite:'):
        db_path = database_url.replace('sqlite:///', '')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # Configure engine
    if database_url.startswith('sqlite'):
        engine = create_engine(
            database_url,
            echo=False,
            connect_args={"check_same_thread": False}
        )
    else:
        engine = create_engine(database_url, echo=False)

    # Create session factory
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine
    )

    return engine, SessionLocal


# Global database objects
engine: Optional[Engine] = None
SessionLocal: Optional[sessionmaker] = None


def init_database(database_url: str = None):
    """Initialize database connection and create tables"""
    global engine, SessionLocal
    engine, SessionLocal = create_engine_and_session(database_url)

    # Create all tables
    Base.metadata.create_all(bind=engine)
    print(f"Database initialized: {database_url or DATABASE_URL}")


def get_db_session():
    """Get database session for dependency injection"""
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
