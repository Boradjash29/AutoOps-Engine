# FILE: dashboard/app.py
from flask import Flask, render_template
import os

app = Flask(__name__)

# Note: The dashboard now heavily relies on client-side JS + WebSockets + fetch API
# for dynamic data. The backend only needs to serve the initial index.html page.

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    # Run Flask server
    app.run(host='0.0.0.0', port=5000)
