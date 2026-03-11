from fastapi import FastAPI

from database.db import Base, engine
import backend.models  # noqa: F401

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Accessa API")


@app.get("/")
def root():
    return {"message": "Accessa API running"}