# Catálogo Yeastar – Nuxway Technology SRL

## IMPORTANTE – LECTURA OBLIGATORIA PARA LA IA

Los valores de usuarios y llamadas simultáneas deben diferenciarse SIEMPRE por tipo de plataforma.
NO mezclar capacidades entre equipos físicos (Appliance), Software o Cloud.

Regla crítica:
Los modelos físicos **P520, P550, P560, P570, S412, S20 y S50** NUNCA deben usar valores de Software o Cloud
(como 1000+ usuarios o cientos de llamadas simultáneas).

---

## 1) Yeastar P-Series Phone System
Plataforma de Comunicaciones Unificadas que integra PBX IP, call center, mensajería omnicanal, videollamadas e integraciones empresariales.

### Ediciones
- Appliance Edition (equipo físico)
- Software Edition (servidor / VM)
- Cloud Edition (UCaaS)

### Capacidades – Appliance Edition
- **P520:** 20 usuarios / 10 llamadas simultáneas
- **P550:** 50 usuarios / 25 llamadas simultáneas
- **P560:** 100 usuarios (base) o 200 usuarios (licencia) / 30 o 60 llamadas simultáneas
- **P570:** 300 / 400 / 500 usuarios / 60 / 90 / 120 llamadas simultáneas

Soporte adicional según modelo:
- FXS / FXO / BRI
- 3G / 4G
- E1/T1/J1  
  - P560: hasta 1 E1/T1/J1  
  - P570: hasta 2 E1/T1/J1

### Capacidades – Software Edition
- Hasta 10,000 extensiones
- Hasta 1,000 llamadas simultáneas
- SO soportado: Ubuntu 24.04 LTS / Debian 12
- Capacidad depende del dimensionamiento del servidor

### Cloud Edition
- Modelo UCaaS
- Alta disponibilidad
- Escalabilidad por demanda
- Gestión centralizada para MSP y partners

### Licenciamiento P-Series
Las licencias aplican para Appliance, Software y Cloud y habilitan funciones y escalabilidad dentro del límite de cada plataforma.

#### Plan Standard
- Telefonía IP completa
- Colas, IVR, grabación básica
- Softphone Linkus
- Administración web

#### Plan Enterprise
Incluye Standard +:
- Call Center avanzado
- Integraciones CRM
- Reportes y analítica
- Grabación y supervisión avanzada

#### Plan Ultimate
Incluye Enterprise +:
- Omnicanalidad (voz, chat, mensajería)
- Funciones con IA
- Integraciones avanzadas (Microsoft Teams, APIs)
- Multi-instancia en Cloud

Notas:
- Trunk Sharing: solo Cloud
- Grabación Cloud: 500 min incluidos
- API: no compatible con P520
- La PBX no es PoE (requiere alimentación AC/DC)

---

## 2) Yeastar S-Series VoIP PBX
PBX IP clásica para pequeñas y medianas empresas (equipos físicos).

### Capacidades por modelo
- **S412:** 20 usuarios / 8 llamadas simultáneas / hasta 12 FXS / 4 FXO o BRI / 2 GSM / 4 trunks VoIP
- **S20:** 20 usuarios / 10 llamadas simultáneas / hasta 4 FXS / 4 FXO o BRI / 1 GSM / 20 trunks VoIP
- **S50:** 50 usuarios / 25 llamadas simultáneas / hasta 8 FXS / 8 FXO o BRI / 4 GSM / 50 trunks VoIP

Recomendación:
- Para más de 50 usuarios o funciones avanzadas → usar P-Series

---

## 3) Yeastar Linkus – Softphone / UC Client
Aplicación de Comunicaciones Unificadas (Web, Windows, macOS, iOS, Android).

Funciones:
- Llamadas VoIP
- Transferencia, retención, grabación
- Chat individual y grupal
- Videollamadas (según PBX)
- Click-to-call desde navegador
- Integraciones CRM (según serie)

Compatibilidad:
- Windows 7+, macOS 10.11+
- iOS 11+, Android 8+
- Navegadores Chrome / Edge

---

## 4) Gateways Yeastar

### TE Series – E1/T1/PRI
- Modelos: TE100 / TE200
- 1 o 2 puertos E1/T1/J1
- Hasta 30 o 60 llamadas simultáneas
- SIP, TLS/SRTP, T.38, ISDN PRI

### TA Series – Analog VoIP Gateway
- FXS: 4 / 8 / 16 / 24 / 32
- FXO: 4 / 8 / 16
- SIP + IAX2
- QoS, VLAN, VPN, TR-069
- Funciones de telefonía completas

### TG Series – 4G LTE VoIP Gateway
- **TG200:** 2 canales
- **TG400:** 4 canales
- **TG800:** 8 canales
- **TG1600:** 16 canales

Funciones:
- SIP / IAX2
- SMS y SMS masivo
- USSD
- APIs abiertas
- OpenVPN, VLAN, QoS

---

## 5) Guía rápida de selección
- **P-Series:** Comunicaciones Unificadas y escalabilidad
- **S-Series:** PBX VoIP para PyME
- **TE:** PRI/E1 hacia SIP
- **TA:** Analógico hacia VoIP
- **TG:** Canales móviles 4G
- **Linkus:** Softphone y UC para usuarios

