# Frontend de la Plataforma Académica

Abre una terminal en esta carpeta y ejecuta:

```powershell
py -m http.server 5500 --bind 127.0.0.1
```

Luego visita `http://127.0.0.1:5500`. La página se comunica únicamente con el API Gateway en `http://127.0.0.1:8080`; deben estar activos Gateway y los siete microservicios. La primera cuenta se crea como administrador y luego se inicia sesión. El menú y las operaciones disponibles dependen del rol. Cada panel enlaza Swagger a través del Gateway.
