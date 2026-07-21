# Configuración de latexmk para compilaciones optimizadas
# (Opcional: mejora compilaciones incrementales)

$pdf_mode = 1;                    # Usa pdflatex
$postscript_mode = 0;            # No postscript
$dvi_mode = 0;                    # No DVI
$silent = 0;                      # Muestra output
$jobname = "main";                # Nombre del trabajo

# Sincronización entre editor y PDF (usado por VSCode)
$synctex = 1;

# Máximo de intentos de compilación antes de dar por error
$max_repeat = 3;

# Limpiar archivos auxiliares al finalizar
# (Comentado: LaTeX Workshop maneja esto)
# $clean_ext = "fls fdb_latexmk";
