# Instalacion automatica en Windows

En una copia del repositorio, ejecuta simplemente:

```bat
setup_dev.cmd
```

El setup es el punto de entrada autonomo de desarrollo/instalacion. Detecta un Python compatible (3.10-3.14); si no existe, instala Python 3.13. Instala las dependencias, crea el entorno virtual, instala las dependencias de build, compila el EXE con PyInstaller, instala la build en `%LOCALAPPDATA%\Programs\BambuLabToolbox` y crea el acceso directo **BambuLab Toolbox** en el Escritorio.

Bambu Studio se conserva si ya existia. Si falta, el setup intenta instalarlo mediante WinGet y, si WinGet no esta disponible o falla, descarga el instalador Windows de la ultima release oficial de `bambulab/BambuStudio`.

El instalador guarda un manifiesto de lo que existia antes. Para revertir los cambios gestionados por el setup:

```bat
uninstall.cmd
```

La desinstalacion elimina/restaura unicamente lo que el setup gestiono: no desinstala un Python ni un Bambu Studio que ya estuvieran presentes antes de ejecutarlo. Tambien restaura `.venv`, `build`, `dist`, instalacion previa y acceso directo si existian antes del primer setup gestionado.

> Nota: "volver atras" se refiere al estado que el instalador registra al comenzar. Cambios que el usuario haga manualmente a esos mismos componentes despues de la instalacion no pueden reconstruirse de forma perfecta.

# Analizador Bambu de Jarvis

## Desarrollo en Windows

Primera instalaciÃ³n:

```bat
git clone URL_DEL_REPOSITORIO
cd BambuAnalyzer
setup_dev.cmd
```

Ejecutar GUI: `run_gui.cmd`

Ejecutar tests: `.venv\Scripts\python.exe -m unittest discover -s tests`

Actualizar repositorio: `git pull`

La URL se completarÃ¡ cuando se configure el remoto de GitHub.

Automatiza el análisis de la última pieza STL descargada o de todas las piezas descargadas hoy. Usa la línea de comandos de Bambu Studio, organiza y lamina cada pieza, extrae su vista previa y añade los resultados al mismo Excel sin depender de clics ni de cambios en pantalla.

## Qué incluye

- Búsqueda automática de la última pieza o de todas las piezas del día.
- Control visual de Bambu Studio con detección de ventanas conocidas.
- Gestión del aviso **Sincronizar ahora / Más tarde**.
- Continuación con la siguiente pieza ante un error recuperable.
- Excel acumulativo con imagen, tiempo, peso y fórmulas de coste.
- Evita duplicados mediante un identificador interno del archivo.
- Sensores MQTT opcionales para que Home Assistant anuncie el resultado.
- Optimización por el contorno real de las piezas, sin usar hitboxes rectangulares.
- Modo simple y avanzado con diálogo guiado desde Assist.
- **Mapa de color STL / 3MF:** analiza geometría por altura con preview 2D ligera, aprovecha colores existentes de proyectos 3MF, genera previews cenitales bajo demanda y mantiene el render 3D apagado hasta que el usuario lo activa explícitamente.

## Instalación inicial

1. Descomprime la carpeta en `C:\Jarvis\BambuAnalyzer`.
2. Haz clic derecho en `instalar.ps1` y selecciona **Ejecutar con PowerShell**.
3. Abre `config.yaml` y revisa la ruta de Bambu Studio.
4. Para probar el buscador sin abrir Bambu Studio, ejecuta desde PowerShell:

   ```powershell
   $env:PYTHONPATH = "$PWD\src"
   .\.venv\Scripts\python.exe -m jarvis_bambu.main --mode today --dry-run
   ```

5. Cierra cualquier Excel diario que esté abierto antes de ejecutar el análisis.

## Comandos para HASS.Agent

Crea dos comandos `Custom` de tipo `Button`:

- **Analizar última pieza** → `C:\Jarvis\BambuAnalyzer\analizar_ultima.cmd`
- **Analizar piezas de hoy** → `C:\Jarvis\BambuAnalyzer\analizar_hoy.cmd`
- **Actualizar registro global** → `C:\Jarvis\BambuAnalyzer\crear_registro_global.cmd`

Pulsa **Store and Activate Commands** después de crearlos.

## Optimizar la colocación

El optimizador trabaja directamente sobre el proyecto 3MF abierto y conserva el
original. Antes de empezar, Bambu Studio guarda una copia en:

```text
Documentos\Jarvis\Proyectos Bambu
```

- **Simple:** no toca las placas bloqueadas, reúne las piezas de todas las
  placas desbloqueadas y deja al menos 1,5 mm entre modelos.
- **Avanzado:** puede redistribuir objetos, vaciar y eliminar placas, y deja al
  menos 1 mm entre modelos. Su primera prioridad es reducir el número de placas.
- **Esfuerzo bajo:** hasta 1 minuto y giros evolutivos de 5°.
- **Esfuerzo medio:** hasta 3 minutos y giros evolutivos de 2°.
- **Esfuerzo alto:** giros de 1° y termina al agotar las mejoras disponibles.
- **Tiempo personalizado:** utiliza un número de minutos como esfuerzo, por
  ejemplo `advanced 3 ask`.

Todos los niveles avanzados usan ahora una búsqueda generacional: seleccionan
las mejores distribuciones, cruzan su orden y rotaciones y aplican mutaciones
para crear la siguiente generación. La opción `preview` admite destino `pc` o
`echo_show` y dos comportamientos: `improvements` solo muestra soluciones
mejores; `debug` muestra todas las evaluaciones y ralentiza deliberadamente el
proceso para hacerlas visibles:

```text
optimizar_actual.cmd advanced high ask preview
optimizar_actual.cmd advanced 3 same preview pc improvements
optimizar_actual.cmd advanced medium ask preview echo_show debug
```

La imagen y el estado actuales también quedan en `Proyectos Bambu` como
`preview_optimizacion.png` y `preview_optimizacion.json`. Cuando MQTT está
activo, la imagen se publica como `camera.jarvis_preview_optimizador`.

También respeta el área imprimible, las exclusiones guardadas en el perfil, el
brim respecto al borde y las asignaciones de filamento. Nunca voltea una pieza.

Para instalar el diálogo de voz:

1. Crea los botones indicados en `home_assistant\COMANDOS_HASS_AGENT.txt`.
2. Copia `home_assistant\custom_sentences_es_jarvis_bambu.yaml` a
   `/config/custom_sentences/es/jarvis_bambu.yaml` en Home Assistant.
3. Añade `home_assistant\jarvis_bambu_optimizer.yaml` como paquete o copia sus
   secciones a la configuración correspondiente.
4. Sustituye las entidades marcadas con `REEMPLAZAR`.
5. Reinicia Home Assistant.

El diálogo admite «Optimiza esta cama», pregunta modo y esfuerzo, repasa las
opciones y puede preguntar al terminar si debe abrir el resultado aparte o en
la ventana actual. Home Assistant permite esta secuencia mediante la acción
`assist_satellite.ask_question`.

El registro global `Registro_global_piezas.xlsx` se reconstruye automáticamente
después de cada análisis y también puede actualizarse manualmente con
`crear_registro_global.cmd`. Incluye todas las filas e imágenes de los Excel diarios.

## Excel

El archivo diario se guarda por defecto en:

```text
Documentos\Jarvis\Analisis de piezas\Analisis_piezas_AAAA-MM-DD.xlsx
```

Las fórmulas utilizan los valores editables de la hoja `Configuracion`:

- Filamento: `0,0115 €/g`
- Desgaste P2S: `0,20 €/h`
- Multiplicador de filamento: `3`
- Venta aproximada: `(coste de filamento × 3) + desgaste`

## Funcionamiento seguro

- Windows debe permanecer encendido y desbloqueado.
- El programa nunca pulsa automáticamente botones de ventanas desconocidas.
- Si no reconoce una ventana, guarda una captura, registra el error y continúa con la siguiente pieza.
- El libro Excel debe estar cerrado durante la ejecución.

## Motor por comandos

El modo predeterminado `cli` espera a que Bambu Studio termine realmente. El tiempo se lee del 3MF y el peso se calcula con los metros utilizados, diámetro de 1,75 mm y densidad PLA de 1,26 g/cm³. La vista previa se extrae del propio 3MF.
# Caja de herramientas BambuLab

La GUI modular puede ejecutarse en desarrollo con:

```powershell
$env:PYTHONPATH="src"
python -m jarvis_bambu.gui
```

La CLI y los comandos MQTT existentes continúan disponibles. La arquitectura de
migración está documentada en `docs/APPLICATION_ARCHITECTURE.md`.

## Actualización: mapa cenital y exportación DSC

La herramienta mantiene su registro actual y ahora genera máscaras +Z con Z-buffer,
resolución 256/512/1024, caché de profundidad y exportación independiente de Qt.
El ZIP se importa directamente desde el editor de modelos de la web DSC incluida.
Consulte `VALIDACION.md`, `DSC_EXPORT_FORMAT.md`, `OPTIMIZACIONES.md` y
`PROPUESTAS_ORGANIZADOR.md`. El motor del organizador no se ha modificado.
