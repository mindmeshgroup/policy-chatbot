from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

# Import your route
from backend.routes.ask import router as ask_router

# Rate limiting
from slowapi import Limiter
from slowapi.util import get_remote_address

# Initialize app
app = FastAPI(
    title="Policy DB Chatbot Backend",
    version="1.0.0"
)

# Initialize limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# CORS Middleware (API Security)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(ask_router)

# Root endpoint
@app.get("/")
def root():
    return RedirectResponse(url='docs')

# Health check endpoint
@app.get("/health")
def health():
    return {"status": "ok"}