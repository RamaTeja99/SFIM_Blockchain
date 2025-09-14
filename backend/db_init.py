import sys
import os
from pathlib import Path

# FIXED: Import the new database manager
try:
    from models import db_manager, IntegrityEvent, AuditLog, NodeModel

    print("✅ Using new database manager")
except ImportError:
    # Fallback for different import paths
    try:
        from backend.models import db_manager, IntegrityEvent, AuditLog, NodeModel

        print("✅ Using new database manager (backend)")
    except ImportError as e:
        print(f"❌ Import error: {e}")
        sys.exit(1)


def create_tables(database_url):
    """Create all database tables"""
    print("Creating database tables...")
    db_manager.init_database(database_url)
    print("Tables created successfully!")


def seed_data():
    """Insert sample data for testing - FIXED: Use new database manager"""
    print("Seeding sample data...")

    # FIXED: Use db_manager to get a session instead of SessionLocal
    db = db_manager.get_session()

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
                print(f"➕ Added node {node.node_id}")
            else:
                print(f"✅ Node {node.node_id} already exists")

        # Create sample integrity event
        existing_event = db.query(IntegrityEvent).filter(
            IntegrityEvent.merkle_root == "a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456"
        ).first()

        if not existing_event:
            sample_event = IntegrityEvent(
                merkle_root="a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
                file_path="/watched/sample.txt",
                file_hash="sha512_hash_here",
                node_id=0,
                consensus_round=1,
                status="committed"
            )
            db.add(sample_event)
            print("➕ Added sample integrity event")
        else:
            print("✅ Sample integrity event already exists")

        # Create audit log
        existing_log = db.query(AuditLog).filter(
            AuditLog.event_type == "system_start",
            AuditLog.message == "SFIM system initialized"
        ).first()

        if not existing_log:
            log = AuditLog(
                event_type="system_start",
                message="SFIM system initialized",
                severity="info"
            )
            db.add(log)
            print("➕ Added system start audit log")
        else:
            print("✅ System start audit log already exists")

        db.commit()
        print("✅ Sample data seeded successfully!")

    except Exception as e:
        print(f"❌ Error seeding data: {e}")
        db.rollback()
        raise e
    finally:
        db.close()


def main():
    database_url = os.getenv('SFIM_DB', 'sqlite:///./data/sfim_audit.db')
    print(f"Initializing database: {database_url}")

    # Ensure data directory exists
    if database_url.startswith('sqlite:'):
        db_path = database_url.replace('sqlite:///', '')
        data_dir = os.path.dirname(db_path)
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
            print(f"✅ Ensured data directory exists: {data_dir}")

    # Create tables
    create_tables(database_url)

    # Seed data if requested
    if len(sys.argv) > 1 and sys.argv[1] == "--seed":
        seed_data()

    print("🎉 Database initialization complete!")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        sys.exit(1)