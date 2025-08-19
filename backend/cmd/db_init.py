import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.models import init_database, engine, Base
from backend.models import IntegrityEvent, TPMQuote, Node, AuditLog


def create_tables():
    """Create all database tables"""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully!")


def seed_data():
    """Insert sample data for testing"""
    from backend.models import SessionLocal
    from datetime import datetime

    print("Seeding sample data...")

    db = SessionLocal()
    try:
        # Add sample nodes
        nodes = [
            Node(node_id=0, address="ws://node0:7000", status="active"),
            Node(node_id=1, address="ws://node1:7001", status="active"),
            Node(node_id=2, address="ws://node2:7002", status="active"),
            Node(node_id=3, address="ws://node3:7003", status="active"),
        ]

        for node in nodes:
            db.add(node)

        # Add sample integrity event
        event = IntegrityEvent(
            merkle_root="a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
            file_path="/watched/sample.txt",
            file_hash="sha512_hash_here",
            node_id=0,
            consensus_round=1,
            status="committed"
        )
        db.add(event)

        # Add sample audit log
        log = AuditLog(
            event_type="system_start",
            message="SFIM system initialized",
            severity="info"
        )
        db.add(log)

        db.commit()
        print("Sample data seeded successfully!")

    except Exception as e:
        print(f"Error seeding data: {e}")
        db.rollback()
    finally:
        db.close()


def main():
    """Main initialization function"""
    database_url = os.getenv('SFIM_DB', 'sqlite:///sfim_audit.db')
    print(f"Initializing database: {database_url}")

    # Initialize database
    init_database(database_url)

    # Create tables
    create_tables()

    # Optionally seed data
    if len(sys.argv) > 1 and sys.argv[1] == "--seed":
        seed_data()

    print("Database initialization complete!")


if __name__ == "__main__":
    main()