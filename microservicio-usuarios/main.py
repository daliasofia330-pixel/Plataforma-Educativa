import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

DB = Path(os.getenv("DATABASE_PATH", "./data/usuarios.db"))
DB.parent.mkdir(parents=True, exist_ok=True)
SECRET = os.getenv("JWT_SECRET", "demo-equipo4-cambiar-en-produccion").encode()
bearer = HTTPBearer(auto_error=False)

def db():
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row; return conn

@asynccontextmanager
async def lifespan(_: FastAPI):
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS usuarios (
          id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL,
          correo TEXT NOT NULL UNIQUE, rol TEXT NOT NULL CHECK(rol IN ('administrador','estudiante','docente')),
          password_hash TEXT NOT NULL, activo INTEGER NOT NULL DEFAULT 1)""")
    yield

app = FastAPI(title="Microservicio de Usuarios", description="Gestión de usuarios, autenticación y emisión de token Bearer de demostración.", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"], allow_methods=["*"], allow_headers=["*"])

class UsuarioIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    correo: str = Field(min_length=6, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    rol: str = Field(pattern=r"^(administrador|estudiante|docente)$")
    contrasena: str = Field(min_length=8, max_length=128)

class Login(BaseModel):
    correo: str
    contrasena: str

class BootstrapIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    correo: str = Field(min_length=6, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    contrasena: str = Field(min_length=8, max_length=128)

class UsuarioPublico(BaseModel):
    id: int; nombre: str; correo: str; rol: str; activo: bool

def password_hash(value: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", value.encode(), salt, 200000)
    return base64.b64encode(salt + derived).decode()

def verify_password(value: str, stored: str) -> bool:
    try:
        raw = base64.b64decode(stored); salt, expected = raw[:16], raw[16:]
        actual = hashlib.pbkdf2_hmac("sha256", value.encode(), salt, 200000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def make_token(user: sqlite3.Row) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"sub": user["id"], "correo": user["correo"], "rol": user["rol"], "exp": int(time.time()) + 3600}).encode()).rstrip(b"=").decode()
    message = f"{header}.{payload}"
    signature = base64.urlsafe_b64encode(hmac.new(SECRET, message.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{message}.{signature}"

def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials or credentials.scheme.lower() != "bearer": raise HTTPException(401, "Se requiere un token Bearer.")
    try:
        head, payload, signature = credentials.credentials.split(".")
        expected = base64.urlsafe_b64encode(hmac.new(SECRET, f"{head}.{payload}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        if not hmac.compare_digest(signature, expected): raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if data["exp"] < time.time(): raise ValueError()
        with db() as c: user = c.execute("SELECT id,nombre,correo,rol,activo FROM usuarios WHERE id=?", (data["sub"],)).fetchone()
        if not user or not user["activo"]: raise ValueError()
        return dict(user)
    except Exception:
        raise HTTPException(401, "Token inválido o vencido.")

@app.get("/health", tags=["Sistema"])
def health(): return {"servicio":"usuarios", "estado":"activo", "base_de_datos":"conectada"}

@app.post("/usuarios", response_model=UsuarioPublico, status_code=201, tags=["Usuarios"])
def crear_usuario(body: UsuarioIn):
    try:
        with db() as c:
            cur = c.execute("INSERT INTO usuarios(nombre,correo,rol,password_hash) VALUES(?,?,?,?)", (body.nombre.strip(), body.correo.strip().lower(), body.rol, password_hash(body.contrasena)))
            row = c.execute("SELECT id,nombre,correo,rol,activo FROM usuarios WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)
    except sqlite3.IntegrityError: raise HTTPException(409, "Ese correo ya está registrado.")

@app.post("/auth/bootstrap", response_model=UsuarioPublico, status_code=201, tags=["Autenticación"])
def bootstrap(body: BootstrapIn):
    try:
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone():
                raise HTTPException(409, "El administrador inicial ya fue creado.")
            cur = c.execute(
                "INSERT INTO usuarios(nombre,correo,rol,password_hash) VALUES(?,?,?,?)",
                (body.nombre.strip(), body.correo.strip().lower(), "administrador", password_hash(body.contrasena)),
            )
            return dict(c.execute("SELECT id,nombre,correo,rol,activo FROM usuarios WHERE id=?", (cur.lastrowid,)).fetchone())
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Ese correo ya está registrado.")

@app.post("/auth/login", tags=["Autenticación"])
def login(body: Login):
    with db() as c: row = c.execute("SELECT * FROM usuarios WHERE correo=?", (body.correo.strip().lower(),)).fetchone()
    if not row or not row["activo"] or not verify_password(body.contrasena, row["password_hash"]): raise HTTPException(401, "Correo o contraseña incorrectos.")
    return {"access_token": make_token(row), "token_type":"bearer", "expires_in":3600, "usuario":{"id":row["id"],"nombre":row["nombre"],"correo":row["correo"],"rol":row["rol"]}}

@app.get("/auth/me", tags=["Autenticación"])
def me(user=Depends(current_user)): return user

@app.get("/usuarios", response_model=list[UsuarioPublico], tags=["Usuarios"])
def listar_usuarios():
    with db() as c: return [dict(r) for r in c.execute("SELECT id,nombre,correo,rol,activo FROM usuarios ORDER BY id")]

@app.get("/usuarios/{usuario_id}", response_model=UsuarioPublico, tags=["Usuarios"])
def obtener_usuario(usuario_id:int):
    with db() as c: row=c.execute("SELECT id,nombre,correo,rol,activo FROM usuarios WHERE id=?",(usuario_id,)).fetchone()
    if not row: raise HTTPException(404,"Usuario no encontrado.")
    return dict(row)

@app.delete("/usuarios/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Usuarios"])
def eliminar_usuario(usuario_id:int):
    with db() as c: cur=c.execute("DELETE FROM usuarios WHERE id=?",(usuario_id,))
    if not cur.rowcount: raise HTTPException(404,"Usuario no encontrado.")
    return Response(status_code=204)
