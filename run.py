# This is the "start button" for the whole backend. When you run python run.py,
# this file turns the app from "a Python file on disk" into "a live website on the internet."
# python run.py
#     │
#     ▼
# uvicorn.run("app.main:app", ...)     ← "start a web server on port 8000"
#     │
#     ▼
# http://localhost:8000  →  your app responds
#
# if __name__ == "__main__":
# This is Python's "only do this if someone ran me directly" check.
# Every Python file has a hidden variable called __name__. It equals:
#   "__main__"   when you run that file directly with `python file.py`
#   the module's dotted name  when something else imports it
#
# So the guard below is True only in the first case: the server starts when
# you run this file, and does not start when another module imports it.
#
# This is the local development entry point. Production runs uvicorn
# directly — see DEPLOYMENT.md.

import uvicorn

if __name__ == "__main__":
  uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
