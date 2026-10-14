# Photo Watermark 1.0

Aplicación de escritorio en español para estampar un logo sobre una fotografía o un lote. Compatible con **Debian 11, 12 y 13 con Cinnamon**, con Python 3.9 o superior, GTK 3.24 y Pillow 8.1 o superior. Todo el procesamiento se hace localmente.

## Instalar y ejecutar

Instala las dependencias desde los repositorios de Debian:

```bash
sudo apt update
sudo apt install python3 python3-gi gir1.2-gtk-3.0 python3-pil librsvg2-common
```

Desde la carpeta del proyecto:

```bash
./run.sh
```

También puedes ejecutar `/usr/bin/python3 app.py`. No hace falta instalar paquetes con pip ni crear un entorno virtual. `run.sh` usa el Python del sistema para encontrar las dependencias instaladas mediante apt.

Opcionalmente, crea una entrada **Photo Watermark** en el menú de Cinnamon:

```bash
/usr/bin/python3 install_launcher.py
```

El instalador solo crea un archivo `.desktop` del usuario. El programa continúa usando esta carpeta del proyecto: si la mueves, vuelve a crear el lanzador. No requiere `sudo`.

## Uso

1. Pulsa **Elegir logo**. Se detectan los archivos de `logos/`, incluidas sus subcarpetas. Puedes buscar por nombre, carpeta o formato, y ver el logo sobre un fondo cuadriculado que muestra la transparencia.
2. Selecciona **Ancho** o **Alto** y la unidad: **Píxeles fijos** o **Porcentaje de la fotografía**. El otro lado siempre conserva la proporción del logo.
3. Elige una de las ocho posiciones y escribe el **margen en píxeles**. La casilla central no es una posición seleccionable. Opcionalmente ajusta la opacidad; 100 conserva la transparencia propia del archivo sin atenuarla.
4. Añade una o varias fotografías, o una carpeta completa con sus subcarpetas. Selecciona una foto de la lista para comprobar su vista previa y las dimensiones calculadas.
5. Elige la carpeta de salida y el formato. Pulsa **Aplicar a las fotografías**.

El procesamiento corre en segundo plano y muestra el progreso y el resultado de cada archivo. **Cancelar** termina la fotografía actual y omite las pendientes. Un archivo defectuoso o una marca que no cabe generan un error para esa fotografía; el resto del lote continúa. Puedes guardar un informe de los resultados.

El menú de hamburguesa **☰**, en la barra superior, incluye **Acerca de Photo Watermark** y **Salir**. El diálogo «Acerca de» muestra la versión 1.0, la descripción, el enlace a [LibreCía](https://librecia.com/), los créditos de Misael Matamoros, el copyright de 2026 y la declaración de ausencia de garantía bajo la GPL versión 3 o posterior.

### Ejemplos de tamaño

Para un logo de 1500 × 600 px:

| Selección | Fotografía | Marca calculada |
|---|---|---|
| Ancho, 750 px | Cualquier tamaño que permita colocarla | 750 × 300 px |
| Alto, 750 px | Cualquier tamaño que permita colocarla | 1875 × 750 px |
| Ancho, 50 % | 4000 × 3000 px | 2000 × 800 px |
| Alto, 30 % | 4000 × 3000 px | 2250 × 900 px |
| Alto, 30 % | 3000 × 2000 px | 1500 × 600 px |

Los porcentajes se calculan **para cada fotografía**, después de aplicar su orientación EXIF, sobre el ancho o alto completo de la foto. Los resultados se redondean al píxel más cercano. Las medidas incluyen el lienzo transparente del logo: si tiene espacio vacío alrededor, ese espacio forma parte de su tamaño.

### Posiciones y margen

| Posición | Bordes que usan el margen |
|---|---|
| Superior izquierda | Superior e izquierdo |
| Superior centro | Superior; centrada horizontalmente |
| Superior derecha | Superior y derecho |
| Centro izquierda | Izquierdo; centrada verticalmente |
| Centro derecha | Derecho; centrada verticalmente |
| Inferior izquierda | Inferior e izquierdo |
| Inferior centro | Inferior; centrada horizontalmente |
| Inferior derecha | Inferior y derecho |

Por ejemplo, **Inferior derecha, margen 100 px** deja 100 píxeles desde el lienzo del logo hasta los bordes derecho e inferior. El margen no se aplica a los ejes centrados ni al borde opuesto. Si la marca o el margen solicitado hacen que se salga de la foto, se muestra el problema; no se recorta ni se reduce automáticamente.

### Biblioteca y configuraciones

- **Importar logo** copia un archivo a la biblioteca personal y lo deja disponible en las siguientes sesiones.
- **Añadir carpeta** registra otra carpeta de logos, incluidas sus subcarpetas. Esa carpeta debe seguir existiendo para usar sus archivos.
- **Guardar** crea una configuración con nombre que recuerda el logo, la dimensión, la unidad, el tamaño, la posición, el margen, la opacidad y el formato de salida.
- Al abrir el programa se restauran los últimos ajustes y la carpeta de salida. La lista de fotografías comienza vacía.

La configuración se guarda en `~/.config/photo-watermark/settings.json` y los logos importados en `~/.local/share/photo-watermark/logos/`. Se respetan las variables `XDG_CONFIG_HOME` y `XDG_DATA_HOME`.

### Archivos

- Logos: PNG y SVG, además de JPEG, WebP y TIFF. Usa PNG transparente o SVG para mantener la transparencia. Los SVG se rasterizan al tamaño solicitado.
- Fotografías: JPEG, PNG, WebP y TIFF estáticos, con extensiones indistintamente en mayúsculas o minúsculas. Los archivos animados o de varias páginas se rechazan.
- Salida: formato original, JPEG, PNG, WebP o TIFF. Se mantienen las dimensiones orientadas de la fotografía. JPEG y WebP usan calidad 95; PNG y TIFF usan compresión sin pérdida. JPEG se guarda sobre blanco si la fuente tiene transparencia.
- Se conservan EXIF, perfil ICC y resolución cuando el formato lo admite, salvo la orientación EXIF ya aplicada. Al convertir una foto CMYK a RGB se descarta su perfil CMYK, que ya no corresponde a los píxeles resultantes.
- Los originales se conservan. Las copias se llaman `nombre_marca.jpg`; si ese nombre ya existe, se usa `nombre_marca_2.jpg`, etc. Nunca se sobrescribe un archivo existente.
- Al importar una carpeta se excluyen `resultados/` y la carpeta de salida configurada si es una subcarpeta de la fuente. Si la salida coincide con la carpeta fuente, una nueva importación puede incluir las copias de una ejecución anterior; revisa la lista o usa una salida separada.

La vista previa muestra la composición a la escala de la ventana. El archivo exportado se calcula y compone de nuevo a la resolución real.

## Uso desde la terminal

No requiere una sesión gráfica para PNG, JPEG, WebP y TIFF. Los logos SVG usan el cargador de GdkPixbuf/librsvg, que tampoco necesita una pantalla.

Ancho fijo de 750 píxeles, esquina inferior derecha, margen de 100 píxeles:

```bash
./run.sh batch fotos/panadería --recursive \
  --logo logos/03-logotipo/png/00-logotipo-transparente.png \
  --axis width --unit px --size 750 \
  --position bottom-right --margin 100 \
  --output resultados
```

Alto del 30 % de cada fotografía, centro superior:

```bash
./run.sh batch fotos/panadería --recursive \
  --logo logos/03-logotipo/svg/00-logotipo-transparente.svg \
  --axis height --unit percent --size 30 \
  --position top-center --margin 100 \
  --output resultados --format png
```

Para listar las opciones y los identificadores de las ocho posiciones:

```bash
./run.sh batch --help
```

El comando devuelve 0 si todas las fotos se procesaron y 1 si alguna falló; imprime las rutas guardadas y los errores. Una carpeta no incluye subcarpetas salvo que añadas `--recursive`.

## Verificación

### Compatibilidad con Debian 11

Debian 11 utiliza Python 3.9 y Pillow 8.1. Las anotaciones de tipos se evalúan de forma diferida para permitir esa versión de Python, y el filtro LANCZOS funciona tanto con las constantes de Pillow 8.1 como con la enumeración de versiones posteriores. Puedes utilizar las dependencias del sistema y ejecutar `./run.sh` sin instalar otro Python.

Si una copia anterior falla con `TypeError: unsupported operand type(s) for |`, actualiza los cuatro archivos `photo_watermark/cli.py`, `photo_watermark/storage.py`, `photo_watermark/gui.py` y `photo_watermark/core.py`. También puedes aplicar el parche `compatibilidad-debian11.patch` desde la carpeta de esa copia:

```bash
patch -p1 < compatibilidad-debian11.patch
./run.sh
```

El código de este proyecto ya contiene la corrección; el parche sirve para actualizar una copia anterior.

### Pruebas

Pruebas de cálculo, composición, orientación, persistencia, archivos y terminal:

```bash
/usr/bin/python3 -m unittest discover -s tests -v
```

Prueba de la interfaz en una sesión gráfica (abre una ventana temporal y usa carpetas temporales):

```bash
/usr/bin/python3 tools/gui_smoke.py --screenshot /tmp/photo-watermark-preview.png
```

Las dependencias utilizadas están disponibles en los repositorios de [Debian 11](https://packages.debian.org/bullseye/python3-pil), [Debian 12](https://packages.debian.org/bookworm/python3-gi) y [Debian 13](https://packages.debian.org/trixie/gir1.2-gtk-3.0). El cargador SVG lo proporciona [librsvg2-common](https://packages.debian.org/bookworm/librsvg2-common).

Verificado en este entorno Debian 12 con Python 3.11, GTK 3.24 y Pillow 9.4: 32 pruebas automatizadas, la prueba gráfica, los 79 archivos de la biblioteca y un lote de las 14 fotografías del proyecto. Se comprobó que los originales conservan su contenido y que las copias mantienen las dimensiones orientadas. La ejecución en Debian 13 y en tu sesión de Cinnamon queda pendiente de validación en esos equipos.

También se verificaron las 32 pruebas y la interfaz en un contenedor Debian 11 con los paquetes del sistema: Python 3.9 y Pillow 8.1, usando Xvfb como pantalla de prueba. Para reproducir esa comprobación con Docker desde la carpeta del proyecto:

```bash
docker build --tag photo-watermark-debian11-test --file tools/Dockerfile.debian11 tools
docker run --rm --network none \
  --mount "type=bind,source=$PWD,target=/app,readonly" \
  photo-watermark-debian11-test
```

El contenedor monta el proyecto solo para lectura y usa configuración y archivos de salida temporales.

## Self-Promotion

Si lo desea, puede:

- Visitar mi canal de YouTube [MizaqScreencasts](https://www.youtube.com/MizaqScreencasts)
- Seguirme en [Twitter](https://twitter.com/mismatso)
- Contactarme por [Telegram](https://t.me/mismatso)

## Licencia

[Photo Watermark](https://github.com/mismatso/photo-watermark) © 2026 by [Misael Matamoros](https://t.me/mismatso) está licenciado bajo la **GNU General Public License, version 3 or later (GPL-3.0-or-later)**. El programa se distribuye sin ninguna garantía. Para más detalles, consulta el archivo [LICENSE](LICENSE).

!["GPLv3"](https://www.gnu.org/graphics/gplv3-with-text-136x68.png)
