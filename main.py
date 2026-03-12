"""
Reporte Diario de Reuniones Marketing - Panel de Gestión
Extrae datos de Monday.com, analiza reuniones por ejecutivo,
tipo de reunión, satisfacción y envía resumen a Google Chat.
"""

import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# ─── Configuración ───────────────────────────────────────────────
MONDAY_API_TOKEN = os.environ["MONDAY_API_TOKEN"]
GOOGLE_CHAT_WEBHOOK = os.environ["GOOGLE_CHAT_WEBHOOK"]
BOARD_ID = os.environ.get("MONDAY_BOARD_ID", "18403745516")

MONDAY_API_URL = "https://api.monday.com/v2"

# Columnas del tablero
COL_EJECUTIVO = "multiple_person_mm1cbx62"
COL_TIPO_REUNION = "color_mm1ce47q"
COL_FECHA = "date_mm1cyjth"
COL_HITOS = "long_text_mm1c3azq"
COL_SATISFACCION = "rating_mm1ckjer"

# Grupos
GROUP_REALIZADAS = "group_mm1cq232"
GROUP_PROGRAMADAS = "group_mm1c5bar"

# Tipos de reunión (index -> label)
TIPO_REUNION_MAP = {
    0: "Ventas",
    1: "Marketing",
    2: "Administración",
    9: "Retención",
}

# Ejecutivos conocidos
EJECUTIVOS = {
    "82423932": "Brian",
    "98564315": "Francis",
    "98933770": "Franco",
    "82475640": "Daniel",
    "97018678": "Eduardo",
}

CHILE_TZ = timezone(timedelta(hours=-3))


# ─── API Monday.com ──────────────────────────────────────────────
def monday_query(query: str, variables: dict = None) -> dict:
    """Ejecuta una query GraphQL en Monday.com."""
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        MONDAY_API_URL,
        data=payload,
        headers={
            "Authorization": MONDAY_API_TOKEN,
            "Content-Type": "application/json",
            "API-Version": "2024-10",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_all_items() -> list:
    """Obtiene todos los items del tablero con sus columnas."""
    items = []
    cursor = None

    while True:
        if cursor:
            query = """
            query ($cursor: String!) {
                next_items_page(cursor: $cursor, limit: 200) {
                    cursor
                    items {
                        id
                        name
                        updated_at
                        group { id title }
                        column_values {
                            id
                            text
                            value
                            ... on StatusValue { index }
                            ... on PeopleValue { persons_and_teams { id kind } }
                            ... on RatingValue { rating }
                        }
                    }
                }
            }
            """
            variables = {"cursor": cursor}
            data = monday_query(query, variables)
            page = data["data"]["next_items_page"]
        else:
            query = """
            query ($boardId: [ID!]!) {
                boards(ids: $boardId) {
                    items_page(limit: 200) {
                        cursor
                        items {
                            id
                            name
                            updated_at
                            group { id title }
                            column_values {
                                id
                                text
                                value
                                ... on StatusValue { index }
                                ... on PeopleValue { persons_and_teams { id kind } }
                                ... on RatingValue { rating }
                            }
                        }
                    }
                }
            }
            """
            variables = {"boardId": [BOARD_ID]}
            data = monday_query(query, variables)
            page = data["data"]["boards"][0]["items_page"]

        items.extend(page["items"])
        cursor = page.get("cursor")
        if not cursor:
            break

    return items


def fetch_users(user_ids: list) -> dict:
    """Obtiene nombres de usuarios por ID."""
    if not user_ids:
        return {}
    query = """
    query ($ids: [ID!]!) {
        users(ids: $ids) { id name }
    }
    """
    data = monday_query(query, {"ids": user_ids})
    users = data.get("data", {}).get("users", [])
    return {u["id"]: u["name"] for u in users}


# ─── Procesamiento de datos ─────────────────────────────────────
def parse_item(item: dict) -> dict:
    """Convierte un item raw de Monday en un dict limpio."""
    cols = {}
    for cv in item["column_values"]:
        cols[cv["id"]] = cv

    # Extraer ejecutivo
    exec_col = cols.get(COL_EJECUTIVO, {})
    exec_id = None
    exec_name = None
    persons = exec_col.get("persons_and_teams", [])
    if persons:
        exec_id = str(persons[0]["id"])
        exec_name = EJECUTIVOS.get(exec_id, exec_col.get("text", "").strip())
    else:
        exec_name = exec_col.get("text", "").strip() or None

    # Extraer tipo de reunión
    tipo_col = cols.get(COL_TIPO_REUNION, {})
    tipo_index = tipo_col.get("index")
    tipo_label = TIPO_REUNION_MAP.get(tipo_index, tipo_col.get("text", "Sin tipo"))

    # Extraer satisfacción
    sat_col = cols.get(COL_SATISFACCION, {})
    rating = sat_col.get("rating")
    if rating is None:
        # Intentar desde text
        try:
            rating = int(sat_col.get("text", "0") or "0")
        except (ValueError, TypeError):
            rating = 0

    # Extraer fecha
    fecha_text = cols.get(COL_FECHA, {}).get("text", "")

    # Extraer hitos
    hitos_text = cols.get(COL_HITOS, {}).get("text", "")

    return {
        "id": item["id"],
        "cliente": item["name"],
        "updated_at": item["updated_at"],
        "group_id": item.get("group", {}).get("id", ""),
        "group_title": item.get("group", {}).get("title", ""),
        "exec_id": exec_id,
        "exec_name": exec_name,
        "tipo_reunion": tipo_label,
        "tipo_index": tipo_index,
        "fecha": fecha_text,
        "hitos": hitos_text,
        "satisfaccion": rating,
    }


# ─── Análisis ────────────────────────────────────────────────────
def analyze(items: list) -> dict:
    """Analiza todos los items y genera métricas."""
    now = datetime.now(CHILE_TZ)
    today = now.date()

    realizadas = [i for i in items if i["group_id"] == GROUP_REALIZADAS]
    programadas = [i for i in items if i["group_id"] == GROUP_PROGRAMADAS]

    # --- Reuniones por ejecutivo ---
    por_ejecutivo = defaultdict(lambda: {"realizadas": 0, "programadas": 0, "clientes": [], "ratings": []})
    for item in realizadas:
        name = item["exec_name"] or "Sin asignar"
        por_ejecutivo[name]["realizadas"] += 1
        por_ejecutivo[name]["clientes"].append(item["cliente"])
        if item["satisfaccion"] and item["satisfaccion"] > 0:
            por_ejecutivo[name]["ratings"].append(item["satisfaccion"])
    for item in programadas:
        name = item["exec_name"] or "Sin asignar"
        por_ejecutivo[name]["programadas"] += 1

    # --- Reuniones por tipo ---
    por_tipo = defaultdict(lambda: {"realizadas": 0, "programadas": 0})
    for item in realizadas:
        por_tipo[item["tipo_reunion"]]["realizadas"] += 1
    for item in programadas:
        por_tipo[item["tipo_reunion"]]["programadas"] += 1

    # --- Satisfacción general ---
    all_ratings = [i["satisfaccion"] for i in realizadas if i["satisfaccion"] and i["satisfaccion"] > 0]
    avg_rating = sum(all_ratings) / len(all_ratings) if all_ratings else 0

    # --- Próximas reuniones (7 días) ---
    proximas = []
    for item in programadas:
        if item["fecha"]:
            try:
                fecha = datetime.strptime(item["fecha"].split(" ")[0], "%Y-%m-%d").date()
                dias_faltan = (fecha - today).days
                if 0 <= dias_faltan <= 7:
                    proximas.append({**item, "dias_faltan": dias_faltan, "fecha_obj": fecha})
            except ValueError:
                continue
    proximas.sort(key=lambda x: x["fecha_obj"])

    # --- Reuniones de hoy ---
    reuniones_hoy = []
    for item in items:
        if item["fecha"]:
            try:
                fecha = datetime.strptime(item["fecha"].split(" ")[0], "%Y-%m-%d").date()
                if fecha == today:
                    reuniones_hoy.append(item)
            except ValueError:
                continue

    # --- Hitos pendientes (reuniones realizadas con hitos) ---
    con_hitos = [i for i in realizadas if i["hitos"] and len(i["hitos"].strip()) > 0]

    # --- Ranking satisfacción por ejecutivo ---
    ranking_satisfaccion = {}
    for name, data in por_ejecutivo.items():
        if data["ratings"]:
            ranking_satisfaccion[name] = sum(data["ratings"]) / len(data["ratings"])

    return {
        "total": len(items),
        "total_realizadas": len(realizadas),
        "total_programadas": len(programadas),
        "items_realizadas": realizadas,
        "por_ejecutivo": dict(por_ejecutivo),
        "por_tipo": dict(por_tipo),
        "avg_rating": avg_rating,
        "total_ratings": len(all_ratings),
        "proximas": proximas,
        "reuniones_hoy": reuniones_hoy,
        "con_hitos": con_hitos,
        "ranking_satisfaccion": ranking_satisfaccion,
        "now": now,
    }


# ─── Formateo del mensaje ───────────────────────────────────────
def summarize_hitos(items_realizadas: list) -> str:
    """Resume los hitos de un ejecutivo en una frase corta."""
    hitos = [i["hitos"].strip() for i in items_realizadas if i["hitos"] and i["hitos"].strip()]
    if not hitos:
        return "sin notas importantes"
    # Concatenar todos los hitos y truncar a algo legible
    combined = ". ".join(h.replace("\n", " ").strip() for h in hitos)
    if len(combined) > 120:
        combined = combined[:117] + "..."
    return combined.lower()


def format_report(analysis: dict) -> str:
    """Genera el mensaje breve para Google Chat."""
    now = analysis["now"]
    day_names = {
        0: "Lunes", 1: "Martes", 2: "Miércoles",
        3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"
    }
    day_name = day_names[now.weekday()]
    date_str = f"{day_name} {now.day}/{now.month:02d}"

    lines = []

    # ── Header ──
    lines.append(f"📊 *Reuniones Marketing* — {date_str}")
    lines.append(f"✅ {analysis['total_realizadas']} realizadas | 📅 {analysis['total_programadas']} programadas | ⭐ {analysis['avg_rating']:.1f}/5 promedio")
    lines.append("")

    # ── Una línea por ejecutivo ──
    sorted_execs = sorted(
        analysis["por_ejecutivo"].items(),
        key=lambda x: x[1]["realizadas"],
        reverse=True,
    )

    # Recopilar items realizados por ejecutivo para extraer hitos
    realizadas_por_exec = defaultdict(list)
    for item in analysis.get("items_realizadas", []):
        name = item["exec_name"] or "Sin asignar"
        realizadas_por_exec[name].append(item)

    for exec_name, data in sorted_execs:
        avg = analysis["ranking_satisfaccion"].get(exec_name, 0)
        avg_str = f"{avg:.1f}" if avg > 0 else "s/d"
        nota = summarize_hitos(realizadas_por_exec.get(exec_name, []))
        lines.append(f"*{exec_name}*: {data['realizadas']} reuniones, {avg_str} de satisfacción, {nota}")

    # ── Tipos (una línea compacta) ──
    if analysis["por_tipo"]:
        lines.append("")
        tipos_parts = []
        for tipo, data in sorted(analysis["por_tipo"].items(), key=lambda x: x[1]["realizadas"], reverse=True):
            tipos_parts.append(f"{tipo}: {data['realizadas']}")
        lines.append(f"🏷️ {' | '.join(tipos_parts)}")

    # ── Próximas (solo si hay) ──
    if analysis["proximas"]:
        lines.append("")
        lines.append(f"📅 *Próximas:*")
        for item in analysis["proximas"][:5]:
            exec_short = item["exec_name"] or "?"
            lines.append(f"• {item['fecha']} → {item['cliente']} ({exec_short})")

    lines.append("")
    lines.append(f"🔗 <https://metricads-chile.monday.com/boards/{BOARD_ID}|Ver tablero>")

    return "\n".join(lines)


# ─── Envío a Google Chat ────────────────────────────────────────
def send_to_google_chat(message: str):
    """Envía un mensaje a Google Chat via webhook."""
    payload = json.dumps({"text": message}).encode()
    req = urllib.request.Request(
        GOOGLE_CHAT_WEBHOOK,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read().decode())
        print(f"Mensaje enviado a Google Chat: {result.get('name', 'OK')}")


# ─── Main ────────────────────────────────────────────────────────
def main():
    print("🚀 Iniciando reporte diario de reuniones marketing...")
    print(f"⏰ {datetime.now(CHILE_TZ).strftime('%Y-%m-%d %H:%M:%S')} Chile")

    # 1. Obtener items
    print("📥 Obteniendo items del tablero...")
    raw_items = fetch_all_items()
    print(f"   → {len(raw_items)} items obtenidos")

    # 2. Parsear items
    items = [parse_item(i) for i in raw_items]

    # 3. Analizar
    print("🔍 Analizando datos...")
    analysis = analyze(items)

    # 4. Generar reporte
    print("📊 Generando reporte...")
    report = format_report(analysis)

    # Preview
    print("\n" + "=" * 50)
    print(report)
    print("=" * 50 + "\n")

    # 5. Enviar
    print("📤 Enviando a Google Chat...")
    send_to_google_chat(report)

    print("✅ Reporte enviado exitosamente!")


if __name__ == "__main__":
    main()
