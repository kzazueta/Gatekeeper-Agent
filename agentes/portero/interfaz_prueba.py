#!/usr/bin/env python
"""
Interfaz de prueba para el Agente Portero (Gatekeeper Agent)
Formato estandar de mensajes con client_id y timestamp
"""

import paho.mqtt.client as mqtt
import json
import os
import time
import logging
import ssl
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("InterfazPrueba")

# Configuracion EMQX Cloud
MQTT_HOST = "bbf91f19.ala.us-east-1.emqxsl.com"
MQTT_PORT = 8883
MQTT_USERNAME = "western_test"
MQTT_PASSWORD = "123456789"
CLIENT_ID = "interfaz_prueba"

# Topico unico
TOPIC_GATEKEEPER = "gatekeeper_agent"


def obtener_timestamp():
    return datetime.now(timezone.utc).isoformat()


class InterfazPrueba:
    def __init__(self):
        self.mqtt_client = None
        self.puerta_actual = 1
        
    def conectar_mqtt(self):
        self.mqtt_client = mqtt.Client(client_id=CLIENT_ID)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        
        self.mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        self.mqtt_client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        self.mqtt_client.tls_insecure_set(False)
        
        try:
            self.mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
            logger.info(f"Conectado a MQTT: {MQTT_HOST}:{MQTT_PORT}")
            return True
        except Exception as e:
            logger.error(f"Error conectando a MQTT: {e}")
            return False
    
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Conectado al broker MQTT")
            client.subscribe(TOPIC_GATEKEEPER)
            logger.info(f"Suscrito a: {TOPIC_GATEKEEPER}")
        else:
            logger.error(f"Error de conexion: {rc}")
    
    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            
            # Ignorar mensajes propios
            if payload.get('client_id') == CLIENT_ID:
                return
            
            data = payload.get('data', {})
            message_type = data.get('message_type')
            message = data.get('message', {})
            operation = message.get('operation')
            
            if operation == 'ACCESS_RESULT':
                decision = message.get('decision')
                nombre = message.get('nombre')
                codigo = message.get('codigo')
                motivo = message.get('motivo')
                
                if decision == 'autorizado':
                    print(f"\n[RESPUESTA] ACCESO AUTORIZADO para {nombre} (codigo: {codigo})")
                else:
                    print(f"\n[RESPUESTA] ACCESO DENEGADO para codigo: {codigo}")
                    if motivo:
                        print(f"           Motivo: {motivo}")
            
            elif operation == 'DOOR_OPEN':
                puerta_id = message.get('puerta_id')
                persona = message.get('persona')
                print(f"\n[EVENTO] Puerta {puerta_id} ABIERTA para {persona}")
            
            elif operation == 'DOOR_CLOSE':
                puerta_id = message.get('puerta_id')
                print(f"\n[EVENTO] Puerta {puerta_id} CERRADA")
            
            elif message_type == 'Response':
                status = message.get('status')
                operation = message.get('operation')
                if status == 'success':
                    print(f"\n[GESTION] {operation} completado")
                else:
                    error = message.get('error')
                    print(f"\n[GESTION] {operation} fallo: {error}")
            
            elif operation == 'ACCESS_INFO':
                access_arr = message.get('access_arr', [])
                print(f"\n[HISTORIAL] {len(access_arr)} registros:")
                for acc in access_arr[:10]:
                    print(f"   ID:{acc['id']} - {acc['name']} - {acc['access']}")
                    
        except Exception as e:
            logger.error(f"Error procesando mensaje: {e}")
    
    def publicar_mensaje(self, data):
        mensaje = {
            "client_id": CLIENT_ID,
            "timestamp": obtener_timestamp(),
            "data": data
        }
        self.mqtt_client.publish(TOPIC_GATEKEEPER, json.dumps(mensaje))
    
    def enviar_solicitud_acceso(self, codigo, puerta_id=1):
        data = {
            "performative": "request",
            "sender": CLIENT_ID,
            "reply-with": f"req-{int(time.time())}",
            "content": {
                "puerta_id": puerta_id,
                "codigo": str(codigo)
            }
        }
        self.publicar_mensaje(data)
        print(f"\n[ENVIADO] Solicitud: codigo={codigo}, puerta={puerta_id}")
    
    def enviar_solicitud_historial(self):
        data = {
            "sender": CLIENT_ID,
            "message_type": "Request",
            "message": {
                "operation": "ACCESS_INFO",
                "date": None,
                "user_code": None
            },
            "expecting_response": "Yes"
        }
        self.publicar_mensaje(data)
        print("\n[ENVIADO] Solicitud de historial")
    
    def mostrar_menu(self):
        print("\n" + "="*50)
        print("INTERFAZ DE PRUEBA - GATEKEEPER AGENT")
        print("="*50)
        print("\nCODIGOS VALIDOS:")
        print("   12345 - Ana Perez (alumno)")
        print("   67890 - Dr. Juan Martinez (doctor)")
        print("   54321 - Carlos Lopez (admin)")
        print("   11111 - Maria Garcia (invitado)")
        print("\nCOMANDOS:")
        print("   [codigo] - Enviar codigo de acceso")
        print("   puerta   - Cambiar puerta (1-4)")
        print("   historial- Solicitar historial")
        print("   salir    - Salir")
        print("-"*50)
    
    def seleccionar_puerta(self):
        print("\nPUERTAS:")
        print("   1. Entrada Principal (todos)")
        print("   2. Laboratorio 1 (admin, doctor)")
        print("   3. Oficina Direccion (solo admin)")
        print("   4. Sala Reuniones (admin, doctor, alumno)")
        
        try:
            opcion = input("Selecciona puerta (1-4): ").strip()
            return int(opcion) if opcion in ['1','2','3','4'] else 1
        except:
            return 1
    
    def run(self):
        if not self.conectar_mqtt():
            print("Error: No se pudo conectar a MQTT")
            return
        
        self.mostrar_menu()
        self.puerta_actual = self.seleccionar_puerta()
        print(f"\nPuerta seleccionada: {self.puerta_actual}")
        
        while True:
            try:
                entrada = input("\nIngresa codigo: ").strip()
                
                if entrada.lower() == 'salir':
                    print("\nSaliendo...")
                    break
                elif entrada.lower() == 'puerta':
                    self.puerta_actual = self.seleccionar_puerta()
                    print(f"Puerta cambiada a: {self.puerta_actual}")
                elif entrada.lower() == 'historial':
                    self.enviar_solicitud_historial()
                elif entrada.isdigit():
                    self.enviar_solicitud_acceso(entrada, self.puerta_actual)
                else:
                    print("Codigo invalido")
                    
            except KeyboardInterrupt:
                print("\n\nSaliendo...")
                break
        
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()


if __name__ == "__main__":
    interfaz = InterfazPrueba()
    interfaz.run()