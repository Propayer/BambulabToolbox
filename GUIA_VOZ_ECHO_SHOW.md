# Instalar el diálogo del optimizador en el Echo Show

Este flujo usa la aplicación de Home Assistant instalada en el Echo Show,
`media_player.echo_show`, Piper, Browser Mod, MQTT y los botones de HASS.Agent.
No utiliza ni requiere `assist_satellite`.

## Archivos

1. Copia `home_assistant/jarvis_bambu_optimizer.yaml` como
   `/config/packages/jarvis_bambu_optimizer.yaml`.
2. Copia `home_assistant/custom_sentences_es_jarvis_bambu.yaml` como
   `/config/custom_sentences/es/jarvis_bambu.yaml`.
3. Deja desactivado o elimina el anterior
   `/config/packages/jarvis_bambu_optimizer.yaml.disabled` después de copiar el
   nuevo archivo.

## Activación

1. En **Herramientas para desarrolladores > YAML**, comprueba la configuración.
2. Reinicia Home Assistant.
3. En **Herramientas para desarrolladores > Estados**, verifica que existe
   `input_select.jarvis_optimizador_paso` y está en `idle`.

## Ayudantes visuales compartidos

Además de los cuatro controles del dashboard, crea dos desplegables editables:

- `input_select.jarvis_destino_preview`, con opciones `pc` y `echo_show`.
- `input_select.jarvis_modo_preview`, con opciones `improvements` y `debug`.

La voz y el dashboard escriben en los mismos ayudantes.

## Primera prueba

1. Desde el Echo o la ventana de Assist di «Optimiza esta cama».
2. El Echo preguntará «¿Modo simple o avanzado?».
3. Activa de nuevo la entrada de voz de Home Assistant para cada respuesta. Al
   no ser un satélite, cada respuesta es una nueva petición de Assist, aunque el
   estado permite mantener el hilo de la conversación.
4. Responde sucesivamente al cuestionario. Las respuestas admitidas incluyen:
   `simple`, `avanzado`, `bajo`, `medio`, `alto`, `con preview`, `sin preview`,
   `PC`, `Echo Show`, `normal`, `debug`,
   `preguntar`, `abrir directamente`, `aparte` y `en mi ventana`.

Si Assist muestra una respuesta vacía mientras el Echo formula la pregunta, es
normal: la voz del cuestionario se envía directamente mediante Piper para que
salga por `media_player.echo_show`.
