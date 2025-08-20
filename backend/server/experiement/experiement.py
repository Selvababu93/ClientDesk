import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.auth import get_agent_by_hostname
from app.db import SessionLocal  # Import SessionLocal from your db module

def main(host: str):
    # Create a database session
    db = SessionLocal()
    try:
        agent = get_agent_by_hostname(db, host)
        print(agent)
    finally:
        db.close()  # Ensure the session is closed

if __name__ == "__main__":
    main("FRTESTPC")