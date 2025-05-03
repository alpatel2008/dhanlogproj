#dhanlogproj.wsgi

import os
from dhan_bg_process import app

if __name__ == "__main__":
  port = int(os.environ.get("PORT",4000))
  app.run(host="0.0.0.0", port=port)

