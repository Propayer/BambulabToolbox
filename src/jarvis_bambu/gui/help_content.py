from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HelpDefinition:
    id: str
    title: str
    short_description: str
    detailed_description: str
    recommendations: str
    keywords: tuple[str, ...] = ()
    example: str = ""


HELP = {item.id: item for item in (
    HelpDefinition("optimizer.mode", "Modo de optimización", "Define cuánto puede redistribuir el optimizador.", "Simple conserva cada plate. Avanzado puede redistribuir piezas entre plates para buscar una solución mejor.", "Usa Simple para cambios conservadores y Avanzado cuando quieras minimizar plates.", ("simple", "avanzado", "plates")),
    HelpDefinition("optimizer.effort", "Esfuerzo", "Controla el presupuesto de búsqueda.", "Rápido y Medio tienen un deadline. Alto no tiene un límite temporal fijo y termina por los criterios del optimizador.", "Medio ofrece normalmente el mejor equilibrio.", ("tiempo", "deadline", "calidad")),
    HelpDefinition("optimizer.preview", "Preview", "Muestra visualmente la distribución durante la búsqueda.", "La preview es informativa y no representa un porcentaje lineal de progreso.", "Desactívala si no necesitas seguimiento visual.", ("vista", "progreso")),
    HelpDefinition("optimizer.preview_mode", "Modo de preview", "Elige la frecuencia de información visual.", "Normal muestra mejoras; Debug puede mostrar más intentos y datos de diagnóstico.", "Usa Debug solo para diagnosticar.", ("normal", "debug")),
    HelpDefinition("optimizer.workers", "Workers", "Procesos que buscan distribuciones simultáneamente.", "Auto elige una cantidad adecuada. Los valores manuales limitan los procesos paralelos.", "Auto es la opción recomendada.", ("procesos", "cpu", "auto")),
    HelpDefinition("application.open", "Abrir proyecto", "Trabaja con el proyecto abierto en Bambu Studio.", "La aplicación guarda una copia y entrega su ruta al mismo core usado por CLI y MQTT.", "Guarda tus cambios antes de optimizar.", ("bambu", "proyecto")),
    HelpDefinition("application.results", "Resultados", "Resume plates, tiempo y mejora.", "El resultado permite abrir el 3MF generado en Bambu Studio cuando existe una mejora.", "Revisa las plates antes de laminar.", ("plates", "resultado")),
    HelpDefinition("application.settings", "Ajustes", "Identidad y preferencias locales.", "Los valores se guardan en AppData y sobreviven a actualizaciones.", "Mantén correcta la ruta de Bambu Studio.", ("device", "appdata")),
    HelpDefinition("pricing.import", "Importar archivos", "Añade uno o varios STL o 3MF.", "Puedes usar el selector o arrastrar archivos. Los duplicados y formatos incompatibles se omiten sin borrar archivos.", "Añade todos los trabajos que quieras comparar.", ("stl", "3mf", "arrastrar")),
    HelpDefinition("pricing.global_multiplier", "Multiplicador global", "Aplica un factor comercial a todo el análisis.", "Se aplica una sola vez después del coste base y se combina con cantidad y multiplicador individual.", "Usa 1,00 para conservar el precio base.", ("precio", "margen")),
    HelpDefinition("pricing.item_multiplier", "Multiplicador por archivo", "Ajusta el precio de un elemento concreto.", "No repite el laminado: recalcula inmediatamente sobre las métricas ya obtenidas.", "Úsalo para piezas con dificultad especial.", ("pieza", "precio")),
    HelpDefinition("pricing.quantity", "Cantidad", "Indica las unidades comerciales del archivo.", "Peso, tiempo, coste y subtotal se multiplican por esta cantidad.", "La cantidad mínima es una unidad.", ("unidades", "copias")),
    HelpDefinition("pricing.excel_columns", "Columnas del Excel", "Elige los campos visibles del informe.", "Pieza es obligatoria; el resto puede ocultarse y ordenarse como preferencia para futuras exportaciones.", "Restaura los valores predeterminados si dudas.", ("excel", "columnas")),
    HelpDefinition("pricing.export", "Exportar Excel", "Genera un libro basado en la plantilla existente.", "Conserva estilos y fórmulas e incorpora cantidad, multiplicadores y precio final.", "Revisa los resultados antes de exportar.", ("xlsx", "informe")),
)}


def search_help(text):
    query = text.strip().casefold()
    if not query:
        return list(HELP.values())
    return [item for item in HELP.values() if query in " ".join((item.title,
        item.short_description, item.detailed_description, *item.keywords)).casefold()]
