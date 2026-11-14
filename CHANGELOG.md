# Historial de cambios

## 1.1.0 - 2026-11-13

- incorpora S-TOCSY interactivo para perfiles continuos, con selección del
  pivote desde el gráfico de valores de carga, escala cromática ajustable y
  exportación fiel a la geometría visible;
- amplía la navegación espectral mediante zoom y desplazamiento independientes
  por eje sin interferir con la selección del pivote;
- permite representar en los scores una segunda condición mediante el borde de
  cada muestra, además de la clase indicada por su relleno;
- reorganiza los temas y estilos gráficos e incorpora los modos claro, oscuro y
  clásico;
- corrige la validación leave-one-out en OPLS-DA y refuerza las pruebas de los
  métodos de validación cruzada;
- separa las preferencias de desarrollo de las correspondientes a la aplicación
  instalada y permite borrar desde la GUI el perfil local del clúster;
- añade instalación automatizada para macOS y compatibilidad comprobada con
  Python 3.12 y 3.13;
- incorpora manual de usuario, documentación científica en LaTeX/PDF y versión
  Markdown navegable desde GitHub, accesibles desde el nuevo menú de ayuda;
- independiza formalmente la versión de escritorio 1.1.0 del runtime remoto
  Slurm, que permanece en la versión 1.0.0.

## 1.0.1 - 2026-10-13

- corrige el estado de cálculo fantasma cuando el motor R local no puede
  iniciarse;
- muestra el error de arranque real y restablece los controles de la interfaz;
- diferencia correctamente los cálculos locales de los trabajos Slurm al
  cerrar Arii;
- separa correctamente las rutas absolutas usadas al empaquetar R en Windows
  de las rutas relocatables necesarias en el runtime Linux;
- elimina una detección de hardware ajena al motor científico, que utiliza
  exclusivamente CPU y memoria.

## 1.0.0 - 2026-10-04

Primera edición pública de Arii:

- PCA, PLS-DA y OPLS-DA mediante `mixOmics`;
- importación asistida de perfiles continuos y tablas de características desde
  CSV, TSV y TXT, con muestras en filas o columnas;
- centrado, Pareto y varianza unitaria con preprocesamiento reproducible;
- Random Subsets, Monte Carlo, Venetian Blinds y leave-one-out;
- selección de complejidad, scores, loadings, valores de carga, ROC, umbrales,
  Hotelling T², R²X, R²Y y Q²Y;
- tests de permutaciones empírico y residual, locales o distribuidos con Slurm;
- proyectos `.arii`, temas claro/oscuro y exportación ráster a tamaño exacto;
- ejecución local o en clúster mediante acceso SSH administrado por Arii;
- instalador Windows con runtime privado de R y motor Linux relocatable para
  servidor/clúster como descarga independiente;
- metadatos de citación preparados para el archivado de releases con Zenodo.

La distribución se publica bajo `GPL-3.0-or-later`, acompañada por los avisos
de las dependencias Python y R incluidas.
