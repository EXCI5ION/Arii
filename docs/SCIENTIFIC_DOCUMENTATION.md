# Documentación científica de Arii

**Versión documentada:** 1.1.0  
**Alcance:** análisis quimiométrico de una matriz ómica mediante PCA, PLS-DA y
OPLS-DA con `mixOmics`.

[Fuente editorial LaTeX](scientific_documentation.tex) ·
[PDF científico](pdf/Arii-documentacion-cientifica-versión1.1.0.pdf)

Este documento explica qué calcula Arii, cómo se relaciona cada resultado con la
implementación y qué supuestos deben respetarse. Arii separa el tratamiento
técnico anterior a la matriz, el preprocesamiento estadístico aprendido dentro
del modelo y la presentación de resultados. Confundir esos niveles puede producir
una validación optimista aunque el cálculo sea numéricamente correcto.

## 1. Alcance y principio de diseño

Los modelos base se calculan con `mixOmics`. Arii añade el contrato de datos, la
validación agrupada, la selección de complejidad, los diagnósticos y una rotación
ortogonal propia para la vista OPLS-DA. No reemplaza el criterio analítico propio
de RMN, GC/LC-MS, proteómica, genómica u otra plataforma.

Arii separa tres niveles que no deben confundirse: el tratamiento técnico
anterior a la matriz, el preprocesamiento estadístico aprendido por el modelo y
la presentación de resultados. Este documento explica qué calcula Arii 1.1.0,
qué supuestos exige y qué conclusiones no permite.

## 2. Contrato de datos y preprocesamiento

### Matriz y metadatos

El núcleo trabaja con una matriz `X` de dimensiones `muestras × variables`. El
eje ppm o los nombres de características son metadatos de variables; clase e
individuo son metadatos de muestras. Arii puede reconocer archivos con muestras
en filas o columnas y normaliza internamente la orientación, pero nunca usa el
vector ppm como predictor.

La orientación es una propuesta que el usuario debe comprobar. Una matriz
transpuesta puede seguir siendo sintácticamente válida y, sin embargo, responder
una pregunta diferente. Arii también distingue perfiles continuos de tablas de
características: esa decisión afecta la representación y la disponibilidad de
STOCSY, no la forma matemática del ajuste.

Las matrices deben llegar con el pretratamiento técnico pertinente ya realizado:
normalización de área o estándar interno, corrección de deriva, alineamiento,
filtrado de calidad e imputación, cuando correspondan. La ausencia real de una
señal y un valor faltante no son conceptos intercambiables.

El identificador de individuo define la unidad de remuestreo cuando está
informado: sus réplicas permanecen juntas en entrenamiento o validación. Un
individuo no puede pertenecer a más de una clase.

El motor rechaza valores ausentes, infinitos o no numéricos y excluye del ajuste
las variables constantes. Arii no imputa automáticamente porque un cero, una
ausencia de detección y un valor faltante no son equivalentes entre plataformas.

### Centrado y escalado

Todas las opciones incluyen centrado por la media. Para cada variable `j`:

- **Pareto:** `(x_ij - media_j) / sqrt(sd_j)`.
- **Varianza unitaria:** `(x_ij - media_j) / sd_j`.
- **Sin escalado:** `x_ij - media_j`.

En validación supervisada, media y desviación se estiman sólo en el conjunto de
entrenamiento y se aplican después al conjunto externo. Esto evita fuga de
información.

Pareto reduce la dominancia de variables intensas sin igualar completamente sus
varianzas. El escalado unitario concede un peso similar a todas las variables no
constantes y puede amplificar ruido de baja varianza. Sin escalado conserva las
diferencias originales de magnitud. Ninguna opción es universal.

## 3. Análisis de componentes principales

PCA describe direcciones ortogonales de máxima varianza de X sin utilizar las
clases. Los scores ubican muestras y los loadings relacionan variables con cada
componente. La varianza explicada acumulada se informa como R²X.

Para `a` componentes, Arii reconstruye `X_hat = T_a P_a'` e informa:

- `RMSE = sqrt(mean((X - X_hat)^2))`;
- `R²X = 1 - SSE/TSS`.

Son métricas descriptivas calculadas sobre las mismas muestras utilizadas para
ajustar el PCA. No constituyen validación predictiva ni justifican por sí solas
un número óptimo de componentes.

La clase no interviene en el ajuste, aunque puede colorear los scores. Una
agrupación visual por clase sigue siendo descriptiva y no equivale a una
clasificación supervisada. La cantidad máxima queda limitada por
`min(n - 1, p)`; añadir componentes aumenta normalmente R²X aunque esas
direcciones puedan recoger ruido.

## 4. PLS-DA

PLS-DA modela una matriz indicadora de clases Y a partir de X. Arii ajusta
`mixOmics::plsda`, asigna clase mediante `max.dist` y conserva las respuestas
continuas para calcular R²Y, Q²Y, ROC y los análisis de umbral.

### Métricas

- **R²Y:** bondad de ajuste del modelo completo, `1 - SSE/TSS` sobre Y.
- **Q²Y:** capacidad predictiva interna, usando exclusivamente predicciones
  externas de validación cruzada.
- **Exactitud:** proporción total correctamente clasificada.
- **BER:** media de los errores por clase; es preferible a la exactitud cuando
  los tamaños de clase difieren.
- **AUC:** área ROC one-vs-rest; el AUC macro es la media no ponderada entre
  clases.

Arii separa resultados de **ajuste** y **CV**. El ajuste describe cómo el modelo
representa sus propios datos y suele ser optimista. CV aproxima el rendimiento
interno fuera de fold.

## 5. OPLS-DA

La implementación es una transformación de un PLS-DA binario calculado con
`mixOmics`. La dirección asociada a Y se denomina **Predictiva** y una base del
subespacio latente residual produce **Ortogonal 1**, **Ortogonal 2**, etc. Los
loadings se reestiman sobre los scores rotados.

La rotación facilita separar variación predictiva y no predictiva de X, pero no
vuelve a ajustar las clases. Por ello no modifica R²Y, Q²Y, BER, confusión, ROC o
las predicciones del PLS-DA subyacente. Los componentes ortogonales no deben
interpretarse como biomarcadores discriminantes.

Esta es una implementación explícita de Arii, no una llamada a una función OPLS
nativa de `mixOmics`. Para cada complejidad, la respuesta continua predicha
define una base predictiva; una descomposición QR del residuo de los scores
genera las bases ortogonales y los loadings se reestiman por mínimos cuadrados.
La rotación se recalcula por complejidad, por lo que componentes ortogonales de
modelos distintos no forman necesariamente una base fija comparable.

## 6. Validación cruzada

### Random subsets repetido

La configuración predeterminada ejecuta 20 repeticiones de 5 folds
estratificados. En cada repetición todos los folds actúan una vez como conjunto
externo: se generan 100 submodelos y cada unidad recibe una predicción externa
por repetición. La fracción teórica es 80/20, con variaciones por redondeo y
agrupación de réplicas.

La estratificación se realiza sobre unidades de remuestreo. Con identificador
biológico, todas las réplicas comparten fold; sin él, cada muestra constituye
una unidad. Cada clase necesita al menos tantas unidades independientes como
folds y Arii registra la fracción externa efectiva.

### Monte Carlo

Cada iteración genera una partición aleatoria estratificada independiente con
el porcentaje de entrenamiento elegido. No garantiza que todas las muestras
sean externas el mismo número de veces; Arii informa la cobertura efectiva.

### Leave-one-out

Retira una unidad de remuestreo por submodelo. Usa gran parte de los datos para
entrenar, pero puede tener varianza alta y ser costoso. Con individuos, se retira
el grupo completo y no una réplica aislada.

### Venetian blinds

Distribuye sistemáticamente las unidades ordenadas entre folds. Sólo es
defendible si el orden no codifica clase, lote, deriva o dependencia temporal de
forma que favorezca artificialmente la predicción.

### Selección de complejidad

La sugerencia usa la regla de un error estándar sobre BER CV: elige la menor
cantidad de componentes cuyo error no supera el mínimo más un error estándar.
Como selección y estimación reutilizan la misma CV, el resultado es exploratorio.
Una estimación final sin sesgo requiere validación anidada o datos externos.

Arii diferencia el modelo sugerido del modelo actual. El usuario puede adoptar
otra complejidad; a partir de ese momento las vistas, la exportación y las
permutaciones se refieren a esa elección. La validación interna no corrige por sí
sola una imputación, filtrado supervisado o corrección de lote aprendida antes de
crear los folds.

Toda operación aprendida desde X debe ejecutarse dentro del entrenamiento. Arii
aplica este principio al centrado, escalado y eliminación de variables
constantes. Un preprocesamiento supervisado realizado globalmente antes de Arii
puede mantener fuga de información aunque la validación interna sea correcta.

## 7. Scores y T² de Hotelling

La elipse global para dos componentes utiliza:

`T²(alpha) = p(n-1)/(n-p) × F(alpha; p, n-p)`, con `p = 2`.

Representa una región multivariada global de scores, no intervalos por clase ni
una prueba de separación. El relleno de cada punto codifica la clase principal;
cuando existe individuo, su color puede mostrarse en el borde como segundo
factor visual sin intervenir en el ajuste.

La expresión se aplica a la proyección bidimensional visible y presupone una
estructura aproximadamente elíptica. Un punto exterior es una señal de revisión,
no evidencia automática de error ni autorización para excluir la muestra.

## 8. Loadings y gráfico de valores de carga

La vista **Loadings** muestra el loading estándar. **Loading plot** lo reescala
para recuperar una magnitud más próxima a las variables originales:

- Pareto: `valor_jk = sqrt(sd_j) × loading_jk`;
- varianza unitaria: `valor_jk = sd_j × loading_jk`;
- sin escalado: conserva el loading.

El color representa el loading con signo. En perfiles RMN el eje ppm se muestra
descendente y se dibuja una curva continua; las tablas discretas se representan
como líneas o puntos independientes para no sugerir continuidad inexistente. El
signo de una componente latente es indeterminado y puede invertirse sin cambiar
el modelo.

Para tablas de características Arii no une variables adyacentes con una curva,
porque esa continuidad sería artificial. Para perfiles continuos conserva la
geometría del eje y, en RMN, el orden descendente de ppm.

## 9. ROC y respuesta al umbral

Las curvas ROC usan respuestas continuas one-vs-rest. Arii muestra por separado
ajuste y CV. La vista de respuesta al umbral presenta sensibilidad y
especificidad; el umbral CV exploratorio maximiza el índice de Youden
`sensibilidad + especificidad - 1`. Ese umbral no recalcula las métricas ni debe
considerarse validado clínicamente.

## 10. Tests de permutaciones

La etiqueta se permuta entre unidades intercambiables, manteniendo juntas las
réplicas de un individuo. Arii fija la complejidad del modelo actual, reutiliza
los folds y las transformaciones de X permitidas, y repite la evaluación externa
para cada Y permutada.

El resultado principal es el p empírico con corrección:

`p = (1 + b)/(B + 1)`.

La cola es superior para R²Y, Q²Y y AUC, e inferior para BER. Con `B`
permutaciones, la mínima resolución posible es `1/(B+1)`. La comparación residual
y las gráficas contra correlación de Y son diagnósticos complementarios; no
reemplazan el p empírico.

La intercambiabilidad debe ser defendible: bloques, pares, familias, centros o
series temporales pueden exigir restricciones adicionales. La complejidad se
mantiene fija en la del modelo actual, de modo que el test no corrige el
optimismo de haber seleccionado esa complejidad con el mismo dataset.

La pregunta inferencial es: «¿un modelo con esta complejidad supera lo esperable
bajo etiquetas intercambiadas?». Repetir la selección completa dentro de cada
permutación respondería otra pregunta y tendría un coste computacional mayor.

La interpretación detallada está en la [guía del test de
permutaciones](permutation-test-guide.md).

## 11. STOCSY

STOCSY usa una variable pivote de un perfil continuo y calcula, a través de las
muestras, su covarianza y correlación con cada variable. Arii usa el dataset
completo cargado para maximizar el número estadístico, independientemente de las
muestras que participaron en el modelo desde cuyo loading plot se abrió la
herramienta.

El perfil vertical representa covarianza y el color representa correlación. Una
asociación puede reflejar pertenencia al mismo metabolito, covariación biológica,
clase, lote o confusión. STOCSY es exploratorio: no demuestra causalidad ni
identifica por sí solo un metabolito.

La selección gráfica usa la variable cuyo eje es más cercano al punto elegido.
Si el pivote no varía entre muestras, la correlación no está definida y Arii
rechaza el cálculo. Usar el dataset completo aumenta el tamaño muestral, pero
también significa que la selección del modelo no restringe STOCSY.

## 12. Ejecución local y Slurm

El mismo worker R y la misma especificación JSON se usan localmente y en Slurm.
Las validaciones y permutaciones independientes pueden distribuirse; el modelo
final conserva el mismo contrato científico. La GPU no participa actualmente en
los cálculos y Arii no la consulta.

El worker, la especificación JSON y el resultado forman el límite reproducible
entre interfaz y motor. Las semillas de tareas paralelas se derivan de forma
determinista para que cambiar la cantidad de CPU no cambie la secuencia
científica esperada.

Los perfiles de acceso remoto son configuración operativa, no parte del
resultado científico, y nunca deben incorporar contraseñas al proyecto. Véase la
[guía del clúster](cluster-user-guide.md).

## 13. Reproducibilidad y límites

Un informe debe conservar dataset y huella, clases e individuos, muestras
incluidas, centrado/escalado, método y semilla de CV, cantidad de componentes,
versión de Arii/R/`mixOmics`, métricas externas y advertencias. Los proyectos
`.arii` guardan configuración y resultados, pero referencian el dataset por ruta
y SHA-256 para evitar duplicar datos grandes o sensibles.

La exportación visible de datos produce únicamente el eje o identificador,
desviación estándar y pesos de la primera dirección del modelo actual. Las
figuras se exportan por separado y representan el estado visual elegido; no
constituyen por sí solas un paquete reproducible del análisis.

Los modelos supervisados con `p >> n` son vulnerables al sobreajuste. Ninguna
separación visual, R²Y alto o p de permutación sustituye validación externa,
control de calidad, diseño experimental y plausibilidad biológica.

Arii no realiza actualmente imputación, corrección de lote, selección dispersa
de variables ni validación anidada. Tampoco transforma automáticamente conteos,
composiciones o datos de célula única a una geometría apropiada. La vista
OPLS-DA debe describirse como una rotación documentada del PLS-DA binario de
Arii, no como una implementación externa equivalente.

## 14. Referencias y citación

- Rohart F, Gautier B, Singh A, Lê Cao KA. mixOmics: an R package for 'omics
  feature selection and multiple data integration. *PLoS Computational
  Biology*. 2017;13(11):e1005752.
  [doi:10.1371/journal.pcbi.1005752](https://doi.org/10.1371/journal.pcbi.1005752).
- Wiklund S et al. Visualization of GC/TOF-MS-based metabolomics data for
  identification of biochemically interesting compounds using OPLS class
  models. *Analytical Chemistry*. 2008;80:115–122.
  [doi:10.1021/ac0713510](https://doi.org/10.1021/ac0713510).
- Trygg J, Wold S. Orthogonal projections to latent structures (O-PLS).
  *Journal of Chemometrics*. 2002;16(3):119–128.
  [doi:10.1002/cem.695](https://doi.org/10.1002/cem.695).
- Westerhuis JA et al. Assessment of PLSDA cross validation. *Metabolomics*.
  2008;4(1):81–89.
  [doi:10.1007/s11306-007-0099-6](https://doi.org/10.1007/s11306-007-0099-6).
- Cloarec O et al. Statistical total correlation spectroscopy: an exploratory
  approach for latent biomarker identification from metabolic 1H NMR data sets.
  *Analytical Chemistry*. 2005;77:1282–1289.
  [doi:10.1021/ac048630x](https://doi.org/10.1021/ac048630x).

Para citar Arii use `CITATION.cff` y el DOI indicado en el README de la versión
utilizada.
