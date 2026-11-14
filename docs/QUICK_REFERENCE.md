# Referencia rápida de Arii

## 1. Preparar y cargar los datos

1. Abra un CSV, TSV o TXT desde **Archivo > Abrir dataset…**.
2. Confirme que cada fila de la tabla de muestras corresponde a una muestra.
3. Marque las muestras que participarán en el análisis.
4. Asigne una clase para PLS-DA u OPLS-DA. El campo **Individuo** es opcional y
   permite representar un segundo factor visual y agrupar réplicas en la
   validación.

Los datos deben llegar con el pretratamiento específico de la técnica ya
realizado. Arii centra y escala, pero no sustituye la normalización, corrección
de deriva, imputación ni control de calidad propios de cada plataforma.

## 2. Elegir el análisis

- **PCA:** exploración no supervisada. Revise varianza explicada, scores,
  Hotelling, loadings, R²X y RMSE de reconstrucción.
- **PLS-DA:** clasificación supervisada multiclase.
- **OPLS-DA:** clasificación binaria con una dirección predictiva y componentes
  ortogonales para facilitar la interpretación de X.

## 3. Configurar la validación supervisada

- **Random subsets:** por defecto, 20 repeticiones de 5 folds estratificados.
- **Monte Carlo:** particiones aleatorias independientes con porcentaje de
  entrenamiento configurable.
- **Leave-one-out:** una unidad externa por submodelo.
- **Venetian blinds:** asignación sistemática a bloques; exige que el orden de
  las muestras tenga sentido y no introduzca sesgo.

## 4. Interpretar antes de reportar

- Use las métricas **CV** para estimar rendimiento interno; las de ajuste son
  descriptivas y normalmente optimistas.
- Revise BER, confusión y ROC además de Q²Y.
- La complejidad sugerida es exploratoria; no reemplaza una cohorte externa o
  validación anidada.
- En OPLS-DA, las métricas predictivas no cambian por la rotación ortogonal.
- Una elipse T² de Hotelling no demuestra separación estadística entre clases.

## 5. Loading plot y STOCSY

El **Loading plot** reescala el loading de la componente elegida y conserva el
signo mediante el color. Para perfiles RMN, active STOCSY y seleccione un punto
del espectro como pivote. Arii calcula covarianza y correlación contra todas las
variables usando el dataset completo cargado; el resultado es exploratorio y no
establece causalidad ni identidad metabólica.

## 6. Permutaciones

Seleccione primero el modelo actual y después ejecute el test. El p empírico usa
la corrección `(b + 1)/(B + 1)`. Cien permutaciones sólo permiten una resolución
mínima aproximada de 0,0099; aumente B para un informe definitivo.

## 7. Reproducibilidad

Guarde el proyecto `.arii`, anote la versión del programa, semilla, método de
validación, cantidad de componentes, preprocesamiento y unidad de remuestreo.
Consulte la [documentación científica](SCIENTIFIC_DOCUMENTATION.md) antes de
interpretar o publicar resultados.

## 8. Exportar y ejecutar remotamente

**Archivo > Exportar datos de loadings…** exporta el eje, los identificadores,
la desviación estándar y los pesos de la primera dirección del modelo actual:
PC1 en PCA, LV1 en PLS-DA y Predictiva en OPLS-DA. No exporta un informe ni todas
las tablas del análisis. Las figuras se exportan desde el menú contextual de
PyQtGraph; S-TOCSY dispone de su propio botón **Guardar figura**.

La versión del runtime remoto es independiente de la aplicación. Arii 1.1.0
continúa utilizando el runtime de clúster 1.0.0 mientras no cambien sus
dependencias ni el contrato de ejecución.
