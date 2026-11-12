import os, sqlite3
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB=Path(os.getenv("DATABASE_PATH","./data/docentes.db")); DB.parent.mkdir(parents=True,exist_ok=True)
def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
@asynccontextmanager
async def lifespan(_:FastAPI):
    with db() as c: c.execute("""CREATE TABLE IF NOT EXISTS docentes(id INTEGER PRIMARY KEY AUTOINCREMENT, documento TEXT NOT NULL UNIQUE, nombres TEXT NOT NULL, apellidos TEXT NOT NULL, correo TEXT NOT NULL UNIQUE, departamento TEXT NOT NULL, especialidad TEXT NOT NULL, activo INTEGER NOT NULL DEFAULT 1 CHECK(activo IN(0,1)))""")
    yield
app=FastAPI(title="Microservicio de Docentes",description="Registro y consulta de docentes.",version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://127.0.0.1:5500","http://localhost:5500"],allow_methods=["*"],allow_headers=["*"])
class DocenteIn(BaseModel):
    documento:str=Field(min_length=5,max_length=20); nombres:str=Field(min_length=2,max_length=80); apellidos:str=Field(min_length=2,max_length=80)
    correo:str=Field(min_length=6,max_length=200,pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"); departamento:str=Field(min_length=2,max_length=100); especialidad:str=Field(min_length=2,max_length=120); activo:bool=True
def public(r): return {**dict(r),"activo":bool(r["activo"])}
@app.get("/health",tags=["Sistema"])
def health(): return {"servicio":"docentes","estado":"activo","base_de_datos":"conectada"}
@app.post("/docentes",status_code=201,tags=["Docentes"])
def create(x:DocenteIn):
    try:
        with db() as c:
            q=c.execute("INSERT INTO docentes(documento,nombres,apellidos,correo,departamento,especialidad,activo) VALUES(?,?,?,?,?,?,?)",(x.documento.strip(),x.nombres.strip(),x.apellidos.strip(),x.correo.strip().lower(),x.departamento.strip(),x.especialidad.strip(),int(x.activo)))
            return public(c.execute("SELECT * FROM docentes WHERE id=?",(q.lastrowid,)).fetchone())
    except sqlite3.IntegrityError: raise HTTPException(409,"Documento o correo ya registrado.")
@app.get("/docentes",tags=["Docentes"])
def list_all():
    with db() as c: return [public(r) for r in c.execute("SELECT * FROM docentes ORDER BY id")]
@app.get("/docentes/{id}",tags=["Docentes"])
def get(id:int):
    with db() as c: r=c.execute("SELECT * FROM docentes WHERE id=?",(id,)).fetchone()
    if not r: raise HTTPException(404,"Docente no encontrado.")
    return public(r)
@app.put("/docentes/{id}",tags=["Docentes"])
def update(id:int,x:DocenteIn):
    try:
        with db() as c:
            q=c.execute("UPDATE docentes SET documento=?,nombres=?,apellidos=?,correo=?,departamento=?,especialidad=?,activo=? WHERE id=?",(x.documento.strip(),x.nombres.strip(),x.apellidos.strip(),x.correo.strip().lower(),x.departamento.strip(),x.especialidad.strip(),int(x.activo),id))
            if not q.rowcount: raise HTTPException(404,"Docente no encontrado.")
            return public(c.execute("SELECT * FROM docentes WHERE id=?",(id,)).fetchone())
    except sqlite3.IntegrityError: raise HTTPException(409,"Documento o correo ya registrado.")
@app.delete("/docentes/{id}",status_code=204,tags=["Docentes"])
def delete(id:int):
    with db() as c: q=c.execute("DELETE FROM docentes WHERE id=?",(id,))
    if not q.rowcount: raise HTTPException(404,"Docente no encontrado.")
    return Response(status_code=204)
