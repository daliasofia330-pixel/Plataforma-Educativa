import json, os, sqlite3, urllib.error, urllib.request
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB=Path(os.getenv("DATABASE_PATH","./data/matriculas.db")); DB.parent.mkdir(parents=True,exist_ok=True)
STUDENTS_URL=os.getenv("ESTUDIANTES_URL","http://127.0.0.1:8001").rstrip("/")
COURSES_URL=os.getenv("CURSOS_URL","http://127.0.0.1:8000").rstrip("/")
def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def service_get(url):
    try:
        with urllib.request.urlopen(url,timeout=3) as r: return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code==404: return None
        raise HTTPException(503,"Un servicio relacionado respondió con error.")
    except Exception: raise HTTPException(503,"No se pudo conectar con Cursos o Estudiantes; verifica que estén activos.")
@asynccontextmanager
async def lifespan(_:FastAPI):
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS matriculas(id INTEGER PRIMARY KEY AUTOINCREMENT, estudiante_id INTEGER NOT NULL, curso_id INTEGER NOT NULL, fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, estado TEXT NOT NULL DEFAULT 'activa' CHECK(estado IN('activa','cancelada')))""")
        schema=c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='matriculas'").fetchone()[0]
        if "UNIQUE(estudiante_id,curso_id)" in schema.replace(" ", ""):
            c.execute("ALTER TABLE matriculas RENAME TO matriculas_legacy")
            c.execute("CREATE TABLE matriculas(id INTEGER PRIMARY KEY AUTOINCREMENT, estudiante_id INTEGER NOT NULL, curso_id INTEGER NOT NULL, fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, estado TEXT NOT NULL DEFAULT 'activa' CHECK(estado IN('activa','cancelada')))" )
            c.execute("INSERT INTO matriculas(id,estudiante_id,curso_id,fecha,estado) SELECT id,estudiante_id,curso_id,fecha,estado FROM matriculas_legacy")
            c.execute("DROP TABLE matriculas_legacy")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_matricula_activa ON matriculas(estudiante_id,curso_id) WHERE estado='activa'")
    yield
app=FastAPI(title="Microservicio de Matrículas",description="Gestiona matrículas y valida estudiante y curso consultando sus APIs.",version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://127.0.0.1:5500","http://localhost:5500"],allow_methods=["*"],allow_headers=["*"])
class MatriculaIn(BaseModel): estudiante_id:int=Field(gt=0); curso_id:int=Field(gt=0)
@app.get("/health",tags=["Sistema"])
def health(): return {"servicio":"matriculas","estado":"activo","base_de_datos":"conectada","dependencias":["estudiantes","cursos"]}
@app.post("/matriculas",status_code=201,tags=["Matrículas"])
def create(x:MatriculaIn):
    student=service_get(f"{STUDENTS_URL}/estudiantes/{x.estudiante_id}"); course=service_get(f"{COURSES_URL}/cursos/{x.curso_id}")
    if not student or not student.get("activo"): raise HTTPException(422,"El estudiante no existe o está inactivo.")
    if not course or not course.get("activo"): raise HTTPException(422,"El curso no existe o está inactivo.")
    try:
        with db() as c:
            n=c.execute("SELECT COUNT(*) FROM matriculas WHERE curso_id=? AND estado='activa'",(x.curso_id,)).fetchone()[0]
            if n>=course["cupos"]: raise HTTPException(409,"El curso no tiene cupos disponibles.")
            q=c.execute("INSERT INTO matriculas(estudiante_id,curso_id) VALUES(?,?)",(x.estudiante_id,x.curso_id))
            return dict(c.execute("SELECT * FROM matriculas WHERE id=?",(q.lastrowid,)).fetchone())
    except sqlite3.IntegrityError: raise HTTPException(409,"Ese estudiante ya está matriculado en ese curso.")
@app.get("/matriculas",tags=["Matrículas"])
def list_all():
    with db() as c: return [dict(r) for r in c.execute("SELECT * FROM matriculas ORDER BY id")]
@app.get("/matriculas/{id}",tags=["Matrículas"])
def get(id:int):
    with db() as c: r=c.execute("SELECT * FROM matriculas WHERE id=?",(id,)).fetchone()
    if not r: raise HTTPException(404,"Matrícula no encontrada.")
    return dict(r)
@app.put("/matriculas/{id}/cancelar",tags=["Matrículas"])
def cancel(id:int):
    with db() as c:
        q=c.execute("UPDATE matriculas SET estado='cancelada' WHERE id=? AND estado='activa'",(id,))
        if not q.rowcount:
            if not c.execute("SELECT 1 FROM matriculas WHERE id=?",(id,)).fetchone(): raise HTTPException(404,"Matrícula no encontrada.")
        return dict(c.execute("SELECT * FROM matriculas WHERE id=?",(id,)).fetchone())
@app.delete("/matriculas/{id}",status_code=204,tags=["Matrículas"])
def delete(id:int):
    with db() as c: q=c.execute("DELETE FROM matriculas WHERE id=?",(id,))
    if not q.rowcount: raise HTTPException(404,"Matrícula no encontrada.")
    return Response(status_code=204)
