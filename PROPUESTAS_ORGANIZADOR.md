# Propuestas futuras para el organizador

No implementadas en esta entrega. Se ha conservado byte a byte `nesting_optimizer.py`, `optimizer_models.py` y el resto del motor. El roadmap parte de las estructuras reales, no de asumir que faltan funcionalidades que ya existen.

## Estado observado

El organizador ya tiene evolución de genomas, seeds, workers por procesos, cachés de rotación/buffer/raster/score, índices espaciales, regiones libres, filtros dimensionales, fallback vectorial/raster, selección previa de candidatos para score exacto y validación de asignaciones. `_solution_score` ya recompensa la región libre dominante y penaliza fragmentación/huecos pequeños; no conviene añadir otro objetivo equivalente sin medir los pesos actuales.

## Prioridad alta

| Problema observado | Posible mejora | Beneficio | Dificultad | Riesgo |
|---|---|---|---|---|
| El score combina envolvente, convex hull, huecos y fragmentación con unidades/escalas distintas (`_solution_score`). | Evaluar pesos normalizados por placa y una batería de trabajos reales con preferencia humana. | Alinear compactación con espacio libre realmente aprovechable. | Media | Cambiar el ranking puede empeorar trabajos que hoy funcionan; mantener baseline y seeds. |
| El espacio accesible usa un radio fijo derivado del clearance, mínimo 3 mm. | Comparar varios radios ligados a tamaños de las piezas pendientes, sin recalcularlos para todos los candidatos. | Distinguir huecos útiles de cavidades o corredores demasiado estrechos. | Media/alta | Coste elevado de buffers y diferencias geométricas; usar evaluación final selectiva. |
| `_select_full_score_candidates` puede descartar soluciones por la aproximación raster. | Medir tasa de falsos descartes y calibrar umbral/top-k con muestreo de auditoría. | Mantener la ganancia de rendimiento sin perder mejores soluciones. | Media | Más evaluaciones exactas aumentan tiempo. |
| La validación final y el límite de placas son garantías importantes ya presentes. | Crear corpus real anonimizado y pruebas deterministas de no-regresión antes de tocar heurísticas. | Evitar colisiones, pérdidas de piezas o mejoras solo aparentes. | Media | Corpus poco representativo o coste excesivo de CI. |

## Prioridad media

| Problema observado | Posible mejora | Beneficio | Dificultad | Riesgo |
|---|---|---|---|---|
| El score evalúa una colocación completa, mientras una buena solución puede mejorar con pequeños movimientos locales. | Compactación final acotada por placa: desplazamientos cortos y pocas rotaciones con validación exacta. | Reducir envolvente y agrupar espacio libre sin rehacer la búsqueda. | Alta | Interacciones entre piezas y tiempos crecientes; nunca aceptar colisiones. |
| Se mantienen cachés de geometría y raster con memoria creciente según orientación/piezas. | Instrumentar máximos y evaluar presupuestos de memoria/LRU solo tras medir reutilización. | Evitar picos de RAM en trabajos grandes. | Media | Expulsar entradas útiles puede aumentar CPU. |
| Workers reciben payload geométrico y retornan colocaciones compactas; la paralelización ya existe. | Ajustar lotes y número de workers según RAM medida y tamaño del trabajo. | Evitar oversubscription y serialización desproporcionada en Windows. | Media | Variaciones de orden pueden afectar reproducibilidad si no se conserva la política de seeds. |
| Las orientaciones se filtran por dimensiones y regiones disponibles. | Afinar búsqueda angular en torno a orientaciones prometedoras de piezas alargadas, con presupuesto fijo. | Encontrar encajes adicionales sin explorar todos los ángulos. | Media | Más rotaciones y cachés; puede perjudicar prioridades estéticas o de impresión. |

## Prioridad baja

| Problema observado | Posible mejora | Beneficio | Dificultad | Riesgo |
|---|---|---|---|---|
| La agrupación actual prioriza geometría/espacio, no necesariamente lotes comerciales. | Añadir preferencias opcionales de agrupación por pedido/color/material sin violar restricciones. | Preparación y retirada de piezas más cómodas. | Media/alta | Puede consumir más placas; requiere un modo explícito y objetivo claro. |
| Existen métricas detalladas en `NestingPerformanceMetrics`, difíciles de interpretar para el usuario. | Resumen comparativo del resultado: placas, región libre, tiempo, memoria y motivo de la mejora. | Diagnóstico y ajuste con evidencia. | Baja/media | Mostrar métricas aproximadas como si fueran exactas. |

## Secuencia recomendada

1. Corpus y medición de score/tiempos/RAM.
2. Calibrar pesos y comprobar falsos descartes del filtro aproximado.
3. Probar compactación local con presupuesto y comparación determinista.
4. Ajustar memoria y paralelización únicamente donde el perfil lo justifique.

No se han realizado benchmarks costosos de nesting para esta entrega. La verificación del motor se limita a las regresiones existentes seleccionadas y al smoke de empaquetado.
