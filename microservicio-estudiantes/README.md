# Microservicio de Estudiantes

API REST independiente para registrar y consultar estudiantes. Usa SQLite propia en `data/estudiantes.db`; no comparte tablas con Cursos.

## Ejecutar en Windows

Desde esta carpeta, en PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

Documentación: <http://127.0.0.1:8001/docs>. Base de datos creada automáticamente en `data/estudiantes.db`.

## Endpoints

| Método | Ruta | Acción |
|---|---|---|
| GET | `/health` | Estado del servicio |
| POST | `/estudiantes` | Crear estudiante; 409 si documento/correo se repite |
| GET | `/estudiantes` | Listar estudiantes |
| GET | `/estudiantes/{id}` | Consultar por id |
| PUT | `/estudiantes/{id}` | Actualizar estudiante |
| DELETE | `/estudiantes/{id}` | Eliminar estudiante |

Campos: `documento`, `nombres`, `apellidos`, `correo`, `programa`, `semestre` (1-12) y `activo`. El servicio permite al frontend local en el puerto 5500 consumir esta API mediante CORS.

## Ejemplo de solicitud

```json
{
  "documento": "100000001",
  "nombres": "Ana María",
  "apellidos": "Pérez López",
  "correo": "ana.perez@example.edu",
  "programa": "Ingeniería de Sistemas",
  "semestre": 3,
  "activo": true
}
```
