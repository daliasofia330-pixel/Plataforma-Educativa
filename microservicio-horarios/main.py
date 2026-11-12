import json, os, sqlite3, urllib.error, urllib.request
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB=Path(os.getenv("DATABASE_PATH","./data/horarios.db")); DB.parent.mkdir(parents=True,exist_ok=True)
COURSES_URL=os.getenv("CURSOS_URL","http://127.0.0.1:8000").rstrip("/")
TEACHERS_URL=os.getenv("DOCENTES_URL","http://127.0.0.1:8003").rstrip("/")
def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def api_get(url):
    try:
        with urllib.request.urlopen(url,timeout=3) as r: return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code==404: return None
        raise HTTPException(503,"Una API relacionada respondió con error.")
    except Exception: raise HTTPException(503,"No se pudo conectar con Cursos o Docentes; verifica que estén activos.")
@asynccontextmanager
async def lifespan(_:FastAPI):
    with db() as c: c.execute("""CREATE TABLE IF NOT EXISTS horarios(id INTEGER PRIMARY KEY AUTOINCREMENT, curso_id INTEGER NOT NULL, docente_id INTEGER NOT NULL, dia TEXT NOT NULL CHECK(dia IN('lunes','martes','miércoles','jueves','viernes','sábado')), hora_inicio TEXT NOT NULL, hora_fin TEXT NOT NULL, aula TEXT NOT NULL, CHECK(hora_inicio < hora_fin), UNIQUE(docente_id,dia,hora_inicio,aula))""")
    yield
app=FastAPI(title="Microservicio de Horarios",description="Asigna franjas y aulas a cursos y docentes; verifica ambas APIs al crear el horario.",version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://127.0.0.1:5500","http://localhost:5500"],allow_methods=["*"],allow_headers=["*"])
class HorarioIn(BaseModel):
    curso_id:int=Field(gt=0); docente_id:int=Field(gt=0); dia:str=Field(pattern=r"^(lunes|martes|miércoles|jueves|viernes|sábado)$"); hora_inicio:str=Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$"); hora_fin:str=Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$"); aula:str=Field(min_length=1,max_length=30)
def validate_refs(x):
    course=api_get(f"{COURSES_URL}/cursos/{x.curso_id}"); teacher=api_get(f"{TEACHERS_URL}/docentes/{x.docente_id}")
    if not course or not course.get("activo"): raise HTTPException(422,"El curso no existe o está inactivo.")
    if not teacher or not teacher.get("activo"): raise HTTPException(422,"El docente no existe o está inactivo.")
@app.get("/health",tags=["Sistema"])
def health(): return {"servicio":"horarios","estado":"activo","base_de_datos":"conectada","dependencias":["cursos","docentes"]}
@app.post("/horarios",status_code=201,tags=["Horarios"])
def create(x:HorarioIn):
    if x.hora_inicio>=x.hora_fin: raise HTTPException(422,"La hora de inicio debe ser anterior a la hora final.")
    validate_refs(x)
    try:
        with db() as c:
            q=c.execute("INSERT INTO horarios(curso_id,docente_id,dia,hora_inicio,hora_fin,aula) VALUES(?,?,?,?,?,?)",(x.curso_id,x.docente_id,x.dia,x.hora_inicio,x.hora_fin,x.aula.strip()))
            return dict(c.execute("SELECT * FROM horarios WHERE id=?",(q.lastrowid,)).fetchone())
    except sqlite3.IntegrityError: raise HTTPException(409,"Ya existe un horario coincidente para docente, día, hora y aula.")
@app.get("/horarios",tags=["Horarios"])
def list_all():
    with db() as c: return [dict(r) for r in c.execute("SELECT * FROM horarios ORDER BY dia,hora_inicio")]
@app.get("/horarios/{id}",tags=["Horarios"])
def get(id:int):
    with db() as c: r=c.execute("SELECT * FROM horarios WHERE id=?",(id,)).fetchone()
    if not r: raise HTTPException(404,"Horario no encontrado.")
    return dict(r)
@app.put("/horarios/{id}",tags=["Horarios"])
def update(id:int,x:HorarioIn):
    if x.hora_inicio>=x.hora_fin: raise HTTPException(422,"La hora de inicio debe ser anterior a la hora final.")
    validate_refs(x)
    try:
        with db() as c:
            q=c.execute("UPDATE horarios SET curso_id=?,docente_id=?,dia=?,hora_inicio=?,hora_fin=?,aula=? WHERE id=?",(x.curso_id,x.docente_id,x.dia,x.hora_inicio,x.hora_fin,x.aula.strip(),id))
            if not q.rowcount: raise HTTPException(404,"Horario no encontrado.")
            return dict(c.execute("SELECT * FROM horarios WHERE id=?",(id,)).fetchone())
    except sqlite3.IntegrityError: raise HTTPException(409,"Ya existe un horario coincidente.")
@app.delete("/horarios/{id}",status_code=204,tags=["Horarios"])
def delete(id:int):
    with db() as c: q=c.execute("DELETE FROM horarios WHERE id=?",(id,))
    if not q.rowcount: raise HTTPException(404,"Horario no encontrado.")
    return Response(status_code=204)
