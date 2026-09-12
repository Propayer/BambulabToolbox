# Interfaz BambuLab Toolbox · revisión Nebu

Se continúa la aplicación Qt existente. Se conservan el nombre BambuLab Toolbox, el ICO original, el registro de herramientas y la separación core/GUI. Esta revisión no cambia el core, los algoritmos del organizador ni el contrato DSC.

## Aplicación del manual v1.1

El manual pide precisión, calma y autonomía; información contextual, una acción principal por bloque y estado persistente. Se aplica a la distribución y al comportamiento, además de la paleta:

- Base #10191D, superficies #1B282E / #25363E, acento menta #72E2C0 y lavanda #BBAAFF. Color concentrado en acciones y estados.
- Jerarquía tipográfica: título de página, títulos de bloque, texto y ayuda secundaria. Fuente de sistema equivalente para mantener compatibilidad sin descargar fuentes.
- Navegación de 208 px que se reduce a iconos de 72 px en ventanas estrechas; nombres completos en tooltips. Logo original visible.
- Inicio con tarjetas en dos columnas y accesos a las herramientas registradas.
- Mapa dividido en selección de propuesta, edición de zonas y espacio de revisión. La columna de controles solo desplaza verticalmente; no queda desplazada fuera de la ventana.
- Pestañas Vista cenital, Máscaras y Explorar 3D. La vista completa dispone del espacio principal y cada máscara tiene su propia tarjeta.
- Exportación, resolución, progreso y cancelación permanecen en el pie visible.
- Avisos del 3MF accesibles bajo un control contextual; estado del mapa y siguiente acción visibles.
- Seleccionar una zona permite aislarla. Pulsar la vista cenital obtiene Z; se mantienen edición exacta y nombres/IDs.
- Transición discreta de 160 ms entre pestañas; sin animación continua. NEBU_REDUCED_MOTION=1 la desactiva.
- La miniatura embebida puede recortar su margen transparente para aprovechar el visor. Las máscaras conservan íntegro su encuadre común y el exportador permanece intacto.

## Arquitectura

`color_map_layout.py` construye la interfaz; `stl_color_map.py` conserva el controlador y sus workers. `workspace_widgets.py` contiene iconos vectoriales, canvas ligero y transición de pestañas. `theme.py` centraliza estilos y paleta Qt, incluyendo estados deshabilitados y foco. No se añaden dependencias de producción.

La especificación PyInstaller incluye ahora assets como datos para que el logo también esté disponible dentro de la ventana del ejecutable.

## Comprobación

Capturas reales de Qt offscreen en `validation/nebu/`, con un relieve sintético conocido; no son mockups ni representan el archivo de la captura del usuario. Inspección visual a 1360×860 y 1000×720. Tests de distribución a 960×640, 1000×720, 1360×860 y 1920×1080, con textos largos de 3MF, sin desbordamiento horizontal del inspector. Se verifican aislamiento, invalidación y recorte exclusivo de miniaturas.

Suite completa en Linux: 125 tests aprobados, 3 subtests aprobados y 1 fallo preexistente reproducido sobre la copia anterior. El test de conexión a Bambu Studio simula Windows sobre Linux, donde no existe subprocess.CREATE_NEW_PROCESS_GROUP. No se modifica esa integración ni el organizador para resolver un problema del entorno de prueba.

La apariencia nativa, escalado de Windows y conexión real con Bambu Studio requieren verificación en Windows. El entorno actual es Linux.
