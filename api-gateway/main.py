import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

SECRET = os.getenv("JWT_SECRET", "demo-equipo4-cambiar-en-produccion").encode()
bearer = HTTPBearer(auto_error=False)
SERVICES = {
    "cursos": os.getenv("CURSOS_URL", "http://127.0.0.1:8000").rstrip("/"),
    "estudiantes": os.getenv("ESTUDIANTES_URL", "http://127.0.0.1:8001").rstrip("/"),
    "matriculas": os.getenv("MATRICULAS_URL", "http://127.0.0.1:8002").rstrip("/"),
    "docentes": os.getenv("DOCENTES_URL", "http://127.0.0.1:8003").rstrip("/"),
    "calificaciones": os.getenv("CALIFICACIONES_URL", "http://127.0.0.1:8004").rstrip("/"),
    "usuarios": os.getenv("USUARIOS_URL", "http://127.0.0.1:8005").rstrip("/"),
    "horarios": os.getenv("HORARIOS_URL", "http://127.0.0.1:8006").rstrip("/"),
}
app = FastAPI(
    title="API Gateway — Plataforma Académica",
    description="Punto de entrada de la plataforma. Protege y enruta solicitudes a los siete microservicios.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


def decode_token(token: str) -> dict[str, Any]:
    try:
        header, payload, signature = token.split(".")
        message = f"{header}.{payload}"
        expected = base64.urlsafe_b64encode(
            hmac.new(SECRET, message.encode(), hashlib.sha256).digest()
        ).rstrip(b"=").decode()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("firma")
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if int(claims.get("exp", 0)) <= int(time.time()):
            raise ValueError("expirado")
        if claims.get("rol") not in {"administrador", "docente", "estudiante"}:
            raise ValueError("rol")
        return claims
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido o vencido.", headers={"WWW-Authenticate": "Bearer"})


def identify_service(path: str) -> tuple[str, str]:
    parts = path.split("/")
    if len(parts) < 3 or parts[0] != "api":
        raise HTTPException(404, "Usa una ruta /api/{servicio}/{recurso}.")
    service = parts[1]
    if service not in SERVICES:
        raise HTTPException(404, "Microservicio desconocido.")
    return service, "/" + "/".join(parts[2:])


def allowed(role: str, method: str, path: str) -> bool:
    if role == "administrador":
        return True
    method = method.upper()
    if role == "docente":
        if method == "GET" and path.startswith(("/cursos", "/matriculas", "/calificaciones", "/horarios")):
            return True
        if method in {"POST", "PUT"} and path.startswith("/calificaciones"):
            return True
        return False
    if role == "estudiante":
        if method == "GET" and path.startswith(("/cursos", "/matriculas", "/calificaciones", "/horarios")):
            return True
        if method == "POST" and path == "/matriculas":
            return True
        if method in {"PUT", "DELETE"} and (path.startswith("/matriculas/") or path.startswith("/matriculas")):
            return True
    return False


async def service_json(service: str, path: str) -> Any:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{SERVICES[service]}{path}")
    except httpx.RequestError:
        raise HTTPException(503, f"El microservicio {service} no está disponible.")
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise HTTPException(503, f"No se pudo consultar el microservicio {service}.")
    return response.json()


async def profile_by_email(role: str, email: str) -> dict[str, Any] | None:
    service = "estudiantes" if role == "estudiante" else "docentes"
    rows = await service_json(service, f"/{service}")
    return next((row for row in rows or [] if row.get("correo", "").strip().lower() == email.strip().lower()), None)


def resource_id(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


async def rows_for_user(role: str, email: str) -> tuple[dict[str, Any], list[int]]:
    profile = await profile_by_email(role, email)
    if not profile or not profile.get("activo", True):
        raise HTTPException(403, "Esta cuenta no está vinculada a un perfil académico activo.")
    if role == "estudiante":
        enrollments = await service_json("matriculas", "/matriculas") or []
        own = [row for row in enrollments if row.get("estudiante_id") == profile["id"]]
        return profile, [row["id"] for row in own]
    schedules = await service_json("horarios", "/horarios") or []
    courses = sorted({row["curso_id"] for row in schedules if row.get("docente_id") == profile["id"]})
    return profile, courses


async def belongs_to_scope(role: str, profile: dict[str, Any], ids: list[int], enrollment_id: int) -> bool:
    enrollment = await service_json("matriculas", f"/matriculas/{enrollment_id}")
    if not enrollment:
        return False
    if role == "estudiante":
        return enrollment.get("estudiante_id") == profile["id"]
    return enrollment.get("curso_id") in ids


async def scoped_rows(service: str, path: str, role: str, profile: dict[str, Any], scope_ids: list[int]) -> Any:
    item_id = resource_id(path)
    if service == "cursos":
        row = await service_json(service, path)
        if path == "/cursos":
            rows = row or []
            if role == "estudiante":
                return [item for item in rows if item.get("activo")]
            return [item for item in rows if item.get("id") in scope_ids and item.get("activo")]
        if role == "estudiante":
            return row if row and row.get("activo") else None
        return row if row and row.get("id") in scope_ids and row.get("activo") else None
    if service == "matriculas":
        rows = await service_json(service, "/matriculas") or []
        if role == "estudiante":
            rows = [row for row in rows if row.get("estudiante_id") == profile["id"]]
        else:
            rows = [row for row in rows if row.get("curso_id") in scope_ids]
        if item_id is not None:
            return next((row for row in rows if row.get("id") == item_id), None)
        return rows
    if service == "calificaciones":
        grades = await service_json(service, "/calificaciones") or []
        visible = []
        for grade in grades:
            if await belongs_to_scope(role, profile, scope_ids, grade.get("matricula_id", 0)):
                visible.append(grade)
        if item_id is not None:
            return next((row for row in visible if row.get("id") == item_id), None)
        return visible
    if service == "horarios":
        rows = await service_json(service, "/horarios") or []
        if role == "estudiante":
            enrollments = await service_json("matriculas", "/matriculas") or []
            course_ids = {row["curso_id"] for row in enrollments if row.get("estudiante_id") == profile["id"] and row.get("estado") == "activa"}
        else:
            course_ids = set(scope_ids)
        rows = [row for row in rows if row.get("curso_id") in course_ids]
        if item_id is not None:
            return next((row for row in rows if row.get("id") == item_id), None)
        return rows
    return None


async def authenticated_user(request: Request) -> dict[str, Any]:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Inicia sesión para usar esta operación.", headers={"WWW-Authenticate": "Bearer"})
    decode_token(authorization.split(" ", 1)[1].strip())
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{SERVICES['usuarios']}/auth/me", headers={"Authorization": authorization})
    except httpx.RequestError:
        raise HTTPException(503, "El servicio de autenticación no está disponible.")
    if response.status_code == 401:
        raise HTTPException(401, "La sesión venció o el usuario ya no está activo.", headers={"WWW-Authenticate": "Bearer"})
    if response.status_code != 200:
        raise HTTPException(503, "No se pudo validar la sesión.")
    return response.json()


async def proxy(service: str, path: str, request: Request, *, body_override: bytes | None = None, method_override: str | None = None) -> Response:
    url = f"{SERVICES[service]}{path}"
    if request.url.query:
        url += "?" + request.url.query
    headers = {
        key: value for key, value in request.headers.items()
        if key.lower() in {"accept", "content-type", "authorization"}
    }
    body = await request.body() if body_override is None else body_override
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            upstream = await client.request(method_override or request.method, url, headers=headers, content=body)
    except httpx.RequestError:
        raise HTTPException(503, f"El microservicio {service} no está disponible.")
    response_headers = {
        key: value for key, value in upstream.headers.items()
        if key.lower() in {"content-type", "content-disposition"}
    }
    return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)


@app.get("/health", tags=["Gateway"])
async def health():
    async def check(name: str, url: str):
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                response = await client.get(f"{url}/health")
            return name, response.status_code == 200
        except httpx.RequestError:
            return name, False
    results = await asyncio.gather(*(check(name, url) for name, url in SERVICES.items()))
    service_states = dict(results)
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            users = await client.get(f"{SERVICES['usuarios']}/usuarios")
        configured = users.status_code == 200 and len(users.json()) > 0
    except Exception:
        configured = False
    return {"gateway": "activo", "servicios": service_states, "administrador_configurado": configured}


@app.post("/auth/bootstrap", tags=["Autenticación"])
async def bootstrap(request: Request):
    """Crea una sola vez el primer administrador; Usuarios valida la operación de forma atómica."""
    return await proxy("usuarios", "/auth/bootstrap", request)


@app.post("/auth/login", tags=["Autenticación"])
async def login(request: Request):
    return await proxy("usuarios", "/auth/login", request)


@app.get("/auth/me", tags=["Autenticación"])
async def me(request: Request, _: HTTPAuthorizationCredentials | None = Depends(bearer)):
    return await authenticated_user(request)


@app.get("/portal/docente/cursos", tags=["Portal docente"])
async def teacher_course_roster(request: Request):
    user = await authenticated_user(request)
    if user.get("rol") != "docente":
        raise HTTPException(403, "Esta vista es exclusiva para docentes.")
    profile, course_ids = await rows_for_user("docente", user["correo"])
    courses, students, enrollments, schedules = await asyncio.gather(
        service_json("cursos", "/cursos"),
        service_json("estudiantes", "/estudiantes"),
        service_json("matriculas", "/matriculas"),
        service_json("horarios", "/horarios"),
    )
    students_by_id = {row["id"]: row for row in students or []}
    schedules_by_course: dict[int, list[dict[str, Any]]] = {}
    for schedule in schedules or []:
        if schedule.get("docente_id") == profile["id"]:
            schedules_by_course.setdefault(schedule["curso_id"], []).append(schedule)
    result = []
    for course in courses or []:
        course_id = course["id"]
        if course_id not in course_ids or not course.get("activo"):
            continue
        roster = []
        for enrollment in enrollments or []:
            if enrollment.get("curso_id") != course_id:
                continue
            student = students_by_id.get(enrollment.get("estudiante_id"), {})
            roster.append({
                "matricula_id": enrollment["id"],
                "estudiante_id": enrollment["estudiante_id"],
                "documento": student.get("documento", "—"),
                "nombres": student.get("nombres", "Perfil no disponible"),
                "apellidos": student.get("apellidos", ""),
                "correo": student.get("correo", ""),
                "programa": student.get("programa", ""),
                "semestre": student.get("semestre", ""),
                "estado": enrollment.get("estado", "desconocido"),
                "fecha": enrollment.get("fecha", ""),
            })
        result.append({**course, "horarios": schedules_by_course.get(course_id, []), "estudiantes": roster})
    return {"docente": {"id": profile["id"], "nombre": f"{profile['nombres']} {profile['apellidos']}"}, "cursos": result}


@app.get("/docs/{service}", include_in_schema=False)
async def service_docs(service: str):
    if service not in SERVICES:
        raise HTTPException(404, "No existe documentación para ese servicio.")
    return get_swagger_ui_html(
        openapi_url=f"/openapi/{service}.json",
        title=f"{service.capitalize()} — Swagger",
    )


@app.get("/openapi/{service}.json", include_in_schema=False)
async def service_openapi(service: str):
    if service not in SERVICES:
        raise HTTPException(404, "No existe documentación para ese servicio.")
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            upstream = await client.get(f"{SERVICES[service]}/openapi.json")
        except httpx.RequestError:
            raise HTTPException(503, f"El microservicio {service} no está disponible.")
    try:
        spec = upstream.json()
    except ValueError:
        raise HTTPException(502, "El microservicio devolvió una especificación OpenAPI inválida.")
    spec["servers"] = [{"url": f"/api/{service}"}]
    spec.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {
        "type": "http", "scheme": "bearer", "bearerFormat": "JWT",
    }
    for route_path, operations in spec.get("paths", {}).items():
        for method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            if route_path == "/auth/login" and method.lower() == "post":
                operation["security"] = []
            else:
                operation["security"] = [{"BearerAuth": []}]
    return JSONResponse(content=spec, status_code=upstream.status_code)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
async def route(path: str, request: Request):
    service, upstream_path = identify_service(path)
    method = request.method.upper()
    public_routes = {("POST", "/auth/login")}
    if (method, upstream_path) in public_routes:
        return await proxy(service, upstream_path, request)
    user = await authenticated_user(request)
    role = user["rol"]
    if not allowed(role, method, upstream_path):
        raise HTTPException(403, "Tu rol no tiene permiso para realizar esta operación.")

    if role == "administrador":
        if service == "usuarios" and method == "POST" and upstream_path == "/usuarios":
            try:
                payload = await request.json()
            except ValueError:
                raise HTTPException(400, "El cuerpo JSON no es válido.")
            if payload.get("rol") in {"estudiante", "docente"}:
                profile = await profile_by_email(payload["rol"], payload.get("correo", ""))
                if not profile or not profile.get("activo", True):
                    raise HTTPException(422, "Primero crea un perfil académico activo con el mismo correo.")
        return await proxy(service, upstream_path, request)

    if role in {"estudiante", "docente"}:
        profile, scope_ids = await rows_for_user(role, user["correo"])
        item_id = resource_id(upstream_path)

        if role == "estudiante" and service == "matriculas" and method == "POST" and upstream_path == "/matriculas":
            try:
                payload = await request.json()
            except ValueError:
                raise HTTPException(400, "El cuerpo JSON no es válido.")
            payload["estudiante_id"] = profile["id"]
            return await proxy(service, upstream_path, request, body_override=json.dumps(payload).encode())

        if role == "estudiante" and service == "matriculas" and method in {"PUT", "DELETE"} and item_id is not None:
            owned = await scoped_rows(service, "/matriculas", role, profile, scope_ids)
            if not any(row.get("id") == item_id for row in owned):
                raise HTTPException(404, "Matrícula no encontrada.")
            if method == "DELETE" or upstream_path.endswith("/cancelar"):
                cancel_path = f"/matriculas/{item_id}/cancelar"
                return await proxy(service, cancel_path, request, method_override="PUT")
            raise HTTPException(403, "Solo puedes dar de baja una matrícula propia.")

        if service in {"cursos", "matriculas", "calificaciones", "horarios"} and method == "GET":
            if service == "cursos" and upstream_path.startswith("/cursos"):
                pass
            elif service == "matriculas" and upstream_path.startswith("/matriculas"):
                pass
            elif service == "calificaciones" and upstream_path.startswith("/calificaciones"):
                pass
            elif service == "horarios" and upstream_path.startswith("/horarios"):
                pass
            else:
                raise HTTPException(403, "Tu rol no puede consultar este recurso.")
            result = await scoped_rows(service, upstream_path, role, profile, scope_ids)
            if result is None:
                raise HTTPException(404, "Registro no encontrado en tu perfil académico.")
            return JSONResponse(content=result)

        if role == "docente" and service == "calificaciones" and method in {"POST", "PUT"}:
            try:
                payload = await request.json()
            except ValueError:
                raise HTTPException(400, "El cuerpo JSON no es válido.")
            if not await belongs_to_scope(role, profile, scope_ids, int(payload.get("matricula_id", 0))):
                raise HTTPException(403, "Solo puedes registrar o cambiar notas de matrículas en tus cursos asignados.")
            if method == "PUT" and item_id is not None:
                own_grades = await scoped_rows("calificaciones", "/calificaciones", role, profile, scope_ids)
                if not any(row.get("id") == item_id for row in own_grades):
                    raise HTTPException(404, "Calificación no encontrada en tus cursos.")
            return await proxy(service, upstream_path, request)

    raise HTTPException(403, "Tu rol no tiene permiso para realizar esta operación.")
