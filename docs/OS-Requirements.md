# Requisitos del sistema

Esta guía reúne la preparación previa necesaria para instalar Arii 1.0.0. Los
comandos de instalación de la aplicación se mantienen en el
[`README.md`](../README.md).

## Distribuciones autocontenidas

El instalador oficial para Windows ya incluye Python, R, `mixOmics`, `jsonlite`
y las demás dependencias de ejecución. Es la opción recomendada para usuarios
de Windows y no requiere preparar un entorno de desarrollo.

El runtime para servidores o clústeres Linux también incluye R y sus paquetes.
No debe confundirse con la aplicación de escritorio: solamente proporciona el
motor de cálculo remoto.

## Instalación desde el código fuente

Las instalaciones desde código fuente requieren:

- [Git](https://git-scm.com/downloads);
- [Python 3.12](https://www.python.org/downloads/);
- R 4.5.x;
- acceso a Internet durante la instalación de paquetes.

Arii 1.0.0 se validó con R 4.5.2 en Windows y R 4.5.3 en Linux. Utiliza
[Bioconductor 3.22](https://bioconductor.org/news/bioc_3_22_release/), diseñado
para la serie R 4.5.

Las dependencias Python están declaradas en [`pyproject.toml`](../pyproject.toml)
y se instalan automáticamente mediante `python -m pip install .`:

- [NumPy](https://pypi.org/project/numpy/);
- [PySide6](https://pypi.org/project/PySide6/);
- [pyqtgraph](https://pypi.org/project/pyqtgraph/);
- [Paramiko](https://pypi.org/project/paramiko/);
- [keyring](https://pypi.org/project/keyring/).

El comando R incluido en el README instala automáticamente:

- [BiocManager](https://cran.r-project.org/package=BiocManager);
- [mixOmics](https://bioconductor.org/packages/3.22/bioc/html/mixOmics.html) y
  sus dependencias;
- [jsonlite](https://cran.r-project.org/package=jsonlite).

No es necesario descargar individualmente estos paquetes.

## Windows

### Instalador oficial

- Windows 10 u 11 de 64 bits.
- No requiere una instalación externa de Python o R.

### Desde el código fuente

- [Python 3.12 para Windows](https://www.python.org/downloads/);
- [R 4.5.2 para Windows](https://cran.r-project.org/bin/windows/base/old/4.5.2/R-4.5.2-win.exe);
- Git para Windows.

Durante la instalación de R, permita que `Rscript.exe` pueda localizarse desde
la consola o añada su carpeta `bin` a `PATH`. Si R necesita compilar algún
paquete para el que no haya binario disponible, instale también
[Rtools45](https://cran.r-project.org/bin/windows/Rtools/rtools45/rtools.html).

## Linux

Arii requiere una sesión gráfica para ejecutar la GUI. Los nombres concretos
de los paquetes del sistema varían entre distribuciones.

En Debian y Ubuntu, las bibliotecas de ejecución más habituales para Qt son:

```bash
sudo apt install git python3-venv libegl1 libgl1 libdbus-1-3 \
  libxkbcommon-x11-0 libxcb-cursor0 libxcb-xinerama0
```

El intérprete utilizado para crear el entorno virtual debe ser Python 3.12. Si
es necesario compilar R o dependencias de R desde código fuente, normalmente
también se requieren:

```bash
sudo apt install build-essential gfortran libcurl4-openssl-dev libssl-dev \
  libxml2-dev libfontconfig1-dev libfreetype6-dev libharfbuzz-dev \
  libfribidi-dev libpng-dev libtiff-dev libjpeg-dev libgl1-mesa-dev \
  libglu1-mesa-dev libx11-dev libxt-dev
```

Utilice R 4.5.3. Su
[código fuente oficial](https://cran.r-project.org/src/base/R-4/R-4.5.3.tar.gz)
permanece disponible en CRAN si el gestor de paquetes de la distribución no
ofrece esa versión.

## macOS

Se requiere macOS 11 o posterior y una versión de Python 3.12 adecuada para la
arquitectura del equipo.

Instale uno de los paquetes oficiales de R:

- [R 4.5.3 para Apple silicon](https://cran.r-project.org/bin/macosx/big-sur-arm64/base/R-4.5.3-arm64.pkg);
- [R 4.5.3 para Intel](https://cran.r-project.org/bin/macosx/big-sur-x86_64/base/R-4.5.3-x86_64.pkg).

Instale además [XQuartz](https://www.xquartz.org/), utilizado por dependencias
gráficas de `mixOmics`. Si algún paquete R debe compilarse desde código fuente,
pueden ser necesarias las herramientas de Apple y GNU Fortran:

```bash
xcode-select --install
```

Los compiladores compatibles están disponibles en la
[página de herramientas de R para macOS](https://mac.r-project.org/tools/).

## Servidor o clúster Linux

El runtime precompilado requiere:

- Linux x86-64;
- glibc 2.28 o posterior;
- `bash`, `tar` y `sha256sum`;
- `curl` o `wget` para la instalación automática;
- una carpeta personal escribible;
- acceso SSH y una cuenta Slurm propia para la ejecución remota desde Arii.

No requiere instalar R, Python, Conda ni `mixOmics` en el servidor. Consulte la
[guía de usuario del clúster](cluster-user-guide.md) para configurar la conexión.

## Comprobación rápida

Antes de instalar Arii desde código fuente, compruebe las versiones:

```bash
python --version
Rscript --version
git --version
```

Después de ejecutar los comandos del README, compruebe el motor R:

```bash
Rscript -e 'stopifnot(getRversion() >= "4.5", getRversion() < "4.6", requireNamespace("mixOmics", quietly=TRUE), requireNamespace("jsonlite", quietly=TRUE)); cat("Entorno R de Arii: OK\n")'
```

Y las dependencias Python:

```bash
python -c "import numpy, PySide6, pyqtgraph, paramiko, keyring; print('Entorno Python de Arii: OK')"
```
