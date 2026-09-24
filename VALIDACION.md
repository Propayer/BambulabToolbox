# Validación y uso de la entrega

## Resultados

- BambuLab Toolbox: **55 tests aprobados** en la selección de core, mapa de alturas, GUI, precios, Excel y fundamentos de aplicación.
- DSC Minerva Artis: **17 tests aprobados**, incluidos autenticación/CSRF, importación de paquetes, persistencia de modelos y fixture generado por el exportador real de Toolbox.
- JavaScript: suite DOM existente y nueva prueba de importación aprobadas con `npm test`.
- Python: `compileall` correcto. Importación de `core.stl_color_map` y `core.dsc_export` confirmada sin cargar PySide6.
- PyInstaller: empaquetado Linux con el `.spec` existente, sin añadir dependencias de producción. Smoke del ejecutable: páginas de GUI, cálculo de precios, Excel, multiprocessing y paquete DSC.
- GUI: comprobación visual offscreen con tema Nebu, vista cenital y máscaras de un relieve sintético. Pruebas de worker, edición, caché, cancelación y creación/destrucción del visor 3D.

No se ha compilado ni ejecutado un `.exe` de Windows en este entorno Linux. El smoke informa `qt_windows_plugin: false` y no verifica foco/control de una instalación real de Bambu Studio. Para certificar esa parte, ejecutar `build_exe.cmd` en Windows con los requisitos del proyecto y su smoke original.

No se ha ejecutado toda la batería costosa de nesting, porque el motor no se modificó y se solicitó reservar los recursos para el mapa. Tampoco se ha realizado QA visual en un navegador real/móvil de DSC: se ha probado el backend y el DOM; la composición CSS se mantiene salvo el modo solid explícito para los nuevos paquetes.

Los modelos geométricos de prueba son sintéticos, con resultado analítico conocido. No venía adjunto el STL/3MF exacto que originó la captura ni `collar.3mf`; por tanto, no se afirma haber comprobado ese archivo específico. Los cinco adjuntos recibidos fueron ambos proyectos ZIP, captura, manual y kit de marca.

## Tests geométricos y formatos

Se cubren STL ASCII/binario, varios niveles Z, orientación +Z, proporciones XY, superficies que intercambian orden en profundidad, caras verticales, independencia del winding/orden, límites de intervalos, máscaras exclusivas/alineadas y unión igual a la base; caché de cortes/resolución, cancelación y exportación atómica; JSON; ausencia de geometría, NaN y degenerados; 3MF sin color, unidades, materiales base, objetos/partes con filamentos y pintura completa de cara. La pintura subdividida se prueba como caso de advertencia, no como decodificación exacta.

La suite de DSC verifica que los paquetes inválidos no escriban imágenes, incluidos solapamientos, resolución incorrecta, rutas y duplicados. Se prueba la importación del fixture `tests/fixtures/toolbox-steps.zip`, producido por este exportador.

## Reproducir las pruebas

Bambu, desde `BambuAnalyzer`, después de instalar requisitos de desarrollo:

```bash
PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen python -m pytest tests/test_color_map_gui.py tests/test_height_raster.py tests/test_stl_color_map.py tests/test_price_analysis.py tests/test_pricing_gui.py tests/test_gui_ux.py tests/test_app_foundation.py tests/test_core.py -q
PYTHONPATH=src python benchmarks/benchmark_height_map.py
```

En Windows PowerShell, definir `$env:PYTHONPATH='src;.;tests'` y `$env:QT_QPA_PLATFORM='offscreen'` antes de ejecutar el mismo comando `python -m pytest ...` sin los prefijos de entorno de Bash.

DSC, desde la raíz de su proyecto:

```bash
python -m pip install -r requirements.txt -r tests/requirements.txt
PYTHONPATH=. python -m pytest tests -q
cd tests
npm install
npm test
```

Se corrigió una fixture preexistente de test DSC: usaba una cabecera PNG seguida del texto `store-logo`, que no es una imagen válida. Se confirmó el fallo contra el ZIP original antes de reemplazarla por un PNG real de 8×8. No se relajó la validación del logo. Quedan avisos de deprecación del código previo de paleta con la versión de Pillow del entorno y el aviso intencionado de ZIP duplicado en la prueba adversa.

## Flujo de uso

1. Abrir la aplicación con `run_gui.cmd` o el procedimiento habitual.
2. Entrar en Mapa de color STL / 3MF y cargar el modelo.
3. Revisar colores detectados y avisos. Elegir propuesta o introducir cortes manuales.
4. Pulsar Generar vista previa de alturas. El dibujo es cenital +Z y las máscaras se muestran en su encuadre común.
5. Pulsar una superficie para obtener Z, escribir altura exacta o hacer doble clic en una zona para editar su corte superior. El botón Nombre / ID permite vincular campos personalizados de DSC.
6. Elegir 256/512/1024 px y Exportar paquete DSC.
7. Ejecutar la web DSC incluida; en Taller/gestión, editar el modelo, importar el ZIP y revisar campos. Guardar el modelo.
8. En el configurador, elegir colores: cada selector modifica exclusivamente su máscara.

Los IDs/nombres de zonas se restablecen al añadir/eliminar cortes o aplicar una propuesta; terminar primero los cortes y nombrar después. Al editar un corte exacto sin cambiar el número de zonas se mantienen.

El visor 3D es opcional. Solo se crea tras confirmar. Botón izquierdo rota, rueda hace zoom, derecho desplaza; un clic obtiene Z. Parar libera el widget y su geometría. En modelos grandes se advierte que muestra una muestra de hasta 6.000 caras; para validar recoloreado se deben usar las máscaras completas.

## Entrega y compatibilidad

- Proyecto Bambu completo con documentos `OPTIMIZACIONES.md`, `PROPUESTAS_ORGANIZADOR.md`, `DSC_EXPORT_FORMAT.md` y este informe.
- Proyecto DSC completo con importador, tests, contrato y guía de actualización.
- ZIP adicional de archivos modificados/añadidos, con índice de SHA-256 para revisión.

No se modifican los datos/configuración de la instalación del usuario. No se publica el sitio, no se envían pedidos y no se incluyen dependencias descargadas, cachés, entornos virtuales ni ejecutables de Linux en los ZIP fuente. El logo original y el motor del organizador se mantienen sin cambios.

## Revisión de interfaz Nebu posterior

Ver `INTERFAZ_NEBU.md` y las capturas `validation/nebu/`. La nueva ejecución completa obtiene 125 tests aprobados, 3 subtests aprobados y un fallo preexistente de simulación Windows/Linux, reproducido sin estos cambios. Esta ejecución sustituye el alcance parcial de 55 tests citado en la primera entrega; no modifica los resultados anteriores de DSC.

Build de esta revisión: PyInstaller Linux completado y smoke del ejecutable aprobado (GUI, precios/Excel, multiprocessing y exportación DSC). Informe en `validation/nebu/build-smoke.json`. Tras el ajuste final del indicador Manual, los 8 tests de workspace y ciclo del mapa vuelven a aprobar.

## Entrega DSC v2 · 15-09-2026

95 tests Toolbox aprobados (selección de core, GUI, precios y nuevos contratos); 19 tests originales DSC de paquetes/campos vivos aprobados. Único aviso DSC: entrada ZIP duplicada intencional en prueba adversa. Se verifican v1/v2 a 256/512/1024 con el importador real, y una exportación v2 a través del endpoint HTTP autenticado con CSRF. Se probaron arrastre, redimensionado, coordenadas manuales, null, estado desactivado, conflictos de IDs y conservación de píxeles/caché.

Build PyInstaller Linux aprobada, incluido smoke del ejecutable con exportación v2, GUI, precios/Excel y multiprocessing. No se certifica ejecutable Windows desde Linux. No se repitió la batería extensa del organizador; su código no cambia. Capturas reales offscreen en 1360×860 y 1000×720, fixture sintética.

Reproducción desde BambuAnalyzer:

```bash
DSC_PROJECT=/ruta/al/dsc-minerva-artis PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen python -m pytest tests/test_dsc_v2.py tests/test_live_editor.py tests/test_height_raster.py tests/test_stl_color_map.py tests/test_nebu_workspace.py tests/test_color_map_gui.py tests/test_price_analysis.py tests/test_pricing_gui.py tests/test_gui_ux.py tests/test_app_foundation.py tests/test_core.py -q
```

DSC_PROJECT debe apuntar al proyecto real y requiere sus dependencias. Sin esa variable, los tests de contrato locales siguen funcionando y el test HTTP se omite. Los resultados entregados sí usaron DSC_PROJECT; ver hashes y registros en `validation/dsc-v2/`.

Comprobación adicional de persistencia: el test HTTP importa el ZIP, combina metadatos con los campos existentes como hace el editor DSC, guarda el modelo y verifica default/hitbox en el catálogo público. Aprobado; registro en test-persistencia.txt.
