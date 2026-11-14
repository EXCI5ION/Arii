# Requisitos del sistema

Esta guía reúne la preparación previa necesaria para instalar Arii 1.1.0. Los
comandos de instalación de la aplicación se mantienen en el
[`README.md`](../README.md).

## Distribuciones autocontenidas

El instalador oficial para Windows ya incluye Python, R, `mixOmics`, `jsonlite`
y las demás dependencias de ejecución. Es la opción recomendada para usuarios
de Windows y no requiere preparar un entorno de desarrollo.

El runtime para servidores o clústeres Linux también incluye R y sus paquetes.
No debe confundirse con la aplicación de escritorio: solamente proporciona el
motor de cálculo remoto. Su ciclo de versión es independiente: Arii 1.1.0
continúa utilizando el runtime de clúster 1.0.0.

## Instalación desde el código fuente

Las instalaciones desde código fuente requieren:

- [Git](https://git-scm.com/downloads);
- [Python 3.12 o 3.13](https://www.python.org/downloads/);
- R 4.5.x;
- acceso a Internet durante la instalación de paquetes.

Arii se validó con R 4.5.2 en Windows y R 4.5.3 en Linux. La versión 1.1.0 utiliza
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

El paquete se compila para x64. Las compilaciones nuevas también se pueden
instalar en **Windows 11 ARM64** mediante la capa oficial de compatibilidad x64
del sistema. En ese caso Arii y su runtime científico se ejecutan emulados, no
como binarios ARM64 nativos. Esta modalidad debe validarse en hardware ARM64
antes de considerarse equivalente a la distribución x64; Windows 10 ARM no es
compatible.

Una distribución totalmente nativa para ARM64 queda pendiente hasta que R y el
ecosistema Bioconductor para Windows ARM dispongan de una validación comparable
a la de Windows x86-64.

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

El intérprete utilizado para crear el entorno virtual debe ser Python 3.12 o
3.13. El instalador global usa el `python3` predeterminado de la distribución y
rechaza otras versiones con un mensaje explícito. Si
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

El instalador global admite **macOS 13 o posterior**, tanto en Apple Silicon
(`arm64`) como en Intel (`x86_64`). Se necesitan:

- una Terminal ejecutada de forma nativa, no mediante Rosetta;
- Python 3.9 o posterior solamente para iniciar el instalador;
- Git y las herramientas de línea de comandos de Apple;
- conexión a Internet y al menos 8 GiB libres durante la instalación.

El instalador proporciona su propio Python 3.12, R 4.5.3, `mixOmics` y
`jsonlite`; no necesita instalarlos manualmente. Las herramientas de Apple se
obtienen con:

```bash
xcode-select --install
```

En una instalación manual desde el código fuente, utilice Python 3.12 o 3.13 y
uno de los paquetes oficiales de R 4.5.3 para
[Apple Silicon](https://cran.r-project.org/bin/macosx/big-sur-arm64/base/R-4.5.3-arm64.pkg)
o [Intel](https://cran.r-project.org/bin/macosx/big-sur-x86_64/base/R-4.5.3-x86_64.pkg).
Algunas dependencias gráficas de R también pueden requerir
[XQuartz](https://www.xquartz.org/).

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
