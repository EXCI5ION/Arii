# Componentes de terceros

Arii se distribuye junto con componentes de terceros que conservan sus propias
licencias y avisos. Este documento es informativo y no sustituye los textos de
licencia incluidos con cada componente.

- **Qt for Python / PySide6 y Qt 6:** LGPL-3.0-only, GPL-2.0-only,
  GPL-3.0-only o licencia comercial, según el componente. Arii usa la edición
  comunitaria y conserva las bibliotecas dinámicas como archivos separados.
- **NumPy:** BSD-3-Clause y licencias adicionales declaradas por el paquete.
- **pyqtgraph:** MIT.
- **Paramiko:** LGPL-2.1.
- **keyring:** MIT.
- **Python y sus dependencias transitivas:** consulte los metadatos incluidos
  en la distribución.
- **R:** GPL-2.0 y/o GPL-3.0; el runtime conserva `COPYING` y sus avisos.
- **mixOmics:** GPL (>= 2).
- **jsonlite y restantes paquetes R:** el manifiesto del runtime enumera versión
  y licencia; cada directorio de paquete conserva `DESCRIPTION`, `LICENSE` y
  demás avisos suministrados por sus autores.

Fuentes y código correspondiente:

- https://code.qt.io/cgit/pyside/pyside-setup.git/
- https://code.qt.io/cgit/qt/
- https://github.com/numpy/numpy
- https://github.com/pyqtgraph/pyqtgraph
- https://github.com/paramiko/paramiko
- https://github.com/jaraco/keyring
- https://cran.r-project.org/sources.html
- https://git.bioconductor.org/packages/mixOmics
