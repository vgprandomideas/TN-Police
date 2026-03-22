import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tn_police_final.db")
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-final")
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "480"))
