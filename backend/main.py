from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from backend.core.limiter import limiter

import backend.models  # noqa: F401
from backend.api import users
from backend.api import auth
from backend.api import change_requests
from backend.api import audit_logs
from backend.api import roles
from backend.api import git_context
from backend.api import ai_review
from backend.api import review_actions
from backend.api import mfa
from fastapi.middleware.cors import CORSMiddleware
from backend.core.security_headers import SecurityHeadersMiddleware

# The schema is managed only by Alembic migrations (alembic upgrade head),
# never created implicitly at startup.

app = FastAPI(title="Accessa API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

import os

_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Added last = outermost: also covers CORS preflight answers and error responses.
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(users.router)
app.include_router(auth.router)
app.include_router(change_requests.router)
app.include_router(audit_logs.router)
#app.openapi_schema = None
app.include_router(roles.router)
app.include_router(git_context.router)
app.include_router(ai_review.router)
app.include_router(review_actions.router)
app.include_router(mfa.router)

@app.get("/")
def root():
    return {"message": "Accessa API running"}