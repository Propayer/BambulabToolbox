# Contrato de exportación DSC

## Contrato encontrado en la web recibida

Se estudiaron `app/static/js/preview-editor.js`, `configurator.js`, `field-editor.js`, `admin.js`, `app/validation.py`, `app/catalog.py` y las reglas `.model-preview` de `app/static/style.css`.

La web almacena en cada modelo:

```json
{
  "preview": {
    "base_image": "/media/previews/0123456789abcdef0123456789abcdef.png",
    "layers": [
      {
        "field_id": "color_1",
        "mask_image": "/media/previews/abcdef0123456789abcdef0123456789.png"
      }
    ]
  }
}
```

- `field_id` apunta a un campo del modelo de tipo `color`, no directamente a un filamento ni a un color del catálogo.
- El valor elegido para ese campo identifica una entrada de `data.colors`; su `hex` determina el color mostrado.
- Una capa usa `mask-image` CSS, centrada y sin repetición, con `mask-size: contain`.
- La base usa `object-fit: contain`, dentro de un canvas cuadrado.
- Se admiten hasta 12 capas y un solo vínculo por campo.
- Las rutas persistidas se restringen a `/media/previews/<32 hex>.<ext>`; no pueden ser nombres locales del ZIP.
- El upload individual admite 5 MiB por archivo; PNG/WebP para máscaras y PNG/WebP/JPG para bases.
- La web anterior no fijaba una resolución de píxeles y no importaba `model-map.json` ni ZIP.
- Las capas anteriores usan opacidad 0,92 y `mix-blend-mode: multiply`.

## Extensión compatible implementada

Nuevo endpoint autenticado: `POST /api/admin/uploads/preview-package`.

Formulario multipart con `file=<ZIP>`, usando la autenticación de administración y los headers CSRF existentes. Máximo 5 MiB comprimidos. El botón aparece al editar un modelo en Taller/gestión DSC.

El importador valida el paquete antes de escribir imágenes, asigna los nombres opacos existentes y devuelve:

```json
{
  "preview": {
    "base_image": "/media/previews/<32 hex>.png",
    "compositing": "solid",
    "layers": [
      {"field_id": "color_1", "mask_image": "/media/previews/<32 hex>.png"}
    ]
  },
  "fields": [
    {
      "id": "color_1", "label": "Color 1", "type": "color",
      "required": false, "order": 0, "placeholder": "", "options": [], "default": ""
    }
  ],
  "warnings": []
}
```

`compositing: solid` activa opacidad 1 y mezcla normal exclusivamente en estos modelos. Los modelos anteriores mantienen su aspecto y su forma de edición. No hay migración de datos ni conexión de pedidos. No se ha desplegado la web.

El editor conserva campos existentes del mismo ID y tipo color, incluidas opciones, obligatoriedad y valor por defecto. Añade los ausentes, con todos los colores activos disponibles. Un ID que ya exista con otro tipo provoca un error comprensible. Después de importar hay que revisar y guardar el modelo, igual que cualquier otra edición en Taller. Los archivos se suben al importar; el catálogo solo cambia al guardar.

## Contenido del ZIP de Toolbox

Todos los archivos están en la raíz:

| Archivo | Función |
|---|---|
| `model-map.json` | Contrato, orientación, zonas, origen y avisos |
| `preview.png` | Huella visible blanca, RGBA, fondo transparente |
| `height-map-preview.png` | Imagen de diagnóstico con colores contrastados |
| `color_1.png` … `color_N.png` | Máscara blanca RGBA exclusiva de cada intervalo |

El filename de máscara sigue el índice 1…N. El `field_id` puede personalizarse y se declara en JSON; no tiene por qué coincidir con el filename. Los IDs deben ser únicos, empezar por letra minúscula y contener hasta 64 caracteres de letras minúsculas, dígitos, `_` o `-`. No se admiten IDs reservados de JavaScript. Los nombres visibles tienen hasta 100 caracteres.

Resoluciones de paquete: 256×256 (rápida), 512×512 (normal, predeterminada) y 1024×1024 (alta). **Todas** las imágenes del paquete tienen exactamente la misma resolución. La GUI puede mostrarlas más pequeñas, sin modificar el raster exportado.

## JSON de ejemplo

```json
{
  "schema": "dsc.stl-height-map.v2",
  "package_schema": "dsc.preview-package.v1",
  "source": "collar.3mf",
  "source_type": "3mf",
  "triangle_count": 12000,
  "bounds": {"min": [0, 0, 0], "max": [40, 20, 3]},
  "height": 3,
  "zones": [
    {"id": "color_1", "label": "Base", "z_from": 0, "z_to": 1.2},
    {"id": "color_2", "label": "Relieve", "z_from": 1.2, "z_to": 3}
  ],
  "detected_colors": [],
  "warnings": [],
  "view": {
    "projection": "orthographic", "camera": "+Z",
    "image_right": "+X", "image_up": "+Y",
    "width": 512, "height": 512,
    "center_xy_mm": [20, 10], "pixels_per_mm": 11.264,
    "sampling": "pixel-center",
    "intervals": "[from,to); last includes maximum",
    "alpha": "binary"
  },
  "preview": {
    "base_image": "preview.png",
    "layers": [
      {"field_id": "color_1", "mask_image": "color_1.png"},
      {"field_id": "color_2", "mask_image": "color_2.png"}
    ]
  }
}
```

El ejemplo es ilustrativo. El exportador calcula límites y escala a partir del archivo real. `detected_colors`, cuando existe, incluye slot, color HEX, número de triángulos, Z mínimo/máximo y mediana. Son datos de guía; no asignan colores comerciales automáticamente.

## Geometría, orientación y transparencia

Cámara situada en +Z mirando perpendicularmente a XY. Sin perspectiva. X aumenta hacia la derecha de la imagen; Y del modelo aumenta hacia arriba. Se respetan las transformaciones del build del 3MF y las unidades se convierten a milímetros. No se orienta ni se gira automáticamente el objeto para cambiar su cara superior: +Z es el +Z del modelo ensamblado.

El lado mayor de su caja XY ocupa el 88 % del canvas; el encuadre se centra en el centro de esa caja. Escala común en X/Y:

```text
scale = size × 0.88 / max(ancho_X, alto_Y)
x_pixel = (X - centro_X) × scale + size/2
y_pixel = -(Y - centro_Y) × scale + size/2
```

Para el píxel entero `(columna, fila)` se evalúa el centro `(columna+0.5, fila+0.5)`. En ese XY se interpola la altura de cada triángulo que lo cubre y se conserva la máxima. Las caras verticales de área XY nula no invaden la máscara.

Cada píxel cubierto se asigna a un solo intervalo `[z_from,z_to)`; un Z exactamente igual a un corte pertenece al intervalo superior. El último incluye el máximo Z. El fondo no pertenece a ninguna zona. Una zona totalmente tapada produce una máscara transparente: es una salida correcta y conserva el vínculo de campo.

- RGB blanco dentro de cada máscara, alfa 255.
- Fuera de la zona, RGBA `(0,0,0,0)`.
- Sin antialiasing ni mezcla de IDs en la exportación.
- Las máscaras no se recortan individualmente ni se reencuadran.
- La suma de sus alfas debe coincidir exactamente con el alfa de la base.
- En el importador se comprueban dimensiones, alfa binario, ausencia de solapamiento y coincidencia de la unión con la base.

La exactitud es a la resolución de muestreo elegida; un detalle menor que un píxel puede no aparecer. La interpolación visual del navegador al escalar una imagen no modifica la pertenencia binaria del archivo exportado.

## Límites y fallos

Se rechazan ZIP con rutas, entradas duplicadas, más de 16 archivos o más de 32 MiB descomprimidos; JSON de más de 128 KiB; máscaras con tamaño/formato/alfa inválidos; IDs repetidos; solapamientos y huellas inconsistentes. No se extrae el ZIP al sistema de archivos. No se aceptan URLs suministradas por el paquete.

La guía por materiales no representa pintura lateral o subdividida de forma exacta. Los avisos se muestran en Toolbox y se transportan en `warnings`. Los colores comerciales siguen siendo una decisión de Taller y del cliente.

## Uso sin GUI

Desde la raíz de BambuAnalyzer, con `src` en `PYTHONPATH`:

```python
from jarvis_bambu.core.stl_color_map import analyze_model
from jarvis_bambu.core.dsc_export import export_dsc

model = analyze_model('collar.3mf')
export_dsc('collar-dsc-preview.zip', model, [1.2, 2.4], size=512)
```

No inicia Qt. Para usar IDs/nombres personalizados puede pasarse `zones=` con `HeightZone` y los mismos límites de los cortes.
