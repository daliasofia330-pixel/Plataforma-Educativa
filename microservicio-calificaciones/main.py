import json, os, sqlite3, urllib.error, urllib.request
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB=Path(os.getenv("DATABASE_PATH","./data/calificaciones.db")); DB.parent.mkdir(parents=True,exist_ok=True)
MATRICULAS_URL=os.getenv("MATRICULAS_URL","http://127.0.0.1:8002").rstrip("/")
def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def enrollment(id):
    try:
        with urllib.request.urlopen(f"{MATRICULAS_URL}/matriculas/{id}",timeout=3) as r: return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code==404: return None
        raise HTTPException(503,"Matrículas respondió con error.")
    except Exception: raise HTTPException(503,"No se pudo conectar con Matrículas; verifica que esté activo.")
@asynccontextmanager
async def lifespan(_:FastAPI):
    with db() as c: c.execute("""CREATE TABLE IF NOT EXISTS calificaciones(id INTEGER PRIMARY KEY AUTOINCREMENT, matricula_id INTEGER NOT NULL, actividad TEXT NOT NULL, nota REAL NOT NULL CHECK(nota BETWEEN 0 AND 5), observaciones TEXT NOT NULL DEFAULT '', fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(matricula_id,actividad))""")
    yield
app=FastAPI(title="Microservicio de Calificaciones",description="Registra notas por matrícula y valida matrícula activa por API.",version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://127.0.0.1:5500","http://localhost:5500"],allow_methods=["*"],allow_headers=["*"])
class NotaIn(BaseModel): matricula_id:int=Field(gt=0); actividad:str=Field(min_length=2,max_length=100); nota:float=Field(ge=0,le=5); observaciones:str=Field(default="",max_length=300)
@app.get("/health",tags=["Sistema"])
def health(): return {"servicio":"calificaciones","estado":"activo","base_de_datos":"conectada","dependencia":"matriculas"}
@app.post("/calificaciones",status_code=201,tags=["Calificaciones"])
def create(x:NotaIn):
    m=enrollment(x.matricula_id)
    if not m or m["estado"]!="activa": raise HTTPException(422,"La matrícula no existe o no está activa.")
    try:
        with db() as c:
            q=c.execute("INSERT INTO calificaciones(matricula_id,actividad,nota,observaciones) VALUES(?,?,?,?)",(x.matricula_id,x.actividad.strip(),x.nota,x.observaciones.strip()))
            return dict(c.execute("SELECT * FROM calificaciones WHERE id=?",(q.lastrowid,)).fetchone())
    except sqlite3.IntegrityError: raise HTTPException(409,"Ya existe una nota para esa actividad y matrícula.")
@app.get("/calificaciones",tags=["Calificaciones"])
def list_all():
    with db() as c: return [dict(r) for r in c.execute("SELECT * FROM calificaciones ORDER BY id")]
@app.get("/calificaciones/{id}",tags=["Calificaciones"])
def get(id:int):
    with db() as c: r=c.execute("SELECT * FROM calificaciones WHERE id=?",(id,)).fetchone()
    if not r: raise HTTPException(404,"Calificación no encontrada.")
    return dict(r)
@app.put("/calificaciones/{id}",tags=["Calificaciones"])
def update(id:int,x:NotaIn):
    m=enrollment(x.matricula_id)
    if not m or m["estado"]!="activa": raise HTTPException(422,"La matrícula no existe o no está activa.")
    try:
        with db() as c:
            q=c.execute("UPDATE calificaciones SET matricula_id=?,actividad=?,nota=?,observaciones=? WHERE id=?",(x.matricula_id,x.actividad.strip(),x.nota,x.observaciones.strip(),id))
            if not q.rowcount: raise HTTPException(404,"Calificación no encontrada.")
            return dict(c.execute("SELECT * FROM calificaciones WHERE id=?",(id,)).fetchone())
    except sqlite3.IntegrityError: raise HTTPException(409,"Ya existe una nota para esa actividad y matrícula.")
@app.delete("/calificaciones/{id}",status_code=204,tags=["Calificaciones"])
def delete(id:int):
    with db() as c: q=c.execute("DELETE FROM calificaciones WHERE id=?",(id,))
    if not q.rowcount: raise HTTPException(404,"Calificación no encontrada.")
    return Response(status_code=204)
