#!/usr/bin/env python
"""
Interfaz de prueba para el Agente Portero
Simula la lectura de un código QR/barras mediante entrada numérica manual
"""

import paho.mqtt.client as mqtt
import json
import os
import time
import logging
import ssl

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("InterfazPrueba")

# Configuración EMQX Cloud (igual que el agente)
MQTT_HOST = "bbf91f19.ala.us-east-1.emqxsl.com"
MQTT_PORT = 8883
MQTT_USERNAME = "western_test"
MQTT_PASSWORD = "123456789"

TOPIC_SOLICITUD_ACCESO = "uat/portero/solicitud_acceso"
TOPIC_RESPUESTA_ACCESO = "uat/portero/respuesta_acceso"
TOPIC_EVENTO_PUERTA = "uat/portero/evento_puerta"


class InterfazPrueba:
    def __init__(self):
        self.mqtt_client = None
        self.puerta_actual = 1
        
    def conectar_mqtt(self):
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        
        # Configurar autenticación
        self.mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        
        # Configurar TLS para EMQX Cloud
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
            client.subscribe(TOPIC_RESPUESTA_ACCESO)
            client.subscribe(TOPIC_EVENTO_PUERTA)
            logger.info(f"📡 Suscrito a respuestas y eventos")
        else:
            logger.error(f"Error de conexión: {rc}")
    
    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            
            if msg.topic == TOPIC_RESPUESTA_ACCESO:
                content = payload.get('content', {})
                decision = content.get('decision', 'desconocido')
                nombre = content.get('nombre')
                codigo = content.get('codigo')
                
                if decision == 'autorizado':
                    print(f"\n[RESPUESTA] ACCESO AUTORIZADO para {nombre} (código: {codigo})")
                else:
                    print(f"\n[RESPUESTA] ACCESO DENEGADO para código: {codigo}")
                    
            elif msg.topic == TOPIC_EVENTO_PUERTA:
                content = payload.get('content', {})
                accion = content.get('accion')
                estado = content.get('estado')
                persona = content.get('persona', 'desconocido')
                
                if accion == 'abrir':
                    print(f"🔓 [EVENTO] Puerta {estado} para {persona}")
                elif accion == 'cerrar':
                    print(f"🔒 [EVENTO] Puerta {estado} ({content.get('motivo', '')})")
                    
        except Exception as e:
            logger.error(f"Error: {e}")
    
    def enviar_solicitud(self, codigo, puerta_id=1):
        solicitud = {
            "performative": "request",
            "sender": "InterfazPrueba",
            "reply-with": f"req-{int(time.time())}",
            "content": {
                "puerta_id": puerta_id,
                "codigo": str(codigo)
            }
        }
        self.mqtt_client.publish(TOPIC_SOLICITUD_ACCESO, json.dumps(solicitud))
        print(f"\nEnviando solicitud: código={codigo}, puerta={puerta_id}")
    
    def mostrar_menu(self):
        print("\n" + "="*50)
        print("PRUEBA - AGENTE PORTERO")
        print(f"   Broker: {MQTT_HOST}:{MQTT_PORT}")
        print("="*50)
        print("\n CÓDIGOS DE PRUEBA VÁLIDOS:")
        print("   12345  - Ana Pérez (alumno)")
        print("   67890  - Dr. Juan Martínez (doctor)")
        print("   54321  - Carlos López (admin)")
        print("   11111  - María García (invitado)")
        print("\n CÓDIGOS DE PRUEBA INVÁLIDOS:")
        print("   99999  - Cualquier número no registrado")
        print("\n" + "-"*50)
        print("COMANDOS:")
        print("   'puerta' - Cambiar número de puerta")
        print("   'salir'  - Terminar prueba")
        print("-"*50)
    
    def seleccionar_puerta(self):
        print("\n PUERTAS DISPONIBLES:")
        print("   1. Entrada Principal")
        print("   2. Laboratorio 1")
        print("   3. Oficina Dirección")
        print("   4. Sala de Reuniones")
        
        try:
            opcion = input("Selecciona puerta (1-4): ").strip()
            return int(opcion) if opcion in ['1','2','3','4'] else 1
        except:
            return 1
    
    def run(self):
        if not self.conectar_mqtt():
            print(" No se pudo conectar a MQTT")
            return
        
        self.mostrar_menu()
        self.puerta_actual = self.seleccionar_puerta()
        print(f"\n Puerta seleccionada: {self.puerta_actual}")
        
        print("\n" + "-"*50)
        print(" INSTRUCCIONES:")
        print("   Ingresa un código numérico y presiona Enter")
        print("-"*50)
        
        while True:
            try:
                entrada = input("\n Ingresa código: ").strip()
                
                if entrada.lower() == 'salir':
                    print("\n Saliendo...")
                    break
                elif entrada.lower() == 'puerta':
                    self.puerta_actual = self.seleccionar_puerta()
                    print(f" Puerta cambiada a: {self.puerta_actual}")
                    continue
                elif entrada.isdigit():
                    self.enviar_solicitud(entrada, self.puerta_actual)
                else:
                    print(" Código inválido. Ingresa solo números o comandos.")
                    
            except KeyboardInterrupt:
                print("\n\n Saliendo...")
                break
        
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()


if __name__ == "__main__":
    interfaz = InterfazPrueba()
    interfaz.run()