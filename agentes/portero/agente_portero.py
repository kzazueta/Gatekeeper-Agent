import paho.mqtt.client as mqtt
import psycopg2
import json
import os
import time
import logging
import ssl
from datetime import datetime, timezone
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
CLIENT_ID = os.getenv('CLIENT_ID', 'gatekeeper_agent')

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', 5432))
DB_NAME = os.getenv('DB_NAME', 'portero_local')
DB_USER = os.getenv('DB_USER', 'portero')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'portero123')

# Topicos
TOPIC_GATEKEEPER = "gatekeeper_agent"
TOPIC_EMERGENCY = "emergency_agent"


def obtener_timestamp():
    return datetime.now(timezone.utc).isoformat()


class AgentePortero:
    def __init__(self):
        self.db_conn = None
        self.mqtt_client = None
        self.client_id = CLIENT_ID
        
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
        self.mqtt_client = mqtt.Client(client_id=self.client_id)
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
            client.subscribe(TOPIC_GATEKEEPER)
            logger.info(f"Suscrito a: {TOPIC_GATEKEEPER}")
        else:
            logger.error(f"Error de conexion MQTT: {rc}")
    
    def on_mqtt_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            
            # Ignorar mensajes propios
            if payload.get('client_id') == self.client_id:
                return
            
            data = payload.get('data', {})
            sender = data.get('sender')
            message_type = data.get('message_type')
            message = data.get('message', {})
            operation = message.get('operation')
            
            logger.info(f"Mensaje recibido de {sender}: {message_type} - {operation}")
            
            # Operaciones de gestion (NEW_USER, RM_USER, ACCESS_INFO)
            if operation in ['NEW_USER', 'RM_USER', 'ACCESS_INFO']:
                self.procesar_mensaje_gestion(data)
            # Solicitud de acceso normal
            elif data.get('performative') == 'request' and data.get('content', {}).get('codigo'):
                self.procesar_solicitud_acceso(data)
            # Operaciones de emergencia
            elif operation == 'CERRAR_PUERTA':
                self.procesar_cerrar_puerta(data)
            elif operation == 'ABRIR_PUERTA':
                self.procesar_abrir_puerta_emergencia(data)
            else:
                logger.warning(f"Tipo de mensaje no reconocido: {payload}")
                
        except Exception as e:
            logger.error(f"Error procesando mensaje: {e}")
    
    def publicar_mensaje(self, data, topic=TOPIC_GATEKEEPER):
        mensaje = {
            "client_id": self.client_id,
            "timestamp": obtener_timestamp(),
            "data": data
        }
        self.mqtt_client.publish(topic, json.dumps(mensaje))
        logger.debug(f"Mensaje publicado en {topic}: {data.get('message_type')} - {data.get('message', {}).get('operation', 'N/A')}")
    
    # ==================== MENSAJES DE GESTION ====================
    def procesar_mensaje_gestion(self, data):
        sender = data.get('sender', 'desconocido')
        message_type = data.get('message_type')
        message = data.get('message', {})
        operation = message.get('operation')
        expecting_response = data.get('expecting_response', 'No')
        
        logger.info(f"Mensaje de gestion de {sender}: {message_type} - {operation}")
        
        if operation == 'NEW_USER':
            self.procesar_nuevo_usuario(message, sender, expecting_response)
        elif operation == 'RM_USER':
            self.procesar_eliminar_usuario(message, sender, expecting_response)
        elif operation == 'ACCESS_INFO':
            self.procesar_solicitud_info_accesos(message, sender, expecting_response)
        else:
            logger.warning(f"Operacion desconocida: {operation}")
    
    def procesar_nuevo_usuario(self, message, sender, expecting_response):
        user_id = message.get('id')
        name = message.get('name')
        role = message.get('role')
        code = message.get('code')
        access = message.get('access', True)
        
        if not code:
            logger.error("NEW_USER: codigo es obligatorio")
            if expecting_response == 'Yes':
                self.enviar_respuesta_gestion(sender, 'NEW_USER', 'error', user_id, "Codigo obligatorio")
            return
        
        if not name:
            logger.error("NEW_USER: nombre es obligatorio")
            if expecting_response == 'Yes':
                self.enviar_respuesta_gestion(sender, 'NEW_USER', 'error', user_id, "Nombre obligatorio")
            return
        
        logger.info(f"Nuevo usuario: {name} ({role}) con codigo {code}")
        
        try:
            cursor = self.db_conn.cursor()
            
            cursor.execute("SELECT id FROM perfiles WHERE codigo = %s", (code,))
            existe = cursor.fetchone()
            
            if existe:
                cursor.execute("""
                    UPDATE perfiles 
                    SET nombre = %s, tipo = %s, activo = %s
                    WHERE codigo = %s
                """, (name, role, access, code))
            else:
                cursor.execute("""
                    INSERT INTO perfiles (id, codigo, nombre, tipo, activo)
                    VALUES (%s, %s, %s, %s, %s)
                """, (user_id, code, name, role, access))
            
            self.db_conn.commit()
            logger.info(f"Usuario {name} registrado correctamente")
            
            if expecting_response == 'Yes':
                self.enviar_respuesta_gestion(sender, 'NEW_USER', 'success', user_id)
                
        except Exception as e:
            self.db_conn.rollback()
            logger.error(f"Error registrando nuevo usuario: {e}")
            if expecting_response == 'Yes':
                self.enviar_respuesta_gestion(sender, 'NEW_USER', 'error', user_id, str(e))
    
    def procesar_eliminar_usuario(self, message, sender, expecting_response):
        user_id = message.get('id')
        code = message.get('code')
        
        logger.info(f"Eliminando usuario: id={user_id}, codigo={code}")
        
        try:
            cursor = self.db_conn.cursor()
            
            if code:
                cursor.execute("UPDATE perfiles SET activo = FALSE WHERE codigo = %s", (code,))
            elif user_id:
                cursor.execute("UPDATE perfiles SET activo = FALSE WHERE id = %s", (user_id,))
            else:
                logger.warning("RM_USER: se requiere code o id")
                return
            
            self.db_conn.commit()
            logger.info(f"Usuario desactivado")
            
            if expecting_response == 'Yes':
                self.enviar_respuesta_gestion(sender, 'RM_USER', 'success', user_id)
                
        except Exception as e:
            self.db_conn.rollback()
            logger.error(f"Error eliminando usuario: {e}")
            if expecting_response == 'Yes':
                self.enviar_respuesta_gestion(sender, 'RM_USER', 'error', user_id, str(e))
    
    def procesar_solicitud_info_accesos(self, message, sender, expecting_response):
        fecha = message.get('date')
        user_code = message.get('user_code')
        
        logger.info(f"Solicitud de historial: fecha={fecha}, user_code={user_code}")
        
        try:
            cursor = self.db_conn.cursor()
            
            if user_code:
                cursor.execute("""
                    SELECT id, nombre, resultado, created_at 
                    FROM access_logs 
                    WHERE codigo = %s 
                    ORDER BY created_at DESC
                    LIMIT 100
                """, (user_code,))
            else:
                cursor.execute("""
                    SELECT id, nombre, resultado, created_at 
                    FROM access_logs 
                    ORDER BY created_at DESC
                    LIMIT 100
                """)
            
            resultados = cursor.fetchall()
            
            access_arr = []
            for r in resultados:
                access_arr.append({
                    "id": r[0],
                    "name": r[1] if r[1] else "Desconocido",
                    "access": r[3].isoformat() if r[3] else None
                })
            
            respuesta_data = {
                "sender": self.client_id,
                "message_type": "Update",
                "message": {
                    "operation": "ACCESS_INFO",
                    "access_arr": access_arr
                },
                "expecting_response": "No"
            }
            
            self.publicar_mensaje(respuesta_data)
            logger.info(f"Historial enviado: {len(access_arr)} registros")
            
        except Exception as e:
            self.db_conn.rollback()
            logger.error(f"Error consultando historial: {e}")
            respuesta_data = {
                "sender": self.client_id,
                "message_type": "Update",
                "message": {
                    "operation": "ACCESS_INFO",
                    "access_arr": []
                },
                "expecting_response": "No"
            }
            self.publicar_mensaje(respuesta_data)
    
    def enviar_respuesta_gestion(self, sender, operation, status, user_id, error_msg=None):
        respuesta_data = {
            "sender": self.client_id,
            "message_type": "Response",
            "message": {
                "operation": operation,
                "status": status,
                "user_id": user_id,
                "error": error_msg
            },
            "expecting_response": "No"
        }
        self.publicar_mensaje(respuesta_data)
        logger.info(f"Confirmacion enviada: {operation} - {status}")
    
    # ==================== SOLICITUDES DE ACCESO NORMAL ====================
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
    
    def ejecutar_apertura_normal(self, puerta_id, codigo, nombre):
        logger.info(f"ABRIENDO puerta {puerta_id} para {nombre} (codigo: {codigo})")
        
        evento_data = {
            "sender": self.client_id,
            "message_type": "Event",
            "message": {
                "operation": "DOOR_OPEN",
                "puerta_id": puerta_id,
                "persona": nombre,
                "codigo": codigo,
                "timestamp": obtener_timestamp()
            },
            "expecting_response": "No"
        }
        self.publicar_mensaje(evento_data)
        
        timer = threading.Timer(5.0, self.cerrar_puerta_automatico, args=[puerta_id])
        timer.start()
    
    def cerrar_puerta_automatico(self, puerta_id):
        logger.info(f"CERRANDO puerta {puerta_id} (cierre automatico)")
        
        evento_data = {
            "sender": self.client_id,
            "message_type": "Event",
            "message": {
                "operation": "DOOR_CLOSE",
                "puerta_id": puerta_id,
                "motivo": "cierre_automatico",
                "timestamp": obtener_timestamp()
            },
            "expecting_response": "No"
        }
        self.publicar_mensaje(evento_data)
    
    def procesar_solicitud_acceso(self, data):
        content = data.get('content', {})
        codigo = content.get('codigo')
        puerta_id = content.get('puerta_id', 1)
        reply_with = data.get('reply-with')
        sender = data.get('sender', 'desconocido')
        
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
            
            respuesta_data = {
                "sender": self.client_id,
                "message_type": "Response",
                "message": {
                    "operation": "ACCESS_RESULT",
                    "codigo": codigo,
                    "puerta_id": puerta_id,
                    "decision": decision,
                    "ejecutado": False,
                    "motivo": motivo,
                    "timestamp": obtener_timestamp()
                },
                "in-reply-to": reply_with,
                "expecting_response": "No"
            }
            self.publicar_mensaje(respuesta_data)
            return
        
        tiene_permiso = self.verificar_permiso_por_tipo(tipo, puerta_id)
        
        if not tiene_permiso:
            decision = "denegado"
            motivo = f"permiso_denegado: {tipo} no autorizado para puerta {puerta_id}"
            logger.warning(f"ACCESO DENEGADO: {nombre} ({tipo}) no tiene permiso para puerta {puerta_id}")
            self.registrar_evento(codigo, nombre, tipo, puerta_id, False, motivo)
            
            respuesta_data = {
                "sender": self.client_id,
                "message_type": "Response",
                "message": {
                    "operation": "ACCESS_RESULT",
                    "codigo": codigo,
                    "puerta_id": puerta_id,
                    "decision": decision,
                    "ejecutado": False,
                    "motivo": motivo,
                    "nombre": nombre,
                    "tipo": tipo,
                    "timestamp": obtener_timestamp()
                },
                "in-reply-to": reply_with,
                "expecting_response": "No"
            }
            self.publicar_mensaje(respuesta_data)
            return
        
        decision = "autorizado"
        logger.info(f"ACCESO AUTORIZADO: {nombre} ({tipo}) a puerta {puerta_id}")
        
        self.ejecutar_apertura_normal(puerta_id, codigo, nombre)
        self.registrar_evento(codigo, nombre, tipo, puerta_id, True, None)
        
        respuesta_data = {
            "sender": self.client_id,
            "message_type": "Response",
            "message": {
                "operation": "ACCESS_RESULT",
                "codigo": codigo,
                "puerta_id": puerta_id,
                "decision": decision,
                "ejecutado": True,
                "nombre": nombre,
                "tipo": tipo,
                "timestamp": obtener_timestamp()
            },
            "in-reply-to": reply_with,
            "expecting_response": "No"
        }
        self.publicar_mensaje(respuesta_data)
    
    # ==================== FUNCIONES PARA EMERGENCY AGENT ====================
    def procesar_cerrar_puerta(self, data):
        """Recibe comando de Emergency Agent para cerrar una puerta"""
        message = data.get('message', {})
        puerta_id = message.get('puerta_id')
        motivo = message.get('motivo', 'emergencia')
        persona = message.get('persona', 'Desconocido')
        ubicacion = message.get('ubicacion', '')
        
        logger.warning(f"COMANDO DE EMERGENCIA: Cerrar puerta {puerta_id} - Motivo: {motivo}")
        logger.info(f"Intruso: {persona} en {ubicacion}")
        
        # Ejecutar cierre de puerta
        self.ejecutar_cierre_emergencia(puerta_id, motivo)
        
        # Registrar evento especial en BD
        self.registrar_evento_emergencia(puerta_id, persona, ubicacion, motivo)
        
        # Confirmar al Emergency Agent
        self.confirmar_accion_emergencia(puerta_id, 'cerrada', motivo)
    
    def ejecutar_cierre_emergencia(self, puerta_id, motivo):
        """Ejecutar cierre inmediato de puerta por emergencia"""
        logger.info(f"EMERGENCIA: Cerrando puerta {puerta_id} - {motivo}")
        
        evento_data = {
            "sender": self.client_id,
            "message_type": "Event",
            "message": {
                "operation": "DOOR_CLOSE_EMERGENCY",
                "puerta_id": puerta_id,
                "motivo": motivo,
                "timestamp": obtener_timestamp()
            },
            "expecting_response": "No"
        }
        self.publicar_mensaje(evento_data)
    
    def registrar_evento_emergencia(self, puerta_id, persona, ubicacion, motivo):
        """Registrar evento de emergencia en la base de datos"""
        try:
            cursor = self.db_conn.cursor()
            cursor.execute("""
                INSERT INTO access_logs (codigo, nombre, tipo, puerta_id, resultado, motivo, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, ('EMERGENCIA', persona, 'sistema', puerta_id, 'cerrada_emergencia', f"{motivo} - {ubicacion}"))
            self.db_conn.commit()
            logger.info(f"Evento de emergencia registrado: puerta {puerta_id} cerrada")
        except Exception as e:
            self.db_conn.rollback()
            logger.error(f"Error registrando evento de emergencia: {e}")
    
    def confirmar_accion_emergencia(self, puerta_id, estado, motivo):
        """Confirmar a Emergency Agent que la accion se completo"""
        respuesta_data = {
            "sender": self.client_id,
            "message_type": "Response",
            "message": {
                "operation": "CONFIRMACION_EMERGENCIA",
                "puerta_id": puerta_id,
                "estado": estado,
                "motivo": motivo,
                "timestamp": obtener_timestamp()
            },
            "expecting_response": "No"
        }
        self.publicar_mensaje(respuesta_data, topic=TOPIC_EMERGENCY)
        logger.info(f"Confirmacion enviada a Emergency Agent: puerta {puerta_id} {estado}")
    
    def procesar_abrir_puerta_emergencia(self, data):
        """Recibe comando de Emergency Agent para abrir una puerta (despues de desactivar protocolo)"""
        message = data.get('message', {})
        puerta_id = message.get('puerta_id')
        motivo = message.get('motivo', 'desactivacion_manual')
        usuario = message.get('usuario', 'Emergency Agent')
        
        logger.info(f"COMANDO DE EMERGENCIA: Abrir puerta {puerta_id} - Motivo: {motivo} por {usuario}")
        
        # Ejecutar apertura de puerta
        self.ejecutar_apertura_emergencia(puerta_id, motivo, usuario)
        
        # Registrar evento en BD
        self.registrar_apertura_emergencia(puerta_id, motivo, usuario)
        
        # Confirmar al Emergency Agent
        self.confirmar_accion_emergencia(puerta_id, 'abierta', motivo)
    
    def ejecutar_apertura_emergencia(self, puerta_id, motivo, usuario):
        """Ejecutar apertura de puerta por comando de emergencia"""
        logger.info(f"EMERGENCIA: Abriendo puerta {puerta_id} - {motivo} por {usuario}")
        
        evento_data = {
            "sender": self.client_id,
            "message_type": "Event",
            "message": {
                "operation": "DOOR_OPEN_EMERGENCY",
                "puerta_id": puerta_id,
                "motivo": motivo,
                "usuario": usuario,
                "timestamp": obtener_timestamp()
            },
            "expecting_response": "No"
        }
        self.publicar_mensaje(evento_data)
    
    def registrar_apertura_emergencia(self, puerta_id, motivo, usuario):
        """Registrar apertura por emergencia en la base de datos"""
        try:
            cursor = self.db_conn.cursor()
            cursor.execute("""
                INSERT INTO access_logs (codigo, nombre, tipo, puerta_id, resultado, motivo, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, ('EMERGENCIA', usuario, 'sistema', puerta_id, 'abierta_emergencia', motivo))
            self.db_conn.commit()
            logger.info(f"Apertura de emergencia registrada: puerta {puerta_id}")
        except Exception as e:
            self.db_conn.rollback()
            logger.error(f"Error registrando apertura de emergencia: {e}")
    
    # ==================== METODO RUN ====================
    def run(self):
        logger.info("=" * 50)
        logger.info("GATEKEEPER AGENT (Agente Portero)")
        logger.info(f"Client ID: {self.client_id}")
        logger.info(f"Topico propio: {TOPIC_GATEKEEPER}")
        logger.info(f"Topico Emergency: {TOPIC_EMERGENCY}")
        logger.info(f"Broker MQTT: {MQTT_HOST}:{MQTT_PORT}")
        logger.info("=" * 50)
        
        if not self.conectar_db():
            return
        if not self.conectar_mqtt():
            return
        
        logger.info("Gatekeeper Agent listo")
        logger.info("Escuchando:")
        logger.info("  - Solicitudes de acceso normal")
        logger.info("  - Comandos de emergencia (CERRAR_PUERTA, ABRIR_PUERTA)")
        logger.info("  - Gestion de usuarios (NEW_USER, RM_USER, ACCESS_INFO)")
        logger.info("=" * 50)
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Deteniendo Gatekeeper Agent...")
        finally:
            if self.db_conn:
                self.db_conn.close()
            if self.mqtt_client:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            logger.info("Gatekeeper Agent finalizado")


if __name__ == "__main__":
    agente = AgentePortero()
    agente.run()