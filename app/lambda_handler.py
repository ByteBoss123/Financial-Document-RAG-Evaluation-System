"""AWS Lambda entry point: API Gateway proxy events -> FastAPI app via Mangum."""
from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="auto")
