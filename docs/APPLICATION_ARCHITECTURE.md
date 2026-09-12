# Caja de herramientas BambuLab

## Motor congelado

El motor existente continúa en `nesting_optimizer.py`, `optimizer_models.py` y
`three_mf_project.py`. Las capas nuevas lo consumen mediante
`jarvis_bambu.core.optimize_project`; no duplican nesting, scoring o geometría.

Estado de referencia al iniciar la migración:

- SIMPLE conserva la separación por plates y optimiza cada plate por separado.
- ADVANCED puede redistribuir piezas, usa búsqueda evolutiva y workers entre genomas.
- Workers recomendados: `Auto` (todos menos un núcleo, limitado por población).
- Configuración equilibrada: ADVANCED, esfuerzo Medio, preview normal, workers Auto.
- El deadline limita la mejora y conserva una solución completa; la distribución
  original es el límite superior de plates.
- Preview es opcional; `debug` publica intentos y `improvements` solo mejoras.
- Benchmark conocido de 192 piezas: aproximadamente 156 s con 1 worker y 158 s
  con 4 workers, ambos con 4 plates (el resultado depende del presupuesto temporal).

## Capas

- `core/api.py`: API estable e independiente de MQTT/GUI/CLI.
- `core/installation.py`: identidad persistente bajo `%LOCALAPPDATA%`.
- `core/routing.py`: sobre de mensajes y rechazo estricto por `target_id`.
- `integrations/`: adaptadores MQTT y consultas futuras.
- `gui/`: aplicación PySide6, registro modular y conversión de opciones.

Para registrar una herramienta se añade un `ToolDefinition` al registro de
`MainWindow`, proporcionando identificador, textos, icono y `widget_factory`.

## Desarrollo

```powershell
$env:PYTHONPATH="src"
python -m jarvis_bambu.gui
```

PySide6 está declarado en `requirements.txt`. El siguiente paso de distribución
es añadir metadatos de paquete y una configuración PyInstaller/Nuitka; no se ha
creado instalador ni updater en esta fase.

## GUI y ayuda

`gui/theme.py` concentra el estilo compatible con la paleta Qt clara u oscura.
`gui/help_content.py` es la única fuente para tooltips, botones `?` y la Guía
buscable. El reloj de la ventana usa `time.monotonic()` mediante un `QTimer` de
500 ms: la barra representa presupuesto de búsqueda, nunca progreso algorítmico.

Los límites mostrados se leen de `OptimizerOptions.time_limit_seconds`: Rápido
1 min, Medio 3 min y Alto sin límite temporal fijo.

## Mapa de color STL / 3MF

La herramienta `stl_color_map` mantiene la separación modular del resto de la aplicación:

- `core/stl_color_map.py`: lectura STL/3MF, extracción de mallas, detección de
  asignaciones de filamento, perfil geométrico, propuestas de cortes y clipping Z.
- `gui/stl_color_map.py`: preview 2D ligera, previews cenitales de alturas y viewer
  3D opcional que solo se carga tras confirmación del usuario.
- `gui/app.py`: únicamente registra la herramienta mediante `ToolDefinition`.

El render interactivo no participa en el análisis ni en la exportación, por lo que
equipos modestos pueden usar la herramienta completa sin activarlo.
