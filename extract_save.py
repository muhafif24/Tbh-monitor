import os
import json
import logging
import datetime
from src.save_reader import decrypt_save, SAVE_PATH

logging.basicConfig(level=logging.INFO)

def get_latest_save_file():
    """Find the newest .es3 or .es3.bak file in the save folder."""
    save_dir = os.path.dirname(SAVE_PATH)
    latest_file = None
    latest_time = 0
    
    if not os.path.exists(save_dir):
        return SAVE_PATH

    for filename in os.listdir(save_dir):
        if filename.endswith(".es3") or filename.endswith(".es3.bak"):
            filepath = os.path.join(save_dir, filename)
            mtime = os.path.getmtime(filepath)
            if mtime > latest_time:
                latest_time = mtime
                latest_file = filepath
                
    return latest_file or SAVE_PATH

def main():
    target_path = get_latest_save_file()
    mtime = os.path.getmtime(target_path)
    dt_mtime = datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
    
    print("=" * 60)
    print(f"Decrypting the LATEST Task Bar Hero savegame file:")
    print(f"Location: {target_path}")
    print(f"Time    : {dt_mtime}")
    print("=" * 60)
    
    try:
        data = decrypt_save(target_path)
        output_file = "decrypted_save.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        
        print("\n[SUCCESS]")
        print(f"Savegame decrypted successfully and saved to:")
        print(f"-> {os.path.abspath(output_file)}")
        
    except Exception as e:
        print("\n[FAILED]")
        print(f"An error occurred while decrypting save game:\n{e}")

if __name__ == "__main__":
    main()
