# Optimizaciones de BambuLab Toolbox

Fecha: 12 de septiembre de 2026. Cambios sobre el proyecto recibido, conservando su paquete `jarvis_bambu`, registro de herramientas, configuración, CLI, plantilla Excel, recursos y sistema PyInstaller. BambuLab Toolbox conserva nombre y logo; Nebu v1.1 aporta únicamente el lenguaje visual.

## Carga de archivos

### Optimización
Análisis y preparación de imágenes fuera del hilo de interfaz; cancelación cooperativa.
### Antes
`load_file` analizaba la malla y dibujaba la preview en el hilo de Qt.
### Después
Un `MapTask` ejecuta la operación; el hilo principal recibe el resultado al finalizar. La cancelación se consulta entre etapas y bloques de parsing/rasterización. Un resultado cancelado no sustituye el modelo anterior. El cierre de ventana espera de forma asíncrona a que termine el worker.
### Motivo
La interfaz sigue atendiendo eventos; se evita destruir un QThread activo. Las operaciones nativas indivisibles (lectura, XML, NumPy) terminan su etapa antes de cancelar.
### Impacto estimado
Alto en capacidad de respuesta; no equivale a acelerar el disco.

## STL

### Optimización
Perfil geométrico vectorizado y validación de geometría.
### Antes
Se recorría la malla para cada una de 180 alturas; las selecciones copiaban subconjuntos para calcular su envolvente XY.
### Después
Los cruces se calculan con extremos Z ordenados y `searchsorted`; un histograma ponderado por área proyectada detecta cambios de superficie. Se descartan triángulos sin área y se rechazan coordenadas no finitas/modelos sin geometría.
### Motivo
Elimina el barrido repetido de la malla por altura. El perfil ahora mide área proyectada por banda, no el área de la caja envolvente anterior; las propuestas son orientativas, no cortes de laminador certificados.
### Impacto estimado
Alto en análisis de mallas grandes.

## 3MF

### Optimización
Índice de objetos por documento, transformaciones afines sin coordenadas homogéneas y guía que conserva colores repetidos en distintas alturas.
### Antes
Búsqueda lineal de objetos; matriz temporal de cuatro columnas para cada vértice; propuesta basada en una mediana por filamento. Pintura subdividida se ignoraba sin advertencia específica.
### Después
Diccionarios por documento XML; transformación `XYZ @ R.T + t`; histogramas de área por material/altura. Se conservan las asignaciones de objetos/partes y pintura de cara completa admitidas por el lector previo, y se añaden materiales base/colorgroup con índices uniformes. Las unidades se convierten a mm. Se comprueban índices y referencias.
### Motivo
Menos búsquedas y copias. Un material que reaparece en alturas separadas ya no se reduce necesariamente a una sola zona. Las limitaciones quedan visibles y se exportan en JSON.
### Impacto estimado
Medio en rendimiento; alto en claridad del resultado.

La pintura subdividida de Bambu no se decodifica completamente. Colores interpolados por vértice tampoco. Se usa la asignación conocida como aproximación y se avisa. La detección de solapamiento de materiales usa 256 bandas Z y es conservadora: detecta incompatibilidades, pero no acredita que una guía sea exacta en todos los modelos. Si hay advertencias, no se selecciona automáticamente la propuesta guiada; el usuario puede elegirla o editar manualmente.

## Previews

### Optimización
Preview embebida compartida y huella ligera de 256 px.
### Antes
Dos lectores de thumbnails; render fallback mediante miles de polígonos QPainter, con submuestreo.
### Después
`model_preview.read_3mf_preview` se comparte con precios. Si no hay thumbnail válida, se usa el mismo raster cenital del core a 256 px. Nunca se inicializa el visor 3D para cargar el archivo.
### Motivo
Reutilización real de infraestructura y una sola definición geométrica de la huella. El thumbnail del 3MF puede tener perspectiva: se etiqueta como tal y no se usa para generar máscaras.
### Impacto estimado
Medio.

## Máscaras

### Optimización
Visibilidad cenital con Z-buffer y clasificación posterior.
### Antes
Se recortaban los triángulos por zonas y se proyectaba cada zona de forma independiente. Las caras ocultas aparecían en sus máscaras. Existía submuestreo a 65.000 piezas y antialiasing. Las previews individuales tenían resolución diferente.
### Después
Por cada centro de píxel se conserva el máximo Z interpolado de la malla completa. La clasificación por intervalos produce un único mapa de etiquetas. Todas las imágenes derivan del mismo búfer, con dimensiones, escala y encuadre idénticos. Alfa 0/255; cada píxel visible pertenece a exactamente una zona.
### Motivo
Corrige la causa geométrica. Cambiar cortes solamente reclasifica el búfer: no relee el archivo ni recorta/rasteriza de nuevo los triángulos.
### Impacto estimado
Alto en exactitud de máscaras y coste de ediciones sucesivas.

## Visor 3D

### Optimización
Inicialización diferida, preparación de geometría en worker y liberación efectiva.
### Antes
El widget ya se construía al entrar en la herramienta y el clipping se calculaba sin worker. Durante cada repintado se volvían a calcular los límites de toda la malla.
### Después
El módulo/widget solo se importa y crea tras confirmar con botones explícitos. El clipping se conserva, limitado a una muestra de 6.000 caras para interacción y preparado en worker. Los límites se reutilizan desde `MeshSummary`. Se añade pan con botón derecho; rotación izquierda y zoom con rueda. Picking interpolado por profundidad entre las caras mostradas. Al parar se vacían geometría/picking/modelo, se retira el widget y se destruye con `deleteLater`.
### Motivo
No hay temporizador de animación ni trabajo 3D en segundo plano al detenerlo. La muestra del visor nunca interviene en las máscaras.
### Impacto estimado
Alto en carga inicial y recursos al detener; medio en interacción.

Límite: el visor opcional sigue siendo un renderer software de diagnóstico. En mallas complejas muestra una muestra, no una simplificación topológica garantizada. La oclusión del mapa/exportación se verifica con Z-buffer; el visor 3D interactivo conserva ordenación de polígonos y no promete el mismo nivel de exactitud visual.

## Memoria

### Optimización
Caché acotada y temporales de rasterización limitados.
### Antes
Listas grandes de triángulos recortados y reconstrucción de imágenes por zona.
### Después
Hasta dos resoluciones de profundidad por modelo. Transformación XY en bloques de 1.024 triángulos y evaluación de píxeles en tiras de 32 filas. No se construye un tensor triángulos × canvas. El exportador codifica una imagen cada vez; el visor libera sus referencias al pararse.
### Motivo
Memoria temporal predecible. Un búfer de profundidad float64 más índice de cara int32 ocupa 3 MiB a 512². Las imágenes de GUI y la malla ocupan memoria adicional; 1.024 px y muchas zonas consumen más.
### Impacto estimado
Alto.

## GUI

### Optimización
Tema común Nebu, edición numérica y galería sin acumulaciones.
### Antes
Paleta genérica del sistema y colores oscuros procedentes de los filamentos. No había editor numérico de cortes accesible sin visor.
### Después
Tokens del kit: grafito #10191D, superficie #1B282E, menta #72E2C0, texto #F2F6F4; radios 8/12 px y Ubuntu con fallback Segoe UI. Colores diagnósticos independientes. Corte exacto con spinbox o doble clic; picking en cenital; nombre/ID editables. Estados, progreso y cancelación. La galería anterior se elimina antes de reconstruirla. Controles desplazables.
### Motivo
Legibilidad y consistencia sin cambiar la marca del producto. Cambiar el número de zonas o aplicar otra propuesta restablece sus nombres/IDs; conviene nombrarlas después de fijar los cortes.
### Impacto estimado
Medio en mantenimiento; alto en usabilidad.

## IO

### Optimización
Exportación atómica y paquetes autocontenidos.
### Antes
Se exportaba una carpeta reutilizada y después todo su contenido: podían entrar máscaras obsoletas de una exportación anterior. JSON e imágenes no tenían importador directo en DSC.
### Después
ZIP temporal con lista explícita de archivos, seguido de reemplazo atómico al completar. La cancelación/fallo conserva el ZIP anterior. El core admite exportación sin Qt. DSC valida dimensiones, alfa, unión y exclusividad de máscaras antes de escribir recursos con nombres opacos.
### Motivo
Evita paquetes parciales y archivos sobrantes; protege la relación campo/máscara.
### Impacto estimado
Medio.

## Código duplicado

### Optimización
Lectura común de thumbnail y ruta única de rasterización.
### Antes
Lectores embebidos separados, render de huella y render de máscaras diferentes.
### Después
`model_preview.py` para recursos 3MF; `core/height_raster.py` para rasterización; las funciones GUI solo convierten RGBA a QImage. `core/dsc_export.py` genera el paquete sin depender de GUI.
### Motivo
Menos divergencias entre lo que se revisa y lo que se entrega.
### Impacto estimado
Medio.

## Arquitectura

### Optimización
Separación del visor y del contrato de exportación.
### Antes
La GUI contenía proyección, clipping para exportación y escritura de paquetes.
### Después
El core contiene malla, perfil, propuestas, profundidad y exportador. `gui/height_viewer.py` contiene interacción/dibujo opcional. `gui/stl_color_map.py` orquesta presentación y workers. `app/preview_package.py` añade el importador DSC sin modificar los modelos anteriores.
### Motivo
Tests sin Qt, extensiones futuras y compatibilidad con el registro actual. No se renombra `jarvis_bambu` ni se cambian rutas CLI. No se añaden dependencias de producción; pytest se declara solo para desarrollo/tests.
### Impacto estimado
Alto en mantenimiento.

## Otras herramientas

### Optimización
Inspección ligera STL y previews de precios sin colisiones entre carpetas.
### Antes
Un STL ASCII se leía completo para comprobar si comenzaba por `solid`; thumbnails de archivos con el mismo basename compartían destino.
### Después
Se reutilizan los primeros 84 bytes ya leídos. El nombre del thumbnail incluye un hash de la ruta y la lectura embebida usa la utilidad compartida.
### Motivo
Reduce IO innecesario y evita que dos trabajos distintos muestren la misma preview por sobrescritura.
### Impacto estimado
Bajo/medio, según tamaño de archivos.

Se revisaron la inicialización, precios, recursos, exportación y wrappers de las demás herramientas. No se alteró el algoritmo del organizador, sus opciones ni sus estructuras; tampoco se rehizo su arranque. Las optimizaciones aquí descritas son acotadas, no una auditoría exhaustiva de cada línea del proyecto.

## Medición reproducible

`PYTHONPATH=src python benchmarks/benchmark_height_map.py`

En este entorno Linux/Python 3.12, malla sintética de 20.000 triángulos, 512²:

| Operación | Medición |
|---|---:|
| Análisis y propuestas | 0,0081 s |
| Primer Z-buffer | 0,6421 s |
| Reclasificación tras editar cortes, media de 50 | 0,000883 s |
| Búfer profundidad + cara | 3.145.728 bytes |

No se ha medido aceleración relativa frente a la versión anterior. Los apartados Antes describen el código recibido; los impactos son estimaciones razonadas. La carga depende de tamaño, solapamiento y cobertura de los triángulos, no solo de su número.

## Revisión posterior de interfaz Nebu

### Optimización
GUI y previews: distribución adaptable, canvas compartido y contenido contextual.

### Antes
La navegación ocupaba demasiado ancho, los controles podían quedar desplazados horizontalmente y las secciones competían por espacio. Las imágenes podían condicionar el tamaño mínimo del layout.

### Después
Navegación compacta, inspector con desplazamiento solo vertical, pestañas, exportación persistente y canvas cuyo tamaño depende del espacio disponible. Recorte cacheado del margen transparente de miniaturas embebidas. Máscaras y core sin cambios.

### Motivo
Evita reconstruir imágenes al redimensionar, conserva el encuadre de exportación y hace visible cada etapa de trabajo. Componentes visuales compartidos separados del controlador. Las transiciones terminan a los 160 ms; no generan trabajo en reposo.

### Impacto estimado
Medio en mantenibilidad y uso del espacio. Bajo en procesamiento; no se atribuyen mejoras al algoritmo de malla en esta revisión. Ver INTERFAZ_NEBU.md.
