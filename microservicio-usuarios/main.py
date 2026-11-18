import base64
import hashlib
import hmac
import json
import os
import secrets
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
        c.execute("""CREATE TABLE IF NOT EXISTS recovery_codes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          code_hash TEXT NOT NULL UNIQUE,
          created_at INTEGER NOT NULL,
          expires_at INTEGER NOT NULL,
          used_at INTEGER)""")
        columns = {row["name"] for row in c.execute("PRAGMA table_info(usuarios)")}
        if "documento" not in columns:
            c.execute("ALTER TABLE usuarios ADD COLUMN documento TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS idx_recovery_codes_user ON recovery_codes(user_id, used_at, expires_at)")
        c.execute("""CREATE TABLE IF NOT EXISTS recovery_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          correo TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          handled_at INTEGER)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_recovery_requests_pending ON recovery_requests(handled_at, created_at)")
    yield

app = FastAPI(title="Microservicio de Usuarios", description="Gestión de usuarios, autenticación y emisión de token Bearer de demostración.", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"], allow_methods=["*"], allow_headers=["*"])

class UsuarioIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    correo: str = Field(min_length=6, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    rol: str = Field(pattern=r"^(administrador|estudiante|docente)$")
    contrasena: str = Field(min_length=8, max_length=128)
    documento: str | None = Field(default=None, min_length=4, max_length=40)

class Login(BaseModel):
    correo: str
    contrasena: str

class RecoveryCodeRequest(BaseModel):
    correo: str = Field(min_length=6, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

class DocumentUpdate(BaseModel):
    documento: str = Field(min_length=4, max_length=40)

class PasswordReset(BaseModel):
    correo: str = Field(min_length=6, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    codigo_recuperacion: str = Field(min_length=20, max_length=100)
    nueva_contrasena: str = Field(min_length=8, max_length=128)

class RecoveryRequest(BaseModel):
    correo: str = Field(min_length=6, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

class BootstrapIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    correo: str = Field(min_length=6, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    contrasena: str = Field(min_length=8, max_length=128)
    documento: str = Field(min_length=4, max_length=40)

class UsuarioPublico(BaseModel):
    id: int; nombre: str; correo: str; rol: str; activo: bool; documento: str | None = None

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

def issue_recovery_code(c: sqlite3.Connection, user_id: int, now: int) -> str:
    code = secrets.token_urlsafe(24)
    digest = hashlib.sha256(code.encode()).hexdigest()
    c.execute("DELETE FROM recovery_codes WHERE user_id=? AND used_at IS NULL", (user_id,))
    c.execute(
        "INSERT INTO recovery_codes(user_id,code_hash,created_at,expires_at) VALUES(?,?,?,?)",
        (user_id, digest, now, now + 90 * 24 * 60 * 60),
    )
    return code

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
        with db() as c: user = c.execute("SELECT id,nombre,correo,rol,activo,documento FROM usuarios WHERE id=?", (data["sub"],)).fetchone()
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
            cur = c.execute("INSERT INTO usuarios(nombre,correo,rol,password_hash,documento) VALUES(?,?,?,?,?)", (body.nombre.strip(), body.correo.strip().lower(), body.rol, password_hash(body.contrasena), body.documento.strip() if body.documento else None))
            row = c.execute("SELECT id,nombre,correo,rol,activo,documento FROM usuarios WHERE id=?", (cur.lastrowid,)).fetchone()
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
                "INSERT INTO usuarios(nombre,correo,rol,password_hash,documento) VALUES(?,?,?,?,?)",
                (body.nombre.strip(), body.correo.strip().lower(), "administrador", password_hash(body.contrasena), body.documento.strip()),
            )
            return dict(c.execute("SELECT id,nombre,correo,rol,activo,documento FROM usuarios WHERE id=?", (cur.lastrowid,)).fetchone())
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Ese correo ya está registrado.")

@app.post("/auth/login", tags=["Autenticación"])
def login(body: Login):
    with db() as c:
        row = c.execute("SELECT * FROM usuarios WHERE correo=?", (body.correo.strip().lower(),)).fetchone()
        if not row or not row["activo"] or not verify_password(body.contrasena, row["password_hash"]):
            raise HTTPException(401, "Correo o contraseña incorrectos.")
    return {"access_token": make_token(row), "token_type":"bearer", "expires_in":3600, "usuario":{"id":row["id"],"nombre":row["nombre"],"correo":row["correo"],"rol":row["rol"]}}

@app.post("/usuarios/{usuario_id}/recovery-code", tags=["Autenticación"])
def create_recovery_code(usuario_id: int, admin=Depends(current_user)):
    if admin["rol"] != "administrador":
        raise HTTPException(403, "Solo el administrador puede generar códigos de recuperación.")
    now = int(time.time())
    with db() as c:
        user = c.execute("SELECT id FROM usuarios WHERE id=? AND activo=1", (usuario_id,)).fetchone()
        if not user:
            raise HTTPException(404, "La cuenta no existe o está inactiva.")
        code = issue_recovery_code(c, usuario_id, now)
    return {"codigo_recuperacion": code, "vence_en_dias": 90}

@app.post("/auth/recovery-code", tags=["Autenticación"])
def self_serve_recovery_code(body: RecoveryCodeRequest):
    correo = body.correo.strip().lower()
    now = int(time.time())
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        user = c.execute("SELECT id FROM usuarios WHERE lower(correo)=? AND activo=1", (correo,)).fetchone()
        if not user:
            raise HTTPException(400, "No se pudo validar el correo y el documento.")
        code = issue_recovery_code(c, user["id"], now)
    return {"codigo_recuperacion": code, "vence_en_dias": 90}

@app.post("/auth/password-reset", tags=["Autenticación"])
def reset_password(body: PasswordReset):
    now = int(time.time())
    digest = hashlib.sha256(body.codigo_recuperacion.encode()).hexdigest()
    correo = body.correo.strip().lower()
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        record = c.execute(
            """SELECT rc.id AS recovery_id, rc.user_id
               FROM recovery_codes rc JOIN usuarios u ON u.id=rc.user_id
               WHERE lower(u.correo)=? AND u.activo=1 AND rc.code_hash=?
                 AND rc.used_at IS NULL AND rc.expires_at>?""",
            (correo, digest, now),
        ).fetchone()
        if not record:
            raise HTTPException(400, "El correo o el código de recuperación no es válido o ya venció.")
        c.execute("UPDATE usuarios SET password_hash=? WHERE id=?", (password_hash(body.nueva_contrasena), record["user_id"]))
        c.execute("UPDATE recovery_codes SET used_at=? WHERE user_id=? AND used_at IS NULL", (now, record["user_id"]))
    return {"mensaje": "Contraseña actualizada correctamente."}

@app.post("/auth/recovery-request", tags=["Autenticación"])
def request_recovery_help(body: RecoveryRequest):
    now = int(time.time())
    correo = body.correo.strip().lower()
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        user = c.execute("SELECT id FROM usuarios WHERE lower(correo)=? AND activo=1", (correo,)).fetchone()
        if user:
            recent = c.execute(
                "SELECT 1 FROM recovery_requests WHERE user_id=? AND handled_at IS NULL AND created_at>? LIMIT 1",
                (user["id"], now - 10 * 60),
            ).fetchone()
            if not recent:
                c.execute(
                    "INSERT INTO recovery_requests(user_id,correo,created_at) VALUES(?,?,?)",
                    (user["id"], correo, now),
                )
    return {"mensaje": "Si la cuenta está registrada, el administrador verá la solicitud de ayuda."}

@app.get("/recovery-requests", tags=["Autenticación"])
def list_recovery_requests(admin=Depends(current_user)):
    if admin["rol"] != "administrador":
        raise HTTPException(403, "Solo el administrador puede consultar las solicitudes.")
    with db() as c:
        return [dict(row) for row in c.execute(
            """SELECT r.id,r.correo,r.created_at,u.nombre,u.rol
               FROM recovery_requests r JOIN usuarios u ON u.id=r.user_id
               WHERE r.handled_at IS NULL AND u.activo=1 ORDER BY r.created_at"""
        )]

@app.post("/recovery-requests/{request_id}/recovery-code", tags=["Autenticación"])
def issue_requested_recovery_code(request_id: int, admin=Depends(current_user)):
    if admin["rol"] != "administrador":
        raise HTTPException(403, "Solo el administrador puede emitir códigos.")
    now = int(time.time())
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        request_row = c.execute(
            """SELECT r.id,r.user_id,u.activo FROM recovery_requests r
               JOIN usuarios u ON u.id=r.user_id
               WHERE r.id=? AND r.handled_at IS NULL""",
            (request_id,),
        ).fetchone()
        if not request_row or not request_row["activo"]:
            raise HTTPException(404, "La solicitud ya fue atendida o la cuenta está inactiva.")
        code = issue_recovery_code(c, request_row["user_id"], now)
        c.execute("UPDATE recovery_requests SET handled_at=? WHERE id=?", (now, request_id))
    return {"codigo_recuperacion": code, "vence_en_dias": 90}

@app.get("/auth/me", tags=["Autenticación"])
def me(user=Depends(current_user)): return user

@app.get("/usuarios", response_model=list[UsuarioPublico], tags=["Usuarios"])
def listar_usuarios():
    with db() as c: return [dict(r) for r in c.execute("SELECT id,nombre,correo,rol,activo,documento FROM usuarios ORDER BY id")]

@app.get("/usuarios/{usuario_id}", response_model=UsuarioPublico, tags=["Usuarios"])
def obtener_usuario(usuario_id:int):
    with db() as c: row=c.execute("SELECT id,nombre,correo,rol,activo,documento FROM usuarios WHERE id=?",(usuario_id,)).fetchone()
    if not row: raise HTTPException(404,"Usuario no encontrado.")
    return dict(row)

@app.put("/usuarios/{usuario_id}/documento", tags=["Usuarios"])
def update_user_document(usuario_id: int, body: DocumentUpdate, admin=Depends(current_user)):
    if admin["rol"] != "administrador":
        raise HTTPException(403, "Solo el administrador puede actualizar documentos de cuenta.")
    with db() as c:
        cur = c.execute("UPDATE usuarios SET documento=? WHERE id=? AND activo=1", (body.documento.strip(), usuario_id))
        if not cur.rowcount:
            raise HTTPException(404, "La cuenta no existe o está inactiva.")
        row = c.execute("SELECT id,nombre,correo,rol,activo,documento FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
    return dict(row)

@app.delete("/usuarios/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Usuarios"])
def eliminar_usuario(usuario_id:int):
    with db() as c: cur=c.execute("DELETE FROM usuarios WHERE id=?",(usuario_id,))
    if not cur.rowcount: raise HTTPException(404,"Usuario no encontrado.")
    return Response(status_code=204)
