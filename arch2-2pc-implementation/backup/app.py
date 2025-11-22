import shutil, time, os
from datetime import datetime

DB_PATH = "/metadata/metadata.db"
STORAGE_PATH = "/storage"
BACKUP_PATH = "/backup"

os.makedirs(BACKUP_PATH, exist_ok=True)

def backup():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Backup database
    if os.path.exists(DB_PATH):
        shutil.copy(DB_PATH, os.path.join(BACKUP_PATH, f"metadata_{timestamp}.db"))
    # Backup storage files
    storage_backup = os.path.join(BACKUP_PATH, f"storage_{timestamp}")
    shutil.copytree(STORAGE_PATH, storage_backup)
    print(f"Backup completed at {timestamp}")

if __name__ == "__main__":
    while True:
        backup()
        time.sleep(3600)  # Run every hour
