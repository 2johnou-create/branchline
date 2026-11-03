"""Prepare only owned data mount roots, then run the application without root.

Managed hosts can mount fresh disks as root regardless of image-time chown.
This entrypoint never recursively changes ownership or reads user content.
"""
import os
from pathlib import Path
import pwd
import stat
import sys


kind, *command = sys.argv[1:]
if kind not in {"gateway", "engine"} or not command:
    raise SystemExit("Invalid application entrypoint")
user = pwd.getpwnam("branchline")
roots = ["/data"] if kind == "gateway" else ["/app/backend/uploads", "/app/backend/logs"]
os.umask(0o077)
if os.geteuid() == 0:
    for name in roots:
        path = Path(name)
        path.mkdir(parents=True, exist_ok=True)
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise SystemExit("A data mount root is not a real directory")
        os.chown(path, user.pw_uid, user.pw_gid)
        os.chmod(path, 0o700)
    os.setgroups([])
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)
os.environ["HOME"] = user.pw_dir
os.execvp(command[0], command)
