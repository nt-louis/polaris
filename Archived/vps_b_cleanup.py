#!/usr/bin/env python3
import os
import shutil
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_tracked_dirs():
    """Retrieve all directories that contain at least one git-tracked file."""
    try:
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        tracked_files = res.stdout.strip().split("\n")
    except Exception as e:
        print(f"Error running git ls-files: {e}")
        sys.exit(1)
        
    tracked_dirs = set()
    for f in tracked_files:
        parts = f.split("/")
        # Build all parent directory paths
        for i in range(1, len(parts)):
            tracked_dirs.add(os.path.join(REPO_ROOT, *parts[:i]))
            
    return tracked_dirs

def clean_untracked_dirs():
    print("=== Obsolete Directory Purge ===")
    
    tracked_dirs = get_tracked_dirs()
    
    # Target top-level service folders inside these specific category roots
    target_search_dirs = [
        "Utilities",
        "Media/stremio/addons",
        "Media/stremio/utilities",
        "Media/comics",
        "Media/local-media/download-clients",
        "Media/local-media/players",
        "Media/local-media/managers",
        "Media/local-media/tools",
        "Media/local-media/requests"
    ]
    
    deleted_count = 0
    
    for rel_root in target_search_dirs:
        abs_root = os.path.join(REPO_ROOT, rel_root)
        if not os.path.exists(abs_root):
            continue
            
        try:
            subdirs = [d for d in os.listdir(abs_root) if os.path.isdir(os.path.join(abs_root, d))]
        except Exception:
            continue
            
        for d in subdirs:
            dir_path = os.path.join(abs_root, d)
            rel_dir_path = os.path.relpath(dir_path, REPO_ROOT)
            
            # A directory is tracked if it or any of its subfolders contains a tracked file
            is_tracked = False
            for td in tracked_dirs:
                if td == dir_path or td.startswith(dir_path + "/"):
                    is_tracked = True
                    break
                    
            if not is_tracked:
                print(f"Removing obsolete directory: {rel_dir_path}...")
                try:
                    shutil.rmtree(dir_path)
                    deleted_count += 1
                except Exception as e:
                    print(f"Permission denied on {dir_path}. Trying with sudo...")
                    res = subprocess.run(["sudo", "rm", "-rf", dir_path])
                    if res.returncode == 0:
                        deleted_count += 1
                    else:
                        print(f"Failed to delete {dir_path}")

    print(f"\nCleanup complete! Purged {deleted_count} obsolete/untracked directories.")

if __name__ == "__main__":
    clean_untracked_dirs()
