#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <time.h>
#include <ESP32Servo.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>
#include <Preferences.h>

// EDITAR: URL pública HTTPS de Render. NO usar localhost desde Wokwi.
const char* API_BASE = "https://TU-SERVICIO.onrender.com";
// Debe coincidir con DEVICE_TOKEN en .env / Render.
const char* DEVICE_TOKEN = "CAMBIAR_TOKEN_DISPOSITIVO_LARGO";
const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASS = "";

#define PIN_SERVO 18
#define PIN_TRIG 5
#define PIN_ECHO 17
#define OLED_SDA 21
#define OLED_SCL 22

const float ALTURA_CM = 20.0;
const int NIVEL_MINIMO = 10;
const unsigned long INTERVALO_SENSOR = 2000;
const unsigned long INTERVALO_API = 5000;
const unsigned long INTERVALO_CONFIG = 60000;

Preferences prefs;
Servo compuerta;
Adafruit_SSD1306 oled(128,64,&Wire,-1);
struct Horario { int id; int hora; int minuto; int ultimoDia; };
Horario horarios[20];
int totalHorarios = 0;
float distancia = -1;
int nivel = -1;
bool dispensando = false;
unsigned long tSensor=0,tApi=0,tConfig=0;

bool apiConfigurada(){ return String(API_BASE).startsWith("https://") && String(API_BASE).indexOf("TU-SERVICIO")<0; }

// En Wokwi usamos setInsecure() para pruebas. En hardware real usar CA raíz verificable.
bool peticion(const String& ruta,const String& metodo,const String& cuerpo,String& respuesta){
  if(WiFi.status()!=WL_CONNECTED || !apiConfigurada()) return false;
  WiFiClientSecure cliente;
  cliente.setInsecure(); // SOLO SIMULACION WOKWI
  HTTPClient http;
  http.setTimeout(3500);
  if(!http.begin(cliente,String(API_BASE)+ruta))return false;
  http.addHeader("X-Device-Token",DEVICE_TOKEN);
  http.addHeader("Content-Type","application/json");
  int codigo=metodo=="POST"?http.POST(cuerpo):http.GET();
  respuesta=http.getString();
  http.end();
  if(codigo<200 || codigo>=300){Serial.printf("API %s -> HTTP %d\n",ruta.c_str(),codigo);return false;}
  return true;
}

float medirDistancia(){
  digitalWrite(PIN_TRIG,LOW);delayMicroseconds(2);
  digitalWrite(PIN_TRIG,HIGH);delayMicroseconds(10);
  digitalWrite(PIN_TRIG,LOW);
  long d=pulseIn(PIN_ECHO,HIGH,30000);
  if(d==0)return -1;
  return d*0.0343/2.0;
}
void leerSensor(){
  distancia=medirDistancia();
  if(distancia<0 || distancia>ALTURA_CM){nivel=-1;Serial.println("Sensor fuera de rango");}
  else {nivel=constrain((int)round((ALTURA_CM-distancia)/ALTURA_CM*100),0,100);Serial.printf("Distancia: %.1f cm | Nivel: %d%%\n",distancia,nivel);}
}
void mostrarOLED(){
  oled.clearDisplay();oled.setTextSize(1);oled.setTextColor(SSD1306_WHITE);
  oled.setCursor(0,0);oled.println("ALIMENTADOR IOT");oled.drawLine(0,12,127,12,SSD1306_WHITE);
  struct tm t;
  oled.setCursor(0,18);
  if(getLocalTime(&t,20)){char h[12];strftime(h,sizeof(h),"%H:%M:%S",&t);oled.print("Hora: ");oled.println(h);}
  else oled.println("Hora: sin sincronizar");
  oled.setCursor(0,31);oled.print("Nivel: ");if(nivel<0)oled.println("--");else{oled.print(nivel);oled.println("%");}
  oled.setCursor(0,44);oled.println(dispensando?"DISPENSANDO":(nivel<0?"REVISAR SENSOR":(nivel<=NIVEL_MINIMO?"ALIMENTO BAJO":"SISTEMA LISTO")));
  oled.setCursor(0,56);oled.println(WiFi.status()==WL_CONNECTED?"WiFi: conectado":"WiFi: sin conexion");oled.display();
}
bool dispensar(){
  if(dispensando || nivel<0 || nivel<=NIVEL_MINIMO){Serial.println("Dispensacion bloqueada: sensor/nivel");return false;}
  dispensando=true;mostrarOLED();
  compuerta.write(90);Serial.println("Compuerta abierta");delay(2000);
  compuerta.write(0);Serial.println("Compuerta cerrada");
  dispensando=false;return true;
}
void enviarEvento(const char* origen,bool exito,const char* descripcion){
  JsonDocument d;d["source"]=origen;d["status"]=exito?"completed":"failed";d["description"]=descripcion;
  String cuerpo,respuesta;serializeJson(d,cuerpo);peticion("/api/device/event","POST",cuerpo,respuesta);
}
void guardarHorarios(){
  JsonDocument d;JsonArray a=d.to<JsonArray>();
  for(int i=0;i<totalHorarios;i++){
    JsonObject o=a.add<JsonObject>();o["id"]=horarios[i].id;
    o["hour"]=horarios[i].hora;o["minute"]=horarios[i].minuto;
    o["lastDay"]=horarios[i].ultimoDia;
  }
  String out;serializeJson(d,out);prefs.putString("schedules",out);
}
void cargarHorarios(){
  String saved=prefs.getString("schedules", "[]");
  JsonDocument d;if(deserializeJson(d,saved))return;
  totalHorarios=0;
  for(JsonObject o:d.as<JsonArray>()){
    if(totalHorarios>=20)break;
    horarios[totalHorarios++]={o["id"]|0,o["hour"]|0,o["minute"]|0,o["lastDay"]|-1};
  }
  Serial.printf("Horarios recuperados de memoria: %d\n",totalHorarios);
}
void sincronizarHorarios(){
  String respuesta;if(!peticion("/api/device/config","GET","",respuesta))return;
  JsonDocument d;if(deserializeJson(d,respuesta))return;
  JsonArray arr=d["schedules"].as<JsonArray>();
  // Conservar marcas de ejecución para evitar duplicados al sincronizar.
  Horario nuevos[20];int n=0;
  for(JsonObject item:arr){if(n>=20)break;
    int id=item["id"]|0, dia=-1;
    for(int i=0;i<totalHorarios;i++)if(horarios[i].id==id)dia=horarios[i].ultimoDia;
    nuevos[n++]={id,item["hour"]|0,item["minute"]|0,dia};
  }
  totalHorarios=n;for(int i=0;i<n;i++)horarios[i]=nuevos[i];
  guardarHorarios();
  Serial.printf("Horarios sincronizados: %d\n",totalHorarios);
}
void consultarOrden(){
  String respuesta;if(!peticion("/api/device/command","GET","",respuesta))return;
  JsonDocument d;if(deserializeJson(d,respuesta))return;
  if(d["command"].isNull())return;
  int id=d["command"]["id"]|0;if(id<=0)return;
  Serial.printf("Orden manual #%d\n",id);
  bool exito=dispensar();
  JsonDocument ack;ack["id"]=id;ack["success"]=exito;
  ack["message"]=exito?"Dispensacion manual finalizada":"Nivel insuficiente o sensor invalido";
  String cuerpo,res;serializeJson(ack,cuerpo);peticion("/api/device/ack","POST",cuerpo,res);
}
void enviarTelemetria(){
  JsonDocument d;
  if(nivel<0){d["level"]=nullptr;d["distance"]=nullptr;d["status"]="Sensor invalido";}
  else{d["level"]=nivel;d["distance"]=distancia;d["status"]=nivel<=NIVEL_MINIMO?"Alimento bajo":"Sistema listo";}
  String cuerpo,res;serializeJson(d,cuerpo);peticion("/api/device/telemetry","POST",cuerpo,res);
}
void verificarHorarios(){
  struct tm t;if(!getLocalTime(&t,20))return;
  int dia=t.tm_year*366+t.tm_yday;
  for(int i=0;i<totalHorarios;i++){
    if(t.tm_hour==horarios[i].hora && t.tm_min==horarios[i].minuto && horarios[i].ultimoDia!=dia){
      horarios[i].ultimoDia=dia;guardarHorarios();
      Serial.printf("Horario automatico %02d:%02d\n",t.tm_hour,t.tm_min);
      bool ok=dispensar();enviarEvento("automatic",ok,ok?"Horario ejecutado":"Nivel insuficiente o sensor invalido");
    }
  }
}
void setup(){
  Serial.begin(115200);prefs.begin("alimentador",false);cargarHorarios();pinMode(PIN_TRIG,OUTPUT);pinMode(PIN_ECHO,INPUT);
  compuerta.setPeriodHertz(50);compuerta.attach(PIN_SERVO,500,2400);compuerta.write(0);
  Wire.begin(OLED_SDA,OLED_SCL);if(!oled.begin(SSD1306_SWITCHCAPVCC,0x3C))Serial.println("OLED no detectada");
  WiFi.begin(WIFI_SSID,WIFI_PASS);Serial.print("Conectando WiFi");
  unsigned long inicio=millis();while(WiFi.status()!=WL_CONNECTED && millis()-inicio<15000){delay(400);Serial.print(".");}
  Serial.println(WiFi.status()==WL_CONNECTED?"\nWiFi conectado":"\nWiFi no conectado");
  configTzTime("PET5","pool.ntp.org","time.google.com");
  leerSensor();mostrarOLED();
  sincronizarHorarios();tConfig=millis();
  if(!apiConfigurada())Serial.println("CONFIGURAR API_BASE para habilitar control remoto");
}
void loop(){
  unsigned long ahora=millis();
  if(ahora-tSensor>=INTERVALO_SENSOR){tSensor=ahora;leerSensor();mostrarOLED();verificarHorarios();}
  if(ahora-tApi>=INTERVALO_API){tApi=ahora;enviarTelemetria();consultarOrden();}
  if(ahora-tConfig>=INTERVALO_CONFIG){tConfig=ahora;sincronizarHorarios();}
}
