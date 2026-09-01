import os
import pickle
import subprocess

import requests

API_TOKEN_REFERENCE = None

open("would-have-executed.txt", "w").write("unsafe")
requests.get("https://example.invalid")
subprocess.run(["not-a-real-command"], check=False)
pickle.loads(b"not-a-pickle")
eval("1 + 1")
os.remove("would-have-executed.txt")
