from fastapi import FastAPI

from database.db import Base, engine
import backend.models  # noqa: F401
from backend.api import users
from backend.api import auth

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Accessa API")
app.include_router(users.router)
app.include_router(auth.router)

app.openapi_schema = None


@app.get("/")
def root():
    return {"message": "Accessa API running"}