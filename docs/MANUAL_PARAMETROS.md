# Manual de parámetros: criterios para llenar cada dato de entrada

Complemento QGIS «Cota de Anegamiento» v1.2. Este manual complementa la
[guía paso a paso](Guia_Cota_Anegamiento.pdf) y explica, parámetro por parámetro, qué valor
poner, de dónde sacarlo y qué pasa si se deja el valor por defecto.

Solo el **DEM** es obligatorio. Los demás datos tienen valores por defecto pensados para
llanuras costeras del norte del Perú (Bajo Piura); en otra zona conviene revisar al menos la
lluvia de diseño y el número de curva.

## 1. Datos de entrada principales

### DEM (modelo digital de elevación)
- **Qué es:** ráster de cotas del terreno (msnm).
- **Criterios:**
  - Mejor fuente disponible, en este orden: topografía propia o LiDAR (ANA), FABDEM, Copernicus
    GLO-30. Evitar SRTM y ALOS 12.5 m en zonas planas: su ruido crea miles de depresiones falsas.
  - Debe cubrir la zona de estudio con **2 a 3 km de margen**, porque los bordes del DEM se
    tratan como salidas de agua. Un DEM justo hace que el agua «se escape» por el borde.
  - Puede estar en grados o en metros: en grados se reproyecta solo a la zona UTM que
    corresponde al centro del DEM. Si es muy grande (más de 6 millones de celdas) se remuestrea
    automáticamente.
- **Error típico:** DEM con huecos grandes en el interior (nubes, agua). Los huecos pequeños se
  rellenan solos (parámetro «Rellenar huecos»); los grandes rellénalos antes con
  Ráster › Análisis › Rellenar sin datos.

### Zona a analizar (opcional)
- **Qué es:** extensión rectangular para recortar el DEM sin tener que hacerlo aparte.
- **Criterio:** dibújala en el mapa dejando el margen de 2 a 3 km alrededor del eje. Vacío = todo
  el DEM.

### Eje de la vía (opcional, recomendado)
- **Qué es:** capa de líneas con el trazo de la vía. Puede venir de Civil 3D (DXF, KML, SHP);
  el complemento la reproyecta al sistema del DEM.
- **Criterios:**
  - Una sola línea continua por vía; la progresiva 0+000 es el primer vértice, así que dibuja o
    invierte la línea en el sentido del kilometraje del proyecto.
  - Prolonga el eje hasta terreno alto en ambos extremos: si termina dentro de una zona baja, el
    escenario con terraplén dejará que el agua rodee el extremo.
  - El sobreancho no hace falta: el terraplén se representa como una franja de una celda de
    ancho (con conectividad 4 para que no haya fugas diagonales).
- **Sin eje:** obtienes el mapa de anegamiento de toda la zona, pero no la rasante.

### Precipitación de diseño (mm)
- **Qué es:** lámina de lluvia del evento de diseño. Se ignora si ingresas una serie (Gumbel).
- **Criterios:**
  - Tómala del estudio hidrológico del proyecto para el periodo de retorno exigido por el
    Manual de Hidrología, Hidráulica y Drenaje del MTC según el tipo de obra.
  - En zonas donde llueve varios días seguidos (El Niño en la costa norte) usa la **lluvia
    acumulada máxima de 3 a 5 días**, no solo la de 24 h, porque las depresiones acumulan agua
    entre lluvias.
  - Por defecto: 150 mm. Es un valor de trabajo, no un dato del proyecto.
- **Efecto:** más lluvia → más volumen en cada depresión → cota de agua más alta.

### Serie de precipitaciones máximas anuales (opcional)
- **Qué es:** lista de máximos anuales en mm, separados por comas, puntos y coma o saltos de
  línea (por ejemplo `45, 60, 380, 610, 30`).
- **Criterios:**
  - Estación SENAMHI (o equivalente) más cercana y representativa; mínimo 3 valores, ideal 20 o
    más años.
  - Incluye los años extremos (1983, 1998, 2017 en Piura). Si el ajuste Gumbel queda por debajo
    de esos años, usa un ajuste Doble Gumbel o el acumulado observado como precipitación de
    diseño directa.
  - Debe ser la misma duración que quieras diseñar (24 h, 3 días, etc.).

### Periodo de retorno para Gumbel (años)
- **Criterio:** según el riesgo admisible y la vida útil de la obra (tabla del Manual MTC).
  Valores usuales: 25 a 50 años para drenaje transversal de vías secundarias, 50 a 100 para
  puentes y obras mayores. Por defecto 50.

### Método de escorrentía
- **Número de Curva SCS (recomendado):** necesita el CN. Adecuado con lluvias grandes y suelos
  con capacidad de infiltración conocida.
- **Coeficiente C:** escorrentía = C × lluvia. Más simple; útil si el estudio hidrológico ya fijó
  un C.

### Número de curva CN
- **Qué es:** parámetro SCS que resume tipo de suelo, uso y humedad previa (1 a 100).
- **Criterios:**
  - Usa **condición húmeda (AMC III)** para quedar del lado seguro en eventos largos.
  - Referencias: suelos arcillosos cultivados 85–92; pastos en suelos arcillosos 80–89; zonas
    urbanas densas 90–98; suelos arenosos con vegetación 55–75.
  - Por defecto 88. Ejecuta al menos con CN bajo (85) y alto (92) y adopta la cota mayor.

### Coeficiente de escorrentía C
- **Criterio:** solo si eliges ese método. Arcillas y terrenos planos cultivados 0.5–0.7; áreas
  urbanas 0.7–0.9; arenas 0.2–0.4. Por defecto 0.60.

### Modo de cálculo
- **Balance hídrico (recomendado):** el nivel de cada depresión depende del volumen que le llega.
- **Llenado hasta el rebose:** todas las depresiones llenas a su cota de rebose, independiente de
  la lluvia. Es la envolvente máxima posible; úsala como corrida de sensibilidad conservadora o
  cuando no confías en la lluvia de diseño.

### Profundidad mínima de una depresión (m)
- **Qué es:** filtro de ruido: depresiones menos profundas se descartan.
- **Criterios:** debe ser mayor que el error vertical del DEM. LiDAR o topografía: 0.20–0.30 m.
  DEM de 30 m (FABDEM, Copernicus): 0.50–1.00 m. Por defecto 0.30 m.
- **Síntoma de valor bajo:** miles de depresiones o manchas sueltas. **Síntoma de valor alto:**
  no aparece ninguna depresión junto a la vía.

### Área mínima de una depresión (m²)
- **Criterios:** al menos 2 celdas del DEM (con celda de 30 m, unos 2 000 m²). Sube a
  5 000–10 000 m² si salen demasiadas depresiones. Con LiDAR de 1–5 m puedes bajar a 500 m² para
  captar charcos junto a la vía. Por defecto 2 000 m².

### Altura del terraplén (m)
- **Qué es:** altura con que se eleva el eje en el escenario «con vía» para ver dónde represa.
- **Criterios:** la altura tentativa del proyecto sobre el terreno natural (típico 1.0–3.0 m).
  Un valor alto muestra la envolvente de represamiento; con 0 no se evalúa. Por defecto 2.0 m.
- **Uso del resultado:** las depresiones con `toca_via = SI` acumulan agua contra el talud; las
  que tienen `vierte_via = SI` pasan por encima de la vía y requieren alcantarilla en su punto
  más bajo.

### Borde libre (m)
- **Qué es:** margen que se suma a la cota de agua para obtener la rasante mínima.
- **Criterios:** confírmalo con el Manual MTC y el tipo de vía; valores usuales 0.50 m para el
  nivel de agua en zonas anegables y 0.30 m adicionales si hay oleaje o sedimentos. Por
  defecto 0.50 m.

## 2. Red de drenes (opcional)

### Red de drenes (líneas)
- **Qué es:** capa de líneas con los drenes, canales o cunetas existentes o proyectados. Puede
  importarse desde CAD (DXF): en QGIS, arrastra el DXF, elige la capa de líneas y guárdala como
  GeoPackage para poder agregarle campos.
- **Cómo se usa en el cálculo:**
  1. Cada dren se rasteriza como una franja de su **ancho**.
  2. De cada depresión que un dren atraviesa se descuenta el volumen que ese dren puede evacuar
     durante el evento: **capacidad (m³/s) × duración (h) × 3600**. Si varios drenes cruzan la
     misma depresión se suman sus capacidades.
  3. Si indicas **profundidad**, el dren se «graba» en el DEM (se rebaja el terreno en su
     franja), de modo que conecta físicamente las depresiones que atraviesa y las lleva hacia
     donde el dren desemboca.
- **Criterios de digitalización:** que las líneas sigan el fondo del dren y lleguen hasta su
  descarga real (río, canal mayor o borde del DEM). Un dren que termina en medio de una
  depresión no tiene salida y solo «descontará» volumen de forma ficticia.

### Campo con la capacidad (m³/s)
- **Qué es:** caudal máximo que el dren puede conducir (capacidad hidráulica a sección llena o
  a tirante de diseño).
- **De dónde sale:** del proyecto del dren, del operador (Junta de usuarios, PECHP en Piura) o
  con Manning: Q = (1/n) · A · R^(2/3) · S^(1/2) con la sección real. Si no hay dato, usa la
  «capacidad por defecto» de los parámetros avanzados (0 = el dren no descuenta nada).
- **Criterio conservador:** usa la capacidad real actual (con sedimentos y vegetación), no la de
  diseño, o reduce esta en 30–50 %.

### Campo con el ancho (m)
- **Qué es:** ancho superior del dren. Define cuántas celdas ocupa la franja y, por tanto, qué
  depresiones «toca».
- **Criterio:** ancho de espejo en el CAD. Si el dren es más angosto que la celda del DEM, ocupa
  igualmente la línea de celdas por donde pasa. Por defecto 2 m.

### Campo con la profundidad (m)
- **Qué es:** profundidad del dren respecto al terreno del DEM. Solo sirve para grabarlo.
- **Criterios:** úsala cuando el DEM no representa el dren (DEM de 30 m, dren angosto). Con
  LiDAR de detalle el dren ya está en el terreno: deja 0. Valor típico 1.0–2.5 m.

### Duración del evento de lluvia (h)
- **Qué es:** tiempo durante el cual se supone que el dren evacúa a su capacidad.
- **Criterios:** la misma duración de la lluvia de diseño (24 h para lluvia diaria; 72–120 h si
  usaste acumulados de 3 a 5 días). Por defecto 24 h. Con 0 los drenes no descuentan volumen.
- **Advertencia:** es una simplificación optimista (el dren nunca se satura ni se obstruye).
  Compara siempre con una corrida sin drenes.

## 3. Parámetros avanzados

| Parámetro | Criterio | Por defecto |
|---|---|---|
| Tamaño de celda de trabajo (m) | 0 = automático (se conserva la celda del DEM, o se agranda si supera 6 M de celdas). Fija 5 m con LiDAR de 1 m; 10–30 m para reconocimiento regional. | 0 |
| Rellenar huecos sin datos (celdas) | Radio máximo de búsqueda para interpolar huecos interiores. 10 celdas cubre nubes pequeñas; 0 desactiva. Los huecos que tocan el borde no se rellenan. | 10 |
| Radio de búsqueda alrededor del eje (m) | Distancia a cada lado del eje dentro de la cual se toma la cota de agua más alta. Debe cubrir el ancho de plataforma más taludes: 30–50 m en vías secundarias, 50–100 m en autopistas. | 50 |
| Distancia entre puntos del perfil (m) | Espaciado de las progresivas. 20 m para perfil; 10 m para expediente; 50 m para reconocimiento. | 20 |
| Caudal desbordado del río (m³/s) | Caudal de diseño del río menos la capacidad del cauce o de las defensas. 0 = no evaluar. | 0 |
| Ancho de la franja inundable B (m) | Mídelo en el mapa de peligro (INDECI/ANA) o en el DEM entre los límites de la llanura. | 3 000 |
| n de Manning de la llanura | Cultivos 0.025–0.035; matorral 0.04–0.05; urbano disperso 0.05–0.08. | 0.035 |
| Pendiente del valle S (m/m) | Pendiente longitudinal del río en el tramo (ANA). | 0.00036 |
| Capacidad / ancho / profundidad por defecto de drenes | Se usan cuando la capa de drenes no tiene el campo correspondiente o el valor está vacío. | 0 / 2 / 0 |

## 4. Corridas recomendadas para un perfil

1. Balance hídrico con CN bajo (85).
2. Balance hídrico con CN alto (92).
3. Llenado hasta el rebose (envolvente).
4. Si hay drenes: la corrida 2 con y sin la red de drenes.

Adopta la mayor cota entre 1, 2 y 3 como cota de anegamiento y justifica con la corrida 4 el
beneficio de los drenes, sin descontarlo del diseño salvo que su operación esté garantizada.
