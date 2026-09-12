# Mapa de color STL / 3MF

Herramienta modular para preparar previews por altura para DSC Minerva Artis sin
activar renderizado 3D de forma automática.

## Flujo

1. Cargar un STL o 3MF.
2. Se analiza la geometría en `core` y se muestra una **preview ligera 2D**.
   - En 3MF se reutiliza `Metadata/plate_1.png` cuando existe, igual que en el
     analizador de precios.
   - En STL se genera una proyección cenital ligera sin abrir el renderer 3D.
3. Si el 3MF contiene varias asignaciones de filamento/colores, se crea primero
   una propuesta `3MF · Guiado por … colores existentes`.
4. El usuario puede seleccionar cualquier propuesta geométrica.
5. `Generar vista previa de alturas` crea bajo demanda:
   - vista cenital con todas las zonas apiladas;
   - vista independiente de cada zona.
6. El render 3D permanece apagado. `Empezar renderizado 3D` muestra una
   advertencia antes de activarlo. `Parar renderizado 3D` descarga la malla del
   visor interactivo.
7. En 3D se puede rotar, hacer zoom y clicar una superficie para tomar su Z y
   crear un corte manual.
8. `Exportar paquete DSC` genera sin depender del render 3D:
   - `model-map.json` (`dsc.stl-height-map.v2`)
   - `preview.png` neutral
   - `height-map-preview.png` cenital coloreado
   - `color_1.png`, `color_2.png`, ... máscaras transparentes

## Detección de color 3MF

El parser aprovecha información ya presente en proyectos Bambu:

- asignación `extruder` a objetos/partes en `Metadata/model_settings.config`;
- paleta `filament_colour`/`filament_multi_colour` de
  `Metadata/project_settings.config`;
- colores de filamento en `Metadata/slice_info.config`;
- `paint_color` de caras cuando representa una cara completa.

Los colores existentes se usan **como guía para alturas**, no como una promesa
de segmentación arbitraria por superficie. Si dos colores ocupan la misma altura
por pintura lateral, el usuario debe corregir los cortes.

## Arquitectura

- `jarvis_bambu.core.stl_color_map`: STL/3MF, geometría, perfiles, propuestas,
  detección de colores, clipping exacto por Z y contrato de exportación.
- `jarvis_bambu.gui.stl_color_map`: previews 2D, galería de capas e interacción
  3D opcional.
- `jarvis_bambu.gui.app`: solo registra la herramienta con `ToolDefinition`.

No se añaden dependencias nuevas.
