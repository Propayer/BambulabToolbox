# MakerWorld → SCAD Builder

Herramienta independiente de BambuLab Toolbox, integrada en Inicio y en la barra
lateral. Conserva PySide6, el registro ToolDefinition y el parser de geometría de
Toolbox. No modifica el organizador, nesting, DSC ni sus formatos de exportación.

## Uso

1. Abre **SCAD Builder → Origen**. Introduce una URL pública de MakerWorld y pulsa
   **Analizar URL**, o importa un SCAD local que tengas derecho a utilizar.
2. Si el código no está públicamente disponible, carga el 3MF que hayas generado
   o descargado legítimamente. No se intenta eludir login, bloqueos ni protecciones.
3. En **Reconstrucción**, selecciona una pieza y pulsa **Ver pieza seleccionada**.
   Su nombre, dimensiones y propuesta son indicios, no una clasificación segura.
   Elige **Geometría fija**, **Texto paramétrico**, **Ignorar**, **Cubo/prisma** o
   **Cilindro aproximado**. Por defecto se conserva toda la geometría como malla.
4. En **Parámetros y colores**, edita texto, fuente, tamaño, altura, posición XYZ,
   rotación XYZ, alineación y separación. Cada texto usa por defecto el color base;
   selecciona **Independiente** para usar su parámetro de color propio, o
   **Heredar color de** para vincularlo a otro color. Los ciclos se rechazan.
   Puedes añadir parámetros desde la pestaña SCAD; los nuevos colores aparecen
   en los selectores de las piezas. Añadir un parámetro no lo vincula mágicamente
   a una geometría: úsalo en el SCAD o asígnalo mediante los controles existentes.
5. **SCAD editable** muestra el código. Si lo editas directamente, pulsa
   **Aplicar SCAD editado** para convertirlo en la fuente editable del proyecto.
   Conserva sus assets de referencia. Los campos se vuelven a analizar sin evaluar
   expresiones en Python. Vuelve a cargar el 3MF si quieres reiniciar la reconstrucción.
6. En **Validar/comparar**, detecta OpenSCAD o selecciona `openscad.exe`. La ruta
   se guarda mediante QSettings de esta herramienta. Validación, render, red,
   análisis y exportación se ejecutan en un QThread cancelable.
7. **Exportar paquete ZIP** guarda el modelo intermedio, SCAD y assets. Usa
   **Abrir paquete** para continuar trabajando después. Los cambios no se guardan
   automáticamente: exporta antes de cerrar.

## Paquete local y MakerWorld

El ZIP contiene una carpeta `model/`:

- `model.scad`: fuente local editable con assets individuales y roles de color.
- `model-parameters.json`: contrato `bambulab.scad-model.v1`, parámetros, elecciones
  por pieza, transformaciones, procedencia y código original si existe.
- `source-info.json`: URL/plataforma, modo de reconstrucción, disponibilidad de la
  fuente original, nombre del 3MF, avisos y hash del SCAD.
- `original.scad`: fuente importada, cuando existe. Se conserva separada del resultado.
- `preview.png`: silueta cenital de referencia, o marcador si falta referencia;
  **no se presenta como render del SCAD**.
- `assets/<sha256>.stl`: mallas normalizadas al origen de su bounding box. El SCAD
  aplica la traslación original. Assets idénticos se reutilizan físicamente.
- `makerworld.scad` y `default.stl`: para reconstrucciones, variante de carga PMM.
  Combina las piezas fijas en un STL. Es necesario cargarlo manualmente en PMM;
  no se presupone que PMM acepte una carpeta de assets arbitrarios.
- `UPLOAD-PMM.txt`: instrucciones y advertencias de portabilidad.
- `validation/`: STL/3MF renderizados, PNG si OpenGL está disponible y logs de la
  última validación realizada en la GUI. Se invalidan al cambiar parámetros.

La variante PMM combina las piezas fijas bajo el color base, porque STL no
conserva múltiples materiales. La variante local sí mantiene su asignación por
pieza. No se añaden módulos `mw_plate_N()` si el modelo no los necesita.

## Contrato intermedio

```json
{
  "schema": "bambulab.scad-model.v1",
  "parameters": [
    {"id": "base_color", "label": "Color base", "type": "color",
     "default": "#FFFF00", "scad_variable": "base_color"},
    {"id": "pet_name", "label": "Nombre", "type": "text", "default": "LUNA",
     "scad_variable": "custom_text",
     "color_binding": {"mode": "inherit", "source": "base_color"}}
  ],
  "elements": [],
  "source_info": {"source_url": "", "source_platform": "local",
    "reconstruction_mode": "reconstructed SCAD", "original_scad_available": false,
    "source_3mf": "reference.3mf", "warnings": []}
}
```

Tipos: `text`, `number`, `boolean`, `select`, `color`, `font`. Select utiliza
`options: [{"value": "S", "label": "Small"}]`. Number admite `min`, `max` y
`step`. `color_binding` es genérico: puede describir el color de texto, otra
pieza o la herencia entre parámetros Color. No cambia el tipo/valor del texto.
El generador local resuelve la referencia al color efectivo. Los alias de
parámetros Color se generan como asignaciones SCAD en Hidden.

El contrato está preparado para un futuro adaptador DSC. **No es** un ZIP
`dsc.preview-package.v2`, no debe importarse allí y no cambia ese contrato.
Las coordenadas geométricas son milímetros en el espacio build del 3MF, no
hitboxes normalizadas de una imagen.

## Arquitectura

`src/jarvis_bambu/core/scad_builder/`:

- `makerworld.py`: acceso HTTPS público acotado, metadatos HTML/JSON-LD, controles
  HTML visibles, bloques de código público y enlaces SCAD explícitos.
- `scad_analysis.py`: lexer conservador de literales top-level, Customizer,
  rangos/listas, color/font, módulos, dependencias y expresiones derivadas.
- `three_mf.py`: límites ZIP/XML/grafo y extracción de piezas. Reutiliza
  `_load_3mf_triangles` de `core/stl_color_map.py` mediante un callback opcional;
  las llamadas existentes conservan su comportamiento.
- `model.py`: parámetros y validación de herencia sin `eval`.
- `reconstruction.py`: propuestas conservadoras y decisiones explícitas.
- `generator.py`: generación determinista, deduplicación de assets, exportación
  ZIP mediante archivo temporal y reapertura del proyecto.
- `runner.py`: proceso OpenSCAD sin shell, timeout de 90 s por salida, cancelación,
  límites de logs/salida/memoria y rechazo de dependencias externas al ejecutar.
- `validation.py`: medidas, posición, componentes/volumen de mallas cerradas y
  comparación aproximada de silueta superior.

`gui/scad_builder/`: editor por pestañas y controles tipados. El registro en
`gui/app.py` es la integración con Toolbox; el cierre espera a la cancelación.
El parser no es un intérprete completo de OpenSCAD: conserva las expresiones
complejas como código en lugar de inventar valores.

## Referencia y límites conocidos

Referencia estudiada: [MakerWorld PMM/OpenSCAD agent-first](https://github.com/nelsonjchen/unofficial-makerworld-parametric-model-maker-openscad-docs),
AGENTS.md, pmm-openscad-api, agent-workflow, feature-reference,
compatibility-rules, gotchas, changelog y patterns. Es una referencia **no oficial**
con enlaces de procedencia; no una garantía de paridad con el runtime PMM.

- No recupera fuentes protegidas ni reconstruye automáticamente el CAD original.
- El HTML dinámico, autenticación o bloqueos pueden impedir incluso los metadatos.
  En esos casos usa la importación local. No se ejecuta JavaScript remoto.
- No identifica fuentes originales desde una malla ni separa automáticamente
  texto fusionado con la base. Hace falta una pieza separada o edición previa.
- Solo propone cajas y cilindros simples; no infiere automáticamente booleanas,
  offsets, perfiles arbitrarios o arrays paramétricos. Repeticiones se identifican
  mediante huellas, no se convierten automáticamente en bucles.
- La lectura conserva objetos/componentes y sus transformaciones mediante el parser
  actual. La pintura subdividida de Bambu y materiales interpolados conservan las
  limitaciones/avisos del parser existente.
- El comparador no demuestra igualdad: raster de 128 px, muestreo en mallas grandes,
  volumen/componentes omitidos por encima de 200000 caras. No hace CAD matching.
- Para ejecutar SCAD importado se rechazan includes/use y rutas externas/dinámicas.
  Pueden conservarse y exportarse, pero hay que aplanarlas/revisarlas para validar
  en la herramienta. OpenSCAD no se considera una sandbox para código hostil.
- La fuente elegida debe existir en el OpenSCAD local y en PMM; puede haber
  sustituciones de fuente o diferencias entre versiones. No se incluyen fuentes.
- El render PNG necesita OpenGL/entorno gráfico. Un fallo de PNG no invalida un
  STL/3MF correcto; los logs muestran la diferencia.
- No se ha ejecutado la compilación Windows ni una publicación real en MakerWorld
  desde este entorno Linux. Se conserva el build PyInstaller existente.

## Prueba local y compilación Windows

En PowerShell, dentro de `BambuAnalyzer`:

```powershell
.\setup_dev.cmd
.\run_gui.cmd
```

Para generar el ejecutable:

```powershell
.\build_exe.cmd
```

Salida: `dist\BambuLabToolbox\BambuLabToolbox.exe`. Distribuye la carpeta completa,
no únicamente el EXE. OpenSCAD es un programa externo; instala/configura su ruta
para renderizar. El builder no añade dependencias Python respecto a las ya
existentes en `requirements.txt`.

Pruebas:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:PYTHONPATH="src;."
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest tests -q
```

## Ejemplo reproducible incluido

`examples/scad-builder/reference-demo.3mf` es un fixture **sintético propio** de
una base y un marcador elevado. No se atribuye a ningún creador de MakerWorld.
Carga el archivo, marca la segunda pieza como Texto paramétrico y escribe LUNA.
`examples/scad-builder/model/model.scad` y `example-package.zip` son el resultado;
el directorio incluye STL/3MF generados realmente y la comparación.

La rama de una URL MakerWorld sin SCAD se prueba con una respuesta pública
simulada explícita en `test_public_source_and_blocked_fallback`. No se ha podido
validar una reconstrucción de un modelo real de MakerWorld sin un 3MF asociado
proporcionado por el usuario; el fixture permite probar el flujo sin inventar
la procedencia de una malla.

## Resultado de esta entrega

Suite completa: **172 passed, 1 skipped, 3 subtests passed** (42,85 s).
Incluye 13 tests nuevos del builder y sus controles Qt. Se ejecutó OpenSCAD local
para CSG/STL/3MF. El PNG OpenGL no pudo generarse porque no hay servidor X en
este entorno; el log lo indica. No hay Xvfb instalado.
La interfaz Qt se ejecutó en modo offscreen y se capturó en `SCAD_BUILDER_GUI.png`.
El único ajuste a tests anteriores simula la constante Windows de subprocess
en Linux; no cambia el controlador ni el motor.
