import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/cursos.db")
if not DATABASE_URL.startswith("sqlite:///"):
    raise RuntimeError("Esta versión de demostración requiere SQLite.")
DB_PATH = Path(DATABASE_URL.removeprefix("sqlite:///"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@asynccontextmanager
async def lifespan(_: FastAPI):
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS cursos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL,
                creditos INTEGER NOT NULL CHECK (creditos BETWEEN 1 AND 10),
                cupos INTEGER NOT NULL CHECK (cupos >= 0),
                activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
            )"""
        )
    yield


app = FastAPI(
    title="Microservicio de Cursos",
    description="API REST para administrar el catálogo de cursos de la Plataforma Académica Universitaria.",
    version="1.0.0",
    lifespan=lifespan,
)

# Permite que el frontend local en el puerto 5500 consuma esta API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)


class CursoIn(BaseModel):
    codigo: str = Field(min_length=2, max_length=20, examples=["INF101"])
    nombre: str = Field(min_length=3, max_length=120, examples=["Fundamentos de Programación"])
    creditos: int = Field(ge=1, le=10, examples=[3])
    cupos: int = Field(ge=0, le=500, examples=[30])
    activo: bool = True


class Curso(CursoIn):
    id: int


def as_curso(row):
    return Curso(id=row["id"], codigo=row["codigo"], nombre=row["nombre"],
                 creditos=row["creditos"], cupos=row["cupos"], activo=bool(row["activo"]))


@app.get("/health", tags=["Sistema"])
def health():
    return {"servicio": "cursos", "estado": "activo", "base_de_datos": "conectada"}


@app.post("/cursos", response_model=Curso, status_code=status.HTTP_201_CREATED, tags=["Cursos"])
def crear_curso(payload: CursoIn):
    try:
        with connect() as conn:
            cursor = conn.execute(
                "INSERT INTO cursos (codigo, nombre, creditos, cupos, activo) VALUES (?, ?, ?, ?, ?)",
                (payload.codigo.strip().upper(), payload.nombre.strip(), payload.creditos,
                 payload.cupos, int(payload.activo)),
            )
            row = conn.execute("SELECT * FROM cursos WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return as_curso(row)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ya existe un curso con ese código.")


@app.get("/cursos", response_model=list[Curso], tags=["Cursos"])
def listar_cursos():
    with connect() as conn:
        return [as_curso(row) for row in conn.execute("SELECT * FROM cursos ORDER BY id")]


@app.get("/cursos/{curso_id}", response_model=Curso, tags=["Cursos"])
def obtener_curso(curso_id: int):
    with connect() as conn:
        row = conn.execute("SELECT * FROM cursos WHERE id = ?", (curso_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Curso no encontrado.")
    return as_curso(row)


@app.put("/cursos/{curso_id}", response_model=Curso, tags=["Cursos"])
def actualizar_curso(curso_id: int, payload: CursoIn):
    try:
        with connect() as conn:
            cursor = conn.execute(
                "UPDATE cursos SET codigo = ?, nombre = ?, creditos = ?, cupos = ?, activo = ? WHERE id = ?",
                (payload.codigo.strip().upper(), payload.nombre.strip(), payload.creditos,
                 payload.cupos, int(payload.activo), curso_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Curso no encontrado.")
            return as_curso(conn.execute("SELECT * FROM cursos WHERE id = ?", (curso_id,)).fetchone())
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ya existe un curso con ese código.")


@app.delete("/cursos/{curso_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Cursos"])
def eliminar_curso(curso_id: int):
    with connect() as conn:
        cursor = conn.execute("DELETE FROM cursos WHERE id = ?", (curso_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Curso no encontrado.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
