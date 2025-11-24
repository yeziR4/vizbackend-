# gunicorn.conf.py
bind = "0.0.0.0:10000"
workers = 2
timeout = 300  # 5 minutes - gives your app time to fetch all the data
worker_class = "sync"
keepalive = 5
