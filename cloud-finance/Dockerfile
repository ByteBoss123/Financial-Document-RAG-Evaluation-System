FROM python:3.12-slim
WORKDIR /opt/cloud-finance
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -m app
COPY . .
USER app
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["python","-m","streamlit","run","app.py","--server.address=0.0.0.0","--server.port=8501","--server.headless=true"]
