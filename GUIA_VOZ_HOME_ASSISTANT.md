# Conectar el optimizador de Bambu a la voz de Home Assistant

Esta configuración permite iniciar el optimizador mediante Assist, responder a
las preguntas de modo y esfuerzo y decidir dónde abrir el resultado.

> El diálogo interactivo requiere una entidad `assist_satellite`. Un Echo Show
> no se convierte por sí solo en un satélite de Assist. El Echo se integrará
> después para mostrar la preview y reproducir avisos; mientras tanto, prueba el
> diálogo desde un satélite de Home Assistant o desde Assist en el móvil.

## 1. Activar MQTT en Home Assistant

1. En Home Assistant abre **Ajustes > Complementos > Tienda de complementos**.
2. Instala **Mosquitto broker**, inicia el complemento y activa **Iniciar al arrancar**.
3. Abre **Ajustes > Personas > Usuarios** y crea un usuario local llamado
   `jarvis_mqtt` con una contraseña propia.
4. Abre `C:\Jarvis\BambuAnalyzer\config.yaml` en el PC.
5. Sustituye la sección `mqtt` por esta, usando la IP real de Home Assistant:

   ```yaml
   mqtt:
     enabled: true
     host: "192.168.1.100"
     port: 1883
     username: "jarvis_mqtt"
     password: "TU_CONTRASEÑA"
     base_topic: "jarvis/bambu_analyzer"
     discovery_prefix: "homeassistant"
   ```

6. Guarda el archivo y ejecuta una optimización una vez. Esto publica los
   sensores MQTT del programa.
7. En Home Assistant abre **Herramientas para desarrolladores > Estados** y
   busca `jarvis_bambu_status` o **Estado del analizador Bambu**. Anota su
   `entity_id`; normalmente será `sensor.estado_del_analizador_bambu`.

## 2. Crear los botones en HASS.Agent

1. Abre HASS.Agent en el PC.
2. Entra en **Configuration > Commands** y pulsa **Add New**.
3. En cada comando selecciona tipo **Custom**, exposición **Button**, escribe
   el nombre y pega el comando correspondiente.
4. Crea los 20 comandos del archivo
   `home_assistant\COMANDOS_HASS_AGENT.txt`.
5. Pulsa **Store and Activate Commands**.
6. En Home Assistant abre **Ajustes > Dispositivos y servicios > HASS.Agent >
   Dispositivos**, entra en tu PC y comprueba que aparecen los 20 botones.
7. Abre **Herramientas para desarrolladores > Acciones**, ejecuta
   `button.press` sobre `button.jarvis_optimizar_advanced_low_ask` y confirma
   que el PC inicia el programa.

Si el identificador real de algún botón no coincide, anótalo. Home Assistant
convierte los espacios del nombre a guiones bajos.

## 3. Activar los paquetes de Home Assistant

1. Instala **Studio Code Server** o **File editor** desde la tienda de
   complementos y ábrelo.
2. Abre `/config/configuration.yaml`.
3. Si no existe una sección `homeassistant:`, añade:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

4. Si ya existe `homeassistant:`, añade solo esta línea dentro de ella,
   respetando sus dos espacios de sangría:

   ```yaml
     packages: !include_dir_named packages
   ```

5. Crea la carpeta `/config/packages` si no existe.
6. Copia el archivo
   `C:\Jarvis\BambuAnalyzer\home_assistant\jarvis_bambu_optimizer.yaml` del PC
   a `/config/packages/jarvis_bambu_optimizer.yaml` en Home Assistant.

## 4. Indicar el satélite y el sensor correctos

1. En **Herramientas para desarrolladores > Estados**, filtra por
   `assist_satellite` y copia la entidad del dispositivo desde el que hablarás,
   por ejemplo `assist_satellite.jarvis_salon`.
2. Abre `/config/packages/jarvis_bambu_optimizer.yaml`.
3. Reemplaza todas las apariciones de:

   ```yaml
   assist_satellite.REEMPLAZAR
   ```

   por la entidad real del satélite.
4. Reemplaza:

   ```yaml
   sensor.REEMPLAZAR_ESTADO_ANALIZADOR
   ```

   por el sensor anotado en el apartado 1.
5. Comprueba que los nombres construidos en `boton_inicio` coinciden con los
   botones reales de HASS.Agent. Si mantuviste exactamente los nombres de la
   guía, no tendrás que modificar esa plantilla.

## 5. Instalar las frases naturales

1. Crea las carpetas `/config/custom_sentences/es` si no existen.
2. Copia
   `C:\Jarvis\BambuAnalyzer\home_assistant\custom_sentences_es_jarvis_bambu.yaml`
   como `/config/custom_sentences/es/jarvis_bambu.yaml`.
3. En Home Assistant abre **Herramientas para desarrolladores > YAML**.
4. Pulsa **Comprobar configuración**. Si no aparece ningún error, reinicia Home
   Assistant desde **Ajustes > Sistema > Reiniciar**.

## 6. Probar primero sin voz

1. Abre **Herramientas para desarrolladores > Acciones**.
2. Selecciona `script.jarvis_optimizar_colocacion_dialogo` y pulsa **Ejecutar**.
3. El satélite debe preguntar: «¿Modo simple o avanzado?».
4. Responde las preguntas hasta que HASS.Agent inicie el comando.
5. Al terminar, el sensor MQTT debe cambiar a `listo para abrir` y Jarvis debe
   preguntar si abre el resultado aparte o en la ventana actual.

## 7. Probar la frase

Di una de estas frases desde el mismo satélite:

- «Optimiza esta cama».
- «Optimiza la colocación».
- «Reorganiza las piezas de esta cama».

También puedes escribir la frase en la ventana de Assist para separar los
problemas de reconocimiento de voz de los problemas de automatización.

## Si todavía no existe un `assist_satellite`

No reemplaces el marcador por una entidad inventada. Los botones de HASS.Agent
y los sensores MQTT seguirán funcionando, pero el cuestionario no podrá hacer
preguntas. En ese caso se puede crear provisionalmente una frase directa para
cada modo o terminar la conexión mediante la skill de Alexa prevista para el
Echo Show.
