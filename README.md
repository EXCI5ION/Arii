<p align="center">
  <img
    src="assets/branding/readme-header.png"
    alt="Arii — análisis quimiométrico de datos ómicos"
    width="1000"
  >
</p>

<p align="center">
  <a href="https://github.com/EXCI5ION/Arii/releases/latest">
    <img src="https://img.shields.io/github/v/release/EXCI5ION/Arii?label=Descargar&amp;logo=github&amp;color=2ea44f" alt="Descargar la última versión">
  </a>
  <a href="https://github.com/EXCI5ION/Arii/actions/workflows/tests.yml">
    <img src="https://github.com/EXCI5ION/Arii/actions/workflows/tests.yml/badge.svg?branch=main" alt="Estado de las pruebas">
  </a>
</p>

Arii es una aplicación de código abierto para el análisis quimiométrico
reproducible de matrices ómicas. Proporciona una interfaz gráfica para
PCA, PLS-DA y OPLS-DA sobre el paquete `mixOmics` sin exigir que el usuario trabaje desde
la consola de R.

Está orientada inicialmente a metabolómica, pero admite tanto perfiles
continuos como tablas de características procedentes de otras plataformas.

La ejecución local y el primer adaptador remoto Slurm comparten un contrato de trabajo.
Los perfiles de clúster conservan sólo configuración no secreta (Consulte docs/cluster-execution-design.md).
La configuración inicial está disponible en la GUI; una guía sin conocimientos previos se encuentra en docs/cluster-user-guide.md.

Versión actual: **1.0.0**.

## Descargar para Windows

[Descargar Arii 1.0.0 para Windows de 64 bits](https://github.com/EXCI5ION/Arii/releases/download/v1.0.0/Arii-1.0.0-windows-x64.exe)

El instalador incluye Arii, sus workers estadísticos y un runtime privado de R
con `mixOmics`. El archivo `.sha256` publicado junto al instalador permite comprobar su integridad.

Consulte la [última versión publicada](https://github.com/EXCI5ION/Arii/releases/latest) y
sus notas de lanzamiento.

## Funcionalidades

En su versión 1.0.0, Arii permite:

- importar matrices CSV, TSV y TXT con muestras en filas o columnas;
- trabajar con perfiles continuos y tablas de características discretas;
- asignar clases e individuos biológicos desde una tabla editable;
- aplicar centrado y escalado Pareto, de varianza unitaria o sin escalado;
- calcular PCA, PLS-DA y OPLS-DA mediante `mixOmics`;
- evaluar modelos supervisados con Random Subsets, Monte Carlo, leave-one-out o
  Venetian blinds;
- seleccionar la complejidad del modelo y consultar R²X, R²Y, Q²Y, BER,
  exactitud, matrices de confusión y ROC/AUC;
- explorar scores, loadings, T² de Hotelling y gráficos de valores de carga;
- ejecutar tests de permutaciones empíricos y comparaciones residuales;
- guardar datos, configuración y resultados en proyectos `.arii`;
- exportar figuras ráster con dimensiones exactas y los vectores necesarios
  para reproducir gráficos de valores de carga;
- ejecutar modelos localmente o distribuir validaciones y permutaciones en un
  clúster Slurm.

## Proyectos reproducibles

Los proyectos `.arii` conservan clases, individuos, muestras excluidas, estilos,
parámetros y resultados numéricos. El dataset original no se duplica: se
registra su ruta y su huella SHA-256. Si el archivo cambia, Arii lo advierte al
volver a abrir el proyecto.

Las réplicas que comparten individuo biológico permanecen juntas durante la
validación cruzada y las permutaciones. Los resultados registran la
configuración, semillas, particiones y versiones del motor científico.

## Ejecución en servidor o clúster

[`Arii-1.0.0-cluster-runtime-linux-x86_64.tar.gz`](https://github.com/EXCI5ION/Arii/releases/download/v1.0.0/Arii-1.0.0-cluster-runtime-linux-x86_64.tar.gz)
es exclusivamente el motor de cálculo para servidores y clústeres Linux x86-64
compatibles con glibc 2.28 o posterior. No contiene la interfaz gráfica,
credenciales, perfiles institucionales, datasets ni resultados.

Cada investigador debe utilizar su propia cuenta SSH y Slurm. La opción
recomendada permite que Arii utilice la contraseña una sola vez para instalar
una clave pública Ed25519; la contraseña no se guarda y las conexiones
posteriores se realizan con la clave cifrada de Arii. OpenSSH, alias SSH y
PuTTY/Pageant permanecen disponibles como alternativas avanzadas.

Consulta la [guía de uso del clúster](docs/cluster-user-guide.md) y las
[instrucciones del runtime de servidor](cluster/runtime/README-SERVER.md).

### Servidor o clúster Linux — consola

No es necesario instalar R, Python, Conda ni `mixOmics` en el servidor. Una vez
publicada la release, el runtime completo puede instalarse en el espacio personal
del usuario con:

```bash
ARII_VERSION=1.0.0
wget -O install-arii-server.sh \
  "https://raw.githubusercontent.com/EXCI5ION/Arii/v${ARII_VERSION}/cluster/install-server.sh"
less install-arii-server.sh
ARII_VERSION="$ARII_VERSION" bash install-arii-server.sh
```

El instalador usa `curl` o `wget`, comprueba la arquitectura y glibc, descarga
el checksum oficial, verifica SHA-256 y ejecuta la relocalización del entorno.
No requiere `sudo` ni modifica la instalación global del servidor. Al terminar
muestra la ruta exacta de `Rscript` que debe introducirse en Arii y el comando
opcional de prueba mediante Slurm.

## Instalación desde el código fuente

Arii requiere **Python 3.11 o posterior**; se recomienda Python 3.12. Para
ejecutar los modelos también deben estar disponibles `Rscript`, `mixOmics` y
`jsonlite`.

### Windows — PowerShell

Instala previamente [Python 3.12](https://www.python.org/downloads/) y
[R](https://cran.r-project.org/bin/windows/base/), y asegúrate de que
`Rscript.exe` esté disponible en `PATH`.

```powershell
git clone --branch v1.0.0 --depth 1 https://github.com/EXCI5ION/Arii.git
cd Arii
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
Rscript -e 'if (!requireNamespace("BiocManager", quietly=TRUE)) install.packages("BiocManager", repos="https://cloud.r-project.org"); BiocManager::install("mixOmics", ask=FALSE, update=FALSE); install.packages("jsonlite", repos="https://cloud.r-project.org")'
arii-gui
```

Si PowerShell bloquea la activación del entorno, consulta la
[documentación oficial de `venv`](https://docs.python.org/3/library/venv.html#how-venvs-work)
o ejecuta directamente `.\.venv\Scripts\python.exe -m pip ...`.

### Linux

Instala Python 3.11 o posterior, R y las bibliotecas gráficas que requiera Qt
mediante el gestor de paquetes de tu distribución. Después ejecuta:

```bash
git clone --branch v1.0.0 --depth 1 https://github.com/EXCI5ION/Arii.git
cd Arii
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
Rscript -e 'if (!requireNamespace("BiocManager", quietly=TRUE)) install.packages("BiocManager", repos="https://cloud.r-project.org"); BiocManager::install("mixOmics", ask=FALSE, update=FALSE); install.packages("jsonlite", repos="https://cloud.r-project.org")'
arii-gui
```

### macOS

Instala Python 3.11 o posterior, R y
[XQuartz](https://www.xquartz.org/), requerido por `mixOmics` en macOS. En una
terminal `bash` o `zsh` ejecuta:

```bash
git clone --branch v1.0.0 --depth 1 https://github.com/EXCI5ION/Arii.git
cd Arii
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
Rscript -e 'if (!requireNamespace("BiocManager", quietly=TRUE)) install.packages("BiocManager", repos="https://cloud.r-project.org"); BiocManager::install("mixOmics", ask=FALSE, update=FALSE); install.packages("jsonlite", repos="https://cloud.r-project.org")'
arii-gui
```

En Linux y macOS, Arii 1.0.0 se ofrece desde el código fuente y depende de la
compatibilidad de Qt, R y Bioconductor con el sistema. El instalador binario
oficial de esta versión corresponde a Windows de 64 bits. `mixOmics` se instala
mediante `BiocManager`, el método recomendado por Bioconductor.

## Desarrollo y pruebas

Para instalar las dependencias de desarrollo y ejecutar la suite:

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

GitHub Actions ejecuta en cada `push` y `pull request` una suite Python/Qt en
Windows y pruebas independientes de los workers científicos con R,
Bioconductor, `mixOmics` y `jsonlite` en Linux.

## Cómo citar

Los metadatos de autoría y versión se encuentran en
[`CITATION.cff`](CITATION.cff). GitHub puede generar desde ese archivo una
referencia en formatos APA y BibTeX.

Tras publicar la primera release, Zenodo proporcionará un DOI específico para
Arii 1.0.0 y un DOI conceptual que agrupará todas las versiones futuras. Ambos
se incorporarán aquí y en `CITATION.cff`.

## Licencia

Copyright (C) 2026 Gabriel Anderson.

Arii es software libre distribuido bajo la
[GNU General Public License](LICENSE) (`GPL-3.0-or-later`). Los componentes de
terceros conservan sus propias licencias; consulta
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
