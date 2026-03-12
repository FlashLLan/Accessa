from fastapi import FastAPI

from database.db import Base, engine
import backend.models  # noqa: F401
from backend.api import users
from backend.api import auth
from backend.api import change_requests
from backend.api import audit_logs

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Accessa API")
app.include_router(users.router)
app.include_router(auth.router)
app.include_router(change_requests.router)
app.include_router(audit_logs.router)
#app.openapi_schema = None


@app.get("/")
def root():
    return {"message": "Accessa API running"}