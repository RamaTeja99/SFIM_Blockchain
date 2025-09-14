import sys
import os
from pathlib import Path

# Local imports
from backend.models import init_database, SessionLocal, IntegrityEvent, AuditLog, NodeModel


def create_tables(database_url):
    """Create all database tables"""
    print("Creating database tables...")
    init_database(database_url)
    print("Tables created successfully!")


def seed_data():
    """Insert sample data for testing"""
    from backend.models import SessionLocal

    print("Seeding sample data...")
    db = SessionLocal()
    try:
        # Create sample nodes
        nodes = [
            NodeModel(node_id=0, address="http://localhost:7000", status="active"),
            NodeModel(node_id=1, address="http://localhost:7001", status="active"),
            NodeModel(node_id=2, address="http://localhost:7002", status="active"),
            NodeModel(node_id=3, address="http://localhost:7003", status="active"),
        ]

        for node in nodes:
            existing = db.query(NodeModel).filter(NodeModel.node_id == node.node_id).first()
            if not existing:
                db.add(node)

        # Create sample integrity event
        sample_event = IntegrityEvent(
            merkle_root="a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
            file_path="/watched/sample.txt",
            file_hash="sha512_hash_here",
            node_id=0,
            consensus_round=1,
            status="committed"
        )
        db.add(sample_event)

        # Create audit log
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
    database_url = os.getenv('SFIM_DB', 'sqlite:///./data/sfim_audit.db')
    print(f"Initializing database: {database_url}")

    # Ensure data directory exists
    if database_url.startswith('sqlite:'):
        db_path = database_url.replace('sqlite:///', '')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    create_tables(database_url)

    if len(sys.argv) > 1 and sys.argv[1] == "--seed":
        seed_data()

    print("Database initialization complete!")


if __name__ == "__main__":
    main()
