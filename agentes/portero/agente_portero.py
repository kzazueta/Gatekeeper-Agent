import paho.mqtt.client as mqtt
import psycopg2
import json
import os
import time
import logging
import ssl
from datetime import datetime
import threading

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AgentePortero")

# Configuracion desde variables de entorno
MQTT_HOST = os.getenv('MQTT_HOST', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
MQTT_USERNAME = os.getenv('MQTT_USERNAME')
MQTT_PASSWORD = os.getenv('MQTT_PASSWORD')
MQTT_TLS = os.getenv('MQTT_TLS', 'false').lower() == 'true'

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', 5432))
DB_NAME = os.getenv('DB_NAME', 'portero_local')
DB_USER = os.getenv('DB_USER', 'portero')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'portero123')

# Topicos MQTT
TOPIC_SOLICITUD_ACCESO = "uat/portero/solicitud_acceso"
TOPIC_RESPUESTA_ACCESO = "uat/portero/respuesta_acceso"
TOPIC_EVENTO_PUERTA = "uat/portero/evento_puerta"
TOPIC_ENTRADAS = "uat/portero/entradas"           # Para recibir NEW_USER, RM_USER, ACCESS_INFO
TOPIC_PUBLICACIONES = "uat/portero/publicaciones" # Para enviar UPDATE con ACCESS_INFO


class AgentePortero:
    def __init__(self):
        self.db_conn = None
        self.mqtt_client = None
        
    def conectar_db(self):
        try:
            self.db_conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, database=DB_NAME,
                user=DB_USER, password=DB_PASSWORD
            )
            logger.info(f"Conectado a BD: {DB_HOST}:{DB_PORT}/{DB_NAME}")
            return True
        except Exception as e:
            logger.error(f"Error conectando a BD: {e}")
            return False
    
    def conectar_mqtt(self):
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.on_mqtt_message
        
        if MQTT_USERNAME and MQTT_PASSWORD:
            self.mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
            logger.info(f"Usando autenticacion: {MQTT_USERNAME}")
        
        if MQTT_TLS:
            self.mqtt_client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
            self.mqtt_client.tls_insecure_set(False)
            logger.info("Conexion TLS habilitada")
        
        try:
            self.mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
            logger.info(f"Conectado a MQTT: {MQTT_HOST}:{MQTT_PORT}")
            return True
        except Exception as e:
            logger.error(f"Error conectando a MQTT: {e}")
            return False
    
    def on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Conectado al broker MQTT")
            client.subscribe(TOPIC_SOLICITUD_ACCESO)
            client.subscribe(TOPIC_ENTRADAS)
            logger.info(f"Suscrito a: {TOPIC_SOLICITUD_ACCESO}, {TOPIC_ENTRADAS}")
        else:
            logger.error(f"Error de conexion MQTT: {rc}")
    
    def on_mqtt_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            logger.info(f"Mensaje recibido en {msg.topic}")
            
            if msg.topic == TOPIC_SOLICITUD_ACCESO:
                self.procesar_solicitud_acceso(payload)
            elif msg.topic == TOPIC_ENTRADAS:
                self.procesar_mensaje_entrada(payload)
                
        except Exception as e:
            logger.error(f"Error procesando mensaje: {e}")
    
    # ==================== PROCESAR MENSAJES DE ENTRADA (formato definido) ====================
    def procesar_mensaje_entrada(self, payload):
        """
        Procesa mensajes con el formato:
        {
            "sender":"agent_name",
            "mesagge_type":"Request",
            "mesagge":{...},
            "expecting_response":"Yes/No"
        }
        """
        sender = payload.get('sender', 'desconocido')
        message_type = payload.get('mesagge_type')
        message = payload.get('mesagge', {})
        expecting_response = payload.get('expecting_response', 'No')
        
        operation = message.get('operation')
        
        logger.info(f"Mensaje de {sender}: {message_type} - {operation}")
        
        if operation == 'NEW_USER':
            self.procesar_nuevo_usuario(message, sender, expecting_response)
        elif operation == 'RM_USER':
            self.procesar_eliminar_usuario(message, sender, expecting_response)
        elif operation == 'ACCESS_INFO':
            self.procesar_solicitud_info_accesos(message, sender, expecting_response)
        else:
            logger.warning(f"Operacion desconocida: {operation}")
    
    # ==================== NEW USER ====================
    def procesar_nuevo_usuario(self, message, sender, expecting_response):
        """
        Formato esperado:
        {
            "operation":"NEW_USER",
            "id":0,
            "name":"",
            "role":"",
            "code":"",
            "access":true
        }
        """
        user_id = message.get('id')
        name = message.get('name')
        role = message.get('role')
        code = message.get('code')
        access = message.get('access', True)
        
        logger.info(f"Nuevo usuario: {name} ({role}) con codigo {code}")
        
        try:
            cursor = self.db_conn.cursor()
            cursor.execute("""
                INSERT INTO perfiles (id, codigo, nombre, tipo, activo)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (codigo) DO UPDATE SET
                    nombre = EXCLUDED.nombre,
                    tipo = EXCLUDED.tipo,
                    activo = EXCLUDED.activo
            """, (user_id, code, name, role, access))
            self.db_conn.commit()
            logger.info(f"Usuario {name} registrado correctamente")
            
            if expecting_response == 'Yes':
                self.enviar_respuesta_confirmacion(sender, 'NEW_USER', 'success', user_id)
                
        except Exception as e:
            logger.error(f"Error registrando nuevo usuario: {e}")
            if expecting_response == 'Yes':
                self.enviar_respuesta_confirmacion(sender, 'NEW_USER', 'error', user_id, str(e))
    
    # ==================== RM USER (Eliminar usuario) ====================
    def procesar_eliminar_usuario(self, message, sender, expecting_response):
        """
        Formato esperado:
        {
            "operation":"RM_USER",
            "id":0,
            "code":"0",
            "access":false
        }
        """
        user_id = message.get('id')
        code = message.get('code')
        access = message.get('access', False)
        
        logger.info(f"Eliminando usuario: id={user_id}, codigo={code}")
        
        try:
            cursor = self.db_conn.cursor()
            cursor.execute("""
                UPDATE perfiles SET activo = FALSE
                WHERE codigo = %s OR id = %s
            """, (code, user_id))
            self.db_conn.commit()
            logger.info(f"Usuario con codigo {code} desactivado")
            
            if expecting_response == 'Yes':
                self.enviar_respuesta_confirmacion(sender, 'RM_USER', 'success', user_id)
                
        except Exception as e:
            logger.error(f"Error eliminando usuario: {e}")
            if expecting_response == 'Yes':
                self.enviar_respuesta_confirmacion(sender, 'RM_USER', 'error', user_id, str(e))
    
    # ==================== ACCESS INFO (Solicitar historial) ====================
    def procesar_solicitud_info_accesos(self, message, sender, expecting_response):
        """
        Formato esperado:
        {
            "operation":"ACCESS_INFO",
            "date":"YYYY-MM-DDTHH:mm:ss",
            "user_code":null
        }
        """
        fecha = message.get('date')
        user_code = message.get('user_code')
        
        logger.info(f"Solicitud de historial de accesos: fecha={fecha}, user_code={user_code}")
        
        try:
            cursor = self.db_conn.cursor()
            
            if user_code:
                cursor.execute("""
                    SELECT id, nombre, resultado, created_at 
                    FROM access_logs 
                    WHERE codigo = %s AND (created_at >= %s OR %s IS NULL)
                    ORDER BY created_at DESC
                    LIMIT 100
                """, (user_code, fecha, fecha))
            else:
                cursor.execute("""
                    SELECT id, nombre, resultado, created_at 
                    FROM access_logs 
                    WHERE created_at >= %s OR %s IS NULL
                    ORDER BY created_at DESC
                    LIMIT 100
                """, (fecha, fecha))
            
            resultados = cursor.fetchall()
            
            # Construir arreglo de accesos
            access_arr = []
            for r in resultados:
                access_arr.append({
                    "id": r[0],
                    "name": r[1] if r[1] else "Desconocido",
                    "access": r[3].isoformat() if r[3] else None
                })
            
            # Publicar respuesta en TOPIC_PUBLICACIONES
            respuesta = {
                "sender": "gatekeeper_agent",
                "mesagge_type": "Update",
                "mesagge": {
                    "operation": "ACCESS_INFO",
                    "access_arr": access_arr
                },
                "expecting_response": "No"
            }
            
            self.mqtt_client.publish(TOPIC_PUBLICACIONES, json.dumps(respuesta))
            logger.info(f"Historial de accesos enviado: {len(access_arr)} registros")
            
        except Exception as e:
            logger.error(f"Error consultando historial: {e}")
            respuesta = {
                "sender": "gatekeeper_agent",
                "mesagge_type": "Update",
                "mesagge": {
                    "operation": "ACCESS_INFO",
                    "access_arr": []
                },
                "expecting_response": "No"
            }
            self.mqtt_client.publish(TOPIC_PUBLICACIONES, json.dumps(respuesta))
    
    def enviar_respuesta_confirmacion(self, sender, operation, status, user_id, error_msg=None):
        respuesta = {
            "sender": "gatekeeper_agent",
            "mesagge_type": "Response",
            "mesagge": {
                "operation": operation,
                "status": status,
                "user_id": user_id,
                "error": error_msg
            },
            "expecting_response": "No"
        }
        self.mqtt_client.publish(TOPIC_PUBLICACIONES, json.dumps(respuesta))
        logger.info(f"Confirmacion enviada: {operation} - {status}")
    
    # ==================== VALIDACION DE ACCESO (apertura de puertas) ====================
    def verificar_permiso_por_tipo(self, tipo_usuario, puerta_id):
        try:
            cursor = self.db_conn.cursor()
            cursor.execute("""
                SELECT puede_acceder FROM permisos_por_tipo
                WHERE tipo_usuario = %s AND puerta_id = %s
            """, (tipo_usuario, puerta_id))
            resultado = cursor.fetchone()
            
            if resultado:
                return resultado[0]
            else:
                logger.warning(f"No hay regla para {tipo_usuario} en puerta {puerta_id}, denegando")
                return False
                
        except Exception as e:
            logger.error(f"Error verificando permiso: {e}")
            return False
    
    def validar_codigo(self, codigo):
        try:
            cursor = self.db_conn.cursor()
            cursor.execute("""
                SELECT id, nombre, tipo FROM perfiles 
                WHERE codigo = %s AND activo = TRUE
            """, (codigo,))
            resultado = cursor.fetchone()
            
            if resultado:
                return True, resultado[0], resultado[1], resultado[2]
            return False, None, None, None
            
        except Exception as e:
            logger.error(f"Error validando codigo: {e}")
            return False, None, None, None
    
    def registrar_evento(self, codigo, nombre, tipo, puerta_id, autorizado, motivo=None):
        try:
            cursor = self.db_conn.cursor()
            resultado = 'exitoso' if autorizado else 'denegado'
            cursor.execute("""
                INSERT INTO access_logs (codigo, nombre, tipo, puerta_id, resultado, motivo, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, (codigo, nombre, tipo, puerta_id, resultado, motivo))
            self.db_conn.commit()
            logger.info(f"Evento registrado: {codigo} - {resultado}" + (f" ({motivo})" if motivo else ""))
        except Exception as e:
            logger.error(f"Error registrando evento: {e}")
    
    def ejecutar_apertura(self, puerta_id, codigo, nombre):
        logger.info(f"ABRIENDO puerta {puerta_id} para {nombre} (codigo: {codigo})")
        
        evento = {
            "performative": "inform-done",
            "sender": "gatekeeper_agent",
            "content": {
                "puerta_id": puerta_id,
                "accion": "abrir",
                "estado": "abierta",
                "persona": nombre,
                "codigo": codigo,
                "timestamp": datetime.now().isoformat()
            }
        }
        self.mqtt_client.publish(TOPIC_EVENTO_PUERTA, json.dumps(evento))
        
        timer = threading.Timer(5.0, self.cerrar_puerta_automatico, args=[puerta_id])
        timer.start()
    
    def cerrar_puerta_automatico(self, puerta_id):
        logger.info(f"CERRANDO puerta {puerta_id} (cierre automatico)")
        
        evento = {
            "performative": "inform-done",
            "sender": "gatekeeper_agent",
            "content": {
                "puerta_id": puerta_id,
                "accion": "cerrar",
                "estado": "cerrada",
                "motivo": "cierre_automatico",
                "timestamp": datetime.now().isoformat()
            }
        }
        self.mqtt_client.publish(TOPIC_EVENTO_PUERTA, json.dumps(evento))
    
    # ==================== PROCESAR SOLICITUD DE ACCESO (desde lector/ESP32) ====================
    def procesar_solicitud_acceso(self, payload):
        content = payload.get('content', {})
        codigo = content.get('codigo')
        puerta_id = content.get('puerta_id', 1)
        reply_with = payload.get('reply-with')
        sender = payload.get('sender', 'desconocido')
        
        if not codigo:
            logger.warning("Solicitud sin codigo")
            return
        
        logger.info(f"Validando acceso: codigo={codigo}, puerta={puerta_id}, origen={sender}")
        
        valido, user_id, nombre, tipo = self.validar_codigo(codigo)
        
        if not valido:
            decision = "denegado"
            motivo = "codigo_invalido"
            logger.warning(f"ACCESO DENEGADO: codigo {codigo} no valido")
            self.registrar_evento(codigo, None, None, puerta_id, False, motivo)
            
            respuesta = {
                "performative": "inform-result",
                "sender": "gatekeeper_agent",
                "in-reply-to": reply_with,
                "content": {
                    "codigo": codigo,
                    "puerta_id": puerta_id,
                    "decision": decision,
                    "ejecutado": False,
                    "motivo": motivo,
                    "timestamp": datetime.now().isoformat()
                }
            }
            self.mqtt_client.publish(TOPIC_RESPUESTA_ACCESO, json.dumps(respuesta))
            return
        
        tiene_permiso = self.verificar_permiso_por_tipo(tipo, puerta_id)
        
        if not tiene_permiso:
            decision = "denegado"
            motivo = f"permiso_denegado: {tipo} no autorizado para puerta {puerta_id}"
            logger.warning(f"ACCESO DENEGADO: {nombre} ({tipo}) no tiene permiso para puerta {puerta_id}")
            self.registrar_evento(codigo, nombre, tipo, puerta_id, False, motivo)
            
            respuesta = {
                "performative": "inform-result",
                "sender": "gatekeeper_agent",
                "in-reply-to": reply_with,
                "content": {
                    "codigo": codigo,
                    "puerta_id": puerta_id,
                    "decision": decision,
                    "ejecutado": False,
                    "motivo": motivo,
                    "nombre": nombre,
                    "tipo": tipo,
                    "timestamp": datetime.now().isoformat()
                }
            }
            self.mqtt_client.publish(TOPIC_RESPUESTA_ACCESO, json.dumps(respuesta))
            return
        
        decision = "autorizado"
        logger.info(f"ACCESO AUTORIZADO: {nombre} ({tipo}) a puerta {puerta_id}")
        
        self.ejecutar_apertura(puerta_id, codigo, nombre)
        self.registrar_evento(codigo, nombre, tipo, puerta_id, True, None)
        
        respuesta = {
            "performative": "inform-result",
            "sender": "gatekeeper_agent",
            "in-reply-to": reply_with,
            "content": {
                "codigo": codigo,
                "puerta_id": puerta_id,
                "decision": decision,
                "ejecutado": True,
                "nombre": nombre,
                "tipo": tipo,
                "timestamp": datetime.now().isoformat()
            }
        }
        self.mqtt_client.publish(TOPIC_RESPUESTA_ACCESO, json.dumps(respuesta))
    
    def run(self):
        logger.info("=" * 50)
        logger.info("AGENTE PORTERO (GATEKEEPER AGENT)")
        logger.info("Responsabilidad: Gestionar accesos y sincronizar datos")
        logger.info(f"Broker MQTT: {MQTT_HOST}:{MQTT_PORT}")
        logger.info("=" * 50)
        
        if not self.conectar_db():
            return
        if not self.conectar_mqtt():
            return
        
        logger.info("Agente Portero listo")
        logger.info("Escuchando:")
        logger.info("  - Solicitudes de acceso (apertura de puertas)")
        logger.info("  - Mensajes de entrada (NEW_USER, RM_USER, ACCESS_INFO)")
        logger.info("=" * 50)
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Deteniendo Agente Portero...")
        finally:
            if self.db_conn:
                self.db_conn.close()
            if self.mqtt_client:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            logger.info("Agente Portero finalizado")


if __name__ == "__main__":
    agente = AgentePortero()
    agente.run()