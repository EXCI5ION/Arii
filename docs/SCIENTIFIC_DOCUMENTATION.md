# Documentación científica de Arii

**Versión documentada:** 1.2.0
**Alcance:** análisis quimiométrico de una matriz ómica mediante PCA con
`mixOmics` y PLS-DA/OPLS-DA con `mixOmics` o SIMPLS (`pls`).

[Fuente editorial LaTeX](scientific_documentation.tex) ·
[PDF científico de la versión 1.2.0](pdf/Arii-documentacion-cientifica-versión1.2.0.pdf)

Este documento explica qué calcula Arii, cómo se relaciona cada resultado con la
implementación y qué supuestos deben respetarse. Arii separa el tratamiento
técnico anterior a la matriz, el preprocesamiento estadístico aprendido dentro
del modelo y la presentación de resultados. Confundir esos niveles puede producir
una validación optimista aunque el cálculo sea numéricamente correcto.

## 1. Alcance y principio de diseño

PCA se calcula con `mixOmics`. Para PLS-DA y OPLS-DA, Arii permite elegir
`mixOmics` o el algoritmo SIMPLS de de Jong implementado por
`pls::simpls.fit`. El motor elegido se usa en el ajuste, la validación cruzada y
las permutaciones. Arii añade a ambos el mismo contrato de datos, selección de
complejidad, métricas y diagnósticos, además de una rotación ortogonal propia
para la vista OPLS-DA. No reemplaza el criterio analítico propio de RMN,
GC/LC-MS, proteómica, genómica u otra plataforma.

Arii separa tres niveles que no deben confundirse: el tratamiento técnico
anterior a la matriz, el preprocesamiento estadístico aprendido por el modelo y
la presentación de resultados. Este documento explica qué calcula Arii 1.2.0,
qué supuestos exige y qué conclusiones no permite.

## 2. Arquitectura estadística y motores de cálculo

### Límite entre Arii y las bibliotecas estadísticas

Arii separa la orquestación del análisis de la extracción numérica de las
componentes latentes. La interfaz construye una especificación JSON con datos,
clases, preprocesamiento, validación, semilla, complejidad y motor. Un worker R
consume ese contrato y produce un resultado estructurado independiente de la
figura mostrada.

En un análisis supervisado se ejecuta solamente el motor elegido. Ese mismo
motor se utiliza en el ajuste completo, todos los submodelos CV y todos los
modelos del test de permutaciones. Arii no ajusta ambos motores para compararlos
automáticamente ni valida un modelo con un algoritmo diferente.

| Operación | Motor mixOmics | Motor SIMPLS |
|---|---|---|
| Extracción PLS | `mixOmics::plsda` | `pls::simpls.fit` |
| Codificación de clase | Contrato de Arii y tratamiento de mixOmics | Matriz indicadora construida por Arii |
| Decisión de clase | `max.dist` de mixOmics | Máximo de la respuesta continua predicha, implementado por Arii |
| Preprocesamiento dentro de fold | Arii | Arii |
| Particiones y semillas CV | Arii | Arii |
| Métricas y selección | Arii | Arii |
| Permutaciones y contrastes residuales | Arii | Arii |
| Rotación OPLS-DA binaria | Arii | Arii |
| Paralelización local y Slurm | Arii | Arii |

PCA constituye una excepción al selector supervisado: se calcula exclusivamente
con `mixOmics`. El selector de motor se habilita para PLS-DA y OPLS-DA.

### Motor mixOmics

Arii entrega la matriz preprocesada y la clase a `mixOmics::plsda`. Esta función
transforma la respuesta categórica en una representación indicadora y obtiene
las componentes dentro del marco PLS iterativo utilizado por `mixOmics`,
relacionado con NIPALS. Las componentes se construyen secuencialmente mediante
scores y loadings asociados a X e Y, con deflación después de cada componente.
En problemas con muchas variables y pocas muestras, repetir esa iteración y
deflación dentro de cada fold o permutación puede aumentar el coste del motor.

El escalado interno se desactiva porque Arii ya aprendió y aplicó dentro del
entrenamiento el centrado y escalado seleccionado. Los scores, loadings y
respuestas continuas proceden del objeto de `mixOmics` y la decisión de clase
utiliza `max.dist`.

El paquete no controla el análisis completo: Arii sigue definiendo unidades de
remuestreo, folds, preprocesamiento sin fuga de información, métricas, selección,
permutaciones, persistencia y distribución. El resultado registra la versión
exacta de `mixOmics`.

### Motor SIMPLS

SIMPLS fue propuesto por de Jong para obtener factores PLS directamente como
combinaciones lineales de las variables originales, evitando la deflación
explícita de toda X. Para `g` clases, Arii construye una matriz indicadora
`Y` de dimensiones `n × g` y entrega `X` e `Y` a `pls::simpls.fit`.
Esquemáticamente, la primera dirección maximiza:

`||Y' X w||²`, sujeto a `||w|| = 1`,

y las direcciones siguientes satisfacen las restricciones de ortogonalidad de
SIMPLS.

Arii no reimplementa en producción esa extracción numérica. Para cada número de
componentes `a`, utiliza los coeficientes acumulados devueltos por `pls`:

`Y_hat_a = (X_nuevo - media_X) B_a + media_Y`,

y asigna cada muestra a la columna de `Y_hat_a` con mayor valor. Esta capa
convierte la regresión PLS multirrespuesta en el flujo PLS-DA de Arii y permite
dos o más clases.

Por tanto, Arii implementa un motor PLS-DA **basado en SIMPLS** y utiliza
`pls::simpls.fit` como núcleo numérico. Arii aporta la codificación, las
predicciones acumulativas, la clasificación, las métricas, la validación y las
permutaciones. El resultado registra la versión exacta de `pls`.

### Capa estadística común de Arii

Los dos motores comparten:

1. muestras, clases y unidades biológicas;
2. particiones y semillas;
3. centrado, escalado y descarte de constantes aprendidos sólo en entrenamiento;
4. predicciones externas por muestra y componente;
5. definiciones de R²Y, Q²Y, exactitud, BER, AUC y confusión;
6. regla de un error estándar para sugerir complejidad;
7. uso del mismo motor para el modelo observado y los modelos permutados.

Esta capa hace comparables las preguntas estadísticas, pero no convierte los
motores en algoritmos equivalentes. SIMPLS y otros algoritmos PLS pueden diferir
con respuestas multivariadas. Arii no exige igualdad de scores, loadings, pesos,
componentes seleccionados o métricas; incluso espacios predictivos próximos
pueden tener orientaciones distintas y el signo completo de una componente puede
invertirse sin modificar el modelo.

### Construcción OPLS-DA y procedencia

OPLS-DA parte del PLS-DA completo del motor seleccionado. Arii aplica después
una rotación binaria común que separa una dirección predictiva, definida por la
respuesta continua, y una base ortogonal del subespacio residual. Esta operación
pertenece a Arii: no es una llamada a una función OPLS nativa de `mixOmics` o
`pls` y no cambia las predicciones del PLS-DA subyacente.

El proyecto conserva la elección del motor y cada resultado registra motor,
versión de su paquete R y versión de R. Una comparación entre motores exige dos
ejecuciones explícitas y debe informarse como tal; no constituye una comprobación
automática de equivalencia.

## 3. Contrato de datos y preprocesamiento

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

## 4. Análisis de componentes principales

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

## 5. PLS-DA

PLS-DA modela una matriz indicadora de clases Y a partir de X. Con **mixOmics**,
Arii ajusta `mixOmics::plsda` y clasifica mediante `max.dist`. Con **SIMPLS**,
usa `pls::simpls.fit`, conserva las predicciones acumulativas de la matriz
indicadora y asigna la clase con la respuesta predicha máxima. Ambos motores
admiten dos o más clases y entregan respuestas continuas para R²Y, Q²Y, ROC y
los análisis de umbral.

La interfaz ejecuta únicamente el motor elegido. Ambos comparten datos,
preprocesamiento por fold, particiones y métricas, pero sus espacios latentes,
loadings y valores numéricos no deben suponerse idénticos. El resultado conserva
el nombre y la versión exacta del motor.

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

## 6. OPLS-DA

La implementación es una transformación del PLS-DA binario calculado con el
motor seleccionado. La dirección asociada a Y se denomina **Predictiva** y una base del
subespacio latente residual produce **Ortogonal 1**, **Ortogonal 2**, etc. Los
loadings se reestiman sobre los scores rotados.

La rotación facilita separar variación predictiva y no predictiva de X, pero no
vuelve a ajustar las clases. Por ello no modifica R²Y, Q²Y, BER, confusión, ROC o
las predicciones del PLS-DA subyacente. Los componentes ortogonales no deben
interpretarse como biomarcadores discriminantes.

Esta es una implementación explícita de Arii, no una llamada a una función OPLS
nativa de `mixOmics` ni de `pls`. Para cada complejidad, la respuesta continua predicha
define una base predictiva; una descomposición QR del residuo de los scores
genera las bases ortogonales y los loadings se reestiman por mínimos cuadrados.
La rotación se recalcula por complejidad, por lo que componentes ortogonales de
modelos distintos no forman necesariamente una base fija comparable.

## 7. Validación cruzada

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

Para ambos motores, Arii limita la complejidad al rango estimable por el modelo
completo y por el menor conjunto de entrenamiento de la CV. Así evita informar
componentes que algún submodelo no puede calcular de forma válida.

Arii diferencia el modelo sugerido del modelo actual. El usuario puede adoptar
otra complejidad; a partir de ese momento las vistas, la exportación y las
permutaciones se refieren a esa elección. La validación interna no corrige por sí
sola una imputación, filtrado supervisado o corrección de lote aprendida antes de
crear los folds.

Toda operación aprendida desde X debe ejecutarse dentro del entrenamiento. Arii
aplica este principio al centrado, escalado y eliminación de variables
constantes. Un preprocesamiento supervisado realizado globalmente antes de Arii
puede mantener fuga de información aunque la validación interna sea correcta.

## 8. Scores y T² de Hotelling

La elipse global para dos componentes utiliza:

`T²(alpha) = p(n-1)/(n-p) × F(alpha; p, n-p)`, con `p = 2`.

Representa una región multivariada global de scores, no intervalos por clase ni
una prueba de separación. El relleno de cada punto codifica la clase principal;
cuando existe individuo, su color puede mostrarse en el borde como segundo
factor visual sin intervenir en el ajuste.

La expresión se aplica a la proyección bidimensional visible y presupone una
estructura aproximadamente elíptica. Un punto exterior es una señal de revisión,
no evidencia automática de error ni autorización para excluir la muestra.

## 9. Loadings y gráfico de valores de carga

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

## 10. ROC y respuesta al umbral

Las curvas ROC usan respuestas continuas one-vs-rest. Arii calcula por separado
la curva del ajuste completo y la construida con la media de las respuestas
externas disponibles por muestra. Esta separación evita presentar una curva de
ajuste potencialmente optimista como rendimiento validado.

Para `g` clases, el AUC macro es la media no ponderada de las áreas por clase:

`AUC_macro = (1/g) sum(AUC_k)`.

La vista de respuesta al umbral presenta sensibilidad y especificidad. El umbral
CV exploratorio maximiza el índice de Youden
`J(c) = sensibilidad(c) + especificidad(c) - 1`. El AUC resume el ordenamiento a
través de todos los umbrales, mientras que Youden selecciona un único punto
operativo. Ese umbral no recalcula las métricas ni debe considerarse validado
clínicamente.

## 11. Tests de permutaciones

La etiqueta se permuta entre unidades intercambiables, manteniendo juntas las
réplicas de un individuo. Arii usa el mismo motor seleccionado para el modelo
observado y para todos los modelos nulos, fija la complejidad actual, reutiliza
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

## 12. STOCSY

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

## 13. Ejecución y reproducibilidad

### Un mismo contrato local y remoto

La ejecución local y Slurm comparten el mismo límite computacional: dataset,
especificación JSON, worker R y archivos auxiliares del motor. El destino cambia
dónde se ejecuta el trabajo, pero no su definición estadística. Se conservan las
muestras, clase, individuo, preprocesamiento, motor, particiones, semilla,
complejidad y definiciones de métricas.

En remoto, Arii crea una carpeta privada, transfiere el dataset, `job.json`, el
worker de la aplicación y sus auxiliares —incluido `pls_engine.R` cuando
corresponde—, genera uno o varios scripts `sbatch`, sigue su estado, comprueba la
integridad de los bloques distribuidos y recupera un único resultado científico.

El runtime remoto aporta R y dependencias versionadas (`mixOmics`, `pls` y
`jsonlite`), pero no reemplaza al worker de la aplicación. El worker actual se
transfiere con cada trabajo para evitar ejecutar silenciosamente código
estadístico antiguo. El runtime 1.0.0 no incluye `pls`; los dos motores requieren
el runtime 1.1.0 o posterior.

### Distribución de validación y permutaciones

Random subsets y Monte Carlo pueden repartir sus tareas entre varios trabajos
Slurm. Cada shard procesa sólo los folds que le corresponden y una fusión final
reconstruye las predicciones externas en su orden original. Leave-one-out y
Venetian blinds permanecen en un trabajo, aunque pueden usar varios procesos
dentro del nodo. Solicitar más trabajos que folds o repeticiones independientes
no aporta aceleración.

Las respuestas permutadas se reparten por índice global entre los nodos. Arii
ordena los resultados parciales antes de recalcular distribuciones nulas, valores
p y comparaciones residuales. La fusión comprueba método, semilla, selección,
unidad de intercambio, validación, modo, cantidad de permutaciones y resultado
observado; rechaza además índices ausentes, duplicados o fuera de rango. Si esos
contratos no coinciden, se detiene para no producir un test híbrido.

### Semillas, recursos y persistencia

Las semillas de folds y permutaciones se derivan determinísticamente de la
semilla principal y de índices globales. Cambiar CPU o nodos altera la asignación
física, no la secuencia científica esperada. Aun así, sistema, arquitectura o
BLAS pueden introducir diferencias de redondeo dentro de tolerancias. Los scripts
Slurm limitan a uno los hilos internos de OpenMP, OpenBLAS y MKL para evitar
sobresuscripción mientras Arii paraleliza mediante procesos independientes.

Los CPU limitan las tareas concurrentes; más memoria evita paginación o fallos,
pero no acelera un cálculo que ya cabe. Añadir nodos sólo ayuda si existen tareas
distribuibles y la ganancia supera transferencia, cola y fusión. La GPU no
participa actualmente en modelos, validaciones ni permutaciones, y Arii no la
consulta.

El worker, `job.json` y el resultado forman el límite reproducible. El proyecto
`.arii` conserva configuración, motor y resultados, pero referencia el dataset
por ruta y SHA-256. Un informe debe conservar además muestras, clases e
individuos, pretratamiento, centrado/escalado, modelo y complejidad, paquete R y
versión, CV, semilla, unidad de remuestreo, destino local o Slurm, tareas
efectivas, métricas, permutaciones, advertencias y validación independiente.

Los perfiles de acceso remoto son configuración operativa, no parte del
resultado científico, y nunca deben incorporar contraseñas al proyecto. Véase la
[guía del clúster](cluster-user-guide.md).

## 14. Limitaciones y uso responsable

Los modelos supervisados con `p >> n` son vulnerables al sobreajuste. Ninguna
separación visual, R²Y alto o p de permutación sustituye validación externa,
control de calidad, diseño experimental y plausibilidad biológica.

Arii no realiza actualmente imputación, corrección de lote, selección dispersa
de variables ni validación anidada. Si esos pasos se realizan antes de Arii con
información de clase o del dataset completo, el rendimiento CV puede quedar
sesgado. Tampoco transforma automáticamente conteos, composiciones o datos de
célula única a una geometría apropiada.

La vista OPLS-DA debe describirse como una rotación documentada del PLS-DA
binario de Arii, no como una implementación externa equivalente. El umbral de
Youden, la elipse de Hotelling y STOCSY son ayudas exploratorias, no decisiones
clínicas ni pruebas de identificación molecular.

## 15. Referencias y citación

- Rohart F, Gautier B, Singh A, Lê Cao KA. mixOmics: an R package for 'omics
  feature selection and multiple data integration. *PLoS Computational
  Biology*. 2017;13(11):e1005752.
  [doi:10.1371/journal.pcbi.1005752](https://doi.org/10.1371/journal.pcbi.1005752).
- de Jong S. SIMPLS: an alternative approach to partial least squares
  regression. *Chemometrics and Intelligent Laboratory Systems*.
  1993;18(3):251–263.
  [doi:10.1016/0169-7439(93)85002-X](https://doi.org/10.1016/0169-7439(93)85002-X).
- Mevik BH, Wehrens R. The pls Package: Principal Component and Partial Least
  Squares Regression in R. *Journal of Statistical Software*. 2007;18(2):1–24.
  [doi:10.18637/jss.v018.i02](https://doi.org/10.18637/jss.v018.i02).
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
