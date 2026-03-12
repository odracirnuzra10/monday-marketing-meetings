# Reporte Diario - Reuniones Marketing

Automatización que envía un reporte diario a Google Chat con el análisis de reuniones de marketing desde Monday.com.

## Configuración en GitHub

### 1. Secrets (Settings > Secrets and variables > Actions)

| Secret | Descripción |
|--------|------------|
| `MONDAY_API_TOKEN` | Token de API de Monday.com |
| `GOOGLE_CHAT_WEBHOOK` | URL del webhook de Google Chat |

### 2. Variables (opcional)

| Variable | Default | Descripción |
|----------|---------|------------|
| `MONDAY_BOARD_ID` | `18403745516` | ID del board de reuniones |

### Obtener el token de Monday.com

1. Ve a monday.com > Tu avatar > Administration
2. API > Personal API Token
3. Copia el token

## Ejecución

- **Automática:** Lunes a Viernes a las 18:00 Chile (21:00 UTC)
- **Manual:** Actions > Reporte Diario Reuniones Marketing > Run workflow

## Qué incluye el reporte

- Resumen general (realizadas vs programadas)
- Reuniones por ejecutivo (Brian, Francis, Franco, Daniel, Eduardo)
- Distribución por tipo (Ventas, Marketing, Administración, Retención)
- Satisfacción promedio del cliente
- Reuniones de hoy y próximas 7 días
- Hitos clave recientes
- Indicadores (más activo, mejor satisfacción, tipo más frecuente)
