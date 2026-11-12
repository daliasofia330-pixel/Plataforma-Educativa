# Plataforma Académica Universitaria — Equipo 4

Avance de la plataforma académica para administrar Usuarios, Estudiantes, Docentes, Cursos, Matrículas, Calificaciones y Horarios. Cada dominio es una API FastAPI independiente con su propia base SQLite. El cliente entra por el API Gateway, que valida JWT y aplica permisos por rol.

## Componentes y direcciones

En Docker, los servicios internos no publican puertos al computador: el único punto de entrada de la aplicación es el Gateway en `http://127.0.0.1:8080`.

| Componente | Puerto interno | Datos persistentes | Swagger a través del Gateway |
|---|---:|---|---|
| API Gateway | 8080 | — | `http://127.0.0.1:8080/docs` |
| Cursos | 8000 | `cursos_data` | `http://127.0.0.1:8080/docs/cursos` |
| Estudiantes | 8001 | `estudiantes_data` | `http://127.0.0.1:8080/docs/estudiantes` |
| Matrículas | 8002 | `matriculas_data` | `http://127.0.0.1:8080/docs/matriculas` |
| Docentes | 8003 | `docentes_data` | `http://127.0.0.1:8080/docs/docentes` |
| Calificaciones | 8004 | `calificaciones_data` | `http://127.0.0.1:8080/docs/calificaciones` |
| Usuarios | 8005 | `usuarios_data` | `http://127.0.0.1:8080/docs/usuarios` |
| Horarios | 8006 | `horarios_data` | `http://127.0.0.1:8080/docs/horarios` |

El frontend se sirve en `http://127.0.0.1:5500` y consume solo el Gateway. Las rutas se publican bajo `/api/{servicio}/...`; por ejemplo, Cursos se consulta en `http://127.0.0.1:8080/api/cursos/cursos` y Estudiantes en `http://127.0.0.1:8080/api/estudiantes/estudiantes`.

Al publicarlo, Caddy sirve el frontend y reenvía las rutas del API al Gateway bajo el mismo dominio. Así el navegador no apunta al `localhost` de cada visitante. El Gateway queda enlazado solo a `127.0.0.1` del servidor; el tráfico externo entra por Caddy.

## Arranque con Docker Compose

Requiere Docker Desktop con el motor activo. Desde la raíz de esta carpeta:

```powershell
docker compose up --build
```

Compose crea siete bases persistentes independientes y espera a que los servicios relacionados estén listos. En otra terminal, sirve el frontend:

```powershell
cd .\frontend
py -m http.server 5500 --bind 127.0.0.1
```

Abre `http://127.0.0.1:5500`. Mantén ambas terminales abiertas. Para detener Compose, pulsa `Ctrl+C`.

## Compartir gratis para una demostración temporal

Para una presentación corta, puedes crear una URL pública temporal sin comprar VPS ni dominio usando Cloudflare Quick Tunnel. Requiere conexión a Internet y que el computador y Docker permanezcan encendidos. La dirección aleatoria deja de funcionar cuando se detiene el túnel y puede cambiar al volver a iniciarlo. Es para pruebas, no para alojar el sistema permanentemente; cualquiera que tenga el enlace puede abrirlo.

Desde la raíz del proyecto ejecuta:

```powershell
docker compose -f compose.yaml -f compose.demo.yaml up --build -d
docker compose -f compose.yaml -f compose.demo.yaml logs -f cloudflared
```

Copia la URL `https://...trycloudflare.com` que aparece en los registros y ábrela para comprobar el sitio. Mantén Docker Desktop y el computador activos durante la sustentación. Para dejar de exponerlo y detener los servicios:

```powershell
docker compose -f compose.yaml -f compose.demo.yaml down
```

Usa solo datos ficticios en esta demostración pública. Cloudflare documenta que estos túneles son temporales y no tienen garantía de disponibilidad.

## Despliegue en un VPS

El proyecto incluye `compose.prod.yaml` y `deploy/Caddyfile` para un servidor Linux con Docker Compose. Caddy sirve el frontend, redirige el tráfico al Gateway y obtiene/renueva HTTPS automáticamente cuando el dominio ya apunta al VPS y los puertos 80 y 443 están abiertos.

1. Crea un VPS Ubuntu y un dominio o subdominio. Configura un registro DNS `A` para que apunte a la IP pública del servidor. Instala Docker Engine con el complemento Compose.
2. Copia/clona esta carpeta al servidor y entra a su raíz (donde están `compose.yaml` y `compose.prod.yaml`).
3. Crea `.env` a partir de `.env.example`; configura `DOMAIN` con el dominio real y genera una clave larga para `JWT_SECRET` (por ejemplo, `openssl rand -hex 32`). No publiques ni compartas `.env`.
4. Permite en el firewall del proveedor y del servidor los puertos TCP 22, 80 y 443. El 22 debe limitarse a las IPs administrativas cuando sea posible.
5. Levanta la plataforma: `docker compose -f compose.yaml -f compose.prod.yaml up -d --build`.
6. Abre `https://TU_DOMINIO` y crea la cuenta administradora en “Primer inicio”. Confirma `/health` y la disponibilidad de los siete servicios antes de compartir el enlace.

La primera instalación en el VPS empieza con bases de datos nuevas: los volúmenes persistentes no se transfieren desde Docker Desktop automáticamente. Conserva el `.env` y programa copias de seguridad de los volúmenes SQLite. Si el servidor se pierde y no hay respaldo, también se pierden los datos. Para actualizar el sitio, ejecuta el comando del paso 5 después de subir los cambios.

## Ejecutar localmente sin Docker

En cada carpeta de servicio (`microservicio-estudiantes`, `microservicio-matriculas`, `microservicio-docentes`, `microservicio-calificaciones`, `microservicio-usuarios`, `microservicio-horarios` y `api-gateway`) crea el entorno e instala sus dependencias una sola vez:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Hazlo también en la raíz para Cursos. Luego abre una terminal por componente: desde su propia carpeta ejecuta `.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port PUERTO`, reemplazando `PUERTO` con el de la tabla. En la raíz de Cursos el comando es `.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000`. Inicia primero las siete APIs, después el Gateway en el puerto 8080 y por último el frontend en el puerto 5500. Las direcciones internas predeterminadas del Gateway apuntan a `127.0.0.1:8000`–`8006`.

## Primer inicio, login y permisos

La primera persona que abra el frontend debe usar **Primer inicio** para crear el administrador inicial. Esta operación solo funciona si la base de Usuarios todavía no tiene cuentas. Luego inicia sesión con ese correo y contraseña. Para crear cuentas de estudiantes o docentes, el administrador primero registra el perfil académico y después crea la cuenta con **el mismo correo** y el rol correspondiente. El Gateway verifica la coincidencia antes de guardar la cuenta; perfiles inexistentes o inactivos no pueden autenticarse con un rol académico.

El servicio de Usuarios almacena las contraseñas con PBKDF2 y entrega tokens Bearer firmados con HS256 que vencen en una hora. El Gateway verifica el token y consulta Usuarios para confirmar que la cuenta siga activa antes de aceptar cada operación.

| Rol | Permisos en el Gateway |
|---|---|
| Administrador | Puede consultar, crear y eliminar registros en todos los servicios. |
| Docente | Consulta sus cursos, los estudiantes matriculados y sus estados. Puede crear y cambiar notas solo para matrículas activas en cursos asignados mediante horarios. Al calificar, selecciona curso y estudiante desde listas; no necesita adivinar IDs. |
| Estudiante | Consulta cursos activos, sus propias matrículas, sus calificaciones y horarios de sus cursos activos. Puede inscribirse en cursos con cupo y dar de baja sus propias matrículas. No puede elegir el ID de otro estudiante en la solicitud: el Gateway lo deriva de su cuenta. |

Los permisos se aplican en el API Gateway, no solo en la interfaz. Las consultas de estudiantes y docentes se filtran por el perfil asociado al correo de su cuenta. El portal docente agrupa la lista por curso e incluye ID de matrícula, documento, nombre, programa, semestre y estado. El formulario de calificaciones solo ofrece estudiantes con matrícula activa del curso elegido. Las matrículas canceladas conservan su historial y liberan el cupo para una inscripción posterior.

Swagger permite probar rutas protegidas: inicia sesión en `POST /auth/login`, copia `access_token`, pulsa **Authorize** y escribe `Bearer ` seguido del token. El token también se envía automáticamente desde el frontend.

## Integración entre dominios

- Matrículas valida por API que el estudiante y el curso existan y estén activos, y revisa cupos.
- Calificaciones valida por API que la matrícula exista y esté activa.
- Horarios valida por API que el curso y el docente existan y estén activos.
- Cada API conserva sus propias tablas; no se comparten tablas entre dominios.
- La comunicación implementada es HTTP/JSON síncrona, apropiada para las validaciones inmediatas de esta demostración. La guía sugiere mensajería asíncrona solo cuando el caso de uso la justifique; no se agregó RabbitMQ/Kafka.

## Flujo para la sustentación

1. Crear el primer administrador e iniciar sesión.
2. Como administrador, registrar un curso, un perfil de estudiante y un perfil de docente.
3. Crear las cuentas de estudiante y docente usando el mismo correo de sus perfiles; compartir cada correo y contraseña con su usuario por el canal acordado.
4. Asignar un horario al curso y docente para habilitar el acceso docente a ese curso.
5. Como administrador o estudiante, inscribir al estudiante en el curso; como estudiante, consultar sus propias matrículas y calificaciones.
6. Como docente asignado, registrar y actualizar una calificación de esa matrícula.
7. Como estudiante, dar de baja una matrícula propia y comprobar que no puede modificar notas ni consultar registros de otros perfiles.
8. Mostrar las tablas y las respuestas protegidas desde Swagger a través del Gateway.

## Código fuente

- `main.py`: microservicio de Cursos.
- `microservicio-estudiantes/`, `microservicio-docentes/`, `microservicio-matriculas/`, `microservicio-calificaciones/`, `microservicio-usuarios/`, `microservicio-horarios/`: APIs, Dockerfile y requisitos por servicio.
- `api-gateway/`: enrutamiento, validación de token, permisos, health y Swagger de servicios.
- `frontend/`: aplicación web de la demostración.
- `compose.yaml`: despliegue integrado.

## Estado y precauciones

Los Dockerfiles, el Gateway, la autorización y el despliegue conjunto están implementados en código; aún deben probarse con Docker y un flujo completo en el computador que se usará para sustentar. Solo se han revisado sintaxis de Python y JavaScript; todavía falta una batería de pruebas funcionales con evidencias.

El secreto incluido en Compose es solo para demostración local. Cámbialo por un secreto privado antes de desplegar fuera del entorno académico. Las APIs están protegidas al acceder por el Gateway; en Docker solo el Gateway publica un puerto al host.
