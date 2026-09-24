# Contrato DSC · Toolbox v2

## Fuente verificada

Esta entrega se contrastó con `DSC-Minerva-Artis-Importador-Sistema-paramétrico(1).zip`, versión disponible del 14-09-2026. Se leyeron `DSC_EXPORT_FORMAT.md`, `ACTUALIZACION_TOOLBOX.md`, `app/preview_package.py`, `app/live_fields.py`, `app/validation.py`, `app/static/js/preview-editor.js`, `app/static/js/live-preview.js` y los tests de importación/campos vivos. No se modifica DSC. Los hashes de estos archivos están en `validation/dsc-v2/contrato-fuentes.json`.

La exportación nueva usa `dsc.preview-package.v2`; puede elegirse v1 para modelos sin campos vivos. El schema geométrico sigue siendo `dsc.stl-height-map.v2` en ambas versiones. v1 con campos vivos se rechaza, evitando pérdida silenciosa de personalización.

## Archivos

Todos en la raíz del ZIP; sin rutas, archivos ajenos, duplicados, enlaces ni cifrado:

| Archivo | Contenido |
|---|---|
| model-map.json | Metadatos, orientación, campos de color y campos vivos |
| preview.png | Huella visible completa, blanca, RGBA |
| color_1.png … color_N.png | Una máscara exclusiva por zona, blanca, RGBA |
| height-map-preview.png | Diagnóstico contrastado, opcional en DSC; Toolbox lo incluye |

Resoluciones cuadradas permitidas: 256, 512 (predeterminada), 1024. Todas las imágenes tienen la misma resolución. Ninguna depende del tamaño de la ventana. Dentro de base/máscara: `(255,255,255,255)`; fuera: `(0,0,0,0)`. Sin antialiasing. Las máscaras no se solapan y su unión coincide píxel a píxel con el alfa de la base. Una máscara individual vacía es válida; una huella completa vacía no lo es. El texto de campos vivos **no se incorpora a los PNG**.

## Proyección y coordenadas

Ortográfica, cámara +Z, derecha +X, arriba +Y. Se usa el modelo ensamblado en milímetros, respetando transformaciones build/componentes de 3MF. Sin rotación automática.

```
scale = size * 0.88 / max(width_X, height_Y)
x_pixel = (X - center_X) * scale + size/2
y_pixel = -(Y - center_Y) * scale + size/2
```

El centro es el del bounding box XY. El muestreo ocurre en `(col+0.5,row+0.5)`. Se interpola Z y conserva el máximo de los triángulos que cubren ese punto. Cada altura visible pertenece a `[from,to)`; una altura exactamente igual al corte pertenece al intervalo superior; el último incluye el máximo.

## model-map.json

El exportador calcula `source`, `source_type`, `triangle_count`, `bounds.min/max`, `height`, `zones`, `detected_colors`, `warnings` y `view` del modelo real. `view` incluye `projection:orthographic`, `camera:+Z`, `image_right:+X`, `image_up:+Y`, `width/height`, `center_xy_mm`, `pixels_per_mm`, `sampling:pixel-center`, `intervals:[from,to); last includes maximum`, `alpha:binary`.

`preview.base_image` es `preview.png`. `preview.layers` vincula cada ID de zona a `color_<índice empezando en 1>.png`. El ID puede ser `base_color`; el nombre de archivo sigue siendo `color_1.png`.

Cada zona incluye `id`, `label`, `z_from`, `z_to`. Cada entrada v2 `live_fields` incluye:

```json
{
  "field_id": "pet_name",
  "label": "Nombre",
  "type": "text",
  "default": "LUNA",
  "enabled": true,
  "hitbox": {"x": 0.24, "y": 0.41, "width": 0.52, "height": 0.14}
}
```

`live_fields:[]` es válido. En v1 se omite. IDs únicos entre colores y campos vivos, patrón `^[a-z][a-z0-9_-]{0,63}$`, excluyendo `constructor`, `prototype`, `__proto__`. Labels no vacíos, máximo 100 caracteres. Máximo 12 zonas de color y 40 campos totales. Tipos vivos: `text` y `number`. Default texto hasta 200 caracteres; número JSON finito (no string numérico ni booleano), valor absoluto ≤999999999999, hasta seis decimales, o `""` sin valor. Se replica la validación del importador real, que también rechaza representaciones numéricas exponenciales como `1e-6`.

Hitbox referida al **canvas completo**, origen arriba-izquierda, unidades normalizadas. `x,y≥0`, `width,height>0`, `x+width≤1`, `y+height≤1`. Solo números finitos, no booleanos. `null` se conserva como campo sin zona. `enabled` booleano; desactivado no muestra texto. Opcionales aceptados: `rotation_deg:0`, `align:center`, `vertical_align:middle`; otras disposiciones y propiedades desconocidas se rechazan. Toolbox normaliza esa disposición a las cuatro coordenadas.

## Plantillas de ida y vuelta

Se importa `dsc-live-field-*.json` con `schema:dsc.live-field-template.v1`, `package_schema:dsc.preview-package.v2`, objeto `field` (`id,label,type,default`), `enabled`, `hitbox` y:

```json
{"coordinate_system":{"origin":"top-left","units":"normalized","reference":"preview_canvas"}}
```

La importación conserva ID, nombre, tipo, default y hitbox (incluido null). Rechaza IDs duplicados para no sustituir otro campo accidentalmente. El editor también permite crear un campo localmente.

1. Cargar STL/3MF y generar la vista de alturas.
2. Abrir Campos vivos e importar la plantilla DSC.
3. Seleccionar el campo, arrastrar caja/esquinas o introducir coordenadas. Aplicar cambios para visualizar valores manuales. Los cambios pendientes se validan también al exportar.
4. Elegir DSC v2 y exportar. Volver a generar la vista si se cambiaron cortes/resolución.
5. En Taller DSC importar el ZIP, revisar y guardar el modelo.

Los campos se conservan al cambiar cortes, resolución o cargar otro modelo en la sesión: revisar su ubicación antes de reutilizarlos. La preview de campos usa la misma base blanca del ZIP y encuadre completo; la tipografía Qt es una comprobación orientativa, no una equivalencia de glifos píxel a píxel con Canvas/Arial del navegador. La hitbox sí es idéntica. No se genera ni modifica geometría CAD.

DSC importa mediante `POST /api/admin/uploads/preview-package`, autenticado y con CSRF. Convierte filenames a rutas opacas `/media/previews/…png`, utiliza compositing solid y combina campos por ID/tipo al editar el modelo. Para IDs existentes conserva los valores y opciones del editor según sus reglas; importa `enabled/hitbox`. Un conflicto de tipo debe resolverse. Guardar el modelo persiste los cambios.

## Validación y límites

Antes de publicar el ZIP final Toolbox valida archivos, PNG, orientación, relaciones de campos, alfa, RGB blanco/transparente, exclusividad y unión. Límites DSC: ZIP ≤5 MiB, ≤16 entradas, total descomprimido ≤32 MiB, JSON ≤128 KiB, cada PNG ≤5 MiB. El archivo se escribe temporalmente y se sustituye solo tras validarlo y comprobar cancelación. Un error conserva el ZIP anterior.

## API sin Qt

```python
from jarvis_bambu.core.stl_color_map import analyze_model
from jarvis_bambu.core.dsc_live_fields import import_template
from jarvis_bambu.core.dsc_export import export_dsc

model = analyze_model('collar.3mf')
field = import_template('dsc-live-field-pet_name.json')
export_dsc('collar-dsc.zip', model, [1.2, 2.4], live_fields=[field], size=512)
export_dsc('legacy.zip', model, [1.2, 2.4], version=1)
```

El ejemplo entregado `examples/relieve-dsc-v2.zip` procede de un relieve sintético de tres niveles, con Nombre=LUNA y Número=12. Se importa con el código real de DSC. No representa el collar del usuario ni incorpora OpenSCAD.
