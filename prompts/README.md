# CodePilot — Secuencia de prompts para OpenCode con Gentle AI

Los prompts están pensados para ejecutarse en orden.

## Modelo recomendado

- **Sol:** análisis, arquitectura, planificación y revisión.
- **Luna:** implementación, tests, refactorización y documentación.

## Orden

1. Foundation and architecture baseline
2. Configuration, logging and error handling
3. Persistence model and Alembic
4. Secure repository ingestion
5. Asynchronous analysis orchestration
6. Analyzer plugin system
7. Python static analysis adapters
8. JavaScript/TypeScript and .NET adapters
9. Git history intelligence and hotspots
10. Dependency graph and architecture insights
11. Explainable risk score and quality gates
12. MVP frontend dashboard
13. LiteLLM AI enrichment
14. GitHub App and pull-request analysis
15. Public MVP hardening

## Uso

Abre OpenCode desde la raíz del repositorio y pega el contenido completo del prompt correspondiente.

No ejecutes varios prompts de implementación simultáneamente. Revisa el resultado y deja el repositorio estable antes de continuar.

Ruta solicitada en tu equipo:

```text
C:\Source\codepilot\prompts
```

Este paquete debe descomprimirse dentro de esa carpeta.
