import os

# Timeout molto lungo per operazioni di sync
timeout = 300  # 5 minuti

# Workers
workers = 2

# Bind
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"

# Logging
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# Graceful timeout
graceful_timeout = 120
