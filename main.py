import os
import re
import requests
import mysql.connector
import json
from datetime import date, timedelta, datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env
load_dotenv()

app = Flask(__name__)

# ---------------------------
# CONFIGURACIÓN DE LA BASE DE DATOS (XAMPP)
# ---------------------------
db_config = {
    'host': os.getenv("DB_HOST"),
    'port': int(os.getenv("DB_PORT")),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'database': os.getenv("DB_DATABASE")
}

# ---------------------------
# CONFIGURACIÓN DEL ENDPOINT DE OPENAI (Azure)
# ---------------------------
openai_endpoint = os.getenv("OPENAI_ENDPOINT")
api_key = os.getenv("OPENAI_API_KEY")

# ---------------------------
# MAPEO DE MESES (para extraer fechas)
# ---------------------------
month_map = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

# ---------------------------
# FUNCIONES PARA EXTRAER FECHA, MENÚ Y CÉDULA
# ---------------------------
def extract_date_from_text(text):
    text_lower = text.lower()
    if "mañana" in text_lower:
        return date.today() + timedelta(days=1)
    if "hoy" in text_lower:
        return date.today()
    pattern = r"(\d{1,2})\s+de\s+([a-záéíóúñ]+)(?:\s+del?\s+(\d{4}))?"
    match = re.search(pattern, text_lower)
    if match:
        day = int(match.group(1))
        month_name = match.group(2).strip()
        year = int(match.group(3)) if match.group(3) else date.today().year
        month = month_map.get(month_name, None)
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass
    return date.today() + timedelta(days=1)

def extract_menu_option(text):
    match = re.search(r"men[úu]\s*(\d+)", text.lower())
    if match:
        return match.group(1)
    return None

def extract_cedula(text):
    match = re.search(r"cedula\s*:\s*(\w+)", text.lower())
    if match:
        return match.group(1)
    return None

# ---------------------------
# DETECCIÓN DE INTENCIÓN
# ---------------------------
def parse_intent(text):
    text_lower = text.lower()
    if "cancelar" in text_lower:
        return "cancelacion"
    elif "editar" in text_lower or "modificar" in text_lower:
        return "editar_reserva"
    elif "mis reservas" in text_lower or "consultar reservas" in text_lower:
        return "consulta_reservas"
    elif "reservar" in text_lower or "reserva" in text_lower:
        return "reserva"
    elif (("todos" in text_lower or "cuales" in text_lower or "lista" in text_lower or "varios" in text_lower)
          and ("menú" in text_lower or "menus" in text_lower)):
        return "consulta_completa"
    else:
        return "consulta"

# ---------------------------
# FUNCIONES DE ACCESO A LA BASE DE DATOS
# ---------------------------
def get_menu_for_date(target_date, menu_option=None):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True, buffered=True)
        if menu_option:
            query = "SELECT * FROM menu WHERE fecha = %s AND descripcion LIKE %s"
            like_pattern = "%" + f"menú {menu_option}" + "%"
            cursor.execute(query, (target_date.isoformat(), like_pattern))
        else:
            query = "SELECT * FROM menu WHERE fecha = %s"
            cursor.execute(query, (target_date.isoformat(),))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result
    except Exception as e:
        print("Error al consultar el menú:", e)
        return None

def get_all_menus_for_date(target_date):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True, buffered=True)
        query = "SELECT * FROM menu WHERE fecha = %s ORDER BY id"
        cursor.execute(query, (target_date.isoformat(),))
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        return results
    except Exception as e:
        print("Error al consultar todos los menús:", e)
        return []

def create_reservation(target_date, cedula, menu_option):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        query = """
            INSERT INTO reservations (fecha, cedula, menu_option, estado)
            VALUES (%s, %s, %s, 'reservado')
        """
        cursor.execute(query, (target_date.isoformat(), cedula, menu_option))
        conn.commit()
        reservation_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return reservation_id
    except Exception as e:
        print("Error al crear la reserva:", e)
        return None

def cancel_reservation(cedula, target_date):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        query = """
            UPDATE reservations 
            SET estado = 'cancelado', updated_at = NOW()
            WHERE cedula = %s AND fecha = %s AND estado NOT IN ('cancelado','eliminado')
        """
        cursor.execute(query, (cedula, target_date.isoformat()))
        conn.commit()
        rows_updated = cursor.rowcount
        cursor.close()
        conn.close()
        return rows_updated
    except Exception as e:
        print("Error al cancelar la reserva:", e)
        return 0

def get_reservations_by_user(cedula, target_date=None):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True, buffered=True)
        if target_date:
            query = """
            SELECT r.id, r.fecha, r.menu_option, r.estado, m.descripcion AS menu_descripcion
            FROM reservations r
            LEFT JOIN menu m ON r.fecha = m.fecha AND m.descripcion LIKE CONCAT('%Menú ', r.menu_option, '%')
            WHERE r.cedula = %s AND r.fecha = %s AND r.estado NOT IN ('cancelado','eliminado')
            """
            cursor.execute(query, (cedula, target_date.isoformat()))
        else:
            query = """
            SELECT r.id, r.fecha, r.menu_option, r.estado, m.descripcion AS menu_descripcion
            FROM reservations r
            LEFT JOIN menu m ON r.fecha = m.fecha AND m.descripcion LIKE CONCAT('%Menú ', r.menu_option, '%')
            WHERE r.cedula = %s AND r.estado NOT IN ('cancelado','eliminado')
            """
            cursor.execute(query, (cedula,))
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        return results
    except Exception as e:
        print("Error al consultar las reservas:", e)
        return []

def update_reservation(cedula, target_date, new_menu_option):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        query = """
            UPDATE reservations 
            SET menu_option = %s, estado = 'editado', updated_at = NOW()
            WHERE cedula = %s AND fecha = %s AND estado NOT IN ('cancelado','eliminado')
        """
        cursor.execute(query, (new_menu_option, cedula, target_date.isoformat()))
        conn.commit()
        rows_updated = cursor.rowcount
        cursor.close()
        conn.close()
        return rows_updated
    except Exception as e:
        print("Error al editar la reserva:", e)
        return 0

# ---------------------------
# GENERACIÓN DE RESPUESTAS NATURALES CON OPENAI
# ---------------------------
def send_to_gpt(message, system_prompt=None):
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key
    }
    if not system_prompt:
        system_prompt = (
            "Eres un asistente para reservas de almuerzos. Responde de forma natural y amigable, "
            "tomando en cuenta la información que se te provea."
        )
    data = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ]
    }
    response = requests.post(openai_endpoint, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"].strip()
    else:
        print("Error en la llamada a GPT:", response.status_code, response.text)
        return None

def generate_natural_response(prompt):
    return send_to_gpt(prompt)

# ---------------------------
# ENDPOINT PRINCIPAL DEL CHATBOT
# ---------------------------
@app.route('/chat', methods=['POST'])
def chat():
    # Se espera recibir un JSON con al menos el campo "message"
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Se requiere el campo 'message'"}), 400

    user_input = data["message"]
    # Los siguientes campos pueden venir en el JSON para evitar preguntas interactivas
    cedula_input = data.get("cedula")
    menu_option_input = data.get("menu_option")
    fecha_input = data.get("fecha")  # Puede enviarse en formato "7 de abril", "hoy", "mañana", etc.

    # Detectar intención, fecha, opción de menú y cédula a partir del mensaje
    intent = parse_intent(user_input)
    query_date = extract_date_from_text(fecha_input) if fecha_input else extract_date_from_text(user_input)
    menu_option_extracted = menu_option_input if menu_option_input else extract_menu_option(user_input)
    cedula_extracted = cedula_input if cedula_input else extract_cedula(user_input)

    response_text = ""

    if intent == "consulta_completa":
        menus = get_all_menus_for_date(query_date)
        if menus:
            menu_list = "\n".join([f"{m['id']}. {m['descripcion']}" for m in menus])
            info = f"Los menús para {query_date.strftime('%d/%m/%Y')} son:\n{menu_list}"
        else:
            info = f"No se encontraron menús para {query_date.strftime('%d/%m/%Y')}."
        prompt = (
            f"El usuario pidió todos los menús para la fecha {query_date.strftime('%d/%m/%Y')}. "
            f"Aquí tienes la lista completa:\n{menu_list}\n\n"
            "Genera una respuesta natural y amigable que incluya todos los menús sin omitir ninguno."
        )
        response_text = generate_natural_response(prompt)

    elif intent == "consulta":
        menu = get_menu_for_date(query_date, menu_option_extracted)
        if menu:
            info = f"El menú para {query_date.strftime('%d/%m/%Y')} es: {menu['descripcion']}."
        else:
            info = f"No se encontró un menú para {query_date.strftime('%d/%m/%Y')}."
        prompt = (
            f"El usuario consultó el menú para la fecha {query_date.strftime('%d/%m/%Y')}. {info} "
            "Genera una respuesta natural y amigable para el usuario."
        )
        response_text = generate_natural_response(prompt)

    elif intent == "reserva":
        if not cedula_extracted:
            return jsonify({"error": "El campo 'cedula' es requerido para realizar una reserva."}), 400
        if not menu_option_extracted:
            return jsonify({"error": "El campo 'menu_option' es requerido para realizar una reserva."}), 400
        menu = get_menu_for_date(query_date, menu_option_extracted)
        if menu:
            reservation_id = create_reservation(query_date, cedula_extracted, menu_option_extracted)
            if reservation_id:
                info = (
                    f"Se ha creado la reserva (ID: {reservation_id}) para la cédula {cedula_extracted} "
                    f"para el menú opción {menu_option_extracted} en la fecha {query_date.strftime('%d/%m/%Y')}."
                )
            else:
                info = "Hubo un error al crear la reserva en la base de datos."
        else:
            info = f"No se encontró un menú con la opción {menu_option_extracted} para {query_date.strftime('%d/%m/%Y')}."
        prompt = info + " Genera una respuesta natural y amigable para confirmar la acción al usuario."
        response_text = generate_natural_response(prompt)

    elif intent == "cancelacion":
        if not cedula_extracted:
            return jsonify({"error": "El campo 'cedula' es requerido para cancelar una reserva."}), 400
        rows = cancel_reservation(cedula_extracted, query_date)
        if rows > 0:
            info = f"La reserva para la cédula {cedula_extracted} en la fecha {query_date.strftime('%d/%m/%Y')} ha sido cancelada."
        else:
            info = f"No se encontró ninguna reserva activa para la cédula {cedula_extracted} en la fecha {query_date.strftime('%d/%m/%Y')}."
        prompt = info + " Genera una respuesta natural y amigable para confirmar la acción al usuario."
        response_text = generate_natural_response(prompt)

    elif intent == "consulta_reservas":
        if not cedula_extracted:
            return jsonify({"error": "El campo 'cedula' es requerido para consultar reservas."}), 400
        reservas = get_reservations_by_user(cedula_extracted, query_date)
        if reservas:
            reservas_list = "\n".join([
                f"ID: {r['id']}, Fecha: {r['fecha']}, Menú: {r.get('menu_descripcion', r['menu_option'])}, Estado: {r['estado']}"
                for r in reservas
            ])
            info = f"Tus reservas son:\n{reservas_list}"
        else:
            info = "No se encontraron reservas activas."
        prompt = (
            f"El usuario consultó sus reservas. {info} "
            "Genera una respuesta natural y amigable para el usuario."
        )
        response_text = generate_natural_response(prompt)

    elif intent == "editar_reserva":
        if not cedula_extracted:
            return jsonify({"error": "El campo 'cedula' es requerido para editar una reserva."}), 400
        # Se espera que se envíe la fecha y la nueva opción de menú en el JSON
        fecha_reserva = data.get("fecha_reserva")
        new_menu_option = data.get("new_menu_option")
        if not fecha_reserva or not new_menu_option:
            return jsonify({"error": "Se requieren 'fecha_reserva' y 'new_menu_option' para editar la reserva."}), 400
        target_date = extract_date_from_text(fecha_reserva)
        rows = update_reservation(cedula_extracted, target_date, new_menu_option)
        if rows > 0:
            info = f"Se ha actualizado la reserva para la cédula {cedula_extracted} en la fecha {target_date.strftime('%d/%m/%Y')}, cambiándola a la opción de menú {new_menu_option}."
        else:
            info = f"No se encontró ninguna reserva activa para editar en la fecha {target_date.strftime('%d/%m/%Y')} para la cédula {cedula_extracted}."
        prompt = info + " Genera una respuesta natural y amigable para confirmar la acción al usuario."
        response_text = generate_natural_response(prompt)

    else:
        response_text = "No se pudo determinar la intención de la consulta. Por favor, intente de nuevo."

    return jsonify({"response": response_text})

if __name__ == "__main__":
    app.run(debug=True)
