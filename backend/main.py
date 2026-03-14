from fastapi import FastAPI

from database.db import Base, engine
import backend.models  # noqa: F401
from backend.api import users
from backend.api import auth
from backend.api import change_requests
from backend.api import audit_logs
from backend.api import roles
from fastapi.middleware.cors import CORSMiddleware
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Accessa API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(users.router)
app.include_router(auth.router)
app.include_router(change_requests.router)
app.include_router(audit_logs.router)
#app.openapi_schema = None
app.include_router(roles.router)

@app.get("/")
def root():
    return {"message": "Accessa API running"}