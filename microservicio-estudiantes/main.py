import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/estudiantes.db")
if not DATABASE_URL.startswith("sqlite:///"):
    raise RuntimeError("Esta versión de demostración requiere SQLite.")
DB_PATH = Path(DATABASE_URL.removeprefix("sqlite:///"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@asynccontextmanager
async def lifespan(_: FastAPI):
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS estudiantes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                documento TEXT NOT NULL UNIQUE,
                nombres TEXT NOT NULL,
                apellidos TEXT NOT NULL,
                correo TEXT NOT NULL UNIQUE,
                programa TEXT NOT NULL,
                semestre INTEGER NOT NULL CHECK (semestre BETWEEN 1 AND 12),
                activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
            )"""
        )
    yield


app = FastAPI(
    title="Microservicio de Estudiantes",
    description="API REST para registrar y consultar estudiantes de la Plataforma Académica Universitaria.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)


class EstudianteIn(BaseModel):
    documento: str = Field(min_length=5, max_length=20, examples=["100000001"])
    nombres: str = Field(min_length=2, max_length=80, examples=["Ana María"])
    apellidos: str = Field(min_length=2, max_length=80, examples=["Pérez López"])
    correo: str = Field(
        min_length=6, max_length=200,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        examples=["ana.perez@example.edu"],
    )
    programa: str = Field(min_length=3, max_length=100, examples=["Ingeniería de Sistemas"])
    semestre: int = Field(ge=1, le=12, examples=[3])
    activo: bool = True


class Estudiante(EstudianteIn):
    id: int


def as_estudiante(row):
    return Estudiante(
        id=row["id"], documento=row["documento"], nombres=row["nombres"],
        apellidos=row["apellidos"], correo=row["correo"], programa=row["programa"],
        semestre=row["semestre"], activo=bool(row["activo"]),
    )


def conflict_error():
    raise HTTPException(status_code=409, detail="Documento o correo ya registrado.")


@app.get("/health", tags=["Sistema"])
def health():
    return {"servicio": "estudiantes", "estado": "activo", "base_de_datos": "conectada"}


@app.post("/estudiantes", response_model=Estudiante, status_code=status.HTTP_201_CREATED, tags=["Estudiantes"])
def crear_estudiante(payload: EstudianteIn):
    try:
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO estudiantes (documento,nombres,apellidos,correo,programa,semestre,activo) VALUES (?,?,?,?,?,?,?)",
                (payload.documento.strip(), payload.nombres.strip(), payload.apellidos.strip(),
                 payload.correo.strip().lower(), payload.programa.strip(), payload.semestre, int(payload.activo)),
            )
            return as_estudiante(conn.execute("SELECT * FROM estudiantes WHERE id=?", (cur.lastrowid,)).fetchone())
    except sqlite3.IntegrityError:
        conflict_error()


@app.get("/estudiantes", response_model=list[Estudiante], tags=["Estudiantes"])
def listar_estudiantes():
    with connect() as conn:
        return [as_estudiante(row) for row in conn.execute("SELECT * FROM estudiantes ORDER BY id")]


@app.get("/estudiantes/{estudiante_id}", response_model=Estudiante, tags=["Estudiantes"])
def obtener_estudiante(estudiante_id: int):
    with connect() as conn:
        row = conn.execute("SELECT * FROM estudiantes WHERE id=?", (estudiante_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado.")
    return as_estudiante(row)


@app.put("/estudiantes/{estudiante_id}", response_model=Estudiante, tags=["Estudiantes"])
def actualizar_estudiante(estudiante_id: int, payload: EstudianteIn):
    try:
        with connect() as conn:
            cur = conn.execute(
                "UPDATE estudiantes SET documento=?, nombres=?, apellidos=?, correo=?, programa=?, semestre=?, activo=? WHERE id=?",
                (payload.documento.strip(), payload.nombres.strip(), payload.apellidos.strip(),
                 payload.correo.strip().lower(), payload.programa.strip(), payload.semestre,
                 int(payload.activo), estudiante_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Estudiante no encontrado.")
            return as_estudiante(conn.execute("SELECT * FROM estudiantes WHERE id=?", (estudiante_id,)).fetchone())
    except sqlite3.IntegrityError:
        conflict_error()


@app.delete("/estudiantes/{estudiante_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Estudiantes"])
def eliminar_estudiante(estudiante_id: int):
    with connect() as conn:
        cur = conn.execute("DELETE FROM estudiantes WHERE id=?", (estudiante_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
