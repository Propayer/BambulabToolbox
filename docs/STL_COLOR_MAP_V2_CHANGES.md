# STL / 3MF Color Map v2 — cambios

- Carga STL y 3MF.
- El render 3D ya no se inicia al cargar un modelo.
- Preview ligera automática:
  - 3MF: reutiliza `Metadata/plate_1.png` si existe.
  - STL: proyección cenital ligera local.
- Botón `Generar vista previa de alturas`:
  - vista cenital de todas las zonas apiladas;
  - preview separada para cada zona.
- Render 3D bajo demanda:
  - `Empezar renderizado 3D` con aviso de coste;
  - `Parar renderizado 3D` libera la malla del viewer;
  - selección de altura por clic solo cuando está activo.
- Análisis 3MF antes de proponer el mapa:
  - asignaciones de extrusor por objeto/parte;
  - paleta de filamentos;
  - `paint_color` cuando la pintura corresponde a la cara completa;
  - propuesta `3MF · Guiado por ... colores existentes` cuando hay más de un color útil.
- Exportación DSC independiente del render 3D:
  - `model-map.json` v2;
  - `preview.png` neutral;
  - `height-map-preview.png`;
  - máscaras `color_N.png`.

La detección de colores sirve como guía de alturas. Pinturas laterales o pintura
subdividida compleja pueden requerir ajustar manualmente los cortes.
