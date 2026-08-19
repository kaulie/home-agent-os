"""Brain entry: re-export the production app from home_brain.py.

Run (from repo root or server/):

  python home_brain.py
  python brain_app.py
"""

from home_brain import app, log

if __name__ == "__main__":
    log.info("Brain home_brain.py on :9527")
    log.info("%s", app.url_map)
    app.run(host="0.0.0.0", port=9527, debug=False, use_reloader=False, threaded=True)
